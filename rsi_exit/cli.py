from __future__ import annotations

import argparse
import logging
from copy import deepcopy
from pathlib import Path

import pandas as pd

from rsi_exit.config import RsiExitConfig, load_config
from rsi_exit.data import AmazingDataAdapter
from rsi_exit.pipeline import analyze_bars, build_validation_summary
from rsi_exit.reporting import write_batch_summary, write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RSI卖点信号识别器 v0.1")
    parser.add_argument("--symbol", required=True, help="AmazingData代码，例如 300308.SZ")
    parser.add_argument("--name", default=None, help="可选名称；在线模式默认由代码信息接口确认")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--adjust", default="forward", choices=["forward", "none", "raw"])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--seed-mode", choices=["first", "mean"], default=None)
    parser.add_argument("--price-tolerance", type=float, default=None)
    parser.add_argument("--rsi-tolerance", type=float, default=None)
    parser.add_argument("--min-peak-gap", type=int, default=None)
    parser.add_argument("--min-rsi-retrace", type=float, default=None)
    parser.add_argument("--min-price-retrace", type=float, default=None)
    parser.add_argument("--max-peak-gap", type=int, default=None)
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help="离线验收入口；CSV仍须来自AmazingData标准日K",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = _with_overrides(load_config(args.config), args)
    project_root = config.source_path.parents[1]
    output_root = args.output_dir or _project_path(
        project_root, config.values["output"]["root"]
    )

    if args.input_csv is not None:
        bars = _read_input_csv(args.input_csv, args.symbol, args.start, args.end)
        bars.attrs.update(source="AmazingData verified CSV", adjust=args.adjust)
        name = args.name
    else:
        source = config.values["data_source"]
        adapter = AmazingDataAdapter(
            legacy_provider_root=_project_path(project_root, source["legacy_provider_root"]),
            cache_dir=_project_path(project_root, source["cache_dir"]),
            retry_count=int(source["retry_count"]),
            retry_delay_seconds=float(source["retry_delay_seconds"]),
            use_numba_compat=bool(source.get("use_numba_compat", True)),
        )
        if args.name:
            symbol, name = args.symbol.upper(), args.name
        else:
            symbol, resolved_name = adapter.resolve_symbol(args.symbol)
            if symbol.upper() != args.symbol.upper():
                raise ValueError(f"代码信息接口返回不一致: {symbol} != {args.symbol}")
            name = resolved_name
        bars = adapter.get_daily_bars(
            symbol,
            args.start,
            args.end,
            args.adjust,
            force_refresh=args.force_refresh,
        )

    result = analyze_bars(
        bars,
        symbol=args.symbol.upper(),
        name=name,
        config=config,
    )
    output_dir = write_outputs(
        result,
        config=config,
        output_root=output_root,
        plot=args.plot,
    )
    write_batch_summary(build_validation_summary([result]), output_root)
    logging.getLogger(__name__).info("RSI exit outputs written to %s", output_dir)
    if args.input_csv is None:
        adapter.close()
    return 0


def _with_overrides(config: RsiExitConfig, args: argparse.Namespace) -> RsiExitConfig:
    values = deepcopy(config.values)
    mappings = (
        ("seed_mode", "rsi", "seed_mode"),
        ("price_tolerance", "divergence", "price_tolerance_pct"),
        ("rsi_tolerance", "divergence", "rsi_tolerance"),
        ("min_peak_gap", "peak_detection", "min_peak_gap"),
        ("min_rsi_retrace", "peak_detection", "min_rsi_retrace"),
        ("min_price_retrace", "peak_detection", "min_price_retrace_pct"),
        ("max_peak_gap", "peak_detection", "max_peak_gap"),
    )
    for argument, section, key in mappings:
        value = getattr(args, argument)
        if value is not None:
            values[section][key] = value
    return RsiExitConfig(values=values, source_path=config.source_path)


def _read_input_csv(path: Path, symbol: str, start: str, end: str) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if "code" in frame.columns:
        frame = frame.loc[frame["code"].astype(str).str.upper() == symbol.upper()].copy()
    dates = pd.to_datetime(frame["date"].astype(str), errors="coerce")
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    return frame.loc[dates.between(start_date, end_date)].reset_index(drop=True)


def _project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
