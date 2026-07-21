from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, Callable


def install_numba_compat() -> None:
    """Install the same no-JIT shim used by the audited pyc-only SDK runtime.

    AmazingData 1.1.6 decorates functions from modules distributed without their
    ``.py`` sources. Real Numba refuses ``cache=True`` for those modules. The SDK
    only needs decorator semantics for this daily-bar workflow, so the verified
    compatibility path executes the Python functions without JIT caching.
    """
    module = ModuleType("numba")

    def njit(*args: Any, **kwargs: Any) -> Any:
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator

    module.njit = njit  # type: ignore[attr-defined]
    module.jit = njit  # type: ignore[attr-defined]
    module.prange = range  # type: ignore[attr-defined]
    sys.modules["numba"] = module
