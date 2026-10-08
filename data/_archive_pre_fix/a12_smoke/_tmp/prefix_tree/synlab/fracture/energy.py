"""Energy bookkeeping of one fragmentation event: where the input energy went.

The fragmentation law lives in :mod:`synlab.fracture.impact`; this module keeps the *ledger* so a
piece count can never be presented without the energy that produced it:

* ``kinetic`` -- ``0.5 * m * v**2`` of the body at impact (measured mass, declared speed);
* ``surface_work`` -- the fracture work actually realised by the produced pieces,
  ``sum over interfaces of G_c * A_interface`` with ``A_interface`` the *measured* common clip
  area of the patch and ``G_c`` the material's fracture energy from the config;
* ``residual`` -- the rest, reported as ``unaccounted_fraction``.  It is **not** silently
  attributed to "dissipation": a large residual means the piece count is not the one the energy
  would predict, and the report says so.

Nothing here guesses a number: the mass comes from the realised mesh volume and the material
density, the interface areas come from the interface patches, and the fracture energy comes from
the config with its provenance attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

__all__ = ["EnergyLedger", "build_ledger", "kinetic_energy_j", "surface_work_j"]


def kinetic_energy_j(mass_kg: float, speed_mm_s: float) -> float:
    """``0.5 m v^2`` with the speed in mm/s (result in joule)."""
    return 0.5 * float(mass_kg) * (float(speed_mm_s) * 1.0e-3) ** 2


def surface_work_j(interface_areas_mm2: Iterable[float], fracture_energy_j_mm2: float) -> float:
    """Fracture work of the realised new surfaces (``G_c * A``), one term per interface."""
    return float(fracture_energy_j_mm2) * float(np.sum(np.asarray(list(interface_areas_mm2),
                                                                 dtype=np.float64)))


@dataclass
class EnergyLedger:
    """Input energy vs. realised fracture work, with the residual left explicit."""

    kinetic_j: float = 0.0
    surface_j: float = 0.0
    fracture_energy_j_mm2: float = 0.0
    mass_kg: float = 0.0
    speed_mm_s: float = 0.0
    new_surface_mm2: float = 0.0
    n_pieces: int = 0
    per_piece_j: list[float] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def residual_j(self) -> float:
        return float(self.kinetic_j - self.surface_j)

    @property
    def unaccounted_fraction(self) -> float:
        if self.kinetic_j <= 0.0:
            return 0.0
        return float(self.residual_j / self.kinetic_j)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kinetic_j": float(self.kinetic_j),
            "surface_work_j": float(self.surface_j),
            "residual_j": float(self.residual_j),
            "unaccounted_fraction": float(self.unaccounted_fraction),
            "fracture_energy_j_mm2": float(self.fracture_energy_j_mm2),
            "mass_kg": float(self.mass_kg),
            "speed_mm_s": float(self.speed_mm_s),
            "new_surface_mm2": float(self.new_surface_mm2),
            "n_pieces": int(self.n_pieces),
            "per_piece_j": [float(x) for x in self.per_piece_j],
            "specific_energy_j_per_kg": float(self.kinetic_j / max(self.mass_kg, 1e-12)),
            "meta": dict(self.meta),
        }


def build_ledger(*, volume_mm3: float, density_g_cm3: float, speed_mm_s: float,
                 interface_areas_mm2: Iterable[float], fracture_energy_j_mm2: float,
                 piece_volumes_mm3: Iterable[float]) -> EnergyLedger:
    """Assemble the ledger from measured volumes/areas and the declared material energy.

    The surface work is distributed over the pieces **in proportion to the new surface each piece
    carries** (``2 * A_i`` for a piece that owns one side of every interface it touches is
    double counting, so the per-piece share is ``G_c * A_i`` with ``A_i`` the piece's own
    interface area), which is what makes ``per_piece_j`` a measured quantity rather than a
    division of the total.
    """
    density_kg_mm3 = float(density_g_cm3) * 1.0e-6
    mass_kg = density_kg_mm3 * float(volume_mm3)
    areas = np.asarray(list(interface_areas_mm2), dtype=np.float64)
    total_area = float(np.sum(areas))
    work = surface_work_j([total_area], fracture_energy_j_mm2)
    volumes = np.asarray(list(piece_volumes_mm3), dtype=np.float64)
    ledger = EnergyLedger(
        kinetic_j=kinetic_energy_j(mass_kg, speed_mm_s),
        surface_j=work,
        fracture_energy_j_mm2=float(fracture_energy_j_mm2),
        mass_kg=float(mass_kg),
        speed_mm_s=float(speed_mm_s),
        new_surface_mm2=total_area,
        n_pieces=int(volumes.shape[0]),
        per_piece_j=[float(fracture_energy_j_mm2) * float(total_area)
                     * float(v) / max(float(np.sum(volumes)), 1e-12) for v in volumes],
        meta={
            "surface_work_formula": "G_c * sum(interface common clip area)",
            "per_piece_formula": "G_c * A_total * V_i / sum(V)",
            "note": ("residual is the energy not turned into new surface; it is reported, never "
                     "called dissipation"),
        },
    )
    return ledger
