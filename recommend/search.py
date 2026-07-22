import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()

TAVILY_ENDPOINT = "https://api.tavily.com/search"
REQUEST_TIMEOUT = 30.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float


def _parse_response(payload: dict) -> list[SearchResult]:
    return [
        SearchResult(
            title=item.get("title", ""),
            url=item["url"],
            snippet=item.get("content", ""),
            score=float(item.get("score", 0.0)),
        )
        for item in payload.get("results", [])
    ]


def search(query: str, k: int = 5) -> list[SearchResult]:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Add it to .env (see .env.example)."
        )

    response = httpx.post(
        TAVILY_ENDPOINT,
        json={
            "api_key": api_key,
            "query": query,
            "max_results": k,
            "search_depth": "basic",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return _parse_response(response.json())
