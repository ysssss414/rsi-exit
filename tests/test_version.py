from __future__ import annotations

import tomllib
from pathlib import Path

import rsi_exit

from rsi_exit.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.2.1"


def test_public_version_sources_are_consistent() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject_version = tomllib.load(handle)["project"]["version"]
    config_version = load_config(
        PROJECT_ROOT / "config" / "rsi_exit_v02.yaml"
    ).values["version"]

    versions = {
        "rsi_exit.__version__": rsi_exit.__version__,
        "pyproject.toml project.version": pyproject_version,
        "config/rsi_exit_v02.yaml version": config_version,
    }
    for source, value in versions.items():
        assert value == EXPECTED_VERSION, (
            f"{source}={value!r}, expected {EXPECTED_VERSION!r}; "
            f"all version sources={versions!r}"
        )
