from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from rsi_exit.config import RsiExitConfig
from rsi_exit.models import SignalType
from rsi_exit.pipeline import AnalysisResult


def write_outputs(
    result: AnalysisResult,
    *,
    config: RsiExitConfig,
    output_root: str | Path,
    plot: bool = True,
    comparison_baseline_dir: str | Path | None = None,
) -> Path:
    output_dir = Path(output_root).resolve() / result.symbol
    output_dir.mkdir(parents=True, exist_ok=True)
    encoding = str(config.values["output"].get("csv_encoding", "utf-8-sig"))
    previous = _read_previous_output(
        Path(comparison_baseline_dir).resolve() if comparison_baseline_dir is not None else output_dir
    )

    frames = {
        "daily_features.csv": result.daily_features,
        "peaks.csv": result.peaks,
        "canonical_peaks.csv": result.canonical_peaks,
        "signals.csv": result.signals,
        "state_log.csv": result.state_log,
        "cycle_log.csv": result.cycle_log,
        "rsi_audit.csv": result.rsi_audit,
    }
    for filename, frame in frames.items():
        _csv_ready(frame).to_csv(output_dir / filename, index=False, encoding=encoding)
    (output_dir / "summary.md").write_text(build_summary(result, config), encoding="utf-8")
    (output_dir / "regression_comparison.md").write_text(
        build_regression_comparison(result, previous), encoding="utf-8"
    )
    if plot:
        from rsi_exit.plotting import create_annotated_chart

        create_annotated_chart(result, output_dir / "annotated_chart.png", config=config)
    return output_dir


def write_batch_summary(frame: pd.DataFrame, output_root: str | Path) -> Path:
    path = Path(output_root).resolve() / "peak_validation_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    _csv_ready(frame).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def build_summary(result: AnalysisResult, config: RsiExitConfig) -> str:
    signals = result.signals
    if not signals.empty and "is_display_range" in signals:
        signals = signals.loc[signals["is_display_range"].astype(bool)]
    peaks = result.peaks
    display_peaks = peaks.loc[peaks["is_display_range"]] if not peaks.empty else peaks
    divergence = signals.loc[signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value]
    weak = signals.loc[signals["signal_type"] == SignalType.LOWER_HIGH_WEAK_REBOUND.value]
    current = result.daily_features.iloc[-1]
    params = {key: config.values[key] for key in (
        "rsi", "levels", "data", "peak_detection", "divergence", "position_caps", "chart"
    )}
    signal_lines = [
        f"- {row['decision_date']} / {row['signal_type']} / {row['candidate_peak_id']}→{row['canonical_peak_id']}@v{int(row['canonical_version'])} / count={int(row['divergence_count'])} / decision cap={float(row['decision_final_position_cap']):.2f} / effective={row['effective_date'] or '区间外'}"
        for _, row in signals.iterrows()
    ]
    warning_lines = [f"- {item}" for item in result.warnings]
    return "\n".join([
        f"# {result.name or result.symbol} RSI卖点识别摘要（{config.values.get('version', 'unknown')}）", "",
        f"- 股票代码：{result.symbol}", f"- 股票名称：{result.name or '未提供'}",
        f"- 计算区间：{result.metadata['calculation_start_date']} 至 {result.metadata['calculation_end_date']}",
        f"- 展示区间：{result.metadata['display_start_date']} 至 {result.metadata['display_end_date']}",
        f"- 预热：要求 {result.metadata['warmup_trading_days_requested']} 日，实际 {result.metadata['warmup_trading_days_actual']} 日，{'通过' if result.metadata['warmup_satisfied'] else '未通过'}",
        f"- 数据源/复权：{result.metadata['source']} / {result.metadata['adjust']}",
        f"- 输入校验和：`{result.metadata['input_checksum_sha256']}`",
        f"- 计算区间已确认候选/规范峰：{len(peaks)} / {len(result.canonical_peaks)}",
        f"- 展示区间候选/独立规范峰：{len(display_peaks)} / {int(display_peaks['is_independent_peak'].sum()) if not display_peaks.empty else 0}",
        f"- 顶部背离/弱反弹：{len(divergence)} / {len(weak)}",
        f"- 当前决策状态：{current['decision_base_state']}",
        f"- 当前有效状态：{current['effective_base_state']}",
        f"- 当前RSI：{float(current['rsi']):.4f}" if pd.notna(current["rsi"]) else "- 当前RSI：不可用",
        f"- 当前有效仓位上限：{float(current['effective_final_position_cap']):.2f}",
        "", "## 信号与仓位", "", *(signal_lines or ["- 无展示区间信号。"]),
        "", "## RSI口径审计", "",
        f"- {result.metadata['rsi_algorithm']}；seed_mode={result.metadata['seed_mode']}。",
        f"- {result.metadata['rsi_difference_explanation']}",
        "- `rsi_audit.csv` 保留原始/复权收盘价、因子、单日变化、正变化、绝对变化、两条平滑序列、RSI、预热/展示标志和校验和。",
        "- `signals.csv` 保留完整计算区间信号，并以 `is_warmup` / `is_display_range` 标识所属区间；展示首日有效约束的来源同时写入 `daily_features.csv`。",
        "", "## 因果与状态口径", "",
        "- 峰值日在下一真实交易日确认；确认日只生成决策，最早再下一真实交易日生效。",
        "- 同日先处理峰值关系并保存版本快照；周期重置通过独立 RESET_SIGNAL_DOMAIN 动作使旧 cycle 信号约束失效。",
        "- `ALLOW_REENTRY` 是一次资格事件，落回 S0；它不表示自动买入，S5 不再持久化。",
        "", "## 参数", "", "```json", json.dumps(params, ensure_ascii=False, indent=2), "```",
        "", "## 警告", "", *(warning_lines or ["- 无。"]), "",
    ])


def build_regression_comparison(
    result: AnalysisResult, previous: dict[str, pd.DataFrame] | None
) -> str:
    daily = result.daily_features.set_index("date")
    old_daily = None if not previous or "daily" not in previous else previous["daily"].copy()
    if old_daily is not None and "date" in old_daily:
        old_daily["date"] = old_daily["date"].astype(str)
        old_daily = old_daily.set_index("date")
    display_signals = result.signals
    if not display_signals.empty and "is_display_range" in display_signals:
        display_signals = display_signals.loc[display_signals["is_display_range"].astype(bool)]
    signal_groups = display_signals.groupby("decision_date")["signal_type"].apply(lambda x: ",".join(x)).to_dict() if not display_signals.empty else {}
    event_dates = set(signal_groups)
    event_dates.update(
        result.daily_features.loc[
            result.daily_features["decision_state_event"].notna(), "date"
        ].astype(str)
    )
    if old_daily is not None:
        for date in daily.index.intersection(old_daily.index):
            current_row, old_row = daily.loc[date], old_daily.loc[date]
            old_state = old_row.get("decision_base_state", old_row.get("base_state"))
            old_cap = old_row.get("effective_final_position_cap", old_row.get("final_position_cap"))
            if old_state != current_row["decision_base_state"] or not _same_number(
                old_cap, current_row["effective_final_position_cap"]
            ):
                event_dates.add(str(date))
    event_dates.add(str(daily.index[-1]))
    dates = sorted(date for date in event_dates if date in daily.index)
    version = result.metadata.get("config_version", "current")
    rows = [
        f"| 日期 | 旧输出状态/上限 | {version} 决策状态 | {version} 决策/有效上限 | 当日关系/事件 |",
        "|---|---|---|---:|---|",
    ]
    for date in dates:
        row = daily.loc[date]
        event = row.get("decision_state_event")
        detail = signal_groups.get(date) or (str(event) if pd.notna(event) else "—")
        old_text = "—"
        if old_daily is not None and date in old_daily.index:
            old_row = old_daily.loc[date]
            old_text = f"{old_row.get('base_state', '—')} / {float(old_row.get('final_position_cap', float('nan'))):.2f}"
        rows.append(
            f"| {date} | {old_text} | {row['decision_base_state']} | "
            f"{float(row['decision_final_position_cap']):.2f} / {float(row['effective_final_position_cap']):.2f} | {detail} |"
        )

    old_note = "未发现可识别的旧版本地输出，以下只记录当前结果。"
    if previous and "daily" in previous:
        old = previous["daily"]
        old_note = f"写入前读取到旧输出 {len(old)} 行；按双方实际日期和可识别列对照。"
    metric_rows = _comparison_metric_rows(result, previous)
    relationship_lines = _relationship_change_lines(result)
    return "\n".join([
        f"# rsi-exit 旧输出 / {version} 回归对照", "", old_note, "",
        "当前版本在完整计算区间递推指标，再截取展示区间；预热长度、复权序列和配置差异均会影响对照结果。",
        "", "## 总体 old/new", "", *metric_rows,
        "", "## 关键关系变化", "", *relationship_lines,
        "", "## 动态差异日期", "", *rows, "",
        "## 版本口径", "",
        "- 当前输出分拆 candidate/canonical/representative/version 身份。",
        "- 当前输出显式区分 decision/earliest_action/effective。",
        "- signal domain reset 独立于普通上限动作；旧 cycle 约束不会与新 cycle reset 取最小值。", "",
    ])


def _read_previous_output(output_dir: Path) -> dict[str, pd.DataFrame] | None:
    daily_path, signals_path = output_dir / "daily_features.csv", output_dir / "signals.csv"
    if not daily_path.exists():
        return None
    try:
        result = {"daily": pd.read_csv(daily_path, encoding="utf-8-sig")}
        for key, filename in (
            ("signals", "signals.csv"), ("peaks", "peaks.csv"),
            ("canonical_peaks", "canonical_peaks.csv"), ("cycle_log", "cycle_log.csv"),
        ):
            path = output_dir / filename
            if path.exists():
                result[key] = pd.read_csv(path, encoding="utf-8-sig")
        return result
    except (OSError, UnicodeError, pd.errors.ParserError):
        return None


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    numeric = output.select_dtypes(include=["number"]).columns
    output[numeric] = output[numeric].round(6)
    return output


def _comparison_metric_rows(
    result: AnalysisResult, previous: dict[str, pd.DataFrame] | None
) -> list[str]:
    old_daily = None if not previous else previous.get("daily")
    old_peaks = pd.DataFrame() if not previous else previous.get("peaks", pd.DataFrame())
    old_signals = pd.DataFrame() if not previous else previous.get("signals", pd.DataFrame())
    display_peaks = result.peaks.loc[result.peaks["is_display_range"]] if not result.peaks.empty else result.peaks
    if not old_peaks.empty and "is_display_range" in old_peaks:
        old_peaks = old_peaks.loc[old_peaks["is_display_range"].astype(bool)]
    display_signals = result.signals
    if not display_signals.empty and "is_display_range" in display_signals:
        display_signals = display_signals.loc[display_signals["is_display_range"].astype(bool)]
    if not old_signals.empty and "is_display_range" in old_signals:
        old_signals = old_signals.loc[old_signals["is_display_range"].astype(bool)]
    current = result.daily_features.iloc[-1]
    end_date = str(current["date"])
    old_current = None
    if old_daily is not None and not old_daily.empty:
        matching = old_daily.loc[old_daily["date"].astype(str) == end_date] if "date" in old_daily else pd.DataFrame()
        old_current = matching.iloc[-1] if not matching.empty else old_daily.iloc[-1]
    old_peak_dates = old_peaks.loc[old_peaks.get("is_independent_peak", pd.Series(False, index=old_peaks.index)).astype(bool), "peak_date"].astype(str).tolist() if not old_peaks.empty else []
    new_peak_dates = display_peaks.loc[display_peaks["is_independent_peak"].astype(bool), "peak_date"].astype(str).tolist() if not display_peaks.empty else []

    def signal_count(frame: pd.DataFrame, kind: SignalType) -> int:
        return 0 if frame.empty or "signal_type" not in frame else int((frame["signal_type"] == kind.value).sum())

    old_rsi_key = "rsi" if old_current is not None and "rsi" in old_current else "rsi14"
    rows = ["| 项目 | 旧输出 | 当前输出 |", "|---|---:|---:|"]
    rows.extend([
        f"| {end_date} RSI | {_old_value(old_current, old_rsi_key)} | {float(current['rsi']):.6f} |",
        f"| 展示区间候选峰 | {len(old_peaks)} | {len(display_peaks)} |",
        f"| 展示区间独立/规范峰 | {int(old_peaks['is_independent_peak'].sum()) if 'is_independent_peak' in old_peaks else '—'} | {int(display_peaks['is_independent_peak'].sum()) if not display_peaks.empty else 0} |",
        f"| 顶部背离 | {signal_count(old_signals, SignalType.BEARISH_DIVERGENCE)} | {signal_count(display_signals, SignalType.BEARISH_DIVERGENCE)} |",
        f"| 弱反弹 | {signal_count(old_signals, SignalType.LOWER_HIGH_WEAK_REBOUND)} | {signal_count(display_signals, SignalType.LOWER_HIGH_WEAK_REBOUND)} |",
        f"| 期末状态 | {_old_value(old_current, 'base_state')} | {current['decision_base_state']} |",
        f"| 期末仓位上限 | {_old_value(old_current, 'final_position_cap')} | decision={float(current['decision_final_position_cap']):.2f}, effective={float(current['effective_final_position_cap']):.2f} |",
        f"| 展示区间cycle reset记录 | 无独立cycle_log | {int((pd.to_datetime(result.cycle_log['reset_decision_date'], errors='coerce') >= pd.Timestamp(result.metadata['display_start_date'])).sum())} |",
        f"| 独立峰日期 | {', '.join(old_peak_dates) or '—'} | {', '.join(new_peak_dates) or '—'} |",
    ])
    return rows


def _relationship_change_lines(result: AnalysisResult) -> list[str]:
    signals = result.signals
    if not signals.empty and "is_display_range" in signals:
        signals = signals.loc[signals["is_display_range"].astype(bool)]
    if signals.empty:
        return ["- 展示区间没有峰值关系信号。"]
    lines: list[str] = []
    for _, item in signals.iterrows():
        lines.append(
            f"- {item['decision_date']}：{item['signal_type']}，当前 {item['current_candidate_peak_id']} "
            f"({item['current_peak_date']}, close={float(item['current_peak_close']):.2f}, RSI={float(item['current_peak_rsi']):.4f})；"
            f"前峰 {item['previous_candidate_peak_id']} ({item['previous_peak_date']}, "
            f"close={float(item['previous_peak_close']):.2f}, RSI={float(item['previous_peak_rsi']):.4f})；"
            f"count={int(item['divergence_count'])}，effective={item['effective_date']}。"
        )
    return lines


def _same_number(left: Any, right: Any) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    try:
        return abs(float(left) - float(right)) < 1e-12
    except (TypeError, ValueError):
        return left == right


def _old_value(row: pd.Series | None, key: str) -> str:
    if row is None or key not in row or pd.isna(row[key]):
        return "—"
    value = row[key]
    return f"{float(value):.6f}" if isinstance(value, (int, float)) else str(value)
