import json

import pytest

from opportunities.feasibility import (
    MATCH_SCHEMA,
    _build_match_prompt,
    _clean_covered_by,
    call_ollama_match,
    score_all,
    score_opportunity,
    skill_names,
    unscored_approved,
)
from storage.models import Opportunity, Skill


def _add_skills(session, *names):
    for name in names:
        session.add(Skill(name=name, proficiency=60.0, source="user_confirmed"))
    session.commit()


def _add_opportunity(session, title="An idea", status="approved",
                     required=("Python",), skill_match_pct=None):
    opportunity = Opportunity(
        title=title,
        description="Does a thing.",
        required_skills=json.dumps(list(required)),
        source_concepts=json.dumps([]),
        status=status,
        skill_match_pct=skill_match_pct,
    )
    session.add(opportunity)
    session.commit()
    return opportunity


def test_skill_names_returns_names_alphabetically(session):
    _add_skills(session, "PyTorch", "Docker", "Python")

    assert skill_names(session) == ["Docker", "PyTorch", "Python"]


def test_skill_names_raises_on_an_empty_table(session):
    with pytest.raises(ValueError, match="add-skills"):
        skill_names(session)


def test_unscored_approved_returns_only_approved_and_unscored(session):
    _add_opportunity(session, "approved unscored")
    _add_opportunity(session, "still generated", status="generated")
    _add_opportunity(session, "rejected", status="rejected")
    _add_opportunity(session, "already scored", skill_match_pct=50.0)

    assert [o.title for o in unscored_approved(session)] == ["approved unscored"]


def test_unscored_approved_is_oldest_first(session):
    _add_opportunity(session, "first")
    _add_opportunity(session, "second")

    assert [o.title for o in unscored_approved(session)] == ["first", "second"]


def test_match_schema_is_object_wrapped():
    """A top-level array schema is satisfiable by `[]`.

    That is what made idea generation return zero ideas in 7b. Here an empty
    completion would be worse than obvious - it would score every opportunity
    at 0% and read as a real verdict rather than a failure.
    """
    assert MATCH_SCHEMA["type"] == "object"
    assert MATCH_SCHEMA["required"] == ["matches"]
    assert MATCH_SCHEMA["properties"]["matches"]["type"] == "array"


def test_build_match_prompt_lists_skills_and_requirements():
    prompt = _build_match_prompt(["Python", "Docker"], ["containerization"])

    assert "Python" in prompt
    assert "Docker" in prompt
    assert "containerization" in prompt


def test_clean_covered_by_treats_the_string_null_as_no_coverage():
    """qwen2.5:7b returns the text "null" instead of a JSON null.

    Observed live: asked about Kubernetes against a table without it, the
    model emitted the four characters n-u-l-l. The schema types covered_by as
    ["string", "null"], so a literal "null" string is valid and slips through.
    """
    assert _clean_covered_by("null") is None
    assert _clean_covered_by("NULL") is None
    assert _clean_covered_by("none") is None
    assert _clean_covered_by("") is None
    assert _clean_covered_by("   ") is None
    assert _clean_covered_by(None) is None


def test_clean_covered_by_keeps_real_skill_names():
    assert _clean_covered_by("Docker") == "Docker"
    assert _clean_covered_by("  FastAPI  ") == "FastAPI"


def test_call_ollama_match_handles_synonyms_compounds_and_true_gaps():
    """Live round-trip. These three cases are the acceptance bar.

    Embedding similarity was measured failing all of them (design spec 3a):
    'containerization' scored 0.577 against Docker, and 'FastAPI or Flask'
    scored 0.652 against FastAPI - both real matches falling below the 0.70
    threshold that gap matching uses. Kubernetes must stay uncovered, or the
    matcher is simply agreeable rather than correct.
    """
    skills = ["Python", "Docker", "FastAPI", "PyTorch"]
    required = ["containerization", "FastAPI or Flask", "Kubernetes"]

    matches = call_ollama_match(skills, required)

    covered_by = {m["requirement"]: m["covered_by"] for m in matches}
    assert covered_by.get("containerization") == "Docker"
    assert covered_by.get("FastAPI or Flask") == "FastAPI"
    assert covered_by.get("Kubernetes") is None


def test_call_ollama_match_never_names_a_skill_outside_the_list():
    """The hallucination check, run against the live model.

    A covered_by naming a skill the user does not have would inflate the
    score with something they cannot do.
    """
    skills = ["Python", "Docker"]
    required = ["Python", "Rust", "Terraform"]

    matches = call_ollama_match(skills, required)

    named = [m["covered_by"] for m in matches if m["covered_by"] is not None]
    assert all(name in skills for name in named), f"invented a skill: {named}"


def _fake_match(mapping):
    """Return a match_fn answering from `mapping`: requirement -> covering skill."""
    def match_fn(skills, required):
        return [
            {"requirement": name, "covered_by": mapping.get(name)}
            for name in required
        ]

    return match_fn


def test_score_opportunity_computes_percentage_and_missing(session):
    opportunity = _add_opportunity(
        session, required=("Python", "PyTorch", "SQL")
    )
    match_fn = _fake_match({"Python": "Python", "PyTorch": "PyTorch"})

    pct = score_opportunity(
        session, opportunity, ["Python", "PyTorch"], match_fn=match_fn
    )

    assert pct == 66.7
    assert opportunity.skill_match_pct == 66.7
    assert json.loads(opportunity.missing_skills) == ["SQL"]


def test_score_opportunity_handles_full_coverage(session):
    opportunity = _add_opportunity(session, required=("Python", "Docker"))
    match_fn = _fake_match({"Python": "Python", "Docker": "Docker"})

    pct = score_opportunity(
        session, opportunity, ["Python", "Docker"], match_fn=match_fn
    )

    assert pct == 100.0
    assert json.loads(opportunity.missing_skills) == []


def test_score_opportunity_matches_skill_names_case_insensitively(session):
    opportunity = _add_opportunity(session, required=("Python",))
    match_fn = _fake_match({"Python": "python"})

    pct = score_opportunity(session, opportunity, ["Python"], match_fn=match_fn)

    assert pct == 100.0


def test_score_opportunity_rejects_a_skill_outside_the_table(session):
    """Rule 2 of spec section 6: hallucinated coverage counts as missing.

    The model claims Rust covers the requirement, but the user has no Rust.
    Trusting it would credit the user with a skill they do not have.
    """
    opportunity = _add_opportunity(session, required=("systems programming",))
    match_fn = _fake_match({"systems programming": "Rust"})

    pct = score_opportunity(session, opportunity, ["Python"], match_fn=match_fn)

    assert pct == 0.0
    assert json.loads(opportunity.missing_skills) == ["systems programming"]


def test_score_opportunity_counts_omitted_requirements_as_missing(session):
    """Rule 1 of spec section 6: iterate the stored requirements.

    The model answers about only one of two requirements. The silent one must
    count as missing rather than vanishing from the denominator, which would
    otherwise report 100%.
    """
    opportunity = _add_opportunity(session, required=("Python", "SQL"))

    def match_fn(skills, required):
        return [{"requirement": "Python", "covered_by": "Python"}]

    pct = score_opportunity(session, opportunity, ["Python"], match_fn=match_fn)

    assert pct == 50.0
    assert json.loads(opportunity.missing_skills) == ["SQL"]


def test_score_opportunity_ignores_invented_requirements(session):
    """Rule 1 again, from the other side: extra requirements are dropped."""
    opportunity = _add_opportunity(session, required=("Python",))

    def match_fn(skills, required):
        return [
            {"requirement": "Python", "covered_by": "Python"},
            {"requirement": "Kubernetes", "covered_by": None},
        ]

    pct = score_opportunity(session, opportunity, ["Python"], match_fn=match_fn)

    assert pct == 100.0
    assert json.loads(opportunity.missing_skills) == []


def test_score_opportunity_skips_a_row_with_no_required_skills(session):
    """No denominator exists, so 0% would assert something untrue."""
    opportunity = _add_opportunity(session, required=())

    pct = score_opportunity(
        session, opportunity, ["Python"], match_fn=_fake_match({})
    )

    assert pct is None
    assert opportunity.skill_match_pct is None
    assert opportunity.missing_skills is None


def test_score_all_scores_every_unscored_approved_row(session):
    _add_skills(session, "Python", "Docker")
    _add_opportunity(session, "one", required=("Python",))
    _add_opportunity(session, "two", required=("Python", "SQL"))
    match_fn = _fake_match({"Python": "Python"})

    counts = score_all(session, match_fn=match_fn)

    assert counts == {"scored": 2, "skipped": 0}
    assert unscored_approved(session) == []


def test_score_all_raises_before_any_call_when_no_skills_exist(session):
    _add_opportunity(session, required=("Python",))

    def match_fn(skills, required):
        raise AssertionError("must not reach the model")

    with pytest.raises(ValueError, match="add-skills"):
        score_all(session, match_fn=match_fn)


def test_score_all_counts_skipped_rows(session):
    _add_skills(session, "Python")
    _add_opportunity(session, "no requirements", required=())

    counts = score_all(session, match_fn=_fake_match({}))

    assert counts == {"scored": 0, "skipped": 1}


def test_score_all_ignores_rows_that_are_already_scored(session):
    _add_skills(session, "Python")
    _add_opportunity(session, "done", required=("Python",), skill_match_pct=42.0)

    counts = score_all(session, match_fn=_fake_match({"Python": "Python"}))

    assert counts == {"scored": 0, "skipped": 0}


def test_score_all_reports_nothing_to_score(session):
    _add_skills(session, "Python")

    counts = score_all(session, match_fn=_fake_match({}))

    assert counts == {"scored": 0, "skipped": 0}


def test_score_all_keeps_scores_written_before_a_failure(session):
    """Commit is per row, so an abort mid-run does not lose earlier work."""
    _add_skills(session, "Python")
    first = _add_opportunity(session, "one", required=("Python",))
    _add_opportunity(session, "two", required=("Python",))

    calls = {"n": 0}

    def match_fn(skills, required):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("model exploded")
        return [{"requirement": "Python", "covered_by": "Python"}]

    with pytest.raises(RuntimeError, match="model exploded"):
        score_all(session, match_fn=match_fn)

    assert first.skill_match_pct == 100.0
