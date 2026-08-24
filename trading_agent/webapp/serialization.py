"""Recursively turns dataclasses/Enums (AnalystReport, TradePlan,
RiskVerdict, FinalDecision, CycleArtifacts, PerformanceReport, ...) into
plain JSON-safe dicts/lists, so `session.py` can hand any pipeline
object straight to `SessionRunner._emit` without each one needing to
know about JSON itself.
"""
from __future__ import annotations

import dataclasses
import enum
from typing import Any


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # fallback: never let a stray object break JSON encoding
