"""Minimal BitTorrent metainfo helpers.

The info hash uniquely identifies a torrent and is what qBittorrent reports as
``hash``. Computing it ourselves means we never have to guess by name -- this is
how Sonarr/Radarr reliably track a grabbed download.
"""

from __future__ import annotations

import hashlib
import re

_BTIH_RE = re.compile(r"btih:([0-9a-fA-F]{40})", re.IGNORECASE)
_HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def magnet_info_hash(magnet_url: str) -> str:
    """Extract the info hash from a magnet link, or '' if absent."""
    match = _BTIH_RE.search(magnet_url or "")
    return match.group(1).lower() if match else ""


def _bdecode(data: bytes, idx: int = 0):
    char = data[idx : idx + 1]
    if char == b"i":  # integer
        end = data.index(b"e", idx)
        return int(data[idx + 1 : end]), end + 1
    if char == b"l":  # list
        idx += 1
        items = []
        while data[idx : idx + 1] != b"e":
            value, idx = _bdecode(data, idx)
            items.append(value)
        return items, idx + 1
    if char == b"d":  # dictionary
        idx += 1
        result: dict[bytes, object] = {}
        while data[idx : idx + 1] != b"e":
            key, idx = _bdecode(data, idx)
            value, idx = _bdecode(data, idx)
            result[key] = value
        return result, idx + 1
    # byte string: <length>:<data>
    colon = data.index(b":", idx)
    length = int(data[idx:colon])
    start = colon + 1
    return data[start : start + length], start + length


def _bencode(obj) -> bytes:
    if isinstance(obj, bool):  # bool is an int subclass; not valid in bencode here
        raise TypeError("bool is not bencodable")
    if isinstance(obj, int):
        return b"i%de" % obj
    if isinstance(obj, str):
        obj = obj.encode()
    if isinstance(obj, bytes):
        return b"%d:%s" % (len(obj), obj)
    if isinstance(obj, (list, tuple)):
        return b"l" + b"".join(_bencode(v) for v in obj) + b"e"
    if isinstance(obj, dict):
        out = b"d"
        for key in sorted(obj.keys()):
            kb = key if isinstance(key, bytes) else str(key).encode()
            out += _bencode(kb) + _bencode(obj[key])
        return out + b"e"
    raise TypeError(f"cannot bencode {type(obj)!r}")


def torrent_info_hash(data: bytes) -> str:
    """SHA-1 of the bencoded ``info`` dictionary from a .torrent file.

    Returns '' if the data isn't a parseable torrent.
    """
    try:
        meta, _ = _bdecode(data, 0)
    except (ValueError, IndexError, TypeError):
        return ""
    if not isinstance(meta, dict):
        return ""
    info = meta.get(b"info")
    if not isinstance(info, dict):
        return ""
    return hashlib.sha1(_bencode(info)).hexdigest()


def is_info_hash(value: str) -> bool:
    return bool(_HEX40_RE.match(value or ""))
