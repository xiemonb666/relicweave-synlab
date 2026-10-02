"""Measured statistics of a mother body and its material, as the fracture law needs them.

``synlab.fracture.impact.count_model`` takes ``BodyStats`` (measured geometry) and ``MaterialStats``
(measured material statistics), and the ``warp_voronoi_cut`` path needs one of each per event.  This
module is the single place that builds them from a live mother, so the calibration instrument, the
batch pipeline entry point and the tests all measure the wall thickness the same way.

The wall thickness is the *measured median* of ``synlab.mothers.measure.thickness_samples`` (the
same estimator ``synlab.mothers.audit`` uses), never an assumed constant; a mother whose thickness
cannot be measured is reported with ``wall_mm == 0`` and ``count_model`` refuses it rather than
falling back to a number.
"""

from __future__ import annotations

from typing import Any

__all__ = ["body_stats_of", "material_stats_of", "CALIBRATION_STORE"]

#: bundle-local store of the calibration measurements (never inside a frozen data root)
CALIBRATION_STORE = "data/a12_fcal/store"


def _thickness(mesh: Any, *, max_probes: int = 400) -> dict[str, Any]:
    from ..mothers.measure import thickness_samples

    faces = list(range(int(len(mesh.faces))))
    if faces:
        stride = max(1, len(faces) // max(int(max_probes), 1))
        faces = faces[::stride]
    return thickness_samples(mesh, faces, max_probes=int(max_probes))


def body_stats_of(mother: Any, vessel_id: str = "", *, max_probes: int = 400) -> Any:
    """Measured ``BodyStats`` of one mother (volume, area, extents, wall-thickness quantiles)."""
    from .impact import BodyStats

    mesh = mother.mesh
    thickness = _thickness(mesh, max_probes=max_probes)
    return BodyStats(
        vessel_id=str(vessel_id or getattr(mother, "vessel_id", "") or ""),
        volume_mm3=float(abs(mesh.volume)),
        area_mm2=float(mesh.area),
        extents_mm=tuple(float(x) for x in mesh.extents),
        thickness_min_mm=float(thickness.get("min_mm", 0.0) or 0.0),
        thickness_p05_mm=float(thickness.get("p05_mm", 0.0) or 0.0),
        thickness_median_mm=float(thickness.get("median_mm", 0.0) or 0.0),
        thickness_max_mm=float(thickness.get("max_mm", 0.0) or 0.0),
        outer_area_mm2=float(mesh.area),
        provenance={"thickness": "synlab.mothers.measure.thickness_samples (measured median)"},
    )


def material_stats_of(material_id: str) -> Any:
    """Measured ``MaterialStats`` from the material profile registry (density wins when present)."""
    from ..materials.api import build_material_profile, default_material_params
    from .impact import MaterialStats

    import numpy as np

    profile = build_material_profile(str(material_id), default_material_params(str(material_id)),
                                     np.random.default_rng(11))
    stats = dict(profile.get("stats") or {})

    def pick(*names: str, default: float = 0.0) -> float:
        for name in names:
            value = stats.get(name)
            if isinstance(value, (int, float)):
                return float(value)
        return float(default)

    return MaterialStats(
        material_id=str(material_id),
        density_g_cm3=pick("density_g_cm3", "density", "bulk_density_g_cm3", default=2.2),
        porosity=pick("porosity", "porosity_fraction"),
        grain_size_mm=pick("grain_size_mm", "grain_mm", "median_grain_mm", default=0.05),
        weibull_modulus=(pick("weibull_modulus") or None),
        provenance={"source": "synlab.materials.api.build_material_profile"},
    )
