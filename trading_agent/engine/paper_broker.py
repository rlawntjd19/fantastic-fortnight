"""In-memory paper broker. No real orders are ever sent anywhere.

`execute` books any decision that cleared risk controls immediately —
there is no per-decision human-approval gate. This is a deliberate,
explicit choice for this project's *current* scope: nothing in this
codebase connects to a real brokerage or exchange, so autonomous
execution here only ever mutates this in-memory ledger.

That reasoning does NOT generalize. If real brokerage/exchange execution
is ever wired in on top of this, that integration must implement its
own explicit human-approval step independently — this class's
auto-execution behavior must not be assumed to carry over to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trading_agent.agents.schemas import Action, FinalDecision


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

    def execute(self, decision: FinalDecision) -> None:
        """Books a decision immediately, netting into any existing position
        for the symbol rather than replacing it.

        A repeated BUY on top of an open long is folded in as a
        weighted-average entry price, not reset to the new tick's price —
        resetting it would silently zero out unrealized PnL on every tick
        (that used to be exactly what happened here; a continuous `watch`
        session or `backtest` run that kept re-confirming the same signal
        would show a perfectly flat equity curve no matter what the market
        did). An order in the opposite direction closes/reduces the
        existing position first, realizing PnL on the closed portion, and
        only opens a position on the other side if it was larger than what
        was needed to flatten the original one.
        """
        if not decision.risk_verdict.approved or decision.status != "pending_approval":
            raise ValueError("Cannot execute a decision that was blocked by risk controls.")

        plan = decision.trade_plan

        if plan.action == Action.CLOSE:
            existing = self.positions.pop(plan.symbol, None)
            if existing is not None:
                pnl = existing.unrealized_pnl(plan.entry_price)
                self.realized_pnl += pnl
                self.cash_equity += pnl
                self._log(plan.symbol, "close", existing.quantity, plan.entry_price, pnl)
            return
        if plan.action == Action.HOLD:
            return

        notional = (
            self.equity({plan.symbol: plan.entry_price})
            * decision.risk_verdict.adjusted_position_pct_of_equity
            * decision.risk_verdict.adjusted_leverage
        )
        order_quantity = notional / plan.entry_price if plan.entry_price else 0.0
        if plan.action == Action.SELL:
            order_quantity = -order_quantity

        existing = self.positions.get(plan.symbol)
        opening_or_same_direction = existing is None or (existing.quantity >= 0) == (order_quantity >= 0)

        if opening_or_same_direction:
            if existing is None:
                new_quantity, new_avg_price = order_quantity, plan.entry_price
            else:
                new_quantity = existing.quantity + order_quantity
                new_avg_price = (
                    (existing.quantity * existing.avg_entry_price + order_quantity * plan.entry_price)
                    / new_quantity
                    if new_quantity != 0
                    else plan.entry_price
                )
            self.positions[plan.symbol] = Position(
                symbol=plan.symbol,
                quantity=new_quantity,
                avg_entry_price=new_avg_price,
                leverage=decision.risk_verdict.adjusted_leverage,
                stop_loss_price=plan.stop_loss_price,
            )
            self._log(plan.symbol, plan.action.value, order_quantity, plan.entry_price, None)
            return

        # Opposite direction from the existing position: close/reduce it first.
        closing_qty = min(abs(order_quantity), abs(existing.quantity))
        closed_signed_qty = closing_qty if existing.quantity > 0 else -closing_qty
        pnl = (plan.entry_price - existing.avg_entry_price) * closed_signed_qty
        self.realized_pnl += pnl
        self.cash_equity += pnl

        remaining_quantity = existing.quantity + order_quantity
        if remaining_quantity == 0:
            del self.positions[plan.symbol]
            self._log(plan.symbol, "close", -closed_signed_qty, plan.entry_price, pnl)
        elif (remaining_quantity >= 0) == (existing.quantity >= 0):
            existing.quantity = remaining_quantity
            existing.leverage = decision.risk_verdict.adjusted_leverage
            existing.stop_loss_price = plan.stop_loss_price
            self._log(plan.symbol, "reduce", -closed_signed_qty, plan.entry_price, pnl)
        else:
            self.positions[plan.symbol] = Position(
                symbol=plan.symbol,
                quantity=remaining_quantity,
                avg_entry_price=plan.entry_price,
                leverage=decision.risk_verdict.adjusted_leverage,
                stop_loss_price=plan.stop_loss_price,
            )
            self._log(plan.symbol, "flip", remaining_quantity, plan.entry_price, pnl)

    def apply_trailing_stops(self, current_prices: dict[str, float], trailing_stop_pct: float) -> None:
        """Ratchets each open position's stop-loss toward the current price
        (never loosens it). No-op for symbols with no price given here."""
        from trading_agent.engine.risk_controls import trailing_stop_price

        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol)
            if price is None:
                continue
            pos.stop_loss_price = trailing_stop_price(pos.quantity, pos.stop_loss_price, price, trailing_stop_pct)

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
