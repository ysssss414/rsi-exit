from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from rsi_exit.models import (
    SignalType,
    WarningEvent,
    WarningLifecycleEvent,
    WarningPositionEffect,
    WarningSourceKind,
    WarningStatus,
    WarningType,
)
from rsi_exit.pipeline import AnalysisResult
from rsi_exit.warning_events import (
    WARNING_EVENT_COLUMNS,
    WarningLifecycleContractError,
    derive_warning_states,
)


HORIZONS = (1, 3, 5, 10, 20)
STATUS_ORDER = ("ACTIVE", "ESCALATED", "CLEARED", "INVALIDATED")
EVENT_ORDER = ("OPENED", "REFRESHED", "ESCALATED", "CLEARED", "INVALIDATED")
TERMINAL_EVENTS = {"ESCALATED", "CLEARED", "INVALIDATED"}
FORMAL_DIVERGENCE_VALUES = {
    SignalType.BEARISH_DIVERGENCE.value,
    SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
    SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
}

SAMPLE_SUMMARY_COLUMNS = [
    "symbol",
    "name",
    "sample_group",
    "display_start_date",
    "display_end_date",
    "calculation_start_date",
    "calculation_end_date",
    "input_checksum_sha256",
    "display_bar_count",
    "backtest_eligible",
    "backtest_ineligible_reason",
    "formal_divergence_count",
    "cohort_warning_count",
    "carry_in_warning_count",
    "opened_event_count",
    "refreshed_event_count",
    "escalated_event_count",
    "cleared_event_count",
    "invalidated_event_count",
    "active_warning_count",
    "escalated_warning_count",
    "cleared_warning_count",
    "invalidated_warning_count",
    "contract_validation_passed",
    "error",
]

WARNING_OUTCOME_COLUMNS = [
    "symbol",
    "name",
    "sample_group",
    "warning_id",
    "source_peak_id",
    "source_peak_date",
    "opened_date",
    "opened_source_version",
    "latest_source_version",
    "refresh_count",
    "as_of_status",
    "latest_event",
    "latest_event_date",
    "terminal_date",
    "terminal_end_reason",
    "linked_formal_signal_ref",
    "duration_trading_days",
    "lead_to_escalation_trading_days",
    "opened_close",
    "opened_rsi",
    "latest_close",
    "latest_rsi",
]
for _horizon in HORIZONS:
    WARNING_OUTCOME_COLUMNS.extend([
        f"forward_return_{_horizon}",
        f"max_forward_return_{_horizon}",
        f"min_forward_return_{_horizon}",
        f"horizon_{_horizon}_complete",
    ])

OUTCOME_SUMMARY_COLUMNS = [
    "as_of_status",
    "horizon_days",
    "warning_count",
    "complete_horizon_count",
    "median_forward_return",
    "median_max_forward_return",
    "median_min_forward_return",
]


class ValidationError(ValueError):
    """A sample cannot support the requested descriptive validation."""


class ContractValidationError(ValidationError):
    """An existing warning event history violates the lifecycle contract."""


@dataclass(frozen=True)
class SampleValidation:
    summary: dict[str, object]
    outcomes: pd.DataFrame


@dataclass(frozen=True)
class ValidationBundle:
    sample_summary: pd.DataFrame
    warning_outcomes: pd.DataFrame
    outcome_summary: pd.DataFrame
    validation_report: str

    @property
    def failed_count(self) -> int:
        if self.sample_summary.empty:
            return 0
        return int((self.sample_summary["error"].astype(str) != "").sum())


def validate_sample_result(
    result: AnalysisResult,
    *,
    sample_group: str,
    display_start_date: str,
    display_end_date: str,
) -> SampleValidation:
    """Validate one existing analysis result without modifying it."""

    display_start = pd.Timestamp(display_start_date)
    display_end = pd.Timestamp(display_end_date)
    if display_start > display_end:
        raise ValidationError("display_start_date is after display_end_date")

    events = _normalized_event_frame(result.warning_events)
    models = _validate_warning_contract(events)
    try:
        states = derive_warning_states(models, as_of_date=display_end.strftime("%Y-%m-%d"))
    except WarningLifecycleContractError as exc:
        raise ContractValidationError(str(exc)) from exc

    daily = _normalized_daily(result.daily_features, display_end)
    display_daily = daily.loc[
        daily["_date"].between(display_start, display_end)
    ].reset_index(drop=True)
    if display_daily.empty:
        raise ValidationError("daily_features has no rows inside the display range")
    date_to_index = {
        date: index for index, date in enumerate(display_daily["_date"].tolist())
    }

    event_dates = pd.to_datetime(events["decision_date"], errors="raise")
    cutoff_events = events.loc[event_dates <= display_end].copy()
    cutoff_events["_date"] = pd.to_datetime(
        cutoff_events["decision_date"], errors="raise"
    )
    cutoff_events["_event_order"] = range(len(cutoff_events))
    cutoff_events = cutoff_events.sort_values(
        ["_date", "warning_id", "_event_order", "source_version"],
        kind="mergesort",
    )

    opened = events.loc[events["lifecycle_event"] == "OPENED"].copy()
    opened["_date"] = pd.to_datetime(opened["decision_date"], errors="raise")
    cohort_opened = opened.loc[opened["_date"].between(display_start, display_end)]
    carry_in_count = _carry_in_count(events, display_start)

    outcomes: list[dict[str, object]] = []
    for _, opened_row in cohort_opened.sort_values(
        ["symbol", "_date", "warning_id"], kind="mergesort"
    ).iterrows():
        warning_id = str(opened_row["warning_id"])
        history = cutoff_events.loc[
            cutoff_events["warning_id"].astype(str) == warning_id
        ]
        if history.empty or warning_id not in states:
            raise ValidationError(
                f"warning {warning_id} has no state at display cutoff"
            )
        outcomes.append(_build_warning_outcome(
            result=result,
            sample_group=sample_group,
            opened_row=opened_row,
            history=history,
            status=states[warning_id].value,
            display_daily=display_daily,
            date_to_index=date_to_index,
        ))

    outcome_frame = pd.DataFrame(outcomes, columns=WARNING_OUTCOME_COLUMNS)
    if not outcome_frame.empty:
        outcome_frame = outcome_frame.sort_values(
            ["symbol", "opened_date", "warning_id"], kind="mergesort"
        ).reset_index(drop=True)

    display_event_counts = {
        event: int(
            (
                cutoff_events["_date"].between(display_start, display_end)
                & (cutoff_events["lifecycle_event"] == event)
            ).sum()
        )
        for event in EVENT_ORDER
    }
    status_counts = {
        status: int((outcome_frame["as_of_status"] == status).sum())
        if not outcome_frame.empty
        else 0
        for status in STATUS_ORDER
    }
    metadata = result.metadata
    summary = {
        "symbol": result.symbol,
        "name": result.name,
        "sample_group": sample_group,
        "display_start_date": display_start.strftime("%Y-%m-%d"),
        "display_end_date": display_end.strftime("%Y-%m-%d"),
        "calculation_start_date": metadata.get("calculation_start_date"),
        "calculation_end_date": metadata.get("calculation_end_date"),
        "input_checksum_sha256": metadata.get("input_checksum_sha256"),
        "display_bar_count": len(display_daily),
        "backtest_eligible": bool(metadata.get("backtest_eligible", False)),
        "backtest_ineligible_reason": _backtest_ineligible_reason(metadata),
        "formal_divergence_count": _formal_divergence_count(
            result.signals, display_start, display_end
        ),
        "cohort_warning_count": len(outcome_frame),
        "carry_in_warning_count": carry_in_count,
        "opened_event_count": display_event_counts["OPENED"],
        "refreshed_event_count": display_event_counts["REFRESHED"],
        "escalated_event_count": display_event_counts["ESCALATED"],
        "cleared_event_count": display_event_counts["CLEARED"],
        "invalidated_event_count": display_event_counts["INVALIDATED"],
        "active_warning_count": status_counts["ACTIVE"],
        "escalated_warning_count": status_counts["ESCALATED"],
        "cleared_warning_count": status_counts["CLEARED"],
        "invalidated_warning_count": status_counts["INVALIDATED"],
        "contract_validation_passed": True,
        "error": "",
    }
    return SampleValidation(summary=summary, outcomes=outcome_frame)


def build_validation_bundle(
    manifest: pd.DataFrame,
    results_by_symbol: Mapping[str, AnalysisResult],
    *,
    names_by_symbol: Mapping[str, str | None],
    display_start_date: str,
    display_end_date: str,
    chart_path_root: str,
    errors_by_symbol: Mapping[str, str] | None = None,
) -> ValidationBundle:
    """Build deterministic multi-sample tables and the answer-first report."""

    samples = _validate_manifest(manifest)
    errors = errors_by_symbol or {}
    summaries: list[dict[str, object]] = []
    outcomes: list[pd.DataFrame] = []
    for row in samples.itertuples(index=False):
        symbol = str(row.symbol)
        if symbol in errors:
            result = results_by_symbol.get(symbol)
            summaries.append(_failed_summary(
                symbol=symbol,
                name=names_by_symbol.get(symbol) or (
                    result.name if result is not None else None
                ),
                sample_group=str(row.sample_group),
                display_start_date=display_start_date,
                display_end_date=display_end_date,
                error=f"analysis failed: {errors[symbol]}",
                result=result,
            ))
            continue
        result = results_by_symbol.get(symbol)
        if result is None:
            summaries.append(_failed_summary(
                symbol=symbol,
                name=names_by_symbol.get(symbol),
                sample_group=str(row.sample_group),
                display_start_date=display_start_date,
                display_end_date=display_end_date,
                error="analysis failed: no analysis result",
            ))
            continue
        try:
            validated = validate_sample_result(
                result,
                sample_group=str(row.sample_group),
                display_start_date=display_start_date,
                display_end_date=display_end_date,
            )
        except ContractValidationError as exc:
            summaries.append(_failed_summary(
                symbol=symbol,
                name=names_by_symbol.get(symbol) or result.name,
                sample_group=str(row.sample_group),
                display_start_date=display_start_date,
                display_end_date=display_end_date,
                error=f"contract validation failed: {exc}",
                result=result,
            ))
            continue
        except Exception as exc:
            summaries.append(_failed_summary(
                symbol=symbol,
                name=names_by_symbol.get(symbol) or result.name,
                sample_group=str(row.sample_group),
                display_start_date=display_start_date,
                display_end_date=display_end_date,
                error=f"validation failed: {exc}",
                result=result,
            ))
            continue
        summaries.append(validated.summary)
        outcomes.append(validated.outcomes)

    sample_summary = pd.DataFrame(summaries, columns=SAMPLE_SUMMARY_COLUMNS)
    warning_outcomes = (
        pd.concat(outcomes, ignore_index=True)
        if outcomes
        else pd.DataFrame(columns=WARNING_OUTCOME_COLUMNS)
    )
    if not warning_outcomes.empty:
        warning_outcomes = warning_outcomes.sort_values(
            ["symbol", "opened_date", "warning_id"], kind="mergesort"
        ).reset_index(drop=True)
    outcome_summary = _build_outcome_summary(warning_outcomes)
    report = build_validation_report(
        sample_summary,
        warning_outcomes,
        outcome_summary,
        display_start_date=display_start_date,
        display_end_date=display_end_date,
        chart_path_root=chart_path_root,
    )
    return ValidationBundle(
        sample_summary=sample_summary,
        warning_outcomes=warning_outcomes,
        outcome_summary=outcome_summary,
        validation_report=report,
    )


def write_validation_bundle(
    bundle: ValidationBundle,
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "sample_summary": output / "sample_summary.csv",
        "warning_outcomes": output / "warning_outcomes.csv",
        "outcome_summary": output / "outcome_summary.csv",
        "validation_report": output / "validation_report.md",
    }
    bundle.sample_summary.to_csv(
        paths["sample_summary"], index=False, encoding="utf-8-sig"
    )
    bundle.warning_outcomes.to_csv(
        paths["warning_outcomes"], index=False, encoding="utf-8-sig"
    )
    bundle.outcome_summary.to_csv(
        paths["outcome_summary"], index=False, encoding="utf-8-sig"
    )
    paths["validation_report"].write_text(
        bundle.validation_report, encoding="utf-8"
    )
    return paths


def build_validation_report(
    sample_summary: pd.DataFrame,
    warning_outcomes: pd.DataFrame,
    outcome_summary: pd.DataFrame,
    *,
    display_start_date: str,
    display_end_date: str,
    chart_path_root: str,
) -> str:
    sample_count = len(sample_summary)
    failed = sample_summary.loc[sample_summary["error"].astype(str) != ""]
    success_count = sample_count - len(failed)
    contract_errors = failed["error"].astype(str).str.startswith(
        "contract validation failed:"
    ).sum()
    cohort_count = int(sample_summary["cohort_warning_count"].fillna(0).sum())
    carry_count = int(sample_summary["carry_in_warning_count"].fillna(0).sum())
    status_counts = {
        status: int(
            sample_summary[f"{status.lower()}_warning_count"].fillna(0).sum()
        )
        for status in STATUS_ORDER
    }
    event_counts = {
        event: int(
            sample_summary[f"{event.lower()}_event_count"].fillna(0).sum()
        )
        for event in EVENT_ORDER
    }
    invalid_reasons = _value_counts(
        warning_outcomes.loc[
            warning_outcomes["as_of_status"] == "INVALIDATED",
            "terminal_end_reason",
        ] if not warning_outcomes.empty else pd.Series(dtype=object)
    )
    lead = (
        pd.to_numeric(
            warning_outcomes["lead_to_escalation_trading_days"], errors="coerce"
        ).dropna()
        if not warning_outcomes.empty
        else pd.Series(dtype=float)
    )
    refresh = (
        pd.to_numeric(warning_outcomes["refresh_count"], errors="coerce").dropna()
        if not warning_outcomes.empty
        else pd.Series(dtype=float)
    )
    density = _warning_density_text(sample_summary)

    sample_table = sample_summary.loc[:, [
        "symbol", "name", "sample_group", "formal_divergence_count",
        "cohort_warning_count", "carry_in_warning_count",
        "active_warning_count", "escalated_warning_count",
        "cleared_warning_count", "invalidated_warning_count",
        "contract_validation_passed", "error",
    ]].copy()
    sample_table.columns = [
        "代码", "名称", "组别", "正式背离", "cohort", "carry-in",
        "ACTIVE", "ESCALATED", "CLEARED", "INVALIDATED", "合同通过", "错误",
    ]

    lifecycle_rows = [
        {"指标": event, "数量": event_counts[event]} for event in EVENT_ORDER
    ]
    lifecycle_rows.extend([
        {
            "指标": "每个 cohort warning 的平均 refresh",
            "数量": _number_or_dash(refresh.mean() if not refresh.empty else np.nan),
        },
        {
            "指标": "每个 cohort warning 的中位 refresh",
            "数量": _number_or_dash(refresh.median() if not refresh.empty else np.nan),
        },
        *[
            {"指标": f"终态 {status}", "数量": status_counts[status]}
            for status in ("ESCALATED", "CLEARED", "INVALIDATED")
        ],
    ])
    price_table = outcome_summary.copy()
    for column in (
        "median_forward_return",
        "median_max_forward_return",
        "median_min_forward_return",
    ):
        price_table[column] = price_table[column].map(_percent_or_dash)
    price_table.columns = [
        "截止状态", "交易日 horizon", "warning 数", "完整样本数",
        "期末收益中位数", "区间最大收益中位数", "区间最小收益中位数",
    ]

    case_lines = _representative_case_lines(
        warning_outcomes, chart_path_root=chart_path_root
    )
    anomaly_lines = _anomaly_lines(
        sample_summary, warning_outcomes, failed_count=len(failed)
    )
    failure_lines = (
        [
            f"- `{row.symbol}`：{row.error}"
            for row in failed.loc[:, ["symbol", "error"]].itertuples(index=False)
        ]
        or ["- 无失败样本。"]
    )

    return "\n".join([
        "# rsi-exit v0.4 Phase 4 多样本描述性验证",
        "",
        "## 执行摘要",
        "",
        (
            f"- **执行结果：**{sample_count} 个样本中 {success_count} 个成功，"
            f"{len(failed)} 个失败；warning lifecycle 合同错误 {contract_errors} 个。"
        ),
        (
            f"- **验证 cohort：**展示区间形成 {cohort_count} 个 warning，另有 "
            f"{carry_count} 个 carry-in；截止状态为 "
            + " / ".join(f"{status} {status_counts[status]}" for status in STATUS_ORDER)
            + "。"
        ),
        (
            "- **INVALIDATED 原因：**"
            + (_counts_text(invalid_reasons) if invalid_reasons else "未观察到 INVALIDATED。")
        ),
        (
            "- **ESCALATED lead time：**"
            + (
                f"中位数 {_number_or_dash(lead.median())} 个交易日，"
                f"范围 {int(lead.min())}–{int(lead.max())} 个交易日。"
                if not lead.empty
                else "没有可计算样本。"
            )
        ),
        f"- **warning 密度：**{density}",
        "",
        "本报告只验证固定口径下的运行稳定性、事件合同和描述性价格路径；"
        "结果不用于比较个股优劣，也不构成参数或仓位建议。",
        "",
        "## 固定样本的运行与合同结果",
        "",
        "表中 warning 数与 event 数保持不同粒度；失败样本保留原 manifest 行。",
        "",
        _markdown_table(sample_table),
        "",
        "### 失败明细",
        "",
        *failure_lines,
        "",
        "## 生命周期结构显示 refresh 与终态分布",
        "",
        (
            "展示区间 event 总数为 "
            + " / ".join(f"{event} {event_counts[event]}" for event in EVENT_ORDER)
            + "。下表同时给出 cohort 粒度的 refresh 汇总，避免把多次 refresh "
            "误计为多个 warning。"
        ),
        "",
        _markdown_table(pd.DataFrame(lifecycle_rows)),
        "",
        (
            "**INVALIDATED end reason：**"
            + (_counts_text(invalid_reasons) if invalid_reasons else "无。")
        ),
        "",
        (
            "**ESCALATED lead time：**"
            + (
                f"中位数 {_number_or_dash(lead.median())}，范围 "
                f"{int(lead.min())}–{int(lead.max())} 个交易日。"
                if not lead.empty
                else "无可计算样本。"
            )
        ),
        "",
        "## 截止状态分组的后续价格路径",
        "",
        "每行使用相同截止状态下的 cohort warning。完整样本数是展示结束日前确有"
        "足够后续交易行的 warning 数；不完整 horizon 不参与中位数。",
        "",
        _markdown_table(price_table),
        "",
        "**解释边界：**这些值只是 warning 后的描述性价格路径，不是策略收益；"
        "没有计入可执行价格、滑点、涨跌停或交易成本，也不能据此直接形成仓位规则。",
        "",
        "## 稳定排序选取的代表案例",
        "",
        "每种实际出现的截止状态最多列 2 个，按 symbol、opened_date、warning_id "
        "排序选取；复用正常单股输出中的本地图表，不另行绘图。",
        "",
        *case_lines,
        "",
        "## 范围、数据与指标定义",
        "",
        f"- 数据源：AmazingData；展示区间：{display_start_date} 至 {display_end_date}；"
        "复权：forward；配置：仓库默认配置；统一使用现有 warmup 要求。",
        "- 主 cohort：OPENED decision_date 位于展示区间；carry-in 单列且不进入"
        "价格路径分母。",
        "- duration 与 escalation lead time 均为 `daily_features` 实际交易行索引差；"
        "OPENED、latest 与 terminal 价格/RSI 只接受同日精确匹配。",
        "- 1/3/5/10/20 日路径只使用展示结束日前数据；不足完整 horizon 时三个"
        "收益字段为空且 complete=False。",
        "",
        "## 方法、稳健性与隔离检查",
        "",
        "- 每个样本先对完整 warning history 执行结构检查，再调用现有 "
        "`derive_warning_states` 推导展示结束日状态；验证层不复制状态机。",
        "- 检查 OPENED 唯一、REFRESHED 版本递增、最多一个终态、终态后无事件、"
        "event/status 对应、event ID 唯一、position_effect 全为 NONE、"
        "recommended_position_cap 全为空。",
        "- 验证函数只读取 AnalysisResult 的副本；生产输出对象、schema、summary "
        "和图表逻辑均不在本模块内修改。",
        "",
        "## 观察到的异常、限制与后续人工问题",
        "",
        *anomaly_lines,
        "- 样本和时间窗均为固定的描述性检查；小样本结果不支持统计显著性、因果"
        "或泛化结论。",
        "- 下一阶段如需研究 warning 过密、长期 ACTIVE、高 refresh 或正式背离缺少"
        "提前 warning，应先人工逐案审阅；本阶段不调参、不修改规则。",
        "",
    ])


def _normalized_event_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty and not frame.columns.tolist():
        return pd.DataFrame(columns=WARNING_EVENT_COLUMNS)
    missing = [column for column in WARNING_EVENT_COLUMNS if column not in frame]
    if missing:
        raise ContractValidationError(
            "warning event schema is missing columns: " + ", ".join(missing)
        )
    return frame.loc[:, WARNING_EVENT_COLUMNS].copy(deep=True)


def _validate_warning_contract(events: pd.DataFrame) -> list[WarningEvent]:
    if events.empty:
        return []
    if events["warning_event_id"].astype(str).duplicated().any():
        duplicate = events.loc[
            events["warning_event_id"].astype(str).duplicated(keep=False),
            "warning_event_id",
        ].iloc[0]
        raise ContractValidationError(f"duplicate warning_event_id: {duplicate}")
    if not events["position_effect"].eq("NONE").all():
        raise ContractValidationError("position_effect contains a value other than NONE")
    if not events["recommended_position_cap"].isna().all():
        raise ContractValidationError("recommended_position_cap contains a non-null value")
    expected_status = {
        "OPENED": "ACTIVE",
        "REFRESHED": "ACTIVE",
        "ESCALATED": "ESCALATED",
        "CLEARED": "CLEARED",
        "INVALIDATED": "INVALIDATED",
    }
    for row in events.loc[:, ["lifecycle_event", "warning_status"]].itertuples(
        index=False
    ):
        if expected_status.get(str(row.lifecycle_event)) != str(row.warning_status):
            raise ContractValidationError(
                f"lifecycle/status mismatch: {row.lifecycle_event}/{row.warning_status}"
            )
    try:
        models = [_warning_event_from_row(row) for _, row in events.iterrows()]
        derive_warning_states(models)
    except (ValueError, TypeError, WarningLifecycleContractError) as exc:
        raise ContractValidationError(str(exc)) from exc
    return models


def _warning_event_from_row(row: pd.Series) -> WarningEvent:
    return WarningEvent(
        symbol=str(row["symbol"]),
        warning_event_id=str(row["warning_event_id"]),
        warning_id=str(row["warning_id"]),
        warning_type=WarningType(str(row["warning_type"])),
        lifecycle_event=WarningLifecycleEvent(str(row["lifecycle_event"])),
        warning_status=WarningStatus(str(row["warning_status"])),
        source_kind=WarningSourceKind(str(row["source_kind"])),
        source_peak_id=str(row["source_peak_id"]),
        source_version=int(row["source_version"]),
        source_canonical_peak_id=_optional_text(row["source_canonical_peak_id"]),
        source_canonical_version=_optional_int(row["source_canonical_version"]),
        source_peak_date=str(row["source_peak_date"]),
        observation_date=str(row["observation_date"]),
        decision_date=str(row["decision_date"]),
        available_date=str(row["available_date"]),
        momentum_anchor_id=str(row["momentum_anchor_id"]),
        momentum_anchor_version=int(row["momentum_anchor_version"]),
        last_structural_peak_id=str(row["last_structural_peak_id"]),
        last_structural_peak_version=int(row["last_structural_peak_version"]),
        latest_confirmed_canonical_id=_optional_text(
            row["latest_confirmed_canonical_id"]
        ),
        latest_confirmed_canonical_version=_optional_int(
            row["latest_confirmed_canonical_version"]
        ),
        divergence_chain_id=str(row["divergence_chain_id"]),
        risk_cycle_id=str(row["risk_cycle_id"]),
        price_relation=str(row["price_relation"]),
        local_rsi_delta=float(row["local_rsi_delta"]),
        anchor_rsi_delta=float(row["anchor_rsi_delta"]),
        warning_reason=str(row["warning_reason"]),
        warning_evidence=str(row["warning_evidence"]),
        end_reason=_optional_text(row["end_reason"]),
        linked_formal_signal_ref=_optional_text(row["linked_formal_signal_ref"]),
        position_effect=WarningPositionEffect(str(row["position_effect"])),
        recommended_position_cap=(
            None
            if pd.isna(row["recommended_position_cap"])
            else float(row["recommended_position_cap"])
        ),
        is_warmup=bool(row["is_warmup"]),
        is_display_range=bool(row["is_display_range"]),
    )


def _normalized_daily(frame: pd.DataFrame, display_end: pd.Timestamp) -> pd.DataFrame:
    missing = [column for column in ("date", "close", "rsi") if column not in frame]
    if missing:
        raise ValidationError(
            "daily_features is missing columns: " + ", ".join(missing)
        )
    daily = frame.loc[:, ["date", "close", "rsi"]].copy(deep=True)
    daily["_date"] = pd.to_datetime(daily["date"], errors="raise")
    if daily["_date"].duplicated().any():
        raise ValidationError("daily_features contains duplicate dates")
    if not daily["_date"].is_monotonic_increasing:
        raise ValidationError("daily_features dates are not ascending")
    daily["close"] = pd.to_numeric(daily["close"], errors="raise")
    daily["rsi"] = pd.to_numeric(daily["rsi"], errors="coerce")
    return daily.loc[daily["_date"] <= display_end].reset_index(drop=True)


def _carry_in_count(events: pd.DataFrame, display_start: pd.Timestamp) -> int:
    if events.empty:
        return 0
    dated = events.copy()
    dated["_date"] = pd.to_datetime(dated["decision_date"], errors="raise")
    count = 0
    for _, history in dated.groupby("warning_id", sort=False):
        opened = history.loc[history["lifecycle_event"] == "OPENED"]
        if opened.empty or opened["_date"].iloc[0] >= display_start:
            continue
        terminal = history.loc[history["lifecycle_event"].isin(TERMINAL_EVENTS)]
        if terminal.empty or terminal["_date"].iloc[0] >= display_start:
            count += 1
    return count


def _build_warning_outcome(
    *,
    result: AnalysisResult,
    sample_group: str,
    opened_row: pd.Series,
    history: pd.DataFrame,
    status: str,
    display_daily: pd.DataFrame,
    date_to_index: Mapping[pd.Timestamp, int],
) -> dict[str, object]:
    latest = history.iloc[-1]
    opened_date = pd.Timestamp(opened_row["_date"])
    latest_date = pd.Timestamp(latest["_date"])
    opened_index = _exact_daily_index(
        date_to_index, opened_date, str(opened_row["warning_id"]), "OPENED"
    )
    latest_index = _exact_daily_index(
        date_to_index, latest_date, str(opened_row["warning_id"]), "latest event"
    )
    terminal = status in TERMINAL_EVENTS
    terminal_date = latest_date if terminal else pd.NaT
    duration_end_index = (
        latest_index if terminal else len(display_daily) - 1
    )
    opened_close = float(display_daily.iloc[opened_index]["close"])
    row: dict[str, object] = {
        "symbol": result.symbol,
        "name": result.name,
        "sample_group": sample_group,
        "warning_id": str(opened_row["warning_id"]),
        "source_peak_id": str(opened_row["source_peak_id"]),
        "source_peak_date": str(opened_row["source_peak_date"]),
        "opened_date": opened_date.strftime("%Y-%m-%d"),
        "opened_source_version": int(opened_row["source_version"]),
        "latest_source_version": int(latest["source_version"]),
        "refresh_count": int((history["lifecycle_event"] == "REFRESHED").sum()),
        "as_of_status": status,
        "latest_event": str(latest["lifecycle_event"]),
        "latest_event_date": latest_date.strftime("%Y-%m-%d"),
        "terminal_date": (
            terminal_date.strftime("%Y-%m-%d") if terminal else None
        ),
        "terminal_end_reason": (
            _optional_text(latest["end_reason"]) if terminal else None
        ),
        "linked_formal_signal_ref": (
            _optional_text(latest["linked_formal_signal_ref"]) if terminal else None
        ),
        "duration_trading_days": int(duration_end_index - opened_index),
        "lead_to_escalation_trading_days": (
            int(latest_index - opened_index) if status == "ESCALATED" else None
        ),
        "opened_close": opened_close,
        "opened_rsi": _finite_or_none(display_daily.iloc[opened_index]["rsi"]),
        "latest_close": float(display_daily.iloc[latest_index]["close"]),
        "latest_rsi": _finite_or_none(display_daily.iloc[latest_index]["rsi"]),
    }
    for horizon in HORIZONS:
        end_index = opened_index + horizon
        complete = end_index < len(display_daily)
        row[f"horizon_{horizon}_complete"] = complete
        if not complete:
            row[f"forward_return_{horizon}"] = None
            row[f"max_forward_return_{horizon}"] = None
            row[f"min_forward_return_{horizon}"] = None
            continue
        future = pd.to_numeric(
            display_daily.iloc[opened_index + 1:end_index + 1]["close"],
            errors="raise",
        )
        row[f"forward_return_{horizon}"] = (
            float(display_daily.iloc[end_index]["close"]) / opened_close - 1.0
        )
        row[f"max_forward_return_{horizon}"] = (
            float(future.max()) / opened_close - 1.0
        )
        row[f"min_forward_return_{horizon}"] = (
            float(future.min()) / opened_close - 1.0
        )
    return row


def _exact_daily_index(
    date_to_index: Mapping[pd.Timestamp, int],
    date: pd.Timestamp,
    warning_id: str,
    label: str,
) -> int:
    index = date_to_index.get(date)
    if index is None:
        raise ValidationError(
            f"warning {warning_id} {label} date {date:%Y-%m-%d} "
            "has no exact daily_features row"
        )
    return index


def _formal_divergence_count(
    signals: pd.DataFrame,
    display_start: pd.Timestamp,
    display_end: pd.Timestamp,
) -> int:
    if signals.empty or "signal_type" not in signals:
        return 0
    selected = signals.copy(deep=True)
    if "is_display_range" in selected:
        selected = selected.loc[selected["is_display_range"].astype(bool)]
    elif "decision_date" in selected:
        dates = pd.to_datetime(selected["decision_date"], errors="coerce")
        selected = selected.loc[dates.between(display_start, display_end)]
    return int(selected["signal_type"].isin(FORMAL_DIVERGENCE_VALUES).sum())


def _backtest_ineligible_reason(metadata: Mapping[str, Any]) -> str:
    if bool(metadata.get("backtest_eligible", False)):
        return ""
    if not bool(metadata.get("warmup_satisfied", False)):
        return (
            f"预热不足：实际 {metadata.get('warmup_trading_days_actual', 'unknown')} 日，"
            f"要求 {metadata.get('warmup_trading_days_requested', 'unknown')} 日"
        )
    if not bool(metadata.get("indicator_ready_on_display_start", False)):
        return "展示首日指标尚未就绪"
    return "分析结果未通过 backtest eligibility"


def _build_outcome_summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for status in STATUS_ORDER:
        status_rows = outcomes.loc[
            outcomes["as_of_status"] == status
        ] if not outcomes.empty else outcomes
        for horizon in HORIZONS:
            complete = (
                status_rows.loc[
                    status_rows[f"horizon_{horizon}_complete"].astype(bool)
                ]
                if not status_rows.empty
                else status_rows
            )
            rows.append({
                "as_of_status": status,
                "horizon_days": horizon,
                "warning_count": len(status_rows),
                "complete_horizon_count": len(complete),
                "median_forward_return": _median(
                    complete, f"forward_return_{horizon}"
                ),
                "median_max_forward_return": _median(
                    complete, f"max_forward_return_{horizon}"
                ),
                "median_min_forward_return": _median(
                    complete, f"min_forward_return_{horizon}"
                ),
            })
    return pd.DataFrame(rows, columns=OUTCOME_SUMMARY_COLUMNS)


def _median(frame: pd.DataFrame, column: str) -> float:
    if frame.empty:
        return np.nan
    return float(pd.to_numeric(frame[column], errors="coerce").median())


def _validate_manifest(manifest: pd.DataFrame) -> pd.DataFrame:
    required = ["symbol", "sample_group", "rationale"]
    missing = [column for column in required if column not in manifest]
    if missing:
        raise ValidationError(
            "manifest is missing columns: " + ", ".join(missing)
        )
    samples = manifest.loc[:, required].copy(deep=True)
    samples["symbol"] = samples["symbol"].astype(str).str.strip().str.upper()
    if samples.empty:
        raise ValidationError("manifest is empty")
    if samples["symbol"].duplicated().any():
        duplicate = samples.loc[samples["symbol"].duplicated(), "symbol"].iloc[0]
        raise ValidationError(f"manifest contains duplicate symbol: {duplicate}")
    return samples


def _failed_summary(
    *,
    symbol: str,
    name: str | None,
    sample_group: str,
    display_start_date: str,
    display_end_date: str,
    error: str,
    result: AnalysisResult | None = None,
) -> dict[str, object]:
    metadata = result.metadata if result is not None else {}
    return {
        "symbol": symbol,
        "name": name,
        "sample_group": sample_group,
        "display_start_date": display_start_date,
        "display_end_date": display_end_date,
        "calculation_start_date": metadata.get("calculation_start_date"),
        "calculation_end_date": metadata.get("calculation_end_date"),
        "input_checksum_sha256": metadata.get("input_checksum_sha256"),
        "display_bar_count": metadata.get("display_row_count"),
        "backtest_eligible": metadata.get("backtest_eligible"),
        "backtest_ineligible_reason": _backtest_ineligible_reason(metadata)
        if metadata
        else "",
        "formal_divergence_count": np.nan,
        "cohort_warning_count": np.nan,
        "carry_in_warning_count": np.nan,
        "opened_event_count": np.nan,
        "refreshed_event_count": np.nan,
        "escalated_event_count": np.nan,
        "cleared_event_count": np.nan,
        "invalidated_event_count": np.nan,
        "active_warning_count": np.nan,
        "escalated_warning_count": np.nan,
        "cleared_warning_count": np.nan,
        "invalidated_warning_count": np.nan,
        "contract_validation_passed": False,
        "error": error,
    }


def _representative_case_lines(
    outcomes: pd.DataFrame,
    *,
    chart_path_root: str,
) -> list[str]:
    if outcomes.empty:
        return ["- 未形成可审计的 cohort warning。"]
    lines: list[str] = []
    for status in STATUS_ORDER:
        selected = outcomes.loc[outcomes["as_of_status"] == status].head(2)
        if selected.empty:
            continue
        lines.extend(["", f"### {status}", ""])
        for row in selected.itertuples(index=False):
            path = f"{chart_path_root.rstrip('/')}/{row.symbol}/annotated_chart.png"
            lines.append(
                f"- `{row.symbol}` / `{row.warning_id}`：OPENED {row.opened_date}，"
                f"refresh {int(row.refresh_count)} 次，截止状态 {row.as_of_status}，"
                f"terminal reason {_display_value(row.terminal_end_reason)}，"
                f"escalation lead {_display_value(row.lead_to_escalation_trading_days)}；"
                f"5 日路径 {_path_text(row, 5)}，20 日路径 {_path_text(row, 20)}；"
                f"图表 `{path}`。"
            )
    return lines


def _anomaly_lines(
    sample_summary: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    failed_count: int,
) -> list[str]:
    lines = [
        (
            f"- 运行/合同异常：{failed_count} 个失败样本。"
            if failed_count
            else "- 运行/合同异常：未观察到。"
        )
    ]
    zero = sample_summary.loc[
        sample_summary["cohort_warning_count"].fillna(-1) == 0, "symbol"
    ].astype(str).tolist()
    lines.append(
        "- 无 cohort warning 的样本：" + (", ".join(zero) if zero else "无。")
    )
    if outcomes.empty:
        lines.append("- 生命周期与价格路径异常：没有 cohort warning 可供观察。")
        return lines
    max_duration = pd.to_numeric(
        outcomes["duration_trading_days"], errors="coerce"
    ).max()
    longest = outcomes.loc[
        pd.to_numeric(outcomes["duration_trading_days"], errors="coerce")
        == max_duration,
        ["symbol", "warning_id"],
    ]
    lines.append(
        f"- 最长观察生命周期为 {int(max_duration)} 个交易日："
        + ", ".join(
            f"{row.symbol}/{row.warning_id}"
            for row in longest.itertuples(index=False)
        )
        + "。"
    )
    max_refresh = int(
        pd.to_numeric(outcomes["refresh_count"], errors="coerce").max()
    )
    refreshed = outcomes.loc[
        pd.to_numeric(outcomes["refresh_count"], errors="coerce") == max_refresh,
        ["symbol", "warning_id"],
    ]
    lines.append(
        f"- 最高 refresh count 为 {max_refresh}："
        + ", ".join(
            f"{row.symbol}/{row.warning_id}"
            for row in refreshed.head(5).itertuples(index=False)
        )
        + ("（仅列前 5 个）。" if len(refreshed) > 5 else "。")
    )
    complete_20 = outcomes.loc[outcomes["horizon_20_complete"].astype(bool)]
    if not complete_20.empty:
        strongest = complete_20.sort_values(
            "max_forward_return_20", ascending=False, kind="mergesort"
        ).iloc[0]
        lines.append(
            f"- 20 日内继续上涨路径的最大观察值为 "
            f"{_percent_or_dash(strongest['max_forward_return_20'])}："
            f"{strongest['symbol']}/{strongest['warning_id']}；这只是路径观察，"
            "不是交易收益。"
        )
    return lines


def _warning_density_text(summary: pd.DataFrame) -> str:
    successful = summary.loc[summary["error"].astype(str) == ""]
    if successful.empty:
        return "没有成功样本可比较 warning 数量。"
    counts = pd.to_numeric(
        successful["cohort_warning_count"], errors="coerce"
    )
    maximum = counts.max()
    minimum = counts.min()
    high = successful.loc[counts == maximum, "symbol"].astype(str).tolist()
    low = successful.loc[counts == minimum, "symbol"].astype(str).tolist()
    zero = successful.loc[counts == 0, "symbol"].astype(str).tolist()
    text = (
        f"最多为 {int(maximum)}（{', '.join(high)}），"
        f"最少为 {int(minimum)}（{', '.join(low)}）"
    )
    if zero:
        text += f"；无 warning：{', '.join(zero)}"
    return text + "。"


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "（无数据）"
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append(
            "| "
            + " | ".join(_markdown_value(value) for value in row)
            + " |"
        )
    return "\n".join(lines)


def _markdown_value(value: object) -> str:
    if pd.isna(value) or str(value) == "":
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "是" if bool(value) else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("|", "\\|").replace("\n", " ")


def _value_counts(values: pd.Series) -> dict[str, int]:
    clean = values.dropna().astype(str)
    clean = clean.loc[clean.str.strip() != ""]
    return {str(key): int(value) for key, value in clean.value_counts().items()}


def _counts_text(counts: Mapping[str, int]) -> str:
    return " / ".join(f"{key} {value}" for key, value in counts.items())


def _path_text(row: object, horizon: int) -> str:
    if not bool(getattr(row, f"horizon_{horizon}_complete")):
        return "不完整"
    return (
        f"期末 {_percent_or_dash(getattr(row, f'forward_return_{horizon}'))}，"
        f"最大 {_percent_or_dash(getattr(row, f'max_forward_return_{horizon}'))}，"
        f"最小 {_percent_or_dash(getattr(row, f'min_forward_return_{horizon}'))}"
    )


def _percent_or_dash(value: object) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value):.2%}"


def _number_or_dash(value: object) -> str:
    if pd.isna(value):
        return "—"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def _display_value(value: object) -> str:
    if pd.isna(value) or str(value).strip() == "":
        return "—"
    return str(value)


def _optional_text(value: object) -> str | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    return None if pd.isna(value) else int(value)


def _finite_or_none(value: object) -> float | None:
    if pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None
