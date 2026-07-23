from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from rsi_exit.validation import (
    FORMAL_DIVERGENCE_VALUES,
    _normalized_event_frame,
    _validate_warning_contract,
)
from rsi_exit.warning_events import derive_warning_states


HORIZONS = (1, 3, 5, 10, 20)
LIFECYCLE_EVENTS = ("OPENED", "ESCALATED", "CLEARED", "INVALIDATED")
TERMINAL_EVENTS = {"ESCALATED", "CLEARED", "INVALIDATED"}

EVENT_OUTCOME_COLUMNS = [
    "symbol",
    "name",
    "sample_group",
    "warning_id",
    "lifecycle_event",
    "event_decision_date",
    "event_source_version",
    "ex_post_terminal_status",
    "terminal_end_reason",
    "linked_formal_signal_ref",
    "refresh_count_as_of_event",
    "latest_refresh_date_as_of_event",
    "event_close",
    "event_rsi",
    "action_date",
    "action_open",
    "action_close",
    "action_available",
]
for _horizon in HORIZONS:
    EVENT_OUTCOME_COLUMNS.extend([
        f"action_forward_close_return_{_horizon}",
        f"action_max_high_return_{_horizon}",
        f"action_min_low_return_{_horizon}",
        f"action_horizon_{_horizon}_complete",
    ])

OPENED_TO_ESCALATED_COLUMNS = [
    "symbol",
    "warning_id",
    "opened_date",
    "escalated_date",
    "lead_trading_days",
    "opened_close",
    "escalated_close",
    "escalated_action_date",
    "escalated_action_open",
    "opened_to_escalated_close_return",
    "opened_close_to_escalated_action_open_return",
    "refresh_count",
    "linked_formal_signal_ref",
]

FORMAL_LINKAGE_COLUMNS = [
    "symbol",
    "formal_signal_ref",
    "formal_decision_date",
    "formal_signal_type",
    "formal_canonical_peak_id",
    "formal_canonical_version",
    "formal_divergence_chain_id",
    "warning_id",
    "escalated_decision_date",
    "escalated_canonical_peak_id",
    "escalated_canonical_version",
    "escalated_divergence_chain_id",
    "linkage_status",
    "error",
]

ACTIONABILITY_SUMMARY_COLUMNS = [
    "lifecycle_event",
    "sample_group",
    "horizon_days",
    "event_count",
    "action_available_count",
    "complete_horizon_count",
    "median_action_forward_close_return",
    "median_action_max_high_return",
    "median_action_min_low_return",
    "p25_action_forward_close_return",
    "p75_action_forward_close_return",
]

SAMPLE_VERIFICATION_COLUMNS = [
    "symbol",
    "name",
    "sample_group",
    "input_checksum_sha256",
    "display_bar_count",
    "files_validation_passed",
    "schema_validation_passed",
    "checksum_validation_passed",
    "linkage_validation_passed",
    "error",
]

SIGNAL_LINKAGE_COLUMNS = [
    "decision_date",
    "signal_type",
    "signal_status",
    "current_canonical_peak_id",
    "current_canonical_version",
    "divergence_chain_id",
    "is_display_range",
]

PHASE4_SUMMARY_COLUMNS = [
    "symbol",
    "name",
    "sample_group",
    "display_start_date",
    "display_end_date",
    "input_checksum_sha256",
    "display_bar_count",
    "contract_validation_passed",
    "error",
]


class ActionabilityValidationError(ValueError):
    """Phase 4 output cannot support the requested action-time validation."""


@dataclass(frozen=True)
class SampleActionability:
    verification: dict[str, object]
    event_outcomes: pd.DataFrame
    opened_to_escalated: pd.DataFrame
    formal_warning_linkage: pd.DataFrame


@dataclass(frozen=True)
class ActionabilityBundle:
    sample_verification: pd.DataFrame
    event_outcomes: pd.DataFrame
    opened_to_escalated: pd.DataFrame
    formal_warning_linkage: pd.DataFrame
    event_actionability_summary: pd.DataFrame
    actionability_report: str

    @property
    def failed_count(self) -> int:
        if self.sample_verification.empty:
            return 0
        return int(
            self.sample_verification["error"].fillna("").astype(str).str.strip().ne(
                ""
            ).sum()
        )


def analyze_actionability_sample(
    *,
    symbol: str,
    name: str | None,
    sample_group: str,
    expected_checksum: str,
    expected_display_bar_count: int,
    display_start_date: str,
    display_end_date: str,
    daily_features: pd.DataFrame,
    warning_events: pd.DataFrame,
    signals: pd.DataFrame,
    rsi_audit: pd.DataFrame,
) -> SampleActionability:
    """Validate and describe one Phase 4 sample without mutating its inputs."""

    display_start = pd.Timestamp(display_start_date)
    display_end = pd.Timestamp(display_end_date)
    if display_start > display_end:
        raise ActionabilityValidationError(
            "display_start_date is after display_end_date"
        )
    daily = _normalized_daily(daily_features, display_start, display_end)
    if len(daily) != int(expected_display_bar_count):
        raise ActionabilityValidationError(
            f"display bar count mismatch: expected {expected_display_bar_count}, "
            f"found {len(daily)}"
        )
    events = _normalized_event_frame(warning_events)
    if not events.empty and not events["symbol"].astype(str).eq(symbol).all():
        raise ActionabilityValidationError(
            f"warning_events symbol mismatch for {symbol}"
        )
    normalized_signals = _normalized_signals(signals)
    _validate_checksum(rsi_audit, expected_checksum)

    models = _validate_warning_contract(events)
    states = derive_warning_states(
        models,
        as_of_date=display_end.strftime("%Y-%m-%d"),
    )
    _validate_event_display_flags(events, display_start, display_end)

    event_outcomes = _build_event_outcomes(
        symbol=symbol,
        name=name,
        sample_group=sample_group,
        events=events,
        states=states,
        daily=daily,
        display_start=display_start,
        display_end=display_end,
    )
    linkage = build_formal_warning_linkage(
        symbol=symbol,
        signals=normalized_signals,
        warning_events=events,
        display_start_date=display_start_date,
        display_end_date=display_end_date,
    )
    waiting = _build_opened_to_escalated(
        symbol=symbol,
        events=events,
        daily=daily,
        display_start=display_start,
        display_end=display_end,
    )
    linkage_errors = linkage.loc[
        linkage["linkage_status"] != "MATCHED", "linkage_status"
    ].astype(str).tolist()
    error = (
        "formal-warning linkage failed: " + ", ".join(linkage_errors)
        if linkage_errors
        else ""
    )
    verification = {
        "symbol": symbol,
        "name": name,
        "sample_group": sample_group,
        "input_checksum_sha256": expected_checksum,
        "display_bar_count": len(daily),
        "files_validation_passed": True,
        "schema_validation_passed": True,
        "checksum_validation_passed": True,
        "linkage_validation_passed": not linkage_errors,
        "error": error,
    }
    return SampleActionability(
        verification=verification,
        event_outcomes=event_outcomes,
        opened_to_escalated=waiting,
        formal_warning_linkage=linkage,
    )


def build_formal_warning_linkage(
    *,
    symbol: str,
    signals: pd.DataFrame,
    warning_events: pd.DataFrame,
    display_start_date: str,
    display_end_date: str,
) -> pd.DataFrame:
    """Reconcile every display-range formal divergence and ESCALATED event."""

    display_start = pd.Timestamp(display_start_date)
    display_end = pd.Timestamp(display_end_date)
    normalized_signals = _normalized_signals(signals)
    events = _normalized_event_frame(warning_events)

    signal_dates = pd.to_datetime(
        normalized_signals["decision_date"], errors="raise"
    )
    signal_display = _bool_series(
        normalized_signals["is_display_range"], "signals.is_display_range"
    )
    formal = normalized_signals.loc[
        signal_display
        & signal_dates.between(display_start, display_end)
        & normalized_signals["signal_status"].astype(str).eq("FORMAL")
        & normalized_signals["signal_type"].astype(str).isin(
            FORMAL_DIVERGENCE_VALUES
        )
    ].copy()
    formal["_decision_date"] = pd.to_datetime(
        formal["decision_date"], errors="raise"
    )
    formal["_formal_order"] = range(len(formal))
    formal["_formal_ref"] = pd.Series(
        (
            _formal_signal_ref(symbol, row)
            for _, row in formal.iterrows()
        ),
        index=formal.index,
        dtype=object,
    )

    if events.empty:
        escalated = events.copy()
        escalated["_decision_date"] = pd.Series(dtype="datetime64[ns]")
        escalated["_escalated_order"] = pd.Series(dtype=int)
    else:
        event_dates = pd.to_datetime(events["decision_date"], errors="raise")
        event_display = _bool_series(
            events["is_display_range"], "warning_events.is_display_range"
        )
        escalated = events.loc[
            event_display
            & event_dates.between(display_start, display_end)
            & events["lifecycle_event"].astype(str).eq("ESCALATED")
        ].copy()
        escalated["_decision_date"] = pd.to_datetime(
            escalated["decision_date"], errors="raise"
        )
        escalated["_escalated_order"] = range(len(escalated))
    escalated["_linked_ref"] = escalated["linked_formal_signal_ref"].map(
        _optional_text
    )

    rows: list[dict[str, object]] = []
    references = sorted(
        set(formal["_formal_ref"].astype(str))
        | set(escalated["_linked_ref"].dropna().astype(str))
    )
    warning_ref_counts = (
        escalated.dropna(subset=["_linked_ref"])
        .groupby("warning_id")["_linked_ref"]
        .nunique()
        .to_dict()
    )
    for reference in references:
        formal_rows = formal.loc[formal["_formal_ref"] == reference]
        escalated_rows = escalated.loc[escalated["_linked_ref"] == reference]
        if formal_rows.empty:
            for _, event in escalated_rows.iterrows():
                rows.append(_linkage_row(
                    symbol=symbol,
                    formal=None,
                    escalated=event,
                    status="ESCALATED_MISSING_FORMAL",
                    error="ESCALATED linked reference has no formal divergence",
                ))
            continue
        if escalated_rows.empty:
            for _, signal in formal_rows.iterrows():
                rows.append(_linkage_row(
                    symbol=symbol,
                    formal=signal,
                    escalated=None,
                    status="MISSING_ESCALATED",
                    error="formal divergence has no ESCALATED warning",
                ))
            continue

        for _, signal in formal_rows.iterrows():
            for _, event in escalated_rows.iterrows():
                if len(formal_rows) > 1 and len(escalated_rows) > 1:
                    status = "CONFLICT"
                    error = "multiple formal divergences and multiple ESCALATED events"
                elif len(formal_rows) > 1:
                    status = "MANY_TO_ONE"
                    error = "multiple formal divergences map to one ESCALATED event"
                elif len(escalated_rows) > 1:
                    status = "ONE_TO_MANY"
                    error = "one formal divergence maps to multiple ESCALATED events"
                elif warning_ref_counts.get(str(event["warning_id"]), 0) > 1:
                    status = "MANY_TO_ONE"
                    error = "multiple formal divergences map to one warning"
                else:
                    status, error = _linkage_field_status(signal, event)
                rows.append(_linkage_row(
                    symbol=symbol,
                    formal=signal,
                    escalated=event,
                    status=status,
                    error=error,
                ))

    unlinked = escalated.loc[escalated["_linked_ref"].isna()]
    for _, event in unlinked.iterrows():
        rows.append(_linkage_row(
            symbol=symbol,
            formal=None,
            escalated=event,
            status="ESCALATED_MISSING_FORMAL",
            error="ESCALATED event has no linked_formal_signal_ref",
        ))

    frame = pd.DataFrame(rows, columns=FORMAL_LINKAGE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            [
                "symbol",
                "formal_decision_date",
                "formal_signal_ref",
                "warning_id",
                "escalated_decision_date",
            ],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
    return frame


def build_actionability_summary(
    event_outcomes: pd.DataFrame,
    *,
    sample_groups: list[str],
) -> pd.DataFrame:
    """Aggregate action-open paths without using ex-post terminal status."""

    groups = ["ALL", *dict.fromkeys(str(group) for group in sample_groups)]
    rows: list[dict[str, object]] = []
    for lifecycle_event in LIFECYCLE_EVENTS:
        event_rows = event_outcomes.loc[
            event_outcomes["lifecycle_event"] == lifecycle_event
        ] if not event_outcomes.empty else event_outcomes
        for sample_group in groups:
            selected = (
                event_rows
                if sample_group == "ALL"
                else event_rows.loc[event_rows["sample_group"] == sample_group]
            )
            for horizon in HORIZONS:
                complete = (
                    selected.loc[
                        selected[
                            f"action_horizon_{horizon}_complete"
                        ].astype(bool)
                    ]
                    if not selected.empty
                    else selected
                )
                forward_column = f"action_forward_close_return_{horizon}"
                rows.append({
                    "lifecycle_event": lifecycle_event,
                    "sample_group": sample_group,
                    "horizon_days": horizon,
                    "event_count": len(selected),
                    "action_available_count": int(
                        selected["action_available"].astype(bool).sum()
                    ) if not selected.empty else 0,
                    "complete_horizon_count": len(complete),
                    "median_action_forward_close_return": _quantile(
                        complete, forward_column, 0.50
                    ),
                    "median_action_max_high_return": _quantile(
                        complete, f"action_max_high_return_{horizon}", 0.50
                    ),
                    "median_action_min_low_return": _quantile(
                        complete, f"action_min_low_return_{horizon}", 0.50
                    ),
                    "p25_action_forward_close_return": _quantile(
                        complete, forward_column, 0.25
                    ),
                    "p75_action_forward_close_return": _quantile(
                        complete, forward_column, 0.75
                    ),
                })
    return pd.DataFrame(rows, columns=ACTIONABILITY_SUMMARY_COLUMNS)


def load_phase4_actionability(
    phase4_output: str | Path,
) -> ActionabilityBundle:
    """Load the fixed Phase 4 output without contacting a data provider."""

    root = Path(phase4_output)
    summary_path = root / "sample_summary.csv"
    if not summary_path.is_file():
        raise ActionabilityValidationError(
            f"missing Phase 4 sample summary: {summary_path}"
        )
    sample_summary = pd.read_csv(summary_path, encoding="utf-8-sig")
    _validate_phase4_summary(sample_summary)
    expected_symbols = sample_summary["symbol"].astype(str).tolist()
    actual_directories = {
        path.name for path in root.iterdir() if path.is_dir()
    }
    if actual_directories != set(expected_symbols):
        missing = sorted(set(expected_symbols) - actual_directories)
        extra = sorted(actual_directories - set(expected_symbols))
        raise ActionabilityValidationError(
            f"Phase 4 symbol directories mismatch; missing={missing}, extra={extra}"
        )

    results: dict[str, SampleActionability] = {}
    errors: dict[str, str] = {}
    required_files = (
        "daily_features.csv",
        "warning_events.csv",
        "signals.csv",
        "rsi_audit.csv",
    )
    for row in sample_summary.itertuples(index=False):
        symbol = str(row.symbol)
        try:
            if str(row.error).strip() not in {"", "nan"}:
                raise ActionabilityValidationError(
                    f"Phase 4 sample already failed: {row.error}"
                )
            if not _truthy(row.contract_validation_passed):
                raise ActionabilityValidationError(
                    "Phase 4 contract_validation_passed is false"
                )
            directory = root / symbol
            paths = {name: directory / name for name in required_files}
            missing = [name for name, path in paths.items() if not path.is_file()]
            if missing:
                raise ActionabilityValidationError(
                    "missing Phase 4 files: " + ", ".join(missing)
                )
            results[symbol] = analyze_actionability_sample(
                symbol=symbol,
                name=_optional_text(row.name),
                sample_group=str(row.sample_group),
                expected_checksum=str(row.input_checksum_sha256),
                expected_display_bar_count=int(row.display_bar_count),
                display_start_date=str(row.display_start_date),
                display_end_date=str(row.display_end_date),
                daily_features=pd.read_csv(
                    paths["daily_features.csv"], encoding="utf-8-sig"
                ),
                warning_events=pd.read_csv(
                    paths["warning_events.csv"], encoding="utf-8-sig"
                ),
                signals=pd.read_csv(
                    paths["signals.csv"], encoding="utf-8-sig"
                ),
                rsi_audit=pd.read_csv(
                    paths["rsi_audit.csv"], encoding="utf-8-sig"
                ),
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            errors[symbol] = str(exc)
    return build_actionability_bundle(
        sample_summary,
        results,
        errors_by_symbol=errors,
        chart_path_root=root.as_posix(),
    )


def build_actionability_bundle(
    sample_summary: pd.DataFrame,
    results_by_symbol: Mapping[str, SampleActionability],
    *,
    errors_by_symbol: Mapping[str, str] | None = None,
    chart_path_root: str,
) -> ActionabilityBundle:
    errors = errors_by_symbol or {}
    verification_rows: list[dict[str, object]] = []
    outcomes: list[pd.DataFrame] = []
    waiting: list[pd.DataFrame] = []
    linkage: list[pd.DataFrame] = []
    for row in sample_summary.itertuples(index=False):
        symbol = str(row.symbol)
        result = results_by_symbol.get(symbol)
        if result is None:
            verification_rows.append(_failed_verification(
                symbol=symbol,
                name=_optional_text(row.name),
                sample_group=str(row.sample_group),
                checksum=_optional_text(row.input_checksum_sha256),
                display_bar_count=row.display_bar_count,
                error=errors.get(symbol, "no actionability result"),
            ))
            continue
        verification_rows.append(result.verification)
        if not result.formal_warning_linkage.empty:
            linkage.append(result.formal_warning_linkage)
        if str(result.verification["error"]).strip():
            continue
        outcomes.append(result.event_outcomes)
        waiting.append(result.opened_to_escalated)

    sample_verification = pd.DataFrame(
        verification_rows, columns=SAMPLE_VERIFICATION_COLUMNS
    )
    event_outcomes = _concat(outcomes, EVENT_OUTCOME_COLUMNS)
    if not event_outcomes.empty:
        event_outcomes["_event_order"] = event_outcomes[
            "lifecycle_event"
        ].map({value: index for index, value in enumerate(LIFECYCLE_EVENTS)})
        event_outcomes = event_outcomes.sort_values(
            [
                "_event_order",
                "symbol",
                "event_decision_date",
                "warning_id",
            ],
            kind="mergesort",
        ).drop(columns="_event_order").reset_index(drop=True)
    opened_to_escalated = _concat(waiting, OPENED_TO_ESCALATED_COLUMNS)
    if not opened_to_escalated.empty:
        opened_to_escalated = opened_to_escalated.sort_values(
            ["symbol", "opened_date", "warning_id"], kind="mergesort"
        ).reset_index(drop=True)
    formal_warning_linkage = _concat(linkage, FORMAL_LINKAGE_COLUMNS)
    if not formal_warning_linkage.empty:
        formal_warning_linkage = formal_warning_linkage.sort_values(
            [
                "symbol",
                "formal_decision_date",
                "formal_signal_ref",
                "warning_id",
            ],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
    sample_groups = sample_summary["sample_group"].astype(str).tolist()
    actionability_summary = build_actionability_summary(
        event_outcomes,
        sample_groups=sample_groups,
    )
    report = build_actionability_report(
        sample_verification,
        event_outcomes,
        opened_to_escalated,
        formal_warning_linkage,
        actionability_summary,
        display_start_date=str(sample_summary.iloc[0]["display_start_date"]),
        display_end_date=str(sample_summary.iloc[0]["display_end_date"]),
        chart_path_root=chart_path_root,
    )
    return ActionabilityBundle(
        sample_verification=sample_verification,
        event_outcomes=event_outcomes,
        opened_to_escalated=opened_to_escalated,
        formal_warning_linkage=formal_warning_linkage,
        event_actionability_summary=actionability_summary,
        actionability_report=report,
    )


def write_actionability_bundle(
    bundle: ActionabilityBundle,
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "event_outcomes": output / "event_outcomes.csv",
        "opened_to_escalated": output / "opened_to_escalated.csv",
        "formal_warning_linkage": output / "formal_warning_linkage.csv",
        "event_actionability_summary": (
            output / "event_actionability_summary.csv"
        ),
        "actionability_report": output / "actionability_report.md",
    }
    bundle.event_outcomes.to_csv(
        paths["event_outcomes"], index=False, encoding="utf-8-sig"
    )
    bundle.opened_to_escalated.to_csv(
        paths["opened_to_escalated"], index=False, encoding="utf-8-sig"
    )
    bundle.formal_warning_linkage.to_csv(
        paths["formal_warning_linkage"], index=False, encoding="utf-8-sig"
    )
    bundle.event_actionability_summary.to_csv(
        paths["event_actionability_summary"],
        index=False,
        encoding="utf-8-sig",
    )
    paths["actionability_report"].write_text(
        bundle.actionability_report, encoding="utf-8"
    )
    return paths


def build_actionability_report(
    sample_verification: pd.DataFrame,
    event_outcomes: pd.DataFrame,
    opened_to_escalated: pd.DataFrame,
    formal_warning_linkage: pd.DataFrame,
    actionability_summary: pd.DataFrame,
    *,
    display_start_date: str,
    display_end_date: str,
    chart_path_root: str,
) -> str:
    failed = sample_verification.loc[
        sample_verification["error"].fillna("").astype(str).str.strip().ne("")
    ]
    event_counts = {
        event: int((event_outcomes["lifecycle_event"] == event).sum())
        if not event_outcomes.empty
        else 0
        for event in LIFECYCLE_EVENTS
    }
    action_counts = {
        event: int(
            event_outcomes.loc[
                event_outcomes["lifecycle_event"] == event,
                "action_available",
            ].astype(bool).sum()
        )
        if not event_outcomes.empty
        else 0
        for event in LIFECYCLE_EVENTS
    }
    opened_5 = _summary_row(actionability_summary, "OPENED", "ALL", 5)
    escalated_5 = _summary_row(actionability_summary, "ESCALATED", "ALL", 5)
    invalidated_5 = _summary_row(actionability_summary, "INVALIDATED", "ALL", 5)
    cleared_5 = _summary_row(actionability_summary, "CLEARED", "ALL", 5)
    waiting_stats = _waiting_stats(opened_to_escalated)
    linkage_counts = _linkage_counts(
        formal_warning_linkage, event_counts["ESCALATED"]
    )
    overall_table = actionability_summary.loc[
        actionability_summary["sample_group"] == "ALL"
    ].copy()
    escalated_groups = actionability_summary.loc[
        actionability_summary["lifecycle_event"] == "ESCALATED"
    ].copy()
    opened_to_cleared = _opened_to_terminal_returns(
        event_outcomes, "CLEARED"
    )
    cases = _representative_case_lines(
        event_outcomes, chart_path_root=chart_path_root
    )
    failures = (
        [
            f"- `{row.symbol}`：{row.error}"
            for row in failed.loc[:, ["symbol", "error"]].itertuples(index=False)
        ]
        or ["- 无失败样本。"]
    )
    return "\n".join([
        "# rsi-exit v0.4 Phase 4.1 warning 事件时点可操作性验证",
        "",
        "## 技术摘要",
        "",
        (
            f"- **数据与合同：**{len(sample_verification) - len(failed)}/"
            f"{len(sample_verification)} 个样本通过文件、schema、checksum 与 "
            f"linkage 核对；失败 {len(failed)} 个。"
        ),
        (
            "- **事件规模：**"
            + " / ".join(
                f"{event} {event_counts[event]}（action date "
                f"{action_counts[event]}）"
                for event in LIFECYCLE_EVENTS
            )
            + "。"
        ),
        (
            "- **OPENED 无条件 5 日路径：**"
            + _summary_sentence(opened_5)
            + "；该统计没有按未来终态分组。"
        ),
        (
            "- **ESCALATED 后 5 日路径：**"
            + _summary_sentence(escalated_5)
            + "。"
        ),
        (
            "- **等待成本：**"
            + _waiting_sentence(waiting_stats)
            + "。"
        ),
        (
            f"- **正式背离 linkage：**正式背离 {linkage_counts['formal']}，"
            f"ESCALATED {linkage_counts['escalated']}，唯一匹配 "
            f"{linkage_counts['matched']}，缺失 {linkage_counts['missing']}，"
            f"冲突 {linkage_counts['conflict']}。"
        ),
        "",
        "这些结果是事件在收盘后已知、最早于下一真实交易日开盘行动的执行代理"
        "路径，不是策略收益，也不代表真实成交必然完成。",
        "",
        "## 事件时点、cohort 与指标定义",
        "",
        f"- 数据范围：Phase 4 固定 12 样本，展示区间 {display_start_date} 至 "
        f"{display_end_date}；不重新连接 AmazingData。",
        "- event decision date 当日收盘后事件才完整可知；action date 是其后"
        "下一条真实交易行，action open 是该日前复权开盘价。",
        "- OPENED、ESCALATED、CLEARED、INVALIDATED 每个实际展示区间事件一行；"
        "REFRESHED 不形成独立 action cohort，只保留截至事件可知的 refresh 审计。",
        "- `ex_post_terminal_status` 只用于事后诊断，不能进入 OPENED 当日决策"
        "或 OPENED 主汇总。",
        "- 1/3/5/10/20 日路径从 action open 起算；action day 是第 1 日，"
        "max 使用 high，min 使用 low，不完整 horizon 留空。",
        "",
        "## OPENED 的无条件路径不足以单独形成直接操作规则",
        "",
        "下表使用所有 OPENED，不按未来 ESCALATED、CLEARED 或 INVALIDATED 分组。"
        "这避免把事后终态泄漏回事件发生日。",
        "",
        _markdown_table(_report_summary_table(
            actionability_summary.loc[
                (actionability_summary["lifecycle_event"] == "OPENED")
                & (actionability_summary["sample_group"] == "ALL")
            ]
        )),
        "",
        (
            "**解释：**OPENED 5 日 action-open 路径"
            + _summary_sentence(opened_5)
            + "。分布同时包含后来升级和后来失效的 warning，描述性结果本身"
            "不足以证明 OPENED 具有可直接执行的统一价值。"
        ),
        "",
        "## ESCALATED 后的路径与板块差异",
        "",
        "ESCALATED 表示正式背离已经在事件日收盘后确认；下表从下一真实交易日"
        "开盘起算，包含总体和每个固定 sample group。",
        "",
        _markdown_table(_report_summary_table(escalated_groups)),
        "",
        (
            "**总体解释：**ESCALATED 5 日 action-open 路径"
            + _summary_sentence(escalated_5)
            + "。总体期末中位数没有呈现持续下跌，四分位区间和样本组差异也较宽；"
            "因此当前证据只显示短期下行暴露，不能证明统一、稳定的短期风险方向。"
            "样本组差异只用于描述稳健性，不用于个股优劣或参数选择。"
        ),
        "",
        "## 等待 OPENED 升级为 ESCALATED 的时间与价格空间",
        "",
        _markdown_table(waiting_stats),
        "",
        "等待成本同时报告 OPENED close 到 ESCALATED close，以及 OPENED close "
        "到 ESCALATED 后最早 action open；后者更接近真正可操作时点，但仍未"
        "计入涨跌停、滑点和交易成本。等待的中位价格成本为负，但 INVALIDATED "
        "事件数量接近 ESCALATED 且事件后路径分布宽，现有描述证据不足以证明在 "
        "OPENED 统一行动所节省的风险能覆盖机会成本。",
        "",
        "## INVALIDATED 后路径描述取消 warning 之后的市场状态",
        "",
        _markdown_table(_report_summary_table(
            actionability_summary.loc[
                (actionability_summary["lifecycle_event"] == "INVALIDATED")
                & (actionability_summary["sample_group"] == "ALL")
            ]
        )),
        "",
        (
            "**解释：**INVALIDATED 5 日 action-open 路径"
            + _summary_sentence(invalidated_5)
            + "。这可以支持研究取消 warning 后恢复普通观察，但不等于自动"
            "恢复仓位或生成买入动作。"
        ),
        "",
        "## CLEARED 前后的两段路径必须分开解释",
        "",
        (
            "OPENED close 到 CLEARED close 的事前等待段："
            + _distribution_sentence(opened_to_cleared)
            + "。"
        ),
        "",
        _markdown_table(_report_summary_table(
            actionability_summary.loc[
                (actionability_summary["lifecycle_event"] == "CLEARED")
                & (actionability_summary["sample_group"] == "ALL")
            ]
        )),
        "",
        (
            "**CLEARED 事件后的路径：**5 日 action-open 路径"
            + _summary_sentence(cleared_5)
            + "。不能再用从 OPENED 起算的 CLEARED 组收益解释 CLEARED 当日动作。"
        ),
        "",
        "## 正式背离与 ESCALATED linkage 逐条一致性",
        "",
        _markdown_table(pd.DataFrame([
            {"指标": "正式背离", "数量": linkage_counts["formal"]},
            {"指标": "ESCALATED", "数量": linkage_counts["escalated"]},
            {"指标": "唯一匹配", "数量": linkage_counts["matched"]},
            {"指标": "缺失匹配", "数量": linkage_counts["missing"]},
            {"指标": "冲突", "数量": linkage_counts["conflict"]},
        ])),
        "",
        "核对包含 linked ref、decision date、symbol、signal type、canonical "
        "ID/version 与 divergence chain；不是只比较总数。",
        "",
        "## 按 5 日路径选择的代表案例",
        "",
        "每个 lifecycle event 最多列出 action 后下跌较明显、上涨较明显和接近"
        "中位数各一个；`ex_post_terminal_status` 仅作事后标签。",
        "",
        *cases,
        "",
        "## 样本文件、schema 与 checksum 核对",
        "",
        _markdown_table(sample_verification.copy()),
        "",
        "### 失败明细",
        "",
        *failures,
        "",
        "## 限制、稳健性与不可越过的解释边界",
        "",
        "- action open 只是最早可执行价格代理；未验证真实成交量、涨跌停、"
        "滑点、交易成本或订单冲击。",
        "- 所有 horizon 严格截断在 Phase 4 展示结束日；近期事件的不完整路径"
        "不进入分位数。",
        "- OPENED 的主要统计没有使用未来终态；任何 ex-post 状态差异只可用于"
        "人工诊断，不能转化为实时信号。",
        "- 报告使用精确审计表而不新增图；代表案例只引用 Phase 4 既有单股图表。",
        "",
        "## Phase 5 决策门只记录证据，不实现规则",
        "",
        "- **OPENED：**应继续保持 `position_effect=NONE`；无条件描述性路径"
        "不足以支持统一仓位动作。",
        "- **ESCALATED：**具有唯一 formal linkage 和明确事件时点，值得进入"
        "下一阶段的仓位规则研究；现有分布尚未证明统一、稳定的短期风险方向，"
        "本阶段不实现规则。",
        "- **INVALIDATED：**值得研究“取消风险降级”是否合理；本报告不实现"
        "恢复仓位逻辑。",
        "- **CLEARED：**必须继续区分 OPENED 至 CLEARED 的既有路径与 CLEARED "
        "之后路径；业务含义仍需结合逐案审阅。",
        "- **人工审阅：**仍需重点检查极端 5 日案例、板块差异、action open "
        "可成交性和小样本 CLEARED。",
        "",
        "## 后续人工问题",
        "",
        "- OPENED 的无条件分布是否在更长时间窗和不同市场状态下保持稳定？",
        "- ESCALATED 的等待成本是否足以覆盖大量 INVALIDATED warning 的机会"
        "成本？",
        "- INVALIDATED 与 CLEARED 的恢复含义能否在不引入未来信息的前提下"
        "定义？",
        "",
        "## 全事件总体汇总",
        "",
        _markdown_table(_report_summary_table(overall_table)),
        "",
    ])


def _build_event_outcomes(
    *,
    symbol: str,
    name: str | None,
    sample_group: str,
    events: pd.DataFrame,
    states: Mapping[str, object],
    daily: pd.DataFrame,
    display_start: pd.Timestamp,
    display_end: pd.Timestamp,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=EVENT_OUTCOME_COLUMNS)
    dated = events.copy()
    dated["_date"] = pd.to_datetime(dated["decision_date"], errors="raise")
    dated["_row_order"] = range(len(dated))
    selected = dated.loc[
        dated["_date"].between(display_start, display_end)
        & _bool_series(dated["is_display_range"], "warning_events.is_display_range")
        & dated["lifecycle_event"].astype(str).isin(LIFECYCLE_EVENTS)
    ].copy()
    date_to_index = {
        date: index for index, date in enumerate(daily["_date"].tolist())
    }
    rows: list[dict[str, object]] = []
    for _, event in selected.iterrows():
        warning_id = str(event["warning_id"])
        event_date = pd.Timestamp(event["_date"])
        event_index = _exact_daily_index(
            date_to_index, event_date, warning_id, str(event["lifecycle_event"])
        )
        history = dated.loc[dated["warning_id"].astype(str) == warning_id].copy()
        history = history.sort_values(
            ["_date", "_row_order"], kind="mergesort"
        )
        known = history.loc[
            (history["_date"] < event_date)
            | (
                (history["_date"] == event_date)
                & (history["_row_order"] <= int(event["_row_order"]))
            )
        ]
        refreshes = known.loc[
            known["lifecycle_event"].astype(str) == "REFRESHED"
        ]
        action_index = (
            event_index + 1 if event_index + 1 < len(daily) else None
        )
        lifecycle_event = str(event["lifecycle_event"])
        status = states.get(warning_id)
        if status is None:
            raise ActionabilityValidationError(
                f"warning {warning_id} has no state at display cutoff"
            )
        row: dict[str, object] = {
            "symbol": symbol,
            "name": name,
            "sample_group": sample_group,
            "warning_id": warning_id,
            "lifecycle_event": lifecycle_event,
            "event_decision_date": event_date.strftime("%Y-%m-%d"),
            "event_source_version": int(event["source_version"]),
            "ex_post_terminal_status": getattr(status, "value", str(status)),
            "terminal_end_reason": (
                _optional_text(event["end_reason"])
                if lifecycle_event in TERMINAL_EVENTS
                else None
            ),
            "linked_formal_signal_ref": _optional_text(
                event["linked_formal_signal_ref"]
            ),
            "refresh_count_as_of_event": len(refreshes),
            "latest_refresh_date_as_of_event": (
                pd.Timestamp(refreshes.iloc[-1]["_date"]).strftime("%Y-%m-%d")
                if not refreshes.empty
                else None
            ),
            "event_close": _finite_value(
                daily.iloc[event_index]["close"],
                f"{warning_id} event close",
            ),
            "event_rsi": _finite_value(
                daily.iloc[event_index]["rsi"],
                f"{warning_id} event RSI",
            ),
            "action_date": (
                pd.Timestamp(daily.iloc[action_index]["_date"]).strftime(
                    "%Y-%m-%d"
                )
                if action_index is not None
                else None
            ),
            "action_open": (
                float(daily.iloc[action_index]["open"])
                if action_index is not None
                else None
            ),
            "action_close": (
                float(daily.iloc[action_index]["close"])
                if action_index is not None
                else None
            ),
            "action_available": action_index is not None,
        }
        _add_action_paths(row, daily, action_index)
        rows.append(row)
    return pd.DataFrame(rows, columns=EVENT_OUTCOME_COLUMNS)


def _build_opened_to_escalated(
    *,
    symbol: str,
    events: pd.DataFrame,
    daily: pd.DataFrame,
    display_start: pd.Timestamp,
    display_end: pd.Timestamp,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=OPENED_TO_ESCALATED_COLUMNS)
    dated = events.copy()
    dated["_date"] = pd.to_datetime(dated["decision_date"], errors="raise")
    dated["_row_order"] = range(len(dated))
    escalated = dated.loc[
        dated["_date"].between(display_start, display_end)
        & _bool_series(dated["is_display_range"], "warning_events.is_display_range")
        & dated["lifecycle_event"].astype(str).eq("ESCALATED")
    ]
    date_to_index = {
        date: index for index, date in enumerate(daily["_date"].tolist())
    }
    rows: list[dict[str, object]] = []
    for _, terminal in escalated.iterrows():
        warning_id = str(terminal["warning_id"])
        history = dated.loc[
            dated["warning_id"].astype(str) == warning_id
        ].sort_values(["_date", "_row_order"], kind="mergesort")
        opened = history.loc[history["lifecycle_event"].astype(str) == "OPENED"]
        if len(opened) != 1:
            raise ActionabilityValidationError(
                f"warning {warning_id} has {len(opened)} OPENED events"
            )
        opened_row = opened.iloc[0]
        opened_date = pd.Timestamp(opened_row["_date"])
        escalated_date = pd.Timestamp(terminal["_date"])
        opened_index = _exact_daily_index(
            date_to_index, opened_date, warning_id, "OPENED"
        )
        escalated_index = _exact_daily_index(
            date_to_index, escalated_date, warning_id, "ESCALATED"
        )
        action_index = (
            escalated_index + 1
            if escalated_index + 1 < len(daily)
            else None
        )
        opened_close = float(daily.iloc[opened_index]["close"])
        escalated_close = float(daily.iloc[escalated_index]["close"])
        action_open = (
            float(daily.iloc[action_index]["open"])
            if action_index is not None
            else None
        )
        refresh_count = int(
            (
                (history["lifecycle_event"].astype(str) == "REFRESHED")
                & (
                    (history["_date"] < escalated_date)
                    | (
                        (history["_date"] == escalated_date)
                        & (
                            history["_row_order"]
                            <= int(terminal["_row_order"])
                        )
                    )
                )
            ).sum()
        )
        rows.append({
            "symbol": symbol,
            "warning_id": warning_id,
            "opened_date": opened_date.strftime("%Y-%m-%d"),
            "escalated_date": escalated_date.strftime("%Y-%m-%d"),
            "lead_trading_days": escalated_index - opened_index,
            "opened_close": opened_close,
            "escalated_close": escalated_close,
            "escalated_action_date": (
                pd.Timestamp(daily.iloc[action_index]["_date"]).strftime(
                    "%Y-%m-%d"
                )
                if action_index is not None
                else None
            ),
            "escalated_action_open": action_open,
            "opened_to_escalated_close_return": (
                escalated_close / opened_close - 1.0
            ),
            "opened_close_to_escalated_action_open_return": (
                action_open / opened_close - 1.0
                if action_open is not None
                else None
            ),
            "refresh_count": refresh_count,
            "linked_formal_signal_ref": _optional_text(
                terminal["linked_formal_signal_ref"]
            ),
        })
    return pd.DataFrame(rows, columns=OPENED_TO_ESCALATED_COLUMNS)


def _add_action_paths(
    row: dict[str, object],
    daily: pd.DataFrame,
    action_index: int | None,
) -> None:
    for horizon in HORIZONS:
        complete = (
            action_index is not None
            and action_index + horizon <= len(daily)
        )
        row[f"action_horizon_{horizon}_complete"] = complete
        if not complete or action_index is None:
            row[f"action_forward_close_return_{horizon}"] = None
            row[f"action_max_high_return_{horizon}"] = None
            row[f"action_min_low_return_{horizon}"] = None
            continue
        action_open = float(daily.iloc[action_index]["open"])
        window = daily.iloc[action_index:action_index + horizon]
        row[f"action_forward_close_return_{horizon}"] = (
            float(window.iloc[-1]["close"]) / action_open - 1.0
        )
        row[f"action_max_high_return_{horizon}"] = (
            float(window["high"].max()) / action_open - 1.0
        )
        row[f"action_min_low_return_{horizon}"] = (
            float(window["low"].min()) / action_open - 1.0
        )


def _normalized_daily(
    frame: pd.DataFrame,
    display_start: pd.Timestamp,
    display_end: pd.Timestamp,
) -> pd.DataFrame:
    required = ["date", "open", "high", "low", "close", "rsi"]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ActionabilityValidationError(
            "daily_features schema is missing: " + ", ".join(missing)
        )
    daily = frame.loc[:, required].copy(deep=True)
    daily["_date"] = pd.to_datetime(daily["date"], errors="raise")
    if daily["_date"].duplicated().any():
        raise ActionabilityValidationError(
            "daily_features contains duplicate dates"
        )
    if not daily["_date"].is_monotonic_increasing:
        raise ActionabilityValidationError(
            "daily_features dates are not ascending"
        )
    for column in ("open", "high", "low", "close", "rsi"):
        daily[column] = pd.to_numeric(daily[column], errors="raise")
    display = daily.loc[
        daily["_date"].between(display_start, display_end)
    ].reset_index(drop=True)
    if display.empty:
        raise ActionabilityValidationError(
            "daily_features has no rows in the display range"
        )
    prices = display.loc[:, ["open", "high", "low", "close"]].to_numpy(
        dtype=float
    )
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ActionabilityValidationError(
            "daily_features contains invalid OHLC values"
        )
    return display


def _normalized_signals(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in SIGNAL_LINKAGE_COLUMNS if column not in frame]
    if missing:
        raise ActionabilityValidationError(
            "signals schema is missing: " + ", ".join(missing)
        )
    return frame.loc[:, SIGNAL_LINKAGE_COLUMNS].copy(deep=True)


def _validate_checksum(frame: pd.DataFrame, expected: str) -> None:
    if "input_checksum_sha256" not in frame:
        raise ActionabilityValidationError(
            "rsi_audit schema is missing input_checksum_sha256"
        )
    expected = str(expected).strip()
    values = {
        str(value).strip()
        for value in frame["input_checksum_sha256"].dropna().tolist()
        if str(value).strip()
    }
    if values != {expected}:
        raise ActionabilityValidationError(
            f"checksum mismatch: expected {expected}, found {sorted(values)}"
        )


def _validate_event_display_flags(
    events: pd.DataFrame,
    display_start: pd.Timestamp,
    display_end: pd.Timestamp,
) -> None:
    if events.empty:
        return
    dates = pd.to_datetime(events["decision_date"], errors="raise")
    actual = _bool_series(
        events["is_display_range"], "warning_events.is_display_range"
    )
    expected = dates.between(display_start, display_end)
    if not actual.equals(expected):
        raise ActionabilityValidationError(
            "warning_events is_display_range does not match decision dates"
        )


def _validate_phase4_summary(frame: pd.DataFrame) -> None:
    missing = [column for column in PHASE4_SUMMARY_COLUMNS if column not in frame]
    if missing:
        raise ActionabilityValidationError(
            "Phase 4 sample_summary schema is missing: " + ", ".join(missing)
        )
    if len(frame) != 12:
        raise ActionabilityValidationError(
            f"Phase 4 sample_summary must contain 12 symbols, found {len(frame)}"
        )
    symbols = frame["symbol"].astype(str)
    if symbols.duplicated().any():
        raise ActionabilityValidationError(
            f"Phase 4 sample_summary contains duplicate symbol: "
            f"{symbols.loc[symbols.duplicated()].iloc[0]}"
        )


def _formal_signal_ref(symbol: str, row: pd.Series) -> str:
    canonical_id = _required_text(
        row["current_canonical_peak_id"], "formal canonical ID"
    )
    canonical_version = _required_int(
        row["current_canonical_version"], "formal canonical version"
    )
    decision_date = pd.Timestamp(row["decision_date"]).strftime("%Y-%m-%d")
    chain_id = _required_text(
        row["divergence_chain_id"], "formal divergence chain"
    )
    signal_type = _required_text(row["signal_type"], "formal signal type")
    return (
        f"{symbol}|{signal_type}|{canonical_id}@v{canonical_version}|"
        f"{decision_date}|{chain_id}"
    )


def _linkage_field_status(
    formal: pd.Series,
    escalated: pd.Series,
) -> tuple[str, str]:
    errors: list[str] = []
    formal_date = pd.Timestamp(formal["_decision_date"])
    escalated_date = pd.Timestamp(escalated["_decision_date"])
    if formal_date != escalated_date:
        errors.append(
            f"decision date mismatch {formal_date:%Y-%m-%d}/"
            f"{escalated_date:%Y-%m-%d}"
        )
    comparisons = (
        (
            "canonical ID",
            _optional_text(formal["current_canonical_peak_id"]),
            _optional_text(escalated["source_canonical_peak_id"]),
        ),
        (
            "canonical version",
            _optional_int(formal["current_canonical_version"]),
            _optional_int(escalated["source_canonical_version"]),
        ),
        (
            "divergence chain",
            _optional_text(formal["divergence_chain_id"]),
            _optional_text(escalated["divergence_chain_id"]),
        ),
    )
    for label, formal_value, escalated_value in comparisons:
        if formal_value != escalated_value:
            errors.append(
                f"{label} mismatch {formal_value}/{escalated_value}"
            )
    if not errors:
        return "MATCHED", ""
    status = (
        "DATE_MISMATCH"
        if len(errors) == 1 and errors[0].startswith("decision date")
        else "FIELD_MISMATCH"
    )
    return status, "; ".join(errors)


def _linkage_row(
    *,
    symbol: str,
    formal: pd.Series | None,
    escalated: pd.Series | None,
    status: str,
    error: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "formal_signal_ref": (
            str(formal["_formal_ref"]) if formal is not None else None
        ),
        "formal_decision_date": (
            pd.Timestamp(formal["_decision_date"]).strftime("%Y-%m-%d")
            if formal is not None
            else None
        ),
        "formal_signal_type": (
            str(formal["signal_type"]) if formal is not None else None
        ),
        "formal_canonical_peak_id": (
            _optional_text(formal["current_canonical_peak_id"])
            if formal is not None
            else None
        ),
        "formal_canonical_version": (
            _optional_int(formal["current_canonical_version"])
            if formal is not None
            else None
        ),
        "formal_divergence_chain_id": (
            _optional_text(formal["divergence_chain_id"])
            if formal is not None
            else None
        ),
        "warning_id": (
            str(escalated["warning_id"])
            if escalated is not None
            else None
        ),
        "escalated_decision_date": (
            pd.Timestamp(escalated["_decision_date"]).strftime("%Y-%m-%d")
            if escalated is not None
            else None
        ),
        "escalated_canonical_peak_id": (
            _optional_text(escalated["source_canonical_peak_id"])
            if escalated is not None
            else None
        ),
        "escalated_canonical_version": (
            _optional_int(escalated["source_canonical_version"])
            if escalated is not None
            else None
        ),
        "escalated_divergence_chain_id": (
            _optional_text(escalated["divergence_chain_id"])
            if escalated is not None
            else None
        ),
        "linkage_status": status,
        "error": error,
    }


def _quantile(frame: pd.DataFrame, column: str, value: float) -> float:
    if frame.empty:
        return np.nan
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.quantile(value)) if not values.empty else np.nan


def _exact_daily_index(
    date_to_index: Mapping[pd.Timestamp, int],
    date: pd.Timestamp,
    warning_id: str,
    label: str,
) -> int:
    index = date_to_index.get(date)
    if index is None:
        raise ActionabilityValidationError(
            f"warning {warning_id} {label} date {date:%Y-%m-%d} "
            "has no exact daily_features row"
        )
    return index


def _bool_series(values: pd.Series, label: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.astype(bool)
    normalized = values.astype(str).str.strip().str.lower()
    allowed = {"true", "false"}
    invalid = normalized.loc[~normalized.isin(allowed)]
    if not invalid.empty:
        raise ActionabilityValidationError(
            f"{label} contains non-boolean value: {invalid.iloc[0]}"
        )
    return normalized.eq("true")


def _truthy(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() == "true"


def _finite_value(value: object, label: str) -> float:
    number = float(value)
    if not np.isfinite(number):
        raise ActionabilityValidationError(f"{label} is not finite")
    return number


def _required_text(value: object, label: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise ActionabilityValidationError(f"{label} is missing")
    return result


def _required_int(value: object, label: str) -> int:
    if pd.isna(value):
        raise ActionabilityValidationError(f"{label} is missing")
    return int(value)


def _optional_text(value: object) -> str | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    return None if pd.isna(value) else int(value)


def _concat(
    frames: list[pd.DataFrame],
    columns: list[str],
) -> pd.DataFrame:
    return (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=columns)
    )


def _failed_verification(
    *,
    symbol: str,
    name: str | None,
    sample_group: str,
    checksum: str | None,
    display_bar_count: object,
    error: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "name": name,
        "sample_group": sample_group,
        "input_checksum_sha256": checksum,
        "display_bar_count": display_bar_count,
        "files_validation_passed": False,
        "schema_validation_passed": False,
        "checksum_validation_passed": False,
        "linkage_validation_passed": False,
        "error": error,
    }


def _summary_row(
    summary: pd.DataFrame,
    lifecycle_event: str,
    sample_group: str,
    horizon: int,
) -> pd.Series | None:
    selected = summary.loc[
        (summary["lifecycle_event"] == lifecycle_event)
        & (summary["sample_group"] == sample_group)
        & (summary["horizon_days"] == horizon)
    ]
    return selected.iloc[0] if len(selected) == 1 else None


def _summary_sentence(row: pd.Series | None) -> str:
    if row is None or int(row["complete_horizon_count"]) == 0:
        return "无完整样本"
    return (
        f"完整样本 {int(row['complete_horizon_count'])}，期末中位数 "
        f"{_percent(row['median_action_forward_close_return'])}，"
        f"25%/75% 分位数 {_percent(row['p25_action_forward_close_return'])}/"
        f"{_percent(row['p75_action_forward_close_return'])}，"
        f"区间最大/最小中位数 "
        f"{_percent(row['median_action_max_high_return'])}/"
        f"{_percent(row['median_action_min_low_return'])}"
    )


def _report_summary_table(frame: pd.DataFrame) -> pd.DataFrame:
    selected = frame.loc[:, ACTIONABILITY_SUMMARY_COLUMNS].copy()
    for column in (
        "median_action_forward_close_return",
        "median_action_max_high_return",
        "median_action_min_low_return",
        "p25_action_forward_close_return",
        "p75_action_forward_close_return",
    ):
        selected[column] = selected[column].map(_percent)
    selected.columns = [
        "事件",
        "样本组",
        "交易日",
        "事件数",
        "action date 可用",
        "完整样本",
        "期末中位数",
        "最大中位数",
        "最小中位数",
        "期末 P25",
        "期末 P75",
    ]
    return selected


def _waiting_stats(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, column, percentage in (
        ("lead trading days", "lead_trading_days", False),
        (
            "OPENED close → ESCALATED close",
            "opened_to_escalated_close_return",
            True,
        ),
        (
            "OPENED close → ESCALATED action open",
            "opened_close_to_escalated_action_open_return",
            True,
        ),
    ):
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        rows.append({
            "指标": label,
            "样本数": len(values),
            "中位数": (
                _percent(values.median())
                if percentage and not values.empty
                else _number(values.median())
            ),
            "P25": (
                _percent(values.quantile(0.25))
                if percentage and not values.empty
                else _number(values.quantile(0.25))
            ),
            "P75": (
                _percent(values.quantile(0.75))
                if percentage and not values.empty
                else _number(values.quantile(0.75))
            ),
            "范围": (
                f"{_percent(values.min())} 至 {_percent(values.max())}"
                if percentage and not values.empty
                else (
                    f"{_number(values.min())} 至 {_number(values.max())}"
                    if not values.empty
                    else "—"
                )
            ),
        })
    return pd.DataFrame(rows)


def _waiting_sentence(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无 ESCALATED 样本"
    lead = frame.iloc[0]
    close = frame.iloc[1]
    action = frame.iloc[2]
    return (
        f"lead 中位数 {lead['中位数']} 个交易日；OPENED close 到 "
        f"ESCALATED close 中位数 {close['中位数']}，到最早 action open "
        f"中位数 {action['中位数']}"
    )


def _opened_to_terminal_returns(
    outcomes: pd.DataFrame,
    lifecycle_event: str,
) -> pd.Series:
    if outcomes.empty:
        return pd.Series(dtype=float)
    opened = outcomes.loc[
        outcomes["lifecycle_event"] == "OPENED",
        ["symbol", "warning_id", "event_close"],
    ].rename(columns={"event_close": "opened_close"})
    terminal = outcomes.loc[
        outcomes["lifecycle_event"] == lifecycle_event,
        ["symbol", "warning_id", "event_close"],
    ].rename(columns={"event_close": "terminal_close"})
    joined = terminal.merge(
        opened,
        on=["symbol", "warning_id"],
        how="inner",
        validate="one_to_one",
    )
    return joined["terminal_close"] / joined["opened_close"] - 1.0


def _distribution_sentence(values: pd.Series) -> str:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return "无可计算样本"
    return (
        f"样本 {len(clean)}，中位数 {_percent(clean.median())}，"
        f"P25/P75 {_percent(clean.quantile(0.25))}/"
        f"{_percent(clean.quantile(0.75))}，范围 "
        f"{_percent(clean.min())} 至 {_percent(clean.max())}"
    )


def _linkage_counts(
    linkage: pd.DataFrame,
    escalated_count: int,
) -> dict[str, int]:
    if linkage.empty:
        return {
            "formal": 0,
            "escalated": escalated_count,
            "matched": 0,
            "missing": escalated_count,
            "conflict": 0,
        }
    formal = linkage["formal_signal_ref"].dropna().astype(str).nunique()
    matched = linkage.loc[
        linkage["linkage_status"] == "MATCHED", "formal_signal_ref"
    ].dropna().astype(str).nunique()
    missing_statuses = {"MISSING_ESCALATED", "ESCALATED_MISSING_FORMAL"}
    missing = int(linkage["linkage_status"].isin(missing_statuses).sum())
    conflict = int(
        (~linkage["linkage_status"].isin({"MATCHED", *missing_statuses})).sum()
    )
    return {
        "formal": formal,
        "escalated": escalated_count,
        "matched": matched,
        "missing": missing,
        "conflict": conflict,
    }


def _representative_case_lines(
    outcomes: pd.DataFrame,
    *,
    chart_path_root: str,
) -> list[str]:
    if outcomes.empty:
        return ["- 无可选择案例。"]
    lines: list[str] = []
    for lifecycle_event in LIFECYCLE_EVENTS:
        selected = outcomes.loc[
            (outcomes["lifecycle_event"] == lifecycle_event)
            & outcomes["action_horizon_5_complete"].astype(bool)
        ].copy()
        if selected.empty:
            continue
        selected["_return"] = pd.to_numeric(
            selected["action_forward_close_return_5"], errors="coerce"
        )
        selected = selected.dropna(subset=["_return"]).sort_values(
            ["_return", "symbol", "event_decision_date", "warning_id"],
            kind="mergesort",
        )
        if selected.empty:
            continue
        median = float(selected["_return"].median())
        candidates = [
            ("下跌较明显", selected.iloc[0]),
            ("上涨较明显", selected.iloc[-1]),
            (
                "接近中位数",
                selected.assign(
                    _distance=(selected["_return"] - median).abs()
                ).sort_values(
                    [
                        "_distance",
                        "symbol",
                        "event_decision_date",
                        "warning_id",
                    ],
                    kind="mergesort",
                ).iloc[0],
            ),
        ]
        lines.extend(["", f"### {lifecycle_event}", ""])
        used: set[tuple[str, str, str]] = set()
        for label, row in candidates:
            identity = (
                str(row["symbol"]),
                str(row["warning_id"]),
                str(row["event_decision_date"]),
            )
            if identity in used:
                continue
            used.add(identity)
            chart = (
                f"{chart_path_root.rstrip('/')}/{row['symbol']}/"
                "annotated_chart.png"
            )
            lines.append(
                f"- **{label}** `{row['symbol']}` / `{row['warning_id']}`："
                f"event {row['event_decision_date']}，action {row['action_date']}，"
                f"5 日期末 {_percent(row['_return'])}，事后终态 "
                f"{row['ex_post_terminal_status']}；图表 `{chart}`。"
            )
    return lines or ["- 无可选择案例。"]


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


def _percent(value: object) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value):.2%}"


def _number(value: object) -> str:
    if pd.isna(value):
        return "—"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"
