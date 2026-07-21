from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from rsi_exit.models import SignalType
from rsi_exit.pipeline import AnalysisResult


SIGNAL_STYLE = {
    SignalType.TREND_STRENGTHENING.value: ("^", "TS"),
    SignalType.BEARISH_DIVERGENCE.value: ("v", "DIV"),
    SignalType.LOWER_HIGH_WEAK_REBOUND.value: ("X", "WR"),
    SignalType.LOWER_PRICE_RSI_IMPROVING.value: ("s", "RI"),
}


def create_annotated_chart(result: AnalysisResult, path: str | Path) -> Path:
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    daily = result.daily_features.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    peaks = result.peaks.copy()
    if not peaks.empty:
        peaks["peak_date"] = pd.to_datetime(peaks["peak_date"])
        peaks["confirm_date"] = pd.to_datetime(peaks["confirm_date"])
    signals = result.signals.copy()
    if not signals.empty:
        signals["signal_date"] = pd.to_datetime(signals["signal_date"])
        signals["previous_peak_date"] = pd.to_datetime(signals["previous_peak_date"])

    fig, (price_ax, rsi_ax) = plt.subplots(
        2,
        1,
        figsize=(16, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [2.1, 1]},
        constrained_layout=True,
    )
    price_ax.plot(daily["date"], daily["close"], linewidth=1.6, label="Close")
    price_ax.plot(daily["date"], daily["ma20"], linestyle="--", linewidth=1.2, label="MA20")

    if not peaks.empty:
        representatives = _effective_representatives(peaks)
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
            label = str(peak["canonical_peak_id"])
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

    for signal_type, (marker, short_label) in SIGNAL_STYLE.items():
        subset = signals.loc[signals["signal_type"] == signal_type]
        if subset.empty:
            continue
        price_y = subset["signal_date"].map(
            daily.set_index("date")["close"].to_dict()
        )
        rsi_y = subset["signal_date"].map(
            daily.set_index("date")["rsi14"].to_dict()
        )
        price_ax.scatter(
            subset["signal_date"], price_y, marker=marker, s=85,
            label=f"{short_label} confirmation", zorder=5
        )
        rsi_ax.scatter(
            subset["signal_date"], rsi_y, marker=marker, s=70,
            label=f"{short_label} confirmation", zorder=5
        )
        for row_index, (_, signal) in enumerate(subset.iterrows()):
            count = int(signal["divergence_count"])
            suffix = str(count) if signal_type == SignalType.BEARISH_DIVERGENCE.value else ""
            below = " <60" if float(signal["confirm_rsi"]) < 60 else " >=60"
            text = f"{short_label}{suffix} confirm{below}"
            if signal_type in {
                SignalType.BEARISH_DIVERGENCE.value,
                SignalType.LOWER_HIGH_WEAK_REBOUND.value,
            }:
                price_ax.annotate(
                    text,
                    (signal["signal_date"], price_y.loc[signal.name]),
                    xytext=(5, -18 - 12 * (row_index % 2)),
                    textcoords="offset points",
                    fontsize=8,
                    arrowprops={"arrowstyle": "->", "lw": 0.7},
                )

    divergence = signals.loc[
        signals["signal_type"] == SignalType.BEARISH_DIVERGENCE.value
    ]
    for _, signal in divergence.iterrows():
        current_peak = representatives.loc[
            representatives["canonical_peak_id"] == signal["peak_id"]
        ]
        if current_peak.empty or pd.isna(signal["previous_peak_date"]):
            continue
        current = current_peak.iloc[0]
        price_ax.plot(
            [signal["previous_peak_date"], current["peak_date"]],
            [signal["previous_peak_close"], current["peak_close"]],
            linestyle=":", linewidth=1.1,
        )
        rsi_ax.plot(
            [signal["previous_peak_date"], current["peak_date"]],
            [signal["previous_peak_rsi"], current["peak_rsi"]],
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

    rsi_ax.plot(daily["date"], daily["rsi14"], linewidth=1.4, label="RSI14 (CN SMA)")
    for level, style in ((70, "--"), (60, "-."), (50, ":"), (40, ":")):
        rsi_ax.axhline(level, linestyle=style, linewidth=0.9, label=f"RSI {level}")
    rsi_ax.set_ylim(0, 105)
    rsi_ax.set_ylabel("RSI14")
    price_ax.set_ylabel("Forward-adjusted price")
    price_ax.set_title(f"{result.symbol} RSI Exit Signal Recognizer v0.1")
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
