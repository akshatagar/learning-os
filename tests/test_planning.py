import json

import pytest

from opportunities.planning import (
    PLAN_SCHEMA,
    _build_plan_prompt,
    _normalize_milestone,
    call_ollama_plan,
    unplanned_approved,
)
from storage.models import Opportunity


def _add_opportunity(session, title="An idea", status="approved",
                     required=("Python",), missing=("SQL",),
                     skill_match_pct=50.0, execution_plan=None):
    opportunity = Opportunity(
        title=title,
        description="Does a thing.",
        required_skills=json.dumps(list(required)),
        missing_skills=None if missing is None else json.dumps(list(missing)),
        source_concepts=json.dumps([]),
        status=status,
        skill_match_pct=skill_match_pct,
        execution_plan=execution_plan,
    )
    session.add(opportunity)
    session.commit()
    return opportunity


def test_execution_plan_defaults_to_null_and_stores_json(session):
    opportunity = _add_opportunity(session)

    assert opportunity.execution_plan is None

    opportunity.execution_plan = json.dumps(
        [{"title": "Learn SQL", "kind": "learn", "detail": "Basics."}]
    )
    session.commit()

    stored = json.loads(opportunity.execution_plan)
    assert stored[0]["kind"] == "learn"


def test_unplanned_approved_returns_only_approved_scored_and_unplanned(session):
    _add_opportunity(session, "ready")
    _add_opportunity(session, "not approved", status="generated")
    _add_opportunity(session, "rejected", status="rejected")
    _add_opportunity(session, "not scored", skill_match_pct=None)
    _add_opportunity(session, "already planned", execution_plan="[]")

    assert [o.title for o in unplanned_approved(session)] == ["ready"]


def test_unplanned_approved_is_oldest_first(session):
    _add_opportunity(session, "first")
    _add_opportunity(session, "second")

    assert [o.title for o in unplanned_approved(session)] == ["first", "second"]


def test_plan_schema_is_object_wrapped():
    """A top-level array schema is satisfiable by `[]`.

    That is what made idea generation return zero ideas in 7b. Here an empty
    completion would produce a stored plan with no milestones, which reads as
    "planned" forever after and is never revisited.
    """
    assert PLAN_SCHEMA["type"] == "object"
    assert PLAN_SCHEMA["required"] == ["milestones"]
    assert PLAN_SCHEMA["properties"]["milestones"]["type"] == "array"


def test_plan_schema_constrains_kind_to_two_values():
    item = PLAN_SCHEMA["properties"]["milestones"]["items"]

    assert item["properties"]["kind"]["enum"] == ["learn", "build"]
    assert item["required"] == ["title", "kind", "detail"]


def test_build_plan_prompt_names_the_idea_and_both_skill_lists():
    prompt = _build_plan_prompt(
        "Query Assistant",
        "Answers questions over a database.",
        ["Python", "SQL"],
        ["SQL"],
    )

    assert "Query Assistant" in prompt
    assert "Answers questions over a database." in prompt
    assert "Python" in prompt
    assert "SQL" in prompt


def test_build_plan_prompt_states_plainly_when_nothing_is_missing():
    """A fully-covered idea is a legitimate build-only plan, not a degenerate one.

    Real rows 10 and 12 both scored 100%. If the prompt showed them an empty
    list under a "skills they lack" heading, the model would be left guessing
    whether that meant "none" or "unknown".
    """
    prompt = _build_plan_prompt("X", "Y", ["Python"], [])

    assert "already have every skill" in prompt


def test_normalize_milestone_keeps_learn_and_build():
    learn = _normalize_milestone(
        {"title": "Learn SQL", "kind": "learn", "detail": "Basics."}
    )
    build = _normalize_milestone(
        {"title": "Build the API", "kind": "build", "detail": "Endpoints."}
    )

    assert learn["kind"] == "learn"
    assert build["kind"] == "build"


def test_normalize_milestone_coerces_an_unknown_kind_to_build():
    """`enum` may not constrain this decoder, so a third category can arrive.

    Coercing to "build" is the safe default: a mislabelled build step is a
    cosmetic error, while an unrecognized kind would slip past the coverage
    guard's `kind == "learn"` check and split the renderer's two cases.
    """
    for raw_kind in ["research", "LEARN ", "", None]:
        milestone = _normalize_milestone(
            {"title": "t", "kind": raw_kind, "detail": "d"}
        )
        assert milestone["kind"] in {"learn", "build"}

    assert _normalize_milestone(
        {"title": "t", "kind": "research", "detail": "d"}
    )["kind"] == "build"
    assert _normalize_milestone(
        {"title": "t", "kind": "LEARN ", "detail": "d"}
    )["kind"] == "learn"


def test_normalize_milestone_strips_whitespace_and_tolerates_missing_keys():
    milestone = _normalize_milestone({"title": "  Learn SQL  ", "kind": "learn"})

    assert milestone["title"] == "Learn SQL"
    assert milestone["detail"] == ""


def test_call_ollama_plan_returns_a_learn_milestone_for_the_missing_skill():
    """Live round-trip. The acceptance bar for the prompt.

    The coverage guard in ensure_missing_covered will backfill a blunt
    "Learn SQL" if the model omits it, so this test is what tells us whether
    the guard is a safety net or the primary mechanism.
    """
    milestones = call_ollama_plan(
        "Database Query Assistant",
        "A tool that answers plain-English questions about a SQL database "
        "by generating and running queries.",
        ["Python", "SQL", "PyTorch"],
        ["SQL"],
    )

    assert len(milestones) >= 3
    assert all(m["kind"] in {"learn", "build"} for m in milestones)
    assert all(m["title"] for m in milestones)

    learn_text = " ".join(
        f"{m['title']} {m['detail']}" for m in milestones if m["kind"] == "learn"
    ).lower()
    assert "sql" in learn_text


def test_call_ollama_plan_honors_min_items():
    """Measures whether `minItems` constrains this decoder.

    7b left this open: `--count` in idea generation is advisory precisely
    because minItems "would enforce it and was not attempted". If this passes,
    that finding transfers straight back to generate.py. Nothing in this
    module depends on the answer.
    """
    milestones = call_ollama_plan(
        "Tiny Script",
        "A one-file script that prints the current time.",
        ["Python"],
        [],
    )

    assert len(milestones) >= 3
