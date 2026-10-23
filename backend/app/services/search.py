"""Helpers for Prowlarr queries and filtering search results."""

from __future__ import annotations

import re

from ..models import Publication
from ..schemas import Release
from .qbittorrent import normalize_name

_EXCLUDE_SPLIT = re.compile(r"[,;\n]+")


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


def parse_exclude_terms(value: str) -> list[str]:
    """Split a comma/semicolon/newline list into normalized match terms."""
    out: list[str] = []
    for chunk in _EXCLUDE_SPLIT.split(value or ""):
        normalized = normalize_name(chunk)
        if normalized:
            out.append(normalized)
    return out


def is_excluded(publication: Publication, title: str) -> bool:
    """True when a release title contains one of the publication exclusions."""
    terms = parse_exclude_terms(publication.exclude_keywords or "")
    if not terms:
        return False
    haystack = normalize_name(title)
    return any(term in haystack for term in terms)


def filter_releases(
    publication: Publication, releases: list[Release]
) -> list[Release]:
    """Drop releases whose title contains an excluded word or phrase."""
    terms = parse_exclude_terms(publication.exclude_keywords or "")
    if not terms:
        return releases
    return [
        release
        for release in releases
        if not any(term in normalize_name(release.title) for term in terms)
    ]
