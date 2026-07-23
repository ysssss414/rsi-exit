from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import zipfile

import pandas as pd

from rsi_exit.config import RsiExitConfig, load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import AnalysisResult, analyze_bars
from rsi_exit.release_check import (
    BASELINE_SHA256,
    FrozenBaselineError,
    load_frozen_bars,
    validate_frozen_baseline,
)
from rsi_exit.reporting import _csv_ready


PACKAGE_NAME = "rsi-exit"
FREEZE_VERSION = "0.3.0"
SEMANTIC_BASE_COMMIT = "2010817939f5cf3a039e2a96936513487fb5114f"
SYMBOL = "300308.SZ"
NAME = "中际旭创"
DISPLAY_START_DATE = "2026-05-01"
DISPLAY_END_DATE = "2026-07-20"
INPUT_BASELINE_FILENAME = "300308.SZ_v0.2.1_frozen_baseline.zip"
CONFIG_PATH = "config/rsi_exit_v03.yaml"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

TABLE_MEMBERS = (
    ("daily_features.csv", "daily_features"),
    ("peaks.csv", "peaks"),
    ("canonical_peaks.csv", "canonical_peaks"),
    ("signals.csv", "signals"),
    ("state_log.csv", "state_log"),
    ("cycle_log.csv", "cycle_log"),
    ("rsi_audit.csv", "rsi_audit"),
)
CONFIG_SNAPSHOT_KEYS = (
    "version",
    "rsi",
    "levels",
    "data",
    "peak_detection",
    "divergence",
    "position_caps",
    "chart",
)
KEY_SEQUENCE = (
    ("2026-04-23", "FORMAL"),
    ("2026-04-30", "FORMAL"),
    ("2026-05-14", "FORMAL"),
    ("2026-05-20", "FORMAL"),
    ("2026-05-28", "FORMAL"),
    ("2026-06-04", "FORMAL"),
    ("2026-06-18", "FORMING"),
    ("2026-06-22", "FORMAL"),
    ("2026-06-25", "FORMAL"),
)


class FreezeBaselineError(FrozenBaselineError):
    pass


def build_frozen_archive(
    result: AnalysisResult,
    config: RsiExitConfig,
    *,
    input_baseline_sha256: str = BASELINE_SHA256,
    formal_divergence_count: int | None = None,
) -> bytes:
    """Serialize a formal AnalysisResult into deterministic frozen ZIP bytes."""
    _validate_identity(result, config)
    member_bytes: dict[str, bytes] = {}
    for filename, attribute in TABLE_MEMBERS:
        frame = getattr(result, attribute)
        if not isinstance(frame, pd.DataFrame):
            raise FreezeBaselineError(f"formal output is not a DataFrame: {attribute}")
        member_bytes[f"{SYMBOL}/{filename}"] = _csv_bytes(frame)

    snapshot = {
        key: deepcopy(config.values[key])
        for key in CONFIG_SNAPSHOT_KEYS
    }
    member_bytes[f"{SYMBOL}/config_snapshot.yaml"] = _json_bytes(snapshot)

    if formal_divergence_count is None:
        formal_divergence_count = _formal_divergence_count(result.signals)
    manifest_member = f"{SYMBOL}/freeze_manifest.json"
    members = sorted([*member_bytes, manifest_member])
    member_sha256 = {
        member: hashlib.sha256(member_bytes[member]).hexdigest().upper()
        for member in sorted(member_bytes)
    }
    manifest = {
        "package": PACKAGE_NAME,
        "version": FREEZE_VERSION,
        "semantic_base_commit": SEMANTIC_BASE_COMMIT,
        "symbol": SYMBOL,
        "input_baseline_filename": INPUT_BASELINE_FILENAME,
        "input_baseline_sha256": input_baseline_sha256.upper(),
        "config": CONFIG_PATH,
        "display_start_date": DISPLAY_START_DATE,
        "display_end_date": DISPLAY_END_DATE,
        "formal_divergence_count": int(formal_divergence_count),
        "members": members,
        "member_sha256": member_sha256,
    }
    member_bytes[manifest_member] = _json_bytes(manifest)
    archive_bytes = _zip_bytes(member_bytes)
    validate_frozen_archive(archive_bytes)
    return archive_bytes


def validate_frozen_archive(archive_bytes: bytes) -> dict[str, object]:
    """Validate member order, manifest coverage, and recorded member digests."""
    try:
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            members = archive.namelist()
            if members != sorted(members):
                raise FreezeBaselineError("frozen archive members are not sorted")
            manifest_member = f"{SYMBOL}/freeze_manifest.json"
            if manifest_member not in members:
                raise FreezeBaselineError("frozen archive manifest is missing")
            manifest = json.loads(archive.read(manifest_member).decode("utf-8"))
            if manifest.get("members") != members:
                raise FreezeBaselineError("frozen archive manifest members mismatch")
            expected_hashes = manifest.get("member_sha256")
            if not isinstance(expected_hashes, dict):
                raise FreezeBaselineError("frozen archive member_sha256 is invalid")
            if set(expected_hashes) != set(members) - {manifest_member}:
                raise FreezeBaselineError("frozen archive member_sha256 coverage mismatch")
            for member, expected in expected_hashes.items():
                actual = hashlib.sha256(archive.read(member)).hexdigest().upper()
                if actual != expected:
                    raise FreezeBaselineError(
                        f"frozen archive member SHA-256 mismatch: {member}"
                    )
            for info in archive.infolist():
                if info.date_time != ZIP_TIMESTAMP:
                    raise FreezeBaselineError(
                        f"frozen archive timestamp mismatch: {info.filename}"
                    )
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreezeBaselineError("invalid frozen archive") from exc
    return manifest


def freeze_baseline(source_baseline: str | Path, output: str | Path) -> dict[str, object]:
    source_path = Path(source_baseline)
    output_path = Path(output)
    if source_path.resolve() == output_path.resolve():
        raise FreezeBaselineError("source baseline and output must be different files")

    release_summary = validate_frozen_baseline(source_path)
    bars = load_frozen_bars(source_path)
    config = load_config(CONFIG_PATH)
    result = analyze_bars(
        bars,
        symbol=SYMBOL,
        name=NAME,
        config=config,
        display_start_date=DISPLAY_START_DATE,
        display_end_date=DISPLAY_END_DATE,
    )
    key_rows = _key_sequence_rows(result.signals)
    archive_bytes = build_frozen_archive(
        result,
        config,
        input_baseline_sha256=str(release_summary["sha256"]),
        formal_divergence_count=int(release_summary["formal_divergences"]),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary.write_bytes(archive_bytes)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "output": output_path,
        "sha256": hashlib.sha256(archive_bytes).hexdigest().upper(),
        "members": validate_frozen_archive(archive_bytes)["members"],
        "key_sequence": key_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic rsi-exit v0.3.0 frozen baseline"
    )
    parser.add_argument("--source-baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.source_baseline is None or args.output is None:
        print("--source-baseline and --output are required", file=sys.stderr)
        return 2
    try:
        summary = freeze_baseline(args.source_baseline, args.output)
    except (FrozenBaselineError, OSError, ValueError) as exc:
        print(f"frozen baseline generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"frozen baseline created: {summary['output']} "
        f"sha256={summary['sha256']}"
    )
    print("key sequence:")
    for row in summary["key_sequence"]:
        print(row)
    return 0


def _validate_identity(result: AnalysisResult, config: RsiExitConfig) -> None:
    config_version = config.values.get("version")
    if config_version != FREEZE_VERSION:
        raise FreezeBaselineError(
            f"v0.3.0 config version mismatch: {config_version!r}"
        )
    if result.symbol != SYMBOL:
        raise FreezeBaselineError(
            f"frozen result symbol mismatch: expected {SYMBOL}, got {result.symbol}"
        )


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    text = _csv_ready(frame).to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.6f",
        na_rep="",
    )
    return text.encode("utf-8")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _zip_bytes(member_bytes: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for member in sorted(member_bytes):
            info = zipfile.ZipInfo(member, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, member_bytes[member])
    return buffer.getvalue()


def _formal_divergence_count(signals: pd.DataFrame) -> int:
    if signals.empty:
        return 0
    formal_types = {
        SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
        SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
    }
    mask = (
        signals["signal_type"].isin(formal_types)
        & (signals["signal_status"] == "FORMAL")
        & (signals["current_peak_date"] >= DISPLAY_START_DATE)
    )
    return int(mask.sum())


def _key_sequence_rows(signals: pd.DataFrame) -> list[str]:
    rows: list[str] = []
    for peak_date, status in KEY_SEQUENCE:
        matches = signals.loc[
            (signals["current_peak_date"] == peak_date)
            & (signals["signal_status"] == status)
        ]
        if len(matches) != 1:
            raise FreezeBaselineError(
                f"expected one {status} key-sequence row for {peak_date}, got {len(matches)}"
            )
        row = matches.iloc[0]
        rows.append(
            " ".join([
                peak_date,
                f"{row['canonical_peak_id']}@v{int(row['canonical_version'])}",
                str(row["signal_type"]),
                f"price_relation={row['price_relation']}",
                f"count={int(row['divergence_count'])}",
                f"position_eligible={bool(row['position_eligible'])}",
                f"position_cap={float(row['divergence_position_cap']):.1f}",
                f"momentum_anchor={row['momentum_anchor_date']}",
                f"anchor_rsi={float(row['momentum_anchor_rsi']):.6f}",
                f"decision_date={row['decision_date']}",
                f"earliest_action_date={row['earliest_action_date'] or '-'}",
            ])
        )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
