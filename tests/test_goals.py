import json

import pytest

from sqlalchemy import select

from goals.gaps import GapResult, all_goal_gaps, concept_gaps
from storage.models import Concept, Goal


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

    assert result == GapResult(
        present=[],
        weak=[],
        missing=["self-attention", "beam search"],
        scores={"self-attention": 0.0, "beam search": 0.0},
    )


def test_concept_gaps_returns_empty_lists_for_a_goal_with_no_requirements(session, collection):
    result = concept_gaps(session, collection, _goal([]))

    assert result == GapResult(present=[], weak=[], missing=[], scores={})


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


def test_concept_gaps_scores_cover_every_requirement(session, collection):
    collection.add(ids=["1"], documents=["Self-attention layers"])
    session.add(Concept(id=1, name="Self-attention layers", confidence_score=0.9))
    session.commit()

    result = concept_gaps(
        session, collection, _goal(["self-attention", "MoE mixture of experts"])
    )

    assert set(result.scores) == {"self-attention", "MoE mixture of experts"}
    assert result.scores["self-attention"] > result.scores["MoE mixture of experts"]


def test_concept_gaps_scores_are_zero_for_empty_collection(session, collection):
    result = concept_gaps(session, collection, _goal(["anything", "else"]))

    assert result.scores == {"anything": 0.0, "else": 0.0}


def test_all_goal_gaps_returns_nothing_when_there_are_no_goals(session, collection):
    assert all_goal_gaps(session, collection) == []


def test_all_goal_gaps_orders_by_priority_then_id(session, collection):
    session.add_all([
        Goal(description="third", category="c", priority=2,
             concept_requirements=json.dumps(["gamma"])),
        Goal(description="first", category="a", priority=1,
             concept_requirements=json.dumps(["alpha"])),
        Goal(description="second", category="b", priority=1,
             concept_requirements=json.dumps(["beta"])),
    ])
    session.commit()

    results = all_goal_gaps(session, collection)

    assert [r.goal.description for r in results] == ["first", "second", "third"]


def test_all_goal_gaps_pairs_each_goal_with_its_own_requirements(session, collection):
    """An empty collection makes every requirement missing, so the pairing is
    the only thing under test and no embedding has to be trusted."""
    session.add_all([
        Goal(description="one", category="a", priority=1,
             concept_requirements=json.dumps(["alpha", "beta"])),
        Goal(description="two", category="b", priority=1,
             concept_requirements=json.dumps(["gamma"])),
    ])
    session.commit()

    results = all_goal_gaps(session, collection)

    assert results[0].gaps.missing == ["alpha", "beta"]
    assert results[1].gaps.missing == ["gamma"]
    assert results[0].gaps.present == []
    assert results[0].gaps.scores["alpha"] == pytest.approx(0.0)


def test_concept_gaps_treats_null_requirements_as_none_yet(session, collection):
    goal = Goal(description="brand new", category="new", priority=1,
                concept_requirements=None)
    session.add(goal)
    session.commit()

    result = concept_gaps(session, collection, goal)

    assert result == GapResult(present=[], weak=[], missing=[], scores={})


def test_all_goal_gaps_includes_a_goal_with_no_requirements(session, collection):
    """A goal drafting its requirements must not break the goals listing."""
    session.add(Goal(description="brand new", category="new", priority=1,
                     concept_requirements=None))
    session.commit()

    results = all_goal_gaps(session, collection)

    assert len(results) == 1
    assert results[0].gaps.missing == []
