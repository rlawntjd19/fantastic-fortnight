"""PortfolioManager: the CIO agent that turns every desk's per-candidate
research into the standing 2-5 name shortlist.

Every ranking/filtering number below is computed in code, in a fixed,
numbered sequence — the chain-of-thought the /goal asked for is this
explicit step sequence, logged as plain text, not a single LLM guess.
The LLM (when configured) only adds a closing narrative on top of numbers
that are already final; it can't move the ranking, same discipline
`agents/analysts.py` and `agents/researchers.py` already use.
"""
from __future__ import annotations

from trading_agent.agents.schemas import Signal
from trading_agent.committee.schemas import CandidateAssessment, CommitteePick
from trading_agent.llm.client import LLMClient

_DIRECTION = {Signal.BULLISH: 1, Signal.BEARISH: -1, Signal.NEUTRAL: 0}


class PortfolioManager:
    name = "portfolio_manager"

    def __init__(
        self,
        llm: LLMClient,
        min_picks: int = 2,
        max_picks: int = 5,
        max_per_sector: int = 2,
    ) -> None:
        self._llm = llm
        self._min_picks = min_picks
        self._max_picks = max_picks
        self._max_per_sector = max_per_sector

    def select(
        self,
        candidates: list[CandidateAssessment],
        already_held: set[str],
        slots_open: int,
    ) -> tuple[list[CommitteePick], str]:
        """Fill up to `slots_open` new positions (never more) from
        `candidates`, excluding anything already held. Returns the picks and
        the full chain-of-thought rationale text."""
        steps: list[str] = []
        steps.append(
            f"Step 1 (Universe screen, upstream): {len(candidates)} candidates cleared the full "
            "eligibility rubric — NYSE/AMEX/NASDAQ-listed stock, ADR, or ETF; no open-end mutual "
            "funds; no raw index tickers; price > $5.00; market cap > $2B for stocks (well above "
            "the $500M rubric floor, per the 'no small-cap' mandate) or AUM > $500M for ETFs."
        )

        pool = [c for c in candidates if c.symbol not in already_held]
        steps.append(
            f"Step 2 (Exclude already-held names): {len(pool)} of {len(candidates)} candidates "
            f"remain after removing {len(already_held)} symbol(s) already in the open basket "
            "(rotation, not duplication)."
        )

        eligible = [c for c in pool if c.debate.consensus_signal == Signal.BULLISH]
        steps.append(
            f"Step 3 (Directional filter): {len(eligible)} of {len(pool)} candidates carry a "
            "net-bullish committee consensus (technical + fundamental + sentiment + macro + "
            "forecast desks, weighted by each desk's own confidence) for the 2-3 month horizon."
        )

        ranked = sorted(eligible, key=lambda c: c.composite_score, reverse=True)
        steps.append(
            "Step 4 (Rank by composite conviction): candidates ranked by a composite score "
            "blending (a) the weighted analyst-desk consensus and (b) 10-bar relative strength "
            "vs. SPY, since the OKR is outperformance, not just a positive return."
        )

        selected: list[CandidateAssessment] = []
        sector_counts: dict[str, int] = {}
        for c in ranked:
            if len(selected) >= slots_open:
                break
            sector = c.sector or "unclassified"
            if sector_counts.get(sector, 0) >= self._max_per_sector:
                continue
            selected.append(c)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        steps.append(
            f"Step 5 (Diversification cap): max {self._max_per_sector} new picks per sector, "
            f"filling {len(selected)} of {slots_open} open slot(s)."
        )

        # If the bullish pool alone can't fill even the floor of open slots
        # needed to keep the total basket at min_picks, relax to the
        # highest-scoring non-bearish names instead of forcing a bearish
        # pick — flagged as lower conviction, never silently promoted.
        floor_needed = max(0, min(slots_open, self._min_picks - len(already_held) + len(selected)))
        if len(selected) < floor_needed:
            fallback_pool = [
                c
                for c in pool
                if c not in selected and c.debate.consensus_signal != Signal.BEARISH
            ]
            fallback_ranked = sorted(fallback_pool, key=lambda c: c.composite_score, reverse=True)
            for c in fallback_ranked:
                if len(selected) >= floor_needed:
                    break
                sector = c.sector or "unclassified"
                if sector_counts.get(sector, 0) >= self._max_per_sector:
                    continue
                selected.append(c)
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
            steps.append(
                f"Step 6 (Floor relaxation): fewer than {self._min_picks} bullish names were "
                f"available basket-wide, so {len(selected)} lower-conviction (net non-bearish) "
                "names were added to keep the basket at its minimum size; flagged 'low' conviction below."
            )
        else:
            steps.append(f"Step 6 (Floor check): minimum basket size of {self._min_picks} already met, no relaxation needed.")

        picks = [self._to_pick(c) for c in selected]
        cot = "\n".join(f"- {s}" for s in steps)

        if picks:
            summary_input = "\n".join(
                f"{p.symbol} ({p.sector}): composite score {p.composite_score:+.2f}, "
                f"conviction {p.conviction}" for p in picks
            )
        else:
            summary_input = "No new names met the bar this run; holding the existing basket unchanged."
        narrative = self._llm.narrate(
            system=(
                "You are the Chief Investment Officer chairing an equity research committee. "
                "In 2-3 sentences, summarize today's new picks and why they were chosen over the "
                "rest of the field, for a 2-3 month holding horizon aimed at beating SPY."
            ),
            user=summary_input,
        )
        return picks, f"{cot}\n\nCIO summary: {narrative}"

    def _to_pick(self, c: CandidateAssessment) -> CommitteePick:
        if c.debate.consensus_signal == Signal.BULLISH and c.debate.consensus_confidence >= 0.5:
            conviction = "high"
        elif c.debate.consensus_signal == Signal.BULLISH:
            conviction = "medium"
        else:
            conviction = "low"
        thesis = (
            f"{c.debate.rationale} Relative strength vs SPY (10-bar): "
            f"{'n/a' if c.relative_strength_vs_spy is None else f'{c.relative_strength_vs_spy * 100:+.1f}%'}."
        )
        return CommitteePick(
            symbol=c.symbol,
            security_type=c.security_type,
            sector=c.sector,
            composite_score=c.composite_score,
            entry_price=c.last_price,
            thesis=thesis,
            conviction=conviction,
        )
