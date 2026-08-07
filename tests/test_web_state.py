import json

from storage.models import Concept, Goal, MergeQueue, Opportunity, Skill
from web.state import HOLDING, RUNNING, UNLIT, panel_state


def _lamps(session, running_kinds=()):
    state = panel_state(session, running_kinds=running_kinds)
    return {stage["id"]: stage["lamp"] for stage in state["stages"]}


def _counts(session):
    state = panel_state(session)
    return {stage["id"]: stage["count"] for stage in state["stages"]}


def test_an_empty_database_lights_only_skills(session):
    """The resting state is dark. An empty skills table is the exception.

    Feasibility scoring cannot run without skills, and only the user can
    supply them, so an empty table is genuinely something waiting on a person.
    """
    lamps = _lamps(session)

    assert lamps["skills"] == HOLDING
    assert all(
        lamp == UNLIT for stage_id, lamp in lamps.items() if stage_id != "skills"
    )


def test_a_pending_queue_entry_lights_the_queue_interlock(session):
    session.add(Skill(name="Python", proficiency=60.0, source="user_confirmed"))
    session.add(MergeQueue(candidate_name="Attention", status="pending"))
    session.commit()

    lamps = _lamps(session)

    assert lamps["queue"] == HOLDING
    assert lamps["skills"] == UNLIT


def test_a_resolved_queue_does_not_light_the_interlock(session):
    session.add(Skill(name="Python", proficiency=60.0, source="user_confirmed"))
    session.add(MergeQueue(candidate_name="Attention", status="merged"))
    session.commit()

    assert _lamps(session)["queue"] == UNLIT


def test_generated_opportunities_light_the_approval_interlock(session):
    session.add(Skill(name="Python", proficiency=60.0, source="user_confirmed"))
    session.add(Opportunity(title="An idea", status="generated"))
    session.commit()

    assert _lamps(session)["approval"] == HOLDING


def test_resolved_opportunities_leave_approval_unlit(session):
    """Matches the real database: 3 approved, 9 rejected, nothing pending."""
    session.add(Skill(name="Python", proficiency=60.0, source="user_confirmed"))
    session.add(Opportunity(title="yes", status="approved"))
    session.add(Opportunity(title="no", status="rejected"))
    session.commit()

    assert _lamps(session)["approval"] == UNLIT


def test_a_running_kind_lights_its_stage_green(session):
    lamps = _lamps(session, running_kinds=("generate-ideas",))

    assert lamps["ideas"] == RUNNING


def test_an_interlock_holding_outranks_a_running_kind(session):
    """A gate that is holding must not be masked by work in flight.

    HOLDING is the only state that asks the user for something, so it wins.
    """
    session.add(Skill(name="Python", proficiency=60.0, source="user_confirmed"))
    session.add(Opportunity(title="An idea", status="generated"))
    session.commit()

    lamps = _lamps(session, running_kinds=("generate-ideas",))

    assert lamps["approval"] == HOLDING


def test_counts_report_real_rows(session):
    session.add(Concept(name="Self-Attention"))
    session.add(Concept(name="Beam Search"))
    session.add(Skill(name="Python", proficiency=60.0, source="user_confirmed"))
    session.commit()

    counts = _counts(session)

    assert counts["concepts"] == 2
    assert counts["skills"] == 1


def test_scoring_counts_only_scored_approved_rows(session):
    session.add(Opportunity(title="scored", status="approved", skill_match_pct=100.0))
    session.add(Opportunity(title="unscored", status="approved"))
    session.commit()

    assert _counts(session)["scoring"] == 1


def test_planning_counts_only_rows_with_a_plan(session):
    session.add(Opportunity(title="planned", status="approved",
                            execution_plan=json.dumps([])))
    session.add(Opportunity(title="unplanned", status="approved"))
    session.commit()

    assert _counts(session)["planning"] == 1


def test_stage_order_follows_the_process(session):
    """The drawing is the navigation, so payload order is the run order."""
    state = panel_state(session)

    assert [stage["id"] for stage in state["stages"]] == [
        "ingest", "resolution", "queue", "concepts", "goals",
        "ideas", "approval", "scoring", "planning", "skills",
    ]


def test_goals_lamp_holds_when_a_goal_has_no_requirements(session):
    session.add(Goal(description="new", category="new", priority=1,
                     concept_requirements=None))
    session.commit()

    stages = panel_state(session)["stages"]
    goals = next(stage for stage in stages if stage["id"] == "goals")

    assert goals["lamp"] == "holding"
