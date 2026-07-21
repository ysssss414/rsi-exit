from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pandas as pd

from rsi_exit.models import Peak, PeakEvent


class PeakDetectionError(ValueError):
    pass


class PeakDetector:
    """Online-style confirmed-peak detector with explicit same-wave state.

    Candidate t is inspected only when t+1 exists. The detector never looks beyond
    t+1 to confirm t, and an independent-wave test uses only rows strictly between
    the previous canonical peak and t.
    """

    def __init__(
        self,
        *,
        min_peak_gap: int = 3,
        min_rsi_retrace: float = 5.0,
        min_price_retrace_pct: float = 0.025,
        price_tolerance_pct: float = 0.005,
    ) -> None:
        if min_peak_gap < 1:
            raise ValueError("min_peak_gap 必须 >= 1")
        self.min_peak_gap = int(min_peak_gap)
        self.min_rsi_retrace = float(min_rsi_retrace)
        self.min_price_retrace_pct = float(min_price_retrace_pct)
        self.price_tolerance_pct = float(price_tolerance_pct)

    def detect(
        self, frame: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict[pd.Timestamp, list[PeakEvent]]]:
        data = self._normalize(frame)
        records: list[Peak] = []
        events: dict[pd.Timestamp, list[PeakEvent]] = defaultdict(list)
        active: Peak | None = None
        candidate_number = 0

        for peak_index in range(2, len(data) - 1):
            if not self._is_confirmed_candidate(data, peak_index):
                continue
            candidate_number += 1
            candidate_id = f"P{candidate_number:04d}"
            confirm_index = peak_index + 1
            action_index = peak_index + 2
            action_date = (
                data.at[action_index, "date"] if action_index < len(data) else pd.NaT
            )

            if active is None:
                record = self._make_peak(
                    data,
                    candidate_id,
                    peak_index,
                    confirm_index,
                    action_date,
                    days_from_previous_peak=None,
                    interim_min_close=None,
                    interim_min_rsi=None,
                    price_retrace_pct=None,
                    rsi_retrace=None,
                    independent=True,
                    merged_into=None,
                    previous_peak_id=None,
                )
                active = deepcopy(record)
                records.append(record)
                events[record.confirm_date].append(PeakEvent(deepcopy(record)))
                continue

            gap = peak_index - active.peak_index
            between = data.iloc[active.peak_index + 1 : peak_index]
            interim_close = self._safe_min(between["close"])
            interim_rsi = self._safe_min(between["rsi14"])
            price_retrace = (
                max(0.0, (active.peak_close - interim_close) / active.peak_close)
                if interim_close is not None and active.peak_close != 0
                else 0.0
            )
            rsi_retrace = (
                max(0.0, active.peak_rsi - interim_rsi)
                if interim_rsi is not None
                else 0.0
            )
            independent = gap >= self.min_peak_gap and (
                rsi_retrace >= self.min_rsi_retrace
                or price_retrace >= self.min_price_retrace_pct
            )

            record = self._make_peak(
                data,
                candidate_id,
                peak_index,
                confirm_index,
                action_date,
                days_from_previous_peak=gap,
                interim_min_close=interim_close,
                interim_min_rsi=interim_rsi,
                price_retrace_pct=price_retrace,
                rsi_retrace=rsi_retrace,
                independent=independent,
                merged_into=None if independent else active.peak_id,
                previous_peak_id=active.peak_id,
            )

            if independent:
                active = deepcopy(record)
            else:
                record.canonical_updated = self._prefer_candidate(record, active)
                if record.canonical_updated:
                    canonical_id = active.peak_id
                    canonical_previous_id = active.previous_peak_id
                    active = deepcopy(record)
                    active.peak_id = canonical_id
                    active.previous_peak_id = canonical_previous_id
                    active.is_independent_peak = True
                    active.merged_into_peak_id = None

            records.append(record)
            events[record.confirm_date].append(PeakEvent(deepcopy(record)))

        columns = list(Peak.__dataclass_fields__)
        output = pd.DataFrame([asdict(item) for item in records], columns=columns)
        if not output.empty:
            for column in ("peak_date", "confirm_date", "earliest_action_date"):
                output[column] = pd.to_datetime(output[column]).dt.strftime("%Y-%m-%d")
        return output, dict(events)

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        required = {"date", "close", "rsi14"}
        missing = required - set(frame.columns)
        if missing:
            raise PeakDetectionError(f"高点识别缺少字段: {', '.join(sorted(missing))}")
        data = frame.loc[:, ["date", "close", "rsi14"]].copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["close"] = pd.to_numeric(data["close"], errors="coerce")
        data["rsi14"] = pd.to_numeric(data["rsi14"], errors="coerce")
        if data["date"].isna().any():
            raise PeakDetectionError("高点识别数据包含无效日期")
        if not data["date"].is_monotonic_increasing:
            raise PeakDetectionError("高点识别数据必须按日期升序")
        return data.reset_index(drop=True)

    @staticmethod
    def _is_confirmed_candidate(data: pd.DataFrame, i: int) -> bool:
        close = data["close"].to_numpy(dtype=float)
        rsi = data["rsi14"].to_numpy(dtype=float)
        values = (close[i - 2], close[i - 1], close[i], close[i + 1],
                  rsi[i - 2], rsi[i - 1], rsi[i], rsi[i + 1])
        if any(np.isnan(value) for value in values):
            return False
        close_max = np.max(close[i - 2 : i + 1])
        rsi_max = np.max(rsi[i - 2 : i + 1])
        is_candidate = (
            close[i] > close[i - 1]
            and rsi[i] > rsi[i - 1]
            and np.isclose(close[i], close_max, rtol=1e-12, atol=1e-12)
            and np.isclose(rsi[i], rsi_max, rtol=1e-12, atol=1e-12)
        )
        return bool(
            is_candidate and close[i + 1] < close[i] and rsi[i + 1] < rsi[i]
        )

    @staticmethod
    def _safe_min(series: pd.Series) -> float | None:
        values = pd.to_numeric(series, errors="coerce").dropna()
        return None if values.empty else float(values.min())

    def _prefer_candidate(self, candidate: Peak, active: Peak) -> bool:
        clear_price_improvement = candidate.peak_close > active.peak_close * (
            1 + self.price_tolerance_pct
        )
        close_within_tolerance = abs(candidate.peak_close - active.peak_close) <= (
            active.peak_close * self.price_tolerance_pct
        )
        return bool(
            clear_price_improvement
            or (close_within_tolerance and candidate.peak_rsi > active.peak_rsi)
        )

    @staticmethod
    def _make_peak(
        data: pd.DataFrame,
        peak_id: str,
        peak_index: int,
        confirm_index: int,
        action_date: pd.Timestamp | pd.NaT,
        *,
        days_from_previous_peak: int | None,
        interim_min_close: float | None,
        interim_min_rsi: float | None,
        price_retrace_pct: float | None,
        rsi_retrace: float | None,
        independent: bool,
        merged_into: str | None,
        previous_peak_id: str | None,
    ) -> Peak:
        return Peak(
            peak_id=peak_id,
            peak_index=peak_index,
            peak_date=data.at[peak_index, "date"],
            confirm_index=confirm_index,
            confirm_date=data.at[confirm_index, "date"],
            earliest_action_date=action_date,
            peak_close=float(data.at[peak_index, "close"]),
            peak_rsi=float(data.at[peak_index, "rsi14"]),
            confirm_close=float(data.at[confirm_index, "close"]),
            confirm_rsi=float(data.at[confirm_index, "rsi14"]),
            days_from_previous_peak=days_from_previous_peak,
            interim_min_close=interim_min_close,
            interim_min_rsi=interim_min_rsi,
            price_retrace_pct=price_retrace_pct,
            rsi_retrace=rsi_retrace,
            is_independent_peak=independent,
            merged_into_peak_id=merged_into,
            previous_peak_id=previous_peak_id,
        )

