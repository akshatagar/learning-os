from sqlalchemy import func, select

from storage.models import (
    AdjudicationLog,
    Concept,
    ContentLog,
    Goal,
    MergeQueue,
    Opportunity,
    Skill,
)

HOLDING = "holding"
RUNNING = "running"
UNLIT = "unlit"


def _count(session, model, *where) -> int:
    statement = select(func.count()).select_from(model)
    for clause in where:
        statement = statement.where(clause)
    return session.scalar(statement)


def panel_state(session, running_kinds=()) -> dict:
    """Every stage's count and lamp, in process order.

    One call renders the whole panel. The home surface is a single drawing,
    and assembling it from six requests would make it appear in pieces.
    """
    running = set(running_kinds)

    pending_queue = _count(session, MergeQueue, MergeQueue.status == "pending")
    pending_ideas = _count(session, Opportunity, Opportunity.status == "generated")
    skill_count = _count(session, Skill)
    undrafted_goals = _count(session, Goal, Goal.concept_requirements.is_(None))

    def flow(kind: str) -> str:
        return RUNNING if kind in running else UNLIT

    def gate(pending: int) -> str:
        # HOLDING outranks RUNNING: a gate waiting on a person must never be
        # masked by work in flight elsewhere.
        return HOLDING if pending else UNLIT

    stages = [
        {"id": "ingest", "label": "Ingest",
         "count": _count(session, ContentLog), "lamp": flow("ingest")},
        {"id": "resolution", "label": "Resolution",
         "count": _count(session, AdjudicationLog), "lamp": flow("ingest")},
        {"id": "queue", "label": "Merge Queue",
         "count": pending_queue, "lamp": gate(pending_queue)},
        {"id": "concepts", "label": "Concept Store",
         "count": _count(session, Concept), "lamp": UNLIT},
        {"id": "goals", "label": "Goals",
         "count": _count(session, Goal),
         # HOLDING outranks RUNNING, the same rule gate() states: a goal whose
         # requirements were never drafted is waiting on a person, and a
         # recommend run elsewhere must not mask it.
         "lamp": HOLDING if undrafted_goals else flow("recommend")},
        {"id": "ideas", "label": "Ideas",
         "count": _count(session, Opportunity), "lamp": flow("generate-ideas")},
        {"id": "approval", "label": "Approval",
         "count": pending_ideas, "lamp": gate(pending_ideas)},
        {"id": "scoring", "label": "Scoring",
         "count": _count(
             session,
             Opportunity,
             Opportunity.status == "approved",
             Opportunity.skill_match_pct.is_not(None),
         ),
         "lamp": flow("score-opportunities")},
        {"id": "planning", "label": "Planning",
         "count": _count(
             session, Opportunity, Opportunity.execution_plan.is_not(None)
         ),
         "lamp": flow("plan-opportunities")},
        {"id": "skills", "label": "Skills",
         "count": skill_count, "lamp": gate(0 if skill_count else 1)},
    ]

    return {"stages": stages}
