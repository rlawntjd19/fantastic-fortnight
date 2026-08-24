"""Adapter around Tauric/shiyu-coder's Kronos financial foundation model.

Kronos (https://github.com/shiyu-coder/Kronos, MIT license) is a
decoder-only transformer pretrained on OHLCV "candlestick" data across
45+ exchanges. Given a lookback window of bars it forecasts future
OHLCV bars; sampling it repeatedly (`sample_count`) gives a cheap
ensemble for uncertainty estimation.

Kronos is not on PyPI — its own README instructions are "clone the repo,
`pip install -r requirements.txt`, `from model import Kronos,
KronosTokenizer, KronosPredictor`". This adapter imports that `model`
package lazily so nothing in this repository breaks if it isn't present;
see README.md for the install steps.

Kronos's own paper is explicit that it forecasts *prices*, not trading
decisions — it does not claim to produce profitable buy/sell signals by
itself. Consistent with that, and with how `llm/client.py` is used
elsewhere in this codebase, this adapter only ever returns a
`ForecastResult` (a predicted price path); it has no say in position
sizing, leverage, or stop placement, which stay governed by
`engine/risk_controls.py`.
"""
from __future__ import annotations

from trading_agent.forecast.base import ForecastResult, summarize_sampled_returns

_INSTALL_HINT = (
    "Kronos is not installed. It is not distributed on PyPI; install it by "
    "cloning the upstream repo and putting its `model` package on your "
    "PYTHONPATH:\n"
    "  git clone https://github.com/shiyu-coder/Kronos.git\n"
    "  pip install -r Kronos/requirements.txt\n"
    "  export PYTHONPATH=$PYTHONPATH:$(pwd)/Kronos\n"
    "Model weights are pulled from Hugging Face on first use "
    "(e.g. NeoQuasar/Kronos-small + NeoQuasar/Kronos-Tokenizer-base)."
)


class KronosForecaster:
    def __init__(
        self,
        model_name: str = "NeoQuasar/Kronos-small",
        tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base",
        max_context: int = 512,
        device: str = "cpu",
        sample_count: int = 5,
        temperature: float = 1.0,
        top_p: float = 0.9,
    ) -> None:
        try:
            from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via guard test
            raise RuntimeError(_INSTALL_HINT) from exc

        tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
        model = Kronos.from_pretrained(model_name)
        self._predictor = KronosPredictor(model, tokenizer, max_context=max_context, device=device)
        self._sample_count = sample_count
        self._temperature = temperature
        self._top_p = top_p
        self._source = f"kronos:{model_name}"

    def forecast(self, closes: list[float], pred_len: int) -> ForecastResult:
        import pandas as pd  # kronos already hard-requires pandas + torch

        lookback = self._predictor.max_context if hasattr(self._predictor, "max_context") else len(closes)
        window = closes[-lookback:]
        # The rest of this pipeline only carries close prices between
        # stages (see MarketSnapshot.closes), so open/high/low are set
        # equal to close here. Kronos forecasts noticeably better with
        # real OHLCV bars; a provider that exposes full bars to analysts
        # should pass those through instead of this simplification.
        x_df = pd.DataFrame({"open": window, "high": window, "low": window, "close": window})
        x_timestamp = pd.Series(pd.date_range(end=pd.Timestamp.now(), periods=len(window), freq="min"))
        y_timestamp = pd.Series(
            pd.date_range(
                start=x_timestamp.iloc[-1] + pd.Timedelta(minutes=1), periods=pred_len, freq="min"
            )
        )

        sampled_final_closes: list[float] = []
        last_path: list[float] = []
        for _ in range(max(1, self._sample_count)):
            pred_df = self._predictor.predict(
                df=x_df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=self._temperature,
                top_p=self._top_p,
                sample_count=1,
            )
            path = pred_df["close"].tolist()
            sampled_final_closes.append(path[-1])
            last_path = path  # keep the last sample's full path for display

        return summarize_sampled_returns(closes[-1], sampled_final_closes, self._source, last_path)
