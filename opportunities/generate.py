import json
import random
from datetime import datetime, timezone
from typing import TypedDict

import ollama
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from storage.models import Concept, Opportunity

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


_IDEA_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "required_skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "description", "required_skills"],
}

# The idea array is wrapped in an object rather than being the top-level schema.
# A top-level array is satisfied by `[]`, so the constrained decoder can emit `]`
# immediately as the shortest legal completion — measured, it did so on every
# run, for every concept set and idea count tried. Requiring an "ideas" key
# forces it past the opening structure and into generating items.
GENERATION_SCHEMA = {
    "type": "object",
    "properties": {"ideas": {"type": "array", "items": _IDEA_SCHEMA}},
    "required": ["ideas"],
}


class GenerateState(TypedDict):
    sample_size: int
    count: int
    sampled_ids: list[int]
    sampled_names: list[str]
    ideas: list[dict]
    opportunity_ids: list[int]


def _build_generation_prompt(concept_names: list[str], count: int) -> str:
    listing = "\n".join(f"- {name}" for name in concept_names)
    return (
        "You are proposing concrete project ideas for someone learning AI "
        "engineering.\n\n"
        f"They currently understand these concepts:\n{listing}\n\n"
        f"Propose {count} distinct project ideas that COMBINE these concepts. "
        "Every idea must genuinely use at least two of them together. Do not "
        "propose ideas that depend on concepts absent from the list above.\n\n"
        "For each idea give a short title and a two-to-three sentence "
        "description of what would be built.\n\n"
        "Also list the practical skills someone needs to BUILD it: programming "
        "languages, libraries, frameworks, and engineering practices, such as "
        "Python, PyTorch, Docker, SQL, or API design. Do NOT list the concepts "
        "above as skills - those are what the project is about, not what is "
        "needed to build it."
    )


def call_ollama_generate(concept_names: list[str], count: int) -> list[dict]:
    response = ollama.chat(
        model="qwen2.5:7b",
        messages=[
            {"role": "user", "content": _build_generation_prompt(concept_names, count)}
        ],
        format=GENERATION_SCHEMA,
    )
    return json.loads(response["message"]["content"])["ideas"]


def build_sample_node(session, rng=random):
    def node(state: GenerateState) -> dict:
        concepts = sample_concepts(session, state["sample_size"], rng=rng)
        return {
            "sampled_ids": [c.id for c in concepts],
            "sampled_names": [c.name for c in concepts],
        }

    return node


def build_generate_node(generate_fn=call_ollama_generate):
    def node(state: GenerateState) -> dict:
        return {"ideas": generate_fn(state["sampled_names"], state["count"])}

    return node


def build_write_opportunities_node(session):
    def node(state: GenerateState) -> dict:
        source_concepts = json.dumps(state["sampled_ids"])
        now = datetime.now(timezone.utc)
        opportunity_ids = []
        for idea in state["ideas"]:
            opportunity = Opportunity(
                title=idea["title"],
                description=idea["description"],
                required_skills=json.dumps(idea["required_skills"]),
                source_concepts=source_concepts,
                status="generated",
                created_at=now,
            )
            session.add(opportunity)
            session.flush()
            opportunity_ids.append(opportunity.id)
        session.commit()
        return {"opportunity_ids": opportunity_ids}

    return node


def build_generation_graph(session, generate_fn=call_ollama_generate, rng=random):
    graph = StateGraph(GenerateState)
    graph.add_node("sample", build_sample_node(session, rng=rng))
    graph.add_node("generate", build_generate_node(generate_fn))
    graph.add_node("write_opportunities", build_write_opportunities_node(session))

    graph.add_edge(START, "sample")
    graph.add_edge("sample", "generate")
    graph.add_edge("generate", "write_opportunities")
    graph.add_edge("write_opportunities", END)

    return graph.compile()


def generate_ideas(
    session,
    sample_size=DEFAULT_SAMPLE_SIZE,
    count=DEFAULT_IDEA_COUNT,
    generate_fn=call_ollama_generate,
    rng=random,
) -> list[Opportunity]:
    app = build_generation_graph(session, generate_fn=generate_fn, rng=rng)
    final_state = app.invoke({
        "sample_size": sample_size,
        "count": count,
        "sampled_ids": [],
        "sampled_names": [],
        "ideas": [],
        "opportunity_ids": [],
    })
    return [
        session.get(Opportunity, opportunity_id)
        for opportunity_id in final_state["opportunity_ids"]
    ]
