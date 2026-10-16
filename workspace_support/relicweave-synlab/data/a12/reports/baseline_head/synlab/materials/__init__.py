"""A12 materials package (plan 8): material profiles, the pure query field and layer stacks.

The package re-exports the façade functions so ``synlab.materials`` itself satisfies the
capability probe in ``synlab.api.capabilities`` (``build_material_profile``, ``material_at``,
``layer_combo``); the implementation lives in :mod:`synlab.materials.api`.
"""

from __future__ import annotations

from . import catalogue, fields, layers  # noqa: F401  (import registers M01..M12, L01..L04)
from .api import (
    MODE_GEOMETRIC,
    MODE_SHADING,
    UNCALIBRATED_MECHANICS,
    build_material_profile,
    canonical_material_params,
    combo_definition,
    combo_entry,
    combo_geometric_layers,
    combo_ids,
    commit_material,
    default_material_params,
    layer_combo,
    load_material,
    material_at,
    material_entry,
    material_ids,
    validate_profile,
)
from .layers import LayerShell, build_layer_shell, erode_mother, measure_layer_thickness

__all__ = [
    "build_material_profile", "material_at", "layer_combo", "commit_material", "load_material",
    "validate_profile", "material_ids", "combo_ids", "material_entry", "combo_entry",
    "default_material_params", "canonical_material_params", "combo_definition",
    "combo_geometric_layers", "build_layer_shell", "erode_mother", "measure_layer_thickness",
    "LayerShell", "MODE_SHADING", "MODE_GEOMETRIC", "UNCALIBRATED_MECHANICS",
    "catalogue", "layers", "fields",
]
