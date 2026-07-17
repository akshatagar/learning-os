from ingestion.papers import IngestResult, IngestState, fetch_source


def test_ingest_types_importable():
    assert IngestState.__annotations__["source"] is str
    result = IngestResult(content_log_id=1, concept_ids=[1, 2], queued_count=0)
    assert result.concept_ids == [1, 2]


def test_fetch_source_reads_local_file_bytes(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")

    result = fetch_source({"source": str(pdf_path)})

    assert result["pdf_bytes"] == b"%PDF-1.4 fake content"


def test_fetch_source_raises_for_missing_local_file(tmp_path):
    missing = tmp_path / "missing.pdf"

    try:
        fetch_source({"source": str(missing)})
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
