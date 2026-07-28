from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from storage.models import AdjudicationLog, Concept, MergeQueue
from web.app import create_app
from web.jobs import JobRegistry


def test_health_reports_ok(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_state_returns_every_stage(engine, collection):
    client = TestClient(create_app(engine, collection))

    payload = client.get("/state").json()

    assert len(payload["stages"]) == 10
    assert payload["stages"][0]["id"] == "ingest"


def test_state_reflects_rows_written_after_startup(engine, collection):
    """The session is per request, so a stale snapshot would be a real bug."""
    client = TestClient(create_app(engine, collection))
    assert client.get("/state").json()["stages"][2]["lamp"] == "unlit"

    with Session(engine) as session:
        session.add(MergeQueue(candidate_name="Attention", status="pending"))
        session.commit()

    stages = client.get("/state").json()["stages"]
    queue = next(stage for stage in stages if stage["id"] == "queue")
    assert queue["lamp"] == "holding"
    assert queue["count"] == 1


def test_events_route_is_registered(engine, collection):
    """Registration only - the stream cannot be driven through TestClient.

    This Starlette version buffers the whole response body before returning,
    so requesting an endless stream hangs before the headers arrive. It is a
    limitation of the test transport, not of the endpoint: verified against a
    real uvicorn server, /events returns 200 text/event-stream, delivers a
    hello snapshot followed by job transitions, and drops its subscriber on
    disconnect.

    Delivery itself is covered deterministically by the registry's own
    publish/subscribe tests in tests/test_web_jobs.py.
    """
    app = create_app(engine, collection)

    assert "/events" in {route.path for route in app.routes}


def test_starting_an_unknown_kind_is_rejected(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/jobs/not-a-real-kind")

    assert response.status_code == 404


def test_starting_a_job_returns_its_id(engine, collection):
    registry = JobRegistry(lambda: Session(engine))
    app = create_app(engine, collection, registry=registry)
    app.state.job_kinds = {"slow": lambda session: None}
    client = TestClient(app)

    payload = client.post("/jobs/slow").json()

    assert payload["kind"] == "slow"
    assert payload["status"] in {"running", "done"}
    assert registry.get(payload["job_id"]) is not None


def test_job_status_is_readable_by_id(engine, collection):
    app = create_app(engine, collection)
    app.state.job_kinds = {"slow": lambda session: None}
    client = TestClient(app)

    job_id = client.post("/jobs/slow").json()["job_id"]

    payload = client.get(f"/jobs/{job_id}").json()
    assert payload["job_id"] == job_id


def test_a_failed_job_reports_why(engine, collection):
    """A failure the surface cannot name is indistinguishable from a hang.

    The registry already records the error; without it on the wire a failed
    job reads as "not running" and the operator has nowhere to look.
    """
    registry = JobRegistry(lambda: Session(engine))
    app = create_app(engine, collection, registry=registry)

    def explode(session):
        raise RuntimeError("model exploded")

    app.state.job_kinds = {"doomed": explode}
    client = TestClient(app)

    job_id = client.post("/jobs/doomed").json()["job_id"]
    registry.get(job_id).thread.join(5.0)

    payload = client.get(f"/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert "model exploded" in payload["error"]


def test_a_successful_job_reports_no_error(engine, collection):
    app = create_app(engine, collection)
    app.state.job_kinds = {"fine": lambda session: None}
    client = TestClient(app)

    job_id = client.post("/jobs/fine").json()["job_id"]

    assert client.get(f"/jobs/{job_id}").json()["error"] is None


def test_reading_an_unknown_job_is_a_404(engine, collection):
    client = TestClient(create_app(engine, collection))

    assert client.get("/jobs/nonexistent").status_code == 404


def test_the_app_carries_the_collection(engine, collection):
    """The queue gate resolves entries, which writes to Chroma.

    Wiring it at construction keeps the endpoints from reaching for a client
    of their own, which would be a second authority over the same store.
    """
    app = create_app(engine, collection)

    assert app.state.collection is collection


def test_queue_next_is_empty_when_nothing_is_pending(engine, collection):
    client = TestClient(create_app(engine, collection))

    payload = client.get("/queue/next").json()

    assert payload == {"entry": None, "neighbors": [], "remaining": 0}


def test_queue_next_returns_the_entry_and_its_neighbors(engine, collection):
    with Session(engine) as session:
        concept = Concept(name="retrieval augmentation")
        session.add(concept)
        session.flush()
        collection.add(ids=[str(concept.id)], documents=["retrieval augmentation"])
        log = AdjudicationLog(
            candidate_name="retrieval-augmented generation", model_decision="match"
        )
        session.add(log)
        session.flush()
        session.add_all([
            MergeQueue(
                candidate_name="retrieval-augmented generation",
                candidate_category="technique",
                llm_confidence=0.78,
                llm_reasoning="Close, but names a pipeline rather than a step.",
                status="pending",
                adjudication_log_id=log.id,
            ),
            MergeQueue(candidate_name="beam search", status="pending"),
        ])
        session.commit()

    payload = TestClient(create_app(engine, collection)).get("/queue/next").json()

    assert payload["entry"]["candidate_name"] == "retrieval-augmented generation"
    assert payload["entry"]["candidate_category"] == "technique"
    assert payload["entry"]["llm_confidence"] == 0.78
    assert payload["entry"]["llm_reasoning"].startswith("Close, but")
    assert payload["entry"]["model_decision"] == "match"
    assert payload["neighbors"][0]["name"] == "retrieval augmentation"
    assert payload["remaining"] == 2


def test_queue_next_has_a_null_decision_without_an_adjudication_log(
    engine, collection
):
    with Session(engine) as session:
        session.add(MergeQueue(candidate_name="beam search", status="pending"))
        session.commit()

    payload = TestClient(create_app(engine, collection)).get("/queue/next").json()

    assert payload["entry"]["model_decision"] is None


def test_queue_agreement_reports_the_tally(engine, collection):
    with Session(engine) as session:
        session.add(AdjudicationLog(
            candidate_name="beam search",
            model_decision="match",
            human_resolution="approved_merge",
        ))
        session.commit()

    payload = TestClient(create_app(engine, collection)).get("/queue/agreement").json()

    assert payload == {"agreed": 1, "disagreed": 0, "dismissed": 0}
