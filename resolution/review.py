from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from resolution.adjudicate import _query_neighbors
from storage.models import AdjudicationLog, Concept, MergeQueue

HUMAN_CONFIDENCE = 1.0
NEIGHBOR_K = 5

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

    if action == "merge":
        if target_concept_id is None:
            raise ValueError("merge requires target_concept_id")
        concept = session.get(Concept, target_concept_id)
        if concept is None:
            raise ValueError(f"No concept with id {target_concept_id}")
        concept.confidence_score = min(1.0, (concept.confidence_score or 0.0) + 0.05)
        concept.last_reinforced = datetime.now(timezone.utc)
        concept_id = concept.id

    elif action == "new":
        concept = Concept(
            name=entry.candidate_name,
            category=entry.candidate_category,
            confidence_score=HUMAN_CONFIDENCE,
            source_type=entry.source_type,
            first_seen=datetime.now(timezone.utc),
            last_reinforced=datetime.now(timezone.utc),
        )
        session.add(concept)
        session.flush()
        collection.add(ids=[str(concept.id)], documents=[entry.candidate_name])
        concept.embedding_id = str(concept.id)
        concept_id = concept.id

    entry.status = status
    _record_human_resolution(session, entry, status)
    session.commit()
    return ReviewResult(action=action, concept_id=concept_id)


def format_entry(entry, neighbors, position, total):
    category = f"  [{entry.candidate_category}]" if entry.candidate_category else ""
    confidence = (
        f"{entry.llm_confidence:.2f}" if entry.llm_confidence is not None else "n/a"
    )
    lines = [
        "",
        f"Pending {position}/{total}  (queue id {entry.id})",
        f'  candidate : "{entry.candidate_name}"{category}',
        f"  model     : confidence {confidence}",
        f"  reasoning : {entry.llm_reasoning or '(none recorded)'}",
        "",
    ]
    if neighbors:
        lines.append("  nearest concepts (live):")
        for number, neighbor in enumerate(neighbors, start=1):
            lines.append(
                f'    {number}. #{neighbor["id"]} "{neighbor["name"]}"'
                f'  {neighbor["similarity_score"]:.2f}'
            )
        lines.append("")
        lines.append(f"[1-{len(neighbors)}] merge into that   [n] insert as new")
    else:
        lines.append("  (no existing concepts to merge into)")
        lines.append("")
        lines.append("[n] insert as new")
    lines.append("[d] dismiss   [s] skip   [q] quit")
    return "\n".join(lines)


def _print_summary(counts):
    print(
        f"\nmerged {counts['merged']}, new {counts['new']}, "
        f"dismissed {counts['dismissed']}, skipped {counts['skipped']}"
    )


def run_review_loop(session, collection, input_fn=input, k=NEIGHBOR_K):
    counts = {"merged": 0, "new": 0, "dismissed": 0, "skipped": 0}
    entries = pending_entries(session)
    if not entries:
        print("No pending entries in the merge queue.")
        return counts

    total = len(entries)
    for position, entry in enumerate(entries, start=1):
        neighbors = _query_neighbors(collection, entry.candidate_name, k)
        print(format_entry(entry, neighbors, position, total))
        while True:
            try:
                choice = input_fn("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                _print_summary(counts)
                return counts

            if choice == "q":
                _print_summary(counts)
                return counts
            if choice == "s":
                counts["skipped"] += 1
                break
            if choice == "n":
                resolve_entry(session, collection, entry, "new")
                counts["new"] += 1
                break
            if choice == "d":
                resolve_entry(session, collection, entry, "dismiss")
                counts["dismissed"] += 1
                break
            if choice.isdigit() and 1 <= int(choice) <= len(neighbors):
                target = neighbors[int(choice) - 1]["id"]
                resolve_entry(session, collection, entry, "merge", target_concept_id=target)
                counts["merged"] += 1
                break
            print("Unrecognized input — pick one of the options above.")

    _print_summary(counts)
    return counts
