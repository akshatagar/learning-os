import os

import pytest

from recommend.search import SearchResult, _parse_response, search


def test_parse_response_maps_tavily_fields():
    payload = {
        "results": [
            {
                "title": "Gradient Accumulation Explained",
                "url": "https://example.com/ga",
                "content": "A short snippet.",
                "score": 0.94,
            }
        ]
    }

    results = _parse_response(payload)

    assert results == [
        SearchResult(
            title="Gradient Accumulation Explained",
            url="https://example.com/ga",
            snippet="A short snippet.",
            score=0.94,
        )
    ]


def test_parse_response_tolerates_missing_optional_fields():
    payload = {"results": [{"url": "https://example.com/x"}]}

    results = _parse_response(payload)

    assert results == [
        SearchResult(title="", url="https://example.com/x", snippet="", score=0.0)
    ]


def test_parse_response_returns_empty_for_no_results():
    assert _parse_response({"results": []}) == []


def test_search_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        search("gradient accumulation")


def test_search_raises_for_empty_api_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        search("gradient accumulation")


def test_search_returns_well_formed_results_from_tavily():
    """Live round-trip against the real Tavily API."""
    if not os.environ.get("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY not set")

    results = search("gradient accumulation deep learning", k=3)

    assert 0 < len(results) <= 3
    for result in results:
        assert result.url.startswith("http")
        assert isinstance(result.title, str)
        assert isinstance(result.score, float)
