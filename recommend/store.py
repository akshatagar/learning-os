import json
from datetime import datetime, timezone

from sqlalchemy import delete, select

from recommend.graph import RecommendResult, load_goal
from storage.models import Recommendation


def _serialise(results) -> str:
    return json.dumps([
        {
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet,
            "score": result.score,
        }
        for result in results
    ])


def store_recommendations(session, result: RecommendResult) -> list[Recommendation]:
    """Replace a goal's recommendations with this run's.

    Takes the category rather than a Goal because the caller is a job thread
    with its own session, and nothing loaded from the request's session may
    cross into it. Re-resolving here removes the hazard instead of documenting
    it.

    Replace rather than append: a recommendation is derived from a gap, and
    gaps move with every ingest, so a row from an earlier run was computed
    against a knowledge base that no longer exists.
    """
    goal = load_goal(session, result.category)

    session.execute(
        delete(Recommendation).where(Recommendation.goal_id == goal.id)
    )

    stamped = datetime.now(timezone.utc)
    rows = [
        Recommendation(
            goal_id=goal.id,
            gap=recommendation.gap,
            gap_score=recommendation.score,
            results=_serialise(recommendation.results),
            error=recommendation.error,
            created_at=stamped,
        )
        for recommendation in result.recommendations
    ]
    session.add_all(rows)
    session.commit()
    return rows


def recommendations_for(session, goal_id: int) -> list[Recommendation]:
    """A goal's recommendations, widest gap first.

    Descending by score matches rank_gaps, which sorts the same way before
    taking the top N — so the surface reads in the order the search chose.
    """
    return list(
        session.scalars(
            select(Recommendation)
            .where(Recommendation.goal_id == goal_id)
            .order_by(Recommendation.gap_score.desc())
        )
    )
