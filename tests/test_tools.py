import json
from unittest.mock import MagicMock, patch

import pytest

from trading_agent.agents.schemas import Action, FinalDecision, RiskVerdict, TradePlan
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.tools import tool_get_price_local, tool_math, tool_trade
from trading_agent.tools.tool_jina_search import search_market_news


def test_tool_math_reexports_indicators_and_performance():
    assert tool_math.sma([1, 2, 3], 2) == 2.5
    report = tool_math.compute_performance([100.0, 110.0], [])
    assert report.total_return_pct == pytest.approx(0.10)


def test_tool_get_price_local_reads_latest_price():
    direct_price = SimulatedFeed().get_snapshot("AAPL").last_price
    tool_price = tool_get_price_local.get_latest_price(SimulatedFeed(), "AAPL")
    # Same seed/symbol, first call on a fresh instance each time -> identical.
    assert tool_price == pytest.approx(direct_price)


def _decision():
    plan = TradePlan(
        symbol="TEST", action=Action.BUY, entry_price=100.0, target_price=110.0,
        stop_loss_price=95.0, leverage=1.0, tranche_sizes=[1.0], rationale="test",
    )
    verdict = RiskVerdict(
        approved=True, adjusted_leverage=1.0, adjusted_position_pct_of_equity=0.10,
        violations_corrected=[], notes="",
    )
    return FinalDecision(trade_plan=plan, risk_verdict=verdict, status="pending_approval")


def test_tool_trade_execute_decision_books_into_broker():
    broker = PaperBroker(cash_equity=1_000_000)
    tool_trade.execute_decision(broker, _decision())
    assert "TEST" in broker.positions


def test_tool_trade_check_stop_losses_delegates_to_broker():
    broker = PaperBroker(cash_equity=1_000_000)
    tool_trade.execute_decision(broker, _decision())
    closed = tool_trade.check_stop_losses(broker, {"TEST": 90.0})
    assert closed == ["TEST"]


def test_jina_search_raises_actionable_error_without_api_key(monkeypatch):
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="JINA_API_KEY"):
        search_market_news("some query")


def test_jina_search_parses_titles_from_mocked_response():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps(
        {"data": [{"title": "Headline one"}, {"title": "Headline two"}, {}]}
    ).encode()
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=fake_response):
        headlines = search_market_news("AAPL news", api_key="fake-key", top_k=5)

    assert headlines == ["Headline one", "Headline two"]
