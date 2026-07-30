import asyncio
import json
import queue
import time

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from pydantic import BaseModel

from concepts.store import list_concepts
from goals.gaps import CONFIDENCE_THRESHOLD
from ingestion.history import recent_ingests
from ingestion.notes import ingest_note
from ingestion.papers import ingest_paper
from opportunities.generate import generate_ideas
from resolution.review import agreement_tally, next_pending, resolve_entry
from storage.models import MergeQueue
from web.jobs import JobRegistry
from web.state import panel_state

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0

# One kind in 8a-1, enough to prove the path end to end. 8b-8d register
# ingest, recommend, score, and plan as those surfaces are built.
JOB_KINDS = {
    "generate-ideas": lambda session: generate_ideas(session),
}


class ResolveRequest(BaseModel):
    action: str
    target_concept_id: int | None = None


class IngestRequest(BaseModel):
    # kind is a plain str, not a Literal: Pydantic would reject an unknown
    # value with 422 before the handler runs, and this application answers
    # a well-formed request naming something invalid with 400.
    source: str
    kind: str


def create_app(engine, collection, registry: JobRegistry | None = None) -> FastAPI:
    app = FastAPI(title="learning-os")
    app.state.engine = engine
    app.state.collection = collection
    app.state.registry = registry or JobRegistry(lambda: Session(engine))

    # Copied onto app.state rather than read from the module constant, so a
    # test can register a fast fake kind without touching the real one.
    app.state.job_kinds = dict(JOB_KINDS)

    # Copied onto app.state for the same reason job_kinds is: so a test can
    # substitute a fast fake without reaching Docling or Ollama.
    app.state.ingest_fns = {"paper": ingest_paper, "note": ingest_note}

    def _describe(job) -> dict:
        # error rides along with status: a failure the panel cannot name is
        # indistinguishable from a stage that simply stopped.
        return {
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "error": job.error,
            # Computed here because a monotonic timestamp means nothing in
            # another process. Only meaningful while the job is running; a
            # finished job's number keeps climbing and no surface shows it.
            "elapsed_seconds": round(time.monotonic() - job.started_at, 1),
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/jobs/{kind}")
    def start_job(kind: str) -> dict:
        fn = app.state.job_kinds.get(kind)
        if fn is None:
            raise HTTPException(status_code=404, detail=f"Unknown job kind: {kind}")
        return _describe(app.state.registry.start(kind, fn))

    # Declared before /jobs/{job_id} on purpose: the parameterised route
    # would otherwise match the literal path and look up a job called
    # "running".
    @app.get("/jobs/running")
    def running_jobs() -> dict:
        return {"jobs": [_describe(job) for job in app.state.registry.running_jobs()]}

    @app.get("/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = app.state.registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such job")
        return _describe(job)

    @app.get("/state")
    def state() -> dict:
        # A short-lived session per request, as web applications normally do.
        # Job threads get their own; see web/jobs.py.
        with Session(engine) as session:
            return panel_state(
                session, running_kinds=app.state.registry.running_kinds()
            )

    @app.post("/ingest")
    def ingest(request: IngestRequest) -> dict:
        fn = app.state.ingest_fns.get(request.kind)
        if fn is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown ingest kind: {request.kind}"
            )
        source = request.source.strip()
        if not source:
            raise HTTPException(status_code=400, detail="A source is required")

        # Not validated further on purpose. ingest_paper fetches over HTTP or
        # reads from disk; either fails for reasons only discoverable at fetch
        # time, and the job's error already carries them to the fault line.
        collection = app.state.collection
        return _describe(
            app.state.registry.start(
                "ingest", lambda session: fn(session, collection, source)
            )
        )

    @app.get("/ingest/history")
    def ingest_history() -> dict:
        with Session(engine) as session:
            return {
                "entries": [
                    {
                        "id": entry.id,
                        "source_path": entry.source_path,
                        "source_type": entry.source_type,
                        "ingested_at": (
                            entry.ingested_at.isoformat()
                            if entry.ingested_at
                            else None
                        ),
                        "concept_count": entry.concept_count,
                    }
                    for entry in recent_ingests(session)
                ]
            }

    @app.get("/concepts")
    def concepts() -> dict:
        with Session(engine) as session:
            return {
                "concepts": [
                    {
                        "id": concept.id,
                        "name": concept.name,
                        "category": concept.category,
                        "confidence_score": concept.confidence_score,
                        "last_reinforced": (
                            concept.last_reinforced.isoformat()
                            if concept.last_reinforced
                            else None
                        ),
                    }
                    for concept in list_concepts(session)
                ],
                # Served rather than hardcoded in JavaScript: goals/gaps.py
                # is the one authority for where the line sits.
                "threshold": CONFIDENCE_THRESHOLD,
            }

    @app.get("/queue/next")
    def queue_next() -> dict:
        with Session(engine) as session:
            view = next_pending(session, app.state.collection)
            if view is None:
                return {"entry": None, "neighbors": [], "remaining": 0}
            return {
                "entry": {
                    "id": view.entry.id,
                    "candidate_name": view.entry.candidate_name,
                    "candidate_category": view.entry.candidate_category,
                    "llm_confidence": view.entry.llm_confidence,
                    "llm_reasoning": view.entry.llm_reasoning,
                    "model_decision": view.model_decision,
                },
                "neighbors": view.neighbors,
                "remaining": view.remaining,
            }

    @app.get("/queue/agreement")
    def queue_agreement() -> dict:
        with Session(engine) as session:
            return agreement_tally(session)

    @app.post("/queue/{entry_id}/resolve")
    def queue_resolve(entry_id: int, request: ResolveRequest) -> dict:
        with Session(engine) as session:
            entry = session.get(MergeQueue, entry_id)
            if entry is None or entry.status != "pending":
                raise HTTPException(
                    status_code=404, detail="No pending entry with that id"
                )
            try:
                result = resolve_entry(
                    session,
                    app.state.collection,
                    entry,
                    request.action,
                    request.target_concept_id,
                )
            except ValueError as error:
                # resolve_entry validates before it mutates, so the entry is
                # still pending here and the operator can pick again.
                raise HTTPException(status_code=400, detail=str(error))
            return {"action": result.action, "concept_id": result.concept_id}

    @app.get("/events")
    async def events() -> StreamingResponse:
        registry = app.state.registry
        stream = registry.subscribe()

        async def publish():
            try:
                # Tell a fresh client what is already running, so a reconnect
                # resynchronizes without waiting for the next transition.
                hello = {
                    "type": "hello",
                    "running": sorted(registry.running_kinds()),
                }
                yield f"data: {json.dumps(hello)}\n\n"

                idle = 0.0
                while True:
                    try:
                        # Bounded, so a disconnected client is noticed within a
                        # poll instead of wedging this generator forever. The
                        # blocking wait goes to a worker thread rather than
                        # stalling the event loop for every other request.
                        event = await asyncio.to_thread(
                            stream.get, True, POLL_SECONDS
                        )
                    except queue.Empty:
                        idle += POLL_SECONDS
                        if idle >= HEARTBEAT_SECONDS:
                            idle = 0.0
                            yield ": keep-alive\n\n"
                        continue
                    idle = 0.0
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                registry.unsubscribe(stream)

        return StreamingResponse(publish(), media_type="text/event-stream")

    # Mounted last on purpose. Mounting "/" before the API routes are declared
    # would shadow every one of them.
    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="static",
    )

    return app
