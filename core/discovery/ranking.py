"""Ranking Engine — score-based sorting and formatted output.

Ranks eligible schemes by match_score (descending), breaks ties
alphabetically, and produces a formatted terminal output.
"""

from utils.logger import get_logger

logger = get_logger("ranking")

# Maximum schemes to return
_TOP_N = 10


def rank_schemes(profile, schemes):
    """Rank eligible schemes by match score.

    Sorting:
        1. match_score descending (higher = better match)
        2. name ascending (alphabetical tiebreaker for determinism)

    Args:
        profile: User profile dict (unused currently, reserved for future weighting).
        schemes: List of eligible scheme dicts with match_score.

    Returns:
        Top N ranked scheme dicts.
    """
    sorted_schemes = sorted(
        schemes,
        key=lambda s: (-s.get("match_score", 0), s.get("name", "").lower())
    )

    top = sorted_schemes[:_TOP_N]

    logger.info(
        f"[DISCOVERY] Ranked {len(schemes)} schemes, returning top {len(top)}"
    )

    return top


def format_ranked_output(ranked_schemes):
    """Format ranked schemes into a styled terminal output.

    Returns:
        Formatted multi-line string with box-drawing characters.
    """
    if not ranked_schemes:
        return "No eligible schemes found."

    # Determine box width based on longest scheme name
    max_name_len = max(len(s["name"]) for s in ranked_schemes)
    # Minimum width for the header, account for score suffix and padding
    content_width = max(max_name_len + 20, 44)
    box_width = content_width + 2  # +2 for border padding

    lines = []
    lines.append("╔" + "═" * box_width + "╗")
    header = "ELIGIBLE SCHEMES FOR YOUR PROFILE"
    lines.append("║" + header.center(box_width) + "║")
    lines.append("╠" + "═" * box_width + "╣")

    for i, scheme in enumerate(ranked_schemes, 1):
        name = scheme["name"]
        score = scheme.get("match_score", 0)
        reasons = scheme.get("match_reasons", [])

        # Line 1: number + name + score
        score_str = f"(score: {score})"
        name_line = f" {i}. {name}"
        padding = box_width - len(name_line) - len(score_str) - 1
        if padding < 1:
            padding = 1
        line1 = f"║{name_line}{' ' * padding}{score_str} ║"
        lines.append(line1)

        # Line 2: matched criteria
        if reasons:
            reasons_str = f"    Matched: {', '.join(reasons)}"
            pad2 = box_width - len(reasons_str)
            if pad2 < 0:
                pad2 = 0
            line2 = f"║{reasons_str}{' ' * pad2}║"
            lines.append(line2)

    lines.append("╚" + "═" * box_width + "╝")

    return "\n".join(lines)
