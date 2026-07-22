from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pandas as pd

from rsi_exit.models import CanonicalPeak, FormingPeakEvent, Peak, PeakEvent


class PeakDetectionError(ValueError):
    pass


class PeakDetector:
    """Causal confirmed-candidate detector with immutable dual identities."""

    def __init__(
        self,
        *,
        lookback: int = 3,
        require_recent_window_max: bool = False,
        min_peak_gap: int = 3,
        min_rsi_retrace: float = 5.0,
        min_price_retrace_pct: float = 0.025,
        price_tolerance_pct: float = 0.005,
    ) -> None:
        if lookback < 2 or min_peak_gap < 1:
            raise ValueError("lookback 必须 >= 2 且 min_peak_gap 必须 >= 1")
        self.lookback = int(lookback)
        self.require_recent_window_max = bool(require_recent_window_max)
        self.min_peak_gap = int(min_peak_gap)
        self.min_rsi_retrace = float(min_rsi_retrace)
        self.min_price_retrace_pct = float(min_price_retrace_pct)
        self.price_tolerance_pct = float(price_tolerance_pct)
        self._canonical: dict[str, CanonicalPeak] = {}
        self.forming_events: dict[pd.Timestamp, list[FormingPeakEvent]] = {}

    def detect(
        self,
        frame: pd.DataFrame,
        *,
        trading_calendar: list[pd.Timestamp] | pd.Series | None = None,
    ) -> tuple[pd.DataFrame, dict[pd.Timestamp, list[PeakEvent]]]:
        data = self._normalize(frame)
        calendar = pd.DatetimeIndex(
            pd.to_datetime(data["date"] if trading_calendar is None else trading_calendar)
        ).sort_values().unique()
        records: list[Peak] = []
        events: dict[pd.Timestamp, list[PeakEvent]] = defaultdict(list)
        self.forming_events = self._build_forming_events(data)
        active: CanonicalPeak | None = None
        candidate_number = 0
        canonical_number = 0
        self._canonical = {}
        first_index = self.lookback - 1 if self.require_recent_window_max else 1

        for peak_index in range(first_index, len(data) - 1):
            if not self._is_confirmed_candidate(data, peak_index):
                continue
            candidate_number += 1
            candidate_id = f"CP{candidate_number:04d}"
            confirm_index = peak_index + 1
            action_index = peak_index + 2
            future_dates = calendar[calendar > data.at[confirm_index, "date"]]
            action_date = future_dates[0] if len(future_dates) else pd.NaT

            metrics = self._relationship_metrics(data, active, peak_index)
            independent = active is None or (
                metrics["days_from_previous_peak"] >= self.min_peak_gap
                and (
                    metrics["rsi_retrace"] >= self.min_rsi_retrace
                    or metrics["price_retrace_pct"] >= self.min_price_retrace_pct
                )
            )
            old_representative = None if active is None else active.representative_candidate_id
            old_canonical = None if active is None else active.canonical_peak_id

            if independent:
                canonical_number += 1
                canonical_id = f"PK{canonical_number:04d}"
                version = 1
                updated = False
                representative = candidate_id
            else:
                assert active is not None
                canonical_id = active.canonical_peak_id
                updated = self._prefer_candidate_values(
                    float(data.at[peak_index, "close"]),
                    float(data.at[peak_index, "rsi14"]),
                    active,
                )
                version = active.canonical_version + 1 if updated else active.canonical_version
                representative = candidate_id if updated else active.representative_candidate_id

            record = Peak(
                peak_id=candidate_id,
                candidate_peak_id=candidate_id,
                canonical_peak_id=canonical_id,
                representative_candidate_id=representative,
                canonical_version=version,
                peak_index=peak_index,
                peak_date=data.at[peak_index, "date"],
                confirm_index=confirm_index,
                confirm_date=data.at[confirm_index, "date"],
                earliest_action_date=action_date,
                peak_close=float(data.at[peak_index, "close"]),
                peak_rsi=float(data.at[peak_index, "rsi14"]),
                confirm_close=float(data.at[confirm_index, "close"]),
                confirm_rsi=float(data.at[confirm_index, "rsi14"]),
                days_from_previous_peak=metrics["days_from_previous_peak"],
                interim_min_close=metrics["interim_min_close"],
                interim_min_rsi=metrics["interim_min_rsi"],
                price_retrace_pct=metrics["price_retrace_pct"],
                rsi_retrace=metrics["rsi_retrace"],
                is_independent_peak=independent,
                merged_into_peak_id=None if independent else canonical_id,
                previous_peak_id=old_canonical,
                previous_candidate_peak_id=old_representative,
                previous_canonical_peak_id=old_canonical,
                canonical_updated=updated,
                peak_high=float(data.at[peak_index, "high"]),
                previous_day_close=float(data.at[peak_index - 1, "close"]),
            )

            if independent or updated:
                active = CanonicalPeak(
                    canonical_peak_id=canonical_id,
                    representative_candidate_id=candidate_id,
                    canonical_version=version,
                    peak_index=record.peak_index,
                    peak_date=record.peak_date,
                    confirm_index=record.confirm_index,
                    confirm_date=record.confirm_date,
                    earliest_action_date=record.earliest_action_date,
                    peak_close=record.peak_close,
                    peak_rsi=record.peak_rsi,
                    confirm_close=record.confirm_close,
                    confirm_rsi=record.confirm_rsi,
                    days_from_previous_peak=record.days_from_previous_peak,
                    interim_min_close=record.interim_min_close,
                    interim_min_rsi=record.interim_min_rsi,
                    price_retrace_pct=record.price_retrace_pct,
                    rsi_retrace=record.rsi_retrace,
                    previous_canonical_peak_id=old_canonical if independent else active.previous_canonical_peak_id,
                    peak_high=record.peak_high,
                    previous_day_close=record.previous_day_close,
                )
                self._canonical[canonical_id] = deepcopy(active)
            assert active is not None
            records.append(record)
            events[record.confirm_date].append(
                PeakEvent(
                    peak=deepcopy(record),
                    canonical=deepcopy(active),
                    canonical_created=independent,
                    canonical_updated=updated,
                )
            )

        columns = list(Peak.__dataclass_fields__)
        output = pd.DataFrame([asdict(item) for item in records], columns=columns)
        return self._format_dates(output), dict(events)

    def canonical_peaks_frame(self) -> pd.DataFrame:
        columns = list(CanonicalPeak.__dataclass_fields__)
        frame = pd.DataFrame([asdict(item) for item in self._canonical.values()], columns=columns)
        return self._format_dates(frame)

    def _is_confirmed_candidate(self, data: pd.DataFrame, i: int) -> bool:
        close = data["close"].to_numpy(dtype=float)
        rsi = data["rsi14"].to_numpy(dtype=float)
        if any(np.isnan(value) for value in (close[i - 1], close[i], close[i + 1], rsi[i - 1], rsi[i], rsi[i + 1])):
            return False
        candidate = close[i] > close[i - 1] and rsi[i] > rsi[i - 1]
        if self.require_recent_window_max:
            start = i - self.lookback + 1
            candidate = candidate and bool(
                np.isclose(close[i], np.max(close[start : i + 1]), rtol=1e-12, atol=1e-12)
                and np.isclose(rsi[i], np.max(rsi[start : i + 1]), rtol=1e-12, atol=1e-12)
            )
        return bool(candidate and close[i + 1] < close[i] and rsi[i + 1] < rsi[i])

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        required = {"date", "close", "rsi14"}
        missing = required - set(frame.columns)
        if missing:
            raise PeakDetectionError(f"高点识别缺少字段: {', '.join(sorted(missing))}")
        columns = ["date", "close", "rsi14"] + (["high"] if "high" in frame else [])
        data = frame.loc[:, columns].copy()
        if "high" not in data:
            data["high"] = data["close"]
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["close"] = pd.to_numeric(data["close"], errors="coerce")
        data["high"] = pd.to_numeric(data["high"], errors="coerce")
        data["rsi14"] = pd.to_numeric(data["rsi14"], errors="coerce")
        if data["date"].isna().any() or not data["date"].is_monotonic_increasing:
            raise PeakDetectionError("高点识别日期必须有效且升序")
        return data.reset_index(drop=True)

    @staticmethod
    def _build_forming_events(
        data: pd.DataFrame,
    ) -> dict[pd.Timestamp, list[FormingPeakEvent]]:
        """Build prefix-causal snapshots without changing candidate detection."""
        events: dict[pd.Timestamp, list[FormingPeakEvent]] = defaultdict(list)
        active_id: str | None = None
        active_version = 0
        forming_number = 0
        for index in range(1, len(data)):
            values = (
                data.at[index - 1, "close"], data.at[index, "close"],
                data.at[index - 1, "rsi14"], data.at[index, "rsi14"],
            )
            rising = not any(pd.isna(value) for value in values) and bool(
                data.at[index, "close"] > data.at[index - 1, "close"]
                and data.at[index, "rsi14"] > data.at[index - 1, "rsi14"]
            )
            if not rising:
                active_id = None
                active_version = 0
                continue
            if active_id is None:
                forming_number += 1
                active_id = f"FPK{forming_number:04d}"
                active_version = 1
            else:
                active_version += 1
            date = pd.Timestamp(data.at[index, "date"])
            events[date].append(FormingPeakEvent(
                forming_peak_id=active_id,
                forming_version=active_version,
                peak_index=index,
                peak_date=date,
                peak_high=float(data.at[index, "high"]),
                peak_close=float(data.at[index, "close"]),
                peak_rsi=float(data.at[index, "rsi14"]),
                previous_day_close=float(data.at[index - 1, "close"]),
            ))
        return dict(events)

    @staticmethod
    def _safe_min(series: pd.Series) -> float | None:
        values = pd.to_numeric(series, errors="coerce").dropna()
        return None if values.empty else float(values.min())

    def _relationship_metrics(
        self, data: pd.DataFrame, active: CanonicalPeak | None, peak_index: int
    ) -> dict[str, float | int | None]:
        if active is None:
            return {
                "days_from_previous_peak": None, "interim_min_close": None,
                "interim_min_rsi": None, "price_retrace_pct": None, "rsi_retrace": None,
            }
        between = data.iloc[active.peak_index + 1 : peak_index]
        interim_close = self._safe_min(between["close"])
        interim_rsi = self._safe_min(between["rsi14"])
        price_retrace = 0.0 if interim_close is None else max(
            0.0, (active.peak_close - interim_close) / active.peak_close
        )
        rsi_retrace = 0.0 if interim_rsi is None else max(0.0, active.peak_rsi - interim_rsi)
        return {
            "days_from_previous_peak": peak_index - active.peak_index,
            "interim_min_close": interim_close,
            "interim_min_rsi": interim_rsi,
            "price_retrace_pct": price_retrace,
            "rsi_retrace": rsi_retrace,
        }

    def _prefer_candidate_values(self, close: float, rsi: float, active: CanonicalPeak) -> bool:
        clear_price_improvement = close > active.peak_close * (1 + self.price_tolerance_pct)
        close_within_tolerance = abs(close - active.peak_close) <= active.peak_close * self.price_tolerance_pct
        return bool(clear_price_improvement or (close_within_tolerance and rsi > active.peak_rsi))

    @staticmethod
    def _format_dates(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        for column in ("peak_date", "confirm_date", "earliest_action_date"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column]).dt.strftime("%Y-%m-%d")
        return frame
