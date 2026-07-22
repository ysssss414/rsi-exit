from __future__ import annotations

from pathlib import Path

import pandas as pd

from rsi_exit.divergence import DivergenceTracker
from rsi_exit.models import Peak


FIXTURE = Path(__file__).parent / "fixtures" / "v03_sanitized_canonical_sequence.csv"


def _flag(value: object) -> bool:
    return str(value).lower() == "true"


def test_sanitized_canonical_sequence_keeps_merged_update_audit_only() -> None:
    tracker = DivergenceTracker()
    rows = pd.read_csv(FIXTURE, keep_default_na=False)
    for row in rows.to_dict("records"):
        date = pd.Timestamp(row["peak_date"])
        created = _flag(row["canonical_created"])
        updated = _flag(row["canonical_updated"])
        peak = Peak(
            peak_id=row["candidate_peak_id"],
            candidate_peak_id=row["candidate_peak_id"],
            canonical_peak_id=row["canonical_peak_id"],
            representative_candidate_id=row["candidate_peak_id"],
            canonical_version=int(row["canonical_version"]),
            peak_index=int(row["peak_index"]),
            peak_date=date,
            confirm_index=int(row["peak_index"]) + 1,
            confirm_date=date + pd.offsets.BDay(1),
            earliest_action_date=date + pd.offsets.BDay(2),
            peak_high=float(row["peak_high"]),
            peak_close=float(row["peak_close"]),
            peak_rsi=float(row["peak_rsi"]),
            previous_day_close=float(row["previous_day_close"]),
            confirm_close=float(row["peak_close"]) - 1,
            confirm_rsi=float(row["peak_rsi"]) - 2,
            days_from_previous_peak=None,
            interim_min_close=None,
            interim_min_rsi=None,
            price_retrace_pct=None,
            rsi_retrace=None,
            is_independent_peak=created,
            merged_into_peak_id=None if created else row["canonical_peak_id"],
            previous_peak_id=None,
            canonical_updated=updated,
        )
        before = (
            tracker.divergence_count,
            tracker.last_structural_peak,
            tracker.anchor,
            tracker.divergence_chain_id,
        )
        result = tracker.process(peak)
        expected_signal = row["expected_signal"]
        if expected_signal:
            assert result.signal_type.value == expected_signal
            assert result.divergence_count == int(row["expected_count"])
        else:
            assert result is None
        if updated:
            assert before == (
                tracker.divergence_count,
                tracker.last_structural_peak,
                tracker.anchor,
                tracker.divergence_chain_id,
            )
        assert tracker.divergence_count == int(row["expected_count"])
