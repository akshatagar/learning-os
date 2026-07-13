import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import ollama

from storage.models import AdjudicationLog, Concept

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


ADJUDICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["match", "new", "uncertain"]},
        "matched_concept_id": {"type": ["integer", "null"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["decision", "matched_concept_id", "confidence", "reasoning"],
}


def _build_prompt(candidate_name, candidate_description, neighbors):
    neighbor_lines = "\n".join(
        f'- id={n["id"]}, name="{n["name"]}", similarity={n["similarity_score"]:.3f}'
        for n in neighbors
    ) or "(no existing concepts yet)"
    description_line = (
        f"\nDescription: {candidate_description}" if candidate_description else ""
    )
    return (
        "You are deciding whether a candidate concept extracted from a document "
        "matches an existing concept in a knowledge base, is a genuinely new "
        "concept, or is too uncertain to decide.\n\n"
        f'Candidate concept: "{candidate_name}"{description_line}\n\n'
        f"Closest existing concepts:\n{neighbor_lines}\n\n"
        "Respond with your decision (match/new/uncertain), the id of the "
        "matched concept if decision is match (else null), your confidence "
        "0-1, and brief reasoning."
    )


def call_ollama_adjudicate(candidate_name, candidate_description, neighbors):
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[
            {
                "role": "user",
                "content": _build_prompt(candidate_name, candidate_description, neighbors),
            }
        ],
        format=ADJUDICATION_SCHEMA,
        # This machine's GPU (2GB VRAM) crashes Ollama's CUDA offload for this
        # model ("CUDA error: shared object initialization failed"); CPU-only
        # inference is reliable, so GPU offload is disabled here.
        options={"num_gpu": 0},
    )
    return json.loads(response["message"]["content"])


def resolve_candidate(
    session, collection, candidate_name,
    candidate_category=None, candidate_description=None, source_type=None,
    k=DEFAULT_K, adjudicate_fn=call_ollama_adjudicate,
):
    neighbors = _query_neighbors(collection, candidate_name, k)
    adjudication = adjudicate_fn(candidate_name, candidate_description, neighbors)
    decision = adjudication["decision"]
    confidence = adjudication["confidence"]

    session.add(AdjudicationLog(
        candidate_name=candidate_name,
        candidate_description=candidate_description,
        retrieved_neighbors=json.dumps(neighbors),
        model_decision=decision,
        model_confidence=confidence,
        model_reasoning=adjudication["reasoning"],
        created_at=datetime.now(timezone.utc),
    ))

    if decision == "match" and confidence >= MATCH_THRESHOLD:
        concept = session.get(Concept, adjudication["matched_concept_id"])
        concept.confidence_score = min(1.0, (concept.confidence_score or 0.0) + 0.05)
        concept.last_reinforced = datetime.now(timezone.utc)
        session.commit()
        return ResolutionResult(decision="match", concept_id=concept.id)

    if decision == "new" and confidence >= NEW_THRESHOLD:
        concept = Concept(
            name=candidate_name,
            category=candidate_category,
            confidence_score=confidence,
            source_type=source_type,
            first_seen=datetime.now(timezone.utc),
            last_reinforced=datetime.now(timezone.utc),
        )
        session.add(concept)
        session.commit()

        collection.add(ids=[str(concept.id)], documents=[candidate_name])
        concept.embedding_id = str(concept.id)
        session.commit()

        return ResolutionResult(decision="new", concept_id=concept.id)

    raise NotImplementedError("queued routing added in the next task")
