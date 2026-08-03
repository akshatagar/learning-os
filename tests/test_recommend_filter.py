from recommend.filter import (
    MAX_PER_GAP,
    _build_filter_prompt,
    call_ollama_filter,
    filter_relevant,
)
from recommend.search import SearchResult


def _result(title, url="https://example.com/x"):
    return SearchResult(title=title, url=url, snippet="snippet", score=0.9)


def test_filter_relevant_keeps_only_selected_indices():
    results = [_result("a"), _result("b"), _result("c")]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [0, 2])

    assert [r.title for r in kept] == ["a", "c"]


def test_filter_relevant_preserves_original_order():
    results = [_result("a"), _result("b"), _result("c")]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [2, 0])

    assert [r.title for r in kept] == ["a", "c"]


def test_filter_relevant_ignores_out_of_range_indices():
    results = [_result("a"), _result("b")]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [0, 7, -1])

    assert [r.title for r in kept] == ["a"]


def test_filter_relevant_deduplicates_repeated_indices():
    results = [_result("a"), _result("b")]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [1, 1])

    assert [r.title for r in kept] == ["b"]


def test_filter_relevant_returns_empty_for_no_results():
    calls = []

    def judge_fn(gap, rs):
        calls.append(1)
        return []

    kept = filter_relevant("some gap", [], judge_fn=judge_fn)

    assert kept == []
    assert calls == []


def test_filter_relevant_can_drop_everything():
    results = [_result("a"), _result("b")]

    assert filter_relevant("some gap", results, judge_fn=lambda gap, rs: []) == []


def test_filter_relevant_caps_results_at_max_per_gap():
    results = [_result(name) for name in "abcde"]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [0, 1, 2, 3, 4])

    assert len(kept) == MAX_PER_GAP


def test_filter_relevant_truncation_keeps_the_highest_ranked():
    """Incoming order is Tavily's ranking, so truncation must keep the front."""
    results = [_result(name) for name in "abcde"]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [1, 2, 3, 4])

    assert [r.title for r in kept] == ["b", "c", "d"]


def test_filter_relevant_leaves_a_short_selection_alone():
    results = [_result(name) for name in "abcde"]

    kept = filter_relevant("some gap", results, judge_fn=lambda gap, rs: [0, 4])

    assert [r.title for r in kept] == ["a", "e"]


def test_build_filter_prompt_indexes_results_and_names_the_gap():
    prompt = _build_filter_prompt(
        "speculative decoding", [_result("A Guide"), _result("B Guide")]
    )

    assert "speculative decoding" in prompt
    assert "[0] A Guide" in prompt
    assert "[1] B Guide" in prompt


def test_call_ollama_filter_returns_valid_indices():
    """Live round-trip against a running Ollama."""
    results = [
        _result("Gradient Accumulation Explained, Step by Step"),
        _result("Best coffee shops in Lisbon"),
    ]

    keep = call_ollama_filter("gradient accumulation", results)

    assert isinstance(keep, list)
    assert all(isinstance(index, int) for index in keep)
    assert all(0 <= index < len(results) for index in keep)
