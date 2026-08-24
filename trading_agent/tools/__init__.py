"""Named, single-purpose entry points mirroring the tool-chain naming from
AI-Trader (https://github.com/HKUDS/AI-Trader) — tool_math / tool_trade /
tool_get_price_local / tool_jina_search — this project's design was asked
to draw ideas from.

One deliberate difference: in AI-Trader, an LLM calls these kinds of
tools itself via MCP, autonomously deciding when to fetch data or place
a trade. **Nothing here is exposed to an LLM as a callable function.**
Every module is a plain Python function other *code* calls (the CLI, the
backtest/live-runner loops, a script) — the same separation this whole
project already enforces everywhere else: analysts compute deterministic
scores, `Trader`/`ResearchManager` narrate text, and only code
(`engine/risk_controls.py`, `engine/paper_broker.py`) ever decides sizes,
prices, or whether an order books. Giving a model direct, autonomous
tool-calling authority over `tool_trade.py` would collapse that
separation back into the exact pattern this project's guardrails exist
to prevent.
"""
