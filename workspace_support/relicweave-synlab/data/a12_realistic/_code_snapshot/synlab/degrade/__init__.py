"""``synlab.degrade``: the 31-axis degradation registry, operators and façade (plan 15, 30.9).

The package exports

* :data:`axis_registry` / :data:`AXIS_REGISTRY` -- the process-wide :class:`AxisRegistry`
  that ``synlab.registry.load_all`` imports for its side effect of registering all 31 axes;
* :func:`compile_recipe`, :func:`apply_axis`, :func:`audit_axis`, :func:`audit_all_axes`
  -- the frozen façade in ``docs/a12/interfaces.md`` section 2 (imported lazily so that
  importing the registry never drags in ``synlab.config``).

Two **realism models** live beside the 31 axes and are not new axes (the axis set of
``synlab.schemas.spec.AXIS_IDS`` is frozen at 31 x 5 and the audit contract 155/155 depends on it):

* :mod:`synlab.degrade.wear` -- antique wear/aging, spatially structured and driven by measured
  physical quantities (wall thickness, curvature, the measured L01/L03 layer interval, material
  porosity/hardness);
* :mod:`synlab.degrade.rig_error` -- capture-rig error for the documented hardware (rolling
  shutter, manual-focus CoC, intrinsics/scale drift, the five documented light states,
  resolution-at-distance, reconstruction error);
* :mod:`synlab.degrade.mapping` -- the 14-component synthetic degradation vector vs. the 8-item
  real quality vector, with the inversion used for real-statistics calibration;
* :mod:`synlab.degrade.specs` -- the hardware/material catalogue with per-value provenance
  (``DOCUMENTED`` / ``DERIVED`` / ``CANDIDATE`` / ``UNKNOWN``), which is what makes "which number
  is measured and which still needs calibration" answerable.

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
    # degradation diversity (config-driven materialisation into the generation pipeline)
    "load_diversity_config": (".diversity", "load_diversity_config"),
    "materialize_lineage_diversity": (".diversity", "materialize_lineage_diversity"),
    "ROLE_DEGRADE_SOURCE": (".diversity", "ROLE_DEGRADE_SOURCE"),
    "ROLE_DEGRADE_VARIANT": (".diversity", "ROLE_DEGRADE_VARIANT"),
    # realism models (not axes): wear/aging, capture-rig error, the 14<->8 mapping, the catalogue
    "wear_apply": (".wear", "apply_wear"),
    "WearModel": (".wear", "WearModel"),
    "wear_legality_report": (".wear", "legality_report"),
    "RigErrorModel": (".rig_error", "RigErrorModel"),
    "scan_fault_ladder": (".rig_error", "scan_fault_ladder"),
    "capture_rig_spec": (".specs", "capture_rig_spec"),
    "light_modes": (".specs", "light_modes"),
    "mapping_table": (".mapping", "mapping_table"),
    "mapping_completeness": (".mapping", "mapping_completeness"),
    "levels_from_quality": (".mapping", "levels_from_quality"),
}

__all__ = [
    "axis_registry", "AXIS_REGISTRY", "AxisRegistry", "AxisOperator", "get_operator",
    "register_operator", "basis_rng", "summary_table", "ALL_MATERIALS", "FACTOR_KINDS",
    "compile_recipe", "apply_axis", "audit_axis", "audit_all_axes", "operator_audit_table",
    "write_operator_measurements", "run_recipe",
    "SourceBundle", "OutputRef", "commit_source", "load_source",
    "load_diversity_config", "materialize_lineage_diversity",
    "ROLE_DEGRADE_SOURCE", "ROLE_DEGRADE_VARIANT",
    "wear_apply", "WearModel", "wear_legality_report", "RigErrorModel", "scan_fault_ladder",
    "capture_rig_spec", "light_modes", "mapping_table", "mapping_completeness",
    "levels_from_quality",
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
