"""Registry entries for the 16 pattern families (plan 9.3 table, one entry per family).

Every family is registered with the central registry with its own id, display name,
version, pydantic parameter model and a builder entry point that binds the family id.
Nothing here is a renamed copy of another family: each builder freezes a different
algorithm (bands, linear-phase stripes, two-set grids, wave centre lines, Poisson disks,
triangular tiles, meander tiles, layered line fields, bounded L-system, vector symbols,
glyph layout, multi-scale blotches, relief masks, engraving curves, region composition).
"""

from __future__ import annotations

from typing import Any, Callable

from ..registry import STATUS_IMPLEMENTED, register_pattern
from .params import FAMILY_MODELS, FAMILY_NAMES, GEOMETRIC_FAMILIES
from .serialize import MODULE_VERSION

FAMILY_NOTES: dict[str, str] = {
    "PAT01": "constant colour with an optional low-frequency colour field; may be fully plain",
    "PAT02": "band centre lines in profile arc length, seamless in the azimuthal direction",
    "PAT03": "linear-phase stripes with an integer azimuthal count (the seam closes exactly)",
    "PAT04": "two (or three) stripe sets combined by union/intersection with explicit mix order",
    "PAT05": "sine or Bezier centre line at an integer wave count, distance raster + EDT",
    "PAT06": "crystal lattice or scipy PoissonDisk dots with an audited periodic seam extension",
    "PAT07": "triangular tile with integer column count; line or solid barycentric fill",
    "PAT08": "meander fret in a periodic tile with shared endpoints across tile borders",
    "PAT09": "2-3 layered line fields with deterministic missing strokes",
    "PAT10": "bounded L-system/turtle skeleton plus svgpathtools Bezier leaf outlines",
    "PAT11": "programmatic vector symbol or a restricted, registered SVG path",
    "PAT12": "one-shot Pillow glyph layout with a SciPy distance map (font hash frozen)",
    "PAT13": "multi-scale continuous blotch field, independent roughness sub-stream",
    "PAT14": "smooth relief mask -> positive height -> real displacement of the whole body",
    "PAT15": "curve distance -> negative height -> real engraved displacement of the whole body",
    "PAT16": "region masks and a bounded composition of the layers above",
}


def _family_builder(family_id: str) -> Callable[..., Any]:
    def builder(mother: Any, spec: Any = None, rng: Any = None, **kwargs: Any) -> Any:
        from .api import build_pattern

        merged: dict[str, Any] = {"family": family_id}
        if isinstance(spec, dict):
            merged.update(spec)
        elif spec is not None:
            merged["params"] = spec
        merged.update(kwargs)
        return build_pattern(mother, merged, rng)

    builder.__name__ = f"build_{family_id.lower()}"
    builder.__qualname__ = builder.__name__
    builder.__doc__ = FAMILY_NOTES.get(family_id, "")
    return builder


def register_families() -> dict[str, Any]:
    """Register all 16 families; idempotent (the registry returns the existing entry)."""
    out: dict[str, Any] = {}
    for family_id, model in FAMILY_MODELS.items():
        entry = register_pattern(
            family_id, FAMILY_NAMES[family_id], version=MODULE_VERSION, param_model=model,
            applicable={
                "geometry": family_id in GEOMETRIC_FAMILIES,
                "appearance_only": family_id not in GEOMETRIC_FAMILIES,
                "complexity_tiers": [1, 2, 3],
                "requires_chart": True,
                "periodic_axis": "u=atan2(y,x)/(2*pi) mod 1",
                "profile_axis": "true profile arc length s_mm",
                "height_policy": {"PAT14": "relief", "PAT15": "engrave"}.get(family_id, "none"),
            },
            notes=FAMILY_NOTES.get(family_id, ""), status=STATUS_IMPLEMENTED,
            module=__name__)(_family_builder(family_id))
        out[family_id] = entry
    return out


REGISTERED = register_families()
