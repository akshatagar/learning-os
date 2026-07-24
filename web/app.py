import asyncio
import json
import queue

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from web.jobs import JobRegistry
from web.state import panel_state

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0


def create_app(engine, registry: JobRegistry | None = None) -> FastAPI:
    app = FastAPI(title="learning-os")
    app.state.engine = engine
    app.state.registry = registry or JobRegistry(lambda: Session(engine))

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

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
