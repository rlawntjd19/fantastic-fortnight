"""One-off: does CoreWeave (CRWV) pass this committee's own eligibility
rubric (trading_agent/committee/universe.screen_ineligible)? Reuses the
project's real YFinanceFeed + screen_ineligible exactly as the live
committee would, against real fetched data -- not a guess from memory.
Meant to be run once via workflow_dispatch and removed afterward.
"""
from trading_agent.committee.universe import UniverseEntry, screen_ineligible
from trading_agent.data.yfinance_provider import YFinanceFeed

feed = YFinanceFeed(period="5d")
snapshot = feed.get_snapshot("CRWV")
entry = UniverseEntry("CRWV", "stock", "Unclassified")

reason = screen_ineligible(entry, snapshot.fundamentals, snapshot.last_price)

print("last_price:", snapshot.last_price)
print("market_cap:", snapshot.fundamentals.get("market_cap"))
print("exchange:", snapshot.fundamentals.get("exchange"))
print("sector:", snapshot.fundamentals.get("sector"))
print("quote_type:", snapshot.fundamentals.get("quote_type"))
print("VERDICT:", "INELIGIBLE - " + reason if reason else "ELIGIBLE")
