"""Private rendering-only appearance evaluation in immutable material coordinates.

This module deliberately exposes no deployment feature, Scene field, serialized view, or
metadata representation.  A caller may compile a sampler from verified truth-side asset data
and pass it to one software ``render_view`` call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError


@dataclass(frozen=True, slots=True)
class PaintedBand:
    center_z_mm: float
    width_mm: float
    color_linear_rgb: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class PaintedCylindricalZRecipe:
    material_binding_id: str
    target_region_codes: tuple[int, ...]
    base_linear_rgb: tuple[float, float, float]
    bands: tuple[PaintedBand, ...]


def _invalid(message: str, *, measurements: dict[str, Any] | None = None) -> SynLabError:
    return SynLabError(ErrorCode.SCHEMA_INVALID, message,
                       stage="observe.continuous_appearance",
                       measurements=measurements or {})


def _rgb(value: Any, label: str) -> tuple[float, float, float]:
    try:
        arr = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{label} must be a three-channel linear RGB array") from exc
    if arr.shape != (3,) or not np.isfinite(arr).all() or np.any(arr < 0.0) \
            or np.any(arr > 1.0):
        raise _invalid(f"{label} must contain three finite values in [0,1]")
    return tuple(float(v) for v in arr)


def compile_painted_cylindrical_z_recipe(
    recipe: Any, *, material_binding_id: str,
) -> PaintedCylindricalZRecipe:
    """Compile the only continuous recipe supported by this A12 preview adapter.

    Unknown coordinate maps, relief, malformed palette/bands, and material mismatches fail
    closed.  This is an optical recipe only; it never creates surface geometry.
    """
    if not isinstance(recipe, dict):
        raise _invalid("continuous appearance recipe must be a mapping")
    if recipe.get("coordinate_map") != "cylindrical_z_up_mm":
        raise _invalid("continuous preview supports only cylindrical_z_up_mm coordinates",
                       measurements={"coordinate_map": recipe.get("coordinate_map")})
    if recipe.get("material_binding_id") != material_binding_id:
        raise _invalid("continuous appearance recipe does not bind to the loaded material",
                       measurements={"recipe_binding": recipe.get("material_binding_id"),
                                     "material_binding": material_binding_id})
    if recipe.get("geometry_relief_mm") != 0.0:
        raise _invalid("continuous painted appearance requires zero geometry relief",
                       measurements={"geometry_relief_mm": recipe.get("geometry_relief_mm")})
    if recipe.get("historical_style_validation") != "NOT_VALIDATED":
        raise _invalid("continuous prototype recipe must remain NOT_VALIDATED",
                       measurements={"historical_style_validation":
                                     recipe.get("historical_style_validation")})

    regions_raw = recipe.get("target_region_codes")
    if not isinstance(regions_raw, list) or not regions_raw:
        raise _invalid("continuous recipe requires non-empty target_region_codes")
    regions: list[int] = []
    for value in regions_raw:
        if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2, 3, 4, 5):
            raise _invalid("continuous recipe target regions must be mother codes 1..5",
                           measurements={"target_region_codes": regions_raw})
        regions.append(int(value))
    if len(set(regions)) != len(regions):
        raise _invalid("continuous recipe target regions must be unique")

    palette_raw = recipe.get("palette_linear_rgb")
    if not isinstance(palette_raw, dict) or "base" not in palette_raw:
        raise _invalid("continuous recipe requires a palette with base linear RGB")
    palette = {str(name): _rgb(rgb, f"palette_linear_rgb.{name}")
               for name, rgb in palette_raw.items()}
    bands_raw = recipe.get("bands")
    if not isinstance(bands_raw, list) or not bands_raw:
        raise _invalid("continuous painted recipe requires at least one band")
    bands: list[PaintedBand] = []
    for index, item in enumerate(bands_raw):
        if not isinstance(item, dict):
            raise _invalid("each continuous band must be a mapping",
                           measurements={"band_index": index})
        center, width, color_name = (item.get("center_z_mm"), item.get("width_mm"),
                                     item.get("color"))
        if isinstance(center, bool) or not isinstance(center, (int, float)) \
                or not np.isfinite(float(center)):
            raise _invalid("band center_z_mm must be finite",
                           measurements={"band_index": index, "center_z_mm": center})
        if isinstance(width, bool) or not isinstance(width, (int, float)) \
                or not np.isfinite(float(width)) or float(width) <= 0.0:
            raise _invalid("band width_mm must be finite and positive",
                           measurements={"band_index": index, "width_mm": width})
        if not isinstance(color_name, str) or color_name not in palette or color_name == "base":
            raise _invalid("band color must name a non-base palette entry",
                           measurements={"band_index": index, "color": color_name})
        bands.append(PaintedBand(float(center), float(width), palette[color_name]))
    ordered = sorted(bands, key=lambda band: band.center_z_mm - band.width_mm / 2.0)
    for left, right in zip(ordered, ordered[1:]):
        if left.center_z_mm + left.width_mm / 2.0 > right.center_z_mm - right.width_mm / 2.0:
            raise _invalid("continuous painted bands must not overlap")

    return PaintedCylindricalZRecipe(
        material_binding_id=str(material_binding_id),
        target_region_codes=tuple(regions),
        base_linear_rgb=palette["base"],
        bands=tuple(bands),
    )


@dataclass(frozen=True, slots=True)
class RestCoordinateAppearanceSampler:
    """Immutable, truth-side sampler held only for the duration of one render call."""

    faces: np.ndarray
    face_regions: np.ndarray
    vertices_material_xyz_mm: np.ndarray
    recipe: PaintedCylindricalZRecipe

    @classmethod
    def from_asset_truth(
        cls, *, faces: np.ndarray, face_regions: np.ndarray,
        vertices_material_xyz_mm: np.ndarray, recipe: Any, material_binding_id: str,
    ) -> "RestCoordinateAppearanceSampler":
        faces_raw = np.asarray(faces)
        regions_raw = np.asarray(face_regions)
        if faces_raw.dtype.kind not in "iu" or regions_raw.dtype.kind not in "iu":
            raise _invalid("truth-side faces and region codes must use integer arrays")
        f = np.array(faces_raw, dtype=np.int64, copy=True, order="C")
        regions = np.array(regions_raw, dtype=np.int64, copy=True, order="C").reshape(-1)
        xyz = np.array(vertices_material_xyz_mm, dtype=np.float64, copy=True, order="C")
        if f.ndim != 2 or f.shape[1] != 3 or not f.size \
                or regions.shape != (f.shape[0],):
            raise _invalid("truth-side face and region arrays have incompatible shapes")
        if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all() \
                or int(f.min(initial=0)) < 0 or int(f.max(initial=-1)) >= xyz.shape[0]:
            raise _invalid("truth-side rest coordinates or face indices are invalid")
        compiled = compile_painted_cylindrical_z_recipe(
            recipe, material_binding_id=material_binding_id)
        if not set(int(x) for x in np.unique(regions)).issubset({1, 2, 3, 4, 5}):
            raise _invalid("truth-side VF region array contains an unsupported code")
        for value in (f, regions, xyz):
            value.setflags(write=False)
        return cls(faces=f, face_regions=regions, vertices_material_xyz_mm=xyz,
                   recipe=compiled)

    def sample_albedo(self, face_indices: np.ndarray, barycentric: np.ndarray,
                      fallback_linear_rgb: np.ndarray) -> np.ndarray:
        """Evaluate linear albedo at perspective-correct hit barycentrics."""
        face_ids_raw = np.asarray(face_indices)
        if face_ids_raw.dtype.kind not in "iu":
            raise _invalid("appearance sample face indices must be integers")
        face_ids = face_ids_raw.astype(np.int64, copy=False).reshape(-1)
        bary_raw = np.asarray(barycentric)
        fallback_raw = np.asarray(fallback_linear_rgb)
        if bary_raw.dtype.kind not in "fiu" or fallback_raw.dtype.kind not in "fiu":
            raise _invalid("appearance sample barycentrics and face albedo must be numeric")
        try:
            bary = np.asarray(bary_raw, dtype=np.float64).reshape(-1, 3)
            fallback = np.asarray(fallback_raw, dtype=np.float64).reshape(-1, 3)
        except (TypeError, ValueError) as exc:
            raise _invalid("appearance sample inputs must have numeric triangle/RGB shapes") from exc
        if bary.shape[0] != face_ids.size or fallback.shape[0] != face_ids.size \
                or np.any(face_ids < 0) or np.any(face_ids >= self.faces.shape[0]):
            raise _invalid("appearance sample face/barycentric inputs are inconsistent")
        bary_sum = bary.sum(axis=1)
        if not np.isfinite(bary).all() or np.any(bary < -1e-8) \
                or np.any(bary > 1.0) \
                or not np.allclose(bary_sum, 1.0, rtol=0.0, atol=1e-8) \
                or not np.isfinite(fallback).all():
            raise _invalid("appearance sample contains invalid barycentrics or face albedo")
        output = fallback.copy()
        target = np.isin(self.face_regions[face_ids],
                         np.asarray(self.recipe.target_region_codes, dtype=np.int64))
        if not target.any():
            return output
        selected = np.flatnonzero(target)
        selected_faces = face_ids[selected]
        selected_bary = bary[selected]
        rest = self.vertices_material_xyz_mm[self.faces[selected_faces]]
        rest_z = np.einsum("ni,ni->n", selected_bary, rest[:, :, 2])
        values = np.asarray(self.recipe.base_linear_rgb, dtype=np.float64)
        sampled = np.broadcast_to(values, (selected.size, 3)).copy()
        for band in self.recipe.bands:
            inside = np.abs(rest_z - band.center_z_mm) <= band.width_mm / 2.0
            sampled[inside] = np.asarray(band.color_linear_rgb, dtype=np.float64)
        output[selected] = sampled
        return output


__all__ = [
    "PaintedBand", "PaintedCylindricalZRecipe", "RestCoordinateAppearanceSampler",
    "compile_painted_cylindrical_z_recipe",
]
