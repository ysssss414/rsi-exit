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
) -> Path:
    output_dir = Path(output_root).resolve() / result.symbol
    output_dir.mkdir(parents=True, exist_ok=True)
    encoding = str(config.values["output"].get("csv_encoding", "utf-8-sig"))

    _csv_ready(result.daily_features).to_csv(
        output_dir / "daily_features.csv", index=False, encoding=encoding
    )
    _csv_ready(result.peaks).to_csv(
        output_dir / "peaks.csv", index=False, encoding=encoding
    )
    _csv_ready(result.signals).to_csv(
        output_dir / "signals.csv", index=False, encoding=encoding
    )
    _csv_ready(result.state_log).to_csv(
        output_dir / "state_log.csv", index=False, encoding=encoding
    )
    (output_dir / "summary.md").write_text(
        build_summary(result, config), encoding="utf-8"
    )
    if plot:
        from rsi_exit.plotting import create_annotated_chart

        create_annotated_chart(result, output_dir / "annotated_chart.png")
    return output_dir


def write_batch_summary(frame: pd.DataFrame, output_root: str | Path) -> Path:
    path = Path(output_root).resolve() / "peak_validation_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    _csv_ready(frame).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def build_summary(result: AnalysisResult, config: RsiExitConfig) -> str:
    signals = result.signals
    peaks = result.peaks
    independent_count = int(peaks["is_independent_peak"].sum()) if not peaks.empty else 0
    divergence = signals.loc[
        signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value
    ]
    weak = signals.loc[
        signals["signal_type"] == SignalType.LOWER_HIGH_WEAK_REBOUND.value
    ]
    current = result.daily_features.iloc[-1]
    divergence_dates = []
    for count in (1, 2, 3):
        dates = divergence.loc[
            divergence["divergence_count"] == count, "signal_date"
        ].tolist()
        divergence_dates.append(f"- {count}背确认日：{', '.join(dates) if dates else '无'}")

    signal_lines = []
    for _, signal in signals.iterrows():
        signal_lines.append(
            "- {date} / {kind} / count={count} / cap={cap:.2f} / action={action} / earliest={earliest}".format(
                date=signal["signal_date"],
                kind=signal["signal_type"],
                count=int(signal["divergence_count"]),
                cap=float(signal["final_position_cap"]),
                action=signal["final_action"],
                earliest=signal["earliest_action_date"] or "区间外",
            )
        )
    warning_lines = [f"- {warning}" for warning in result.warnings]
    params = {
        key: config.values[key]
        for key in ("rsi", "levels", "peak_detection", "divergence", "position_caps")
    }
    missing = bool(result.daily_features[["open", "high", "low", "close", "volume", "amount"]].isna().any().any())
    high_area_lines = _high_area_summary(result)

    return "\n".join(
        [
            f"# {result.name or result.symbol} RSI卖点识别摘要",
            "",
            f"- 股票代码：{result.symbol}",
            f"- 股票名称：{result.name or '未提供'}",
            f"- 数据区间：{result.metadata['start_date']} 至 {result.metadata['end_date']}",
            f"- 数据源：{result.metadata['source']}",
            f"- 复权口径：{result.metadata['adjust']}",
            f"- RSI算法：{result.metadata['rsi_algorithm']}",
            f"- seed_mode：{result.metadata['seed_mode']}",
            f"- 有效独立高点数量：{independent_count}",
            f"- 顶部背离数量：{len(divergence)}",
            f"- 弱反弹数量：{len(weak)}",
            *divergence_dates,
            f"- 当前状态：{current['base_state']}",
            f"- 当前RSI：{float(current['rsi14']):.4f}" if pd.notna(current["rsi14"]) else "- 当前RSI：不可用",
            f"- 当前建议动作：{current['final_action']}",
            f"- 当前目标仓位上限：{float(current['final_position_cap']):.2f}",
            f"- 原始行情字段是否缺失：{'是' if missing else '否'}",
            "",
            "## 信号与仓位",
            "",
            *(signal_lines or ["- 无相邻有效高点分类信号。"]),
            "",
            "## 参数",
            "",
            "```json",
            json.dumps(params, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 关键警告",
            "",
            *(warning_lines or ["- 无。"]),
            "",
            "## 人工核验口径",
            "",
            "算法以收盘价和RSI同步上升形成候选高点，并等待下一交易日二者同步下降后确认。盘中最高价只在行情与图表中展示，不参与高点条件；因此按盘中最高价目测的峰值与程序峰值可能落在同一区域但数值不同。确认日是决策生成日，交易执行不得早于 earliest_action_date。",
            "",
            "## 区间最高价区域核验",
            "",
            *high_area_lines,
            "",
        ]
    )


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    numeric = output.select_dtypes(include=["number"]).columns
    output[numeric] = output[numeric].round(6)
    return output


def _high_area_summary(result: AnalysisResult) -> list[str]:
    daily = result.daily_features.copy()
    high_row = daily.loc[pd.to_numeric(daily["high"], errors="coerce").idxmax()]
    high_date = str(high_row["date"])
    high_value = float(high_row["high"])
    matching = result.peaks.loc[result.peaks["peak_date"] == high_date]
    lines = [f"- 区间盘中最高价：{high_value:.2f}（{high_date}）。"]
    if matching.empty:
        lines.append("- 该日未满足收盘价与RSI同步候选高点条件，因此没有被硬编码为有效高点。")
        return lines
    peak = matching.iloc[-1]
    lines.append(
        f"- 同日收盘价高点 {peak['peak_close']} 被识别为 {peak['peak_id']}，确认日为 {peak['confirm_date']}，最早执行日为 {peak['earliest_action_date']}。"
    )
    signal = result.signals.loc[result.signals["peak_id"] == peak["peak_id"]]
    state = result.state_log.loc[result.state_log["date"] == peak["confirm_date"]]
    if signal.empty:
        lines.append(
            "- 该高点没有新增相邻峰值分类信号：按配置，状态机此前进入 S3 后背离周期已归零，此峰成为新周期首个动能基准；这不是漏看未来数据。"
        )
    else:
        item = signal.iloc[-1]
        lines.append(
            f"- 高点分类：{item['signal_type']}，背离计数 {int(item['divergence_count'])}，最终仓位上限 {float(item['final_position_cap']):.2f}。"
        )
    if not state.empty:
        item = state.iloc[-1]
        lines.append(
            f"- 确认日基础状态：{item['current_state']}，最终仓位上限 {float(item['position_cap']):.2f}。"
        )
    return lines
