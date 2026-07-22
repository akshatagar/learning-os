import json

import pytest

from opportunities.feasibility import skill_names, unscored_approved
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
