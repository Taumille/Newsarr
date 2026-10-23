"""Per-issue auto-grab test: pick the release with the most seeders.

Spins up mock Prowlarr and qBittorrent servers, configures Newsarr, creates a
weekly publication, and exercises POST /issues/{id}/auto-grab.

Run with:  PYTHONPATH=. .venv/bin/python tests/issue_auto_grab.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="newsarr-auto-grab-"))
os.environ["NEWSARR_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import Release  # noqa: E402
from app.services.issues import pick_most_seeded  # noqa: E402

ISSUE_DATE = "2020-01-15"
MAGNET = "magnet:?xt=urn:btih:" + "b" * 40
RELEASES: list[dict] = [
    {
        "guid": "low",
        "title": "Le Canard Enchaine 2020-01-15 PDF",
        "indexerId": 1,
        "indexer": "Mock",
        "size": 1000,
        "downloadUrl": "",
        "magnetUrl": "magnet:?xt=urn:btih:" + "a" * 40,
        "infoUrl": "",
        "publishDate": "2020-01-15T06:00:00Z",
        "protocol": "torrent",
        "categories": [{"id": 7010, "name": "Books/Mags"}],
        "seeders": 3,
    },
    {
        "guid": "high",
        "title": "Le Canard Enchaine 2020-01-15 EPUB",
        "indexerId": 1,
        "indexer": "Mock",
        "size": 2000,
        "downloadUrl": "",
        "magnetUrl": MAGNET,
        "infoUrl": "",
        "publishDate": "2020-01-15T06:00:00Z",
        "protocol": "torrent",
        "categories": [{"id": 7010, "name": "Books/Mags"}],
        "seeders": 42,
    },
]

STATE = {"adds": 0}


class MockProwlarr(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        body = json.dumps(RELEASES).encode() if self.path.startswith("/api/v1/search") else b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MockQBittorrent(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _reply(self, text: str, content_type: str = "text/plain"):
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path.startswith("/api/v2/auth/login"):
            self._reply("Ok.")
        elif self.path.startswith("/api/v2/torrents/add"):
            STATE["adds"] += 1
            self._reply("Ok.")
        else:
            self._reply("")

    def do_GET(self):
        if self.path.startswith("/api/v2/app/version"):
            self._reply("5.0")
        elif self.path.startswith("/api/v2/torrents/info"):
            self._reply("[]", "application/json")
        else:
            self._reply("")


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> None:
    failures: list[str] = []

    def check(label: str, condition: bool, extra: object = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label} {extra if not condition else ''}")
        if not condition:
            failures.append(label)

    print("Seeder selection helper...")
    releases = [
        Release(title="low", seeders=2, magnet_url="magnet:?xt=urn:btih:" + "1" * 40),
        Release(title="none", seeders=None, magnet_url="magnet:?xt=urn:btih:" + "2" * 40),
        Release(title="high", seeders=99, magnet_url="magnet:?xt=urn:btih:" + "3" * 40),
    ]
    check("picks highest seeders", pick_most_seeded(releases).title == "high")
    check("no releases -> None", pick_most_seeded([]) is None)

    prowlarr, prowlarr_url = serve(MockProwlarr)
    qbittorrent, qbittorrent_url = serve(MockQBittorrent)

    try:
        with TestClient(app) as client:
            r = client.put(
                "/api/v1/settings",
                json={
                    "prowlarr_url": prowlarr_url,
                    "prowlarr_api_key": "test",
                    "qbittorrent_url": qbittorrent_url,
                    "qbittorrent_username": "user",
                    "qbittorrent_password": "pass",
                    "library_root": str(TMP / "library"),
                },
            )
            check("settings saved", r.status_code == 200, r.text)

            r = client.post(
                "/api/v1/publications",
                json={
                    "title": "Le Canard Enchaine",
                    "frequency": "weekly",
                    "weekday": 2,
                    "start_date": "2020-01-01",
                    "categories": "7010",
                },
            )
            check("publication created", r.status_code == 201, r.text)
            publication = r.json()

            r = client.get(
                f"/api/v1/publications/{publication['id']}/issues"
                f"?from_date={ISSUE_DATE}&to_date={ISSUE_DATE}"
            )
            issues = r.json()["issues"]
            check("target issue found", len(issues) == 1, r.text)
            issue = issues[0]

            r = client.post(f"/api/v1/issues/{issue['id']}/auto-grab")
            check("auto-grab ok", r.status_code == 200, r.text)
            record = r.json()
            check("grabbed most seeded release", record["title"].endswith("EPUB"), record)
            check("client add called once", STATE["adds"] == 1, STATE)
            check("stored correct hash", record["client_hash"] == "b" * 40, record)

            r = client.get(f"/api/v1/issues/{issue['id']}")
            check("issue marked grabbed", r.json()["status"] == "grabbed", r.text)

            r = client.post(f"/api/v1/issues/{issue['id']}/auto-grab")
            check("second auto-grab rejected", r.status_code == 409, r.text)

            print("No matching release...")
            RELEASES.clear()
            r = client.get(
                f"/api/v1/publications/{publication['id']}/issues?status=expected&limit=1"
            )
            next_issue = r.json()["issues"][0]
            r = client.post(f"/api/v1/issues/{next_issue['id']}/auto-grab")
            check("no release -> 404", r.status_code == 404, r.text)
    finally:
        prowlarr.shutdown()
        qbittorrent.shutdown()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        raise SystemExit(1)
    print("All auto-grab checks passed ✅")


if __name__ == "__main__":
    main()
