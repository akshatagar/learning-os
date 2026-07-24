from fastapi import FastAPI
from sqlalchemy.orm import Session

from web.state import panel_state


def create_app(engine) -> FastAPI:
    app = FastAPI(title="learning-os")
    app.state.engine = engine

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/state")
    def state() -> dict:
        # A short-lived session per request, as web applications normally do.
        # Job threads get their own; see web/jobs.py.
        with Session(engine) as session:
            return panel_state(session)

    return app
