"""The one shape extract() returns, and the repair applied to model output."""

# Order is the output order.
FIELDS = ("summary",)

# Long enough for two or three sentences, short enough for a list row.
SUMMARY_LIMIT = 600

JSON_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": list(FIELDS),
}


def normalize(raw: dict) -> dict:
    """Coerce a model answer into FIELDS. Never invents a value: anything
    empty or malformed becomes None."""
    value = raw.get("summary") if isinstance(raw, dict) else None
    text = " ".join(value.split()) if isinstance(value, str) else ""
    return {"summary": text[:SUMMARY_LIMIT] or None}
