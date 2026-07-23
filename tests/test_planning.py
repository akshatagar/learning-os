import json

import pytest

from opportunities.planning import (
    PLAN_SCHEMA,
    _build_plan_prompt,
    _normalize_milestone,
    call_ollama_plan,
    ensure_missing_covered,
    format_plan,
    plan_opportunity,
    show_plan,
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


def _milestone(title, kind="build", detail=""):
    return {"title": title, "kind": kind, "detail": detail}


def test_ensure_missing_covered_prepends_an_uncovered_skill():
    """The guard iterates the STORED missing_skills, not the model's reply.

    Same rule that made 7c correct. A fluent roadmap that quietly omits the
    learning step is indistinguishable from a good one unless you happen to
    remember what the score said.
    """
    milestones = [_milestone("Build the API")]

    result = ensure_missing_covered(milestones, ["SQL"])

    assert result[0]["kind"] == "learn"
    assert result[0]["title"] == "Learn SQL"
    assert result[1]["title"] == "Build the API"


def test_ensure_missing_covered_does_not_duplicate_a_covered_skill():
    milestones = [
        _milestone("Work through a SQL tutorial", kind="learn"),
        _milestone("Build the API"),
    ]

    result = ensure_missing_covered(milestones, ["SQL"])

    assert result == milestones


def test_ensure_missing_covered_matches_case_insensitively_in_the_detail():
    milestones = [
        _milestone("Get comfortable with queries", kind="learn",
                   detail="Practice joins and aggregates in sql."),
    ]

    result = ensure_missing_covered(milestones, ["SQL"])

    assert len(result) == 1


def test_ensure_missing_covered_ignores_a_build_milestone_naming_the_skill():
    """A build step that uses SQL is not a step that teaches it."""
    milestones = [_milestone("Write the SQL query layer")]

    result = ensure_missing_covered(milestones, ["SQL"])

    assert len(result) == 2
    assert result[0]["title"] == "Learn SQL"


def test_ensure_missing_covered_preserves_stored_order_at_the_front():
    milestones = [_milestone("Build it")]

    result = ensure_missing_covered(milestones, ["SQL", "Docker"])

    assert [m["title"] for m in result] == ["Learn SQL", "Learn Docker", "Build it"]


def test_ensure_missing_covered_adds_nothing_when_nothing_is_missing():
    milestones = [_milestone("Build it")]

    assert ensure_missing_covered(milestones, []) == milestones


def _fake_plan(milestones):
    """Return a plan_fn that always answers with `milestones`."""
    def plan_fn(title, description, required, missing):
        return [dict(milestone) for milestone in milestones]

    return plan_fn


def test_plan_opportunity_writes_and_commits_the_plan(session):
    opportunity = _add_opportunity(session, missing=[])
    plan_fn = _fake_plan([
        _milestone("Scaffold the project"),
        _milestone("Build the API"),
        _milestone("Ship it"),
    ])

    milestones = plan_opportunity(session, opportunity, plan_fn=plan_fn)

    assert [m["title"] for m in milestones] == [
        "Scaffold the project", "Build the API", "Ship it"
    ]
    assert json.loads(opportunity.execution_plan) == milestones


def test_plan_opportunity_applies_the_coverage_guard(session):
    opportunity = _add_opportunity(session, missing=["SQL"])
    plan_fn = _fake_plan([_milestone("Build the API")])

    milestones = plan_opportunity(session, opportunity, plan_fn=plan_fn)

    assert milestones[0]["title"] == "Learn SQL"


def test_plan_opportunity_passes_the_stored_lists_to_the_model(session):
    opportunity = _add_opportunity(
        session, required=("Python", "SQL"), missing=("SQL",)
    )
    seen = {}

    def plan_fn(title, description, required, missing):
        seen.update(title=title, required=required, missing=missing)
        return [_milestone("Build it")]

    plan_opportunity(session, opportunity, plan_fn=plan_fn)

    assert seen["title"] == "An idea"
    assert seen["required"] == ["Python", "SQL"]
    assert seen["missing"] == ["SQL"]


def test_plan_opportunity_raises_on_an_empty_reply_and_writes_nothing(session):
    """7b's empty-array failure in a new place.

    An empty list written to execution_plan satisfies `IS NOT NULL`, so the row
    reads as planned forever after and is never revisited. Crashing is better.
    """
    opportunity = _add_opportunity(session, missing=["SQL"])

    with pytest.raises(ValueError, match="zero milestones"):
        plan_opportunity(session, opportunity, plan_fn=_fake_plan([]))

    assert opportunity.execution_plan is None


def test_format_plan_numbers_milestones_and_tags_their_kind(session):
    opportunity = _add_opportunity(session, "Query Assistant")
    milestones = [
        _milestone("Learn SQL", kind="learn", detail="Joins and aggregates."),
        _milestone("Build the API", detail="Expose one endpoint."),
    ]

    text = format_plan(opportunity, milestones)

    assert "Query Assistant" in text
    assert f"(id {opportunity.id})" in text
    assert "1. [learn] Learn SQL" in text
    assert "2. [build] Build the API" in text
    assert "Joins and aggregates." in text


def test_format_plan_is_ascii_only(session):
    """Em-dashes and arrows garble in the Windows console.

    Same constraint recommend/render.py was written under.
    """
    opportunity = _add_opportunity(session, "Query Assistant")
    text = format_plan(opportunity, [_milestone("Build it", detail="Do it.")])

    text.encode("ascii")


def test_show_plan_renders_a_stored_plan(session):
    opportunity = _add_opportunity(
        session,
        execution_plan=json.dumps(
            [{"title": "Learn SQL", "kind": "learn", "detail": "Basics."}]
        ),
    )

    text = show_plan(session, opportunity.id)

    assert "1. [learn] Learn SQL" in text


def test_show_plan_reports_an_unplanned_opportunity(session):
    opportunity = _add_opportunity(session)

    text = show_plan(session, opportunity.id)

    assert "no plan yet" in text
    assert "plan-opportunities" in text


def test_show_plan_reports_a_missing_opportunity(session):
    text = show_plan(session, 9999)

    assert "No opportunity with id 9999" in text


def test_plan_opportunity_checks_emptiness_before_the_coverage_guard(session):
    """Order matters, and this is the test that pins it.

    With two missing skills and an empty reply, running the guard first would
    produce a two-milestone plan of nothing but generated Learn steps and no
    build work at all - a failed generation wearing the shape of a success.
    """
    opportunity = _add_opportunity(session, missing=["SQL", "Docker"])

    with pytest.raises(ValueError, match="zero milestones"):
        plan_opportunity(session, opportunity, plan_fn=_fake_plan([]))

    assert opportunity.execution_plan is None
