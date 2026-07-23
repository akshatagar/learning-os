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


def _normalize_milestone(raw: dict) -> dict:
    """Coerce one raw milestone into the three-field contract.

    `kind` is typed as an enum in PLAN_SCHEMA, but 7b and 7c both found that a
    schema-valid answer can still be wrong - a top-level array returned `[]`,
    and a ["string","null"] field returned the text "null". Anything that is
    not exactly "learn" becomes "build" here, so no third category reaches the
    coverage guard or the renderer.
    """
    kind = str(raw.get("kind") or "").strip().lower()
    return {
        "title": str(raw.get("title") or "").strip(),
        "kind": "learn" if kind == "learn" else "build",
        "detail": str(raw.get("detail") or "").strip(),
    }


def call_ollama_plan(
    title: str, description: str, required: list[str], missing: list[str]
) -> list[dict]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[
            {
                "role": "user",
                "content": _build_plan_prompt(title, description, required, missing),
            }
        ],
        format=PLAN_SCHEMA,
    )
    milestones = json.loads(response["message"]["content"])["milestones"]
    return [_normalize_milestone(milestone) for milestone in milestones]


def ensure_missing_covered(milestones: list[dict], missing: list[str]) -> list[dict]:
    """Guarantee every stored missing skill has a learn milestone.

    The model's list is a proposal, never the list being iterated - a skill it
    forgets must still appear. Generated milestones are blunt on purpose: they
    read as an obvious fallback, and they are deterministic, so the guarantee
    is testable without the model.
    """
    learn_text = [
        f"{milestone['title']} {milestone['detail']}".lower()
        for milestone in milestones
        if milestone["kind"] == "learn"
    ]

    generated = [
        {
            "title": f"Learn {skill}",
            "kind": "learn",
            "detail": (
                f"Get to working competence with {skill} before the build "
                "milestones that depend on it."
            ),
        }
        for skill in missing
        if not any(skill.lower() in text for text in learn_text)
    ]

    return generated + milestones


def plan_opportunity(session, opportunity, plan_fn=call_ollama_plan) -> list[dict]:
    required = json.loads(opportunity.required_skills or "[]")
    missing = json.loads(opportunity.missing_skills or "[]")

    milestones = plan_fn(
        opportunity.title, opportunity.description, required, missing
    )
    # Checked before the guard runs. The guard fills gaps in a real plan; it
    # must never be what manufactures one.
    if not milestones:
        raise ValueError(
            f"Opportunity {opportunity.id} came back with zero milestones - "
            "refusing to write an empty plan"
        )

    milestones = ensure_missing_covered(milestones, missing)
    opportunity.execution_plan = json.dumps(milestones)
    session.commit()
    return milestones
