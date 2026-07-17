from ingestion.papers import (
    IngestResult,
    IngestState,
    call_ollama_extract,
    extract_concepts,
    fetch_source,
    parse_docling,
    target_sections,
)


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


class _FakeConvertResult:
    def __init__(self, document):
        self.document = document


class _FakeConverter:
    def __init__(self, document):
        self._document = document

    def convert(self, source):
        return _FakeConvertResult(self._document)


def test_parse_docling_returns_converted_document():
    fake_document = object()

    result = parse_docling(
        {"pdf_bytes": b"%PDF-1.4 fake"},
        converter_factory=lambda: _FakeConverter(fake_document),
    )

    assert result["docling_doc"] is fake_document


class _FakeDoclingDoc:
    def __init__(self, markdown):
        self._markdown = markdown

    def export_to_markdown(self):
        return self._markdown


def test_target_sections_selects_heading_matched_sections():
    markdown = (
        "# Introduction\n"
        "Some intro text.\n"
        "# Method\n"
        "We propose a new architecture using gradient descent.\n"
        "# References\n"
        "[1] some citation\n"
    )

    result = target_sections({"docling_doc": _FakeDoclingDoc(markdown)})

    assert result["targeted_sections"] == [
        "We propose a new architecture using gradient descent."
    ]


def test_target_sections_falls_back_to_full_text_when_no_heading_matches():
    markdown = "# Introduction\nSome intro text.\n# References\n[1] some citation\n"

    result = target_sections({"docling_doc": _FakeDoclingDoc(markdown)})

    assert result["targeted_sections"] == [markdown]


def test_extract_concepts_uses_injected_extract_fn():
    def fake_extract(section_text):
        assert "gradient descent" in section_text
        return [
            {"name": "gradient descent", "category": "optimization", "extraction_confidence": 0.9}
        ]

    result = extract_concepts(
        {"targeted_sections": ["We propose a new architecture using gradient descent."]},
        extract_fn=fake_extract,
    )

    assert result["candidates"] == [
        {"name": "gradient descent", "category": "optimization", "extraction_confidence": 0.9}
    ]


def test_call_ollama_extract_returns_schema_valid_candidates():
    section_text = (
        "We propose a new architecture based on the attention mechanism, "
        "using gradient descent for optimization during training."
    )

    result = call_ollama_extract(section_text)

    assert isinstance(result, list)
    assert len(result) >= 1
    for candidate in result:
        assert isinstance(candidate["name"], str) and candidate["name"]
        assert isinstance(candidate["category"], str) and candidate["category"]
        assert isinstance(candidate["extraction_confidence"], (int, float))
        assert 0.0 <= candidate["extraction_confidence"] <= 1.0
