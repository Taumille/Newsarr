"""Unit checks for the torrent info-hash helpers.

Expected hashes were computed independently with `sha1sum` on the bencoded
info dictionary, so these don't just assert our own encoder against itself.

Run with: .venv/bin/python tests/torrent_hash.py
"""

from __future__ import annotations

from app.services.torrent import _bencode, magnet_info_hash, torrent_info_hash

failures = 0


def check(label: str, actual, expected) -> None:
    global failures
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {actual!r}")
    if not ok:
        print(f"         expected {expected!r}")
        failures += 1


def main() -> None:
    # Simple one-key info dict: sha1("d4:name4:teste")
    torrent = _bencode(
        {b"announce": b"http://tracker.test/announce", b"info": {b"name": b"test"}}
    )
    check(
        "single-key info hash",
        torrent_info_hash(torrent),
        "1ade8a1a581f338e4fce4ce784da3f7d03f81f3a",
    )

    # Multi-key info dict: sha1 of the exact bencoded info dictionary.
    torrent = _bencode(
        {
            b"info": {
                b"length": 1234,
                b"name": b"test",
                b"piece length": 16384,
                b"pieces": b"a" * 20,
            }
        }
    )
    check(
        "multi-key info hash",
        torrent_info_hash(torrent),
        "249e14976e49302a672cc90b293f6ed7556f59ff",
    )

    check(
        "magnet btih extraction",
        magnet_info_hash("magnet:?xt=urn:btih:1ADE8A1A581F338E4FCE4CE784DA3F7D03F81F3A&dn=x"),
        "1ade8a1a581f338e4fce4ce784da3f7d03f81f3a",
    )
    check("magnet without btih", magnet_info_hash("magnet:?dn=x"), "")
    check("garbage torrent data", torrent_info_hash(b"not a torrent"), "")

    print()
    if failures:
        print(f"FAILED: {failures}")
        raise SystemExit(1)
    print("All torrent-hash checks passed ✅")


if __name__ == "__main__":
    main()
