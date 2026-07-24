import asyncio
import json
import queue

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from opportunities.generate import generate_ideas
from web.jobs import JobRegistry
from web.state import panel_state

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0

# One kind in 8a-1, enough to prove the path end to end. 8b-8d register
# ingest, recommend, score, and plan as those surfaces are built.
JOB_KINDS = {
    "generate-ideas": lambda session: generate_ideas(session),
}


def create_app(engine, registry: JobRegistry | None = None) -> FastAPI:
    app = FastAPI(title="learning-os")
    app.state.engine = engine
    app.state.registry = registry or JobRegistry(lambda: Session(engine))

    # Copied onto app.state rather than read from the module constant, so a
    # test can register a fast fake kind without touching the real one.
    app.state.job_kinds = dict(JOB_KINDS)

    def _describe(job) -> dict:
        return {"job_id": job.id, "kind": job.kind, "status": job.status}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/jobs/{kind}")
    def start_job(kind: str) -> dict:
        fn = app.state.job_kinds.get(kind)
        if fn is None:
            raise HTTPException(status_code=404, detail=f"Unknown job kind: {kind}")
        return _describe(app.state.registry.start(kind, fn))

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

    return app
