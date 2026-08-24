"""`python -m trading_agent.webapp` — launches the web UI on localhost."""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("TRADING_AGENT_WEB_PORT", "8000"))
    uvicorn.run("trading_agent.webapp.server:app", host="127.0.0.1", port=port, reload=False)
