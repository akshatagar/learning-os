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
            "title": extraction.title if extraction else None,
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


TITLE_LIMIT = 200
DESCRIPTION_LIMIT = 2000


class NotEditable(Exception):
    """Only a reel with no summary yet (pending or failed) can be written up."""


def write_manual(session, capture_id: str, title: str, description: str | None,
                 now=lambda: datetime.now(timezone.utc)) -> None:
    """A title and description written by hand, in place of the LLM summary.
    The reel becomes ready, so no run will process it."""
    capture = session.get(Capture, capture_id)
    if capture is None:
        raise LookupError(capture_id)
    if capture.status not in ("pending", "failed"):
        raise NotEditable(capture.status)
    title = (title or "").strip()
    description = (description or "").strip() or None
    if not title:
        raise ValueError("a title is required")
    if len(title) > TITLE_LIMIT:
        raise ValueError(f"the title is longer than {TITLE_LIMIT} characters")
    if description and len(description) > DESCRIPTION_LIMIT:
        raise ValueError(f"the description is longer than {DESCRIPTION_LIMIT} characters")
    session.merge(Extraction(capture_id=capture_id, title=title, summary=description,
                             model="manual", extracted_at=now()))
    capture.status, capture.fail_reason = "ready", None
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
