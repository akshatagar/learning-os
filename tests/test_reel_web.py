"""The /inbox HTTP surface, on its own app with an in-memory store."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reel_inbox.store import Capture, Extraction, make_store
from reel_inbox.web import make_router

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


@pytest.fixture
def env():
    sessions = make_store("sqlite://")
    with sessions() as s:
        s.add(Capture(id="a", url="https://www.instagram.com/reel/a/", source="t",
                      note="see the repo", captured_at=NOW - timedelta(days=1), status="ready"))
        s.add(Extraction(capture_id="a", summary="uv replaces pip and venv.", model="m",
                         extracted_at=NOW))
        s.add(Capture(id="b", url="https://www.instagram.com/reel/b/", source="t",
                      note=None, captured_at=NOW, status="pending"))
        s.commit()
    opened = []
    app = FastAPI()
    app.include_router(make_router(sessions, open_url=opened.append))
    return TestClient(app), sessions, opened


def test_the_inbox_lists_every_undropped_reel_newest_first(env):
    client, *_ = env
    body = client.get("/inbox").json()
    assert [r["id"] for r in body["reels"]] == ["b", "a"]
    assert body["reels"][1]["summary"] == "uv replaces pip and venv."
    assert body["reels"][1]["note"] == "see the repo"
    assert body["counts"] == {"pending": 1, "ready": 1, "failed": 0, "dropped": 0}


def test_drop_removes_a_reel_from_the_list(env):
    client, *_ = env
    assert client.post("/inbox/reels/a/drop").json() == {"ok": True}
    assert [r["id"] for r in client.get("/inbox").json()["reels"]] == ["b"]
    assert client.post("/inbox/reels/nope/drop").status_code == 404


def test_the_original_reel_opens_in_the_browser(env):
    client, _, opened = env
    assert client.post("/inbox/reels/a/open").json()["opened"] == "https://www.instagram.com/reel/a/"
    assert opened == ["https://www.instagram.com/reel/a/"]
    assert client.post("/inbox/reels/nope/open").status_code == 404


def test_a_non_web_reel_link_is_refused(env):
    client, sessions, opened = env
    with sessions() as s:
        s.get(Capture, "a").url = "file:///C:/x.exe"
        s.commit()
    assert client.post("/inbox/reels/a/open").status_code == 400
    assert opened == []


def test_process_without_a_worker_is_unavailable(env):
    client, *_ = env
    assert client.post("/inbox/process").status_code == 503


class FakeWorker:
    def __init__(self, current=None):
        self.current = current

    def status(self):
        return {"running": self.current is not None, "current": self.current}


def _client(sessions, worker):
    app = FastAPI()
    app.include_router(make_router(sessions, worker=worker, open_url=lambda url: None))
    return TestClient(app)


def test_the_reel_being_processed_cannot_be_dropped(env):
    _, sessions, _ = env
    client = _client(sessions, FakeWorker(current="b"))
    assert client.post("/inbox/reels/b/drop").status_code == 409
    assert [r["id"] for r in client.get("/inbox").json()["reels"]] == ["b", "a"]
    assert client.post("/inbox/reels/a/drop").status_code == 200


def test_manual_entry_marks_a_pending_reel_ready(env):
    client, *_ = env
    response = client.post("/inbox/reels/b/manual", json={"title": "uv", "description": "Fast."})
    assert response.json() == {"ok": True}
    reel = client.get("/inbox").json()["reels"][0]
    assert (reel["status"], reel["title"], reel["summary"]) == ("ready", "uv", "Fast.")


def test_manual_entry_is_refused_for_the_reel_being_processed(env):
    _, sessions, _ = env
    client = _client(sessions, FakeWorker(current="b"))
    assert client.post("/inbox/reels/b/manual", json={"title": "uv"}).status_code == 409


def test_manual_entry_is_refused_for_a_ready_reel(env):
    client, *_ = env
    assert client.post("/inbox/reels/a/manual", json={"title": "uv"}).status_code == 409


def test_manual_entry_needs_a_title(env):
    client, *_ = env
    assert client.post("/inbox/reels/b/manual", json={"title": "  "}).status_code == 400
    assert client.post("/inbox/reels/b/manual", json={}).status_code == 422
    assert client.post("/inbox/reels/nope/manual", json={"title": "uv"}).status_code == 404
