import pytest

from skills.entry import PROFICIENCY_BANDS, add_skill, existing_skills, find_skill
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
