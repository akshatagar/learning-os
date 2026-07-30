from datetime import datetime, timezone

from ingestion.history import recent_ingests
from storage.models import ContentLog


def _at(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=timezone.utc)


def test_the_newest_ingest_comes_first(session):
    session.add_all([
        ContentLog(source_path="old.pdf", ingested_at=_at(1)),
        ContentLog(source_path="new.pdf", ingested_at=_at(9)),
    ])
    session.commit()

    assert [e.source_path for e in recent_ingests(session)] == [
        "new.pdf", "old.pdf",
    ]


def test_the_limit_is_honoured(session):
    session.add_all([
        ContentLog(source_path=f"{day}.pdf", ingested_at=_at(day))
        for day in range(1, 6)
    ])
    session.commit()

    assert len(recent_ingests(session, limit=2)) == 2


def test_the_count_is_the_length_of_the_id_array(session):
    session.add(ContentLog(
        source_path="paper.pdf",
        ingested_at=_at(1),
        extracted_concepts="[1, 2, 3, 4]",
    ))
    session.commit()

    assert recent_ingests(session)[0].concept_count == 4


def test_a_missing_concept_array_counts_zero(session):
    session.add(ContentLog(
        source_path="paper.pdf", ingested_at=_at(1), extracted_concepts=None,
    ))
    session.commit()

    assert recent_ingests(session)[0].concept_count == 0


def test_a_malformed_concept_array_counts_zero_without_raising(session):
    """One bad row costs one wrong count, never the whole surface."""
    session.add(ContentLog(
        source_path="paper.pdf",
        ingested_at=_at(1),
        extracted_concepts="{ not json",
    ))
    session.commit()

    assert recent_ingests(session)[0].concept_count == 0


def test_a_json_scalar_counts_zero_rather_than_raising(session):
    session.add(ContentLog(
        source_path="paper.pdf", ingested_at=_at(1), extracted_concepts="7",
    ))
    session.commit()

    assert recent_ingests(session)[0].concept_count == 0


def test_no_ingests_yet_lists_nothing(session):
    assert recent_ingests(session) == []
