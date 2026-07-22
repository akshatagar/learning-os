from recommend.graph import RecommendResult


def format_recommendations(result: RecommendResult) -> str:
    gaps = result.gap_result
    lines = [
        f"{result.category} - {len(gaps.present)} present, "
        f"{len(gaps.weak)} weak, {len(gaps.missing)} missing",
        "",
    ]

    if not result.recommendations:
        lines.append("No gaps to search - this goal is fully covered.")
        return "\n".join(lines)

    for recommendation in result.recommendations:
        lines.append(f"GAP  {recommendation.gap}  ({recommendation.score:.2f})")
        if recommendation.error is not None:
            lines.append(f"  ! {recommendation.error}")
        elif not recommendation.results:
            lines.append("  nothing new - all results already ingested or filtered out")
        else:
            for search_result in recommendation.results:
                lines.append(f"  {search_result.url}")
                lines.append(f"     {search_result.title}")
        lines.append("")

    return "\n".join(lines)
