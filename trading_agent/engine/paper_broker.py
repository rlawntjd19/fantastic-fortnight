"""In-memory paper broker. No real orders are ever sent anywhere.

Every mutation (`execute`) requires an explicit `human_approved=True` flag
from the caller — the CLI is the only place that flag is ever set, and
only after a person confirms the decision printed to the terminal.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trading_agent.agents.schemas import Action, FinalDecision


class HumanApprovalRequiredError(RuntimeError):
    pass


@dataclass
class Position:
    symbol: str
    quantity: float  # signed: positive = long, negative = short
    avg_entry_price: float
    leverage: float
    stop_loss_price: float

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.avg_entry_price) * self.quantity


@dataclass
class PaperBroker:
    cash_equity: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    trade_log: list[dict] = field(default_factory=list)

    def equity(self, current_prices: dict[str, float]) -> float:
        unrealized = sum(
            pos.unrealized_pnl(current_prices.get(sym, pos.avg_entry_price))
            for sym, pos in self.positions.items()
        )
        return self.cash_equity + unrealized

    def execute(self, decision: FinalDecision, human_approved: bool) -> None:
        if not human_approved:
            raise HumanApprovalRequiredError(
                "PaperBroker.execute requires human_approved=True; no order is "
                "ever booked automatically."
            )
        if not decision.risk_verdict.approved or decision.status != "pending_approval":
            raise ValueError("Cannot execute a decision that was blocked by risk controls.")

        plan = decision.trade_plan
        notional = (
            self.equity({plan.symbol: plan.entry_price})
            * decision.risk_verdict.adjusted_position_pct_of_equity
            * decision.risk_verdict.adjusted_leverage
        )
        quantity = notional / plan.entry_price if plan.entry_price else 0.0

        if plan.action == Action.SELL:
            quantity = -quantity
        elif plan.action == Action.CLOSE:
            existing = self.positions.pop(plan.symbol, None)
            if existing is not None:
                pnl = existing.unrealized_pnl(plan.entry_price)
                self.realized_pnl += pnl
                self.cash_equity += pnl
                self._log(plan.symbol, "close", existing.quantity, plan.entry_price, pnl)
            return
        elif plan.action == Action.HOLD:
            return

        self.positions[plan.symbol] = Position(
            symbol=plan.symbol,
            quantity=quantity,
            avg_entry_price=plan.entry_price,
            leverage=decision.risk_verdict.adjusted_leverage,
            stop_loss_price=plan.stop_loss_price,
        )
        self._log(plan.symbol, plan.action.value, quantity, plan.entry_price, None)

    def check_stop_losses(self, current_prices: dict[str, float]) -> list[str]:
        """Auto-close any simulated position whose stop has been breached.

        This only ever affects the in-memory paper ledger — it is a
        simulation of what a stop order would have done, not a real order.
        """
        closed: list[str] = []
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            price = current_prices.get(symbol)
            if price is None:
                continue
            long_stop_hit = pos.quantity > 0 and price <= pos.stop_loss_price
            short_stop_hit = pos.quantity < 0 and price >= pos.stop_loss_price
            if long_stop_hit or short_stop_hit:
                pnl = pos.unrealized_pnl(price)
                self.realized_pnl += pnl
                self.cash_equity += pnl
                self._log(symbol, "stop_out", pos.quantity, price, pnl)
                del self.positions[symbol]
                closed.append(symbol)
        return closed

    def _log(self, symbol, action, quantity, price, pnl) -> None:
        self.trade_log.append(
            {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "price": price,
                "pnl": pnl,
            }
        )
