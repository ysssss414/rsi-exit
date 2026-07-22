from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from rsi_exit.config import RsiExitConfig
from rsi_exit.divergence import DivergenceTracker
from rsi_exit.indicators import calculate_rsi_audit, rsi_zone
from rsi_exit.models import BaseState, CanonicalPeak, SignalType
from rsi_exit.peak_detector import PeakDetector
from rsi_exit.position_rules import divergence_position_rule, merge_position_caps
from rsi_exit.state_machine import RsiExitStateMachine


@dataclass
class AnalysisResult:
    symbol: str
    name: str | None
    daily_features: pd.DataFrame
    peaks: pd.DataFrame
    canonical_peaks: pd.DataFrame
    signals: pd.DataFrame
    state_log: pd.DataFrame
    cycle_log: pd.DataFrame
    rsi_audit: pd.DataFrame
    warnings: list[str]
    metadata: dict[str, Any]


SIGNAL_COLUMNS = [
    "decision_date", "earliest_action_date", "effective_date", "signal_date",
    "candidate_peak_id", "canonical_peak_id", "canonical_version",
    "current_candidate_peak_id", "current_canonical_peak_id", "current_canonical_version",
    "representative_candidate_id", "previous_candidate_peak_id",
    "previous_canonical_peak_id", "previous_canonical_version", "cycle_id",
    "current_peak_date", "current_peak_close", "current_peak_rsi",
    "signal_type", "price_relation", "rsi_relation", "divergence_count",
    "confirm_rsi", "confirm_rsi_zone", "divergence_position_cap",
    "decision_base_state", "decision_base_position_cap",
    "decision_signal_position_cap", "decision_final_position_cap", "decision_action",
    "momentum_anchor_candidate_id", "momentum_anchor_canonical_id",
    "momentum_anchor_canonical_version", "momentum_anchor_date",
    "momentum_anchor_close", "momentum_anchor_rsi", "price_vs_anchor_pct",
    "rsi_vs_anchor", "reset_reason", "reason",
    # v0.1 compatibility aliases, deliberately tied to candidate identities.
    "peak_id", "previous_peak_id", "previous_peak_date", "previous_peak_close",
    "previous_peak_rsi", "base_state", "base_position_cap", "final_position_cap",
    "final_action",
]


def analyze_bars(
    bars: pd.DataFrame,
    *,
    symbol: str,
    config: RsiExitConfig,
    name: str | None = None,
    display_start_date: str | pd.Timestamp | None = None,
    display_end_date: str | pd.Timestamp | None = None,
) -> AnalysisResult:
    data = _normalize_bars(bars)
    values = config.values
    rsi_cfg, levels = values["rsi"], values["levels"]
    peak_cfg, div_cfg = values["peak_detection"], values["divergence"]
    data_cfg, caps = values["data"], values["position_caps"]

    requested_warmup = int(data_cfg["warmup_trading_days"])
    display_start = pd.Timestamp(display_start_date) if display_start_date is not None else data["date"].iloc[0]
    display_end = pd.Timestamp(display_end_date) if display_end_date is not None else data["date"].iloc[-1]
    if display_start > display_end:
        raise ValueError("展示起始日不得晚于展示结束日")
    display_mask = data["date"].between(display_start, display_end)
    if not display_mask.any():
        raise ValueError("行情中没有展示区间内的交易日")
    warmup_count = int((data["date"] < display_start).sum())
    warmup_satisfied = warmup_count >= requested_warmup

    period, seed_mode = int(rsi_cfg["period"]), str(rsi_cfg["seed_mode"])
    ma_period = int(data_cfg["ma_period"])
    audit_values = calculate_rsi_audit(data["close"], period=period, seed_mode=seed_mode)
    data[f"ma{ma_period}"] = data["close"].rolling(ma_period, min_periods=ma_period).mean()
    data["ma20"] = data[f"ma{ma_period}"]
    data[f"rsi{period}"] = audit_values["rsi"]
    data["rsi14"] = audit_values["rsi"]
    data["rsi_zone"] = data["rsi14"].map(lambda value: rsi_zone(value, **{k: float(levels[k]) for k in ("strong", "life", "neutral", "weak")}))

    detector = PeakDetector(
        lookback=int(peak_cfg["lookback"]),
        require_recent_window_max=bool(peak_cfg["require_recent_window_max"]),
        min_peak_gap=int(peak_cfg["min_peak_gap"]),
        min_rsi_retrace=float(peak_cfg["min_rsi_retrace"]),
        min_price_retrace_pct=float(peak_cfg["min_price_retrace_pct"]),
        price_tolerance_pct=float(div_cfg["price_tolerance_pct"]),
    )
    peaks, peak_events = detector.detect(data, trading_calendar=data["date"])
    canonical_peaks = detector.canonical_peaks_frame()
    tracker = DivergenceTracker(
        price_tolerance_pct=float(div_cfg["price_tolerance_pct"]),
        rsi_tolerance=float(div_cfg["rsi_tolerance"]),
        max_peak_gap=int(peak_cfg["max_peak_gap"]),
        cycle_reset_rsi=float(div_cfg["reset_rsi_level"]),
    )
    machine = RsiExitStateMachine(
        levels={key: float(value) for key, value in levels.items()},
        position_caps={key: float(value) for key, value in caps.items()},
    )

    dates = data["date"].tolist()
    pending: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    effective_base_state = BaseState.UNINITIALIZED
    effective_base_cap = float(caps["uninitialized"])
    effective_base_action = "WAIT_FOR_WARMUP"
    effective_signal_cap = 1.0
    effective_signal_action = "NO_DIVERGENCE_REDUCTION"
    decision_signal_cap = 1.0
    decision_signal_action = "NO_DIVERGENCE_REDUCTION"
    current_divergence_count = 0
    signals: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    cycle_seq = 1
    cycle_start = data["date"].iloc[0]
    candidate_cycle: dict[str, str] = {}
    anchor_by_candidate: dict[str, str] = {}

    def add_pending(date: pd.Timestamp | pd.NaT, entry: dict[str, Any]) -> None:
        if pd.isna(date):
            return
        pending.setdefault(pd.Timestamp(date), []).append(entry)

    for row_index, row in data.iterrows():
        date = pd.Timestamp(row["date"])
        due_entries = pending.pop(date, [])
        for domain in ("base", "signal"):
            entries = [item for item in due_entries if item["domain"] == domain]
            if entries:
                chosen = min(entries, key=lambda item: float(item["cap"]))
                if domain == "base":
                    effective_base_cap = float(chosen["cap"])
                    effective_base_action = str(chosen["action"])
                    effective_base_state = chosen["state"]
                else:
                    effective_signal_cap = float(chosen["cap"])
                    effective_signal_action = str(chosen["action"])

        transition = machine.step(
            rsi=float(row["rsi14"]), close=float(row["close"]), ma20=float(row["ma20"]),
            external_risk=_binary_input(row.get("external_risk", 0)),
            hard_exit=_binary_input(row.get("hard_exit", 0)), decision_date=date,
        )
        day_signal_type: str | None = None
        day_reason: str | None = None
        reset_reasons: list[str] = []
        reset_baseline: CanonicalPeak | None = None
        entered_s3 = transition.previous_state != BaseState.S3_EXIT and transition.current_state == BaseState.S3_EXIT

        for event in peak_events.get(date, []):
            cycle_id = tracker.cycle_id
            event.peak.cycle_id = cycle_id
            if event.canonical is not None:
                event.canonical.cycle_id = cycle_id
            candidate_id = event.peak.candidate_peak_id or event.peak.peak_id
            candidate_cycle[candidate_id] = cycle_id
            result = tracker.process(event)
            if tracker.anchor is not None:
                anchor_by_candidate[candidate_id] = tracker.anchor.representative_candidate_id
            if result is None:
                continue

            current_divergence_count = result.divergence_count
            signal_action, raw_signal_cap = divergence_position_rule(
                result.signal_type, result.divergence_count, event.peak.confirm_rsi,
                life_level=float(levels["life"]), position_caps=caps,
            )
            before_signal_cap = decision_signal_cap
            if result.reset_reason:
                decision_signal_cap = 1.0
                decision_signal_action = "RESET_DIVERGENCE_CAP"
                reset_reasons.append(result.reset_reason)
                reset_baseline = deepcopy(event.canonical)
            elif result.signal_type in {SignalType.BEARISH_DIVERGENCE, SignalType.LOWER_HIGH_WEAK_REBOUND}:
                if raw_signal_cap <= decision_signal_cap:
                    decision_signal_action = signal_action
                decision_signal_cap = min(decision_signal_cap, raw_signal_cap)

            if result.signal_type == SignalType.BEARISH_DIVERGENCE and result.divergence_count >= 3 and result.reset_reason is None:
                transition = machine.force_exit("THIRD_DIVERGENCE")
                entered_s3 = True
                if "THIRD_DIVERGENCE" not in reset_reasons:
                    reset_reasons.append("THIRD_DIVERGENCE")
                reset_baseline = None

            action_date = event.peak.earliest_action_date
            if decision_signal_cap != before_signal_cap or result.reset_reason:
                add_pending(action_date, {
                    "domain": "signal", "cap": decision_signal_cap,
                    "action": decision_signal_action,
                })
            decision_action, decision_final_cap = merge_position_caps(
                base_action=transition.action, base_cap=transition.position_cap,
                signal_action=decision_signal_action, signal_cap=decision_signal_cap,
            )
            reason_parts = [
                f"{result.price_relation}; {result.rsi_relation}",
                f"candidate={candidate_id}; canonical={result.canonical_peak_id}; version={result.canonical_version}",
                f"decision={date:%Y-%m-%d}; effective={_date_text(action_date) or 'beyond-data'}",
            ]
            if result.reset_reason:
                reason_parts.append(f"cycle reset after audit: {result.reset_reason}")
            reason = "; ".join(reason_parts)
            signals.append({
                "decision_date": _date_text(date), "earliest_action_date": _date_text(action_date),
                "effective_date": _date_text(action_date), "signal_date": _date_text(date),
                "candidate_peak_id": candidate_id, "canonical_peak_id": result.canonical_peak_id,
                "canonical_version": result.canonical_version,
                "current_candidate_peak_id": candidate_id,
                "current_canonical_peak_id": result.canonical_peak_id,
                "current_canonical_version": result.canonical_version,
                "representative_candidate_id": event.canonical.representative_candidate_id if event.canonical else candidate_id,
                "previous_candidate_peak_id": result.previous_candidate_peak_id,
                "previous_canonical_peak_id": result.previous_canonical_peak_id,
                "previous_canonical_version": result.previous_canonical_version,
                "cycle_id": result.cycle_id, "signal_type": result.signal_type.value,
                "current_peak_date": _date_text(event.peak.peak_date),
                "current_peak_close": event.peak.peak_close,
                "current_peak_rsi": event.peak.peak_rsi,
                "price_relation": result.price_relation, "rsi_relation": result.rsi_relation,
                "divergence_count": result.divergence_count, "confirm_rsi": event.peak.confirm_rsi,
                "confirm_rsi_zone": rsi_zone(event.peak.confirm_rsi, **{k: float(levels[k]) for k in ("strong", "life", "neutral", "weak")}),
                "divergence_position_cap": raw_signal_cap,
                "decision_base_state": transition.current_state.value,
                "decision_base_position_cap": transition.position_cap,
                "decision_signal_position_cap": decision_signal_cap,
                "decision_final_position_cap": decision_final_cap,
                "decision_action": decision_action,
                "momentum_anchor_candidate_id": result.momentum_anchor_candidate_id,
                "momentum_anchor_canonical_id": result.momentum_anchor_canonical_id,
                "momentum_anchor_canonical_version": result.momentum_anchor_canonical_version,
                "momentum_anchor_date": _date_text(result.momentum_anchor_date),
                "momentum_anchor_close": result.momentum_anchor_close,
                "momentum_anchor_rsi": result.momentum_anchor_rsi,
                "price_vs_anchor_pct": result.price_vs_anchor_pct, "rsi_vs_anchor": result.rsi_vs_anchor,
                "reset_reason": result.reset_reason, "reason": reason,
                "peak_id": candidate_id, "previous_peak_id": result.previous_candidate_peak_id,
                "previous_peak_date": _date_text(result.previous_peak_date),
                "previous_peak_close": result.previous_peak_close, "previous_peak_rsi": result.previous_peak_rsi,
                "base_state": transition.current_state.value, "base_position_cap": transition.position_cap,
                "final_position_cap": decision_final_cap, "final_action": decision_action,
            })
            day_signal_type, day_reason = result.signal_type.value, reason

        if entered_s3 and "STATE_ENTERED_S3" not in reset_reasons:
            reset_reasons.append("STATE_ENTERED_S3")
            reset_baseline = None

        next_date = pd.Timestamp(dates[row_index + 1]) if row_index + 1 < len(dates) else pd.NaT
        add_pending(next_date, {
            "domain": "base", "cap": transition.position_cap,
            "action": transition.action, "state": transition.current_state,
        })

        effective_action, effective_final_cap = merge_position_caps(
            base_action=effective_base_action, base_cap=effective_base_cap,
            signal_action=effective_signal_action, signal_cap=effective_signal_cap,
        )
        decision_action, decision_final_cap = merge_position_caps(
            base_action=transition.action, base_cap=transition.position_cap,
            signal_action=decision_signal_action, signal_cap=decision_signal_cap,
        )
        common = {column: row[column] for column in (
            "date", "open", "high", "low", "close", "volume", "amount", "ma20", "rsi14", "rsi_zone"
        )}
        daily_rows.append({
            **common,
            "decision_base_state": transition.current_state.value,
            "decision_base_action": transition.action,
            "decision_base_position_cap": transition.position_cap,
            "decision_signal_position_cap": decision_signal_cap,
            "decision_final_action": decision_action,
            "decision_final_position_cap": decision_final_cap,
            "decision_state_event": transition.state_event,
            "state_event": transition.state_event,
            "allow_reentry": transition.allow_reentry,
            "reentry_qualification_date": _date_text(transition.reentry_qualification_date),
            "effective_base_state": effective_base_state.value,
            "effective_base_action": effective_base_action,
            "effective_base_position_cap": effective_base_cap,
            "effective_signal_position_cap": effective_signal_cap,
            "effective_final_action": effective_action,
            "effective_action": effective_action,
            "effective_final_position_cap": effective_final_cap,
            "base_state": transition.current_state.value,
            "base_action": transition.action,
            "base_position_cap": transition.position_cap,
            "final_action": effective_action,
            "final_position_cap": effective_final_cap,
        })
        state_rows.append({
            "decision_date": _date_text(date), "effective_date": _date_text(next_date), "date": _date_text(date),
            "previous_state": transition.previous_state.value, "current_state": transition.current_state.value,
            "trigger": transition.trigger, "state_event": transition.state_event,
            "allow_reentry": transition.allow_reentry,
            "reentry_qualification_date": _date_text(transition.reentry_qualification_date),
            "rsi14": row["rsi14"], "close": row["close"], "ma20": row["ma20"],
            "divergence_count": current_divergence_count, "signal_type": day_signal_type,
            "decision_position_cap": decision_final_cap, "effective_position_cap": effective_final_cap,
            "position_cap": effective_final_cap, "signal_reason": day_reason, "cycle_id": tracker.cycle_id,
            "cycle_reset_event": bool(reset_reasons),
            "cycle_reset_reason": "|".join(dict.fromkeys(reset_reasons)) if reset_reasons else None,
        })

        if reset_reasons:
            reason = "|".join(dict.fromkeys(reset_reasons))
            cycle_rows.append({
                "cycle_id": tracker.cycle_id, "cycle_start_date": _date_text(cycle_start),
                "cycle_end_date": _date_text(date), "reset_reason": reason,
                "reset_decision_date": _date_text(date), "reset_effective_date": _date_text(next_date),
                "cycle_reset_event": True,
            })
            cycle_seq += 1
            new_cycle_id = f"CYCLE{cycle_seq:04d}"
            cycle_start = next_date if not pd.isna(next_date) else date
            if entered_s3:
                decision_signal_cap, decision_signal_action = 1.0, "RESET_DIVERGENCE_CAP"
                add_pending(next_date, {"domain": "signal", "cap": 1.0, "action": decision_signal_action})
                current_divergence_count = 0
            tracker.reset_cycle(new_cycle_id, baseline=reset_baseline)

    cycle_rows.append({
        "cycle_id": tracker.cycle_id, "cycle_start_date": _date_text(cycle_start),
        "cycle_end_date": _date_text(data["date"].iloc[-1]), "reset_reason": None,
        "reset_decision_date": None, "reset_effective_date": None,
        "cycle_reset_event": False,
    })

    daily = pd.DataFrame(daily_rows)
    daily["date"] = pd.to_datetime(daily["date"])
    state_log = pd.DataFrame(state_rows)
    signal_frame = pd.DataFrame(signals, columns=SIGNAL_COLUMNS)
    for frame, column in ((daily, "date"), (state_log, "date")):
        date_values = pd.to_datetime(frame[column])
        frame.drop(frame.index[~date_values.between(display_start, display_end)], inplace=True)
        frame.reset_index(drop=True, inplace=True)
    if not signal_frame.empty:
        mask = pd.to_datetime(signal_frame["decision_date"]).between(display_start, display_end)
        signal_frame = signal_frame.loc[mask].reset_index(drop=True)

    if not peaks.empty:
        peaks["cycle_id"] = peaks["candidate_peak_id"].map(candidate_cycle)
        confirm_dates = pd.to_datetime(peaks["confirm_date"])
        peaks["is_warmup"] = confirm_dates < display_start
        peaks["is_display_range"] = confirm_dates.between(display_start, display_end)
        peaks["momentum_anchor_peak_id"] = peaks["candidate_peak_id"].map(anchor_by_candidate)
    if not canonical_peaks.empty:
        canonical_peaks["cycle_id"] = canonical_peaks["representative_candidate_id"].map(candidate_cycle)

    input_checksum = _input_checksum(data)
    rsi_audit = pd.DataFrame({
        "date": data["date"].dt.strftime("%Y-%m-%d"),
        "raw_close": data["raw_close"] if "raw_close" in data else np.nan,
        "adjusted_close": audit_values["adjusted_close"],
        "adjustment_factor": data["adjustment_factor"] if "adjustment_factor" in data else np.nan,
        "adjustment_ratio": data["adjustment_ratio"] if "adjustment_ratio" in data else np.nan,
        "delta": audit_values["delta"], "gain": audit_values["gain"],
        "absolute_delta": audit_values["absolute_delta"],
        "abs_delta": audit_values["absolute_delta"],
        "smoothed_gain": audit_values["smoothed_gain"],
        "smoothed_absolute": audit_values["smoothed_absolute"], "rsi": audit_values["rsi"],
        "smoothed_abs": audit_values["smoothed_absolute"], "rsi14": audit_values["rsi"],
        "is_warmup": data["date"] < display_start,
        "is_display_range": data["date"].between(display_start, display_end),
        "input_checksum_sha256": input_checksum,
        "config_version": values.get("version", "unknown"),
    })

    daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    warnings = _build_warnings(data, peaks, warmup_count, requested_warmup)
    metadata = {
        "symbol": symbol, "name": name,
        "calculation_start_date": _date_text(data["date"].iloc[0]),
        "calculation_end_date": _date_text(data["date"].iloc[-1]),
        "display_start_date": _date_text(display_start), "display_end_date": _date_text(display_end),
        "start_date": _date_text(display_start), "end_date": _date_text(display_end),
        "calculation_row_count": len(data), "display_row_count": len(daily),
        "warmup_trading_days_requested": requested_warmup,
        "warmup_trading_days_actual": warmup_count, "warmup_satisfied": warmup_satisfied,
        "warmup_rows": warmup_count,
        "source_row_count": len(data),
        "indicator_ready_on_display_start": bool(
            pd.notna(data.loc[display_mask, "rsi14"].iloc[0])
            and pd.notna(data.loc[display_mask, "ma20"].iloc[0])
        ),
        "rsi_period": period,
        "rsi_algorithm": f"CN_SMA(MAX(CLOSE-REF(CLOSE,1),0),{period},1) / CN_SMA(ABS(CLOSE-REF(CLOSE,1)),{period},1) * 100",
        "seed_mode": seed_mode, "ma_period": ma_period,
        "adjust": bars.attrs.get("adjust", "unknown"),
        "source": bars.attrs.get("source", "provided_dataframe"),
        "input_checksum_sha256": input_checksum,
        "rsi_difference_explanation": "v0.1从展示区间起点播种；v0.2先加载至少120个真实交易日并在完整前复权序列上递推，因此同日RSI可与旧版38.8449不同。公式未改变，也未写入目标数值。",
    }
    return AnalysisResult(
        symbol, name, daily, peaks, canonical_peaks, signal_frame, state_log,
        pd.DataFrame(cycle_rows), rsi_audit, warnings, metadata,
    )


def run_batch(
    items: Iterable[tuple[str, str | None, pd.DataFrame]], *, config: RsiExitConfig,
) -> tuple[list[AnalysisResult], pd.DataFrame]:
    results = [analyze_bars(bars, symbol=symbol, name=name, config=config) for symbol, name, bars in items]
    return results, build_validation_summary(results)


def build_validation_summary(results: Iterable[AnalysisResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        signals, current = result.signals, result.daily_features.iloc[-1]
        rows.append({
            "symbol": result.symbol, "name": result.name,
            "start_date": result.metadata["display_start_date"], "end_date": result.metadata["display_end_date"],
            "calculation_start_date": result.metadata["calculation_start_date"],
            "warmup_trading_days_actual": result.metadata["warmup_trading_days_actual"],
            "warmup_satisfied": result.metadata["warmup_satisfied"],
            "peak_count": int((result.peaks["is_display_range"] & result.peaks["is_independent_peak"]).sum()) if not result.peaks.empty else 0,
            "strengthening_count": _signal_count(signals, SignalType.TREND_STRENGTHENING),
            "divergence_count_1": _signal_count(signals, SignalType.BEARISH_DIVERGENCE, 1),
            "divergence_count_2": _signal_count(signals, SignalType.BEARISH_DIVERGENCE, 2),
            "divergence_count_3": int(((signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value) & (signals["divergence_count"] >= 3)).sum()) if not signals.empty else 0,
            "weak_rebound_count": _signal_count(signals, SignalType.LOWER_HIGH_WEAK_REBOUND),
            "current_rsi": current["rsi14"], "current_state": current["decision_base_state"],
            "current_position_cap": current["effective_final_position_cap"],
            "warnings": " | ".join(result.warnings),
        })
    return pd.DataFrame(rows)


def _signal_count(signals: pd.DataFrame, kind: SignalType, count: int | None = None) -> int:
    if signals.empty:
        return 0
    mask = signals["signal_type"] == kind.value
    if count is not None:
        mask &= signals["divergence_count"] == count
    return int(mask.sum())


def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "open", "high", "low", "close", "volume", "amount"]
    missing = set(required) - set(bars.columns)
    if missing:
        raise ValueError(f"行情缺少字段: {', '.join(sorted(missing))}")
    optional_names = (
        "external_risk", "hard_exit", "raw_open", "raw_high", "raw_low", "raw_close",
        "adjustment_factor", "adjustment_ratio",
    )
    optional = [column for column in optional_names if column in bars]
    data = bars[required + optional].copy()
    data["date"] = pd.to_datetime(data["date"].astype(str), errors="coerce")
    for column in required[1:] + [item for item in optional if item not in {"external_risk", "hard_exit"}]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if data.empty or data[required].isna().any().any():
        raise ValueError("行情为空或必需字段存在缺失值")
    return data.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _build_warnings(data: pd.DataFrame, peaks: pd.DataFrame, actual: int, requested: int) -> list[str]:
    warnings: list[str] = []
    if actual < requested:
        warnings.append(f"HIGH_PRIORITY: 展示起始日前仅有 {actual} 个真实交易日，少于要求的 {requested} 日；结果不得视为完整预热验收。")
    if data["ma20"].notna().sum() == 0:
        warnings.append("MA配置周期内没有有效值，状态保持UNINITIALIZED。")
    if not peaks.empty and peaks["earliest_action_date"].isna().any():
        warnings.append("末端高点已确认，但最早执行日超出当前行情区间。")
    if peaks.empty:
        warnings.append("当前计算区间未识别到双下降确认候选。")
    warnings.append("高点使用收盘价而非盘中最高价；确认日只生成决策，最早在下一真实交易日生效。")
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


def _input_checksum(data: pd.DataFrame) -> str:
    content = data[["date", "close"]].assign(date=data["date"].dt.strftime("%Y-%m-%d")).to_csv(index=False, float_format="%.12g")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
