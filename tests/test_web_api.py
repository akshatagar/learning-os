from fastapi.testclient import TestClient

from web.app import create_app


def test_health_reports_ok(engine):
    client = TestClient(create_app(engine))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
