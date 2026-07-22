import re
from urllib.parse import urlparse

from sqlalchemy import select

from recommend.search import SearchResult
from storage.models import ContentLog

_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")

    if host == "arxiv.org":
        match = _ARXIV_ID.search(path)
        if match:
            return f"arxiv:{match.group(1)}"

    return f"{host}{path}"


def exclude_ingested(session, results: list[SearchResult]) -> list[SearchResult]:
    ingested = {
        normalize_url(path)
        for path in session.scalars(select(ContentLog.source_path)).all()
        if path
    }
    return [result for result in results if normalize_url(result.url) not in ingested]
