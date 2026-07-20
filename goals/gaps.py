import json
from dataclasses import dataclass

from storage.models import Concept

SIMILARITY_THRESHOLD = 0.70
CONFIDENCE_THRESHOLD = 0.7


@dataclass
class GapResult:
    present: list[str]
    weak: list[str]
    missing: list[str]


def concept_gaps(
    session,
    collection,
    goal,
    similarity_threshold=SIMILARITY_THRESHOLD,
    confidence_threshold=CONFIDENCE_THRESHOLD,
) -> GapResult:
    requirements = json.loads(goal.concept_requirements)
    present: list[str] = []
    weak: list[str] = []
    missing: list[str] = []

    for requirement in requirements:
        if collection.count() == 0:
            missing.append(requirement)
            continue

        results = collection.query(query_texts=[requirement], n_results=1)
        similarity = 1 - results["distances"][0][0]
        if similarity < similarity_threshold:
            missing.append(requirement)
            continue

        present.append(requirement)

    return GapResult(present=present, weak=weak, missing=missing)
