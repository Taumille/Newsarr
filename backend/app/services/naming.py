"""Filename / folder helpers."""

from __future__ import annotations

import re
import unicodedata

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = _INVALID.sub("", value)
    value = re.sub(r"\s+", "-", value.strip())
    value = re.sub(r"-+", "-", value).strip("-")
    return value.lower() or "untitled"


def sanitize_filename(value: str) -> str:
    value = _INVALID.sub("_", value or "").strip().strip(".")
    return value or "untitled"


def apply_template(template: str, *, title: str, date: str, ext: str = "") -> str:
    """Expand a naming template like ``{title} - {date}``."""
    name = template or "{title} - {date}"
    name = name.replace("{title}", title).replace("{date}", date)
    name = sanitize_filename(name)
    if ext and not name.lower().endswith(ext.lower()):
        name = f"{name}{ext}"
    return name
