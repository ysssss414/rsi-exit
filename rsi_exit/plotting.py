from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from rsi_exit.config import RsiExitConfig
from rsi_exit.models import SignalType
from rsi_exit.pipeline import AnalysisResult


SIGNAL_STYLE = {
    SignalType.TREND_STRENGTHENING.value: ("^", "TS"),
    SignalType.BEARISH_DIVERGENCE.value: ("v", "DIV"),
    SignalType.LOWER_HIGH_WEAK_REBOUND.value: ("X", "WR"),
    SignalType.LOWER_PRICE_RSI_FLAT.value: ("D", "FLAT"),
    SignalType.LOWER_PRICE_RSI_IMPROVING.value: ("s", "RI"),
    SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value: ("v", "NHD"),
    SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value: ("P", "NRTD"),
    SignalType.NON_COMPARABLE_PEAK.value: ("x", "NC"),
    SignalType.INTRADAY_POTENTIAL_RETEST.value: ("1", "IPR"),
    SignalType.DIVERGENCE_FORMING.value: ("+", "FORM"),
}

FORMAL_DIVERGENCE_VALUES = {
    SignalType.BEARISH_DIVERGENCE.value,
    SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
    SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
}

WARNING_LIFECYCLE_STYLE = {
    "OPENED": ("o", "tab:orange", "Warning opened"),
    "REFRESHED": (">", "tab:blue", "Warning active latest"),
    "ESCALATED": ("*", "tab:red", "Warning escalated"),
    "CLEARED": ("P", "tab:green", "Warning cleared"),
    "INVALIDATED": ("X", "tab:gray", "Warning invalidated"),
}


def signal_threshold_label(confirm_rsi: float, *, life_level: float) -> str:
    operator = "<" if float(confirm_rsi) < float(life_level) else ">="
    return f"{operator}{float(life_level):g}"


def price_axis_label(adjust: str | None) -> str:
    normalized = str(adjust or "").strip().lower()
    if normalized == "forward":
        return "Forward-adjusted price"
    if normalized in {"raw", "none"}:
        return "Raw price"
    return "Price"


def create_annotated_chart(
    result: AnalysisResult,
    path: str | Path,
    *,
    config: RsiExitConfig | None = None,
) -> Path:
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    daily = result.daily_features.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    peaks = result.canonical_peaks.copy()
    if not peaks.empty:
        peaks["peak_date"] = pd.to_datetime(peaks["peak_date"])
        peaks["confirm_date"] = pd.to_datetime(peaks["confirm_date"])
        peaks = peaks.loc[
            peaks["confirm_date"].between(daily["date"].min(), daily["date"].max())
        ].copy()
    signals = result.signals.copy()
    if not signals.empty:
        if "is_display_range" in signals:
            signals = signals.loc[signals["is_display_range"].astype(bool)].copy()
        signals["signal_date"] = pd.to_datetime(signals["signal_date"])
        signals["previous_peak_date"] = pd.to_datetime(signals["previous_peak_date"])
        forming_mask = signals["signal_type"] == SignalType.DIVERGENCE_FORMING.value
        signals = pd.concat([
            signals.loc[~forming_mask],
            signals.loc[forming_mask].drop_duplicates("candidate_peak_id", keep="first"),
        ]).sort_values("signal_date")

    candidates = result.peaks.copy()
    if not candidates.empty:
        candidates["peak_date"] = pd.to_datetime(candidates["peak_date"])
        candidates["confirm_date"] = pd.to_datetime(candidates["confirm_date"])
        candidates = candidates.loc[
            candidates["confirm_date"].between(daily["date"].min(), daily["date"].max())
        ]

    fig, (price_ax, rsi_ax) = plt.subplots(
        2,
        1,
        figsize=(16, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [2.1, 1]},
        constrained_layout=True,
    )
    ma_period = int(result.metadata["ma_period"])
    configured_levels = (
        config.values["levels"] if config is not None else result.metadata["rsi_levels"]
    )
    life_level = float(configured_levels["life"])
    price_ax.plot(daily["date"], daily["close"], linewidth=1.6, label="Close")
    price_ax.plot(daily["date"], daily["ma"], linestyle="--", linewidth=1.2, label=f"MA{ma_period}")

    if not candidates.empty:
        price_ax.scatter(
            candidates["peak_date"], candidates["peak_close"], marker=".",
            color="0.55", s=22, label="Candidate peak", zorder=3,
        )

    if not peaks.empty:
        representatives = peaks
        price_ax.scatter(
            representatives["peak_date"],
            representatives["peak_close"],
            marker="o",
            facecolors="none",
            edgecolors="black",
            s=60,
            label="Confirmed peak (peak date)",
            zorder=4,
        )
        rsi_ax.scatter(
            representatives["peak_date"],
            representatives["peak_rsi"],
            marker="o",
            facecolors="none",
            edgecolors="black",
            s=50,
            label="RSI peak",
            zorder=4,
        )
        for _, peak in representatives.iterrows():
            label = f"{peak['canonical_peak_id']}@v{int(peak['canonical_version'])}"
            price_ax.annotate(
                label,
                (peak["peak_date"], peak["peak_close"]),
                xytext=(0, 8),
                textcoords="offset points",
                fontsize=8,
                ha="center",
            )
            rsi_ax.annotate(
                label,
                (peak["peak_date"], peak["peak_rsi"]),
                xytext=(0, 7),
                textcoords="offset points",
                fontsize=7,
                ha="center",
            )

        if "structural_eligible" in representatives:
            structural = representatives.loc[
                representatives["structural_eligible"].fillna(False).astype(bool)
            ]
            if not structural.empty:
                price_ax.scatter(
                    structural["peak_date"], structural["peak_close"], marker="s",
                    facecolors="none", edgecolors="tab:purple", s=95,
                    label="Structural peak", zorder=5,
                )
                rsi_ax.scatter(
                    structural["peak_date"], structural["peak_rsi"], marker="s",
                    facecolors="none", edgecolors="tab:purple", s=80,
                    label="Structural peak RSI", zorder=5,
                )

    for signal_type, (marker, short_label) in SIGNAL_STYLE.items():
        subset = signals.loc[signals["signal_type"] == signal_type]
        if subset.empty:
            continue
        price_y = subset["signal_date"].map(
            daily.set_index("date")["close"].to_dict()
        )
        rsi_y = subset["signal_date"].map(
            daily.set_index("date")["rsi"].to_dict()
        )
        event_label = "snapshot" if signal_type == SignalType.DIVERGENCE_FORMING.value else "confirmation"
        price_ax.scatter(
            subset["signal_date"], price_y, marker=marker, s=85,
            label=f"{short_label} {event_label}", zorder=5
        )
        rsi_ax.scatter(
            subset["signal_date"], rsi_y, marker=marker, s=70,
            label=f"{short_label} {event_label}", zorder=5
        )
        for row_index, (_, signal) in enumerate(subset.iterrows()):
            count = int(signal["divergence_count"])
            suffix = str(count) if signal_type in FORMAL_DIVERGENCE_VALUES else ""
            threshold = signal_threshold_label(signal["confirm_rsi"], life_level=life_level)
            text = f"{short_label}{suffix} confirm {threshold}"
            if signal_type in {
                *FORMAL_DIVERGENCE_VALUES,
            }:
                price_ax.annotate(
                    text,
                    (signal["signal_date"], price_y.loc[signal.name]),
                    xytext=(5, -18 - 12 * (row_index % 2)),
                    textcoords="offset points",
                    fontsize=8,
                    arrowprops={"arrowstyle": "->", "lw": 0.7},
                )

    divergence = signals.loc[signals["signal_type"].isin(FORMAL_DIVERGENCE_VALUES)]
    for _, signal in divergence.iterrows():
        if pd.isna(signal["previous_peak_date"]):
            continue
        price_ax.plot(
            [signal["previous_peak_date"], pd.Timestamp(signal["current_peak_date"])],
            [signal["previous_peak_close"], signal["current_peak_close"]],
            linestyle=":", linewidth=1.1,
        )
        rsi_ax.plot(
            [signal["previous_peak_date"], pd.Timestamp(signal["current_peak_date"])],
            [signal["previous_peak_rsi"], signal["current_peak_rsi"]],
            linestyle=":", linewidth=1.1,
        )

    if not signals.empty:
        anchors = signals.drop_duplicates(
            ["momentum_anchor_date", "momentum_anchor_rsi"]
        ).copy()
        anchors["momentum_anchor_date"] = pd.to_datetime(anchors["momentum_anchor_date"])
        rsi_ax.scatter(
            anchors["momentum_anchor_date"],
            anchors["momentum_anchor_rsi"],
            marker="*", s=130, edgecolors="black", linewidths=0.5,
            label="Momentum anchor", zorder=6,
        )

    warning_points = _warning_lifecycle_plot_points(
        result.warning_events,
        daily,
        display_start_date=result.metadata["display_start_date"],
        display_end_date=result.metadata["display_end_date"],
    )
    for lifecycle_event, (marker, color, label) in (
        WARNING_LIFECYCLE_STYLE.items()
    ):
        if warning_points.empty:
            break
        subset = warning_points.loc[
            warning_points["lifecycle_event"] == lifecycle_event
        ]
        if subset.empty:
            continue
        scatter_options: dict[str, object] = {
            "marker": marker,
            "s": 82,
            "label": label,
            "zorder": 7,
        }
        if lifecycle_event == "OPENED":
            scatter_options.update({
                "facecolors": "none",
                "edgecolors": color,
                "linewidths": 1.4,
            })
        else:
            scatter_options["color"] = color
        rsi_ax.scatter(
            pd.to_datetime(subset["decision_date"]),
            subset["plot_rsi"],
            **scatter_options,
        )

    rsi_period = int(result.metadata["rsi_period"])
    rsi_ax.plot(daily["date"], daily["rsi"], linewidth=1.4, label=f"RSI{rsi_period} (CN SMA)")
    configured_lines = (
        config.values["chart"]["rsi_lines"]
        if config is not None
        else [configured_levels[key] for key in ("strong", "life", "neutral", "weak")]
    )
    styles = ("--", "-.", ":", ":")
    for index, level in enumerate(configured_lines):
        style = styles[index % len(styles)]
        rsi_ax.axhline(level, linestyle=style, linewidth=0.9, label=f"RSI {level}")
    rsi_ax.set_ylim(0, 105)
    rsi_ax.set_ylabel(f"RSI{rsi_period}")
    price_ax.set_ylabel(price_axis_label(result.metadata.get("adjust")))
    price_ax.set_title(f"{result.symbol} RSI Exit Signal Recognizer {result.metadata.get('config_version', 'v0.2')}")
    price_ax.grid(alpha=0.22)
    rsi_ax.grid(alpha=0.22)
    price_ax.legend(loc="best", fontsize=8, ncol=2)
    rsi_ax.legend(loc="best", fontsize=8, ncol=3)
    rsi_ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    rsi_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    plt.setp(rsi_ax.get_xticklabels(), rotation=35, ha="right")
    fig.savefig(output, dpi=170)
    plt.close(fig)
    return output


def _select_warning_lifecycle_events(
    warning_events: pd.DataFrame,
    *,
    display_start_date: object,
    display_end_date: object,
) -> pd.DataFrame:
    """Select at most the display OPENED and latest event per warning."""

    events = warning_events.copy(deep=True)
    if events.empty:
        return events
    display_start = pd.Timestamp(display_start_date)
    display_end = pd.Timestamp(display_end_date)
    events["_event_order"] = range(len(events))
    events["_decision_timestamp"] = pd.to_datetime(events["decision_date"])
    events = events.loc[events["_decision_timestamp"] <= display_end]
    in_display = events.loc[
        events["_decision_timestamp"].between(display_start, display_end)
    ]
    warning_ids = set(in_display["warning_id"])
    eligible = events.loc[events["warning_id"].isin(warning_ids)].sort_values(
        [
            "_decision_timestamp",
            "warning_id",
            "_event_order",
            "source_version",
        ],
        kind="mergesort",
    )

    selected_rows: list[pd.Series] = []
    for warning_id in sorted(warning_ids):
        history = eligible.loc[eligible["warning_id"] == warning_id]
        opened = history.loc[
            (history["lifecycle_event"] == "OPENED")
            & history["_decision_timestamp"].between(display_start, display_end)
        ]
        opened_event_id: object | None = None
        if not opened.empty:
            opened_row = opened.iloc[0]
            opened_event_id = opened_row["warning_event_id"]
            selected_rows.append(opened_row)
        latest = history.iloc[-1]
        if opened_event_id != latest["warning_event_id"]:
            selected_rows.append(latest)

    if not selected_rows:
        return warning_events.iloc[0:0].copy()
    selected = pd.DataFrame(selected_rows).drop_duplicates(
        "warning_event_id",
        keep="first",
    ).sort_values(
        [
            "_decision_timestamp",
            "warning_id",
            "_event_order",
            "source_version",
        ],
        kind="mergesort",
    )
    return selected.drop(
        columns=["_event_order", "_decision_timestamp"]
    ).reset_index(drop=True)


def _warning_lifecycle_plot_points(
    warning_events: pd.DataFrame,
    daily_features: pd.DataFrame,
    *,
    display_start_date: object,
    display_end_date: object,
) -> pd.DataFrame:
    """Map selected warning events to same-day RSI without substitution."""

    selected = _select_warning_lifecycle_events(
        warning_events,
        display_start_date=display_start_date,
        display_end_date=display_end_date,
    )
    if selected.empty:
        output = selected.copy()
        output["plot_rsi"] = pd.Series(dtype=float)
        return output
    daily = daily_features.loc[:, ["date", "rsi"]].copy(deep=True)
    daily["_date_timestamp"] = pd.to_datetime(daily["date"])
    rsi_by_date = daily.set_index("_date_timestamp")["rsi"].to_dict()
    output = selected.copy(deep=True)
    output["plot_rsi"] = pd.to_datetime(output["decision_date"]).map(
        rsi_by_date
    )
    return output.loc[output["plot_rsi"].notna()].reset_index(drop=True)


def _effective_representatives(peaks: pd.DataFrame) -> pd.DataFrame:
    """Return the latest confirmed representative for each merged swing."""
    representatives: dict[str, pd.Series] = {}
    for _, row in peaks.iterrows():
        if bool(row["is_independent_peak"]):
            canonical_id = str(row["peak_id"])
            chosen = row.copy()
            chosen["canonical_peak_id"] = canonical_id
            representatives[canonical_id] = chosen
        elif bool(row["canonical_updated"]):
            canonical_id = str(row["merged_into_peak_id"])
            chosen = row.copy()
            chosen["canonical_peak_id"] = canonical_id
            representatives[canonical_id] = chosen
    return pd.DataFrame(representatives.values()).sort_values("peak_date")
