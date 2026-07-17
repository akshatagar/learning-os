from ingestion.papers import IngestResult, IngestState


def test_ingest_types_importable():
    assert IngestState.__annotations__["source"] is str
    result = IngestResult(content_log_id=1, concept_ids=[1, 2], queued_count=0)
    assert result.concept_ids == [1, 2]
