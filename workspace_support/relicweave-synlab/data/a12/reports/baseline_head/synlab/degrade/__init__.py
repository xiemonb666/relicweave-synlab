"""``synlab.degrade``: the 31-axis degradation registry, operators and façade (plan 15, 30.9).

The package exports

* :data:`axis_registry` / :data:`AXIS_REGISTRY` -- the process-wide :class:`AxisRegistry`
  that ``synlab.registry.load_all`` imports for its side effect of registering all 31 axes;
* :func:`compile_recipe`, :func:`apply_axis`, :func:`audit_axis`, :func:`audit_all_axes`
  -- the frozen façade in ``docs/a12/interfaces.md`` section 2 (imported lazily so that
  importing the registry never drags in ``synlab.config``).

Nothing in this package re-writes the source at level 0 and nothing reports a declared
effect that was not measured.
"""

from __future__ import annotations

from typing import Any

from .registry import (
    ALL_MATERIALS,
    AXIS_REGISTRY,
    FACTOR_KINDS,
    AxisOperator,
    AxisRegistry,
    basis_rng,
    get_operator,
    register_operator,
    summary_table,
)

#: Alias imported by ``synlab.registry.load_all`` (``from .degrade import axis_registry``).
axis_registry = AXIS_REGISTRY

_LAZY = {
    "compile_recipe": (".api", "compile_recipe"),
    "apply_axis": (".api", "apply_axis"),
    "audit_axis": (".api", "audit_axis"),
    "audit_all_axes": (".api", "audit_all_axes"),
    "operator_audit_table": (".api", "operator_audit_table"),
    "write_operator_measurements": (".api", "write_operator_measurements"),
    "SourceBundle": (".sources", "SourceBundle"),
    "OutputRef": (".sources", "OutputRef"),
    "commit_source": (".sources", "commit_source"),
    "load_source": (".sources", "load_source"),
    "run_recipe": (".api", "run_recipe"),
}

__all__ = [
    "axis_registry", "AXIS_REGISTRY", "AxisRegistry", "AxisOperator", "get_operator",
    "register_operator", "basis_rng", "summary_table", "ALL_MATERIALS", "FACTOR_KINDS",
    "compile_recipe", "apply_axis", "audit_axis", "audit_all_axes", "operator_audit_table",
    "write_operator_measurements", "run_recipe",
    "SourceBundle", "OutputRef", "commit_source", "load_source",
]


def __getattr__(name: str) -> Any:
    """PEP 562 lazy façade access (keeps ``import synlab.degrade`` free of import cycles)."""
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(target[0], __name__)
    value = getattr(module, target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
