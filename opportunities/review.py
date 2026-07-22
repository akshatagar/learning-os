import json

from sqlalchemy import select

from storage.models import Concept, Opportunity

_STATUS_BY_ACTION = {
    "approve": "approved",
    "reject": "rejected",
}


def pending_opportunities(session) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.status == "generated")
            .order_by(Opportunity.id)
        )
    )


def resolve_opportunity(session, opportunity, action) -> str:
    if action not in _STATUS_BY_ACTION:
        raise ValueError(f"Unknown approval action: {action}")
    opportunity.status = _STATUS_BY_ACTION[action]
    session.commit()
    return opportunity.status


def source_concept_names(session, opportunity) -> list[str]:
    names = []
    for concept_id in json.loads(opportunity.source_concepts or "[]"):
        concept = session.get(Concept, concept_id)
        if concept is not None:
            names.append(concept.name)
    return names


def format_opportunity(opportunity, concept_names, position, total) -> str:
    required = json.loads(opportunity.required_skills or "[]")
    return "\n".join([
        "",
        f"Idea {position}/{total}  (id {opportunity.id})",
        f"  {opportunity.title}",
        "",
        f"  {opportunity.description}",
        "",
        f"  from concepts : {', '.join(concept_names) or '(none recorded)'}",
        f"  requires      : {', '.join(required) or '(none listed)'}",
        "",
        "[a]pprove   [r]eject   [s]kip   [q]uit",
    ])


def _print_summary(counts):
    print(
        f"\napproved {counts['approved']}, rejected {counts['rejected']}, "
        f"skipped {counts['skipped']}"
    )


def run_idea_review_loop(session, input_fn=input) -> dict[str, int]:
    counts = {"approved": 0, "rejected": 0, "skipped": 0}
    entries = pending_opportunities(session)
    if not entries:
        print("No pending ideas.")
        return counts

    total = len(entries)
    for position, opportunity in enumerate(entries, start=1):
        print(
            format_opportunity(
                opportunity,
                source_concept_names(session, opportunity),
                position,
                total,
            )
        )
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
            if choice == "a":
                resolve_opportunity(session, opportunity, "approve")
                counts["approved"] += 1
                break
            if choice == "r":
                resolve_opportunity(session, opportunity, "reject")
                counts["rejected"] += 1
                break
            print("Unrecognized input - pick one of the options above.")

    _print_summary(counts)
    return counts
