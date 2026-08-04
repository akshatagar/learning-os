import pytest
from sqlalchemy import select


from resolution.adjudicate import MATCH_THRESHOLD, NEW_THRESHOLD
from resolution.review import (
    LOG_PAGE,
    adjudication_count,
    adjudication_views,
    agreement_tally,
    format_entry,
    next_pending,
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


def test_next_pending_is_none_on_an_empty_queue(session, collection):
    assert next_pending(session, collection) is None


def test_next_pending_serves_the_lowest_pending_id(session, collection):
    session.add_all([
        MergeQueue(candidate_name="already done", status="approved_new"),
        MergeQueue(candidate_name="first", status="pending"),
        MergeQueue(candidate_name="second", status="pending"),
    ])
    session.commit()

    view = next_pending(session, collection)

    assert view.entry.candidate_name == "first"
    assert view.remaining == 2


def test_next_pending_returns_live_neighbors_with_scores(session, collection):
    concept = Concept(name="retrieval augmentation")
    session.add(concept)
    session.flush()
    collection.add(ids=[str(concept.id)], documents=["retrieval augmentation"])
    session.add(MergeQueue(candidate_name="retrieval augmentation", status="pending"))
    session.commit()

    view = next_pending(session, collection)

    assert [n["id"] for n in view.neighbors] == [concept.id]
    assert view.neighbors[0]["similarity_score"] > 0.9


def test_next_pending_sees_a_concept_created_by_the_previous_resolve(
    session, collection
):
    """The second entry must be mergeable into a concept the first one made.

    Snapshotting the neighbour list when the surface opens would hide it, and
    the operator would create a duplicate they had no way to see.
    """
    first = MergeQueue(candidate_name="beam search", status="pending")
    second = MergeQueue(candidate_name="beam search", status="pending")
    session.add_all([first, second])
    session.commit()

    resolve_entry(session, collection, first, "new")

    view = next_pending(session, collection)

    assert view.entry.id == second.id
    assert [n["name"] for n in view.neighbors] == ["beam search"]


def test_next_pending_carries_the_model_decision_from_the_linked_log(
    session, collection
):
    log = AdjudicationLog(candidate_name="beam search", model_decision="match")
    session.add(log)
    session.flush()
    session.add(MergeQueue(
        candidate_name="beam search", status="pending", adjudication_log_id=log.id
    ))
    session.commit()

    assert next_pending(session, collection).model_decision == "match"


def test_next_pending_has_no_model_decision_without_a_log(session, collection):
    session.add(MergeQueue(candidate_name="beam search", status="pending"))
    session.commit()

    assert next_pending(session, collection).model_decision is None


def _resolved_log(decision, resolution):
    return AdjudicationLog(
        candidate_name="beam search",
        model_decision=decision,
        human_resolution=resolution,
    )


def test_agreement_tally_is_zero_on_an_empty_log(session):
    assert agreement_tally(session) == {
        "agreed": 0, "disagreed": 0, "dismissed": 0
    }


def test_agreement_tally_counts_matching_calls_as_agreed(session):
    session.add_all([
        _resolved_log("match", "approved_merge"),
        _resolved_log("new", "approved_new"),
    ])
    session.commit()

    assert agreement_tally(session)["agreed"] == 2


def test_agreement_tally_counts_the_other_branch_as_disagreed(session):
    session.add_all([
        _resolved_log("match", "approved_new"),
        _resolved_log("new", "approved_merge"),
    ])
    session.commit()

    tally = agreement_tally(session)
    assert tally["disagreed"] == 2
    assert tally["agreed"] == 0


def test_agreement_tally_counts_a_rejection_apart_from_disagreement(session):
    """Dismissing is not preferring the other branch.

    The human threw the candidate away entirely, which says nothing about
    whether match or new was the better call.
    """
    session.add(_resolved_log("match", "rejected"))
    session.commit()

    tally = agreement_tally(session)
    assert tally == {"agreed": 0, "disagreed": 0, "dismissed": 1}


def test_agreement_tally_ignores_uncertain_and_unresolved_rows(session):
    session.add_all([
        _resolved_log("uncertain", "approved_new"),
        AdjudicationLog(candidate_name="beam search", model_decision="match"),
    ])
    session.commit()

    assert agreement_tally(session) == {
        "agreed": 0, "disagreed": 0, "dismissed": 0
    }


def _pending_with_decision(session, decision):
    log = AdjudicationLog(candidate_name="Attention", model_decision=decision)
    session.add(log)
    session.flush()
    session.add(MergeQueue(
        candidate_name="Attention", status="pending", adjudication_log_id=log.id,
    ))
    session.commit()


def test_a_match_entry_carries_the_match_threshold(session, collection):
    _pending_with_decision(session, "match")

    assert next_pending(session, collection).threshold == MATCH_THRESHOLD


def test_a_new_entry_carries_the_new_threshold(session, collection):
    _pending_with_decision(session, "new")

    assert next_pending(session, collection).threshold == NEW_THRESHOLD


def test_an_uncertain_entry_carries_no_threshold(session, collection):
    """Neither branch was reachable, so the number never had a line to cross."""
    _pending_with_decision(session, "uncertain")

    assert next_pending(session, collection).threshold is None


def test_an_entry_with_no_log_carries_no_threshold(session, collection):
    session.add(MergeQueue(candidate_name="Attention", status="pending"))
    session.commit()

    assert next_pending(session, collection).threshold is None


def _log(session, name, decision, confidence=0.85, human=None):
    log = AdjudicationLog(
        candidate_name=name,
        model_decision=decision,
        model_confidence=confidence,
        model_reasoning="Because.",
        human_resolution=human,
    )
    session.add(log)
    session.commit()
    return log


def test_adjudication_views_are_newest_first(session):
    _log(session, "older", "new")
    _log(session, "newer", "new")

    views = adjudication_views(session)

    assert [v.log.candidate_name for v in views] == ["newer", "older"]


def test_an_unlinked_new_row_was_created_automatically(session):
    _log(session, "Attention Mechanism", "new")

    assert adjudication_views(session)[0].outcome == "created"


def test_an_unlinked_match_row_was_merged_automatically(session):
    _log(session, "multi-head attention", "match")

    assert adjudication_views(session)[0].outcome == "merged"


def test_a_row_with_a_queue_entry_was_queued(session):
    """Read from the link, not re-derived from the thresholds.

    Re-deriving would make every historical row re-report itself if a
    threshold ever moved, in the one surface whose job is to be accurate.
    """
    log = _log(session, "Auto-regressive property", "uncertain", confidence=0.25)
    session.add(MergeQueue(
        candidate_name="Auto-regressive property",
        status="pending",
        adjudication_log_id=log.id,
    ))
    session.commit()

    assert adjudication_views(session)[0].outcome == "queued"


def test_a_high_confidence_row_that_was_queued_still_reads_as_queued(session):
    """The link is the fact; the confidence is not evidence about the outcome."""
    log = _log(session, "Beam search", "new", confidence=0.99)
    session.add(MergeQueue(
        candidate_name="Beam search", status="pending", adjudication_log_id=log.id
    ))
    session.commit()

    assert adjudication_views(session)[0].outcome == "queued"


def test_an_unlinked_uncertain_row_is_an_anomaly(session):
    """resolve_candidate always queues an uncertain call, so this cannot happen.

    Falling through to "created" would put a fabricated outcome in an audit
    trail. It has to read as unknown instead.
    """
    _log(session, "impossible", "uncertain", confidence=0.25)

    assert adjudication_views(session)[0].outcome == "unknown"


def test_a_new_row_carries_the_new_threshold(session):
    _log(session, "Beam search", "new")

    assert adjudication_views(session)[0].threshold == NEW_THRESHOLD


def test_a_match_row_carries_the_match_threshold(session):
    _log(session, "multi-head attention", "match")

    assert adjudication_views(session)[0].threshold == MATCH_THRESHOLD


def test_an_uncertain_row_carries_no_threshold(session):
    """Neither branch was reachable, so the number never had a line to cross."""
    _log(session, "Auto-regressive property", "uncertain", confidence=0.25)

    assert adjudication_views(session)[0].threshold is None


def test_adjudication_views_respect_the_limit(session):
    for index in range(5):
        _log(session, f"candidate {index}", "new")

    assert len(adjudication_views(session, limit=3)) == 3


def test_adjudication_count_ignores_the_limit(session):
    """This is what makes the truncation line honest rather than decorative."""
    for index in range(5):
        _log(session, f"candidate {index}", "new")

    assert len(adjudication_views(session, limit=3)) == 3
    assert adjudication_count(session) == 5


def test_log_page_is_the_default_limit(session):
    assert LOG_PAGE == 100
