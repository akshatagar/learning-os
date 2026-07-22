import random

from sqlalchemy import select

from storage.models import Concept

HIGH_CONFIDENCE = 0.7
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_IDEA_COUNT = 3


def sample_concepts(session, n=DEFAULT_SAMPLE_SIZE, rng=random) -> list[Concept]:
    eligible = list(
        session.scalars(
            select(Concept)
            .where(Concept.confidence_score >= HIGH_CONFIDENCE)
            .order_by(Concept.id)
        )
    )
    if not eligible:
        raise ValueError(
            f"No concepts with confidence_score >= {HIGH_CONFIDENCE} to sample from"
        )
    if len(eligible) <= n:
        return eligible
    return rng.sample(eligible, n)
