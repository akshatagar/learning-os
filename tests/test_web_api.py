from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from storage.models import MergeQueue
from web.app import create_app


def test_health_reports_ok(engine):
    client = TestClient(create_app(engine))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_state_returns_every_stage(engine):
    client = TestClient(create_app(engine))

    payload = client.get("/state").json()

    assert len(payload["stages"]) == 10
    assert payload["stages"][0]["id"] == "ingest"


def test_state_reflects_rows_written_after_startup(engine):
    """The session is per request, so a stale snapshot would be a real bug."""
    client = TestClient(create_app(engine))
    assert client.get("/state").json()["stages"][2]["lamp"] == "unlit"

    with Session(engine) as session:
        session.add(MergeQueue(candidate_name="Attention", status="pending"))
        session.commit()

    stages = client.get("/state").json()["stages"]
    queue = next(stage for stage in stages if stage["id"] == "queue")
    assert queue["lamp"] == "holding"
    assert queue["count"] == 1
