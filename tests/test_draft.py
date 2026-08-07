import pytest

from goals.draft import (
    DEFAULT_REQUIREMENT_COUNT,
    REQUIREMENT_SCHEMA,
    build_draft_prompt,
    call_ollama_draft,
    flag_bare_acronym,
)


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
def test_call_ollama_draft_returns_real_concept_names(category, description):
    """Live Ollama. Takes 60-90 seconds."""
    requirements = call_ollama_draft(description, category, count=14)

    assert len(requirements) >= 10
    assert all(isinstance(r, str) and r.strip() for r in requirements)
    # Not an assertion about quality, only that it did not echo the goal back.
    assert description not in requirements
