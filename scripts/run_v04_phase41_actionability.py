from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsi_exit.actionability import (
    ActionabilityValidationError,
    load_phase4_actionability,
    write_actionability_bundle,
)


LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate warning actionability from existing rsi-exit v0.4 "
            "Phase 4 outputs."
        )
    )
    parser.add_argument("--phase4-output", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        bundle = load_phase4_actionability(args.phase4_output)
        paths = write_actionability_bundle(bundle, args.output_dir)
    except (ActionabilityValidationError, OSError, ValueError) as exc:
        LOGGER.error("Phase 4.1 actionability validation failed: %s", exc)
        return 1

    for label, path in paths.items():
        LOGGER.info("Wrote %s: %s", label, path)
    if bundle.failed_count:
        LOGGER.error(
            "Phase 4.1 validation finished with %s failed samples",
            bundle.failed_count,
        )
        return 1
    LOGGER.info(
        "Phase 4.1 actionability validation completed: %s samples",
        len(bundle.sample_verification),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
