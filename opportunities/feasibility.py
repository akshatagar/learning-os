import json

import ollama
from sqlalchemy import select

from storage.models import Opportunity, Skill


def skill_names(session) -> list[str]:
    names = list(session.scalars(select(Skill.name).order_by(Skill.name)))
    if not names:
        raise ValueError(
            "No skills on record - run 'add-skills' first, or every "
            "opportunity would score 0%"
        )
    return names


def unscored_approved(session) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.status == "approved")
            .where(Opportunity.skill_match_pct.is_(None))
            .order_by(Opportunity.id)
        )
    )


MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "covered_by": {"type": ["string", "null"]},
                },
                "required": ["requirement", "covered_by"],
            },
        }
    },
    "required": ["matches"],
}


def _build_match_prompt(skills: list[str], required: list[str]) -> str:
    skill_listing = "\n".join(f"- {name}" for name in skills)
    required_listing = "\n".join(f"- {name}" for name in required)
    return (
        "You are checking which requirements of a project are already covered "
        "by a person's existing skills.\n\n"
        f"Their skills:\n{skill_listing}\n\n"
        f"The project requires:\n{required_listing}\n\n"
        "For EACH requirement, return the requirement text exactly as written "
        "above, and the name of the ONE skill from their list that covers it "
        "- copied exactly as it appears in their skills. When no skill covers "
        "it, use a real JSON null, not the text \"null\".\n\n"
        "A skill covers a requirement when it is the same technology under a "
        "different name, or a specific tool satisfying a general requirement "
        "(knowing Docker covers 'containerization'). When a requirement lists "
        "alternatives, one of them is enough. Never name a skill that is not "
        "in their list, and do not treat a related-but-different technology "
        "as coverage."
    )


def _clean_covered_by(value):
    """Normalize a covered_by value to a real skill name or None.

    `covered_by` is typed ["string", "null"], which makes the literal string
    "null" schema-valid - and qwen2.5:7b does emit it. Measured: asked about
    Kubernetes against a table without it, the model returned the four
    characters n-u-l-l rather than a JSON null. Normalizing here keeps the
    str | None contract honest for every caller.
    """
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text


def call_ollama_match(skills: list[str], required: list[str]) -> list[dict]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[
            {"role": "user", "content": _build_match_prompt(skills, required)}
        ],
        format=MATCH_SCHEMA,
    )
    matches = json.loads(response["message"]["content"])["matches"]
    return [
        {
            "requirement": match["requirement"],
            "covered_by": _clean_covered_by(match["covered_by"]),
        }
        for match in matches
    ]
