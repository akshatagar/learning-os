import re

_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
_LOWER_WORD = re.compile(r"\b[a-z]{2,}\b")


def flag_bare_acronym(phrase: str) -> bool:
    """True when a phrase carries an acronym without enough words to expand it.

    Embedding models mean-pool the whole string, so a bare acronym scores
    0.51-0.68 against its spelled-out concept and false-misses. The convention
    is that both forms appear. An N-letter acronym needs at least N lowercase
    words beside it, which is what distinguishes "KV cache" from "KV cache
    key-value cache".

    Mixed-case acronyms (RoPE, MoE) are not detected - they contain no all-caps
    run of two or more characters. This catches the common case; it is not a
    proof, which is why it warns rather than blocks.
    """
    acronyms = _ACRONYM.findall(phrase)
    if not acronyms:
        return False
    longest = max(len(acronym) for acronym in acronyms)
    return len(_LOWER_WORD.findall(phrase)) < longest
