"""Canonical identifiers: every AURA id is a UUID v4 in canonical text form.

Single source of truth for generating, validating and normalizing catalogue
identifiers so that API responses, request validation and the persisted schema
all agree on one format:

- random UUID version 4 (RFC 4122/9562), variant RFC 4122;
- lowercase hexadecimal, 8-4-4-4-12, exactly 36 characters ("canonical form").

``canonical()`` accepts the common alternate spellings the standard library
understands (upper case, braces, ``urn:uuid:``, un-hyphenated) and returns the
canonical lowercase form, or ``None`` when the value is not a v4 UUID. Callers
must treat ``None`` as "not an identifier AURA could ever have issued".

The database keeps these values in ``TEXT`` columns and does not add ``CHECK``
constraints: SQLite cannot attach a table-level ``CHECK`` to an existing table,
so a constraint would silently apply to fresh installs only. Validation is
therefore enforced at the application boundary (here, ``api/main.py``) and by
the seed logic in ``api/migrations.py``.
"""
import re
import uuid

# Canonical v4 form. Anchored so a valid UUID cannot be smuggled inside noise.
CANONICAL_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)

# Regex source without the anchors; used in OpenAPI/JSON-schema patterns.
PATTERN = CANONICAL_RE.pattern


def new_id() -> str:
    """Return a fresh canonical UUID v4 string."""
    return str(uuid.uuid4())


def canonical(value: object) -> str | None:
    """Return ``value`` in canonical UUID v4 form, or ``None`` if invalid."""
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        return None
    return str(parsed)


def is_canonical(value: object) -> bool:
    """True when ``value`` is already in canonical UUID v4 form."""
    return isinstance(value, str) and CANONICAL_RE.match(value) is not None
