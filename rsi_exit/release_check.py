from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import zipfile

import pandas as pd

from rsi_exit.config import load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import analyze_bars


BASELINE_SHA256 = "EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5"
BASELINE_MEMBER = "300308.SZ/daily_features.csv"
OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]
FORMAL_DIVERGENCES = (
    ("2026-05-28", "2026-05-29", "2026-06-01", 1, 0.7),
    ("2026-06-04", "2026-06-05", "2026-06-08", 2, 0.4),
    ("2026-06-22", "2026-06-23", "2026-06-24", 3, 0.0),
)


class FrozenBaselineError(RuntimeError):
    pass


def load_frozen_bars(path: str | Path) -> pd.DataFrame:
    baseline = Path(path)
    if not baseline.is_file():
        raise FrozenBaselineError(f"frozen baseline ZIP not found: {baseline}")
    digest = hashlib.sha256(baseline.read_bytes()).hexdigest().upper()
    if digest != BASELINE_SHA256:
        raise FrozenBaselineError(
            f"frozen baseline SHA-256 mismatch: expected {BASELINE_SHA256}, got {digest}"
        )
    try:
        with zipfile.ZipFile(baseline) as archive:
            if BASELINE_MEMBER not in archive.namelist():
                raise FrozenBaselineError(
                    f"frozen baseline member is missing: {BASELINE_MEMBER}"
                )
            with archive.open(BASELINE_MEMBER) as handle:
                frame = pd.read_csv(handle, encoding="utf-8-sig")
    except zipfile.BadZipFile as exc:
        raise FrozenBaselineError(f"invalid frozen baseline ZIP: {baseline}") from exc
    missing = set(OHLCV_COLUMNS) - set(frame.columns)
    if missing:
        raise FrozenBaselineError(
            f"frozen baseline OHLCV columns are missing: {', '.join(sorted(missing))}"
        )
    return frame.loc[:, OHLCV_COLUMNS].copy()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FrozenBaselineError(message)


def _formal_row(signals: pd.DataFrame, peak_date: str) -> pd.Series:
    rows = signals.loc[
        (signals["signal_status"] == "FORMAL")
        & (signals["current_peak_date"] == peak_date)
    ]
    _require(len(rows) == 1, f"expected one formal row for {peak_date}, got {len(rows)}")
    return rows.iloc[0]


def validate_frozen_baseline(path: str | Path) -> dict[str, object]:
    bars = load_frozen_bars(path)
    result = analyze_bars(
        bars,
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
        & (result.signals["signal_status"] == "FORMAL")
        & (result.signals["current_peak_date"] >= "2026-05-01")
    ]
    actual = list(zip(
        formal["current_peak_date"],
        formal["decision_date"],
        formal["earliest_action_date"],
        formal["divergence_count"].astype(int),
        formal["divergence_position_cap"].astype(float),
    ))
    _require(actual == list(FORMAL_DIVERGENCES), f"formal divergence sequence mismatch: {actual}")
    _require(
        set(formal["signal_type"]) == {SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value},
        "frozen formal divergence type mismatch",
    )
    _require(set(formal["momentum_anchor_date"]) == {"2026-05-14"}, "momentum anchor date mismatch")
    _require(formal["position_eligible"].astype(bool).all(), "formal divergence must be position eligible")

    anchor = _formal_row(result.signals, "2026-05-14")
    _require(anchor["momentum_anchor_date"] == "2026-05-14", "P0 momentum anchor mismatch")
    _require(int(anchor["divergence_count"]) == 0, "P0 divergence count mismatch")

    expected_nonstructural = {
        "2026-05-20": ("INTRADAY_POTENTIAL_RETEST", 0),
        "2026-06-09": ("NON_COMPARABLE_PEAK", 2),
        "2026-06-25": ("NON_COMPARABLE_PEAK", 3),
    }
    for peak_date, (relation, count) in expected_nonstructural.items():
        row = _formal_row(result.signals, peak_date)
        _require(row["price_relation"] == relation, f"{peak_date} price relation mismatch")
        _require(int(row["divergence_count"]) == count, f"{peak_date} divergence count mismatch")
        _require(not bool(row["structural_eligible"]), f"{peak_date} must be nonstructural")
        _require(not bool(row["position_eligible"]), f"{peak_date} must be position ineligible")

    forming = result.signals.loc[
        (result.signals["current_peak_date"] == "2026-06-18")
        & (result.signals["signal_type"] == SignalType.DIVERGENCE_FORMING.value)
    ]
    _require(len(forming) == 1, f"expected one 2026-06-18 forming row, got {len(forming)}")
    _require(int(forming.iloc[0]["divergence_count"]) == 2, "forming divergence count mismatch")
    _require(not bool(forming.iloc[0]["position_eligible"]), "forming row must be position ineligible")

    version_columns = [
        "candidate_peak_id", "canonical_peak_id", "canonical_version",
        "representative_candidate_id", "current_peak_date", "decision_date",
        "earliest_action_date", "current_peak_high", "current_peak_close",
        "current_peak_rsi", "price_relation", "signal_type",
        "divergence_count", "divergence_chain_id",
    ]
    full_v1 = _formal_row(result.signals, "2026-04-30")
    for cutoff in ("2026-05-07", "2026-05-18"):
        prefix_bars = bars.loc[pd.to_datetime(bars["date"]) <= pd.Timestamp(cutoff)]
        prefix_result = analyze_bars(
            prefix_bars,
            symbol="300308.SZ",
            name="中际旭创",
            config=load_config(),
            display_start_date="2026-04-01",
            display_end_date=cutoff,
        )
        prefix_v1 = _formal_row(prefix_result.signals, "2026-04-30")
        _require(
            full_v1[version_columns].to_dict() == prefix_v1[version_columns].to_dict(),
            f"PK0008 version 1 was rewritten by data through {cutoff}",
        )
    version_2 = _formal_row(result.signals, "2026-05-14")
    _require(
        (full_v1["canonical_peak_id"], int(full_v1["canonical_version"]))
        == ("PK0008", 1),
        "2026-04-30 canonical version mismatch",
    )
    _require(
        (version_2["canonical_peak_id"], int(version_2["canonical_version"]))
        == ("PK0008", 2),
        "2026-05-14 canonical version mismatch",
    )
    _require(
        version_2["chain_reset_reason"] == "ANCHOR_RSI_BREAKOUT"
        and bool(version_2["same_canonical_anchor_breakout"]),
        "2026-05-14 same-canonical anchor breakout mismatch",
    )
    _require(not bool(version_2["position_eligible"]), "anchor breakout must be position ineligible")

    prefix_columns = [
        "canonical_peak_id", "current_peak_date", "decision_date",
        "earliest_action_date", "signal_type", "divergence_count",
        "momentum_anchor_canonical_id", "previous_canonical_peak_id",
        "divergence_position_cap", "position_eligible",
    ]
    for peak_date, _, action_date, _, _ in FORMAL_DIVERGENCES:
        prefix_bars = bars.loc[pd.to_datetime(bars["date"]) <= pd.Timestamp(action_date)]
        prefix_result = analyze_bars(
            prefix_bars,
            symbol="300308.SZ",
            name="中际旭创",
            config=load_config(),
            display_start_date="2026-05-01",
            display_end_date=action_date,
        )
        full_row = _formal_row(result.signals, peak_date)
        prefix_row = _formal_row(prefix_result.signals, peak_date)
        _require(
            full_row[prefix_columns].to_dict() == prefix_row[prefix_columns].to_dict(),
            f"prefix immutability mismatch for {peak_date}",
        )

    return {
        "sha256": BASELINE_SHA256,
        "formal_divergences": len(formal),
        "status": "passed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the required v0.3 frozen baseline release check")
    parser.add_argument("--frozen-baseline", type=Path)
    args = parser.parse_args(argv)
    path = args.frozen_baseline
    if path is None:
        configured = os.getenv("RSI_EXIT_FROZEN_BASELINE_PATH")
        if configured:
            path = Path(configured)
    if path is None:
        print(
            "frozen baseline path is required; pass --frozen-baseline or set RSI_EXIT_FROZEN_BASELINE_PATH",
            file=sys.stderr,
        )
        return 2
    try:
        summary = validate_frozen_baseline(path)
    except FrozenBaselineError as exc:
        print(f"frozen baseline release check failed: {exc}", file=sys.stderr)
        return 1
    print(
        "frozen baseline release check passed: "
        f"sha256={summary['sha256']} formal_divergences={summary['formal_divergences']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
