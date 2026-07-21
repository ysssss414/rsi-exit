from __future__ import annotations

import importlib
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

import numpy as np
import pandas as pd

from rsi_exit.data.cache import CsvBarCache
from rsi_exit.data.numba_compat import install_numba_compat


LOGGER = logging.getLogger(__name__)
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


class DataSourceError(RuntimeError):
    pass


class AmazingDataAdapter:
    """Reuse the verified legacy AmazingDataProvider behind a stable v0.1 API."""

    def __init__(
        self,
        *,
        legacy_provider_root: str | Path,
        cache_dir: str | Path,
        retry_count: int = 3,
        retry_delay_seconds: float = 1.0,
        use_numba_compat: bool = True,
    ) -> None:
        self.legacy_provider_root = Path(legacy_provider_root).resolve()
        self.cache_dir = Path(cache_dir).resolve()
        self.retry_count = max(1, int(retry_count))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.use_numba_compat = bool(use_numba_compat)
        self.cache = CsvBarCache(self.cache_dir)
        self._session_provider: Any | None = None

    def get_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "forward",
        *,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Return ascending, unique A-share daily bars in the standard schema."""
        symbol = _validate_symbol(symbol)
        start = _normalize_date_text(start_date)
        end = _normalize_date_text(end_date)
        if start > end:
            raise ValueError("start_date 不得晚于 end_date")
        adjust_key = adjust.lower()
        if adjust_key not in {"forward", "none", "raw"}:
            raise ValueError("adjust 当前仅支持 forward、none 或 raw")

        cached = None if force_refresh else self.cache.read(symbol, start, end)
        if cached is not None:
            LOGGER.info("Using cached raw AmazingData bars: %s %s..%s", symbol, start, end)
            raw = self._validate_bars(cached, symbol)
        else:
            raw, factor = self._fetch_with_retry(
                symbol, start, end, fetch_factor=adjust_key == "forward", force_refresh=force_refresh
            )
            raw = self._validate_bars(raw, symbol)
            cache_path = self.cache.write(raw, symbol, start, end)
            LOGGER.info("Cached raw AmazingData bars: %s", cache_path)
            if adjust_key == "forward":
                adjusted = self._apply_forward_adjustment(raw, factor, symbol)
                adjusted.attrs.update(
                    source="AmazingData",
                    adjust="forward",
                    raw_cache_path=str(cache_path),
                )
                return adjusted

        if adjust_key == "forward":
            factor = self._fetch_factor_with_retry(symbol, force_refresh=force_refresh)
            result = self._apply_forward_adjustment(raw, factor, symbol)
        else:
            result = raw.copy()
        result.attrs.update(source="AmazingData", adjust=adjust_key)
        return result

    def get_trade_calendar(self) -> list[int]:
        return self._call_with_retry(lambda provider: provider.get_trade_calendar())

    def get_code_info(self) -> pd.DataFrame:
        frame = self._call_with_retry(lambda provider: provider.get_code_info())
        if not isinstance(frame, pd.DataFrame):
            raise DataSourceError("AmazingData code info 未返回 DataFrame")
        return frame.copy()

    def resolve_symbol(self, name_or_symbol: str) -> tuple[str, str | None]:
        value = name_or_symbol.strip()
        if value.upper().endswith((".SZ", ".SH", ".BJ")):
            info = self.get_code_info()
            match = info.loc[info["code"].astype(str).str.upper() == value.upper()]
            name = None if match.empty else str(match.iloc[0]["name"])
            return value.upper(), name
        info = self.get_code_info()
        matches = info.loc[info["name"].astype(str) == value]
        if len(matches) != 1:
            raise DataSourceError(f"证券名称 {value!r} 匹配到 {len(matches)} 个代码")
        row = matches.iloc[0]
        return str(row["code"]), str(row["name"])

    def close(self) -> None:
        """Release the single SDK session after outputs have been persisted."""
        if self._session_provider is None:
            return
        self._session_provider.logout()
        self._session_provider = None

    def _fetch_with_retry(
        self,
        symbol: str,
        start: str,
        end: str,
        *,
        fetch_factor: bool,
        force_refresh: bool,
    ) -> tuple[pd.DataFrame, pd.DataFrame | None]:
        def operation(provider: Any) -> tuple[pd.DataFrame, pd.DataFrame | None]:
            raw = provider.get_daily_bars(
                symbol, int(start.replace("-", "")), int(end.replace("-", ""))
            )
            factor = (
                self._fetch_factor_from_provider(provider, symbol, force_refresh)
                if fetch_factor
                else None
            )
            return raw, factor

        return self._call_with_retry(operation)

    def _fetch_factor_with_retry(self, symbol: str, *, force_refresh: bool) -> pd.DataFrame:
        return self._call_with_retry(
            lambda provider: self._fetch_factor_from_provider(provider, symbol, force_refresh)
        )

    def _fetch_factor_from_provider(
        self, provider: Any, symbol: str, force_refresh: bool
    ) -> pd.DataFrame:
        base = getattr(provider, "base", None)
        if base is None or not hasattr(base, "get_backward_factor"):
            raise DataSourceError("现有 AmazingData Provider 未暴露 BaseData.get_backward_factor")
        factor_dir = self.cache_dir / "factors"
        factor_dir.mkdir(parents=True, exist_ok=True)
        raw = base.get_backward_factor(
            [symbol], local_path=str(factor_dir) + os.sep, is_local=not force_refresh
        )
        return pd.DataFrame(raw).copy()

    def _call_with_retry(self, operation: Any) -> Any:
        last_error: BaseException | None = None
        for attempt in range(1, self.retry_count + 1):
            try:
                with self._provider() as provider:
                    return operation(provider)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "AmazingData attempt %s/%s failed: %s",
                    attempt,
                    self.retry_count,
                    exc,
                )
                if attempt < self.retry_count and self.retry_delay_seconds:
                    time.sleep(self.retry_delay_seconds)
        assert last_error is not None
        raise DataSourceError(
            f"AmazingData 请求在 {self.retry_count} 次尝试后失败: {last_error}"
        ) from last_error

    @contextmanager
    def _provider(self) -> Iterator[Any]:
        if self._session_provider is not None:
            yield self._session_provider
            return
        module = self._load_legacy_module()
        provider_class = getattr(module, "AmazingDataProvider", None)
        if provider_class is None:
            raise DataSourceError("旧 Provider 中缺少 AmazingDataProvider")
        if self.use_numba_compat:
            install_numba_compat()
        provider = provider_class()
        provider.login()
        self._session_provider = provider
        try:
            yield provider
        finally:
            # AmazingData 1.1.6 logout terminates the native process in the
            # audited Windows/Python 3.10 runtime before callers can persist
            # returned data. CLI processes are short-lived, so deliberately
            # leave native cleanup to process teardown.
            LOGGER.debug("Skipping unstable AmazingData 1.1.6 native logout")

    def _load_legacy_module(self) -> ModuleType:
        provider_file = self.legacy_provider_root / "yh_quant_shape" / "data_provider.py"
        if not provider_file.exists():
            raise DataSourceError(f"未找到已审计的旧 Provider: {provider_file}")
        root_text = str(self.legacy_provider_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        return importlib.import_module("yh_quant_shape.data_provider")

    @staticmethod
    def _validate_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if not isinstance(raw, pd.DataFrame):
            raise DataSourceError("AmazingData 日 K 必须返回 DataFrame")
        frame = raw.copy()
        missing = set(STANDARD_COLUMNS) - set(frame.columns)
        if missing:
            raise DataSourceError(f"{symbol} 日 K 缺少字段: {', '.join(sorted(missing))}")
        frame = frame[STANDARD_COLUMNS].copy()
        frame["date"] = pd.to_datetime(frame["date"].astype(str), errors="coerce")
        for column in STANDARD_COLUMNS[1:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame.empty:
            raise DataSourceError(f"{symbol} 没有返回日 K")
        if frame.isna().any().any():
            bad = frame.columns[frame.isna().any()].tolist()
            raise DataSourceError(f"{symbol} 日 K 存在缺失值: {', '.join(bad)}")
        frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        invalid_ohlc = (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
            | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (frame[["volume", "amount"]] < 0).any(axis=1)
        )
        if invalid_ohlc.any():
            dates = frame.loc[invalid_ohlc, "date"].dt.strftime("%Y-%m-%d").tolist()
            raise DataSourceError(f"{symbol} 日 K OHLC/成交字段非法: {dates[:5]}")
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        return frame

    @staticmethod
    def _apply_forward_adjustment(
        raw: pd.DataFrame, factor_raw: pd.DataFrame | None, symbol: str
    ) -> pd.DataFrame:
        if factor_raw is None or factor_raw.empty:
            raise DataSourceError(f"{symbol} 前复权因子为空")
        factor = factor_raw.copy()
        if symbol in factor.columns:
            values = pd.to_numeric(factor[symbol], errors="coerce")
        elif len(factor.columns) == 1:
            values = pd.to_numeric(factor.iloc[:, 0], errors="coerce")
        else:
            raise DataSourceError(f"{symbol} 复权因子中找不到证券列")
        dates = pd.to_datetime(factor.index.astype(str), errors="coerce")
        if dates.isna().all() and "date" in factor.columns:
            dates = pd.to_datetime(factor["date"].astype(str), errors="coerce")
        series = pd.Series(values.to_numpy(dtype=float), index=dates).dropna()
        series = series[~series.index.isna()].sort_index()
        series = series[~series.index.duplicated(keep="last")]
        bar_dates = pd.to_datetime(raw["date"])
        aligned = series.reindex(bar_dates).ffill()
        if aligned.isna().any():
            first_missing = bar_dates[aligned.isna().to_numpy()][0]
            raise DataSourceError(
                f"{symbol} 在 {first_missing:%Y-%m-%d} 缺少可用前复权因子"
            )
        latest_factor = float(aligned.iloc[-1])
        if not np.isfinite(latest_factor) or latest_factor == 0:
            raise DataSourceError(f"{symbol} 最新复权因子非法")
        ratio = aligned.to_numpy(dtype=float) / latest_factor
        output = raw.copy()
        for column in ("open", "high", "low", "close"):
            output[column] = pd.to_numeric(output[column], errors="raise") * ratio
        return output


def _normalize_date_text(value: str) -> str:
    parsed = pd.to_datetime(value, errors="raise")
    return parsed.strftime("%Y-%m-%d")


def _validate_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol.endswith((".SZ", ".SH", ".BJ")):
        raise ValueError("symbol 必须使用 AmazingData 代码格式，例如 300308.SZ")
    return symbol
