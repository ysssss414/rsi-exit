from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import analyze_bars


BASELINE_SHA256 = "EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5"
BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "outputs"
    / "v0.2.1_baseline"
    / "300308.SZ_v0.2.1_frozen_baseline.zip"
)


def load_frozen_bars() -> pd.DataFrame:
    if not BASELINE_PATH.exists():
        pytest.skip("v0.2.1 frozen baseline ZIP is not available in this workspace")
    assert hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest().upper() == BASELINE_SHA256
    with zipfile.ZipFile(BASELINE_PATH) as archive:
        with archive.open("300308.SZ/daily_features.csv") as handle:
            frame = pd.read_csv(handle, encoding="utf-8-sig")
    return frame[["date", "open", "high", "low", "close", "volume", "amount"]]


def test_300308_frozen_baseline_has_expected_v03_structural_chain() -> None:
    result = analyze_bars(
        load_frozen_bars(),
        symbol="300308.SZ",
        name="中际旭创",
        config=load_config(),
        display_start_date="2026-05-01",
        display_end_date="2026-07-20",
    )
    formal_types = {
        SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
        SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
    }
    formal = result.signals.loc[
        result.signals["signal_type"].isin(formal_types)
        & (result.signals["current_peak_date"] >= "2026-05-01")
    ]
    assert list(zip(
        formal["current_peak_date"],
        formal["decision_date"],
        formal["signal_type"],
        formal["divergence_count"],
    )) == [
        ("2026-05-28", "2026-05-29", "NEW_HIGH_BEARISH_DIVERGENCE", 1),
        ("2026-06-04", "2026-06-05", "NEW_HIGH_BEARISH_DIVERGENCE", 2),
        ("2026-06-22", "2026-06-23", "NEW_HIGH_BEARISH_DIVERGENCE", 3),
    ]
    assert set(formal["momentum_anchor_date"]) == {"2026-05-14"}


def test_300308_low_peaks_and_forming_are_isolated_from_formal_chain() -> None:
    result = analyze_bars(
        load_frozen_bars(), symbol="300308.SZ", config=load_config(),
        display_start_date="2026-05-01", display_end_date="2026-07-20",
    )
    formal_audit = result.signals.loc[result.signals["signal_status"] == "FORMAL"].set_index(
        "current_peak_date"
    )
    # The general 4.3 formula makes 5/20 an intraday potential retest:
    # high=1071 >= zone low=1049.20, while close=1037 is below the zone.
    assert formal_audit.loc["2026-05-20", "price_relation"] == "INTRADAY_POTENTIAL_RETEST"
    assert not bool(formal_audit.loc["2026-05-20", "structural_eligible"])
    for date in ("2026-06-09", "2026-06-25"):
        assert formal_audit.loc[date, "price_relation"] == "NON_COMPARABLE_PEAK"
        assert not bool(formal_audit.loc[date, "position_eligible"])

    forming = result.signals.loc[
        (result.signals["current_peak_date"] == "2026-06-18")
        & (result.signals["signal_type"] == SignalType.DIVERGENCE_FORMING.value)
    ]
    assert len(forming) == 1
    assert not bool(forming.iloc[0]["position_eligible"])
    third = result.signals.loc[
        (result.signals["current_peak_date"] == "2026-06-22")
        & (result.signals["signal_status"] == "FORMAL")
    ].iloc[0]
    assert third["decision_date"] == "2026-06-23"
    assert third["divergence_count"] == 3
