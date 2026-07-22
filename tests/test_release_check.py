from __future__ import annotations

from pathlib import Path

from rsi_exit.release_check import main


def test_release_check_missing_file_returns_nonzero(capsys) -> None:
    missing = Path("tests/fixtures/definitely-missing-frozen-baseline.zip")
    exit_code = main(["--frozen-baseline", str(missing)])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "frozen baseline ZIP not found" in captured.err
