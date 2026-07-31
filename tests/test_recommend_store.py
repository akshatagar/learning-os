import json

import pytest
from sqlalchemy import select

from goals.gaps import GapResult
from recommend.graph import GapRecommendation, RecommendResult
from recommend.search import SearchResult
from recommend.store import recommendations_for, store_recommendations
from storage.models import Goal, Recommendation


def _goal(session, category="llm-internals"):
    goal = Goal(description="d", category=category, priority=1,
                concept_requirements=json.dumps(["flash attention"]))
    session.add(goal)
    session.commit()
    return goal


def _result(category="llm-internals", recommendations=None):
    return RecommendResult(
        category=category,
        gap_result=GapResult(present=[], weak=[], missing=[], scores={}),
        recommendations=recommendations or [],
    )


def _hit(url="https://example.com/a"):
    return SearchResult(title="A paper", url=url, snippet="about it", score=0.9)


def test_store_writes_one_row_per_gap(session):
    goal = _goal(session)
    result = _result(recommendations=[
        GapRecommendation(gap="flash attention", score=0.626, results=[_hit()]),
        GapRecommendation(gap="MoE mixture of experts", score=0.330, results=[]),
    ])

    stored = store_recommendations(session, result)

    assert len(stored) == 2
    rows = session.scalars(select(Recommendation)).all()
    assert {r.gap for r in rows} == {"flash attention", "MoE mixture of experts"}
    assert all(r.goal_id == goal.id for r in rows)


def test_store_serialises_results_as_json(session):
    _goal(session)
    result = _result(recommendations=[
        GapRecommendation(gap="flash attention", score=0.626, results=[_hit()]),
    ])

    store_recommendations(session, result)

    row = session.scalars(select(Recommendation)).one()
    payload = json.loads(row.results)
    assert payload == [{
        "title": "A paper", "url": "https://example.com/a",
        "snippet": "about it", "score": pytest.approx(0.9),
    }]


def test_store_persists_an_errored_gap_with_empty_results(session):
    """A failed gap must be a row, or it is indistinguishable from a quiet one."""
    _goal(session)
    result = _result(recommendations=[
        GapRecommendation(gap="flash attention", score=0.626,
                          results=[], error="search failed: boom"),
    ])

    store_recommendations(session, result)

    row = session.scalars(select(Recommendation)).one()
    assert row.error == "search failed: boom"
    assert json.loads(row.results) == []


def test_store_replaces_the_goals_previous_rows(session):
    _goal(session)
    store_recommendations(session, _result(recommendations=[
        GapRecommendation(gap="old gap", score=0.5, results=[_hit()]),
    ]))

    store_recommendations(session, _result(recommendations=[
        GapRecommendation(gap="new gap", score=0.4, results=[_hit()]),
    ]))

    rows = session.scalars(select(Recommendation)).all()
    assert [r.gap for r in rows] == ["new gap"]


def test_store_leaves_another_goals_rows_alone(session):
    _goal(session, "llm-internals")
    _goal(session, "training")
    store_recommendations(session, _result("llm-internals", [
        GapRecommendation(gap="attention gap", score=0.5, results=[]),
    ]))
    store_recommendations(session, _result("training", [
        GapRecommendation(gap="lora gap", score=0.5, results=[]),
    ]))

    store_recommendations(session, _result("training", [
        GapRecommendation(gap="replaced", score=0.5, results=[]),
    ]))

    rows = session.scalars(select(Recommendation)).all()
    assert sorted(r.gap for r in rows) == ["attention gap", "replaced"]


def test_store_rejects_an_unknown_category(session):
    with pytest.raises(ValueError):
        store_recommendations(session, _result("not-a-goal"))


def test_store_stamps_created_at(session):
    _goal(session)

    store_recommendations(session, _result(recommendations=[
        GapRecommendation(gap="flash attention", score=0.6, results=[]),
    ]))

    assert session.scalars(select(Recommendation)).one().created_at is not None


def test_recommendations_for_orders_by_gap_score_descending(session):
    goal = _goal(session)
    store_recommendations(session, _result(recommendations=[
        GapRecommendation(gap="narrow", score=0.62, results=[]),
        GapRecommendation(gap="widest", score=0.19, results=[]),
        GapRecommendation(gap="middle", score=0.43, results=[]),
    ]))

    rows = recommendations_for(session, goal.id)

    assert [r.gap for r in rows] == ["narrow", "middle", "widest"]


def test_recommendations_for_is_empty_for_a_goal_never_run(session):
    goal = _goal(session)

    assert recommendations_for(session, goal.id) == []
