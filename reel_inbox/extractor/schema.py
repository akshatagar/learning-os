"""The one shape extract() returns, and the repair applied to model output."""

REFERENT_TYPES = ("paper", "tool", "repo", "technique", "claim", "person", "other")

# Order is the output order.
FIELDS = (
    "referent",
    "referent_type",
    "search_query",
    "source_url_guess",
    "confidence",
    "why_explorable",
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "referent": {"type": ["string", "null"]},
        "referent_type": {"type": "string", "enum": list(REFERENT_TYPES)},
        "search_query": {"type": "string"},
        "source_url_guess": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "why_explorable": {"type": "string"},
    },
    "required": list(FIELDS),
}


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def normalize(raw: dict) -> dict:
    """Coerce a model answer into FIELDS. Never invents a value: anything
    malformed becomes None (or "other" for the type)."""
    kind = (_text(raw.get("referent_type")) or "").lower()
    url = _text(raw.get("source_url_guess"))
    if url and not url.lower().startswith(("http://", "https://")):
        url = None
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "referent": _text(raw.get("referent")),
        "referent_type": kind if kind in REFERENT_TYPES else "other",
        "search_query": _text(raw.get("search_query")),
        "source_url_guess": url,
        "confidence": confidence,
        "why_explorable": _text(raw.get("why_explorable")),
    }
