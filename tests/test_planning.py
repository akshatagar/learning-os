import json

import pytest

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
