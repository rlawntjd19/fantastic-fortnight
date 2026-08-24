"""Simple JSON-backed reflection memory.

After a paper trade closes, a short reflection ("what worked / what
didn't") is appended here. Later cycles can feed the most recent entries
back into analyst/trader prompts as lessons-learned context — this is the
offline, file-based analogue of the "financial memory" idea in multi-agent
trading-agent research, without any external vector-DB dependency.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ReflectionEntry:
    symbol: str
    action: str
    entry_price: float
    exit_price: float
    pnl: float
    lesson: str


class ReflectionMemory:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def append(self, entry: ReflectionEntry) -> None:
        entries = self.load_all()
        entries.append(asdict(entry))
        self._path.write_text(json.dumps(entries, indent=2))

    def load_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        return json.loads(self._path.read_text() or "[]")

    def recent_lessons(self, symbol: str, n: int = 3) -> list[str]:
        entries = [e for e in self.load_all() if e["symbol"] == symbol]
        return [e["lesson"] for e in entries[-n:]]
