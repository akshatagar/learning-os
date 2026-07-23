import json

import ollama
from sqlalchemy import select

from storage.models import Opportunity


def unplanned_approved(session) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.status == "approved")
            .where(Opportunity.skill_match_pct.is_not(None))
            .where(Opportunity.execution_plan.is_(None))
            .order_by(Opportunity.id)
        )
    )
