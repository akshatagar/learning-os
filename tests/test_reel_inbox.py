"""Capture import, the processing queue and the reel list, on an in-memory store
with a fake inbox source, a fake extractor and a fake clock."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from reel_inbox.extractor.pipeline import ExtractionFailed
from reel_inbox.queue import process_pending
from reel_inbox.sources import RemoteCapture, import_captures
from reel_inbox import reels
from reel_inbox.store import Capture, Extraction, make_store

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)

ANSWER = {"summary": "Meta's Byte Latent Transformer drops the tokenizer."}


@pytest.fixture
def sessions():
    return make_store("sqlite://")


def _add(sessions, id_, url=None, status="pending", age_days=0, fail_reason=None, note=None):
    with sessions() as s:
        s.add(Capture(id=id_, url=url or f"https://www.instagram.com/reel/{id_}/",
                      source="test", note=note, status=status, fail_reason=fail_reason,
                      captured_at=NOW - timedelta(days=age_days)))
        s.commit()


def _ready(sessions, id_, age_days=0, note=None):
    _add(sessions, id_, status="ready", age_days=age_days, note=note)
    with sessions() as s:
        s.add(Extraction(capture_id=id_, summary=f"summary of {id_}", model="fake",
                         extracted_at=NOW))
        s.commit()


def _status(sessions, id_):
    with sessions() as s:
        c = s.get(Capture, id_)
        return c.status, c.fail_reason


# --- import ------------------------------------------------------------------

class FakeSource:
    name = "fake"

    def __init__(self, rows):
        self.rows, self.acked = rows, []

    def pull(self):
        return list(self.rows)

    def ack(self, ids):
        self.acked += ids


def test_pulled_captures_land_pending_with_clean_urls_and_are_acked(sessions):
    source = FakeSource([RemoteCapture("r1", "https://www.instagram.com/reel/X/?utm_source=a&srtk=b",
                                       "the paper", NOW)])
    assert import_captures(sessions, source) == 1
    with sessions() as s:
        c = s.get(Capture, "r1")
        assert (c.url, c.note, c.status, c.source) == (
            "https://www.instagram.com/reel/X/", "the paper", "pending", "fake")
    assert source.acked == ["r1"]


def test_a_capture_pulled_twice_is_stored_once(sessions):
    row = RemoteCapture("r1", "https://youtu.be/a", None, NOW)
    import_captures(sessions, FakeSource([row]))
    assert import_captures(sessions, FakeSource([row])) == 0
    with sessions() as s:
        assert len(s.scalars(select(Capture)).all()) == 1


# --- queue -------------------------------------------------------------------

class FakeExtractor:
    model = "fake-model"

    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def extract(self, url):
        self.seen.append(url)
        answer = self.answers[url]
        if isinstance(answer, str):
            raise ExtractionFailed(answer, answer)
        return answer


def _url(id_):
    return f"https://www.instagram.com/reel/{id_}/"


def test_a_run_is_capped_and_takes_the_oldest_first(sessions):
    for i, age in enumerate([1, 5, 3]):
        _add(sessions, f"c{i}", age_days=age)
    extractor = FakeExtractor({_url(f"c{i}"): ANSWER for i in range(3)})
    report = process_pending(sessions, extractor, limit=2, delay=(0, 0), sleep=lambda s: None)
    assert extractor.seen == [_url("c1"), _url("c2")]
    assert report.processed == 2
    assert _status(sessions, "c0") == ("pending", None)
    with sessions() as s:
        e = s.get(Extraction, "c1")
        assert (e.summary, e.model) == (ANSWER["summary"], "fake-model")
    assert _status(sessions, "c1") == ("ready", None)


def test_instagram_fetches_wait_a_random_delay_between_them(sessions):
    _add(sessions, "a", age_days=2)
    _add(sessions, "b", age_days=1)
    _add(sessions, "y", url="https://youtube.com/shorts/y", age_days=0)
    extractor = FakeExtractor({_url("a"): ANSWER, _url("b"): ANSWER,
                               "https://youtube.com/shorts/y": ANSWER})
    sleeps = []
    process_pending(sessions, extractor, delay=(20, 90), sleep=sleeps.append,
                    jitter=lambda lo, hi: 42)
    assert sleeps == [42]


def test_a_login_wall_stops_the_run_and_leaves_the_rest_pending(sessions):
    for i in range(3):
        _add(sessions, f"c{i}", age_days=3 - i)
    extractor = FakeExtractor({_url("c0"): ANSWER, _url("c1"): "login_wall", _url("c2"): ANSWER})
    report = process_pending(sessions, extractor, delay=(0, 0), sleep=lambda s: None)
    assert report.stopped == "login_wall"
    assert _status(sessions, "c1") == ("pending", None)
    assert _status(sessions, "c2") == ("pending", None)


def test_a_failure_is_retried_once_on_the_next_run_then_given_up(sessions):
    _add(sessions, "c0")
    broken = FakeExtractor({_url("c0"): "unavailable"})

    process_pending(sessions, broken, delay=(0, 0), sleep=lambda s: None)
    assert _status(sessions, "c0") == ("pending", "unavailable")

    process_pending(sessions, broken, delay=(0, 0), sleep=lambda s: None)
    assert _status(sessions, "c0") == ("failed", "unavailable")
    assert broken.seen == [_url("c0"), _url("c0")]

    process_pending(sessions, broken, delay=(0, 0), sleep=lambda s: None)
    assert len(broken.seen) == 2  # failed items are never picked up again


def test_a_retry_that_succeeds_clears_the_reason(sessions):
    _add(sessions, "c0", fail_reason="llm_error")
    process_pending(sessions, FakeExtractor({_url("c0"): ANSWER}), delay=(0, 0),
                    sleep=lambda s: None)
    assert _status(sessions, "c0") == ("ready", None)


def test_a_stop_request_ends_the_run_between_items(sessions):
    _add(sessions, "a", age_days=2)
    _add(sessions, "b", age_days=1)
    extractor = FakeExtractor({_url("a"): ANSWER, _url("b"): ANSWER})
    report = process_pending(sessions, extractor, delay=(0, 0), sleep=lambda s: None,
                             should_stop=lambda: len(extractor.seen) >= 1)
    assert extractor.seen == [_url("a")]
    assert report.stopped == "stop_requested"


# --- reels -----------------------------------------------------------------------

def test_the_list_holds_every_undropped_reel_newest_first(sessions):
    _ready(sessions, "old", age_days=9, note="look at the benchmark")
    _add(sessions, "waiting", age_days=1)
    _add(sessions, "broken", status="failed", fail_reason="unavailable", age_days=3)
    _add(sessions, "gone", status="dropped", age_days=0)
    with sessions() as s:
        listed = reels.list_reels(s)
    assert [r["id"] for r in listed] == ["waiting", "broken", "old"]
    old = listed[2]
    assert (old["summary"], old["note"], old["status"]) == (
        "summary of old", "look at the benchmark", "ready")
    assert listed[0]["summary"] is None
    assert listed[1]["fail_reason"] == "unavailable"


def test_drop_hides_a_reel_but_keeps_it(sessions):
    _ready(sessions, "a")
    with sessions() as s:
        reels.drop(s, "a")
        assert reels.list_reels(s) == []
        assert s.get(Capture, "a").status == "dropped"
        assert reels.counts(s)["dropped"] == 1


def test_dropping_an_unknown_reel_is_an_error(sessions):
    with sessions() as s, pytest.raises(LookupError):
        reels.drop(s, "nope")


@pytest.mark.parametrize("url,safe", [
    ("https://www.instagram.com/reel/a/", True),
    ("http://youtu.be/x", True),
    ("file:///C:/x.exe", False),
    ("javascript:alert(1)", False),
    ("ms-settings:", False),
    ("https://", False),
    (None, False),
])
def test_only_web_addresses_are_ever_opened(url, safe):
    assert (reels.safe_web_url(url) is not None) is safe


# --- worker --------------------------------------------------------------------

class Exploding:
    """A source or extractor that must never be touched."""

    name = "exploding"

    def pull(self):
        raise AssertionError("pulled")

    def extract(self, url):
        raise AssertionError("extracted")


def test_processing_never_pulls(sessions):
    from reel_inbox.worker import Worker

    _add(sessions, "c0")
    worker = Worker(sessions, lambda: FakeExtractor({_url("c0"): ANSWER}), Exploding,
                    delay=(0, 0))
    assert worker.start() is True
    worker.join(5)
    assert worker.status()["last_error"] is None
    assert worker.status()["last_pulled"] is None
    assert _status(sessions, "c0") == ("ready", None)


def test_a_pull_never_processes(sessions):
    from reel_inbox.worker import Worker

    source = FakeSource([RemoteCapture("r1", _url("r1"), None, NOW)])
    worker = Worker(sessions, Exploding, lambda: source, delay=(0, 0))
    assert worker.start_pull() is True
    worker.join(5)
    status = worker.status()
    assert (status["last_pulled"], status["last_pull_error"]) == (1, None)
    assert status["last_report"] is None
    assert _status(sessions, "r1") == ("pending", None)


def test_a_pull_and_a_run_never_overlap(sessions):
    import threading

    from reel_inbox.worker import Worker

    _add(sessions, "r1")
    entered, gate = threading.Event(), threading.Event()

    class Slow(FakeExtractor):
        def extract(self, url):
            entered.set()
            gate.wait(5)
            return super().extract(url)

    worker = Worker(sessions, lambda: Slow({_url("r1"): ANSWER}), lambda: FakeSource([]),
                    delay=(0, 0))
    assert worker.start() is True
    assert entered.wait(5)
    assert worker.status()["job"] == "process"
    assert worker.start_pull() is False
    assert worker.start() is False
    gate.set()
    worker.join(5)
    assert worker.status()["job"] is None
    assert worker.start_pull() is True
    worker.join(5)


def test_an_unreachable_inbox_is_a_pull_error(sessions):
    from reel_inbox.worker import Worker

    class Down:
        name = "down"

        def pull(self):
            raise ConnectionError("offline")

    worker = Worker(sessions, Exploding, Down, delay=(0, 0))
    worker.start_pull()
    worker.join(5)
    assert "offline" in worker.status()["last_pull_error"]
    assert worker.status()["last_error"] is None


def test_no_mailbox_pulls_nothing(sessions):
    from reel_inbox.worker import Worker

    worker = Worker(sessions, Exploding, lambda: None, delay=(0, 0))
    worker.start_pull()
    worker.join(5)
    assert (worker.status()["last_pulled"], worker.status()["last_pull_error"]) == (0, None)


# --- the reel being processed --------------------------------------------------

def _set_status(sessions, id_, status):
    with sessions() as s:
        s.get(Capture, id_).status = status
        s.commit()


class ChangesTheNext(FakeExtractor):
    """Extracting the first reel changes the second one's status, as a
    manual write-up or a drop would while the run is going."""

    def __init__(self, sessions, first, second, to):
        super().__init__({_url(first): ANSWER})
        self.sessions, self.first, self.second, self.to = sessions, first, second, to

    def extract(self, url):
        assert url == _url(self.first), "the changed reel must not be extracted"
        _set_status(self.sessions, self.second, self.to)
        return super().extract(url)


def test_a_run_skips_a_reel_that_stopped_being_pending(sessions):
    _add(sessions, "p1", age_days=2)
    _add(sessions, "p2", age_days=1)
    report = process_pending(sessions, ChangesTheNext(sessions, "p1", "p2", "ready"),
                             delay=(0, 0), sleep=lambda _: None)
    assert report.processed == 1
    assert _status(sessions, "p2") == ("ready", None)


def test_a_run_skips_a_reel_dropped_after_the_snapshot(sessions):
    _add(sessions, "p1", age_days=2)
    _add(sessions, "p2", age_days=1)
    process_pending(sessions, ChangesTheNext(sessions, "p1", "p2", "dropped"),
                    delay=(0, 0), sleep=lambda _: None)
    assert _status(sessions, "p2") == ("dropped", None)
    with sessions() as s:
        assert s.get(Extraction, "p2") is None


def test_the_worker_reports_the_reel_it_is_on(sessions):
    import threading

    from reel_inbox.worker import Worker

    _add(sessions, "r1")
    entered, gate = threading.Event(), threading.Event()

    class Slow(FakeExtractor):
        def extract(self, url):
            entered.set()
            gate.wait(5)
            return super().extract(url)

    worker = Worker(sessions, lambda: Slow({_url("r1"): ANSWER}), delay=(0, 0))
    assert worker.status()["current"] is None
    worker.start()
    assert entered.wait(5)
    assert worker.status()["current"] == "r1"
    gate.set()
    worker.join(5)
    assert worker.status()["current"] is None


def test_current_is_cleared_when_the_run_fails(sessions):
    from reel_inbox.worker import Worker

    _add(sessions, "r1")

    class Broken(FakeExtractor):
        def extract(self, url):
            raise RuntimeError("boom")

    worker = Worker(sessions, lambda: Broken({}), delay=(0, 0))
    worker.start()
    worker.join(5)
    assert worker.status()["current"] is None
    assert "processing failed" in worker.status()["last_error"]


def test_a_reel_dropped_during_the_pause_before_it_is_skipped(sessions):
    _add(sessions, "p1", age_days=2)
    _add(sessions, "p2", age_days=1)
    extractor = FakeExtractor({_url("p1"): ANSWER})  # p2 would raise KeyError
    process_pending(sessions, extractor, delay=(0, 0),
                    sleep=lambda _: _set_status(sessions, "p2", "dropped"))
    assert extractor.seen == [_url("p1")]
    assert _status(sessions, "p2") == ("dropped", None)


# --- store upgrade ---------------------------------------------------------------

def test_an_existing_database_gains_the_title_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:  # the schema before titles existed
        db.executescript("""
            CREATE TABLE captures (id VARCHAR PRIMARY KEY, url VARCHAR NOT NULL,
                source VARCHAR NOT NULL, note VARCHAR, captured_at DATETIME NOT NULL,
                status VARCHAR NOT NULL, fail_reason VARCHAR);
            CREATE TABLE extractions (capture_id VARCHAR PRIMARY KEY REFERENCES captures(id),
                summary VARCHAR, model VARCHAR, extracted_at DATETIME NOT NULL);
            INSERT INTO captures VALUES ('o1', 'https://www.instagram.com/reel/o1/', 't', NULL,
                '2026-11-01 00:00:00', 'ready', NULL);
            INSERT INTO extractions VALUES ('o1', 'old summary', 'm', '2026-11-01 00:00:00');
        """)
    stored = make_store(f"sqlite:///{path}")
    with stored() as s:
        [reel] = reels.list_reels(s)
    assert reel["title"] is None
    assert reel["summary"] == "old summary"


# --- written up by hand ------------------------------------------------------------

def test_a_pending_reel_can_be_written_by_hand(sessions):
    _add(sessions, "m1")
    with sessions() as s:
        reels.write_manual(s, "m1", "  uv  ", "Replaces pip.", now=lambda: NOW)
    with sessions() as s:
        e = s.get(Extraction, "m1")
        assert (e.title, e.summary, e.model) == ("uv", "Replaces pip.", "manual")
    assert _status(sessions, "m1") == ("ready", None)


def test_a_failed_reel_can_be_written_by_hand(sessions):
    _add(sessions, "m1", status="failed", fail_reason="login_wall")
    with sessions() as s:
        reels.write_manual(s, "m1", "uv", None)
    assert _status(sessions, "m1") == ("ready", None)


def test_a_ready_reel_cannot_be_written_by_hand(sessions):
    _ready(sessions, "m1")
    with sessions() as s, pytest.raises(reels.NotEditable):
        reels.write_manual(s, "m1", "uv", None)


def test_a_blank_title_is_refused(sessions):
    _add(sessions, "m1")
    with sessions() as s, pytest.raises(ValueError):
        reels.write_manual(s, "m1", "   ", "text")
    assert _status(sessions, "m1") == ("pending", None)


def test_an_empty_description_is_stored_as_none(sessions):
    _add(sessions, "m1")
    with sessions() as s:
        reels.write_manual(s, "m1", "uv", "   ")
    with sessions() as s:
        assert s.get(Extraction, "m1").summary is None


def test_ollama_not_running_stops_the_run_and_fails_nothing(sessions):
    _add(sessions, "o1", age_days=2)
    _add(sessions, "o2", age_days=1)
    extractor = FakeExtractor({_url("o1"): "llm_unavailable", _url("o2"): ANSWER})
    report = process_pending(sessions, extractor, delay=(0, 0), sleep=lambda _: None)
    assert report.stopped == "llm_unavailable"
    assert extractor.seen == [_url("o1")]
    assert _status(sessions, "o1") == ("pending", None)
    assert _status(sessions, "o2") == ("pending", None)
