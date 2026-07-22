import json
from datetime import datetime, timezone

import pytest

from goals.gaps import GapResult
from recommend.graph import build_recommend_graph, rank_gaps, recommend_goal
from recommend.search import SearchResult
from storage.models import Concept, ContentLog, Goal


def _gaps(weak, missing, scores):
    return GapResult(present=[], weak=weak, missing=missing, scores=scores)


def test_rank_gaps_orders_by_similarity_descending():
    result = _gaps([], ["a", "b", "c"], {"a": 0.31, "b": 0.68, "c": 0.58})

    assert rank_gaps(result, top=3) == ["b", "c", "a"]


def test_rank_gaps_puts_weak_above_missing_without_tier_logic():
    result = _gaps(["w"], ["m"], {"w": 0.72, "m": 0.68})

    assert rank_gaps(result, top=2) == ["w", "m"]


def test_rank_gaps_truncates_to_top():
    result = _gaps([], ["a", "b", "c"], {"a": 0.31, "b": 0.68, "c": 0.58})

    assert rank_gaps(result, top=2) == ["b", "c"]


def test_rank_gaps_returns_all_when_top_exceeds_gap_count():
    result = _gaps([], ["a"], {"a": 0.31})

    assert rank_gaps(result, top=5) == ["a"]


def test_rank_gaps_returns_empty_when_there_are_no_gaps():
    result = _gaps([], [], {"present-thing": 0.99})

    assert rank_gaps(result, top=3) == []


def test_rank_gaps_ignores_present_requirements():
    result = _gaps([], ["m"], {"present-thing": 0.99, "m": 0.31})

    assert rank_gaps(result, top=3) == ["m"]


def _seed_goal(session, category, requirements):
    goal = Goal(
        description="d",
        category=category,
        priority=1,
        concept_requirements=json.dumps(requirements),
    )
    session.add(goal)
    session.commit()
    return goal


def _fake_search(results_by_gap):
    def search_fn(query, k=5):
        return list(results_by_gap.get(query, []))

    return search_fn


def _result(url, title="t"):
    return SearchResult(title=title, url=url, snippet="s", score=0.9)


def test_recommend_goal_returns_shortlist_per_gap(session, collection):
    _seed_goal(session, "training", ["gradient accumulation", "MoE mixture of experts"])
    search_fn = _fake_search({
        "gradient accumulation": [_result("https://example.com/ga")],
        "MoE mixture of experts": [_result("https://example.com/moe")],
    })

    result = recommend_goal(
        session, collection, "training", top=2,
        search_fn=search_fn, filter_fn=lambda gap, rs: rs,
    )

    # Both gaps score 0.0 against an empty collection, and `sorted` is stable,
    # so the order is the requirement order.
    assert [r.gap for r in result.recommendations] == [
        "gradient accumulation", "MoE mixture of experts",
    ]
    assert all(r.error is None for r in result.recommendations)
    assert sum(len(r.results) for r in result.recommendations) == 2


def test_recommend_goal_raises_for_unknown_category(session, collection):
    _seed_goal(session, "training", ["x"])

    with pytest.raises(ValueError, match="training"):
        recommend_goal(session, collection, "nonexistent")


def test_recommend_goal_makes_no_search_calls_when_there_are_no_gaps(session, collection):
    collection.add(ids=["1"], documents=["Self-attention layers"])
    session.add(Concept(id=1, name="Self-attention layers", confidence_score=0.9))
    _seed_goal(session, "covered", ["self-attention"])
    calls = []

    def search_fn(query, k=5):
        calls.append(query)
        return []

    result = recommend_goal(
        session, collection, "covered", search_fn=search_fn, filter_fn=lambda gap, rs: rs
    )

    assert calls == []
    assert result.recommendations == []


def test_recommend_goal_keeps_deduped_gap_as_empty_rather_than_dropping_it(session, collection):
    session.add(
        ContentLog(
            source_path="https://arxiv.org/pdf/1706.03762",
            source_type="paper",
            ingested_at=datetime.now(timezone.utc),
            extracted_concepts=json.dumps([]),
        )
    )
    _seed_goal(session, "training", ["gradient accumulation"])
    search_fn = _fake_search({
        "gradient accumulation": [_result("https://arxiv.org/abs/1706.03762")],
    })

    result = recommend_goal(
        session, collection, "training", search_fn=search_fn, filter_fn=lambda gap, rs: rs
    )

    assert len(result.recommendations) == 1
    assert result.recommendations[0].gap == "gradient accumulation"
    assert result.recommendations[0].results == []
    assert result.recommendations[0].error is None


def test_recommend_goal_isolates_a_failing_search_to_its_own_gap(session, collection):
    _seed_goal(session, "training", ["alpha gap", "beta gap"])

    def search_fn(query, k=5):
        if query == "alpha gap":
            raise RuntimeError("boom")
        return [_result("https://example.com/beta")]

    result = recommend_goal(
        session, collection, "training", top=2,
        search_fn=search_fn, filter_fn=lambda gap, rs: rs,
    )

    by_gap = {r.gap: r for r in result.recommendations}
    assert "boom" in by_gap["alpha gap"].error
    assert by_gap["alpha gap"].results == []
    assert by_gap["beta gap"].error is None
    assert len(by_gap["beta gap"].results) == 1


def test_recommend_goal_isolates_a_failing_filter_to_its_own_gap(session, collection):
    _seed_goal(session, "training", ["alpha gap", "beta gap"])
    search_fn = _fake_search({
        "alpha gap": [_result("https://example.com/a")],
        "beta gap": [_result("https://example.com/b")],
    })

    def filter_fn(gap, results):
        if gap == "alpha gap":
            raise RuntimeError("filter exploded")
        return results

    result = recommend_goal(
        session, collection, "training", top=2, search_fn=search_fn, filter_fn=filter_fn
    )

    by_gap = {r.gap: r for r in result.recommendations}
    assert "filter exploded" in by_gap["alpha gap"].error
    assert by_gap["beta gap"].error is None


def test_build_recommend_graph_has_expected_nodes(session, collection):
    app = build_recommend_graph(session, collection)

    assert set(app.get_graph().nodes) >= {
        "compute_gaps", "rank_gaps", "search", "dedup", "filter_relevance",
    }
