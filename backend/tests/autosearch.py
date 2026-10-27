"""Tests the automatic-search / RSS-sync decision logic.

Mock Prowlarr returns a mix of relevant, irrelevant, excluded and too-old
releases; the test checks what gets grabbed, that exclusions are respected,
that grabs are de-duplicated, that the recent window and the max-grabs cap are
respected, and that we never re-download an older issue once a newer one has
been grabbed.

Run with: .venv/bin/python tests/autosearch.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TMP = Path(tempfile.mkdtemp(prefix="newsarr-auto-"))
os.environ["NEWSARR_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DownloadRecord  # noqa: E402
from app.services.torrent import _bencode  # noqa: E402

TORRENT_BYTES = _bencode(
    {b"info": {b"length": 10, b"name": b"x", b"piece length": 1, b"pieces": b"a" * 20}}
)
DOWNLOAD_URL = ""
RELEASES: list[dict] = []


def rel(days: float = 0, hours: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def set_releases(items: list[tuple[str, str, str]]) -> None:
    global RELEASES
    RELEASES = [
        {
            "guid": guid,
            "title": title,
            "indexerId": 1,
            "indexer": "Mock",
            "size": 100,
            "downloadUrl": f"{DOWNLOAD_URL}?guid={guid}",
            "publishDate": published,
            "protocol": "torrent",
            "categories": [{"id": 7010, "name": "Books/Mags"}],
        }
        for title, guid, published in items
    ]


class MockProwlarr(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/v1/search"):
            self._json(RELEASES)
        elif self.path.startswith("/download"):
            # Give each release its own torrent so info hashes are distinct,
            # like real releases from an indexer.
            query = parse_qs(urlparse(self.path).query)
            guid = (query.get("guid") or ["x"])[0]
            blob = _bencode(
                {
                    b"info": {
                        b"length": 10,
                        b"name": guid.encode(),
                        b"piece length": 1,
                        b"pieces": b"a" * 20,
                    }
                }
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
        else:
            self.send_response(404)
            self.end_headers()


class MockQbittorrent(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, text="", status=200, ct="text/plain"):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._send("Ok." if "add" in self.path else "Ok.")

    def do_GET(self):
        if self.path.startswith("/api/v2/app/version"):
            self._send("5.0.0")
        elif self.path.startswith("/api/v2/torrents/info"):
            self._send("[]", ct="application/json")
        else:
            self._send("", 404)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def clear_records() -> None:
    session = SessionLocal()
    try:
        session.execute(delete(DownloadRecord))
        session.commit()
    finally:
        session.close()


def main() -> None:
    prowlarr_server, prowlarr_url = serve(MockProwlarr)
    qbit_server, qbit_url = serve(MockQbittorrent)
    global DOWNLOAD_URL
    DOWNLOAD_URL = f"{prowlarr_url}/download"

    failures = 0

    def check(label, condition, extra=""):
        nonlocal failures
        print(f"  [{'PASS' if condition else 'FAIL'}] {label} {'' if condition else extra}")
        if not condition:
            failures += 1

    with TestClient(app) as client:
        client.put(
            "/api/v1/settings",
            json={
                "prowlarr_url": prowlarr_url,
                "prowlarr_api_key": "k",
                "qbittorrent_url": qbit_url,
                "qbittorrent_username": "admin",
                "qbittorrent_password": "pw",
                "library_root": str(TMP / "library"),
                "rss_sync_enabled": True,
                "rss_recent_hours": 72,
                "auto_search_enabled": True,
                "auto_search_recent_days": 30,
                "auto_search_max_grabs": 3,
            },
        )
        pub = client.post(
            "/api/v1/publications",
            json={
                "title": "The Guardian",
                "exclude_keywords": "magazine, sport",
                "categories": "7010",
            },
        ).json()

        new_issue = ("The Guardian 2026 issue PDF", "guid-new", rel(hours=1))
        mid_issue = ("The Guardian older issue PDF", "guid-mid", rel(days=10))
        old_issue = ("The Guardian ancient issue PDF", "guid-old", rel(days=60))
        irrelevant = ("Cooking Weekly 2026", "guid-irrelevant", rel(hours=1))
        excluded = ("The Guardian Magazine 2026", "guid-excluded", rel(hours=1))

        # -- RSS sync: only very recent, relevant issues ---------------------
        print("RSS sync (72h window)...")
        set_releases([new_issue, mid_issue, old_issue, irrelevant, excluded])
        clear_records()
        r = client.post("/api/v1/tasks/rss-sync").json()
        check("grabbed exactly the recent issue", r["grabbed"] == 1, r)
        titles = [x["title"] for x in client.get("/api/v1/queue").json()["records"]]
        check("correct issue grabbed", titles == [new_issue[0]], titles)

        # -- Auto search: catches up within the look-back window -------------
        print("Auto search (30d window)...")
        clear_records()
        r = client.post("/api/v1/tasks/auto-search").json()
        check("grabbed mid + new issues", r["grabbed"] == 2, r)

        # -- Idempotent ------------------------------------------------------
        print("Auto search is idempotent...")
        r = client.post("/api/v1/tasks/auto-search").json()
        check("second run grabs nothing", r["grabbed"] == 0, r)

        # -- max_grabs cap ---------------------------------------------------
        print("Max grabs cap...")
        clear_records()
        client.put("/api/v1/settings", json={"auto_search_max_grabs": 1})
        r = client.post("/api/v1/tasks/auto-search").json()
        check("capped at 1 grab", r["grabbed"] == 1, r)
        client.put("/api/v1/settings", json={"auto_search_max_grabs": 3})

        # -- Never fetch an issue older than the newest we already have ------
        print("Cutoff at newest existing issue...")
        clear_records()
        client.post("/api/v1/publications/%d/auto-search" % pub["id"])  # baseline grab
        r = client.post("/api/v1/tasks/auto-search").json()
        check("no older issue re-grabbed", r["grabbed"] == 0, r)

    prowlarr_server.shutdown()
    qbit_server.shutdown()

    print()
    if failures:
        print(f"FAILED: {failures}")
        raise SystemExit(1)
    print("All auto-search checks passed ✅")


if __name__ == "__main__":
    main()
