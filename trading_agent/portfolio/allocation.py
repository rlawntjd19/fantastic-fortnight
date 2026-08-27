"""Turn target weights + a cash budget into whole-share orders.

Whole-share investing always leaves some cash on the table relative to
the continuous target weights the optimizer produced (you can't buy 2.7
shares). This does one greedy improvement pass after the initial floor
so leftover cash isn't just abandoned: on each pass it buys one more
share of whichever held name is currently furthest *below* its target
dollar weight, as long as it can still afford a share of it — a standard
"round down, then greedily top up" approach for small, discrete
portfolios like this one.
"""
from __future__ import annotations

from trading_agent.portfolio.schemas import AllocationLine


def allocate_capital(
    weights: dict[str, float],
    prices: dict[str, float],
    budget: float,
) -> tuple[list[AllocationLine], float]:
    symbols = list(weights)
    shares = {s: 0 for s in symbols}
    for s in symbols:
        price = prices[s]
        if price > 0:
            shares[s] = int((weights[s] * budget) // price)

    remaining = budget - sum(shares[s] * prices[s] for s in symbols)

    while True:
        affordable = [s for s in symbols if prices[s] > 0 and prices[s] <= remaining]
        if not affordable:
            break
        current_dollars = {s: shares[s] * prices[s] for s in symbols}
        deficits = {s: weights[s] * budget - current_dollars[s] for s in affordable}
        best = max(affordable, key=lambda s: deficits[s])
        if deficits[best] <= 0:
            break
        shares[best] += 1
        remaining -= prices[best]

    lines = [
        AllocationLine(
            symbol=s,
            target_weight=weights[s],
            price=prices[s],
            shares=shares[s],
            dollars=shares[s] * prices[s],
            actual_weight=(shares[s] * prices[s] / budget) if budget else 0.0,
        )
        for s in symbols
    ]
    return lines, remaining
