from sqlalchemy import select

from storage.models import Concept


def list_concepts(session) -> list[Concept]:
    """Every concept, weakest first.

    The concept store is never a gate — its stage is hardcoded unlit — so
    what this ordering puts at the top is the only thing the surface says.
    A concept below the gap threshold is invisible to idea generation and
    counts as weak against goals, so those come first.

    Null confidence sorts ahead of the lowest real value, which is SQLite's
    default for ASC and is also the honest answer: an unmeasured concept is
    not a confident one.
    """
    return list(
        session.scalars(
            select(Concept).order_by(Concept.confidence_score, Concept.name)
        )
    )
