from trading_agent.agents.schemas import ResearchDebateResult, Signal
from trading_agent.agents.trader import Trader


class _CapturingLLM:
    def __init__(self):
        self.last_user_prompt = None

    def narrate(self, system: str, user: str) -> str:
        self.last_user_prompt = user
        return "ok"


def _research(signal=Signal.BULLISH, confidence=0.8):
    return ResearchDebateResult(
        bull_thesis="bull", bear_thesis="bear", consensus_signal=signal,
        consensus_confidence=confidence, rationale="research rationale",
    )


def test_recent_lessons_are_appended_to_narration_prompt_but_not_required():
    llm = _CapturingLLM()
    trader = Trader(llm)
    trader.propose("TEST", 100.0, _research())
    assert "Recent closed trades" not in llm.last_user_prompt


def test_recent_lessons_appear_in_narration_prompt_when_given():
    llm = _CapturingLLM()
    trader = Trader(llm)
    trader.propose("TEST", 100.0, _research(), recent_lessons=["losing buy on TEST: pnl=-500.00"])
    assert "Recent closed trades" in llm.last_user_prompt
    assert "losing buy on TEST" in llm.last_user_prompt


def test_recent_lessons_do_not_change_the_numeric_plan():
    llm = _CapturingLLM()
    trader = Trader(llm)
    without_lessons = trader.propose("TEST", 100.0, _research())
    with_lessons = trader.propose("TEST", 100.0, _research(), recent_lessons=["losing buy: pnl=-500.00"])

    assert without_lessons.action == with_lessons.action
    assert without_lessons.target_price == with_lessons.target_price
    assert without_lessons.stop_loss_price == with_lessons.stop_loss_price
    assert without_lessons.tranche_sizes == with_lessons.tranche_sizes
