import re

_TIMING = re.compile(r"^\d{2}:\d{2}(:\d{2})?[.,]\d{3}\s+-->")
_HEADER = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE\b)")
_TAG = re.compile(r"<[^>]+>")


def vtt_to_text(vtt: str) -> str | None:
    """Plain text from WebVTT (or SRT) captions.

    Auto-captions roll: each cue repeats the end of the previous one before
    adding new words. Each line is appended minus its longest overlap with
    what is already there, so the rolling repeats disappear.
    """
    out: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or _TIMING.match(line) or _HEADER.match(line):
            continue
        words = _TAG.sub("", line).split()
        overlap = next(
            (k for k in range(min(len(out), len(words)), 0, -1)
             if out[-k:] == words[:k]),
            0,
        )
        out.extend(words[overlap:])
    return " ".join(out) or None
