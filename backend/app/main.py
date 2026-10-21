"""Newsarr FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import publications, queue, search, settings as settings_api, system
from .config import settings as bootstrap
from .database import init_db
from .services.sync import sync_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("newsarr")


async def _queue_loop() -> None:
    """Periodically reconcile our queue with the download client."""
    while True:
        await asyncio.sleep(bootstrap.queue_poll_seconds)
        try:
            await sync_once()
        except Exception:  # pragma: no cover - keep the loop alive
            logger.exception("Background queue sync failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_queue_loop())
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
