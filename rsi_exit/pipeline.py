from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from rsi_exit.config import RsiExitConfig
from rsi_exit.divergence import DivergenceTracker
from rsi_exit.indicators import calculate_rsi_cn, rsi_zone
from rsi_exit.models import BaseState, SignalType, StateTransition
from rsi_exit.peak_detector import PeakDetector
from rsi_exit.position_rules import divergence_position_rule, merge_position_caps
from rsi_exit.state_machine import RsiExitStateMachine, STATE_ACTIONS


@dataclass
class AnalysisResult:
    symbol: str
    name: str | None
    daily_features: pd.DataFrame
    peaks: pd.DataFrame
    signals: pd.DataFrame
    state_log: pd.DataFrame
    warnings: list[str]
    metadata: dict[str, Any]


SIGNAL_COLUMNS = [
    "signal_date",
    "earliest_action_date",
    "peak_id",
    "previous_peak_id",
    "previous_peak_date",
    "previous_peak_close",
    "previous_peak_rsi",
    "signal_type",
    "price_relation",
    "rsi_relation",
    "divergence_count",
    "confirm_rsi",
    "confirm_rsi_zone",
    "divergence_position_cap",
    "base_state",
    "base_position_cap",
    "final_position_cap",
    "final_action",
    "momentum_anchor_date",
    "momentum_anchor_close",
    "momentum_anchor_rsi",
    "price_vs_anchor_pct",
    "rsi_vs_anchor",
    "reason",
]


def analyze_bars(
    bars: pd.DataFrame,
    *,
    symbol: str,
    config: RsiExitConfig,
    name: str | None = None,
) -> AnalysisResult:
    data = _normalize_bars(bars)
    values = config.values
    rsi_cfg = values["rsi"]
    peak_cfg = values["peak_detection"]
    div_cfg = values["divergence"]
    levels = values["levels"]

    period = int(rsi_cfg["period"])
    seed_mode = str(rsi_cfg["seed_mode"])
    data["ma20"] = data["close"].rolling(20, min_periods=20).mean()
    data["rsi14"] = calculate_rsi_cn(data["close"], period, seed_mode)
    data["rsi_zone"] = data["rsi14"].map(
        lambda value: rsi_zone(
            value,
            strong=float(levels["strong"]),
            life=float(levels["life"]),
            neutral=float(levels["neutral"]),
            weak=float(levels["weak"]),
        )
    )

    detector = PeakDetector(
        min_peak_gap=int(peak_cfg["min_peak_gap"]),
        min_rsi_retrace=float(peak_cfg["min_rsi_retrace"]),
        min_price_retrace_pct=float(peak_cfg["min_price_retrace_pct"]),
        price_tolerance_pct=float(div_cfg["price_tolerance_pct"]),
    )
    peaks, peak_events = detector.detect(data)
    tracker = DivergenceTracker(
        price_tolerance_pct=float(div_cfg["price_tolerance_pct"]),
        rsi_tolerance=float(div_cfg["rsi_tolerance"]),
        max_peak_gap=int(peak_cfg["max_peak_gap"]),
        cycle_reset_rsi=float(div_cfg["reset_rsi_level"]),
    )
    state_machine = RsiExitStateMachine()
    signals: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    anchor_by_candidate: dict[str, str] = {}
    persistent_signal_cap = 1.0
    current_divergence_count = 0

    for _, row in data.iterrows():
        date = pd.Timestamp(row["date"])
        external_risk = _binary_input(row.get("external_risk", 0))
        hard_exit = _binary_input(row.get("hard_exit", 0))
        transition = state_machine.step(
            rsi=float(row["rsi14"]),
            close=float(row["close"]),
            ma20=float(row["ma20"]),
            external_risk=external_risk,
            hard_exit=hard_exit,
        )
        entered_s3 = (
            transition.previous_state != BaseState.S3_EXIT
            and transition.current_state == BaseState.S3_EXIT
        )
        if entered_s3:
            tracker.reset_cycle()
            persistent_signal_cap = 1.0
            current_divergence_count = 0

        day_signal_type: str | None = None
        day_signal_action: str | None = None
        day_signal_cap: float | None = None
        day_reason: str | None = None

        for event in peak_events.get(date, []):
            result = tracker.process(event.peak)
            if tracker.anchor is not None:
                anchor_by_candidate[event.peak.peak_id] = tracker.anchor.peak_id
            if result is None:
                continue

            current_divergence_count = result.divergence_count
            signal_action, signal_cap = divergence_position_rule(
                result.signal_type, result.divergence_count, event.peak.confirm_rsi
            )
            if result.reset_reason is not None or result.signal_type == SignalType.TREND_STRENGTHENING:
                persistent_signal_cap = 1.0
            elif result.signal_type in {
                SignalType.BEARISH_DIVERGENCE,
                SignalType.LOWER_HIGH_WEAK_REBOUND,
            }:
                persistent_signal_cap = min(persistent_signal_cap, signal_cap)

            if (
                result.signal_type == SignalType.BEARISH_DIVERGENCE
                and result.divergence_count >= 3
                and result.reset_reason is None
            ):
                base_previous = transition.previous_state
                forced = state_machine.force_exit("THIRD_DIVERGENCE")
                transition = StateTransition(
                    previous_state=base_previous,
                    current_state=forced.current_state,
                    trigger=f"{transition.trigger}|THIRD_DIVERGENCE",
                    action=forced.action,
                    position_cap=forced.position_cap,
                )

            final_action, final_cap = merge_position_caps(
                base_action=transition.action,
                base_cap=transition.position_cap,
                signal_action=signal_action,
                signal_cap=persistent_signal_cap,
            )
            reason_parts = [
                f"{result.price_relation}; {result.rsi_relation}",
                f"peak confirmed on {event.peak.confirm_date:%Y-%m-%d}",
                f"earliest action {event.peak.earliest_action_date:%Y-%m-%d}"
                if not pd.isna(event.peak.earliest_action_date)
                else "earliest action is beyond available data",
            ]
            if result.reset_reason:
                reason_parts.append(f"cycle reset: {result.reset_reason}")
            signals.append(
                {
                    "signal_date": date.strftime("%Y-%m-%d"),
                    "earliest_action_date": _date_text(event.peak.earliest_action_date),
                    "peak_id": event.peak.peak_id,
                    "previous_peak_id": result.previous_peak_id,
                    "previous_peak_date": _date_text(result.previous_peak_date),
                    "previous_peak_close": result.previous_peak_close,
                    "previous_peak_rsi": result.previous_peak_rsi,
                    "signal_type": result.signal_type.value,
                    "price_relation": result.price_relation,
                    "rsi_relation": result.rsi_relation,
                    "divergence_count": result.divergence_count,
                    "confirm_rsi": event.peak.confirm_rsi,
                    "confirm_rsi_zone": rsi_zone(event.peak.confirm_rsi),
                    "divergence_position_cap": signal_cap,
                    "base_state": transition.current_state.value,
                    "base_position_cap": transition.position_cap,
                    "final_position_cap": final_cap,
                    "final_action": final_action,
                    "momentum_anchor_date": result.momentum_anchor_date.strftime("%Y-%m-%d"),
                    "momentum_anchor_close": result.momentum_anchor_close,
                    "momentum_anchor_rsi": result.momentum_anchor_rsi,
                    "price_vs_anchor_pct": result.price_vs_anchor_pct,
                    "rsi_vs_anchor": result.rsi_vs_anchor,
                    "reason": "; ".join(reason_parts),
                }
            )
            day_signal_type = result.signal_type.value
            day_signal_action = signal_action
            day_signal_cap = persistent_signal_cap
            day_reason = "; ".join(reason_parts)

        final_action, final_position_cap = merge_position_caps(
            base_action=transition.action,
            base_cap=transition.position_cap,
            signal_action=day_signal_action or "MAINTAIN_RISK_CAP",
            signal_cap=persistent_signal_cap,
        )
        daily_rows.append(
            {
                **{column: row[column] for column in (
                    "date", "open", "high", "low", "close", "volume", "amount",
                    "ma20", "rsi14", "rsi_zone"
                )},
                "base_state": transition.current_state.value,
                "base_action": transition.action,
                "base_position_cap": transition.position_cap,
                "final_action": final_action,
                "final_position_cap": final_position_cap,
            }
        )
        state_rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "previous_state": transition.previous_state.value,
                "current_state": transition.current_state.value,
                "trigger": transition.trigger,
                "rsi14": row["rsi14"],
                "close": row["close"],
                "ma20": row["ma20"],
                "divergence_count": current_divergence_count,
                "signal_type": day_signal_type,
                "position_cap": final_position_cap,
                "signal_reason": day_reason,
            }
        )

        if transition.current_state == BaseState.S3_EXIT and "THIRD_DIVERGENCE" in transition.trigger:
            tracker.reset_cycle()
            persistent_signal_cap = 1.0
            current_divergence_count = 0

    daily = pd.DataFrame(daily_rows)
    daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    signal_frame = pd.DataFrame(signals, columns=SIGNAL_COLUMNS)
    if not peaks.empty:
        peaks["momentum_anchor_peak_id"] = peaks["peak_id"].map(anchor_by_candidate)
    warnings = _build_warnings(data, peaks)
    metadata = {
        "symbol": symbol,
        "name": name,
        "start_date": data["date"].iloc[0].strftime("%Y-%m-%d"),
        "end_date": data["date"].iloc[-1].strftime("%Y-%m-%d"),
        "row_count": len(data),
        "rsi_algorithm": "CN_SMA(MAX(CLOSE-REF(CLOSE,1),0),14,1) / CN_SMA(ABS(CLOSE-REF(CLOSE,1)),14,1) * 100",
        "seed_mode": seed_mode,
        "adjust": bars.attrs.get("adjust", "unknown"),
        "source": bars.attrs.get("source", "provided_dataframe"),
    }
    return AnalysisResult(
        symbol=symbol,
        name=name,
        daily_features=daily,
        peaks=peaks,
        signals=signal_frame,
        state_log=pd.DataFrame(state_rows),
        warnings=warnings,
        metadata=metadata,
    )


def run_batch(
    items: Iterable[tuple[str, str | None, pd.DataFrame]],
    *,
    config: RsiExitConfig,
) -> tuple[list[AnalysisResult], pd.DataFrame]:
    results: list[AnalysisResult] = []
    for symbol, name, bars in items:
        result = analyze_bars(bars, symbol=symbol, name=name, config=config)
        results.append(result)
    return results, build_validation_summary(results)


def build_validation_summary(results: Iterable[AnalysisResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        symbol = result.symbol
        name = result.name
        signals = result.signals
        current = result.daily_features.iloc[-1]
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "start_date": result.metadata["start_date"],
                "end_date": result.metadata["end_date"],
                "peak_count": int(result.peaks["is_independent_peak"].sum()) if not result.peaks.empty else 0,
                "strengthening_count": int((signals["signal_type"] == SignalType.TREND_STRENGTHENING.value).sum()),
                "divergence_count_1": int(((signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value) & (signals["divergence_count"] == 1)).sum()),
                "divergence_count_2": int(((signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value) & (signals["divergence_count"] == 2)).sum()),
                "divergence_count_3": int(((signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value) & (signals["divergence_count"] >= 3)).sum()),
                "weak_rebound_count": int((signals["signal_type"] == SignalType.LOWER_HIGH_WEAK_REBOUND.value).sum()),
                "current_rsi": current["rsi14"],
                "current_state": current["base_state"],
                "current_position_cap": current["final_position_cap"],
                "warnings": " | ".join(result.warnings),
            }
        )
    return pd.DataFrame(rows)


def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "open", "high", "low", "close", "volume", "amount"]
    missing = set(required) - set(bars.columns)
    if missing:
        raise ValueError(f"行情缺少字段: {', '.join(sorted(missing))}")
    optional = [column for column in ("external_risk", "hard_exit") if column in bars]
    data = bars[required + optional].copy()
    data["date"] = pd.to_datetime(data["date"].astype(str), errors="coerce")
    for column in required[1:]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if data.empty:
        raise ValueError("行情为空")
    if data[required].isna().any().any():
        bad = data.columns[data.isna().any()].tolist()
        raise ValueError(f"行情存在缺失值: {', '.join(bad)}")
    data = data.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return data


def _build_warnings(data: pd.DataFrame, peaks: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    if len(data) < 20:
        warnings.append("行情不足20个交易日，MA20无法形成完整有效区间。")
    if data["rsi14"].notna().sum() < 14:
        warnings.append("RSI有效数据少于14行，人工核验可靠性有限。")
    if not peaks.empty and peaks["earliest_action_date"].isna().any():
        warnings.append("末端高点已确认，但其最早执行日超出当前数据区间。")
    if peaks.empty:
        warnings.append("当前区间未识别到满足双下降确认的有效高点。")
    warnings.append("高点条件使用收盘价而非盘中最高价；与按最高价目测的峰值可能不同。")
    return warnings


def _binary_input(value: Any) -> int:
    if pd.isna(value):
        return 0
    number = int(value)
    if number not in {0, 1}:
        raise ValueError("external_risk/hard_exit 只能是 0 或 1")
    return number


def _date_text(value: Any) -> str | None:
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")
