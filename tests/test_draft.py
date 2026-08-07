import json

import pytest

from sqlalchemy import select

from goals.draft import (
    DEFAULT_REQUIREMENT_COUNT,
    REQUIREMENT_SCHEMA,
    build_draft_prompt,
    call_ollama_draft,
    draft_all,
    flag_bare_acronym,
    undrafted_goals,
)
from storage.models import Goal


@pytest.mark.parametrize("phrase", [
    "KV cache",
    "TFLOPS",
    "GQA attention",
])
def test_bare_acronyms_are_flagged(phrase):
    assert flag_bare_acronym(phrase) is True


@pytest.mark.parametrize("phrase", [
    "KV cache key-value cache",
    "GQA grouped query attention",
    "TFLOPS trillion floating point operations per second",
    "self-attention",
    "positional encoding",
])
def test_expanded_and_plain_phrases_pass(phrase):
    assert flag_bare_acronym(phrase) is False


def test_schema_is_object_wrapped_not_a_top_level_array():
    """A top-level array is satisfied by [], which returned zero ideas in 7b."""
    assert REQUIREMENT_SCHEMA["type"] == "object"
    assert REQUIREMENT_SCHEMA["required"] == ["requirements"]


def test_schema_pins_the_count_at_both_ends():
    requirements = REQUIREMENT_SCHEMA["properties"]["requirements"]
    assert requirements["minItems"] == DEFAULT_REQUIREMENT_COUNT
    assert requirements["maxItems"] == DEFAULT_REQUIREMENT_COUNT


def test_prompt_states_the_acronym_convention_with_an_example():
    prompt = build_draft_prompt("understand transformers", "llm-internals", 14)

    assert "key-value cache" in prompt
    assert "llm-internals" in prompt
    assert "understand transformers" in prompt


@pytest.mark.parametrize("category,description", [
    ("llm-internals", "understand transformer internals well enough to "
                      "modify architecture choices"),
])
@pytest.mark.live
def test_call_ollama_draft_returns_real_concept_names(category, description):
    """Live Ollama. Takes 60-90 seconds."""
    requirements = call_ollama_draft(description, category, count=14)

    assert len(requirements) >= 10
    assert all(isinstance(r, str) and r.strip() for r in requirements)
    # Not an assertion about quality, only that it did not echo the goal back.
    assert description not in requirements


def _goal(session, description="a goal", requirements=None):
    goal = Goal(description=description, category="test", priority=1,
                concept_requirements=requirements)
    session.add(goal)
    session.commit()
    return goal


def test_draft_all_fills_only_the_undrafted_rows(session):
    _goal(session, "needs drafting")
    _goal(session, "already done", json.dumps(["self-attention"]))

    counts = draft_all(session, draft_fn=lambda d, c: ["one", "two"])

    assert counts == {"drafted": 1}
    done = session.scalars(
        select(Goal).where(Goal.description == "already done")
    ).one()
    assert json.loads(done.concept_requirements) == ["self-attention"]


def test_draft_all_is_a_no_op_on_a_second_run(session):
    _goal(session, "needs drafting")
    draft_all(session, draft_fn=lambda d, c: ["one", "two"])

    counts = draft_all(session, draft_fn=lambda d, c: ["three"])

    assert counts == {"drafted": 0}


def test_draft_all_refuses_to_write_an_empty_list(session):
    """An empty list satisfies IS NOT NULL, so a failure would read as done."""
    goal = _goal(session, "needs drafting")

    with pytest.raises(ValueError, match="zero requirements"):
        draft_all(session, draft_fn=lambda d, c: [])

    session.refresh(goal)
    assert goal.concept_requirements is None
