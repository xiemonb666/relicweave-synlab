"""Central registry for vessels, materials, patterns, fracture backends, layers and axes.

Every registered capability exposes: id, kind, display name, version, parameter JSON
schema, applicability matrix, implementation entry point and honest status.  The CLI,
the API and the UI all read this registry instead of duplicating ranges or enumerations.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .canonical import hash_json
from .errors import ErrorCode, SynLabError

KINDS = ("vessel", "material", "layer_combo", "pattern", "fracture_backend", "axis", "operator_stage")

STATUS_SPECIFIED = "SPECIFIED"
STATUS_IMPLEMENTED = "IMPLEMENTED"
STATUS_QA_PASSED = "QA_PASSED"
STATUS_VALIDATED = "VALIDATED"
STATUS_PENDING = "PENDING"
STATUS_MISSING = "MISSING"


@dataclass
class RegistryEntry:
    id: str
    kind: str
    name: str
    version: str
    module: str
    builder: Callable[..., Any] | None = None
    param_model: Any | None = None
    applicable: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_IMPLEMENTED
    notes: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def param_schema(self) -> dict[str, Any]:
        if self.param_model is None:
            return {"type": "object", "additionalProperties": True}
        return self.param_model.model_json_schema()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "name": self.name, "version": self.version,
            "module": self.module, "status": self.status, "notes": self.notes,
            "applicable": self.applicable, "param_schema": self.param_schema,
            "has_builder": self.builder is not None, "meta": self.meta,
        }


class Registry:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], RegistryEntry] = {}

    # ------------------------------------------------------------------ mutation
    def register(self, entry: RegistryEntry) -> RegistryEntry:
        key = (entry.kind, entry.id)
        if key in self._entries:
            existing = self._entries[key]
            if existing.module == entry.module and existing.builder is entry.builder:
                return existing
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"duplicate registration {entry.kind}/{entry.id} "
                              f"({existing.module} vs {entry.module})", stage="registry.register")
        self._entries[key] = entry
        return entry

    def resolve_builder(self, kind: str, id: str) -> Callable[..., Any]:
        entry = self.get(kind, id)
        if entry.builder is not None:
            return entry.builder
        if entry.module:
            module = importlib.import_module(entry.module)
            builder = getattr(module, entry.meta.get("builder_name", ""), None)
            if builder is not None:
                entry.builder = builder
                return builder
        raise SynLabError(ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                          f"{kind}/{id} has no implementation entry point", stage="registry.resolve")

    # ------------------------------------------------------------------ queries
    def get(self, kind: str, id: str) -> RegistryEntry:
        key = (kind, id)
        if key not in self._entries:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unregistered {kind} id {id!r}", stage="registry.get")
        return self._entries[key]

    def has(self, kind: str, id: str) -> bool:
        return (kind, id) in self._entries

    def list(self, kind: str | None = None, *, status: str | None = None) -> list[RegistryEntry]:
        entries = [e for (k, _), e in sorted(self._entries.items()) if kind is None or k == kind]
        if status:
            entries = [e for e in entries if e.status == status]
        return entries

    def ids(self, kind: str) -> list[str]:
        return [e.id for e in self.list(kind)]

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for kind in KINDS:
            entries = self.list(kind)
            if not entries:
                continue
            out[kind] = {
                "count": len(entries),
                "by_status": _counts(e.status for e in entries),
                "ids": [e.id for e in entries],
            }
        return out

    def fingerprint(self) -> str:
        return hash_json([e.as_dict() for e in self.list()])

    def dump(self, path: str) -> None:
        payload = {f"{e.kind}/{e.id}": e.as_dict() for e in self.list()}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _counts(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


#: Process-wide registry.  Modules register themselves at import time.
REGISTRY = Registry()


def register_vessel(id: str, name: str, *, version: str = "1.0", param_model: Any = None,
                    applicable: dict[str, Any] | None = None, notes: str = "",
                    status: str = STATUS_IMPLEMENTED, module: str | None = None) -> Callable:
    return _register("vessel", id, name, version, param_model, applicable, notes, status, module)


def register_material(id: str, name: str, *, version: str = "1.0", param_model: Any = None,
                      applicable: dict[str, Any] | None = None, notes: str = "",
                      status: str = STATUS_IMPLEMENTED, module: str | None = None) -> Callable:
    return _register("material", id, name, version, param_model, applicable, notes, status, module)


def register_layer_combo(id: str, name: str, *, version: str = "1.0", param_model: Any = None,
                         applicable: dict[str, Any] | None = None, notes: str = "",
                         status: str = STATUS_IMPLEMENTED, module: str | None = None) -> Callable:
    return _register("layer_combo", id, name, version, param_model, applicable, notes, status, module)


def register_pattern(id: str, name: str, *, version: str = "1.0", param_model: Any = None,
                     applicable: dict[str, Any] | None = None, notes: str = "",
                     status: str = STATUS_IMPLEMENTED, module: str | None = None) -> Callable:
    return _register("pattern", id, name, version, param_model, applicable, notes, status, module)


def register_fracture_backend(id: str, name: str, *, version: str = "1.0", param_model: Any = None,
                              applicable: dict[str, Any] | None = None, notes: str = "",
                              status: str = STATUS_IMPLEMENTED, module: str | None = None) -> Callable:
    return _register("fracture_backend", id, name, version, param_model, applicable, notes, status, module)


def register_axis(id: str, name: str, *, version: str = "1.0", param_model: Any = None,
                  applicable: dict[str, Any] | None = None, notes: str = "",
                  status: str = STATUS_IMPLEMENTED, module: str | None = None) -> Callable:
    return _register("axis", id, name, version, param_model, applicable, notes, status, module)


def _register(kind: str, id: str, name: str, version: str, param_model: Any,
              applicable: dict[str, Any] | None, notes: str, status: str,
              module: str | None) -> Callable:
    def decorator(func: Callable) -> Callable:
        REGISTRY.register(RegistryEntry(
            id=id, kind=kind, name=name, version=version,
            module=module or getattr(func, "__module__", ""),
            builder=func, param_model=param_model, applicable=applicable or {},
            status=status, notes=notes,
            meta={"builder_name": getattr(func, "__name__", "")},
        ))
        return func

    return decorator


def load_all() -> dict[str, Any]:
    """Import every implementation module so the registry is fully populated.

    Missing optional backends are reported, never hidden.
    """
    from . import fracture, materials, mothers, patterns, physical  # noqa: F401
    from .degrade import axis_registry  # noqa: F401

    reports: dict[str, Any] = {}
    # Registration happens in the façade modules (vessels, backends, axes), so import those
    # explicitly instead of only the packages; a missing façade is reported, never hidden.
    for module_name in ("synlab.mothers", "synlab.mothers.api", "synlab.materials",
                        "synlab.materials.api", "synlab.patterns", "synlab.patterns.api",
                        "synlab.fracture", "synlab.fracture.api", "synlab.degrade.axes",
                        "synlab.degrade.api", "synlab.physical"):
        try:
            importlib.import_module(module_name)
            reports[module_name] = "OK"
        except Exception as exc:  # pragma: no cover - reported honestly
            reports[module_name] = f"{type(exc).__name__}: {exc}"

    # The 31 degradation axes live in their own registry; mirror them into the global one so
    # the CLI, the API and the status matrix see one authoritative capability list.
    try:
        from .degrade.registry import get_operator
        from .schemas.spec import AXIS_IDS

        for axis_id in AXIS_IDS:
            if REGISTRY.has("axis", axis_id):
                continue
            try:
                operator = get_operator(axis_id)
                REGISTRY.register(RegistryEntry(
                    id=axis_id, kind="axis",
                    name=getattr(operator, "NAME", axis_id),
                    version=str(getattr(operator, "VERSION", "1.0")),
                    module=type(operator).__module__,
                    applicable=_jsonable(getattr(operator, "APPLICABLE", {}) or {}),
                    status=STATUS_IMPLEMENTED,
                    notes=str(getattr(operator, "NOTES", ""))[:200],
                    meta={"stage": str(getattr(operator, "STAGE", "")),
                          "unit": str(getattr(operator, "UNIT", ""))},
                ))
            except Exception as exc:  # axis missing or not importable: record it as MISSING
                REGISTRY.register(RegistryEntry(
                    id=axis_id, kind="axis", name=axis_id, version="1.0",
                    module="synlab.degrade.registry", status=STATUS_MISSING,
                    notes=f"{type(exc).__name__}: {exc}"[:200],
                ))
    except Exception as exc:  # pragma: no cover
        reports["synlab.degrade.registry"] = f"{type(exc).__name__}: {exc}"
    return reports


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
