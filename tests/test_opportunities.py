import json
from datetime import datetime, timezone

from sqlalchemy import select

from storage.models import Opportunity


def _all_opportunities(session):
    return list(session.scalars(select(Opportunity).order_by(Opportunity.id)))


def test_opportunity_round_trips_the_new_columns(session):
    now = datetime.now(timezone.utc)
    session.add(
        Opportunity(
            title="Local RAG eval harness",
            description="Build a harness.",
            required_skills=json.dumps(["python", "chromadb"]),
            source_concepts=json.dumps([1, 2, 3]),
            created_at=now,
        )
    )
    session.commit()

    stored = _all_opportunities(session)[0]

    assert json.loads(stored.required_skills) == ["python", "chromadb"]
    assert json.loads(stored.source_concepts) == [1, 2, 3]
    assert stored.created_at is not None
    assert stored.status == "generated"
    assert stored.skill_match_pct is None
    assert stored.missing_skills is None
