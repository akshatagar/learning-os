import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

import httpx
import ollama
from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter
from langgraph.graph import END, START, StateGraph

from resolution.adjudicate import call_ollama_adjudicate, resolve_candidate
from storage.models import ContentLog


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


def build_resolve_candidates_node(session, collection, adjudicate_fn=call_ollama_adjudicate):
    def node(state: IngestState) -> dict:
        concept_ids: list[int] = []
        queued_count = 0
        for candidate in state["candidates"]:
            result = resolve_candidate(
                session,
                collection,
                candidate["name"],
                candidate_category=candidate.get("category"),
                source_type="paper",
                adjudicate_fn=adjudicate_fn,
            )
            if result.decision == "queued":
                queued_count += 1
            else:
                concept_ids.append(result.concept_id)
        return {"concept_ids": concept_ids, "queued_count": queued_count}

    return node


def build_write_content_log_node(session):
    def node(state: IngestState) -> dict:
        log = ContentLog(
            source_path=state["source"],
            source_type="paper",
            ingested_at=datetime.now(timezone.utc),
            extracted_concepts=json.dumps(state["concept_ids"]),
            summary=None,
        )
        session.add(log)
        session.commit()
        return {"content_log_id": log.id}

    return node


def build_papers_graph(session, collection):
    graph = StateGraph(IngestState)
    graph.add_node("fetch_source", fetch_source)
    graph.add_node("parse_docling", parse_docling)
    graph.add_node("target_sections", target_sections)
    graph.add_node("extract_concepts", extract_concepts)
    graph.add_node("resolve_candidates", build_resolve_candidates_node(session, collection))
    graph.add_node("write_content_log", build_write_content_log_node(session))

    graph.add_edge(START, "fetch_source")
    graph.add_edge("fetch_source", "parse_docling")
    graph.add_edge("parse_docling", "target_sections")
    graph.add_edge("target_sections", "extract_concepts")
    graph.add_edge("extract_concepts", "resolve_candidates")
    graph.add_edge("resolve_candidates", "write_content_log")
    graph.add_edge("write_content_log", END)

    return graph.compile()


def ingest_paper(session, collection, source: str) -> IngestResult:
    app = build_papers_graph(session, collection)
    final_state = app.invoke({
        "source": source,
        "pdf_bytes": None,
        "docling_doc": None,
        "targeted_sections": [],
        "candidates": [],
        "concept_ids": [],
        "queued_count": 0,
        "content_log_id": None,
    })
    return IngestResult(
        content_log_id=final_state["content_log_id"],
        concept_ids=final_state["concept_ids"],
        queued_count=final_state["queued_count"],
    )
