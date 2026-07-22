import json

import pytest

from opportunities.feasibility import (
    MATCH_SCHEMA,
    _build_match_prompt,
    _clean_covered_by,
    call_ollama_match,
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
