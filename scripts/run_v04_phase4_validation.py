from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsi_exit.config import load_config
from rsi_exit.data import AmazingDataAdapter
from rsi_exit.pipeline import AnalysisResult, analyze_bars
from rsi_exit.reporting import write_outputs
from rsi_exit.validation import (
    build_validation_bundle,
    write_validation_bundle,
)


LOGGER = logging.getLogger(__name__)
WORKER_ENV = "RSI_EXIT_PHASE4_WORKER"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fixed rsi-exit v0.4 Phase 4 validation sample."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--display-start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--display-end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--adjust", choices=["forward"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force-refresh", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get(WORKER_ENV) == "1":
        return _run_validation(arguments)

    args = build_parser().parse_args(arguments)
    summary_path = args.output_dir / "sample_summary.csv"
    started_ns = time.time_ns()
    environment = os.environ.copy()
    environment[WORKER_ENV] = "1"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *arguments],
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    if (
        not summary_path.is_file()
        or summary_path.stat().st_mtime_ns < started_ns
    ):
        LOGGER.error("Phase 4 worker did not persist a current sample_summary.csv")
        return 1
    summary = pd.read_csv(summary_path, encoding="utf-8-sig")
    if "error" not in summary:
        LOGGER.error("Phase 4 sample_summary.csv is missing the error column")
        return 1
    return int(summary["error"].fillna("").astype(str).str.strip().ne("").any())


def _run_validation(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    manifest = pd.read_csv(args.manifest, encoding="utf-8-sig")
    config = load_config()
    source = config.values["data_source"]
    warmup_days = int(config.values["data"]["warmup_trading_days"])
    adapter = AmazingDataAdapter(
        legacy_provider_root=_project_path(source["legacy_provider_root"]),
        cache_dir=_project_path(source["cache_dir"]),
        retry_count=int(source["retry_count"]),
        retry_delay_seconds=float(source["retry_delay_seconds"]),
        use_numba_compat=bool(source.get("use_numba_compat", True)),
    )

    results: dict[str, AnalysisResult] = {}
    names: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    close_error: str | None = None
    bundle = None
    symbols = manifest["symbol"].astype(str).str.strip().str.upper().tolist()
    try:
        try:
            code_info = adapter.get_code_info()
            calculation_start = adapter.get_calculation_start_date(
                args.display_start, warmup_days
            )
            LOGGER.info(
                "Using unified calculation start %s for %s samples",
                calculation_start,
                len(symbols),
            )
            for symbol in symbols:
                try:
                    name = _resolve_name(code_info, symbol)
                    names[symbol] = name
                    bars = adapter.get_daily_bars(
                        symbol,
                        calculation_start,
                        args.display_end,
                        args.adjust,
                        force_refresh=args.force_refresh,
                    )
                    result = analyze_bars(
                        bars,
                        symbol=symbol,
                        name=name,
                        config=config,
                        display_start_date=args.display_start,
                        display_end_date=args.display_end,
                    )
                    results[symbol] = result
                    write_outputs(
                        result,
                        config=config,
                        output_root=args.output_dir,
                        plot=True,
                    )
                    LOGGER.info("Validated analysis output for %s %s", symbol, name)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    errors[symbol] = str(exc)
                    LOGGER.exception("Phase 4 sample failed: %s", symbol)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            LOGGER.exception("Phase 4 shared AmazingData setup failed")
            for symbol in symbols:
                errors.setdefault(symbol, str(exc))

        bundle = build_validation_bundle(
            manifest,
            results,
            names_by_symbol=names,
            errors_by_symbol=errors,
            display_start_date=args.display_start,
            display_end_date=args.display_end,
            chart_path_root=args.output_dir.as_posix(),
        )
        paths = write_validation_bundle(bundle, args.output_dir)
        for label, path in paths.items():
            LOGGER.info("Wrote %s: %s", label, path)
    finally:
        try:
            adapter.close()
        except KeyboardInterrupt:
            raise
        except SystemExit as exc:
            if exc.code not in (None, 0):
                close_error = f"logout requested exit {exc.code}"
                LOGGER.error("AmazingData adapter close failed: %s", close_error)
            else:
                LOGGER.info("AmazingData adapter closed")
        except Exception as exc:
            close_error = str(exc)
            LOGGER.exception("AmazingData adapter close failed")

    assert bundle is not None
    if bundle.failed_count or close_error is not None:
        LOGGER.error(
            "Phase 4 validation finished with %s failed samples%s",
            bundle.failed_count,
            f"; adapter close error: {close_error}" if close_error else "",
        )
        return 1
    LOGGER.info("Phase 4 validation completed: %s/%s samples", len(results), len(symbols))
    return 0


def _resolve_name(code_info: pd.DataFrame, symbol: str) -> str:
    if not {"code", "name"}.issubset(code_info.columns):
        raise ValueError("AmazingData code info is missing code/name columns")
    matches = code_info.loc[
        code_info["code"].astype(str).str.strip().str.upper() == symbol
    ]
    if len(matches) != 1:
        raise ValueError(
            f"AmazingData code info matched {len(matches)} rows for {symbol}"
        )
    name = str(matches.iloc[0]["name"]).strip()
    if not name or name.lower() == "nan":
        raise ValueError(f"AmazingData code info returned an empty name for {symbol}")
    return name


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
