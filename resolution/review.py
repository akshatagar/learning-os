from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from storage.models import AdjudicationLog, Concept, MergeQueue

HUMAN_CONFIDENCE = 1.0

_STATUS_BY_ACTION = {
    "merge": "approved_merge",
    "new": "approved_new",
    "dismiss": "rejected",
}


@dataclass
class ReviewResult:
    action: str
    concept_id: int | None


def pending_entries(session) -> list[MergeQueue]:
    return list(
        session.scalars(
            select(MergeQueue)
            .where(MergeQueue.status == "pending")
            .order_by(MergeQueue.id)
        )
    )


def _record_human_resolution(session, entry, status):
    if entry.adjudication_log_id is None:
        return
    log = session.get(AdjudicationLog, entry.adjudication_log_id)
    log.human_resolution = status
    log.resolved_at = datetime.now(timezone.utc)


def resolve_entry(session, collection, entry, action, target_concept_id=None) -> ReviewResult:
    if action not in _STATUS_BY_ACTION:
        raise ValueError(f"Unknown review action: {action}")
    status = _STATUS_BY_ACTION[action]

    concept_id = None

    entry.status = status
    _record_human_resolution(session, entry, status)
    session.commit()
    return ReviewResult(action=action, concept_id=concept_id)
