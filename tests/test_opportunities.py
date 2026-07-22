import json
import random
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from opportunities.generate import (
    DEFAULT_IDEA_COUNT,
    DEFAULT_SAMPLE_SIZE,
    HIGH_CONFIDENCE,
    _build_generation_prompt,
    build_generation_graph,
    call_ollama_generate,
    generate_ideas,
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


def _fake_generate(ideas):
    def generate_fn(concept_names, count):
        return ideas

    return generate_fn


IDEAS = [
    {
        "title": "Local RAG eval harness",
        "description": "Build a harness.",
        "required_skills": ["python", "chromadb"],
    },
    {
        "title": "KV cache visualiser",
        "description": "Render cache growth.",
        "required_skills": ["python"],
    },
]


def test_generate_ideas_writes_one_opportunity_per_idea(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, generate_fn=_fake_generate(IDEAS))

    assert len(created) == 2
    assert [o.title for o in created] == ["Local RAG eval harness", "KV cache visualiser"]
    assert all(o.status == "generated" for o in created)


def test_generate_ideas_stores_skills_concepts_and_timestamp(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, sample_size=4, generate_fn=_fake_generate(IDEAS))

    first = created[0]
    assert json.loads(first.required_skills) == ["python", "chromadb"]
    assert len(json.loads(first.source_concepts)) == 4
    assert first.created_at is not None


def test_generate_ideas_leaves_7c_columns_null(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, generate_fn=_fake_generate(IDEAS))

    assert all(o.skill_match_pct is None for o in created)
    assert all(o.missing_skills is None for o in created)


def test_generate_ideas_passes_only_sampled_names_to_the_model(session):
    _add_concepts(session, 6)
    seen = {}

    def generate_fn(concept_names, count):
        seen["names"] = concept_names
        seen["count"] = count
        return IDEAS

    generate_ideas(session, sample_size=3, count=2, generate_fn=generate_fn)

    assert len(seen["names"]) == 3
    assert seen["count"] == 2
    assert all(isinstance(name, str) for name in seen["names"])


def test_generate_ideas_writes_nothing_when_generation_fails(session):
    _add_concepts(session, 6)

    def generate_fn(concept_names, count):
        raise RuntimeError("model exploded")

    with pytest.raises(RuntimeError, match="model exploded"):
        generate_ideas(session, generate_fn=generate_fn)

    assert _all_opportunities(session) == []


def test_generate_ideas_accepts_fewer_ideas_than_requested(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, count=5, generate_fn=_fake_generate(IDEAS[:1]))

    assert len(created) == 1


def test_build_generation_prompt_lists_the_concepts_and_count():
    prompt = _build_generation_prompt(["RAG", "reranking"], 3)

    assert "RAG" in prompt
    assert "reranking" in prompt
    assert "3" in prompt


def test_build_generation_graph_has_expected_nodes(session):
    app = build_generation_graph(session)

    assert set(app.get_graph().nodes) >= {"sample", "generate", "write_opportunities"}


def test_call_ollama_generate_returns_schema_valid_ideas():
    """Live round-trip against a running Ollama."""
    ideas = call_ollama_generate(["retrieval augmented generation", "vector database"], 2)

    assert isinstance(ideas, list)
    assert len(ideas) >= 1
    for idea in ideas:
        assert isinstance(idea["title"], str) and idea["title"]
        assert isinstance(idea["description"], str) and idea["description"]
        assert isinstance(idea["required_skills"], list)
