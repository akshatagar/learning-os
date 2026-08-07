import pytest

from goals.draft import flag_bare_acronym


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
