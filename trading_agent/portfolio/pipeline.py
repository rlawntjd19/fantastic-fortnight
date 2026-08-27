"""End-to-end orchestration: screen the universe, select 2-5 names, size
them with mean-variance optimization, allocate the cash budget, backtest
the result over trailing history, and Monte Carlo-project the next
3 months. See `report.render_markdown_report` for turning the result into
a memo, and `cli.py`'s `portfolio` subcommand for the CLI entry point.
"""
from __future__ import annotations

from trading_agent.config import Config
from trading_agent.data.factory import build_macro_provider
from trading_agent.data.macro import MacroDataProvider
from trading_agent.data.providers import MarketDataProvider
from trading_agent.forecast.base import PriceForecaster
from trading_agent.forecast.factory import build_price_forecaster
from trading_agent.llm.client import LLMClient
from trading_agent.portfolio import risk_metrics
from trading_agent.portfolio.allocation import allocate_capital
from trading_agent.portfolio.backtest import run_portfolio_backtest
from trading_agent.portfolio.forward_simulation import monte_carlo_forward
from trading_agent.portfolio.optimizer import capm_expected_return, evaluate_weights, max_sharpe_weights
from trading_agent.portfolio.schemas import PortfolioReport
from trading_agent.portfolio.screening import ScreeningDesk
from trading_agent.portfolio.selection import select_portfolio
from trading_agent.portfolio.universe import BENCHMARK_SYMBOL, UNIVERSE


def run_portfolio_research(
    config: Config,
    llm: LLMClient,
    data_provider: MarketDataProvider,
    macro_provider: MacroDataProvider | None = None,
    forecaster: PriceForecaster | None = None,
    budget: float = 25_000.0,
    min_stocks: int = 2,
    max_stocks: int = 5,
    risk_free_rate: float = 0.045,
    market_risk_premium: float = 0.05,
    weight_cap: float = 0.60,
    min_weight: float = 0.05,
    optimizer_steps: int = 25,
    forward_paths: int = 2000,
    as_of: str = "",
    data_source: str = "simulated",
    benchmark_symbol: str = BENCHMARK_SYMBOL,
) -> PortfolioReport:
    macro_provider = macro_provider or build_macro_provider(config)
    forecaster = forecaster or build_price_forecaster(config)

    desk = ScreeningDesk(config, llm, data_provider, macro_provider, forecaster)
    candidates = desk.screen(UNIVERSE)

    benchmark_snapshot = data_provider.get_snapshot(benchmark_symbol)
    benchmark_returns = risk_metrics.daily_returns(benchmark_snapshot.closes)

    selected, rounds = select_portfolio(candidates, min_stocks=min_stocks, max_stocks=max_stocks)
    symbols = [c.symbol for c in selected]

    returns_by_symbol = {c.symbol: risk_metrics.daily_returns(c.closes) for c in selected}
    betas = {s: risk_metrics.beta(returns_by_symbol[s], benchmark_returns) for s in symbols}
    expected_returns = {
        s: capm_expected_return(betas[s], risk_free_rate, market_risk_premium) for s in symbols
    }

    optimized = max_sharpe_weights(
        symbols, expected_returns, returns_by_symbol, betas, risk_free_rate,
        weight_cap=weight_cap, min_weight=min(min_weight, 1.0 / len(symbols)), steps=optimizer_steps,
    )
    equal_weight = evaluate_weights(
        symbols, {s: 1.0 / len(symbols) for s in symbols},
        expected_returns, returns_by_symbol, betas, risk_free_rate,
    )

    prices = {c.symbol: c.last_price for c in selected}
    allocation, leftover = allocate_capital(optimized.weights, prices, budget)

    closes_by_symbol = {c.symbol: c.closes for c in selected}
    backtest = run_portfolio_backtest(
        closes_by_symbol, optimized.weights, budget,
        benchmark_closes=benchmark_snapshot.closes, risk_free_rate=risk_free_rate,
    )

    daily_drift = {
        s: (1 + expected_returns[s]) ** (1 / risk_metrics.TRADING_DAYS_PER_YEAR) - 1 for s in symbols
    }
    forward = monte_carlo_forward(
        symbols, optimized.weights, daily_drift, returns_by_symbol, budget, num_paths=forward_paths,
    )

    return PortfolioReport(
        as_of=as_of,
        data_source=data_source,
        budget=budget,
        risk_free_rate=risk_free_rate,
        market_risk_premium=market_risk_premium,
        universe=candidates,
        selection_rounds=rounds,
        selected=selected,
        optimized=optimized,
        equal_weight=equal_weight,
        allocation=allocation,
        leftover_cash=leftover,
        backtest=backtest,
        forward_simulation=forward,
        benchmark_symbol=benchmark_symbol,
    )
