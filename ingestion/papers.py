import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

import httpx
from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter


class IngestState(TypedDict):
    source: str
    pdf_bytes: bytes | None
    docling_doc: Any | None
    targeted_sections: list[str]
    candidates: list[dict]
    concept_ids: list[int]
    queued_count: int
    content_log_id: int | None


@dataclass
class IngestResult:
    content_log_id: int
    concept_ids: list[int]
    queued_count: int


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def fetch_source(state: IngestState) -> dict:
    source = state["source"]
    if _is_url(source):
        response = httpx.get(source, follow_redirects=True)
        response.raise_for_status()
        return {"pdf_bytes": response.content}
    return {"pdf_bytes": Path(source).read_bytes()}


def parse_docling(state: IngestState, converter_factory=DocumentConverter) -> dict:
    stream = DocumentStream(name="source.pdf", stream=io.BytesIO(state["pdf_bytes"]))
    converter = converter_factory()
    result = converter.convert(stream)
    return {"docling_doc": result.document}
