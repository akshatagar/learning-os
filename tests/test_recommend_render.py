from goals.gaps import GapResult
from recommend.graph import GapRecommendation, RecommendResult
from recommend.render import format_recommendations
from recommend.search import SearchResult


def _result(url, title):
    return SearchResult(title=title, url=url, snippet="s", score=0.9)


def _wrap(recommendations, present=(), weak=(), missing=()):
    return RecommendResult(
        category="training",
        gap_result=GapResult(
            present=list(present), weak=list(weak), missing=list(missing), scores={}
        ),
        recommendations=recommendations,
    )


def test_format_shows_header_with_coverage_counts():
    output = format_recommendations(
        _wrap([], present=["a"], weak=["b"], missing=["c", "d"])
    )

    assert "training" in output
    assert "1 present" in output
    assert "1 weak" in output
    assert "2 missing" in output


def test_format_lists_each_gap_with_score_and_links():
    recommendation = GapRecommendation(
        gap="gradient accumulation",
        score=0.68,
        results=[_result("https://example.com/ga", "Gradient Accumulation Explained")],
    )

    output = format_recommendations(
        _wrap([recommendation], missing=["gradient accumulation"])
    )

    assert "gradient accumulation" in output
    assert "0.68" in output
    assert "https://example.com/ga" in output
    assert "Gradient Accumulation Explained" in output


def test_format_reports_an_empty_gap_explicitly():
    recommendation = GapRecommendation(gap="speculative decoding", score=0.61, results=[])

    output = format_recommendations(
        _wrap([recommendation], missing=["speculative decoding"])
    )

    assert "speculative decoding" in output
    assert "nothing new" in output.lower()


def test_format_reports_a_gap_error():
    recommendation = GapRecommendation(
        gap="alpha", score=0.5, results=[], error="search failed: boom"
    )

    output = format_recommendations(_wrap([recommendation], missing=["alpha"]))

    assert "search failed: boom" in output


def test_format_reports_a_fully_covered_goal():
    output = format_recommendations(_wrap([], present=["a", "b"]))

    assert "no gaps" in output.lower()
