"""Helper for turning a Publication into a Prowlarr query."""

from __future__ import annotations

from ..models import Publication


def build_query(publication: Publication, extra: str = "") -> str:
    parts = [publication.title.strip()]
    if publication.keywords.strip():
        parts.append(publication.keywords.strip())
    if extra.strip():
        parts.append(extra.strip())
    return " ".join(parts)


def parse_categories(categories: str) -> list[int]:
    out: list[int] = []
    for chunk in (categories or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.append(int(chunk))
    return out
