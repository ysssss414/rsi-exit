from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when v0.1 configuration is invalid."""


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
    return Path(__file__).resolve().parents[1] / "config" / "rsi_exit_v01.yaml"


def load_config(path: str | Path | None = None) -> RsiExitConfig:
    """Load JSON-compatible YAML, matching the existing project's convention."""
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


def _validate(raw: dict[str, Any]) -> None:
    required = (
        "rsi",
        "levels",
        "peak_detection",
        "divergence",
        "position_caps",
        "data_source",
        "output",
    )
    for name in required:
        if not isinstance(raw.get(name), dict):
            raise ConfigError(f"缺少配置节: {name}")

    rsi = raw["rsi"]
    period = _number(rsi, "period", minimum=1)
    if int(period) != period:
        raise ConfigError("rsi.period 必须是整数")
    if rsi.get("seed_mode") not in {"first", "mean"}:
        raise ConfigError("rsi.seed_mode 必须是 first 或 mean")

    levels = raw["levels"]
    strong = _number(levels, "strong")
    life = _number(levels, "life")
    neutral = _number(levels, "neutral")
    weak = _number(levels, "weak")
    if not strong > life > neutral > weak:
        raise ConfigError("RSI levels 必须满足 strong > life > neutral > weak")

    peak = raw["peak_detection"]
    for key in ("lookback", "min_peak_gap", "max_peak_gap"):
        value = _number(peak, key, minimum=1)
        if int(value) != value:
            raise ConfigError(f"peak_detection.{key} 必须是整数")
    _number(peak, "min_rsi_retrace", minimum=0)
    _number(peak, "min_price_retrace_pct", minimum=0)

    divergence = raw["divergence"]
    _number(divergence, "price_tolerance_pct", minimum=0)
    _number(divergence, "rsi_tolerance", minimum=0)
    _number(divergence, "reset_rsi_level")

    caps = raw["position_caps"]
    for key, value in caps.items():
        number = _number(caps, key, minimum=0)
        if number > 1:
            raise ConfigError(f"position_caps.{key} 必须位于 [0, 1]")

