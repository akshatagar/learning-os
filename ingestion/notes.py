from pathlib import Path
from typing import TypedDict


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
