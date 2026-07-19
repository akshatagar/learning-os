import json
from pathlib import Path
from typing import TypedDict

import ollama

from ingestion.papers import EXTRACTION_SCHEMA


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
