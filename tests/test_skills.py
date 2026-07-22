import pytest

from skills.entry import (
    PROFICIENCY_BANDS,
    add_skill,
    existing_skills,
    find_skill,
    run_skill_entry_loop,
)
from storage.models import Skill


def test_bands_have_the_specified_values():
    assert PROFICIENCY_BANDS == {
        "s": ("strong", 85.0),
        "w": ("working", 60.0),
        "f": ("familiar", 35.0),
    }


def test_add_skill_writes_name_proficiency_and_source(session):
    skill, created = add_skill(session, "docker", "w")

    assert created is True
    assert skill.name == "docker"
    assert skill.proficiency == 60.0
    assert skill.source == "user_confirmed"


def test_add_skill_leaves_last_used_null(session):
    skill, _ = add_skill(session, "docker", "w")

    assert skill.last_used is None


def test_add_skill_strips_surrounding_whitespace(session):
    skill, _ = add_skill(session, "  docker  ", "s")

    assert skill.name == "docker"


def test_add_skill_returns_existing_without_creating_a_duplicate(session):
    first, _ = add_skill(session, "docker", "w")

    second, created = add_skill(session, "Docker", "s")

    assert created is False
    assert second.id == first.id
    assert len(existing_skills(session)) == 1


def test_add_skill_does_not_modify_an_existing_row(session):
    add_skill(session, "docker", "w")

    skill, _ = add_skill(session, "docker", "s")

    assert skill.proficiency == 60.0


def test_add_skill_raises_for_an_unknown_band(session):
    with pytest.raises(ValueError, match="proficiency band"):
        add_skill(session, "docker", "z")


def test_find_skill_matches_case_insensitively(session):
    add_skill(session, "Docker", "w")

    assert find_skill(session, "docker") is not None
    assert find_skill(session, "  DOCKER  ") is not None


def test_find_skill_returns_none_when_absent(session):
    assert find_skill(session, "docker") is None


def test_existing_skills_orders_by_name(session):
    session.add_all([
        Skill(name="python", source="user_confirmed"),
        Skill(name="alembic", source="user_confirmed"),
        Skill(name="docker", source="user_confirmed"),
    ])
    session.commit()

    assert [s.name for s in existing_skills(session)] == ["alembic", "docker", "python"]


def test_existing_skills_is_empty_initially(session):
    assert existing_skills(session) == []


def _scripted(*keys):
    responses = iter(keys)

    def input_fn(prompt=""):
        return next(responses)

    return input_fn


def test_loop_adds_a_skill_with_the_chosen_band(session):
    counts = run_skill_entry_loop(session, input_fn=_scripted("docker", "w", ""))

    assert counts["added"] == 1
    skills = existing_skills(session)
    assert len(skills) == 1
    assert skills[0].name == "docker"
    assert skills[0].proficiency == 60.0
    assert skills[0].source == "user_confirmed"


def test_loop_adds_several_skills(session):
    counts = run_skill_entry_loop(
        session, input_fn=_scripted("docker", "w", "python", "s", "")
    )

    assert counts["added"] == 2
    assert [s.name for s in existing_skills(session)] == ["docker", "python"]


def test_loop_exits_immediately_on_a_blank_name(session):
    counts = run_skill_entry_loop(session, input_fn=_scripted(""))

    assert counts["added"] == 0
    assert existing_skills(session) == []


def test_loop_treats_a_whitespace_only_name_as_blank(session):
    counts = run_skill_entry_loop(session, input_fn=_scripted("   "))

    assert counts["added"] == 0
    assert existing_skills(session) == []


def test_loop_reprompts_on_an_unrecognized_band(session):
    counts = run_skill_entry_loop(session, input_fn=_scripted("docker", "z", "w", ""))

    assert counts["added"] == 1
    assert existing_skills(session)[0].proficiency == 60.0


def test_loop_updates_an_existing_skill_when_confirmed(session):
    add_skill(session, "docker", "f")

    counts = run_skill_entry_loop(session, input_fn=_scripted("Docker", "y", "s", ""))

    assert counts["updated"] == 1
    skills = existing_skills(session)
    assert len(skills) == 1
    assert skills[0].proficiency == 85.0


def test_loop_leaves_an_existing_skill_alone_when_declined(session):
    add_skill(session, "docker", "f")

    counts = run_skill_entry_loop(session, input_fn=_scripted("docker", "n", ""))

    assert counts["unchanged"] == 1
    assert existing_skills(session)[0].proficiency == 35.0


def test_loop_persists_entries_made_before_an_abort(session):
    def input_fn(prompt=""):
        responses = input_fn.responses
        if not responses:
            raise EOFError
        return responses.pop(0)

    input_fn.responses = ["docker", "w", "python", "s"]

    counts = run_skill_entry_loop(session, input_fn=input_fn)

    assert counts["added"] == 2
    assert [s.name for s in existing_skills(session)] == ["docker", "python"]


def test_loop_aborting_during_the_band_prompt_keeps_earlier_skills(session):
    def input_fn(prompt=""):
        responses = input_fn.responses
        if not responses:
            raise KeyboardInterrupt
        return responses.pop(0)

    input_fn.responses = ["docker", "w", "python"]

    counts = run_skill_entry_loop(session, input_fn=input_fn)

    assert counts["added"] == 1
    assert [s.name for s in existing_skills(session)] == ["docker"]
