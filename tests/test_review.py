import pytest
from sqlalchemy import select


from resolution.review import (
    format_entry,
    pending_entries,
    resolve_entry,
    run_review_loop,
)
from storage.models import AdjudicationLog, Concept, MergeQueue


def test_merge_queue_stores_adjudication_link_and_source_type(session):
    log = AdjudicationLog(candidate_name="beam search", model_decision="uncertain")
    session.add(log)
    session.flush()

    entry = MergeQueue(
        candidate_name="beam search",
        candidate_category="decoding",
        status="pending",
        adjudication_log_id=log.id,
        source_type="note",
    )
    session.add(entry)
    session.commit()

    stored = session.get(MergeQueue, entry.id)
    assert stored.adjudication_log_id == log.id
    assert stored.source_type == "note"


def test_pending_entries_returns_only_pending_ordered_by_id(session):
    session.add_all([
        MergeQueue(candidate_name="a", status="pending"),
        MergeQueue(candidate_name="b", status="rejected"),
        MergeQueue(candidate_name="c", status="pending"),
    ])
    session.commit()

    entries = pending_entries(session)

    assert [e.candidate_name for e in entries] == ["a", "c"]


def test_dismiss_marks_rejected_and_creates_no_concept(session, collection):
    entry = MergeQueue(candidate_name="vague thing", status="pending")
    session.add(entry)
    session.commit()

    result = resolve_entry(session, collection, entry, "dismiss")

    assert result.action == "dismiss"
    assert result.concept_id is None
    assert entry.status == "rejected"
    assert session.scalars(select(Concept)).all() == []


def test_dismiss_backfills_human_resolution_on_linked_log(session, collection):
    log = AdjudicationLog(candidate_name="vague thing", model_decision="uncertain")
    session.add(log)
    session.flush()
    entry = MergeQueue(candidate_name="vague thing", status="pending", adjudication_log_id=log.id)
    session.add(entry)
    session.commit()

    resolve_entry(session, collection, entry, "dismiss")

    assert log.human_resolution == "rejected"
    assert log.resolved_at is not None


def test_resolve_entry_without_linked_log_does_not_raise(session, collection):
    entry = MergeQueue(candidate_name="orphan", status="pending", adjudication_log_id=None)
    session.add(entry)
    session.commit()

    resolve_entry(session, collection, entry, "dismiss")

    assert entry.status == "rejected"


def test_resolve_entry_rejects_unknown_action(session, collection):
    entry = MergeQueue(candidate_name="whatever", status="pending")
    session.add(entry)
    session.commit()

    with pytest.raises(ValueError):
        resolve_entry(session, collection, entry, "explode")


def test_merge_reinforces_target_and_marks_approved_merge(session, collection):
    target = Concept(name="attention mechanism", confidence_score=0.5)
    session.add(target)
    session.commit()
    entry = MergeQueue(candidate_name="multi-head attention", status="pending")
    session.add(entry)
    session.commit()

    result = resolve_entry(session, collection, entry, "merge", target_concept_id=target.id)

    assert result.action == "merge"
    assert result.concept_id == target.id
    assert target.confidence_score == pytest.approx(0.55)
    assert target.last_reinforced is not None
    assert entry.status == "approved_merge"


def test_merge_caps_confidence_at_one(session, collection):
    target = Concept(name="attention mechanism", confidence_score=0.99)
    session.add(target)
    session.commit()
    entry = MergeQueue(candidate_name="multi-head attention", status="pending")
    session.add(entry)
    session.commit()

    resolve_entry(session, collection, entry, "merge", target_concept_id=target.id)

    assert target.confidence_score == 1.0


def test_merge_without_target_raises(session, collection):
    entry = MergeQueue(candidate_name="multi-head attention", status="pending")
    session.add(entry)
    session.commit()

    with pytest.raises(ValueError):
        resolve_entry(session, collection, entry, "merge")


def test_merge_into_missing_concept_raises(session, collection):
    entry = MergeQueue(candidate_name="multi-head attention", status="pending")
    session.add(entry)
    session.commit()

    with pytest.raises(ValueError):
        resolve_entry(session, collection, entry, "merge", target_concept_id=9999)


def test_new_inserts_concept_with_human_confidence_and_embeds(session, collection):
    entry = MergeQueue(
        candidate_name="rotary positional embeddings",
        candidate_category="positional encoding",
        status="pending",
        source_type="note",
    )
    session.add(entry)
    session.commit()

    result = resolve_entry(session, collection, entry, "new")

    assert result.action == "new"
    concept = session.get(Concept, result.concept_id)
    assert concept.name == "rotary positional embeddings"
    assert concept.category == "positional encoding"
    assert concept.source_type == "note"
    assert concept.confidence_score == 1.0
    assert concept.first_seen is not None
    assert concept.last_reinforced is not None
    assert concept.embedding_id == str(concept.id)
    assert entry.status == "approved_new"


def test_new_adds_exactly_one_vector_to_chroma(session, collection):
    entry = MergeQueue(candidate_name="rotary positional embeddings", status="pending")
    session.add(entry)
    session.commit()
    before = collection.count()

    result = resolve_entry(session, collection, entry, "new")

    assert collection.count() == before + 1
    assert collection.get(ids=[str(result.concept_id)])["documents"] == [
        "rotary positional embeddings"
    ]


def test_format_entry_lists_numbered_neighbors():
    entry = MergeQueue(
        id=7,
        candidate_name="multi-head attention",
        candidate_category="architecture",
        llm_confidence=0.62,
        llm_reasoning="May be a variant of a broader concept.",
        status="pending",
    )
    neighbors = [
        {"id": 12, "name": "attention mechanism", "similarity_score": 0.81},
        {"id": 19, "name": "self-attention", "similarity_score": 0.74},
    ]

    text = format_entry(entry, neighbors, position=1, total=3)

    assert "Pending 1/3" in text
    assert "queue id 7" in text
    assert "multi-head attention" in text
    assert "architecture" in text
    assert "0.62" in text
    assert "May be a variant of a broader concept." in text
    assert '1. #12 "attention mechanism"' in text
    assert '2. #19 "self-attention"' in text
    assert "[1-2] merge into that" in text


def test_format_entry_offers_no_merge_when_no_neighbors():
    entry = MergeQueue(id=8, candidate_name="rotary embeddings", status="pending")

    text = format_entry(entry, [], position=1, total=1)

    assert "merge into that" not in text
    assert "[n] insert as new" in text
    assert "[d] dismiss" in text


def _scripted(*keys):
    responses = iter(keys)

    def input_fn(prompt=""):
        return next(responses)

    return input_fn


def test_review_loop_applies_each_action(session, collection):
    target = Concept(name="attention mechanism", confidence_score=0.5)
    session.add(target)
    session.commit()
    collection.add(ids=[str(target.id)], documents=["attention mechanism"])
    session.add_all([
        MergeQueue(candidate_name="multi-head attention", status="pending"),
        MergeQueue(candidate_name="rotary embeddings", status="pending"),
        MergeQueue(candidate_name="vague thing", status="pending"),
        MergeQueue(candidate_name="later thing", status="pending"),
    ])
    session.commit()

    counts = run_review_loop(session, collection, input_fn=_scripted("1", "n", "d", "s"))

    assert counts == {"merged": 1, "new": 1, "dismissed": 1, "skipped": 1}
    statuses = [e.status for e in session.scalars(select(MergeQueue).order_by(MergeQueue.id))]
    assert statuses == ["approved_merge", "approved_new", "rejected", "pending"]


def test_review_loop_reprompts_on_unrecognized_key(session, collection):
    session.add(MergeQueue(candidate_name="vague thing", status="pending"))
    session.commit()

    counts = run_review_loop(session, collection, input_fn=_scripted("zzz", "d"))

    assert counts["dismissed"] == 1


def test_review_loop_quit_leaves_remaining_pending(session, collection):
    session.add_all([
        MergeQueue(candidate_name="first", status="pending"),
        MergeQueue(candidate_name="second", status="pending"),
    ])
    session.commit()

    counts = run_review_loop(session, collection, input_fn=_scripted("d", "q"))

    assert counts["dismissed"] == 1
    statuses = [e.status for e in session.scalars(select(MergeQueue).order_by(MergeQueue.id))]
    assert statuses == ["rejected", "pending"]


def test_review_loop_treats_eof_as_quit(session, collection):
    session.add(MergeQueue(candidate_name="first", status="pending"))
    session.commit()

    def input_fn(prompt=""):
        raise EOFError

    counts = run_review_loop(session, collection, input_fn=input_fn)

    assert counts == {"merged": 0, "new": 0, "dismissed": 0, "skipped": 0}


def test_review_loop_handles_empty_queue(session, collection):
    counts = run_review_loop(session, collection, input_fn=_scripted())

    assert counts == {"merged": 0, "new": 0, "dismissed": 0, "skipped": 0}
