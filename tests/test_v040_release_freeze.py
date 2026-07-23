from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile

import pandas as pd

import rsi_exit
from rsi_exit.config import default_config_path, load_config
from rsi_exit.freeze_baseline import (
    ZIP_TIMESTAMP,
    validate_frozen_archive as validate_v03_archive,
)
from rsi_exit.freeze_baseline_v04 import (
    COMMON_V03_MEMBERS,
    CONFIG_PATH,
    FREEZE_VERSION,
    SEMANTIC_BASE_COMMIT,
    SYMBOL,
    TABLE_MEMBERS,
    V04_BASELINE_SHA256,
    build_frozen_archive,
    validate_frozen_archive,
)
from rsi_exit.pipeline import AnalysisResult
from rsi_exit.warning_events import WARNING_EVENT_COLUMNS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V03_CONFIG = PROJECT_ROOT / "config" / "rsi_exit_v03.yaml"
V04_CONFIG = PROJECT_ROOT / "config" / "rsi_exit_v04.yaml"
V03_BASELINE = (
    PROJECT_ROOT / "baselines" / "300308.SZ_v0.3.0_frozen_baseline.zip"
)
V04_BASELINE = (
    PROJECT_ROOT / "baselines" / "300308.SZ_v0.4.0_frozen_baseline.zip"
)
SANITIZED_FIXTURE = (
    Path(__file__).parent / "fixtures" / "v03_sanitized_canonical_sequence.csv"
)
V03_CONFIG_SHA256 = (
    "60DF8EB61E08EF2C54864A29068D63B637F360DDFDC4A27656F656BACA54EAAA"
)
V03_BASELINE_SHA256 = (
    "932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52"
)
PHASE_ARTIFACT_SHA256 = {
    "docs/validation/v04_phase4/outcome_summary.csv":
        "B5F89EF19DB1D1ECAA0378CF17BA816620862AAD2F7CC4B5883112FBE85180D0",
    "docs/validation/v04_phase4/sample_summary.csv":
        "47694B03C96CF7E4FD4A4CAD5F491854ADBF73CE468CA2CA562313EE90CBB101",
    "docs/validation/v04_phase4/validation_report.md":
        "656B7BBD33807F2CBE185C6F6058E6F00336A662C6E116BF6A195F5E24B86732",
    "docs/validation/v04_phase4/warning_outcomes.csv":
        "5A0166ECD1FE335674878F88F57492CB34A08E11170FF2155720D7C797443D7E",
    "docs/validation/v04_phase41_actionability/actionability_report.md":
        "3B0A093E0C3C2E173765A4352B1E1C4CD97A6DB2D18E5FDBE7366027A3CDA406",
    "docs/validation/v04_phase41_actionability/event_actionability_summary.csv":
        "43EEBC4448E38B6B6A8BE3429CD5BDC7F4A4A77406DBC28E7B0FA2E212D79C95",
    "docs/validation/v04_phase41_actionability/event_outcomes.csv":
        "41F4D68C04F6E5EBB7C4C732ACAC9F416F797A6166932404E29CA91998AD231A",
    "docs/validation/v04_phase41_actionability/formal_warning_linkage.csv":
        "7051291B79365190D36B9EF564142BF12564893144E11BDDE589476B71B5D9E9",
    "docs/validation/v04_phase41_actionability/opened_to_escalated.csv":
        "2E41D78F4BD5F19026D43FF9B01E5E4CE49781AF87E3F8BB9CD03836DD21A1C1",
}


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
        warning_events=pd.DataFrame(columns=WARNING_EVENT_COLUMNS),
    )


def _archive_bytes() -> bytes:
    return build_frozen_archive(
        _sanitized_result(),
        load_config(V04_CONFIG),
        formal_divergence_count=3,
    )


def _read_official_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    with zipfile.ZipFile(V04_BASELINE) as archive:
        events = pd.read_csv(archive.open(f"{SYMBOL}/warning_events.csv"))
        signals = pd.read_csv(archive.open(f"{SYMBOL}/signals.csv"))
    return events, signals


def test_v04_version_identity_and_default_config_are_consistent() -> None:
    assert rsi_exit.__version__ == FREEZE_VERSION == "0.4.0"
    assert default_config_path().resolve() == V04_CONFIG.resolve()
    assert load_config().values["version"] == "0.4.0"
    assert CONFIG_PATH == "config/rsi_exit_v04.yaml"
    assert SEMANTIC_BASE_COMMIT == "06e1468c0f76be13dbb3966707babc7a1d4dd281"

    baseline_bytes = V04_BASELINE.read_bytes()
    assert sha256(baseline_bytes).hexdigest().upper() == V04_BASELINE_SHA256
    with zipfile.ZipFile(BytesIO(baseline_bytes)) as archive:
        manifest = json.loads(
            archive.read(f"{SYMBOL}/freeze_manifest.json").decode("utf-8")
        )
    assert manifest["package"] == "rsi-exit"
    assert manifest["version"] == "0.4.0"
    assert manifest["semantic_base_commit"] == SEMANTIC_BASE_COMMIT
    assert manifest["warning_event_counts"] == {
        "CLEARED": 0,
        "ESCALATED": 3,
        "INVALIDATED": 4,
        "OPENED": 7,
        "REFRESHED": 9,
    }
    assert manifest["display_warning_event_counts"] == {
        "CLEARED": 0,
        "ESCALATED": 3,
        "INVALIDATED": 1,
        "OPENED": 4,
        "REFRESHED": 8,
    }
    assert manifest["warning_status_counts"] == {
        "ACTIVE": 0,
        "CLEARED": 0,
        "ESCALATED": 3,
        "INVALIDATED": 4,
    }
    assert manifest["formal_warning_linkage_count"] == 3
    assert manifest["warning_position_effect"] == "NONE"
    assert manifest["warning_recommended_position_cap"] is None


def test_v03_config_is_immutable_and_v04_only_changes_version() -> None:
    assert sha256(V03_CONFIG.read_bytes()).hexdigest().upper() == V03_CONFIG_SHA256
    v03 = load_config(V03_CONFIG).values
    v04 = load_config(V04_CONFIG).values
    assert v03["version"] == "0.3.0"
    assert v04["version"] == "0.4.0"
    v03_without_version = deepcopy(v03)
    v04_without_version = deepcopy(v04)
    del v03_without_version["version"]
    del v04_without_version["version"]
    assert v04_without_version == v03_without_version
    assert "warning" not in json.dumps(v04["position_caps"], sort_keys=True)


def test_v04_archive_is_deterministic_complete_and_static() -> None:
    archive_a = _archive_bytes()
    archive_b = _archive_bytes()
    assert archive_a == archive_b
    manifest = validate_frozen_archive(archive_a)
    expected_members = sorted(
        f"{SYMBOL}/{filename}" for filename, _ in TABLE_MEMBERS
    )
    expected_members.append(f"{SYMBOL}/config_snapshot.yaml")
    expected_members.append(f"{SYMBOL}/freeze_manifest.json")
    expected_members.sort()

    with zipfile.ZipFile(BytesIO(archive_a)) as archive:
        assert archive.namelist() == expected_members == manifest["members"]
        assert all(info.date_time == ZIP_TIMESTAMP for info in archive.infolist())
        assert f"{SYMBOL}/warning_events.csv" in archive.namelist()
        for member, expected in manifest["member_sha256"].items():
            assert sha256(archive.read(member)).hexdigest().upper() == expected
        config_snapshot = json.loads(
            archive.read(f"{SYMBOL}/config_snapshot.yaml").decode("utf-8")
        )
        assert config_snapshot["version"] == "0.4.0"

    archive_text = archive_a.decode("latin-1")
    for forbidden in (
        "annotated_chart.png",
        "summary.md",
        "AmazingData",
        "generated_at",
        "D:\\",
        "/home/",
    ):
        assert forbidden not in archive_text


def test_v03_archive_and_common_formal_members_are_byte_identical() -> None:
    v03_bytes = V03_BASELINE.read_bytes()
    assert sha256(v03_bytes).hexdigest().upper() == V03_BASELINE_SHA256
    v03_manifest = validate_v03_archive(v03_bytes)
    assert v03_manifest["version"] == "0.3.0"
    assert not any("warning_events" in name for name in v03_manifest["members"])

    with zipfile.ZipFile(V03_BASELINE) as v03, zipfile.ZipFile(
        V04_BASELINE
    ) as v04:
        # These outputs cover the base-state transitions, SignalCapQueue result,
        # and merged final position. Byte identity proves warnings changed none.
        assert {
            "daily_features.csv",
            "signals.csv",
            "state_log.csv",
        }.issubset(COMMON_V03_MEMBERS)
        for filename in COMMON_V03_MEMBERS:
            member = f"{SYMBOL}/{filename}"
            assert v04.read(member) == v03.read(member), member


def test_official_warning_history_is_position_neutral_and_frozen() -> None:
    events, _ = _read_official_frames()
    assert events["lifecycle_event"].value_counts().to_dict() == {
        "REFRESHED": 9,
        "OPENED": 7,
        "INVALIDATED": 4,
        "ESCALATED": 3,
    }
    display = events.loc[events["is_display_range"].astype(bool)]
    assert display["lifecycle_event"].value_counts().to_dict() == {
        "REFRESHED": 8,
        "OPENED": 4,
        "ESCALATED": 3,
        "INVALIDATED": 1,
    }
    latest = events.groupby("warning_id", sort=False).tail(1)
    assert latest["warning_status"].value_counts().to_dict() == {
        "INVALIDATED": 4,
        "ESCALATED": 3,
    }
    assert events["warning_event_id"].is_unique
    assert events["position_effect"].eq("NONE").all()
    assert events["recommended_position_cap"].isna().all()
    terminal = {"ESCALATED", "CLEARED", "INVALIDATED"}
    for _, history in events.groupby("warning_id", sort=False):
        terminal_rows = history["lifecycle_event"].isin(terminal)
        assert not terminal_rows.any() or terminal_rows.iloc[-1]


def test_escalated_delegates_once_to_existing_formal_signal_cap() -> None:
    events, signals = _read_official_frames()
    escalated = events.loc[events["lifecycle_event"] == "ESCALATED"]
    formal = signals.loc[
        signals["signal_status"].eq("FORMAL")
        & signals["signal_type"].isin({
            "NEW_HIGH_BEARISH_DIVERGENCE",
            "NEAR_HIGH_BEARISH_DIVERGENCE",
        })
        & signals["is_display_range"].astype(bool)
    ]
    formal_refs = {
        (
            f"{SYMBOL}|{row.signal_type}|{row.current_canonical_peak_id}"
            f"@v{int(row.current_canonical_version)}|{row.decision_date}|"
            f"{row.divergence_chain_id}"
        )
        for row in formal.itertuples(index=False)
    }
    assert len(formal_refs) == len(escalated) == 3
    assert set(escalated["linked_formal_signal_ref"]) == formal_refs
    assert escalated["linked_formal_signal_ref"].is_unique
    signal_caps = signals.loc[signals["pending_action_type"] == "APPLY_SIGNAL_CAP"]
    assert signal_caps["decision_date"].tolist() == escalated[
        "decision_date"
    ].tolist()
    assert signal_caps["divergence_position_cap"].tolist() == [0.7, 0.4, 0.0]
    assert escalated["position_effect"].eq("NONE").all()
    assert escalated["recommended_position_cap"].isna().all()


def test_phase4_and_phase41_committed_artifacts_are_byte_identical() -> None:
    for relative_path, expected in PHASE_ARTIFACT_SHA256.items():
        actual = sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest()
        assert actual.upper() == expected, relative_path
