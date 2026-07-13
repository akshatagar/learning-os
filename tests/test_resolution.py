from datetime import datetime

import pytest
from sqlalchemy import select

from resolution.adjudicate import _query_neighbors, call_ollama_adjudicate, resolve_candidate
from storage.models import AdjudicationLog, Concept, MergeQueue


def test_query_neighbors_returns_empty_list_when_collection_is_empty(collection):
    neighbors = _query_neighbors(collection, "gradient descent", k=5)
    assert neighbors == []


def test_query_neighbors_returns_top_k_with_similarity_scores(collection):
    collection.add(ids=["1"], documents=["gradient descent"])
    collection.add(ids=["2"], documents=["watercolor painting"])

    neighbors = _query_neighbors(collection, "backpropagation", k=5)

    assert len(neighbors) == 2
    top = neighbors[0]
    assert top["id"] == 1
    assert top["name"] == "gradient descent"
    assert 0.0 < top["similarity_score"] <= 1.0


def test_call_ollama_adjudicate_matches_identical_candidate_name():
    neighbors = [{"id": 1, "name": "gradient descent", "similarity_score": 1.0}]

    result = call_ollama_adjudicate("gradient descent", None, neighbors)

    assert result["decision"] == "match"
    assert result["matched_concept_id"] == 1
    assert result["confidence"] >= 0.5
    assert isinstance(result["reasoning"], str) and result["reasoning"]


def test_confident_match_reinforces_existing_concept(session, collection):
    existing = Concept(name="gradient descent", confidence_score=0.5)
    session.add(existing)
    session.commit()
    collection.add(ids=[str(existing.id)], documents=["gradient descent"])
    existing.embedding_id = str(existing.id)
    session.commit()

    def fake_adjudicate(candidate_name, candidate_description, neighbors):
        return {
            "decision": "match",
            "matched_concept_id": existing.id,
            "confidence": 0.9,
            "reasoning": "same concept, reworded",
        }

    result = resolve_candidate(
        session, collection, "gradient descent (SGD)",
        adjudicate_fn=fake_adjudicate,
    )

    assert result.decision == "match"
    assert result.concept_id == existing.id

    session.refresh(existing)
    assert existing.confidence_score == pytest.approx(0.55)
    assert existing.last_reinforced is not None

    log = session.scalar(
        select(AdjudicationLog).where(
            AdjudicationLog.candidate_name == "gradient descent (SGD)"
        )
    )
    assert log is not None
    assert log.model_decision == "match"
    assert log.model_confidence == 0.9


def test_confident_new_creates_concept_and_embeds_it(session, collection):
    def fake_adjudicate(candidate_name, candidate_description, neighbors):
        return {
            "decision": "new",
            "matched_concept_id": None,
            "confidence": 0.8,
            "reasoning": "no close match in KB",
        }

    result = resolve_candidate(
        session, collection, "diffusion models",
        candidate_category="ML", source_type="paper",
        adjudicate_fn=fake_adjudicate,
    )

    assert result.decision == "new"
    assert result.concept_id is not None

    concept = session.get(Concept, result.concept_id)
    assert concept.name == "diffusion models"
    assert concept.category == "ML"
    assert concept.source_type == "paper"
    assert concept.confidence_score == 0.8
    assert concept.embedding_id == str(concept.id)

    stored = collection.get(ids=[str(concept.id)])
    assert stored["documents"] == ["diffusion models"]

    log = session.scalar(
        select(AdjudicationLog).where(AdjudicationLog.candidate_name == "diffusion models")
    )
    assert log is not None
    assert log.model_decision == "new"


def test_uncertain_decision_queues_for_review(session, collection):
    def fake_adjudicate(candidate_name, candidate_description, neighbors):
        return {
            "decision": "uncertain",
            "matched_concept_id": None,
            "confidence": 0.5,
            "reasoning": "ambiguous",
        }

    result = resolve_candidate(
        session, collection, "attention mechanism",
        adjudicate_fn=fake_adjudicate,
    )

    assert result.decision == "queued"
    assert result.concept_id is None

    queued = session.scalar(
        select(MergeQueue).where(MergeQueue.candidate_name == "attention mechanism")
    )
    assert queued is not None
    assert queued.status == "pending"
    assert session.query(Concept).count() == 0


def test_low_confidence_match_queues_instead_of_reinforcing(session, collection):
    existing = Concept(name="gradient descent", confidence_score=0.5)
    session.add(existing)
    session.commit()

    def fake_adjudicate(candidate_name, candidate_description, neighbors):
        return {
            "decision": "match",
            "matched_concept_id": existing.id,
            "confidence": 0.6,
            "reasoning": "possibly related",
        }

    result = resolve_candidate(
        session, collection, "SGD",
        adjudicate_fn=fake_adjudicate,
    )

    assert result.decision == "queued"
    session.refresh(existing)
    assert existing.confidence_score == 0.5

    queued = session.scalar(
        select(MergeQueue).where(MergeQueue.candidate_name == "SGD")
    )
    assert queued is not None
    assert queued.matched_concept_id == existing.id
