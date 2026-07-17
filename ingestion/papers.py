import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

import httpx
import ollama
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


EXTRACTION_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "category": {"type": "string"},
            "extraction_confidence": {"type": "number"},
        },
        "required": ["name", "category", "extraction_confidence"],
    },
}


def _build_extraction_prompt(section_text: str) -> str:
    return (
        "You are extracting technical concepts from a research paper's "
        "methodology/architecture sections.\n\n"
        f"Text:\n{section_text}\n\n"
        "List the distinct technical concepts named in this text. For each, "
        "give its name, a short free-form category label, and your "
        "confidence 0-1 that it is a genuine, well-defined technical "
        "concept (not a generic word)."
    )


def call_ollama_extract(section_text: str) -> list[dict]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": _build_extraction_prompt(section_text)}],
        format=EXTRACTION_SCHEMA,
        # Same CUDA workaround as resolution/adjudicate.py:78-83 — this
        # machine's GPU crashes on JSON-schema-constrained decoding with
        # GPU offload enabled.
        options={"num_gpu": 0},
    )
    return json.loads(response["message"]["content"])


def extract_concepts(state: IngestState, extract_fn=call_ollama_extract) -> dict:
    combined_text = "\n\n".join(state["targeted_sections"])
    candidates = extract_fn(combined_text)
    return {"candidates": candidates}
