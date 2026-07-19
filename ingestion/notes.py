import json
from pathlib import Path
from typing import TypedDict

import ollama
from langgraph.graph import END, START, StateGraph

from ingestion.papers import (
    EXTRACTION_SCHEMA,
    IngestResult,
    build_resolve_candidates_node,
    build_write_content_log_node,
)


class NoteIngestState(TypedDict):
    source: str
    note_text: str | None
    candidates: list[dict]
    concept_ids: list[int]
    queued_count: int
    content_log_id: int | None


def read_note(state: NoteIngestState) -> dict:
    note_text = Path(state["source"]).read_text(encoding="utf-8")
    if not note_text.strip():
        raise ValueError(f"Note is empty: {state['source']}")
    return {"note_text": note_text}


def _build_note_extraction_prompt(note_text: str) -> str:
    return (
        "You are extracting technical concepts from a personal learning note.\n\n"
        f"Note:\n{note_text}\n\n"
        "List only the technical concepts the note's author demonstrably "
        "engaged with — studied, implemented, compared, or reasoned about. "
        "Skip concepts that are merely name-dropped, appear only in todo "
        "items or reading lists, or are generic words. For each concept, "
        "give its name, a short free-form category label, and your "
        "confidence 0-1 that it is a genuine, well-defined technical "
        "concept the author actually engaged with."
    )


def call_ollama_extract_note(note_text: str) -> list[dict]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": _build_note_extraction_prompt(note_text)}],
        format=EXTRACTION_SCHEMA,
    )
    return json.loads(response["message"]["content"])


def extract_concepts(state: NoteIngestState, extract_fn=call_ollama_extract_note) -> dict:
    candidates = extract_fn(state["note_text"])
    return {"candidates": candidates}


def build_notes_graph(session, collection):
    graph = StateGraph(NoteIngestState)
    graph.add_node("read_note", read_note)
    graph.add_node("extract_concepts", extract_concepts)
    graph.add_node(
        "resolve_candidates",
        build_resolve_candidates_node(session, collection, source_type="note"),
    )
    graph.add_node(
        "write_content_log",
        build_write_content_log_node(session, source_type="note"),
    )

    graph.add_edge(START, "read_note")
    graph.add_edge("read_note", "extract_concepts")
    graph.add_edge("extract_concepts", "resolve_candidates")
    graph.add_edge("resolve_candidates", "write_content_log")
    graph.add_edge("write_content_log", END)

    return graph.compile()


def ingest_note(session, collection, source: str) -> IngestResult:
    app = build_notes_graph(session, collection)
    final_state = app.invoke({
        "source": source,
        "note_text": None,
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
