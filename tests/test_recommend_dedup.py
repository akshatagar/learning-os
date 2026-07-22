import json
from datetime import datetime, timezone

import pytest

from recommend.dedup import exclude_ingested, normalize_url
from recommend.search import SearchResult
from storage.models import ContentLog


def _result(url):
    return SearchResult(title="t", url=url, snippet="s", score=1.0)


@pytest.mark.parametrize(
    "left,right",
    [
        ("https://arxiv.org/pdf/1706.03762", "https://arxiv.org/abs/1706.03762"),
        ("https://arxiv.org/abs/1706.03762v5", "https://arxiv.org/abs/1706.03762"),
        ("http://www.arxiv.org/abs/1706.03762?utm=x", "https://arxiv.org/pdf/1706.03762"),
        ("https://arxiv.org/html/1706.03762v2", "https://arxiv.org/abs/1706.03762"),
        (
            "https://blog.eleuther.ai/rotary-embeddings/",
            "https://blog.eleuther.ai/rotary-embeddings",
        ),
        ("http://example.com/a", "https://www.example.com/a"),
        ("https://example.com/a#section", "https://example.com/a"),
    ],
)
def test_normalize_url_treats_equivalent_urls_as_equal(left, right):
    assert normalize_url(left) == normalize_url(right)


@pytest.mark.parametrize(
    "left,right",
    [
        ("https://arxiv.org/abs/1706.03762", "https://arxiv.org/abs/2104.09864"),
        ("https://example.com/a", "https://example.com/b"),
        ("https://example.com/a", "https://other.com/a"),
    ],
)
def test_normalize_url_keeps_distinct_urls_distinct(left, right):
    assert normalize_url(left) != normalize_url(right)


def test_normalize_url_leaves_local_paths_alone():
    assert normalize_url("notes/attention.md") == "notes/attention.md"


def test_exclude_ingested_drops_paper_under_a_different_arxiv_path(session):
    session.add(
        ContentLog(
            source_path="https://arxiv.org/pdf/1706.03762",
            source_type="paper",
            ingested_at=datetime.now(timezone.utc),
            extracted_concepts=json.dumps([]),
        )
    )
    session.commit()

    results = [
        _result("https://arxiv.org/abs/1706.03762"),
        _result("https://example.com/new"),
    ]

    assert [r.url for r in exclude_ingested(session, results)] == [
        "https://example.com/new"
    ]


def test_exclude_ingested_keeps_everything_when_log_is_empty(session):
    results = [_result("https://example.com/a"), _result("https://example.com/b")]

    assert exclude_ingested(session, results) == results


def test_exclude_ingested_ignores_note_rows_holding_local_paths(session):
    session.add(
        ContentLog(
            source_path="notes/attention.md",
            source_type="note",
            ingested_at=datetime.now(timezone.utc),
            extracted_concepts=json.dumps([]),
        )
    )
    session.commit()

    results = [_result("https://example.com/a")]

    assert exclude_ingested(session, results) == results
