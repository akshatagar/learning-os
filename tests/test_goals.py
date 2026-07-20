import json
import re

from sqlalchemy import select

from goals.seed import GOAL_SEEDS, seed_goals
from storage.models import Goal

EXPECTED_CATEGORIES = {
    "llm-internals",
    "training",
    "agentic-systems",
    "inference",
    "software-engineering",
}


def test_seed_goals_inserts_five_goals(session):
    goals = seed_goals(session)

    assert len(goals) == 5
    stored = session.scalars(select(Goal)).all()
    assert {g.category for g in stored} == EXPECTED_CATEGORIES
    for goal in stored:
        assert goal.priority == 1
        assert goal.description
        requirements = json.loads(goal.concept_requirements)
        assert len(requirements) == 14
        assert all(isinstance(r, str) and r.strip() for r in requirements)


def test_seed_goals_is_idempotent(session):
    seed_goals(session)
    seed_goals(session)

    assert len(session.scalars(select(Goal)).all()) == 5


def test_seed_goals_preserves_an_existing_goal_in_the_same_category(session):
    existing = Goal(
        description="my own wording",
        category="training",
        priority=3,
        concept_requirements=json.dumps(["LoRA low-rank adaptation"]),
    )
    session.add(existing)
    session.commit()

    seed_goals(session)

    stored = session.scalars(select(Goal).where(Goal.category == "training")).all()
    assert len(stored) == 1
    assert stored[0].description == "my own wording"
    assert stored[0].priority == 3


def test_every_acronym_requirement_includes_an_expansion():
    offenders = []
    for seed in GOAL_SEEDS:
        for requirement in seed["concept_requirements"]:
            has_acronym = re.search(r"\b[A-Z]{2,}\b", requirement)
            has_expansion = re.search(r"\b[a-z]{3,}\b", requirement)
            if has_acronym and not has_expansion:
                offenders.append((seed["category"], requirement))

    assert offenders == []
