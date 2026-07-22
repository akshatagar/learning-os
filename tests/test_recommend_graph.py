from goals.gaps import GapResult
from recommend.graph import rank_gaps


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
