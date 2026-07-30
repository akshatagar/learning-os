import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import AdjudicationLog, Concept, ContentLog, MergeQueue
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


def test_resolving_as_new_creates_a_concept_and_embeds_it(engine, collection):
    with Session(engine) as session:
        entry = MergeQueue(candidate_name="beam search", status="pending")
        session.add(entry)
        session.commit()
        entry_id = entry.id

    client = TestClient(create_app(engine, collection))

    payload = client.post(f"/queue/{entry_id}/resolve", json={"action": "new"}).json()

    assert payload["action"] == "new"
    with Session(engine) as session:
        concept = session.get(Concept, payload["concept_id"])
        assert concept.name == "beam search"
        assert session.get(MergeQueue, entry_id).status == "approved_new"
    assert collection.get(ids=[str(payload["concept_id"])])["ids"] == [
        str(payload["concept_id"])
    ]


def test_resolving_as_merge_reinforces_the_target(engine, collection):
    with Session(engine) as session:
        concept = Concept(name="beam search", confidence_score=0.5)
        entry = MergeQueue(candidate_name="beam search decoding", status="pending")
        session.add_all([concept, entry])
        session.commit()
        concept_id, entry_id = concept.id, entry.id

    client = TestClient(create_app(engine, collection))

    response = client.post(
        f"/queue/{entry_id}/resolve",
        json={"action": "merge", "target_concept_id": concept_id},
    )

    assert response.json() == {"action": "merge", "concept_id": concept_id}
    with Session(engine) as session:
        # approx, not ==: resolve_entry computes 0.5 + 0.05, which in binary
        # floating point is 0.55000000000000004.
        assert session.get(Concept, concept_id).confidence_score == pytest.approx(0.55)
        assert session.get(MergeQueue, entry_id).status == "approved_merge"


def test_resolving_as_dismiss_creates_no_concept(engine, collection):
    with Session(engine) as session:
        entry = MergeQueue(candidate_name="vague thing", status="pending")
        session.add(entry)
        session.commit()
        entry_id = entry.id

    client = TestClient(create_app(engine, collection))

    payload = client.post(
        f"/queue/{entry_id}/resolve", json={"action": "dismiss"}
    ).json()

    assert payload == {"action": "dismiss", "concept_id": None}
    with Session(engine) as session:
        assert session.get(MergeQueue, entry_id).status == "rejected"
        assert session.scalars(select(Concept)).all() == []


def test_resolving_backfills_the_human_resolution_on_the_log(engine, collection):
    """The tally reads adjudication_log, so this is what makes it move."""
    with Session(engine) as session:
        log = AdjudicationLog(candidate_name="beam search", model_decision="new")
        session.add(log)
        session.flush()
        entry = MergeQueue(
            candidate_name="beam search",
            status="pending",
            adjudication_log_id=log.id,
        )
        session.add(entry)
        session.commit()
        log_id, entry_id = log.id, entry.id

    client = TestClient(create_app(engine, collection))
    client.post(f"/queue/{entry_id}/resolve", json={"action": "new"})

    with Session(engine) as session:
        assert session.get(AdjudicationLog, log_id).human_resolution == "approved_new"
    assert client.get("/queue/agreement").json()["agreed"] == 1


def test_resolving_an_unknown_entry_is_a_404(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/queue/999/resolve", json={"action": "dismiss"})

    assert response.status_code == 404


def test_resolving_an_already_resolved_entry_is_a_404(engine, collection):
    """Two clicks on the same button must not resolve two different things."""
    with Session(engine) as session:
        entry = MergeQueue(candidate_name="beam search", status="rejected")
        session.add(entry)
        session.commit()
        entry_id = entry.id

    client = TestClient(create_app(engine, collection))

    response = client.post(f"/queue/{entry_id}/resolve", json={"action": "dismiss"})

    assert response.status_code == 404


def test_merging_without_a_target_is_a_400(engine, collection):
    with Session(engine) as session:
        entry = MergeQueue(candidate_name="beam search", status="pending")
        session.add(entry)
        session.commit()
        entry_id = entry.id

    client = TestClient(create_app(engine, collection))

    response = client.post(f"/queue/{entry_id}/resolve", json={"action": "merge"})

    assert response.status_code == 400
    with Session(engine) as session:
        assert session.get(MergeQueue, entry_id).status == "pending"


def test_an_unknown_action_is_a_400(engine, collection):
    with Session(engine) as session:
        entry = MergeQueue(candidate_name="beam search", status="pending")
        session.add(entry)
        session.commit()
        entry_id = entry.id

    client = TestClient(create_app(engine, collection))

    response = client.post(f"/queue/{entry_id}/resolve", json={"action": "banish"})

    assert response.status_code == 400


def test_a_job_reports_how_long_it_has_been_running(engine, collection):
    app = create_app(engine, collection)
    app.state.job_kinds = {"slow": lambda session: None}
    client = TestClient(app)

    payload = client.post("/jobs/slow").json()

    assert payload["elapsed_seconds"] >= 0


def test_running_jobs_are_listable(engine, collection):
    """A surface opened mid-run has no other way to find the job."""
    registry = JobRegistry(lambda: Session(engine))
    app = create_app(engine, collection, registry=registry)
    started = threading.Event()
    release = threading.Event()

    def blocker(session):
        started.set()
        release.wait(5.0)

    app.state.job_kinds = {"blocker": blocker}
    client = TestClient(app)

    job_id = client.post("/jobs/blocker").json()["job_id"]
    started.wait(5.0)
    try:
        jobs = client.get("/jobs/running").json()["jobs"]
        assert [j["job_id"] for j in jobs] == [job_id]
        assert jobs[0]["kind"] == "blocker"
    finally:
        release.set()
        registry.get(job_id).thread.join(5.0)


def test_nothing_running_lists_nothing(engine, collection):
    client = TestClient(create_app(engine, collection))

    assert client.get("/jobs/running").json() == {"jobs": []}


def _fake_ingest(calls):
    def fake(session, collection, source):
        calls.append(source)
    return fake


def test_ingesting_a_paper_starts_a_job_under_the_ingest_kind(engine, collection):
    """The kind string is load-bearing: web/state.py lamps off flow("ingest")."""
    registry = JobRegistry(lambda: Session(engine))
    app = create_app(engine, collection, registry=registry)
    calls = []
    app.state.ingest_fns = {"paper": _fake_ingest(calls), "note": _fake_ingest([])}
    client = TestClient(app)

    payload = client.post(
        "/ingest", json={"source": "paper.pdf", "kind": "paper"}
    ).json()

    assert payload["kind"] == "ingest"
    registry.get(payload["job_id"]).thread.join(5.0)
    assert calls == ["paper.pdf"]


def test_ingesting_a_note_calls_the_note_pipeline(engine, collection):
    registry = JobRegistry(lambda: Session(engine))
    app = create_app(engine, collection, registry=registry)
    calls = []
    app.state.ingest_fns = {"paper": _fake_ingest([]), "note": _fake_ingest(calls)}
    client = TestClient(app)

    payload = client.post(
        "/ingest", json={"source": "note.md", "kind": "note"}
    ).json()

    registry.get(payload["job_id"]).thread.join(5.0)
    assert calls == ["note.md"]


def test_an_unknown_ingest_kind_is_rejected(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/ingest", json={"source": "x.pdf", "kind": "video"})

    assert response.status_code == 400


def test_a_blank_source_is_rejected(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/ingest", json={"source": "   ", "kind": "paper"})

    assert response.status_code == 400


def test_a_second_ingest_while_one_runs_returns_the_same_job(engine, collection):
    registry = JobRegistry(lambda: Session(engine))
    app = create_app(engine, collection, registry=registry)
    release = threading.Event()

    def blocker(session, collection_, source):
        release.wait(5.0)

    app.state.ingest_fns = {"paper": blocker, "note": blocker}
    client = TestClient(app)

    first = client.post("/ingest", json={"source": "a.pdf", "kind": "paper"}).json()
    second = client.post("/ingest", json={"source": "b.pdf", "kind": "paper"}).json()

    try:
        assert first["job_id"] == second["job_id"]
    finally:
        release.set()
        registry.get(first["job_id"]).thread.join(5.0)


def test_the_real_ingest_functions_are_wired_by_default(engine, collection):
    app = create_app(engine, collection)

    assert set(app.state.ingest_fns) == {"paper", "note"}


def test_concepts_are_served_weakest_first(engine, collection):
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        session.add_all([
            Concept(name="Strong", category="Arch", confidence_score=1.0),
            Concept(name="Weak", category="Arch", confidence_score=0.5),
        ])
        session.commit()

    payload = client.get("/concepts").json()

    assert [c["name"] for c in payload["concepts"]] == ["Weak", "Strong"]
    assert payload["concepts"][0]["category"] == "Arch"


def test_the_concept_threshold_comes_from_the_pipeline(engine, collection):
    """One authority for the value, so the surface cannot drift from goals."""
    from goals.gaps import CONFIDENCE_THRESHOLD

    client = TestClient(create_app(engine, collection))

    assert client.get("/concepts").json()["threshold"] == CONFIDENCE_THRESHOLD


def test_an_empty_store_serves_an_empty_list(engine, collection):
    client = TestClient(create_app(engine, collection))

    assert client.get("/concepts").json()["concepts"] == []


def test_the_ingest_history_is_newest_first_with_counts(engine, collection):
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        session.add_all([
            ContentLog(
                source_path="old.pdf", source_type="paper",
                ingested_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                extracted_concepts="[1, 2]",
            ),
            ContentLog(
                source_path="new.pdf", source_type="paper",
                ingested_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
                extracted_concepts="[1, 2, 3]",
            ),
        ])
        session.commit()

    entries = client.get("/ingest/history").json()["entries"]

    assert [e["source_path"] for e in entries] == ["new.pdf", "old.pdf"]
    assert entries[0]["concept_count"] == 3
    assert entries[0]["ingested_at"].startswith("2026-07-09")


def test_no_ingests_yet_serves_an_empty_list(engine, collection):
    client = TestClient(create_app(engine, collection))

    assert client.get("/ingest/history").json() == {"entries": []}


def test_the_queue_entry_carries_its_governing_threshold(engine, collection):
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        log = AdjudicationLog(candidate_name="Attention", model_decision="new")
        session.add(log)
        session.flush()
        session.add(MergeQueue(
            candidate_name="Attention", status="pending",
            adjudication_log_id=log.id,
        ))
        session.commit()

    assert client.get("/queue/next").json()["entry"]["threshold"] == 0.65
