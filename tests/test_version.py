from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from pathlib import Path

import rsi_exit

from rsi_exit.config import load_config
from rsi_exit.freeze_baseline_v04 import FREEZE_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.4.0"
FREEZE_MANIFEST = (
    PROJECT_ROOT / "docs" / "releases" / "rsi_exit_v0.4.0_freeze_manifest.md"
)


def test_public_version_sources_are_consistent() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject_version = tomllib.load(handle)["project"]["version"]
    config_version = load_config().values["version"]

    versions = {
        "rsi_exit.__version__": rsi_exit.__version__,
        "pyproject.toml project.version": pyproject_version,
        "default config version": config_version,
        "freeze manifest version": FREEZE_VERSION,
    }
    for source, value in versions.items():
        assert value == EXPECTED_VERSION, (
            f"{source}={value!r}, expected {EXPECTED_VERSION!r}; "
            f"all version sources={versions!r}"
        )
    assert "Version: 0.4.0" in FREEZE_MANIFEST.read_text(encoding="utf-8")
