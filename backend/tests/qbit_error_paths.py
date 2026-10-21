"""Verify qBittorrent error handling produces accurate, actionable messages.

Run with: .venv/bin/python tests/qbit_error_paths.py
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.services.qbittorrent import QBittorrentClient, QBittorrentError

BEHAVIOR = {"login_status": 200, "login_body": "Ok.", "version": "5.0.0"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, text="", status=200):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path.startswith("/api/v2/auth/login"):
            self._send(BEHAVIOR["login_body"], BEHAVIOR["login_status"])
        else:
            self._send("", 404)

    def do_GET(self):
        if self.path.startswith("/api/v2/app/version"):
            self._send(BEHAVIOR["version"])
        else:
            self._send("", 404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    cases = [
        ("wrong credentials -> clear message", {"login_status": 200, "login_body": "Fails."}, "Incorrect qBittorrent username or password."),
        ("ip banned 403 -> ban message", {"login_status": 403, "login_body": ""}, "temporarily banned"),
        ("csrf/host 401 -> csrf message", {"login_status": 401, "login_body": ""}, "CSRF"),
        ("qbt 5.2 empty 204 success", {"login_status": 204, "login_body": "", "version": "5.2.0"}, None),
    ]

    failures = 0
    for label, behavior, expected_substring in cases:
        BEHAVIOR.update({"login_status": 200, "login_body": "Ok.", "version": "5.0.0"})
        BEHAVIOR.update(behavior)
        client = QBittorrentClient(url, "admin", "pw")

        async def run():
            return await client.test()

        try:
            result = asyncio.run(run())
            ok = expected_substring is None
            detail = result
        except QBittorrentError as exc:
            ok = expected_substring is not None and expected_substring in str(exc)
            detail = str(exc)

        print(f"  [{'PASS' if ok else 'FAIL'}] {label} -> {detail}")
        if not ok:
            failures += 1

    server.shutdown()
    print()
    if failures:
        print(f"FAILED: {failures}")
        raise SystemExit(1)
    print("All error-path checks passed ✅")


if __name__ == "__main__":
    main()
