from __future__ import annotations

import re
import unicodedata

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_SLUGS = frozenset(
    {"api", "admin", "login", "welcome", "health", "assets", "docs", "redoc"}
)


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if not slug:
        raise ValueError("Name must contain at least one letter or number")
    return slug


def validate_slug(slug: str) -> None:
    if len(slug) < 2 or len(slug) > 48:
        raise ValueError("Slug must be 2–48 characters")
    if not SLUG_RE.match(slug):
        raise ValueError("Slug may only contain lowercase letters, numbers, and hyphens")
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Slug '{slug}' is reserved")


def normalize_slug(raw: str) -> str:
    slug = slugify(raw.strip())
    validate_slug(slug)
    return slug
