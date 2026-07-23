from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when RSI-exit configuration is invalid."""


@dataclass(frozen=True)
class RsiExitConfig:
    values: dict[str, Any]
    source_path: Path

    def section(self, name: str) -> dict[str, Any]:
        value = self.values.get(name)
        if not isinstance(value, dict):
            raise ConfigError(f"配置节 {name!r} 缺失或不是对象")
        return value


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "rsi_exit_v04.yaml"


def load_config(path: str | Path | None = None) -> RsiExitConfig:
    source = Path(path or default_config_path()).resolve()
    if not source.exists():
        raise ConfigError(f"配置文件不存在: {source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{source.name} 必须使用 JSON-compatible YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置顶层必须是对象")
    _validate(raw)
    return RsiExitConfig(deepcopy(raw), source)


def _number(section: dict[str, Any], key: str, *, minimum: float | None = None) -> float:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置项 {key} 必须是数值")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ConfigError(f"配置项 {key} 必须 >= {minimum}")
    return number


def _integer(section: dict[str, Any], key: str, *, minimum: int = 0) -> int:
    value = _number(section, key, minimum=minimum)
    if int(value) != value:
        raise ConfigError(f"配置项 {key} 必须是整数")
    return int(value)


def _validate(raw: dict[str, Any]) -> None:
    required = (
        "rsi", "levels", "data", "peak_detection", "divergence",
        "position_caps", "chart", "data_source", "output",
    )
    for name in required:
        if not isinstance(raw.get(name), dict):
            raise ConfigError(f"缺少配置节: {name}")

    _integer(raw["rsi"], "period", minimum=1)
    if raw["rsi"].get("seed_mode") not in {"first", "mean"}:
        raise ConfigError("rsi.seed_mode 必须是 first 或 mean")

    levels = raw["levels"]
    strong, life = _number(levels, "strong"), _number(levels, "life")
    neutral, weak = _number(levels, "neutral"), _number(levels, "weak")
    if not strong > life > neutral > weak:
        raise ConfigError("RSI levels 必须满足 strong > life > neutral > weak")

    _integer(raw["data"], "warmup_trading_days", minimum=120)
    _integer(raw["data"], "ma_period", minimum=1)

    peak = raw["peak_detection"]
    for key in ("lookback", "min_peak_gap", "max_peak_gap"):
        _integer(peak, key, minimum=1)
    if not isinstance(peak.get("require_recent_window_max"), bool):
        raise ConfigError("peak_detection.require_recent_window_max 必须是布尔值")
    _number(peak, "min_rsi_retrace", minimum=0)
    _number(peak, "min_price_retrace_pct", minimum=0)
    if "canonical_price_tolerance_pct" in peak:
        _number(peak, "canonical_price_tolerance_pct", minimum=0)

    divergence = raw["divergence"]
    if "comparable_zone_mode" in divergence:
        if divergence.get("comparable_zone_mode") != "PREVIOUS_CLOSE_TO_PEAK_CLOSE":
            raise ConfigError(
                "divergence.comparable_zone_mode 必须为 PREVIOUS_CLOSE_TO_PEAK_CLOSE"
            )
        for key in (
            "price_epsilon", "divergence_rsi_tolerance", "anchor_rsi_tolerance",
            "momentum_strengthening_tolerance", "anchor_reset_tolerance",
            "deep_reset_rsi_level", "extreme_reset_rsi_level",
        ):
            _number(divergence, key, minimum=0)
        _integer(divergence, "deep_reset_consecutive_days", minimum=1)
        _integer(divergence, "max_structural_peak_gap", minimum=1)
        if not isinstance(divergence.get("forming_divergence_position_eligible"), bool):
            raise ConfigError(
                "divergence.forming_divergence_position_eligible 必须是布尔值"
            )
        if divergence["forming_divergence_position_eligible"]:
            raise ConfigError("forming divergence 不得进入仓位系统")
    else:
        # Historical v0.1/v0.2 files remain readable for regression work.
        _number(divergence, "price_tolerance_pct", minimum=0)
        _number(divergence, "rsi_tolerance", minimum=0)
        _number(divergence, "reset_rsi_level")

    caps = raw["position_caps"]
    expected_caps = {
        "uninitialized", "base_s0", "base_s1", "base_s2", "base_s3", "base_s4",
        "first_divergence", "second_divergence", "third_divergence",
        "divergence_below_life", "weak_rebound_above_life", "weak_rebound_below_life",
    }
    if set(caps) != expected_caps:
        missing = expected_caps - set(caps)
        extra = set(caps) - expected_caps
        raise ConfigError(f"position_caps 字段不完整，缺少={sorted(missing)} 多余={sorted(extra)}")
    for key in expected_caps:
        number = _number(caps, key, minimum=0)
        if number > 1:
            raise ConfigError(f"position_caps.{key} 必须位于 [0, 1]")

    chart = raw["chart"]
    lines = chart.get("rsi_lines")
    if not isinstance(lines, list) or not lines or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) for value in lines
    ):
        raise ConfigError("chart.rsi_lines 必须是非空数值数组")

    source = raw["data_source"]
    if source.get("provider") != "AmazingData":
        raise ConfigError("data_source.provider 必须为 AmazingData")
