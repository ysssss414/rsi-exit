from __future__ import annotations

from copy import deepcopy
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

from rsi_exit.config import RsiExitConfig, load_config
from rsi_exit.indicators import rsi_zone
from rsi_exit.pipeline import SignalCapQueue, analyze_bars, run_batch
from rsi_exit.position_rules import merge_position_caps
from rsi_exit.reporting import build_regression_comparison


def _bars(count: int = 150) -> pd.DataFrame:
    index = np.arange(count)
    close = 100 + index * 0.1
    return pd.DataFrame({
        "date": pd.bdate_range("2025-01-01", periods=count),
        "open": close * 0.995,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1000 + index,
        "amount": close * (1000 + index),
    })


def _scripted_peak_bars(peaks: list[tuple[int, float, float]], count: int = 130) -> tuple[pd.DataFrame, pd.Series]:
    source = _bars(count)
    rsi = pd.Series(65.0, index=source.index)
    for index, close, peak_rsi in peaks:
        source.loc[index - 1, "close"] = close - 2
        source.loc[index, "close"] = close
        source.loc[index + 1, "close"] = close - 3
        rsi.loc[index - 1] = 65
        rsi.loc[index] = peak_rsi
        rsi.loc[index + 1] = max(61, peak_rsi - 6)
    for column, ratio in (("open", .995), ("high", 1.01), ("low", .99)):
        source[column] = source["close"] * ratio
    source["amount"] = source["close"] * source["volume"]
    return source, rsi


def _install_rsi(monkeypatch, scripted_rsi: pd.Series) -> None:
    def fake_audit(close: pd.Series, period: int, seed_mode: str) -> pd.DataFrame:
        delta = close.diff()
        return pd.DataFrame({
            "adjusted_close": close,
            "delta": delta,
            "gain": delta.clip(lower=0),
            "absolute_delta": delta.abs(),
            "smoothed_gain": delta.clip(lower=0),
            "smoothed_absolute": delta.abs(),
            "rsi": scripted_rsi,
        }, index=close.index)

    monkeypatch.setattr("rsi_exit.pipeline.calculate_rsi_audit", fake_audit)


def test_a_same_day_old_point_four_cap_and_s3_reset_do_not_conflict() -> None:
    queue = SignalCapQueue("CYCLE0001")
    effective_date = pd.Timestamp("2026-01-06")
    queue.schedule_cap(effective_date, cycle_id="CYCLE0001", cap=.4, action="REDUCE")
    queue.schedule_reset(
        effective_date, old_cycle_id="CYCLE0001", new_cycle_id="CYCLE0002"
    )

    queue.apply_due(effective_date)
    _, s3_cap = merge_position_caps(
        base_action="EXIT", base_cap=0, signal_action=queue.effective_action,
        signal_cap=queue.effective_cap,
    )
    _, reentry_cap = merge_position_caps(
        base_action="ALLOW_REENTRY", base_cap=1, signal_action=queue.effective_action,
        signal_cap=queue.effective_cap,
    )
    assert s3_cap == 0
    assert queue.effective_cap == 1
    assert queue.effective_cycle_id == "CYCLE0002"
    assert reentry_cap == 1


def test_b_same_day_third_divergence_zero_cap_and_s3_reset_do_not_lock_reentry() -> None:
    queue = SignalCapQueue("CYCLE0001")
    effective_date = pd.Timestamp("2026-01-06")
    queue.schedule_cap(effective_date, cycle_id="CYCLE0001", cap=0, action="EXIT")
    queue.schedule_reset(
        effective_date, old_cycle_id="CYCLE0001", new_cycle_id="CYCLE0002"
    )

    queue.apply_due(effective_date)
    _, s3_cap = merge_position_caps(
        base_action="EXIT", base_cap=0, signal_action=queue.effective_action,
        signal_cap=queue.effective_cap,
    )
    _, reentry_cap = merge_position_caps(
        base_action="ALLOW_REENTRY", base_cap=1, signal_action=queue.effective_action,
        signal_cap=queue.effective_cap,
    )
    assert s3_cap == 0
    assert queue.effective_cap == 1
    assert reentry_cap == 1


def test_c_same_day_ordinary_constraints_without_reset_keep_strictest_cap() -> None:
    queue = SignalCapQueue("CYCLE0001")
    effective_date = pd.Timestamp("2026-01-06")
    queue.schedule_cap(effective_date, cycle_id="CYCLE0001", cap=.7, action="REDUCE")
    queue.schedule_cap(effective_date, cycle_id="CYCLE0001", cap=.4, action="REDUCE_MORE")
    queue.apply_due(effective_date)
    assert queue.effective_cap == .4
    assert queue.effective_action == "REDUCE_MORE"


def test_cycle_reset_invalidates_an_already_effective_old_cycle_cap() -> None:
    queue = SignalCapQueue("CYCLE0001")
    queue.schedule_cap(pd.Timestamp("2026-01-05"), cycle_id="CYCLE0001", cap=.4, action="REDUCE")
    queue.apply_due(pd.Timestamp("2026-01-05"))
    assert queue.effective_cap == .4
    queue.schedule_reset(
        pd.Timestamp("2026-01-06"), old_cycle_id="CYCLE0001", new_cycle_id="CYCLE0002"
    )
    queue.apply_due(pd.Timestamp("2026-01-06"))
    assert queue.effective_cap == 1
    assert queue.effective_source is None


def test_pipeline_same_day_signal_and_s3_reset_leave_new_cycle_unrestricted(monkeypatch) -> None:
    source, scripted_rsi = _scripted_peak_bars([(109, 120, 80), (117, 121, 76)])
    scripted_rsi.loc[118] = 59
    scripted_rsi.loc[119:121] = [65, 72, 65]
    source.loc[119:, "close"] = 130
    source.loc[119:, ["open", "high", "low"]] = source.loc[119:, "close"].to_numpy()[:, None] * np.array([.995, 1.01, .99])
    source["hard_exit"] = 0
    source.loc[118, "hard_exit"] = 1
    _install_rsi(monkeypatch, scripted_rsi)

    result = analyze_bars(source, symbol="TEST.A", config=load_config())
    daily = result.daily_features.set_index("date")
    reset_effective = source.loc[119, "date"].strftime("%Y-%m-%d")
    after_reentry = source.loc[121, "date"].strftime("%Y-%m-%d")
    assert daily.loc[reset_effective, "effective_base_position_cap"] == 0
    assert daily.loc[reset_effective, "effective_signal_position_cap"] == 1
    assert daily.loc[reset_effective, "effective_final_position_cap"] == 0
    assert daily.loc[after_reentry, "effective_signal_position_cap"] == 1
    assert daily.loc[after_reentry, "effective_final_position_cap"] == 1
    old_constraint = result.signals.loc[
        result.signals["pending_action_type"] == "APPLY_SIGNAL_CAP"
    ].iloc[-1]
    assert old_constraint["divergence_position_cap"] == .4
    assert bool(old_constraint["invalidated_by_cycle_reset"])


def test_pipeline_third_divergence_reset_does_not_permanently_lock_zero(monkeypatch) -> None:
    source, scripted_rsi = _scripted_peak_bars([
        (90, 120, 85), (99, 121, 82), (108, 122, 79), (117, 123, 76),
    ])
    scripted_rsi.loc[119:121] = [65, 72, 65]
    source.loc[119:, "close"] = 130
    source.loc[119:, ["open", "high", "low"]] = source.loc[119:, "close"].to_numpy()[:, None] * np.array([.995, 1.01, .99])
    _install_rsi(monkeypatch, scripted_rsi)

    result = analyze_bars(source, symbol="TEST.B", config=load_config())
    daily = result.daily_features.set_index("date")
    reset_effective = source.loc[119, "date"].strftime("%Y-%m-%d")
    after_reentry = source.loc[121, "date"].strftime("%Y-%m-%d")
    assert daily.loc[reset_effective, "effective_base_position_cap"] == 0
    assert daily.loc[reset_effective, "effective_signal_position_cap"] == 1
    assert daily.loc[reset_effective, "effective_final_position_cap"] == 0
    assert daily.loc[after_reentry, "effective_final_position_cap"] == 1
    third = result.signals.loc[result.signals["divergence_count"] >= 3].iloc[-1]
    assert third["divergence_position_cap"] == 0
    assert bool(third["invalidated_by_cycle_reset"])


def test_display_start_cap_can_be_traced_to_warmup_signal(monkeypatch) -> None:
    source, scripted_rsi = _scripted_peak_bars([(99, 120, 80), (109, 121, 77), (117, 122, 74)])
    _install_rsi(monkeypatch, scripted_rsi)
    display_start = source.loc[120, "date"]
    result = analyze_bars(
        source, symbol="TEST.WARMUP", config=load_config(),
        display_start_date=display_start, display_end_date=source.iloc[-1]["date"],
    )

    first = result.daily_features.iloc[0]
    source_signal = result.signals.loc[
        result.signals["candidate_peak_id"] == first["effective_signal_source_candidate_peak_id"]
    ].iloc[0]
    assert first["effective_signal_position_cap"] == .4
    assert first["effective_signal_source_original_cap"] == .4
    assert first["effective_signal_source_is_warmup"]
    assert source_signal["is_warmup"]
    assert not source_signal["is_display_range"]
    assert source_signal["cycle_id"] == first["effective_signal_cycle_id"]
    assert source_signal["decision_date"] == first["effective_signal_source_decision_date"]
    assert source_signal["effective_date"] == first["effective_signal_source_effective_date"]
    assert source_signal["canonical_peak_id"] == first["effective_signal_source_canonical_peak_id"]


def test_run_batch_passes_shared_display_range_and_marks_insufficient_warmup() -> None:
    full = _bars(150)
    short = full.iloc[20:].reset_index(drop=True)
    display_start = full.loc[120, "date"]
    display_end = full.iloc[-1]["date"]
    results, summary = run_batch(
        [("FULL", None, full), ("SHORT", None, short)], config=load_config(),
        display_start_date=display_start, display_end_date=display_end,
    )

    assert [len(item.daily_features) for item in results] == [30, 30]
    table = summary.set_index("symbol")
    assert table.loc["FULL", "warmup_trading_days_actual"] == 120
    assert bool(table.loc["FULL", "backtest_eligible"])
    assert table.loc["SHORT", "warmup_trading_days_actual"] == 100
    assert not bool(table.loc["SHORT", "backtest_eligible"])
    assert "预热不足" in table.loc["SHORT", "backtest_ineligible_reason"]


def test_custom_levels_ma_csv_and_chart_helpers_share_configuration(monkeypatch) -> None:
    matplotlib_cache = Path(".runtime/matplotlib").resolve()
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MPLCONFIGDIR", str(matplotlib_cache))
    from rsi_exit.plotting import price_axis_label, signal_threshold_label

    cfg = load_config()
    values = deepcopy(cfg.values)
    values["levels"] = {"strong": 80, "life": 65, "neutral": 55, "weak": 45}
    values["data"]["ma_period"] = 30
    custom = RsiExitConfig(values, cfg.source_path)
    source = _bars()
    source.attrs["adjust"] = "raw"
    result = analyze_bars(source, symbol="CUSTOM", config=custom)

    assert "ma" in result.daily_features
    assert "ma30" in result.daily_features
    assert "ma20" not in result.daily_features
    assert np.allclose(
        result.daily_features["ma"], result.daily_features["ma30"], equal_nan=True
    )
    first_ready = result.daily_features.dropna(subset=["rsi"]).iloc[0]
    assert first_ready["rsi_zone"] == rsi_zone(
        first_ready["rsi"], strong=80, life=65, neutral=55, weak=45
    )
    assert rsi_zone(82, strong=80, life=65, neutral=55, weak=45) == "ABOVE_STRONG"
    assert rsi_zone(70, strong=80, life=65, neutral=55, weak=45) == "LIFE_TO_STRONG"
    assert rsi_zone(60, strong=80, life=65, neutral=55, weak=45) == "NEUTRAL_TO_LIFE"
    assert rsi_zone(50, strong=80, life=65, neutral=55, weak=45) == "WEAK_TO_NEUTRAL"
    assert rsi_zone(40, strong=80, life=65, neutral=55, weak=45) == "BELOW_WEAK"
    assert signal_threshold_label(64, life_level=65) == "<65"
    assert signal_threshold_label(65, life_level=65) == ">=65"
    assert price_axis_label("raw") == "Raw price"
    assert price_axis_label("none") == "Raw price"
    assert price_axis_label("forward") == "Forward-adjusted price"
    csv_buffer = StringIO()
    result.daily_features.to_csv(csv_buffer, index=False)
    daily_csv = pd.read_csv(StringIO(csv_buffer.getvalue()))
    assert "ma" in daily_csv
    assert "ma30" in daily_csv
    assert "ma20" not in daily_csv
    comparison = build_regression_comparison(result, previous=None)
    assert "2026-07-20" not in comparison
    assert "38.8449" not in comparison
