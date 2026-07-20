import pytest
from sqlalchemy import select

from resolution.review import pending_entries, resolve_entry
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
