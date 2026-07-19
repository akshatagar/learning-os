import json

from storage.models import Concept, ContentLog
from ingestion.papers import build_resolve_candidates_node, build_write_content_log_node


def test_resolve_candidates_node_forwards_note_source_type(session, collection):
    def fake_adjudicate(candidate_name, candidate_description, neighbors):
        return {
            "decision": "new",
            "matched_concept_id": None,
            "confidence": 0.8,
            "reasoning": "novel concept",
        }

    node = build_resolve_candidates_node(
        session, collection, adjudicate_fn=fake_adjudicate, source_type="note"
    )
    state = {
        "candidates": [
            {"name": "spaced repetition", "category": "learning", "extraction_confidence": 0.9},
        ]
    }

    result = node(state)

    assert len(result["concept_ids"]) == 1
    concept = session.get(Concept, result["concept_ids"][0])
    assert concept.source_type == "note"


def test_write_content_log_node_writes_note_source_type(session):
    node = build_write_content_log_node(session, source_type="note")
    state = {"source": "notes/transformers.md", "concept_ids": [1, 2]}

    result = node(state)

    log = session.get(ContentLog, result["content_log_id"])
    assert log.source_path == "notes/transformers.md"
    assert log.source_type == "note"
    assert json.loads(log.extracted_concepts) == [1, 2]
