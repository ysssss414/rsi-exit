from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import analyze_bars
from rsi_exit.release_check import load_frozen_bars as load_required_bars
from rsi_exit.release_check import validate_frozen_baseline


BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "outputs"
    / "v0.2.1_baseline"
    / "300308.SZ_v0.2.1_frozen_baseline.zip"
)


def load_frozen_bars() -> pd.DataFrame:
    configured = os.getenv("RSI_EXIT_FROZEN_BASELINE_PATH")
    path = Path(configured) if configured else BASELINE_PATH
    if not path.exists():
        pytest.skip(
            "real frozen baseline regression was not executed: "
            "set RSI_EXIT_FROZEN_BASELINE_PATH to the private ZIP"
        )
    return load_required_bars(path)


@pytest.mark.frozen_baseline_required
def test_required_300308_frozen_baseline_release_check() -> None:
    configured = os.getenv("RSI_EXIT_FROZEN_BASELINE_PATH")
    path = Path(configured) if configured else BASELINE_PATH
    validate_frozen_baseline(path)


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


def test_300308_pk0008_versions_are_additive_and_anchor_breakout_is_position_ineligible() -> None:
    result = analyze_bars(
        load_frozen_bars(), symbol="300308.SZ", config=load_config(),
        display_start_date="2026-04-01", display_end_date="2026-07-20",
    )
    formal = result.signals.loc[result.signals["signal_status"] == "FORMAL"].set_index(
        "current_peak_date"
    )
    version_1 = formal.loc["2026-04-30"]
    version_2 = formal.loc["2026-05-14"]
    assert (
        version_1["candidate_peak_id"], version_1["canonical_peak_id"],
        int(version_1["canonical_version"]),
    ) == ("CP0014", "PK0008", 1)
    assert (
        version_2["candidate_peak_id"], version_2["canonical_peak_id"],
        int(version_2["canonical_version"]),
    ) == ("CP0015", "PK0008", 2)
    assert version_2["chain_reset_reason"] == "ANCHOR_RSI_BREAKOUT"
    assert bool(version_2["same_canonical_anchor_breakout"])
    assert version_2["momentum_anchor_date"] == "2026-05-14"
    assert version_2["divergence_count"] == 0
    assert not bool(version_2["position_eligible"])
