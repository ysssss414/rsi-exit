from __future__ import annotations

import pandas as pd
import pytest

from rsi_exit.data.amazingdata_adapter import AmazingDataAdapter, DataSourceError


def raw_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "open": [100.0, 200.0],
            "high": [110.0, 220.0],
            "low": [90.0, 180.0],
            "close": [105.0, 210.0],
            "volume": [1000.0, 2000.0],
            "amount": [100000.0, 400000.0],
        }
    )


def test_forward_adjustment_normalizes_to_latest_factor() -> None:
    factor = pd.DataFrame(
        {"300308.SZ": [1.0, 2.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    adjusted = AmazingDataAdapter._apply_forward_adjustment(
        raw_bars(), factor, "300308.SZ"
    )
    assert adjusted.loc[0, "close"] == pytest.approx(52.5)
    assert adjusted.loc[1, "close"] == pytest.approx(210.0)
    assert adjusted["volume"].tolist() == [1000.0, 2000.0]
    assert adjusted["amount"].tolist() == [100000.0, 400000.0]


def test_forward_adjustment_rejects_missing_initial_factor() -> None:
    factor = pd.DataFrame(
        {"300308.SZ": [2.0]}, index=pd.to_datetime(["2026-01-02"])
    )
    with pytest.raises(DataSourceError):
        AmazingDataAdapter._apply_forward_adjustment(raw_bars(), factor, "300308.SZ")


def test_bar_validation_sorts_deduplicates_and_keeps_last() -> None:
    raw = pd.concat([raw_bars().iloc[::-1], raw_bars().iloc[[1]].assign(close=211.0)])
    validated = AmazingDataAdapter._validate_bars(raw, "300308.SZ")
    assert validated["date"].tolist() == ["2026-01-01", "2026-01-02"]
    assert validated.iloc[-1]["close"] == 211.0


def test_bar_validation_rejects_missing_required_value() -> None:
    raw = raw_bars()
    raw.loc[0, "amount"] = None
    with pytest.raises(DataSourceError):
        AmazingDataAdapter._validate_bars(raw, "300308.SZ")
