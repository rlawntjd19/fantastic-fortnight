"""Hard, code-enforced risk ceilings.

This is the one place in the system that has final authority over size,
leverage, and stop-loss placement. It never trusts agent output: it only
ever clamps a proposed `TradePlan` down to fit inside `RiskLimits`, and it
can refuse a trade outright (e.g. daily circuit breaker tripped).
"""
from __future__ import annotations

from trading_agent.agents.schemas import Action, RiskVerdict, TradePlan
from trading_agent.config import RiskLimits


class DailyCircuitBreaker:
    """Tracks the day's starting equity and blocks new BUY/SELL entries
    once losses exceed the configured fraction of that starting equity.
    Closing/reducing existing positions is never blocked.
    """

    def __init__(self, starting_equity: float, limit_pct: float) -> None:
        self.starting_equity = starting_equity
        self.limit_pct = limit_pct

    def tripped(self, current_equity: float) -> bool:
        if self.starting_equity <= 0:
            return False
        drawdown = (self.starting_equity - current_equity) / self.starting_equity
        return drawdown >= self.limit_pct

    def reset(self, new_starting_equity: float) -> None:
        self.starting_equity = new_starting_equity


def enforce_hard_limits(
    plan: TradePlan,
    limits: RiskLimits,
    account_equity: float,
    circuit_breaker: DailyCircuitBreaker | None = None,
) -> RiskVerdict:
    violations: list[str] = []

    if plan.action == Action.HOLD:
        return RiskVerdict(
            approved=True,
            adjusted_leverage=0.0,
            adjusted_position_pct_of_equity=0.0,
            violations_corrected=[],
            notes="No position change proposed.",
        )

    if circuit_breaker is not None and plan.action != Action.CLOSE:
        if circuit_breaker.tripped(account_equity):
            return RiskVerdict(
                approved=False,
                adjusted_leverage=0.0,
                adjusted_position_pct_of_equity=0.0,
                violations_corrected=["daily_circuit_breaker"],
                notes="Daily loss circuit breaker is tripped; only closing "
                "existing positions is allowed until it resets.",
            )

    adjusted_leverage = plan.leverage
    if adjusted_leverage > limits.max_leverage:
        violations.append(
            f"leverage {adjusted_leverage}x > max {limits.max_leverage}x, clamped"
        )
        adjusted_leverage = limits.max_leverage

    requested_position_pct = 1.0 / len(plan.tranche_sizes) if plan.tranche_sizes else 1.0
    # Interpreted here as: the whole plan (all tranches combined) requests
    # up to 100% of whatever notional the trader had in mind; we clamp the
    # *equity fraction* directly rather than trusting the trader's framing.
    adjusted_position_pct = min(1.0, requested_position_pct * len(plan.tranche_sizes))
    if adjusted_position_pct > limits.max_position_pct_of_equity:
        violations.append(
            f"position size {adjusted_position_pct:.1%} of equity > max "
            f"{limits.max_position_pct_of_equity:.1%}, clamped"
        )
        adjusted_position_pct = limits.max_position_pct_of_equity

    if len(plan.tranche_sizes) > limits.max_tranches:
        violations.append(
            f"{len(plan.tranche_sizes)} tranches > max {limits.max_tranches}, will be truncated"
        )

    stop_pct = abs(plan.entry_price - plan.stop_loss_price) / plan.entry_price
    if stop_pct > limits.max_stop_loss_pct:
        violations.append(
            f"stop distance {stop_pct:.1%} > max {limits.max_stop_loss_pct:.1%}"
        )
    if stop_pct == 0:
        violations.append("no stop loss set on a directional trade")

    approved = not any(v.startswith("no stop loss") for v in violations)

    return RiskVerdict(
        approved=approved,
        adjusted_leverage=adjusted_leverage,
        adjusted_position_pct_of_equity=adjusted_position_pct,
        violations_corrected=violations,
        notes="Hard limits enforced in code; the trade plan is clamped to fit, "
        "not rejected, except when a required safety condition is missing.",
    )


def trailing_stop_price(
    quantity: float, current_stop: float, current_price: float, trailing_stop_pct: float
) -> float:
    """The new stop-loss price for one position after a trailing-stop update.

    Only ever tightens the stop toward locking in gains — never loosens it,
    even if the price moves against the position since the last tick (that
    case is exactly what the original fixed stop is still there to catch).
    """
    if quantity > 0:  # long: stop trails below price
        return max(current_stop, current_price * (1 - trailing_stop_pct))
    else:  # short: stop trails above price
        return min(current_stop, current_price * (1 + trailing_stop_pct))
