"""Portfolio manager: turns ranked candidate scores into a 2-5 name,
sector-diversified shortlist.

This is the "repeat until there's a solid logical flow" step made
explicit and inspectable rather than a single opaque cutoff: each round
tries a stricter diversification rule first (at most one pick per sector)
and only relaxes it if that round can't fill `min_stocks` names, exactly
the way a real allocator would rather concentrate than end up unfunded.
Every round's reasoning is kept in a `SelectionRound` so the final report
can show the trace, not just the answer.
"""
from __future__ import annotations

from trading_agent.portfolio.schemas import CandidateScore, SelectionRound

# (round_number, max_picks_per_sector, minimum composite_score to qualify)
# Round 1 insists on real diversification and real conviction; each later
# round relaxes exactly one of those two knobs rather than both at once,
# so the trace shows *which* constraint had to give.
_ROUNDS: list[tuple[int, int | None, float]] = [
    (1, 1, 0.15),
    (2, 2, 0.05),
    (3, None, 0.0),
]


def select_portfolio(
    candidates: list[CandidateScore],
    min_stocks: int = 2,
    max_stocks: int = 5,
) -> tuple[list[CandidateScore], list[SelectionRound]]:
    if not (2 <= min_stocks <= max_stocks):
        raise ValueError("require 2 <= min_stocks <= max_stocks")

    ranked = sorted(candidates, key=lambda c: c.composite_score, reverse=True)
    rounds: list[SelectionRound] = []

    for round_number, sector_cap, threshold in _ROUNDS:
        picked: list[CandidateScore] = []
        sector_counts: dict[str, int] = {}
        for c in ranked:
            if c.composite_score <= threshold:
                continue
            if sector_cap is not None and sector_counts.get(c.sector, 0) >= sector_cap:
                continue
            picked.append(c)
            sector_counts[c.sector] = sector_counts.get(c.sector, 0) + 1
            if len(picked) >= max_stocks:
                break

        cap_desc = f"max {sector_cap}/sector" if sector_cap is not None else "no sector cap"
        notes = (
            f"Round {round_number}: {cap_desc}, composite score > {threshold:+.2f} -> "
            f"{len(picked)} name(s) qualified ({', '.join(c.symbol for c in picked) or 'none'})."
        )
        if len(picked) < min_stocks:
            notes += f" Below the {min_stocks}-stock floor; relaxing constraints and trying again."

        rounds.append(
            SelectionRound(
                round_number=round_number,
                sector_cap=sector_cap,
                score_threshold=threshold,
                considered=[c.symbol for c in ranked],
                selected=[c.symbol for c in picked],
                notes=notes,
            )
        )
        if len(picked) >= min_stocks:
            return picked[:max_stocks], rounds

    # Every round failed to clear the floor with a positive-conviction
    # screen — fall back to the top `min_stocks` names outright, regardless
    # of sign, clearly flagged as a low-conviction, degraded pick rather
    # than silently returned as if it were an ordinary result.
    fallback = ranked[:min_stocks]
    rounds.append(
        SelectionRound(
            round_number=len(_ROUNDS) + 1,
            sector_cap=None,
            score_threshold=float("-inf"),
            considered=[c.symbol for c in ranked],
            selected=[c.symbol for c in fallback],
            notes=(
                "Fallback: no round found enough net-bullish names with diversification "
                f"to fill the {min_stocks}-stock floor. Took the top {min_stocks} names by "
                "composite score regardless of sign — treat this as a lower-conviction, "
                "capital-preservation-tilted pick, not a high-conviction bull thesis."
            ),
        )
    )
    return fallback, rounds
