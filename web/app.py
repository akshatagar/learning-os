from fastapi import FastAPI


def create_app(engine) -> FastAPI:
    app = FastAPI(title="learning-os")
    app.state.engine = engine

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
