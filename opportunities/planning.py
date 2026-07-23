import json

import ollama
from sqlalchemy import select

from storage.models import Opportunity


def unplanned_approved(session) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.status == "approved")
            .where(Opportunity.skill_match_pct.is_not(None))
            .where(Opportunity.execution_plan.is_(None))
            .order_by(Opportunity.id)
        )
    )


_MILESTONE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": ["learn", "build"]},
        "detail": {"type": "string"},
    },
    "required": ["title", "kind", "detail"],
}

# Object-wrapped for the reason recorded in generate.py: a top-level array is
# satisfied by `[]`, so the constrained decoder can emit `]` immediately as the
# shortest legal completion. `minItems` and `enum` are unproven against this
# decoder - both are measured by the live tests, and neither is relied on.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "milestones": {
            "type": "array",
            "items": _MILESTONE_SCHEMA,
            "minItems": 3,
        }
    },
    "required": ["milestones"],
}


def _build_plan_prompt(
    title: str, description: str, required: list[str], missing: list[str]
) -> str:
    required_listing = "\n".join(f"- {name}" for name in required)
    if missing:
        missing_listing = "\n".join(f"- {name}" for name in missing)
        gap_clause = (
            "They do NOT yet have these skills:\n"
            f"{missing_listing}\n\n"
            "Give each one its own milestone with kind \"learn\", placed "
            "before any build milestone that depends on it."
        )
    else:
        gap_clause = (
            "They already have every skill this project needs, so every "
            "milestone should have kind \"build\"."
        )

    return (
        "You are laying out an execution roadmap for a project someone is "
        "about to build.\n\n"
        f"Project: {title}\n\n"
        f"{description}\n\n"
        f"It requires these skills:\n{required_listing}\n\n"
        f"{gap_clause}\n\n"
        "Return an ordered list of milestones. Each milestone needs a short "
        "imperative title, a kind of either \"learn\" or \"build\", and one "
        "or two sentences of detail on what it involves. Order them so that "
        "each milestone is doable once the ones before it are done.\n\n"
        "Do not introduce technologies beyond the skills listed above."
    )
