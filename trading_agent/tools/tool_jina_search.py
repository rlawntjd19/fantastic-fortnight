"""tool_jina_search.py — optional market-news search via Jina AI's Search
API (https://jina.ai, free tier available).

Optional and off by default: needs a `JINA_API_KEY`. Without one this is
simply unused — `SentimentAnalyst` already has a working, keyless news
source (`YFinanceFeed`'s own `ticker.news`, see `data/yfinance_provider.py`).
This exists only to mirror AI-Trader's tool-chain naming for anyone who
wants a second, broader news source; nothing wires it in automatically.

Uses stdlib `urllib` only — no new dependency. Could not be tested
against the real Jina endpoint in this environment (outbound network to
third-party APIs is blocked in this sandbox); the response-parsing logic
is covered with a mocked HTTP response instead.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def search_market_news(query: str, api_key: str | None = None, top_k: int = 5) -> list[str]:
    """Returns up to `top_k` headline strings for `query`. Raises
    RuntimeError with a clear message if no API key is configured or the
    request fails — callers should catch this and fall back to another
    news source, the same pattern used everywhere else an optional data
    source is wired in (see `forecast/kronos_forecaster.py`,
    `data/yfinance_provider.py`)."""
    key = api_key or os.environ.get("JINA_API_KEY")
    if not key:
        raise RuntimeError(
            "JINA_API_KEY가 설정되어 있지 않습니다. https://jina.ai 에서 무료로 발급 가능합니다. "
            "설정 전까지는 YFinanceFeed의 뉴스(ticker.news)가 대신 사용됩니다."
        )

    url = "https://s.jina.ai/" + urllib.parse.quote(query, safe="")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Jina 검색 요청이 실패했습니다: {exc}") from exc

    results = payload.get("data", [])
    return [item["title"] for item in results[:top_k] if item.get("title")]
