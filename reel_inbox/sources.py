"""Where captures come from. The phone posts to a remote mailbox; the app
pulls from it into the local store, which is the source of truth.

CaptureSource is the seam: Supabase is one implementation, and a Telegram
bot (or anything else that can list and acknowledge messages) can replace
it without the rest of the inbox noticing.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import httpx

from reel_inbox.eval import canonical_url
from reel_inbox.store import Capture

# Pulled per request; more simply waits for the next pull.
PULL_LIMIT = 100


@dataclass(frozen=True)
class RemoteCapture:
    id: str
    url: str
    note: str | None
    captured_at: datetime


class CaptureSource(Protocol):
    name: str

    def pull(self) -> list[RemoteCapture]:
        """Captures waiting in the mailbox, oldest first."""

    def ack(self, ids: list[str]) -> None:
        """Remove these from the mailbox: they are stored locally now."""


def import_captures(session_factory, source: CaptureSource) -> int:
    """Copy waiting captures into the local store, then acknowledge them.

    Acknowledged only after the local commit, so a crash in between means a
    second pull of the same rows, which the id check makes harmless.
    """
    rows = source.pull()
    added = 0
    with session_factory() as session:
        for row in rows:
            if session.get(Capture, row.id) is None:
                session.add(Capture(
                    id=row.id, url=canonical_url(row.url), source=source.name,
                    note=(row.note or "").strip() or None,
                    captured_at=row.captured_at, status="pending",
                ))
                added += 1
        session.commit()
    if rows:
        source.ack([row.id for row in rows])
    return added


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SupabaseSource:
    """Reads and deletes rows in the `captures` table over PostgREST.

    The phone writes with the publishable (anon) key, which RLS limits to
    INSERT. This side needs the secret (service-role) key to read and
    delete, so it lives in Windows Credential Manager, never in a file.
    """

    name = "ios_shortcut"

    def __init__(self, project_url: str, secret_key: str, client: httpx.Client | None = None):
        self.base = project_url.rstrip("/") + "/rest/v1/captures"
        self.headers = {"apikey": secret_key}
        # Only a legacy service_role key (a JWT) also goes in Authorization;
        # a new sb_secret_ key sent there is rejected.
        if secret_key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {secret_key}"
        self.client = client or httpx.Client(timeout=20)

    def pull(self) -> list[RemoteCapture]:
        response = self.client.get(self.base, headers=self.headers, params={
            "select": "id,url,note,created_at", "order": "created_at.asc",
            "limit": str(PULL_LIMIT),
        })
        response.raise_for_status()
        return [RemoteCapture(str(r["id"]), r["url"], r.get("note"), _parse_time(r["created_at"]))
                for r in response.json()]

    def ack(self, ids: list[str]) -> None:
        if not ids:
            return
        response = self.client.delete(self.base, headers=self.headers,
                                      params={"id": f"in.({','.join(ids)})"})
        response.raise_for_status()
