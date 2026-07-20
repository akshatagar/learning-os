from storage.models import AdjudicationLog, MergeQueue


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
