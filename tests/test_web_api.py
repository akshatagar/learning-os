import json
import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import (
    AdjudicationLog,
    Concept,
    ContentLog,
    Goal,
    MergeQueue,
    Opportunity,
    Recommendation,
    Skill,
)
from web.app import JOB_KINDS, create_app
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


def test_skills_are_served_with_their_band_labels(engine, collection):
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        session.add_all([
            Skill(name="docker", proficiency=60.0, source="user_confirmed"),
            Skill(name="python", proficiency=85.0, source="user_confirmed"),
        ])
        session.commit()

    payload = client.get("/skills").json()

    assert [s["name"] for s in payload["skills"]] == ["docker", "python"]
    assert payload["skills"][0]["band"] == "working"
    assert payload["skills"][1]["band"] == "strong"


def test_the_bands_come_from_the_pipeline(engine, collection):
    """One authority for the three bands, so the surface cannot drift from
    the values every score was written against."""
    from skills.entry import PROFICIENCY_BANDS

    client = TestClient(create_app(engine, collection))

    bands = client.get("/skills").json()["bands"]

    assert [b["key"] for b in bands] == list(PROFICIENCY_BANDS)
    assert [(b["label"], b["value"]) for b in bands] == [
        (label, value) for label, value in PROFICIENCY_BANDS.values()
    ]


def test_posting_a_skill_creates_it(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/skills", json={"name": "docker", "band": "w"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True
    assert payload["skill"]["name"] == "docker"
    assert payload["skill"]["proficiency"] == pytest.approx(60.0)
    assert payload["skill"]["band"] == "working"


def test_posting_a_name_already_on_record_is_not_an_error(engine, collection):
    """The CLI counts a duplicate under `unchanged`, not as a failure, and the
    surface needs the existing row back to offer a band change."""
    client = TestClient(create_app(engine, collection))
    client.post("/skills", json={"name": "docker", "band": "w"})

    response = client.post("/skills", json={"name": "DOCKER", "band": "s"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert payload["skill"]["band"] == "working"


def test_posting_a_blank_name_is_rejected(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/skills", json={"name": "   ", "band": "w"})

    assert response.status_code == 400


def test_posting_an_unknown_band_is_rejected(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/skills", json={"name": "docker", "band": "z"})

    assert response.status_code == 400
    with Session(engine) as session:
        assert session.scalars(select(Skill)).all() == []


def test_patching_a_skill_changes_its_band(engine, collection):
    client = TestClient(create_app(engine, collection))
    created = client.post("/skills", json={"name": "docker", "band": "f"}).json()

    response = client.patch(f"/skills/{created['skill']['id']}", json={"band": "s"})

    assert response.status_code == 200
    assert response.json()["skill"]["band"] == "strong"
    assert response.json()["skill"]["proficiency"] == pytest.approx(85.0)


def test_patching_an_unknown_skill_is_a_404(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.patch("/skills/999", json={"band": "s"})

    assert response.status_code == 404


def test_patching_with_an_unknown_band_leaves_the_row_alone(engine, collection):
    client = TestClient(create_app(engine, collection))
    created = client.post("/skills", json={"name": "docker", "band": "f"}).json()

    response = client.patch(f"/skills/{created['skill']['id']}", json={"band": "z"})

    assert response.status_code == 400
    assert client.get("/skills").json()["skills"][0]["band"] == "familiar"


def test_goals_are_served_with_their_buckets(engine, collection):
    """The collection is empty, so every requirement is missing — which makes
    this a test of the serialisation and not of an embedding."""
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        session.add(Goal(
            description="understand transformers",
            category="llm-internals",
            priority=1,
            concept_requirements=json.dumps(["self-attention", "beam search"]),
        ))
        session.commit()

    payload = client.get("/goals").json()

    assert len(payload["goals"]) == 1
    goal = payload["goals"][0]
    assert goal["category"] == "llm-internals"
    assert goal["description"] == "understand transformers"
    assert goal["priority"] == 1
    assert goal["missing"] == ["self-attention", "beam search"]
    assert goal["present"] == []
    assert goal["weak"] == []
    assert goal["scores"]["self-attention"] == pytest.approx(0.0)


def test_goals_are_served_in_priority_order(engine, collection):
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        session.add_all([
            Goal(description="later", category="b", priority=2,
                 concept_requirements=json.dumps(["beta"])),
            Goal(description="sooner", category="a", priority=1,
                 concept_requirements=json.dumps(["alpha"])),
        ])
        session.commit()

    payload = client.get("/goals").json()

    assert [g["description"] for g in payload["goals"]] == ["sooner", "later"]


def test_the_goal_thresholds_come_from_the_pipeline(engine, collection):
    """One authority for both lines, so the meter's tick cannot drift from the
    rule that actually decides a bucket."""
    from goals.gaps import CONFIDENCE_THRESHOLD, SIMILARITY_THRESHOLD

    client = TestClient(create_app(engine, collection))

    payload = client.get("/goals").json()

    assert payload["similarity_threshold"] == pytest.approx(SIMILARITY_THRESHOLD)
    assert payload["confidence_threshold"] == pytest.approx(CONFIDENCE_THRESHOLD)


def test_goals_are_empty_when_none_are_seeded(engine, collection):
    client = TestClient(create_app(engine, collection))

    assert client.get("/goals").json()["goals"] == []


def _fake_search(query, k=5):
    from recommend.search import SearchResult
    return [SearchResult(title=f"On {query}", url=f"https://example.com/{k}",
                         snippet="snippet", score=0.9)]


def _fake_filter(gap, results):
    return results


def _recommend_app(engine, collection):
    """An app whose recommend job reaches neither Tavily nor Ollama."""
    app = create_app(engine, collection)
    app.state.recommend_fns = {"search": _fake_search, "filter": _fake_filter}
    return app


def _seed_goal(engine, category="llm-internals"):
    with Session(engine) as session:
        session.add(Goal(description="d", category=category, priority=1,
                         concept_requirements=json.dumps(["flash attention"])))
        session.commit()


def test_recommend_starts_a_job_under_the_recommend_kind(engine, collection):
    """The kind string is load-bearing: web/state.py lights goals from it."""
    _seed_goal(engine)
    registry = JobRegistry(lambda: Session(engine))
    app = _recommend_app(engine, collection)
    app.state.registry = registry
    client = TestClient(app)

    payload = client.post("/recommend",
                          json={"category": "llm-internals", "top": 1}).json()

    assert payload["kind"] == "recommend"
    registry.get(payload["job_id"]).thread.join(10.0)


def test_recommend_stores_what_the_run_produced(engine, collection):
    _seed_goal(engine)
    registry = JobRegistry(lambda: Session(engine))
    app = _recommend_app(engine, collection)
    app.state.registry = registry
    client = TestClient(app)

    job_id = client.post("/recommend",
                         json={"category": "llm-internals", "top": 1}).json()["job_id"]
    registry.get(job_id).thread.join(10.0)

    assert registry.get(job_id).status == "done"
    with Session(engine) as session:
        rows = session.scalars(select(Recommendation)).all()
        assert len(rows) == 1
        assert rows[0].gap == "flash attention"


def test_recommend_rejects_an_unknown_category_before_starting(engine, collection):
    """A typo must be a 400, not a failed job noticed seconds later."""
    _seed_goal(engine)
    client = TestClient(_recommend_app(engine, collection))

    response = client.post("/recommend", json={"category": "nope", "top": 1})

    assert response.status_code == 400
    assert "llm-internals" in response.json()["detail"]


def test_recommend_rejects_a_top_below_one(engine, collection):
    _seed_goal(engine)
    client = TestClient(_recommend_app(engine, collection))

    response = client.post("/recommend", json={"category": "llm-internals", "top": 0})

    assert response.status_code == 400


def test_goals_carry_their_stored_recommendations(engine, collection):
    _seed_goal(engine)
    with Session(engine) as session:
        goal = session.scalars(select(Goal)).one()
        session.add(Recommendation(
            goal_id=goal.id, gap="flash attention", gap_score=0.626,
            results=json.dumps([{"title": "A paper", "url": "https://example.com/a",
                                 "snippet": "s", "score": 0.9}]),
            error=None,
        ))
        session.commit()

    goal_payload = TestClient(create_app(engine, collection)).get("/goals").json()["goals"][0]

    assert len(goal_payload["recommendations"]) == 1
    entry = goal_payload["recommendations"][0]
    assert entry["gap"] == "flash attention"
    assert entry["gap_score"] == pytest.approx(0.626)
    assert entry["results"][0]["url"] == "https://example.com/a"
    assert entry["error"] is None


def test_a_goal_never_recommended_carries_an_empty_list(engine, collection):
    _seed_goal(engine)

    goal_payload = TestClient(create_app(engine, collection)).get("/goals").json()["goals"][0]

    assert goal_payload["recommendations"] == []


def _add_opportunity(engine, title, status="generated", required=None, concepts=None,
                     pct=None, missing=None, plan=None):
    with Session(engine) as session:
        opportunity = Opportunity(
            title=title,
            description="Does a thing.",
            status=status,
            # `is not None` rather than `or []`: an explicitly-passed empty
            # list must stay empty, and that is exactly the unscorable case.
            required_skills=json.dumps(required if required is not None else []),
            source_concepts=json.dumps(concepts or []),
            skill_match_pct=pct,
            missing_skills=None if missing is None else json.dumps(missing),
            execution_plan=None if plan is None else json.dumps(plan),
            created_at=datetime.now(timezone.utc),
        )
        session.add(opportunity)
        session.commit()
        return opportunity.id


def test_ideas_returns_every_opportunity_newest_first(engine, collection):
    client = TestClient(create_app(engine, collection))
    _add_opportunity(engine, "older", status="rejected")
    _add_opportunity(engine, "newer", status="approved")

    payload = client.get("/ideas").json()

    assert [o["title"] for o in payload["opportunities"]] == ["newer", "older"]
    assert [o["status"] for o in payload["opportunities"]] == ["approved", "rejected"]


def test_ideas_names_concepts_and_parses_required_skills(engine, collection):
    client = TestClient(create_app(engine, collection))
    with Session(engine) as session:
        concept = Concept(name="LoRA")
        session.add(concept)
        session.commit()
        concept_id = concept.id
    _add_opportunity(
        engine, "An idea", required=["python", "pytorch"], concepts=[concept_id]
    )

    idea = client.get("/ideas").json()["opportunities"][0]

    assert idea["source_concepts"] == ["LoRA"]
    assert idea["required_skills"] == ["python", "pytorch"]


def test_ideas_is_empty_before_anything_is_generated(engine, collection):
    client = TestClient(create_app(engine, collection))

    assert client.get("/ideas").json() == {"opportunities": []}


def test_approval_returns_only_generated_rows(engine, collection):
    client = TestClient(create_app(engine, collection))
    _add_opportunity(engine, "waiting")
    _add_opportunity(engine, "already kept", status="approved")
    _add_opportunity(engine, "already dropped", status="rejected")

    payload = client.get("/approval").json()

    assert [o["title"] for o in payload["opportunities"]] == ["waiting"]


def test_keeping_an_idea_approves_it_and_darkens_the_lamp(engine, collection):
    """The lamp is the point: resolving the last pending idea must go dark."""
    client = TestClient(create_app(engine, collection))
    idea_id = _add_opportunity(engine, "waiting")
    stages = client.get("/state").json()["stages"]
    assert next(s for s in stages if s["id"] == "approval")["lamp"] == "holding"

    response = client.post(f"/opportunities/{idea_id}/resolve", json={"action": "approve"})

    assert response.status_code == 200
    assert response.json() == {"id": idea_id, "status": "approved"}
    stages = client.get("/state").json()["stages"]
    assert next(s for s in stages if s["id"] == "approval")["lamp"] == "unlit"


def test_dropping_an_idea_rejects_it(engine, collection):
    client = TestClient(create_app(engine, collection))
    idea_id = _add_opportunity(engine, "waiting")

    response = client.post(f"/opportunities/{idea_id}/resolve", json={"action": "reject"})

    assert response.json()["status"] == "rejected"


def test_restoring_a_dropped_idea_makes_it_pending_again(engine, collection):
    client = TestClient(create_app(engine, collection))
    idea_id = _add_opportunity(engine, "dropped", status="rejected")

    response = client.post(f"/opportunities/{idea_id}/resolve", json={"action": "restore"})

    assert response.json()["status"] == "generated"
    assert [o["title"] for o in client.get("/approval").json()["opportunities"]] == [
        "dropped"
    ]


def test_resolving_an_unknown_id_is_a_404(engine, collection):
    client = TestClient(create_app(engine, collection))

    response = client.post("/opportunities/9999/resolve", json={"action": "approve"})

    assert response.status_code == 404


def test_an_unknown_action_is_a_400(engine, collection):
    client = TestClient(create_app(engine, collection))
    idea_id = _add_opportunity(engine, "waiting")

    response = client.post(f"/opportunities/{idea_id}/resolve", json={"action": "maybe"})

    assert response.status_code == 400
    assert "approval action" in response.json()["detail"]


def test_restoring_an_approved_idea_is_a_400_and_changes_nothing(engine, collection):
    client = TestClient(create_app(engine, collection))
    idea_id = _add_opportunity(engine, "kept", status="approved")

    response = client.post(f"/opportunities/{idea_id}/resolve", json={"action": "restore"})

    assert response.status_code == 400
    assert "Cannot restore" in response.json()["detail"]
    assert client.get("/ideas").json()["opportunities"][0]["status"] == "approved"


def test_scoring_lists_a_scored_row_with_its_missing_skills(engine, collection):
    client = TestClient(create_app(engine, collection))
    _add_opportunity(engine, "scored", status="approved",
                     required=["Python", "SQL"], pct=50.0, missing=["SQL"])

    payload = client.get("/scoring").json()

    assert [r["title"] for r in payload["scored"]] == ["scored"]
    assert payload["scored"][0]["skill_match_pct"] == 50.0
    assert payload["scored"][0]["missing_skills"] == ["SQL"]


def test_scoring_separates_waiting_from_unscorable(engine, collection):
    client = TestClient(create_app(engine, collection))
    _add_opportunity(engine, "waiting", status="approved", required=["Python"])
    _add_opportunity(engine, "unscorable", status="approved", required=[])

    payload = client.get("/scoring").json()

    assert [r["title"] for r in payload["waiting"]] == ["waiting"]
    assert [r["title"] for r in payload["unscorable"]] == ["unscorable"]


def test_planning_returns_the_plan_as_a_parsed_list(engine, collection):
    """A JSON string here would make the surface parse it, which is web's job."""
    client = TestClient(create_app(engine, collection))
    _add_opportunity(engine, "planned", status="approved", pct=100.0,
                     plan=[{"title": "Ship it", "kind": "build", "detail": "Ship."}])

    payload = client.get("/planning").json()

    assert payload["planned"][0]["execution_plan"] == [
        {"title": "Ship it", "kind": "build", "detail": "Ship."}
    ]


def test_planning_names_the_rows_blocked_on_scoring(engine, collection):
    client = TestClient(create_app(engine, collection))
    _add_opportunity(engine, "not scored", status="approved", required=["Python"])

    payload = client.get("/planning").json()

    assert [r["title"] for r in payload["blocked"]] == ["not scored"]
    assert payload["waiting"] == []


def test_scoring_and_planning_are_registered_job_kinds():
    """The lamps in web/state.py have referred to these names since 8a-1."""
    assert set(JOB_KINDS) == {
        "generate-ideas", "score-opportunities", "plan-opportunities"
    }


def test_starting_the_scoring_job_runs_the_registered_function(engine, collection):
    """Substituted through app.state.job_kinds so the real one never reaches Ollama."""
    app = create_app(engine, collection)
    ran = threading.Event()
    app.state.job_kinds["score-opportunities"] = lambda session: ran.set()
    client = TestClient(app)

    response = client.post("/jobs/score-opportunities")

    assert response.status_code == 200
    assert response.json()["kind"] == "score-opportunities"
    assert ran.wait(timeout=5)


def test_starting_the_planning_job_runs_the_registered_function(engine, collection):
    app = create_app(engine, collection)
    ran = threading.Event()
    app.state.job_kinds["plan-opportunities"] = lambda session: ran.set()
    client = TestClient(app)

    response = client.post("/jobs/plan-opportunities")

    assert response.status_code == 200
    assert response.json()["kind"] == "plan-opportunities"
    assert ran.wait(timeout=5)
