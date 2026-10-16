"""Damage recipe description shared by :mod:`synlab.physical` and the P-axis operators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: P axes that only change appearance (their geometry hash must stay identical).
APPEARANCE_AXES = ("P05", "P06")
#: P08 variants and which of them touch geometry.
P08_VARIANTS = {
    "paint_coat_loss": "APPEARANCE",
    "geometric_coat_loss": "GEOMETRY",
    "geometry_crack": "GEOMETRY",
}
#: P06 variants; the thick soil variant adds an explicit contamination body (plan 12.3).
P06_VARIANTS = {"dirt_appearance": "APPEARANCE", "dirt_geometry": "CONTAMINATION_ENTITY"}


@dataclass
class DamageRecipe:
    """One level of one P axis, resolved into concrete parameters and frozen decisions.

    ``params`` are the *declared* parameters of the level; ``basis`` carries every frozen
    random/geometric decision (sampled once per axis and fragment, shared by all levels).
    """

    axis_id: str
    variant: str = ""
    level: int = 0
    recipe_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    roi: dict[str, Any] = field(default_factory=lambda: {"kind": "interface"})
    grid: dict[str, Any] = field(default_factory=dict)
    basis: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    nesting: dict[str, Any] = field(default_factory=lambda: {"correct": True, "budget_rel": 0.02})
    qa: dict[str, Any] = field(default_factory=lambda: {"outside_tol_mm": 1e-4,
                                                        "min_wall_thickness_mm": None})
    sdf_backend: str | None = None
    previous_mesh: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    def parameter(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    @property
    def is_identity(self) -> bool:
        """Level 0 is the only true identity; it returns the source object untouched."""
        return int(self.level) == 0

    @property
    def touches_geometry(self) -> bool:
        if self.axis_id in APPEARANCE_AXES:
            return P06_VARIANTS.get(self.variant, "APPEARANCE") == "CONTAMINATION_ENTITY"
        if self.axis_id == "P08":
            return P08_VARIANTS.get(self.variant, "GEOMETRY") != "APPEARANCE"
        return True

    def declared(self) -> dict[str, Any]:
        return {
            "axis_id": self.axis_id, "variant": self.variant, "level": int(self.level),
            "recipe_id": self.recipe_id, "params": dict(self.params),
            "roi": dict(self.roi), "expected": dict(self.expected),
            "touches_geometry": bool(self.touches_geometry),
            "sdf_backend": self.sdf_backend,
        }

    def frozen(self) -> dict[str, Any]:
        """Basis fingerprint (arrays reduced to hashes) for provenance records."""
        from ..canonical import array_hash, hash_json

        def reduce(value: Any) -> Any:
            if isinstance(value, np.ndarray):
                return array_hash(value)
            if isinstance(value, dict):
                return {str(k): reduce(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
            if isinstance(value, (list, tuple)):
                return [reduce(v) for v in value]
            if hasattr(value, "vertices") and hasattr(value, "faces"):
                return array_hash(np.asarray(value.faces))
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return type(value).__name__

        return {"basis": reduce(self.basis), "hash": hash_json(reduce(self.basis))}


@dataclass
class DamageOutcome:
    """Result of one P-axis level *before* component/identity bookkeeping."""

    mesh: Any = None                       # damaged geometry (None for appearance-only axes)
    appearance: dict[str, Any] | None = None
    measurements: dict[str, float] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    realized: bool = False
    added_bodies: list[Any] = field(default_factory=list)
    failure_code: str | None = None
