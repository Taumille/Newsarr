"""Newsarr FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import publications, queue, search, settings as settings_api, system, tasks
from .config import settings as bootstrap
from .database import SessionLocal, init_db
from .services import settings as settings_service
from .services.autosearch import run_auto_search, run_rss_sync
from .services.sync import sync_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("newsarr")

# How often the scheduler wakes up to check what is due.
_SCHEDULER_TICK_SECONDS = 5


async def _scheduler() -> None:
    """Run the queue reconcile, RSS sync and auto-search on their own cadences."""
    last = {"queue": 0.0, "rss": 0.0, "auto": 0.0}
    while True:
        await asyncio.sleep(_SCHEDULER_TICK_SECONDS)
        db = SessionLocal()
        try:
            cfg = settings_service.get_map(db)
            now = time.monotonic()

            if now - last["queue"] >= bootstrap.queue_poll_seconds:
                last["queue"] = now
                await sync_queue(db)

            rss_interval = max(60, settings_service.as_int(cfg, "rss_sync_interval_minutes", 30) * 60)
            if settings_service.as_bool(cfg, "rss_sync_enabled", True) and now - last["rss"] >= rss_interval:
                last["rss"] = now
                await run_rss_sync(db)

            auto_interval = max(60, settings_service.as_int(cfg, "auto_search_interval_minutes", 360) * 60)
            if settings_service.as_bool(cfg, "auto_search_enabled", True) and now - last["auto"] >= auto_interval:
                last["auto"] = now
                await run_auto_search(db)
        except Exception:  # pragma: no cover - keep the loop alive
            logger.exception("Scheduler tick failed")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_scheduler())
    logger.info("Newsarr %s starting (data dir: %s)", __version__, bootstrap.data_dir)
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Newsarr", version=__version__, lifespan=lifespan)

# The Vite dev server runs on another origin; allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_routers = [
    system.router,
    publications.router,
    search.router,
    queue.router,
    settings_api.router,
    tasks.router,
]
for router in api_routers:
    app.include_router(router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": __version__}


# --------------------------------------------------------------------------- #
# Serve the built React frontend (production). During development use Vite.
# --------------------------------------------------------------------------- #
if bootstrap.frontend_dir.exists():
    assets = bootstrap.frontend_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = bootstrap.frontend_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(bootstrap.frontend_dir / "index.html")
