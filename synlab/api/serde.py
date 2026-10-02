"""JSON sanitisation for objects coming out of the scientific modules.

Parallel modules return ``numpy`` arrays, dataclasses and enums.  The API must be able to
serialise them without silently dropping content, and it must never leak a filesystem path.
Arrays are summarised by shape/dtype/content hash plus a bounded sample so a response stays
a *reference* to data rather than an accidental bulk download.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from pathlib import Path
from typing import Any

MAX_LIST = 512
MAX_SAMPLE = 8


def jsonable(value: Any, *, depth: int = 0) -> Any:
    """Best-effort conversion of module output into JSON-safe primitives."""
    if depth > 12:
        return "<max-depth>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return value.name
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": len(bytes(value))}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name), depth=depth + 1)
                for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): jsonable(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        out = [jsonable(v, depth=depth + 1) for v in items[:MAX_LIST]]
        if len(items) > MAX_LIST:
            out.append(f"<{len(items) - MAX_LIST} more items elided>")
        return out
    if hasattr(value, "model_dump"):
        try:
            return jsonable(value.model_dump(mode="json"), depth=depth + 1)
        except Exception:  # noqa: BLE001 - fall through to the generic handlers
            pass
    if hasattr(value, "as_dict") and callable(value.as_dict):
        try:
            return jsonable(value.as_dict(), depth=depth + 1)
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "tolist") and hasattr(value, "shape") and hasattr(value, "dtype"):
        return _array_summary(value, depth=depth)
    if hasattr(value, "item"):
        try:
            return jsonable(value.item(), depth=depth + 1)
        except Exception:  # noqa: BLE001
            pass
    return f"<{type(value).__name__}>"


def _array_summary(array: Any, *, depth: int) -> dict[str, Any]:
    from ..canonical import array_hash

    summary: dict[str, Any] = {
        "__array__": True,
        "dtype": str(array.dtype),
        "shape": list(array.shape),
        "hash": array_hash(array),
    }
    if array.size == 0 or array.ndim > 2:
        return summary
    flat = array.reshape(-1)
    if flat.size <= MAX_SAMPLE:
        summary["values"] = [jsonable(v, depth=depth + 1) for v in flat.tolist()]
    else:
        step = max(1, flat.size // MAX_SAMPLE)
        summary["sample"] = [jsonable(v, depth=depth + 1) for v in flat[::step][:MAX_SAMPLE].tolist()]
        summary["sample_stride"] = step
    return summary
