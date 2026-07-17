from dataclasses import dataclass
from typing import Any, TypedDict


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
