import json
import re

import pytest

from sqlalchemy import select

from goals.gaps import GapResult, concept_gaps
from goals.seed import GOAL_SEEDS, seed_goals
from storage.models import Concept, Goal

EXPECTED_CATEGORIES = {
    "llm-internals",
    "training",
    "agentic-systems",
    "inference",
    "software-engineering",
}


def test_seed_goals_inserts_five_goals(session):
    goals = seed_goals(session)

    assert len(goals) == 5
    stored = session.scalars(select(Goal)).all()
    assert {g.category for g in stored} == EXPECTED_CATEGORIES
    for goal in stored:
        assert goal.priority == 1
        assert goal.description
        requirements = json.loads(goal.concept_requirements)
        assert len(requirements) == 14
        assert all(isinstance(r, str) and r.strip() for r in requirements)


def test_seed_goals_is_idempotent(session):
    seed_goals(session)
    seed_goals(session)

    assert len(session.scalars(select(Goal)).all()) == 5


def test_seed_goals_preserves_an_existing_goal_in_the_same_category(session):
    existing = Goal(
        description="my own wording",
        category="training",
        priority=3,
        concept_requirements=json.dumps(["LoRA low-rank adaptation"]),
    )
    session.add(existing)
    session.commit()

    seed_goals(session)

    stored = session.scalars(select(Goal).where(Goal.category == "training")).all()
    assert len(stored) == 1
    assert stored[0].description == "my own wording"
    assert stored[0].priority == 3


def test_every_acronym_requirement_includes_an_expansion():
    offenders = []
    for seed in GOAL_SEEDS:
        for requirement in seed["concept_requirements"]:
            has_acronym = re.search(r"\b[A-Z]{2,}\b", requirement)
            has_expansion = re.search(r"\b[a-z]{3,}\b", requirement)
            if has_acronym and not has_expansion:
                offenders.append((seed["category"], requirement))

    assert offenders == []


def _goal(requirements):
    return Goal(
        description="test goal",
        category="test",
        priority=1,
        concept_requirements=json.dumps(requirements),
    )


def _add_concept(session, collection, name, confidence):
    concept = Concept(name=name, confidence_score=confidence)
    session.add(concept)
    session.commit()
    collection.add(ids=[str(concept.id)], documents=[name])
    return concept


def test_concept_gaps_marks_a_close_match_present(session, collection):
    _add_concept(session, collection, "Self-attention layers", 0.8)

    result = concept_gaps(session, collection, _goal(["self-attention"]))

    assert result.present == ["self-attention"]
    assert result.missing == []


def test_concept_gaps_marks_an_unrelated_requirement_missing(session, collection):
    _add_concept(session, collection, "Self-attention layers", 0.8)

    result = concept_gaps(
        session, collection, _goal(["AWS Lambda serverless functions"])
    )

    assert result.missing == ["AWS Lambda serverless functions"]
    assert result.present == []


def test_concept_gaps_marks_a_semantically_adjacent_gap_missing(session, collection):
    _add_concept(session, collection, "Learned positional embeddings", 0.85)

    result = concept_gaps(
        session, collection, _goal(["RoPE rotary positional embeddings"])
    )

    assert result.missing == ["RoPE rotary positional embeddings"]


def test_concept_gaps_returns_all_missing_for_an_empty_collection(session, collection):
    result = concept_gaps(
        session, collection, _goal(["self-attention", "beam search"])
    )

    assert result == GapResult(present=[], weak=[], missing=["self-attention", "beam search"])


def test_concept_gaps_returns_empty_lists_for_a_goal_with_no_requirements(session, collection):
    result = concept_gaps(session, collection, _goal([]))

    assert result == GapResult(present=[], weak=[], missing=[])


def test_concept_gaps_needs_the_expansion_to_match_an_acronym(session, collection):
    _add_concept(
        session, collection,
        "TFLOPS (Trillion Floating Point Operations Per Second)", 0.85,
    )

    expanded = concept_gaps(
        session, collection,
        _goal(["TFLOPS trillion floating point operations per second"]),
    )
    bare = concept_gaps(session, collection, _goal(["TFLOPS"]))

    assert expanded.present == ["TFLOPS trillion floating point operations per second"]
    assert bare.missing == ["TFLOPS"]


def test_concept_gaps_marks_a_low_confidence_match_weak(session, collection):
    _add_concept(session, collection, "Beam search", 0.4)

    result = concept_gaps(session, collection, _goal(["beam search"]))

    assert result.weak == ["beam search"]
    assert result.present == []
    assert result.missing == []


def test_concept_gaps_respects_a_custom_confidence_threshold(session, collection):
    _add_concept(session, collection, "Beam search", 0.4)

    result = concept_gaps(
        session, collection, _goal(["beam search"]), confidence_threshold=0.3
    )

    assert result.present == ["beam search"]
    assert result.weak == []


def test_concept_gaps_raises_when_a_chroma_hit_has_no_sqlite_row(session, collection):
    collection.add(ids=["9999"], documents=["Beam search"])

    with pytest.raises(ValueError):
        concept_gaps(session, collection, _goal(["beam search"]))
