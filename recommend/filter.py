import json

import ollama

from recommend.search import SearchResult

FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "keep": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["keep"],
}


def _build_filter_prompt(gap: str, results: list[SearchResult]) -> str:
    listing = "\n".join(
        f"[{index}] {result.title} — {result.snippet}"
        for index, result in enumerate(results)
    )
    return (
        "You are selecting reading material for someone who wants to learn a "
        "specific technical concept.\n\n"
        f"Concept to learn: {gap}\n\n"
        f"Candidate results:\n{listing}\n\n"
        "Return the indices of the results that would actually teach this "
        "concept. Keep explanations, tutorials, and papers about the concept. "
        "Drop API reference pages, unrelated results, and pages that merely "
        "mention the term in passing. Return an empty list if none qualify."
    )


def call_ollama_filter(gap: str, results: list[SearchResult]) -> list[int]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": _build_filter_prompt(gap, results)}],
        format=FILTER_SCHEMA,
    )
    return json.loads(response["message"]["content"])["keep"]


def filter_relevant(
    gap: str, results: list[SearchResult], judge_fn=call_ollama_filter
) -> list[SearchResult]:
    if not results:
        return []
    keep = set(judge_fn(gap, results))
    return [result for index, result in enumerate(results) if index in keep]
