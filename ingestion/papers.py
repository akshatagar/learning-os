import io
import re
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


SECTION_KEYWORDS = ["method", "approach", "architecture", "model", "design"]


def _split_markdown_sections(markdown: str) -> list[tuple[str, str]]:
    sections = []
    heading = ""
    body_lines: list[str] = []
    for line in markdown.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            if heading or body_lines:
                sections.append((heading, "\n".join(body_lines).strip()))
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            body_lines = []
        else:
            body_lines.append(line)
    if heading or body_lines:
        sections.append((heading, "\n".join(body_lines).strip()))
    return sections


def target_sections(state: IngestState) -> dict:
    markdown = state["docling_doc"].export_to_markdown()
    sections = _split_markdown_sections(markdown)
    matched = [
        body
        for heading, body in sections
        if any(keyword in heading.lower() for keyword in SECTION_KEYWORDS)
    ]
    if not matched:
        return {"targeted_sections": [markdown]}
    return {"targeted_sections": matched}
