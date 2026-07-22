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
    signals, peaks = result.signals, result.peaks
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
        f"# {result.name or result.symbol} RSI卖点识别摘要（v0.2）", "",
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
        f"- 当前RSI：{float(current['rsi14']):.4f}" if pd.notna(current["rsi14"]) else "- 当前RSI：不可用",
        f"- 当前有效仓位上限：{float(current['effective_final_position_cap']):.2f}",
        "", "## 信号与仓位", "", *(signal_lines or ["- 无展示区间信号。"]),
        "", "## RSI口径审计", "",
        f"- {result.metadata['rsi_algorithm']}；seed_mode={result.metadata['seed_mode']}。",
        f"- {result.metadata['rsi_difference_explanation']}",
        "- `rsi_audit.csv` 保留原始/复权收盘价、因子、单日变化、正变化、绝对变化、两条平滑序列、RSI、预热/展示标志和校验和。",
        "", "## 因果与状态口径", "",
        "- 峰值日在下一真实交易日确认；确认日只生成决策，最早再下一真实交易日生效。",
        "- 同日先处理峰值关系并保存版本快照，随后执行 S3/趋势强化等周期重置。",
        "- `ALLOW_REENTRY` 是一次资格事件，落回 S0；它不表示自动买入，S5 不再持久化。",
        "", "## 参数", "", "```json", json.dumps(params, ensure_ascii=False, indent=2), "```",
        "", "## 警告", "", *(warning_lines or ["- 无。"]), "",
    ])


def build_regression_comparison(
    result: AnalysisResult, previous: dict[str, pd.DataFrame] | None
) -> str:
    dates = [
        "2026-04-28", "2026-05-21", "2026-05-29", "2026-06-01", "2026-06-05",
        "2026-06-08", "2026-06-11", "2026-06-18", "2026-06-22", "2026-06-23",
        "2026-06-24", "2026-06-26", "2026-06-29", "2026-07-20",
    ]
    daily = result.daily_features.set_index("date")
    old_daily = None if not previous or "daily" not in previous else previous["daily"].copy()
    if old_daily is not None and "date" in old_daily:
        old_daily["date"] = old_daily["date"].astype(str)
        old_daily = old_daily.set_index("date")
    signal_groups = result.signals.groupby("decision_date")["signal_type"].apply(lambda x: ",".join(x)).to_dict() if not result.signals.empty else {}
    rows = ["| 日期 | v0.1 状态/上限 | v0.2 决策状态 | v0.2 决策/有效上限 | 当日关系/事件 |", "|---|---|---|---:|---|"]
    for date in dates:
        if date not in daily.index:
            rows.append(f"| {date} | — | 无交易行 | — | — |")
            continue
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

    old_note = "未发现可识别的 v0.1 本地输出，以下只记录 v0.2。"
    if previous and "daily" in previous:
        old = previous["daily"]
        old_note = f"写入前读取到旧输出 {len(old)} 行；旧列契约={'v0.1' if 'decision_base_state' not in old else 'v0.2'}。"
        if "date" in old and "rsi14" in old:
            old_last = old.loc[old["date"].astype(str) == "2026-07-20"]
            if not old_last.empty:
                old_note += f" 旧版 2026-07-20 RSI={float(old_last.iloc[-1]['rsi14']):.6f}。"
    new_last = daily.loc["2026-07-20", "rsi14"] if "2026-07-20" in daily.index else None
    new_text = "无该日交易行" if new_last is None or pd.isna(new_last) else f"{float(new_last):.6f}"
    metric_rows = _comparison_metric_rows(result, previous)
    relationship_lines = _relationship_change_lines(result)
    return "\n".join([
        "# rsi-exit v0.1 / v0.2 回归对照", "", old_note, "",
        "v0.2 的 RSI 公式不变；差异来自在完整前复权序列上先递推至少 120 个真实交易日再截取展示区间。旧验收值 38.8449 是从展示起点播种所得，不是本版目标常量。",
        f"v0.2 的 2026-07-20 RSI：{new_text}。", "", "## 总体 old/new", "", *metric_rows,
        "", "## 关键关系变化", "", *relationship_lines,
        "", "## 关键日期", "", *rows, "",
        "## 版本口径", "",
        "- v0.1 的 `peak_id` 同时承担候选和代表身份；v0.2 分拆为 candidate/canonical/representative/version。",
        "- v0.1 当日更新仓位；v0.2 显式区分 decision/earliest_action/effective，并用排队约束取严。",
        "- v0.1 在状态步进前重置周期；v0.2 先保存同日峰值关系，再重置未来周期。", "",
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
    current = result.daily_features.iloc[-1]
    old_current = None if old_daily is None or old_daily.empty else old_daily.iloc[-1]
    old_peak_dates = old_peaks.loc[old_peaks.get("is_independent_peak", pd.Series(False, index=old_peaks.index)).astype(bool), "peak_date"].astype(str).tolist() if not old_peaks.empty else []
    new_peak_dates = display_peaks.loc[display_peaks["is_independent_peak"].astype(bool), "peak_date"].astype(str).tolist() if not display_peaks.empty else []

    def signal_count(frame: pd.DataFrame, kind: SignalType) -> int:
        return 0 if frame.empty or "signal_type" not in frame else int((frame["signal_type"] == kind.value).sum())

    rows = ["| 项目 | v0.1 | v0.2 |", "|---|---:|---:|"]
    rows.extend([
        f"| 2026-07-20 RSI | {_old_value(old_current, 'rsi14')} | {float(current['rsi14']):.6f} |",
        f"| 展示区间候选峰 | {len(old_peaks)} | {len(display_peaks)} |",
        f"| 展示区间独立/规范峰 | {int(old_peaks['is_independent_peak'].sum()) if 'is_independent_peak' in old_peaks else '—'} | {int(display_peaks['is_independent_peak'].sum()) if not display_peaks.empty else 0} |",
        f"| 顶部背离 | {signal_count(old_signals, SignalType.BEARISH_DIVERGENCE)} | {signal_count(result.signals, SignalType.BEARISH_DIVERGENCE)} |",
        f"| 弱反弹 | {signal_count(old_signals, SignalType.LOWER_HIGH_WEAK_REBOUND)} | {signal_count(result.signals, SignalType.LOWER_HIGH_WEAK_REBOUND)} |",
        f"| 期末状态 | {_old_value(old_current, 'base_state')} | {current['decision_base_state']} |",
        f"| 期末仓位上限 | {_old_value(old_current, 'final_position_cap')} | decision={float(current['decision_final_position_cap']):.2f}, effective={float(current['effective_final_position_cap']):.2f} |",
        f"| 展示区间cycle reset记录 | 无独立cycle_log | {int((pd.to_datetime(result.cycle_log['reset_decision_date'], errors='coerce') >= pd.Timestamp(result.metadata['display_start_date'])).sum())} |",
        f"| 独立峰日期 | {', '.join(old_peak_dates) or '—'} | {', '.join(new_peak_dates) or '—'} |",
    ])
    return rows


def _relationship_change_lines(result: AnalysisResult) -> list[str]:
    lines: list[str] = []
    for date in ("2026-05-29", "2026-06-05"):
        subset = result.signals.loc[result.signals["decision_date"] == date]
        if subset.empty:
            lines.append(f"- {date}：新版没有峰值关系信号。")
            continue
        item = subset.iloc[-1]
        lines.append(
            f"- {date}：{item['signal_type']}，当前 {item['current_candidate_peak_id']} "
            f"({item['current_peak_date']}, close={float(item['current_peak_close']):.2f}, RSI={float(item['current_peak_rsi']):.4f})；"
            f"前峰 {item['previous_candidate_peak_id']} ({item['previous_peak_date']}, "
            f"close={float(item['previous_peak_close']):.2f}, RSI={float(item['previous_peak_rsi']):.4f})；"
            f"count={int(item['divergence_count'])}，effective={item['effective_date']}。"
        )
        if date == "2026-05-29":
            lines.append(
                f"  当时动能锚为 {item['momentum_anchor_candidate_id']}/"
                f"{item['momentum_anchor_canonical_id']}@v{int(item['momentum_anchor_canonical_version'])} "
                f"({item['momentum_anchor_date']}, RSI={float(item['momentum_anchor_rsi']):.4f})。"
            )
    lines.append("- 5月29日改为趋势强化的直接原因是默认候选定义不再附加三日窗口最大值，5月20日新增为相邻规范峰；5月28日价格和RSI均高于该前峰，周期据此重置。6月5日因此从一背开始，而不是保留旧版二背编号。")
    return lines


def _old_value(row: pd.Series | None, key: str) -> str:
    if row is None or key not in row or pd.isna(row[key]):
        return "—"
    value = row[key]
    return f"{float(value):.6f}" if isinstance(value, (int, float)) else str(value)
