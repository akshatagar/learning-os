import json
import random
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from opportunities.generate import (
    DEFAULT_IDEA_COUNT,
    DEFAULT_SAMPLE_SIZE,
    GENERATION_SCHEMA,
    HIGH_CONFIDENCE,
    _build_generation_prompt,
    build_generation_graph,
    call_ollama_generate,
    generate_ideas,
    sample_concepts,
)
from opportunities.review import (
    format_opportunity,
    pending_opportunities,
    resolve_opportunity,
    run_idea_review_loop,
)
from storage.models import Concept, Opportunity


def _add_concepts(session, count, confidence=0.9):
    for index in range(count):
        session.add(Concept(name=f"concept {index}", confidence_score=confidence))
    session.commit()


def _all_opportunities(session):
    return list(session.scalars(select(Opportunity).order_by(Opportunity.id)))


def test_opportunity_round_trips_the_new_columns(session):
    now = datetime.now(timezone.utc)
    session.add(
        Opportunity(
            title="Local RAG eval harness",
            description="Build a harness.",
            required_skills=json.dumps(["python", "chromadb"]),
            source_concepts=json.dumps([1, 2, 3]),
            created_at=now,
        )
    )
    session.commit()

    stored = _all_opportunities(session)[0]

    assert json.loads(stored.required_skills) == ["python", "chromadb"]
    assert json.loads(stored.source_concepts) == [1, 2, 3]
    assert stored.created_at is not None
    assert stored.status == "generated"
    assert stored.skill_match_pct is None
    assert stored.missing_skills is None


def test_defaults_are_five_concepts_and_three_ideas():
    assert DEFAULT_SAMPLE_SIZE == 5
    assert DEFAULT_IDEA_COUNT == 3
    assert HIGH_CONFIDENCE == 0.7


def test_sample_concepts_returns_exactly_n(session):
    _add_concepts(session, 10)

    assert len(sample_concepts(session, 5)) == 5


def test_sample_concepts_excludes_low_confidence(session):
    _add_concepts(session, 3, confidence=0.9)
    _add_concepts(session, 3, confidence=0.4)

    sampled = sample_concepts(session, 5)

    assert len(sampled) == 3
    assert all(c.confidence_score >= HIGH_CONFIDENCE for c in sampled)


def test_sample_concepts_returns_all_when_fewer_than_n_qualify(session):
    _add_concepts(session, 2)

    assert len(sample_concepts(session, 5)) == 2


def test_sample_concepts_raises_when_none_qualify(session):
    _add_concepts(session, 3, confidence=0.4)

    with pytest.raises(ValueError, match="confidence_score"):
        sample_concepts(session, 5)


def test_sample_concepts_raises_on_an_empty_kb(session):
    with pytest.raises(ValueError, match="confidence_score"):
        sample_concepts(session, 5)


def test_sample_concepts_is_deterministic_under_a_seeded_rng(session):
    _add_concepts(session, 10)

    first = [c.id for c in sample_concepts(session, 5, rng=random.Random(0))]
    second = [c.id for c in sample_concepts(session, 5, rng=random.Random(0))]

    assert first == second


def _fake_generate(ideas):
    def generate_fn(concept_names, count):
        return ideas

    return generate_fn


IDEAS = [
    {
        "title": "Local RAG eval harness",
        "description": "Build a harness.",
        "required_skills": ["python", "chromadb"],
    },
    {
        "title": "KV cache visualiser",
        "description": "Render cache growth.",
        "required_skills": ["python"],
    },
]


def test_generate_ideas_writes_one_opportunity_per_idea(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, generate_fn=_fake_generate(IDEAS))

    assert len(created) == 2
    assert [o.title for o in created] == ["Local RAG eval harness", "KV cache visualiser"]
    assert all(o.status == "generated" for o in created)


def test_generate_ideas_stores_skills_concepts_and_timestamp(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, sample_size=4, generate_fn=_fake_generate(IDEAS))

    first = created[0]
    assert json.loads(first.required_skills) == ["python", "chromadb"]
    assert len(json.loads(first.source_concepts)) == 4
    assert first.created_at is not None


def test_generate_ideas_leaves_7c_columns_null(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, generate_fn=_fake_generate(IDEAS))

    assert all(o.skill_match_pct is None for o in created)
    assert all(o.missing_skills is None for o in created)


def test_generate_ideas_passes_only_sampled_names_to_the_model(session):
    _add_concepts(session, 6)
    seen = {}

    def generate_fn(concept_names, count):
        seen["names"] = concept_names
        seen["count"] = count
        return IDEAS

    generate_ideas(session, sample_size=3, count=2, generate_fn=generate_fn)

    assert len(seen["names"]) == 3
    assert seen["count"] == 2
    assert all(isinstance(name, str) for name in seen["names"])


def test_generate_ideas_writes_nothing_when_generation_fails(session):
    _add_concepts(session, 6)

    def generate_fn(concept_names, count):
        raise RuntimeError("model exploded")

    with pytest.raises(RuntimeError, match="model exploded"):
        generate_ideas(session, generate_fn=generate_fn)

    assert _all_opportunities(session) == []


def test_generate_ideas_accepts_fewer_ideas_than_requested(session):
    _add_concepts(session, 6)

    created = generate_ideas(session, count=5, generate_fn=_fake_generate(IDEAS[:1]))

    assert len(created) == 1


def test_build_generation_prompt_lists_the_concepts_and_count():
    prompt = _build_generation_prompt(["RAG", "reranking"], 3)

    assert "RAG" in prompt
    assert "reranking" in prompt
    assert "3" in prompt


def test_build_generation_graph_has_expected_nodes(session):
    app = build_generation_graph(session)

    assert set(app.get_graph().nodes) >= {"sample", "generate", "write_opportunities"}


def test_generation_schema_is_object_wrapped():
    """A top-level array schema lets the model satisfy it with `[]`.

    An empty array is always schema-valid, so a constrained decoder can emit
    `]` immediately as the shortest legal completion. Wrapping the array in an
    object with a required key forces it past the opening structure and into
    generating items. Measured: the array form returned `[ ]` on every run.
    """
    assert GENERATION_SCHEMA["type"] == "object"
    assert GENERATION_SCHEMA["required"] == ["ideas"]
    assert GENERATION_SCHEMA["properties"]["ideas"]["type"] == "array"


def test_build_generation_prompt_distinguishes_skills_from_concepts():
    prompt = _build_generation_prompt(["Beam search"], 2)

    assert "Do NOT list the concepts above as skills" in prompt


def test_call_ollama_generate_asks_for_skills_not_the_concepts_back():
    """Live: required_skills must name buildable tools, not echo the concepts.

    The first implementation returned things like "Transformer architecture"
    and "Sinusoidal positional encoding" as required skills. Those are what
    the project is about, not what builds it, and 7c matches required_skills
    against a skills table holding entries like "python" and "docker" — so
    echoing concepts back would make every skill_match_pct near zero.

    An exact-match check against the passed concepts is too weak: the model
    returned "Transformer architecture" for a call that did not include that
    concept, so the echo slips through. This instead requires at least one
    recognizable implementation technology across all ideas.
    """
    ideas = call_ollama_generate(["KV cache", "beam search", "attention mechanism"], 3)

    implementation_vocabulary = {
        "python", "pytorch", "tensorflow", "jax", "numpy", "scipy", "pandas",
        "huggingface", "hugging face", "transformers", "cuda", "docker",
        "git", "linux", "c++", "rust", "javascript", "sql", "fastapi", "flask",
    }
    all_skills = [s.lower() for idea in ideas for s in idea["required_skills"]]

    assert all_skills, "no required_skills returned at all"
    assert any(
        any(tool in skill for tool in implementation_vocabulary)
        for skill in all_skills
    ), f"no buildable technology named, only concepts: {all_skills}"


def test_call_ollama_generate_returns_schema_valid_ideas():
    """Live round-trip against a running Ollama.

    Asks for 3 ideas and requires at least 2. An earlier version asked for 2
    and accepted 1, which passed while the real CLI run produced zero.
    """
    ideas = call_ollama_generate(
        ["KV cache", "beam search", "attention mechanism"], 3
    )

    assert isinstance(ideas, list)
    assert len(ideas) >= 2
    for idea in ideas:
        assert isinstance(idea["title"], str) and idea["title"]
        assert isinstance(idea["description"], str) and idea["description"]
        assert isinstance(idea["required_skills"], list)


def _scripted(*keys):
    responses = iter(keys)

    def input_fn(prompt=""):
        return next(responses)

    return input_fn


def _add_idea(session, title="An idea", status="generated"):
    opportunity = Opportunity(
        title=title,
        description="Does a thing.",
        required_skills=json.dumps(["python"]),
        source_concepts=json.dumps([]),
        status=status,
        created_at=datetime.now(timezone.utc),
    )
    session.add(opportunity)
    session.commit()
    return opportunity


def test_pending_opportunities_returns_only_generated(session):
    _add_idea(session, "pending one")
    _add_idea(session, "already approved", status="approved")

    assert [o.title for o in pending_opportunities(session)] == ["pending one"]


def test_resolve_opportunity_sets_status(session):
    idea = _add_idea(session)

    assert resolve_opportunity(session, idea, "approve") == "approved"
    assert idea.status == "approved"


def test_resolve_opportunity_rejects(session):
    idea = _add_idea(session)

    assert resolve_opportunity(session, idea, "reject") == "rejected"


def test_resolve_opportunity_raises_for_an_unknown_action(session):
    idea = _add_idea(session)

    with pytest.raises(ValueError, match="approval action"):
        resolve_opportunity(session, idea, "maybe")


def test_format_opportunity_shows_title_concepts_and_skills(session):
    idea = _add_idea(session, "Local RAG harness")

    rendered = format_opportunity(idea, ["RAG", "reranking"], 1, 3)

    assert "Local RAG harness" in rendered
    assert "RAG" in rendered
    assert "reranking" in rendered
    assert "python" in rendered
    assert "1/3" in rendered


def test_loop_applies_each_action(session):
    _add_idea(session, "one")
    _add_idea(session, "two")
    _add_idea(session, "three")

    counts = run_idea_review_loop(session, input_fn=_scripted("a", "r", "s"))

    assert counts == {"approved": 1, "rejected": 1, "skipped": 1}
    assert [o.status for o in _all_opportunities(session)] == [
        "approved", "rejected", "generated",
    ]


def test_loop_reprompts_on_an_unrecognized_key(session):
    _add_idea(session, "one")

    counts = run_idea_review_loop(session, input_fn=_scripted("zzz", "a"))

    assert counts["approved"] == 1


def test_loop_quit_leaves_later_ideas_pending(session):
    _add_idea(session, "one")
    _add_idea(session, "two")

    counts = run_idea_review_loop(session, input_fn=_scripted("a", "q"))

    assert counts["approved"] == 1
    assert [o.status for o in _all_opportunities(session)] == ["approved", "generated"]


def test_loop_persists_decisions_made_before_an_abort(session):
    _add_idea(session, "one")
    _add_idea(session, "two")

    def input_fn(prompt=""):
        if not input_fn.responses:
            raise KeyboardInterrupt
        return input_fn.responses.pop(0)

    input_fn.responses = ["a"]

    counts = run_idea_review_loop(session, input_fn=input_fn)

    assert counts["approved"] == 1
    assert [o.status for o in _all_opportunities(session)] == ["approved", "generated"]


def test_loop_reports_nothing_pending(session):
    counts = run_idea_review_loop(session, input_fn=_scripted())

    assert counts == {"approved": 0, "rejected": 0, "skipped": 0}


def test_loop_includes_leftovers_from_an_earlier_run(session):
    _add_idea(session, "old leftover")
    _add_idea(session, "freshly generated")

    counts = run_idea_review_loop(session, input_fn=_scripted("a", "a"))

    assert counts["approved"] == 2
