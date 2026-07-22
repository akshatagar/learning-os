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
    scores: dict[str, float]


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
    scores: dict[str, float] = {}

    for requirement in requirements:
        if collection.count() == 0:
            scores[requirement] = 0.0
            missing.append(requirement)
            continue

        results = collection.query(query_texts=[requirement], n_results=1)
        similarity = 1 - results["distances"][0][0]
        scores[requirement] = similarity
        if similarity < similarity_threshold:
            missing.append(requirement)
            continue

        concept_id = int(results["ids"][0][0])
        concept = session.get(Concept, concept_id)
        if concept is None:
            raise ValueError(
                f"Chroma returned concept id {concept_id} with no matching row"
            )

        if (concept.confidence_score or 0.0) < confidence_threshold:
            weak.append(requirement)
        else:
            present.append(requirement)

    return GapResult(present=present, weak=weak, missing=missing, scores=scores)
