from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from goals.gaps import GapResult, concept_gaps
from recommend.dedup import exclude_ingested
from recommend.filter import filter_relevant
from recommend.search import SearchResult, search
from storage.models import Goal

DEFAULT_TOP = 3
RESULTS_PER_GAP = 5


@dataclass
class GapRecommendation:
    gap: str
    score: float
    results: list[SearchResult] = field(default_factory=list)
    error: str | None = None


@dataclass
class RecommendResult:
    category: str
    gap_result: GapResult
    recommendations: list[GapRecommendation]


class RecommendState(TypedDict):
    category: str
    top: int
    gap_result: GapResult | None
    ranked_gaps: list[str]
    recommendations: list[GapRecommendation]


def rank_gaps(gap_result: GapResult, top: int) -> list[str]:
    gaps = gap_result.weak + gap_result.missing
    ranked = sorted(gaps, key=lambda phrase: gap_result.scores[phrase], reverse=True)
    return ranked[:top]


def load_goal(session, category: str) -> Goal:
    goal = session.scalars(select(Goal).where(Goal.category == category)).first()
    if goal is None:
        available = sorted(session.scalars(select(Goal.category)).all())
        raise ValueError(
            f"No goal with category {category!r}. "
            f"Available: {', '.join(available) or 'none'}"
        )
    return goal


def build_compute_gaps_node(session, collection):
    def node(state: RecommendState) -> dict:
        goal = load_goal(session, state["category"])
        return {"gap_result": concept_gaps(session, collection, goal)}

    return node


def build_rank_gaps_node():
    def node(state: RecommendState) -> dict:
        return {"ranked_gaps": rank_gaps(state["gap_result"], state["top"])}

    return node


def build_search_node(search_fn=search):
    def node(state: RecommendState) -> dict:
        gap_result = state["gap_result"]
        recommendations = []
        for gap in state["ranked_gaps"]:
            recommendation = GapRecommendation(gap=gap, score=gap_result.scores[gap])
            try:
                recommendation.results = search_fn(gap, RESULTS_PER_GAP)
            except Exception as exc:
                recommendation.error = f"search failed: {exc}"
            recommendations.append(recommendation)
        return {"recommendations": recommendations}

    return node


def build_dedup_node(session):
    def node(state: RecommendState) -> dict:
        for recommendation in state["recommendations"]:
            if recommendation.error is not None:
                continue
            recommendation.results = exclude_ingested(session, recommendation.results)
        return {"recommendations": state["recommendations"]}

    return node


def build_filter_node(filter_fn=filter_relevant):
    def node(state: RecommendState) -> dict:
        for recommendation in state["recommendations"]:
            if recommendation.error is not None:
                continue
            try:
                recommendation.results = filter_fn(
                    recommendation.gap, recommendation.results
                )
            except Exception as exc:
                recommendation.results = []
                recommendation.error = f"relevance filter failed: {exc}"
        return {"recommendations": state["recommendations"]}

    return node


def build_recommend_graph(session, collection, search_fn=search, filter_fn=filter_relevant):
    graph = StateGraph(RecommendState)
    graph.add_node("compute_gaps", build_compute_gaps_node(session, collection))
    graph.add_node("rank_gaps", build_rank_gaps_node())
    graph.add_node("search", build_search_node(search_fn))
    graph.add_node("dedup", build_dedup_node(session))
    graph.add_node("filter_relevance", build_filter_node(filter_fn))

    graph.add_edge(START, "compute_gaps")
    graph.add_edge("compute_gaps", "rank_gaps")
    graph.add_edge("rank_gaps", "search")
    graph.add_edge("search", "dedup")
    graph.add_edge("dedup", "filter_relevance")
    graph.add_edge("filter_relevance", END)

    return graph.compile()


def recommend_goal(
    session,
    collection,
    category: str,
    top: int = DEFAULT_TOP,
    search_fn=search,
    filter_fn=filter_relevant,
) -> RecommendResult:
    app = build_recommend_graph(
        session, collection, search_fn=search_fn, filter_fn=filter_fn
    )
    final_state = app.invoke({
        "category": category,
        "top": top,
        "gap_result": None,
        "ranked_gaps": [],
        "recommendations": [],
    })
    return RecommendResult(
        category=category,
        gap_result=final_state["gap_result"],
        recommendations=final_state["recommendations"],
    )
