from goals.gaps import GapResult


def rank_gaps(gap_result: GapResult, top: int) -> list[str]:
    gaps = gap_result.weak + gap_result.missing
    ranked = sorted(gaps, key=lambda phrase: gap_result.scores[phrase], reverse=True)
    return ranked[:top]
