import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Concept
from web.jobs import JobRegistry


def _factory(engine):
    return lambda: Session(engine)


def _wait(job, timeout=5.0):
    job.thread.join(timeout)
    assert job.status != "running", "job did not finish in time"


def test_start_returns_a_running_job(engine):
    registry = JobRegistry(_factory(engine))
    started = threading.Event()

    def work(session):
        started.wait(2.0)

    job = registry.start("ingest", work)

    assert job.kind == "ingest"
    assert job.status == "running"
    assert registry.running_kinds() == {"ingest"}
    started.set()
    _wait(job)


def test_a_completed_job_reports_done_and_frees_its_kind(engine):
    registry = JobRegistry(_factory(engine))

    job = registry.start("ingest", lambda session: None)
    _wait(job)

    assert job.status == "done"
    assert registry.running_kinds() == set()


def test_a_failing_job_records_the_error(engine):
    registry = JobRegistry(_factory(engine))

    def explode(session):
        raise RuntimeError("model exploded")

    job = registry.start("ingest", explode)
    _wait(job)

    assert job.status == "failed"
    assert "model exploded" in job.error
    assert registry.running_kinds() == set()


def test_starting_a_running_kind_returns_the_same_job(engine):
    """Two runs of one kind would race for the same rows to no benefit.

    Every batch loop selects rows by "not yet handled", so a second run picks
    up whatever the first has not committed yet.
    """
    registry = JobRegistry(_factory(engine))
    release = threading.Event()

    first = registry.start("ingest", lambda session: release.wait(2.0))
    second = registry.start("ingest", lambda session: release.wait(2.0))

    assert second is first
    release.set()
    _wait(first)


def test_different_kinds_run_concurrently(engine):
    registry = JobRegistry(_factory(engine))
    release = threading.Event()

    ingest = registry.start("ingest", lambda session: release.wait(2.0))
    ideas = registry.start("generate-ideas", lambda session: release.wait(2.0))

    assert registry.running_kinds() == {"ingest", "generate-ideas"}
    release.set()
    _wait(ingest)
    _wait(ideas)


def test_get_finds_a_job_by_id(engine):
    registry = JobRegistry(_factory(engine))

    job = registry.start("ingest", lambda session: None)
    _wait(job)

    assert registry.get(job.id) is job
    assert registry.get("nonexistent") is None


def test_each_job_thread_gets_its_own_session(engine):
    """The invariant that fails silently.

    A SQLAlchemy Session is not thread-safe. Two jobs sharing one would
    corrupt state only under concurrency, in a way that is very hard to
    attribute later. Both jobs here write, and both writes must land.
    """
    registry = JobRegistry(_factory(engine))
    seen = {}
    both_started = threading.Barrier(2, timeout=5.0)

    def make(name):
        def work(session):
            seen[name] = id(session)
            session.add(Concept(name=name))
            session.commit()
            both_started.wait()
        return work

    first = registry.start("ingest", make("from-ingest"))
    second = registry.start("generate-ideas", make("from-ideas"))
    _wait(first)
    _wait(second)

    assert first.status == "done"
    assert second.status == "done"
    assert seen["from-ingest"] != seen["from-ideas"]

    with Session(engine) as session:
        names = {concept.name for concept in session.scalars(select(Concept))}
    assert {"from-ingest", "from-ideas"} <= names


def test_subscribers_receive_published_events(engine):
    registry = JobRegistry(_factory(engine))
    stream = registry.subscribe()

    registry.publish({"type": "test"})

    assert stream.get(timeout=1.0) == {"type": "test"}


def test_a_finished_job_publishes_its_status(engine):
    registry = JobRegistry(_factory(engine))
    stream = registry.subscribe()

    job = registry.start("ingest", lambda session: None)
    _wait(job)

    assert stream.get(timeout=1.0) == {
        "type": "job", "id": job.id, "kind": "ingest", "status": "running"
    }
    assert stream.get(timeout=1.0) == {
        "type": "job", "id": job.id, "kind": "ingest", "status": "done"
    }


def test_a_job_records_when_it_started(engine):
    registry = JobRegistry(_factory(engine))
    before = time.monotonic()

    job = registry.start("slow", lambda session: None)

    assert before <= job.started_at <= time.monotonic()
