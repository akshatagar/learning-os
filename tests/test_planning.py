import json

import pytest

from opportunities.planning import (
    PLAN_SCHEMA,
    _build_plan_prompt,
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
