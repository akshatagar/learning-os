"""The stored reels: list them, drop one, and the one link ever opened."""
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from reel_inbox.store import Capture, Extraction


def _aware(moment: datetime) -> datetime:
    # SQLite hands datetimes back naive; every stored one is UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def list_reels(session) -> list[dict]:
    """Every reel not dropped, newest first, with its summary once ready.

    Pending and failed reels are listed too, so nothing captured is ever
    invisible; they simply have no summary yet (or a reason instead)."""
    rows = session.execute(
        select(Capture, Extraction)
        .outerjoin(Extraction, Extraction.capture_id == Capture.id)
        .where(Capture.status != "dropped")
        .order_by(Capture.captured_at.desc(), Capture.id)
    ).all()
    return [
        {
            "id": capture.id,
            "url": capture.url,
            "note": capture.note,
            "status": capture.status,
            "fail_reason": capture.fail_reason,
            "summary": extraction.summary if extraction else None,
            "captured_at": _aware(capture.captured_at).isoformat(),
        }
        for capture, extraction in rows
    ]


def drop(session, capture_id: str) -> None:
    """Hide a reel from the list. Kept in the store, never deleted."""
    capture = session.get(Capture, capture_id)
    if capture is None:
        raise LookupError(capture_id)
    capture.status = "dropped"
    session.commit()


def counts(session) -> dict:
    result = {status: 0 for status in ("pending", "ready", "failed", "dropped")}
    for (status,) in session.execute(select(Capture.status)):
        result[status] = result.get(status, 0) + 1
    return result


def safe_web_url(url: str | None) -> str | None:
    """url if it is an http(s) address with a host, else None.

    The browser is opened through the OS, which would launch a program for
    file:, ms-settings: or any registered scheme. Stored links came from a
    phone over the network, so nothing else is ever handed over."""
    if not url:
        return None
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return None
    return url.strip() if parts.scheme in ("http", "https") and parts.hostname else None
