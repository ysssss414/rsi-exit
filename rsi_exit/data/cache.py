from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


class CsvBarCache:
    """Exact-request raw-bar cache; never fabricates missing trading dates."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def path_for(self, symbol: str, start_date: str, end_date: str) -> Path:
        key = f"{symbol}|{start_date}|{end_date}".encode("utf-8")
        digest = hashlib.sha256(key).hexdigest()[:12]
        safe_symbol = symbol.replace(".", "_").replace("/", "_")
        return self.root / "raw" / f"{safe_symbol}_{start_date}_{end_date}_{digest}.csv"

    def read(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        path = self.path_for(symbol, start_date, end_date)
        if not path.exists():
            return None
        return pd.read_csv(path, encoding="utf-8-sig")

    def write(
        self,
        frame: pd.DataFrame,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Path:
        path = self.path_for(symbol, start_date, end_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        return path

