import json
import re

import ollama
from sqlalchemy import select

from storage.models import Goal

_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
_LOWER_WORD = re.compile(r"\b[a-z]{2,}\b")


def flag_bare_acronym(phrase: str) -> bool:
    """True when a phrase carries an acronym without enough words to expand it.

    Embedding models mean-pool the whole string, so a bare acronym scores
    0.51-0.68 against its spelled-out concept and false-misses. The convention
    is that both forms appear. An N-letter acronym needs at least N lowercase
    words beside it, which is what distinguishes "KV cache" from "KV cache
    key-value cache".

    Mixed-case acronyms (RoPE, MoE) are not detected - they contain no all-caps
    run of two or more characters. This catches the common case; it is not a
    proof, which is why it warns rather than blocks.
    """
    acronyms = _ACRONYM.findall(phrase)
    if not acronyms:
        return False
    longest = max(len(acronym) for acronym in acronyms)
    return len(_LOWER_WORD.findall(phrase)) < longest


DEFAULT_REQUIREMENT_COUNT = 14

# Object-wrapped for the reason recorded in generate.py: a top-level array is
# satisfied by `[]`, so the constrained decoder emits `]` immediately as the
# shortest legal completion. minItems/maxItems are set because 7d measured that
# minItems binds this decoder exactly.
REQUIREMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": DEFAULT_REQUIREMENT_COUNT,
            "maxItems": DEFAULT_REQUIREMENT_COUNT,
        }
    },
    "required": ["requirements"],
}


def build_draft_prompt(description: str, category: str, count: int) -> str:
    return (
        "Someone is learning a subject and needs the list of concepts that "
        "would mean they had learned it.\n\n"
        f"Their goal: {description}\n"
        f"Subject area: {category}\n\n"
        f"Return exactly {count} concept names. Each should be a specific "
        "thing that can be learned, not a broad topic and not an activity.\n\n"
        "Every name containing an acronym MUST also spell the acronym out, "
        "because these strings are matched by embedding similarity and a bare "
        "acronym does not match its expansion. Write \"KV cache key-value "
        "cache\", not \"KV cache\". Write \"GQA grouped query attention\", "
        "not \"GQA\".\n\n"
        "Use lower case except where a name is normally capitalised."
    )


def call_ollama_draft(
    description: str, category: str, count: int = DEFAULT_REQUIREMENT_COUNT
) -> list[str]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[
            {
                "role": "user",
                "content": build_draft_prompt(description, category, count),
            }
        ],
        format=REQUIREMENT_SCHEMA,
    )
    raw = json.loads(response["message"]["content"])["requirements"]
    # The model's reply is a proposal, never the list being iterated. Blanks
    # and duplicates are dropped here so nothing downstream has to.
    seen: list[str] = []
    for item in raw:
        phrase = str(item or "").strip()
        if phrase and phrase.lower() not in {s.lower() for s in seen}:
            seen.append(phrase)
    return seen


def undrafted_goals(session) -> list[Goal]:
    return list(
        session.scalars(
            select(Goal)
            .where(Goal.concept_requirements.is_(None))
            .order_by(Goal.id)
        )
    )


def draft_all(session, draft_fn=call_ollama_draft) -> dict[str, int]:
    """Draft requirements for every goal that has none, committing per row.

    Same shape as score_all and plan_all: the NULL column is the work queue, so
    interrupting a run loses nothing and re-running continues where it stopped.
    """
    counts = {"drafted": 0}
    for goal in undrafted_goals(session):
        requirements = draft_fn(goal.description, goal.category)
        # Checked before anything is written. An empty list would satisfy
        # IS NOT NULL and make a failed draft read as drafted forever after.
        if not requirements:
            raise ValueError(
                f"Goal {goal.id} came back with zero requirements - "
                "refusing to write an empty list"
            )
        goal.concept_requirements = json.dumps(requirements)
        session.commit()
        counts["drafted"] += 1
    return counts
