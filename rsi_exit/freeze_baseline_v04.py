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

from rsi_exit import __version__
from rsi_exit.actionability import build_formal_warning_linkage
from rsi_exit.config import RsiExitConfig, load_config
from rsi_exit.freeze_baseline import (
    CONFIG_SNAPSHOT_KEYS,
    DISPLAY_END_DATE,
    DISPLAY_START_DATE,
    INPUT_BASELINE_FILENAME,
    KEY_SEQUENCE,
    NAME,
    PACKAGE_NAME,
    SYMBOL,
    ZIP_TIMESTAMP,
    _csv_bytes,
    _formal_divergence_count,
    _json_bytes,
    _key_sequence_rows,
    _zip_bytes,
)
from rsi_exit.pipeline import APPLY_SIGNAL_CAP, AnalysisResult, analyze_bars
from rsi_exit.release_check import (
    BASELINE_SHA256,
    FrozenBaselineError,
    load_frozen_bars,
    validate_frozen_baseline,
)
from rsi_exit.validation import (
    _normalized_event_frame,
    _validate_warning_contract,
)
from rsi_exit.warning_events import derive_warning_states


FREEZE_VERSION = "0.4.0"
SEMANTIC_BASE_COMMIT = "06e1468c0f76be13dbb3966707babc7a1d4dd281"
CONFIG_PATH = "config/rsi_exit_v04.yaml"
FORMAL_MEMBER_CONFIG_PATH = "config/rsi_exit_v03.yaml"
V03_BASELINE_SHA256 = (
    "932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52"
)
V04_BASELINE_SHA256 = (
    "623EE4EB5892AF4CCDB14DEE0CCD7CBF3CFB9AF12D115D3C6E9D61F1884B4C86"
)
V03_BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "baselines"
    / "300308.SZ_v0.3.0_frozen_baseline.zip"
)

TABLE_MEMBERS = (
    ("daily_features.csv", "daily_features"),
    ("peaks.csv", "peaks"),
    ("canonical_peaks.csv", "canonical_peaks"),
    ("signals.csv", "signals"),
    ("state_log.csv", "state_log"),
    ("cycle_log.csv", "cycle_log"),
    ("rsi_audit.csv", "rsi_audit"),
    ("warning_events.csv", "warning_events"),
)
COMMON_V03_MEMBERS = (
    "canonical_peaks.csv",
    "cycle_log.csv",
    "daily_features.csv",
    "peaks.csv",
    "rsi_audit.csv",
    "signals.csv",
    "state_log.csv",
)
LIFECYCLE_EVENTS = ("OPENED", "REFRESHED", "ESCALATED", "CLEARED", "INVALIDATED")
WARNING_STATUSES = ("ACTIVE", "ESCALATED", "CLEARED", "INVALIDATED")
EXPECTED_EVENT_COUNTS = {
    "OPENED": 7,
    "REFRESHED": 9,
    "ESCALATED": 3,
    "CLEARED": 0,
    "INVALIDATED": 4,
}
EXPECTED_DISPLAY_EVENT_COUNTS = {
    "OPENED": 4,
    "REFRESHED": 8,
    "ESCALATED": 3,
    "CLEARED": 0,
    "INVALIDATED": 1,
}
EXPECTED_STATUS_COUNTS = {
    "ACTIVE": 0,
    "ESCALATED": 3,
    "CLEARED": 0,
    "INVALIDATED": 4,
}


class FreezeBaselineV04Error(FrozenBaselineError):
    pass


def build_frozen_archive(
    result: AnalysisResult,
    config: RsiExitConfig,
    *,
    input_baseline_sha256: str = BASELINE_SHA256,
    formal_divergence_count: int | None = None,
) -> bytes:
    """Serialize an AnalysisResult into deterministic v0.4.0 frozen ZIP bytes."""

    _validate_identity(result, config)
    member_bytes: dict[str, bytes] = {}
    for filename, attribute in TABLE_MEMBERS:
        frame = getattr(result, attribute)
        if not isinstance(frame, pd.DataFrame):
            raise FreezeBaselineV04Error(
                f"formal output is not a DataFrame: {attribute}"
            )
        member_bytes[f"{SYMBOL}/{filename}"] = _csv_bytes(frame)

    snapshot = {
        key: deepcopy(config.values[key])
        for key in CONFIG_SNAPSHOT_KEYS
    }
    member_bytes[f"{SYMBOL}/config_snapshot.yaml"] = _json_bytes(snapshot)

    if formal_divergence_count is None:
        formal_divergence_count = _formal_divergence_count(result.signals)
    warning_summary = _warning_summary(result.warning_events)
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
        "formal_member_config": FORMAL_MEMBER_CONFIG_PATH,
        "display_start_date": DISPLAY_START_DATE,
        "display_end_date": DISPLAY_END_DATE,
        "formal_divergence_count": int(formal_divergence_count),
        "formal_warning_linkage_count": warning_summary["linkage_count"],
        "warning_event_counts": warning_summary["event_counts"],
        "display_warning_event_counts": warning_summary[
            "display_event_counts"
        ],
        "warning_status_counts": warning_summary["status_counts"],
        "warning_position_effect": "NONE",
        "warning_recommended_position_cap": None,
        "members": members,
        "member_sha256": member_sha256,
    }
    member_bytes[manifest_member] = _json_bytes(manifest)
    archive_bytes = _zip_bytes(member_bytes)
    validate_frozen_archive(archive_bytes)
    return archive_bytes


def validate_frozen_archive(archive_bytes: bytes) -> dict[str, object]:
    """Validate v0.4 identity, deterministic metadata, and member digests."""

    try:
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            members = archive.namelist()
            expected_members = sorted([
                *(f"{SYMBOL}/{filename}" for filename, _ in TABLE_MEMBERS),
                f"{SYMBOL}/config_snapshot.yaml",
                f"{SYMBOL}/freeze_manifest.json",
            ])
            if members != expected_members:
                raise FreezeBaselineV04Error(
                    f"v0.4 frozen archive members mismatch: {members}"
                )
            manifest_member = f"{SYMBOL}/freeze_manifest.json"
            manifest = json.loads(archive.read(manifest_member).decode("utf-8"))
            expected_identity = {
                "package": PACKAGE_NAME,
                "version": FREEZE_VERSION,
                "semantic_base_commit": SEMANTIC_BASE_COMMIT,
                "config": CONFIG_PATH,
            }
            for key, expected in expected_identity.items():
                if manifest.get(key) != expected:
                    raise FreezeBaselineV04Error(
                        f"v0.4 frozen archive {key} mismatch"
                    )
            if manifest.get("members") != members:
                raise FreezeBaselineV04Error(
                    "v0.4 frozen archive manifest members mismatch"
                )
            expected_hashes = manifest.get("member_sha256")
            if not isinstance(expected_hashes, dict):
                raise FreezeBaselineV04Error(
                    "v0.4 frozen archive member_sha256 is invalid"
                )
            if set(expected_hashes) != set(members) - {manifest_member}:
                raise FreezeBaselineV04Error(
                    "v0.4 frozen archive member_sha256 coverage mismatch"
                )
            for member, expected in expected_hashes.items():
                actual = hashlib.sha256(archive.read(member)).hexdigest().upper()
                if actual != expected:
                    raise FreezeBaselineV04Error(
                        f"v0.4 frozen archive member SHA-256 mismatch: {member}"
                    )
            for info in archive.infolist():
                if info.date_time != ZIP_TIMESTAMP:
                    raise FreezeBaselineV04Error(
                        f"v0.4 frozen archive timestamp mismatch: {info.filename}"
                    )
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreezeBaselineV04Error("invalid v0.4 frozen archive") from exc
    return manifest


def validate_release_result(result: AnalysisResult) -> dict[str, object]:
    """Validate the frozen warning contract without changing production logic."""

    warning_summary = _warning_summary(result.warning_events)
    expected = (
        ("event_counts", EXPECTED_EVENT_COUNTS),
        ("display_event_counts", EXPECTED_DISPLAY_EVENT_COUNTS),
        ("status_counts", EXPECTED_STATUS_COUNTS),
    )
    for label, expected_counts in expected:
        if warning_summary[label] != expected_counts:
            raise FreezeBaselineV04Error(
                f"v0.4 warning {label} mismatch: {warning_summary[label]}"
            )
    if _formal_divergence_count(result.signals) != 3:
        raise FreezeBaselineV04Error(
            "v0.4 frozen formal divergence count must be 3"
        )

    linkage = build_formal_warning_linkage(
        symbol=SYMBOL,
        signals=result.signals,
        warning_events=result.warning_events,
        display_start_date=DISPLAY_START_DATE,
        display_end_date=DISPLAY_END_DATE,
    )
    if len(linkage) != 3 or not linkage["linkage_status"].eq("MATCHED").all():
        raise FreezeBaselineV04Error(
            "v0.4 formal-warning linkage must contain 3 unique matches"
        )
    signal_caps = result.signals.loc[
        result.signals["pending_action_type"] == APPLY_SIGNAL_CAP
    ]
    if signal_caps["divergence_position_cap"].astype(float).tolist() != [
        0.7,
        0.4,
        0.0,
    ]:
        raise FreezeBaselineV04Error(
            "v0.4 formal signal-cap sequence mismatch"
        )
    warning_summary["linkage_count"] = len(linkage)
    return warning_summary


def compare_v03_common_members(
    archive_bytes: bytes,
    v03_baseline: str | Path = V03_BASELINE_PATH,
) -> dict[str, str]:
    """Require every pre-warning formal member to remain byte-identical."""

    v03_path = Path(v03_baseline)
    if not v03_path.is_file():
        raise FreezeBaselineV04Error(
            f"v0.3 frozen baseline ZIP not found: {v03_path}"
        )
    v03_bytes = v03_path.read_bytes()
    v03_sha = hashlib.sha256(v03_bytes).hexdigest().upper()
    if v03_sha != V03_BASELINE_SHA256:
        raise FreezeBaselineV04Error(
            f"v0.3 frozen baseline SHA-256 mismatch: {v03_sha}"
        )
    try:
        with zipfile.ZipFile(BytesIO(v03_bytes)) as v03, zipfile.ZipFile(
            BytesIO(archive_bytes)
        ) as v04:
            hashes: dict[str, str] = {}
            for filename in COMMON_V03_MEMBERS:
                member = f"{SYMBOL}/{filename}"
                v03_member = v03.read(member)
                v04_member = v04.read(member)
                if v03_member != v04_member:
                    raise FreezeBaselineV04Error(
                        f"v0.3/v0.4 formal member changed: {member}"
                    )
                hashes[filename] = hashlib.sha256(v04_member).hexdigest().upper()
    except (zipfile.BadZipFile, KeyError) as exc:
        raise FreezeBaselineV04Error(
            "invalid v0.3/v0.4 isolation archive"
        ) from exc
    return hashes


def freeze_baseline(
    source_baseline: str | Path,
    output: str | Path,
) -> dict[str, object]:
    source_path = Path(source_baseline)
    output_path = Path(output)
    if source_path.resolve() == output_path.resolve():
        raise FreezeBaselineV04Error(
            "source baseline and output must be different files"
        )

    release_summary = validate_frozen_baseline(source_path)
    bars = load_frozen_bars(source_path)
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / CONFIG_PATH)
    formal_member_config = load_config(
        project_root / FORMAL_MEMBER_CONFIG_PATH
    )
    _validate_config_isolation(formal_member_config, config)
    result = analyze_bars(
        bars,
        symbol=SYMBOL,
        name=NAME,
        config=formal_member_config,
        display_start_date=DISPLAY_START_DATE,
        display_end_date=DISPLAY_END_DATE,
    )
    warning_summary = validate_release_result(result)
    key_rows = _key_sequence_rows(result.signals)
    archive_bytes = build_frozen_archive(
        result,
        config,
        input_baseline_sha256=str(release_summary["sha256"]),
        formal_divergence_count=int(release_summary["formal_divergences"]),
    )
    common_member_sha256 = compare_v03_common_members(archive_bytes)

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
        "warning_summary": warning_summary,
        "common_member_sha256": common_member_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic rsi-exit v0.4.0 frozen baseline"
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
        print(f"v0.4 frozen baseline generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"v0.4 frozen baseline created: {summary['output']} "
        f"sha256={summary['sha256']}"
    )
    print("key sequence:")
    for row in summary["key_sequence"]:
        print(row)
    return 0


def _validate_identity(result: AnalysisResult, config: RsiExitConfig) -> None:
    versions = {
        "rsi_exit.__version__": __version__,
        CONFIG_PATH: config.values.get("version"),
    }
    if set(versions.values()) != {FREEZE_VERSION}:
        raise FreezeBaselineV04Error(
            f"v0.4.0 version identity mismatch: {versions}"
        )
    if result.symbol != SYMBOL:
        raise FreezeBaselineV04Error(
            f"frozen result symbol mismatch: expected {SYMBOL}, got {result.symbol}"
        )


def _validate_config_isolation(
    formal_member_config: RsiExitConfig,
    release_config: RsiExitConfig,
) -> None:
    formal_values = deepcopy(formal_member_config.values)
    release_values = deepcopy(release_config.values)
    if formal_values.pop("version", None) != "0.3.0":
        raise FreezeBaselineV04Error(
            "formal member compatibility config must be v0.3.0"
        )
    if release_values.pop("version", None) != FREEZE_VERSION:
        raise FreezeBaselineV04Error(
            "release config must be v0.4.0"
        )
    if formal_values != release_values:
        raise FreezeBaselineV04Error(
            "v0.3/v0.4 business configuration mismatch"
        )


def _warning_summary(events: pd.DataFrame) -> dict[str, object]:
    normalized = _normalized_event_frame(events)
    models = _validate_warning_contract(normalized)
    states = derive_warning_states(models, as_of_date=DISPLAY_END_DATE)
    event_counts = _counts(normalized["lifecycle_event"], LIFECYCLE_EVENTS)
    display = normalized.loc[
        normalized["is_display_range"].astype(bool)
    ]
    display_event_counts = _counts(
        display["lifecycle_event"], LIFECYCLE_EVENTS
    )
    status_counts = _counts(
        pd.Series(
            [getattr(status, "value", str(status)) for status in states.values()],
            dtype=object,
        ),
        WARNING_STATUSES,
    )
    return {
        "event_counts": event_counts,
        "display_event_counts": display_event_counts,
        "status_counts": status_counts,
        "linkage_count": event_counts["ESCALATED"],
    }


def _counts(values: pd.Series, keys: tuple[str, ...]) -> dict[str, int]:
    counts = values.astype(str).value_counts().to_dict()
    return {key: int(counts.get(key, 0)) for key in keys}


if __name__ == "__main__":
    raise SystemExit(main())
