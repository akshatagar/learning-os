from dataclasses import dataclass
from typing import Literal

MATCH_THRESHOLD = 0.85
NEW_THRESHOLD = 0.65
DEFAULT_K = 5


@dataclass
class ResolutionResult:
    decision: Literal["match", "new", "queued"]
    concept_id: int | None


def _query_neighbors(collection, candidate_name, k):
    if collection.count() == 0:
        return []

    n_results = min(k, collection.count())
    results = collection.query(query_texts=[candidate_name], n_results=n_results)

    return [
        {"id": int(id_), "name": name, "similarity_score": 1 - distance}
        for id_, name, distance in zip(
            results["ids"][0], results["documents"][0], results["distances"][0]
        )
    ]
