"""Point-in-time panel store — prove as-of reads never leak future facts."""

from bist_trader_mcp.data_store import PanelStore, _date_to_ts


def _store() -> PanelStore:
    return PanelStore(path=":memory:")


def test_schema_and_counts_empty():
    with _store() as s:
        c = s.counts()
        assert c == {"prices": 0, "fundamentals": 0, "universe": 0, "foreign_flow": 0}


def test_upsert_is_idempotent():
    with _store() as s:
        row = {"ticker": "THYAO", "date": "2024-01-02", "close": 100.0,
               "known_at": _date_to_ts("2024-01-02")}
        s.upsert_prices([row])
        s.upsert_prices([{**row, "close": 101.0}])  # same PK → replace, not dup
        assert s.counts()["prices"] == 1
        got = s.get_price_as_of("THYAO", "2024-02-01")
        assert got["close"] == 101.0


def test_fundamental_known_at_defaults_to_kap_publish():
    with _store() as s:
        # Q4 2023 results (period_end Dec) but only disclosed in March 2024.
        s.upsert_fundamentals([{
            "ticker": "ASELS", "period_end": "2023-12-31",
            "statement": "income", "line_item": "net_income",
            "value": 1000.0, "kap_publish_date": "2024-03-01",
        }])
        # As of Feb 2024 the result was NOT yet public → must not be returned.
        assert s.get_fundamental_as_of("ASELS", "net_income", "2024-02-15") is None
        # As of April 2024 it is public.
        got = s.get_fundamental_as_of("ASELS", "net_income", "2024-04-01")
        assert got is not None and got["value"] == 1000.0


def test_fundamental_as_of_picks_latest_known_period():
    with _store() as s:
        s.upsert_fundamentals([
            {"ticker": "EREGL", "period_end": "2023-12-31", "statement": "income",
             "line_item": "revenue", "value": 500.0, "kap_publish_date": "2024-03-01"},
            {"ticker": "EREGL", "period_end": "2024-03-31", "statement": "income",
             "line_item": "revenue", "value": 600.0, "kap_publish_date": "2024-05-01"},
        ])
        # Between the two disclosures, only the FY2023 figure is known.
        mid = s.get_fundamental_as_of("EREGL", "revenue", "2024-04-15")
        assert mid["value"] == 500.0
        # After Q1 disclosure, the newer period wins.
        latest = s.get_fundamental_as_of("EREGL", "revenue", "2024-06-01")
        assert latest["value"] == 600.0


def test_price_as_of_respects_known_at():
    with _store() as s:
        s.upsert_prices([
            {"ticker": "GARAN", "date": "2024-01-10", "close": 50.0,
             "known_at": _date_to_ts("2024-01-10")},
            {"ticker": "GARAN", "date": "2024-01-11", "close": 52.0,
             "known_at": _date_to_ts("2024-01-11")},
        ])
        got = s.get_price_as_of("GARAN", "2024-01-10")
        assert got["close"] == 50.0  # the 11th's bar is not yet knowable


def test_active_universe_is_survivorship_safe():
    with _store() as s:
        s.upsert_universe([
            {"ticker": "AAA", "date": "2024-01-01", "in_xu100": True, "is_active": True,
             "known_at": _date_to_ts("2024-01-01")},
            {"ticker": "BBB", "date": "2024-01-01", "in_xu100": True, "is_active": True,
             "known_at": _date_to_ts("2024-01-01")},
            # BBB delisted mid-year.
            {"ticker": "BBB", "date": "2024-06-01", "in_xu100": False, "is_active": False,
             "known_at": _date_to_ts("2024-06-01")},
        ])
        # Early in the year both names were live.
        assert s.active_universe_as_of("2024-02-01") == ["AAA", "BBB"]
        # After delisting, BBB drops out — but its history remains in the panel.
        assert s.active_universe_as_of("2024-07-01") == ["AAA"]


def test_foreign_flow_roundtrip_and_counts():
    with _store() as s:
        n = s.upsert_foreign_flow([
            {"ticker": "THYAO", "date": "2024-01-02", "foreign_ratio": 0.41,
             "known_at": _date_to_ts("2024-01-03")},
        ])
        assert n == 1
        assert s.counts()["foreign_flow"] == 1
