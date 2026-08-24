"""Macro-economic context: rate regime, market-wide risk appetite (VIX),
and dollar strength — read-only proxies `MacroAnalyst` factors in
alongside company-specific fundamentals, the same separation a trading
desk draws between a stock analyst and a macro/rates desk.

These are market-based *proxies* (10Y Treasury yield, VIX, dollar index),
not official macro releases (CPI/GDP/unemployment) — chosen because
they're available through the same `yfinance` dependency already used
for live price data, with no second API or key to manage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class MacroSnapshot:
    ten_year_yield_pct: float | None = None
    ten_year_yield_change_pct: float | None = None
    vix_level: float | None = None
    dollar_index_change_pct: float | None = None


class MacroDataProvider(Protocol):
    def get_macro_snapshot(self) -> MacroSnapshot: ...


class StaticMacroProvider:
    """Zero-dependency default: an all-None (= "no signal") snapshot.
    Used whenever live macro data isn't enabled, including every test, so
    results stay fully offline and deterministic."""

    def get_macro_snapshot(self) -> MacroSnapshot:
        return MacroSnapshot()


class YFinanceMacroProvider:
    def __init__(self, lookback_period: str = "1mo") -> None:
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "yfinance가 설치되어 있지 않습니다. 설치하려면:\n  pip install -r requirements-live.txt"
            ) from exc
        self._lookback_period = lookback_period

    def get_macro_snapshot(self) -> MacroSnapshot:
        ten_year_level, ten_year_change = self._level_and_change("^TNX")
        vix_level, _ = self._level_and_change("^VIX")
        _, dollar_change = self._level_and_change("DX-Y.NYB")

        return MacroSnapshot(
            ten_year_yield_pct=ten_year_level,
            ten_year_yield_change_pct=ten_year_change,
            vix_level=vix_level,
            dollar_index_change_pct=dollar_change,
        )

    def _level_and_change(self, ticker_symbol: str) -> tuple[float | None, float | None]:
        import yfinance as yf

        try:
            history = yf.Ticker(ticker_symbol).history(period=self._lookback_period)
            if history.empty:
                return None, None
            level = float(history["Close"].iloc[-1])
            first = float(history["Close"].iloc[0])
            change_pct = (level / first - 1) if first else None
            return level, change_pct
        except Exception:
            return None, None
