from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile

import pandas as pd

from rsi_exit.config import load_config
from rsi_exit.freeze_baseline import (
    BASELINE_SHA256,
    CONFIG_PATH,
    FREEZE_VERSION,
    INPUT_BASELINE_FILENAME,
    SEMANTIC_BASE_COMMIT,
    SYMBOL,
    ZIP_TIMESTAMP,
    build_frozen_archive,
    main,
    validate_frozen_archive,
)
from rsi_exit.pipeline import AnalysisResult


SANITIZED_FIXTURE = (
    Path(__file__).parent / "fixtures" / "v03_sanitized_canonical_sequence.csv"
)


def _sanitized_result() -> AnalysisResult:
    sequence = pd.read_csv(SANITIZED_FIXTURE)
    return AnalysisResult(
        symbol=SYMBOL,
        name="sanitized",
        daily_features=sequence.copy(),
        peaks=sequence.copy(),
        canonical_peaks=sequence.copy(),
        signals=sequence.copy(),
        state_log=sequence.copy(),
        cycle_log=sequence.copy(),
        rsi_audit=sequence.copy(),
        warnings=[],
        metadata={},
    )


def _archive_bytes() -> bytes:
    return build_frozen_archive(
        _sanitized_result(),
        load_config(CONFIG_PATH),
        formal_divergence_count=3,
    )


def test_deterministic_archive_is_byte_identical(tmp_path) -> None:
    path_a = tmp_path / "archive_a.zip"
    path_b = tmp_path / "archive_b.zip"
    path_a.write_bytes(_archive_bytes())
    path_b.write_bytes(_archive_bytes())
    archive_a = path_a.read_bytes()
    archive_b = path_b.read_bytes()
    assert sha256(archive_a).hexdigest() == sha256(archive_b).hexdigest()
    with zipfile.ZipFile(BytesIO(archive_a)) as first, zipfile.ZipFile(
        BytesIO(archive_b)
    ) as second:
        assert first.namelist() == second.namelist()
        assert [first.read(name) for name in first.namelist()] == [
            second.read(name) for name in second.namelist()
        ]


def test_manifest_is_complete_static_and_self_consistent() -> None:
    archive_bytes = _archive_bytes()
    manifest = validate_frozen_archive(archive_bytes)
    assert manifest["version"] == FREEZE_VERSION == "0.3.0"
    assert manifest["semantic_base_commit"] == SEMANTIC_BASE_COMMIT
    assert manifest["input_baseline_filename"] == INPUT_BASELINE_FILENAME
    assert manifest["input_baseline_sha256"] == BASELINE_SHA256
    assert manifest["config"] == CONFIG_PATH
    assert manifest["members"] == sorted(manifest["members"])

    manifest_member = f"{SYMBOL}/freeze_manifest.json"
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        assert archive.namelist() == manifest["members"]
        assert manifest_member not in manifest["member_sha256"]
        for member, expected in manifest["member_sha256"].items():
            assert sha256(archive.read(member)).hexdigest().upper() == expected
        assert all(info.date_time == ZIP_TIMESTAMP for info in archive.infolist())
        config_snapshot = archive.read(f"{SYMBOL}/config_snapshot.yaml").decode(
            "utf-8"
        )
        assert "legacy_provider_root" not in config_snapshot
        assert "cache_dir" not in config_snapshot
        assert "output" not in json.loads(config_snapshot)

    manifest_text = json.dumps(manifest, ensure_ascii=False)
    assert "generated_at" not in manifest_text
    assert "D:\\" not in manifest_text
    assert "/home/" not in manifest_text


def test_missing_input_fails_without_partial_archive(tmp_path, capsys) -> None:
    output = tmp_path / "missing.zip"
    exit_code = main([
        "--source-baseline",
        str(tmp_path / "not-found.zip"),
        "--output",
        str(output),
    ])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "frozen baseline ZIP not found" in captured.err
    assert not output.exists()


def test_input_sha_mismatch_fails_without_partial_archive(tmp_path, capsys) -> None:
    source = tmp_path / INPUT_BASELINE_FILENAME
    source.write_bytes(b"tampered baseline")
    output = tmp_path / "mismatch.zip"
    exit_code = main([
        "--source-baseline",
        str(source),
        "--output",
        str(output),
    ])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "SHA-256 mismatch" in captured.err
    assert not output.exists()


def test_missing_arguments_return_usage_exit_code(capsys) -> None:
    assert main([]) == 2
    assert "are required" in capsys.readouterr().err


def test_sanitized_canonical_sequence_round_trips_through_archive() -> None:
    expected = pd.read_csv(SANITIZED_FIXTURE)
    with zipfile.ZipFile(BytesIO(_archive_bytes())) as archive:
        actual = pd.read_csv(archive.open(f"{SYMBOL}/peaks.csv"))
    columns = [
        "candidate_peak_id",
        "canonical_peak_id",
        "canonical_version",
        "canonical_created",
        "canonical_updated",
        "expected_signal",
        "expected_count",
    ]
    pd.testing.assert_frame_equal(
        actual.loc[:, columns],
        expected.loc[:, columns],
        check_dtype=False,
    )
