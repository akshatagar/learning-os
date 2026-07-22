import json
import random
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from opportunities.generate import (
    DEFAULT_IDEA_COUNT,
    DEFAULT_SAMPLE_SIZE,
    HIGH_CONFIDENCE,
    sample_concepts,
)
from storage.models import Concept, Opportunity


def _add_concepts(session, count, confidence=0.9):
    for index in range(count):
        session.add(Concept(name=f"concept {index}", confidence_score=confidence))
    session.commit()


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


def test_defaults_are_five_concepts_and_three_ideas():
    assert DEFAULT_SAMPLE_SIZE == 5
    assert DEFAULT_IDEA_COUNT == 3
    assert HIGH_CONFIDENCE == 0.7


def test_sample_concepts_returns_exactly_n(session):
    _add_concepts(session, 10)

    assert len(sample_concepts(session, 5)) == 5


def test_sample_concepts_excludes_low_confidence(session):
    _add_concepts(session, 3, confidence=0.9)
    _add_concepts(session, 3, confidence=0.4)

    sampled = sample_concepts(session, 5)

    assert len(sampled) == 3
    assert all(c.confidence_score >= HIGH_CONFIDENCE for c in sampled)


def test_sample_concepts_returns_all_when_fewer_than_n_qualify(session):
    _add_concepts(session, 2)

    assert len(sample_concepts(session, 5)) == 2


def test_sample_concepts_raises_when_none_qualify(session):
    _add_concepts(session, 3, confidence=0.4)

    with pytest.raises(ValueError, match="confidence_score"):
        sample_concepts(session, 5)


def test_sample_concepts_raises_on_an_empty_kb(session):
    with pytest.raises(ValueError, match="confidence_score"):
        sample_concepts(session, 5)


def test_sample_concepts_is_deterministic_under_a_seeded_rng(session):
    _add_concepts(session, 10)

    first = [c.id for c in sample_concepts(session, 5, rng=random.Random(0))]
    second = [c.id for c in sample_concepts(session, 5, rng=random.Random(0))]

    assert first == second
