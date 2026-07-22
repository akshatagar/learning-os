from sqlalchemy import select

from storage.models import Opportunity, Skill


def skill_names(session) -> list[str]:
    names = list(session.scalars(select(Skill.name).order_by(Skill.name)))
    if not names:
        raise ValueError(
            "No skills on record - run 'add-skills' first, or every "
            "opportunity would score 0%"
        )
    return names


def unscored_approved(session) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.status == "approved")
            .where(Opportunity.skill_match_pct.is_(None))
            .order_by(Opportunity.id)
        )
    )
