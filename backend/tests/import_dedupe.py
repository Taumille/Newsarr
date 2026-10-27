"""The same issue/file must never be imported twice.

Covers the three ways a duplicate "... (1).pdf" used to appear:

1. a second release for an already-owned issue date,
2. the same torrent grabbed twice (duplicate records),
3. two overlapping ``sync_queue`` runs importing the same completed record.

Run with: .venv/bin/python tests/import_dedupe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="newsarr-dedupe-"))
os.environ["NEWSARR_DATA_DIR"] = str(TMP / "data")

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import DownloadRecord, Publication, TrackedStatus  # noqa: E402
from app.schemas import Release, SettingsUpdate  # noqa: E402
from app.services import settings as settings_service  # noqa: E402
from app.services.grab import grab_release  # noqa: E402
from app.services.library import import_download  # noqa: E402
from app.services.sync import sync_queue  # noqa: E402
from app.services.torrent import _bencode, torrent_info_hash  # noqa: E402

TORRENT_BYTES = _bencode(
    {b"info": {b"length": 10, b"name": b"x", b"piece length": 1, b"pieces": b"a" * 20}}
)
TORRENT_HASH = torrent_info_hash(TORRENT_BYTES)
TORRENTS: list[dict] = []


class MockClient(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, text="", status=200, ct="text/plain", raw: bytes | None = None):
        body = raw if raw is not None else text.encode()
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._send("Ok.")

    def do_GET(self):
        if self.path.startswith("/api/v2/app/version"):
            self._send("5.0.0")
        elif self.path.startswith("/api/v2/torrents/info"):
            self._send(json.dumps(TORRENTS), ct="application/json")
        elif self.path.startswith("/download"):
            self._send(raw=TORRENT_BYTES)
        else:
            self._send("", 404)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def count_files(folder: Path, suffix: str = ".pdf") -> int:
    return len(list(folder.glob(f"*{suffix}"))) if folder.exists() else 0


async def run() -> None:
    server, base = serve(MockClient)
    init_db()

    failures = 0

    def check(label, condition, extra=""):
        nonlocal failures
        print(f"  [{'PASS' if condition else 'FAIL'}] {label} {'' if condition else extra}")
        if not condition:
            failures += 1

    downloads = TMP / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    library = TMP / "library"

    db = SessionLocal()
    settings_service.update(
        db,
        SettingsUpdate(
            qbittorrent_url=base,
            qbittorrent_username="admin",
            qbittorrent_password="pw",
            qbittorrent_save_path=str(downloads),
            library_root=str(library),
            qbittorrent_category="newsarr",
        ),
    )
    publication = Publication(title="Le Canard", slug="le-canard", folder="le-canard")
    db.add(publication)
    db.commit()

    # -- 1. A second release for an already-owned issue ---------------------
    print("Second release for the same issue date...")
    src_a = downloads / "a.pdf"
    src_a.write_bytes(b"issue-a")

    r1 = DownloadRecord(
        publication_id=publication.id,
        title="Le Canard 2026-10-21 A",
        client_hash="hash-a",
        publish_date=datetime(2026, 10, 21, 8, 0),
        content_path=str(src_a),
        status=TrackedStatus.completed,
    )
    db.add(r1)
    db.commit()
    import_download(db, r1)

    r2 = DownloadRecord(
        publication_id=publication.id,
        title="Le Canard 2026-10-21 B (a different rip)",
        client_hash="hash-b",
        publish_date=datetime(2026, 10, 21, 9, 0),
        content_path=str(src_a),
        status=TrackedStatus.completed,
    )
    db.add(r2)
    db.commit()
    import_download(db, r2)

    folder = library / "le-canard"
    check("only one file on disk", count_files(folder) == 1, list(folder.glob("*")))
    check("second record reuses the first file", r2.imported_path == r1.imported_path, r2.imported_path)

    # -- 2. The same torrent grabbed twice ----------------------------------
    print("Same torrent grabbed twice...")
    release = Release(
        guid="guid-dup",
        title="Le Canard 2026-10-23",
        download_url=f"{base}/download",
        protocol="torrent",
    )
    first = await grab_release(db, release, publication.id)
    second = await grab_release(db, release, publication.id)
    check("grab returns the existing record", first.id == second.id, (first.id, second.id))
    total = db.execute(
        select(func.count(DownloadRecord.id)).where(DownloadRecord.client_hash == TORRENT_HASH)
    ).scalar_one()
    check("only one download record for the hash", total == 1, total)

    # -- 3. Overlapping syncs cannot import the same record twice -----------
    print("Two concurrent sync_queue runs...")
    src_c = downloads / "c.pdf"
    src_c.write_bytes(b"issue-c")
    r3 = DownloadRecord(
        publication_id=publication.id,
        title="Le Canard 2026-10-24",
        client_hash="hash-c",
        publish_date=datetime(2026, 10, 24, 8, 0),
        status=TrackedStatus.queued,
    )
    db.add(r3)
    db.commit()
    TORRENTS[:] = [
        {
            "hash": "hash-c",
            "name": "Le Canard 2026-10-24",
            "progress": 1.0,
            "state": "uploading",
            "save_path": str(downloads),
            "content_path": str(src_c),
            "category": "newsarr",
        }
    ]

    db1 = SessionLocal()
    db2 = SessionLocal()
    try:
        await asyncio.gather(sync_queue(db1), sync_queue(db2))
    finally:
        db1.close()
        db2.close()

    # The 2026-10-24 issue lives in its own file; there must be exactly one.
    oct24 = list(folder.glob("*2026-10-24*"))
    check("concurrent sync imported the issue once", len(oct24) == 1, [p.name for p in oct24])
    check("no duplicate-suffixed files at all", not list(library.rglob("*(1)*")), list(library.rglob("*(1)*")))

    db.close()
    server.shutdown()

    print()
    if failures:
        print(f"FAILED: {failures}")
        raise SystemExit(1)
    print("All import-de-duplication checks passed ✅")


if __name__ == "__main__":
    asyncio.run(run())
