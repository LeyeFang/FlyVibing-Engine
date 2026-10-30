"""Provider signatures for node packs and Example projects.

The UI renders these as muted ``@Provider`` labels. Signatures are intentionally
not inferred from local paths: a community extension must opt in explicitly so
it can never be presented as ``@Official`` by accident.
"""

from __future__ import annotations

DEFAULT_PROVIDER = "@Official"
COMMUNITY_PROVIDER = "@Community"
_MAX_LEN = 32


def normalize_provider(value: object, default: str = DEFAULT_PROVIDER) -> str:
    """Return a display-safe ``@Provider`` token.

    Accepts ``"Official"`` or ``"@Official"``. Empty values fall back to
    ``default``; malformed values (spaces, path separators, too long) also fall
    back rather than leaking arbitrary text into the editor chrome.
    """
    raw = str(value or "").strip()
    if not raw:
        return default
    if not raw.startswith("@"):
        raw = "@" + raw
    body = raw[1:]
    if not body or len(body) > _MAX_LEN:
        return default
    if any(ch.isspace() or ch in "/\\" for ch in body):
        return default
    return raw
