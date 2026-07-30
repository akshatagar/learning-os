import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from storage.models import ContentLog

DEFAULT_LIMIT = 10


@dataclass
class IngestSummary:
    id: int
    source_path: str | None
    source_type: str | None
    ingested_at: datetime | None
    concept_count: int


def _concept_count(raw: str | None) -> int:
    """How many concepts one ingest produced.

    extracted_concepts holds a JSON array of concept ids. This is a
    read-only convenience, so a malformed row costs one wrong count and
    never the whole list.
    """
    if not raw:
        return 0
    try:
        parsed = json.loads(raw)
    except ValueError:
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def recent_ingests(session, limit: int = DEFAULT_LIMIT) -> list[IngestSummary]:
    rows = session.scalars(
        select(ContentLog).order_by(ContentLog.ingested_at.desc()).limit(limit)
    )
    return [
        IngestSummary(
            id=row.id,
            source_path=row.source_path,
            source_type=row.source_type,
            ingested_at=row.ingested_at,
            concept_count=_concept_count(row.extracted_concepts),
        )
        for row in rows
    ]
