from trading_agent.data.providers import SimulatedFeed


def test_different_symbols_get_different_prices():
    feed = SimulatedFeed()
    aapl = feed.get_snapshot("AAPL")
    tsla = feed.get_snapshot("TSLA")
    assert aapl.closes != tsla.closes
    assert aapl.last_price != tsla.last_price


def test_same_seed_and_symbol_is_reproducible_across_instances():
    a = SimulatedFeed(seed=42).get_snapshot("AAPL")
    b = SimulatedFeed(seed=42).get_snapshot("AAPL")
    assert a.closes == b.closes


def test_repeated_calls_for_same_symbol_advance_instead_of_repeating():
    feed = SimulatedFeed()
    first = feed.get_snapshot("AAPL")
    second = feed.get_snapshot("AAPL")
    third = feed.get_snapshot("AAPL")
    assert first.last_price != second.last_price != third.last_price
    # window size stays bounded rather than growing unboundedly
    assert len(second.bars) == len(first.bars)


def test_bar_count_matches_configured_n_bars():
    feed = SimulatedFeed(n_bars=30)
    snapshot = feed.get_snapshot("ANY")
    assert len(snapshot.bars) == 30
