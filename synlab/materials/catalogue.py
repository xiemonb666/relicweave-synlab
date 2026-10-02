"""The twelve registered materials (plan 8.1, table M01..M12).

Each material owns a pydantic parameter model and a builder that describes the *statistical*
differences the plan requires:

======================  =====================================================================
M01 粗陶                big grog aggregate, visible pores, uneven body colour
M02 细陶                fine grain, short correlation length, independent of M01
M03 炻器                dense, low porosity, optional glaze highlight
M04 白瓷                pale body, thin glaze, small-scale fracture statistics
M05 彩瓷                porcelain body plus a mother-continuous painted layer
M06 施釉陶              pottery body plus an independent glaze layer
M07 玻璃                transmissive, high specular, smooth cut faces
M08 石材                mineral grain plus a bedding direction (anisotropy)
M09 石膏                pale porous body with a powdering surface
M10 骨质                porous, outer/inner layer difference, directional field
M11 木质                continuous fibre / growth-ring field, directional edges
M12 金属                reflective, corrosion layer, procedural cut statistics
======================  =====================================================================

Nothing here claims a calibrated mechanical property: Young's modulus, Poisson's ratio and
fracture toughness stay ``UNKNOWN`` in the profile (plan 8.1), and the procedural cut
statistics are explicitly *not* a fracture-mechanics solver.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..errors import ErrorCode, SynLabError
from ..registry import register_material

STAGE = "materials.catalogue"


class _Base(BaseModel):
    """Common knobs: the frozen field salt, the reference shell and appearance amplitudes."""

    model_config = ConfigDict(extra="forbid")

    field_salt: int = Field(0, ge=0, le=2 ** 31 - 1,
                            description="frozen hash salt of this material's field")
    variation_scale: float = Field(1.0, ge=0.0, le=4.0,
                                   description="global multiplier on the appearance variation")
    shell_ref_radius_mm: float = Field(80.0, ge=10.0, le=400.0,
                                       description="reference outer radius of the coated shell")
    shell_ref_height_mm: float = Field(130.0, ge=10.0, le=520.0,
                                       description="reference rim height of the coated shell")

    def salt(self, rng: np.random.Generator | None) -> int:
        """Frozen salt: an explicit value wins, otherwise one draw from the material sub-stream."""
        if int(self.field_salt) > 0:
            return int(self.field_salt)
        if rng is None:
            return 1
        return int(rng.integers(1, 2 ** 31 - 1))

    def reference(self) -> dict[str, Any]:
        return _reference(mode="revolve", r_outer_mm=float(self.shell_ref_radius_mm),
                          r_inner_mm=0.0, z_floor_mm=0.0, z_rim_mm=float(self.shell_ref_height_mm),
                          note="reference outer surface of the mother this profile is queried "
                               "on; material_at only needs it for the layer depth")


def _profile(*, salt: int, appearance: dict[str, Any], stats: dict[str, Any],
             layers: list[dict[str, Any]], reference: dict[str, Any],
             notes: str, variation_scale: float = 1.0,
             transmission: float = 0.0) -> dict[str, Any]:
    """Assemble one material profile body (validated by ``api.build_material_profile``)."""
    for key, value in appearance.items():
        if key == "hue_shift":
            if len(value) != 3:
                raise SynLabError(ErrorCode.SCHEMA_INVALID, "hue_shift needs 3 components",
                                  stage=STAGE)
            continue
        if key == "ior":
            if not 1.0 <= float(value) <= 3.0:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"appearance.ior must be in [1,3], got {value}", stage=STAGE)
            continue
        if isinstance(value, (int, float)) and not 0.0 <= float(value) <= 1.0:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"appearance.{key} must be in [0,1], got {value}",
                              stage=STAGE)
    scaled = dict(appearance)
    for key in ("grain_amount", "pore_amount", "aggregate_amount", "fiber_amount",
                "roughness_variation", "pore_roughness"):
        if key in scaled:
            scaled[key] = float(np.clip(float(scaled[key]) * float(variation_scale), 0.0, 1.0))
    scaled["transmission"] = float(np.clip(transmission, 0.0, 1.0))
    return {
        "field_salt": int(salt),
        "appearance": scaled,
        "stats": stats,
        "layers": layers,
        "outer_reference": reference,
        "notes": notes,
    }


def _body_layer(*, material_id: str, albedo: tuple[float, float, float], roughness: float,
                ior: float, thickness_mm: float = 0.0, kind: str = "base",
                name: str = "body", layer_id: int = 0,
                transmission: float = 0.0) -> dict[str, Any]:
    return {"layer_id": int(layer_id), "name": name, "material_id": material_id,
            "kind": kind, "thickness_mm": float(thickness_mm),
            "albedo": [float(c) for c in albedo], "roughness": float(roughness),
            "ior": float(ior), "transmission": float(transmission),
            "mode": "SHADING_LAYER"}


def _reference(*, mode: str, **kwargs: Any) -> dict[str, Any]:
    return {"mode": mode, **kwargs}


# ---------------------------------------------------------------------------- M01 粗陶
class CoarseEarthenwareParams(_Base):
    aggregate_radius_mm: float = Field(1.6, ge=0.2, le=6.0, description="grog inclusion radius")
    aggregate_density: float = Field(0.00035, ge=0.0, le=0.004,
                                     description="inclusions per cubic millimetre")
    pore_scale_mm: float = Field(4.0, ge=0.4, le=20.0)
    body_albedo: float = Field(0.42, ge=0.05, le=1.0)


@register_material("M01", "粗陶", param_model=CoarseEarthenwareParams,
                   applicable={"family": "earthenware", "grain_scale_mm": [0.8, 3.0],
                               "porosity": "high", "aggregate": True, "layers": 1},
                   notes="large grog aggregate, visible pores and an uneven body colour")
def build_coarse_earthenware(params: dict[str, Any], rng) -> dict[str, Any]:
    p = CoarseEarthenwareParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.55 * float(p.body_albedo)
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.18, base * 0.94, base * 0.74], "roughness": 0.82,
                   "ior": 1.52, "grain_amount": 0.30, "pore_amount": 0.45,
                   "aggregate_amount": 0.60, "hue_shift": [0.03, -0.01, -0.03],
                   "roughness_variation": 0.22, "pore_roughness": 0.28},
        stats={"grain_scale_mm": 2.6, "pore_scale_mm": float(p.pore_scale_mm),
               "aggregate_radius_mm": float(p.aggregate_radius_mm),
               "aggregate_density_per_mm3": float(p.aggregate_density),
               "anisotropy": 0.0, "correlation_length_mm": 2.6,
               "cut_statistics": {"mode": "granular", "correlation_length_mm": 2.6,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "grain pulls out of the matrix; no fracture solver"}},
        layers=[_body_layer(layer_id=1, material_id="M01", albedo=(base * 1.18, base * 0.94, base * 0.74),
                            roughness=0.82, ior=1.52)],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M01: grog aggregate + pores; the body colour is uneven by construction",
    )


# ---------------------------------------------------------------------------- M02 细陶
class FineEarthenwareParams(_Base):
    grain_scale_mm: float = Field(0.55, ge=0.1, le=3.0)
    pore_scale_mm: float = Field(1.1, ge=0.2, le=6.0)
    body_albedo: float = Field(0.62, ge=0.05, le=1.0)
    polish_roughness: float = Field(0.55, ge=0.05, le=1.0)


@register_material("M02", "细陶", param_model=FineEarthenwareParams,
                   applicable={"family": "earthenware", "grain_scale_mm": [0.2, 0.9],
                               "porosity": "medium", "aggregate": False, "layers": 1},
                   notes="fine grain with a short correlation length; polished and eroded apart")
def build_fine_earthenware(params: dict[str, Any], rng) -> dict[str, Any]:
    p = FineEarthenwareParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.62 * float(p.body_albedo)
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.10, base * 1.0, base * 0.88], "roughness": 0.66,
                   "ior": 1.52, "grain_amount": 0.12, "pore_amount": 0.20,
                   "aggregate_amount": 0.0, "hue_shift": [0.02, 0.0, -0.02],
                   "roughness_variation": 0.10, "pore_roughness": 0.14},
        stats={"grain_scale_mm": float(p.grain_scale_mm),
               "pore_scale_mm": float(p.pore_scale_mm),
               "aggregate_radius_mm": 0.0, "aggregate_density_per_mm3": 0.0,
               "anisotropy": 0.0, "correlation_length_mm": float(p.grain_scale_mm),
               "cut_statistics": {"mode": "fine_granular",
                                  "correlation_length_mm": float(p.grain_scale_mm),
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "short correlation length, independent of M01"}},
        layers=[_body_layer(layer_id=1, material_id="M02", albedo=(base * 1.10, base, base * 0.88),
                            roughness=float(p.polish_roughness), ior=1.52)],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M02: fine grain, short correlation length, separate polish/erosion statistics",
    )


# ---------------------------------------------------------------------------- M03 炻器
class StonewareParams(_Base):
    pore_scale_mm: float = Field(6.0, ge=1.0, le=24.0)
    glazed: bool = Field(True, description="record a specular glaze state (no layer body)")
    glaze_thickness_mm: float = Field(0.35, ge=0.05, le=1.2)
    body_albedo: float = Field(0.38, ge=0.05, le=1.0)


@register_material("M03", "炻器", param_model=StonewareParams,
                   applicable={"family": "stoneware", "grain_scale_mm": [0.3, 1.2],
                               "porosity": "low", "aggregate": False, "layers": 2},
                   notes="dense low-porosity body with an optional specular glaze state")
def build_stoneware(params: dict[str, Any], rng) -> dict[str, Any]:
    p = StonewareParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.62 * float(p.body_albedo)
    body = _body_layer(layer_id=1, material_id="M03", albedo=(base * 1.08, base, base * 0.92),
                       roughness=0.52, ior=1.54)
    layers = [body]
    if bool(p.glazed):
        layers.insert(0, {"layer_id": 2, "name": "glaze_state", "material_id": "M03",
                          "kind": "appearance", "thickness_mm": float(p.glaze_thickness_mm),
                          "albedo": [float(np.clip(base * 1.05, 0, 1)), base * 0.98,
                                     base * 0.86],
                          "roughness": 0.16, "ior": 1.52, "transmission": 0.0,
                          "mode": "SHADING_LAYER"})
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.08, base, base * 0.92], "roughness": 0.52, "ior": 1.54,
                   "grain_amount": 0.08, "pore_amount": 0.06, "aggregate_amount": 0.0,
                   "hue_shift": [0.0, 0.0, 0.0],
                   "roughness_variation": 0.06, "pore_roughness": 0.05},
        stats={"grain_scale_mm": 0.8, "pore_scale_mm": float(p.pore_scale_mm),
               "aggregate_radius_mm": 0.0, "aggregate_density_per_mm3": 0.0,
               "anisotropy": 0.0, "correlation_length_mm": 0.8,
               "missed_measurement_ratio": 0.02,
               "cut_statistics": {"mode": "dense", "correlation_length_mm": 0.8,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "dense body; glaze state is appearance only"}},
        layers=layers,
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M03: dense and low porosity; the glaze state is recorded as appearance only",
    )


# ---------------------------------------------------------------------------- M04 白瓷
class PorcelainParams(_Base):
    glaze_thickness_mm: float = Field(0.22, ge=0.03, le=1.0)
    body_albedo: float = Field(0.86, ge=0.3, le=1.0)
    wall_min_mm: float = Field(2.0, ge=0.6, le=12.0, description="thin-wall guard in mm")


@register_material("M04", "白瓷", param_model=PorcelainParams,
                   applicable={"family": "porcelain", "grain_scale_mm": [0.05, 0.3],
                               "porosity": "very_low", "aggregate": False, "layers": 2,
                               "min_wall_mm": 2.0},
                   notes="pale body with a thin glaze and small-scale fracture statistics")
def build_porcelain(params: dict[str, Any], rng) -> dict[str, Any]:
    p = PorcelainParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.9 * float(p.body_albedo)
    body = _body_layer(layer_id=1, material_id="M04", albedo=(base, base * 0.995, base * 0.97),
                       roughness=0.34, ior=1.56)
    # outermost first with descending ids: the glaze sits above the body layer
    glaze = {"layer_id": 2, "name": "glaze", "material_id": "M04", "kind": "appearance",
             "thickness_mm": float(p.glaze_thickness_mm),
             "albedo": [float(np.clip(base * 1.03, 0, 1)), float(np.clip(base * 1.02, 0, 1)),
                        float(np.clip(base * 1.0, 0, 1))],
             "roughness": 0.09, "ior": 1.51, "transmission": 0.02, "mode": "SHADING_LAYER"}
    return _profile(
        salt=salt,
        appearance={"albedo": [base, base * 0.995, base * 0.97], "roughness": 0.34, "ior": 1.56,
                   "grain_amount": 0.04, "pore_amount": 0.03, "aggregate_amount": 0.0,
                   "hue_shift": [0.01, 0.005, 0.0],
                   "roughness_variation": 0.03, "pore_roughness": 0.03},
        stats={"grain_scale_mm": 0.18, "pore_scale_mm": 0.5, "aggregate_radius_mm": 0.0,
               "aggregate_density_per_mm3": 0.0, "anisotropy": 0.0,
               "correlation_length_mm": 0.18,
               "min_wall_mm": float(p.wall_min_mm),
               "cut_statistics": {"mode": "fine", "correlation_length_mm": 0.18,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "small-scale fracture statistics; thin-wall guard "
                                          f"{float(p.wall_min_mm):.2f} mm"}},
        layers=[glaze, body],
        reference=p.reference(),
        variation_scale=float(p.variation_scale), transmission=0.02,
        notes="M04: pale porcelain body with a thin glaze; small-scale fracture statistics",
    )


# ---------------------------------------------------------------------------- M05 彩瓷
class PaintedPorcelainParams(_Base):
    paint_thickness_mm: float = Field(0.06, ge=0.01, le=0.4)
    paint_albedo: tuple[float, float, float] = Field((0.16, 0.26, 0.52))
    body_albedo: float = Field(0.85, ge=0.3, le=1.0)


@register_material("M05", "彩瓷", param_model=PaintedPorcelainParams,
                   applicable={"family": "porcelain", "grain_scale_mm": [0.05, 0.3],
                               "porosity": "very_low", "aggregate": False, "layers": 3},
                   notes="porcelain body with a mother-continuous painted layer; new sections "
                         "expose the body, never the paint")
def build_painted_porcelain(params: dict[str, Any], rng) -> dict[str, Any]:
    p = PaintedPorcelainParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.9 * float(p.body_albedo)
    paint = tuple(float(np.clip(c, 0.0, 1.0)) for c in p.paint_albedo)
    return _profile(
        salt=salt,
        appearance={"albedo": [base, base * 0.995, base * 0.97], "roughness": 0.36, "ior": 1.56,
                   "grain_amount": 0.05, "pore_amount": 0.03, "aggregate_amount": 0.0,
                   "hue_shift": [0.01, 0.005, 0.0],
                   "roughness_variation": 0.04, "pore_roughness": 0.03},
        stats={"grain_scale_mm": 0.18, "pore_scale_mm": 0.5, "aggregate_radius_mm": 0.0,
               "aggregate_density_per_mm3": 0.0, "anisotropy": 0.0,
               "correlation_length_mm": 0.18,
               "cut_statistics": {"mode": "fine", "correlation_length_mm": 0.18,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "decoration is albedo only; a new section has no paint"}},
        layers=[
            {"layer_id": 3, "name": "paint", "material_id": "M05", "kind": "appearance",
             "thickness_mm": float(p.paint_thickness_mm), "albedo": list(paint),
             "roughness": 0.30, "ior": 1.5, "transmission": 0.0, "mode": "SHADING_LAYER"},
            {"layer_id": 2, "name": "glaze", "material_id": "M05", "kind": "appearance",
             "thickness_mm": 0.20, "albedo": [float(np.clip(base * 1.02, 0, 1)),] * 3,
             "roughness": 0.08, "ior": 1.51, "transmission": 0.02, "mode": "SHADING_LAYER"},
            _body_layer(layer_id=1, material_id="M05", albedo=(base, base * 0.995, base * 0.97),
                        roughness=0.36, ior=1.56),
        ],
        reference=p.reference(),
        variation_scale=float(p.variation_scale), transmission=0.02,
        notes="M05: porcelain + mother-continuous paint; the paint never propagates to a "
              "fresh section",
    )


# -------------------------------------------------------------------------- M06 施釉陶
class GlazedPotteryParams(_Base):
    glaze_thickness_mm: float = Field(0.45, ge=0.1, le=2.0)
    glaze_albedo: tuple[float, float, float] = Field((0.30, 0.42, 0.30))
    body_albedo: float = Field(0.55, ge=0.05, le=1.0)
    glaze_crazing: float = Field(0.35, ge=0.0, le=1.0, description="crazing network amplitude")


@register_material("M06", "施釉陶", param_model=GlazedPotteryParams,
                   applicable={"family": "earthenware", "grain_scale_mm": [0.8, 3.0],
                               "porosity": "medium", "aggregate": True, "layers": 2},
                   notes="pottery body with an independent glaze layer: the layer interface, "
                         "glaze loss and body loss are separate records")
def build_glazed_pottery(params: dict[str, Any], rng) -> dict[str, Any]:
    p = GlazedPotteryParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.65 * float(p.body_albedo)
    glaze = tuple(float(np.clip(c, 0.0, 1.0)) for c in p.glaze_albedo)
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.12, base * 0.98, base * 0.80], "roughness": 0.78,
                   "ior": 1.52, "grain_amount": 0.22, "pore_amount": 0.32,
                   "aggregate_amount": 0.35, "hue_shift": [0.02, -0.01, -0.02],
                   "roughness_variation": 0.18, "pore_roughness": 0.22},
        stats={"grain_scale_mm": 2.0, "pore_scale_mm": 3.4, "aggregate_radius_mm": 1.1,
               "aggregate_density_per_mm3": 0.00022, "anisotropy": 0.0,
               "correlation_length_mm": 2.0, "glaze_crazing": float(p.glaze_crazing),
               "cut_statistics": {"mode": "granular", "correlation_length_mm": 2.0,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "glaze loss and body loss are counted separately"}},
        layers=[
            {"layer_id": 2, "name": "glaze", "material_id": "M06", "kind": "geometric",
             "thickness_mm": float(p.glaze_thickness_mm), "albedo": list(glaze),
             "roughness": 0.14, "ior": 1.51, "transmission": 0.0, "mode": "GEOMETRIC_LAYER"},
            _body_layer(layer_id=1, material_id="M06", albedo=(base * 1.12, base * 0.98, base * 0.80),
                        roughness=0.78, ior=1.52),
        ],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M06: pottery body + independent glaze layer (layer interface is its own record)",
    )


# ---------------------------------------------------------------------------- M07 玻璃
class GlassParams(_Base):
    transmission: float = Field(0.82, ge=0.0, le=1.0)
    body_albedo: float = Field(0.90, ge=0.2, le=1.0)
    cut_roughness: float = Field(0.22, ge=0.02, le=0.6, description="smooth conchoidal cut faces")
    tint: tuple[float, float, float] = Field((0.72, 0.86, 0.82))


@register_material("M07", "玻璃", param_model=GlassParams,
                   applicable={"family": "glass", "grain_scale_mm": [0.02, 0.2],
                               "porosity": "none", "aggregate": False, "layers": 1,
                               "missing_scan_allowed": True},
                   notes="transmissive high-specular body with smooth cut faces; legal scans "
                         "may have missing measurements")
def build_glass(params: dict[str, Any], rng) -> dict[str, Any]:
    p = GlassParams.model_validate(params)
    salt = p.salt(rng)
    base = float(p.body_albedo)
    tint = tuple(float(np.clip(c, 0.0, 1.0)) for c in p.tint)
    albedo = tuple(float(np.clip(base * t, 0.0, 1.0)) for t in tint)
    return _profile(
        salt=salt,
        appearance={"albedo": list(albedo), "roughness": float(p.cut_roughness), "ior": 1.52,
                   "grain_amount": 0.02, "pore_amount": 0.0, "aggregate_amount": 0.0,
                   "hue_shift": [0.0, 0.01, 0.0],
                   "roughness_variation": 0.05, "pore_roughness": 0.0},
        stats={"grain_scale_mm": 0.08, "pore_scale_mm": 0.4, "aggregate_radius_mm": 0.0,
               "aggregate_density_per_mm3": 0.0, "anisotropy": 0.0,
               "correlation_length_mm": 0.08,
               "missing_measurement_allowed": True,
               "ideal_depth_separate": True,
               "cut_statistics": {"mode": "conchoidal_smooth",
                                  "correlation_length_mm": 0.08,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "smooth cut faces; ideal-depth runs are a separate "
                                          "axis, not part of this material"}},
        layers=[_body_layer(layer_id=1, material_id="M07", albedo=albedo, roughness=float(p.cut_roughness),
                            ior=1.52, transmission=float(p.transmission))],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        transmission=float(p.transmission),
        notes="M07: transmissive glass; missing measurements on legal scans are recorded",
    )


# ---------------------------------------------------------------------------- M08 石材
class StoneParams(_Base):
    bedding_period_mm: float = Field(14.0, ge=2.0, le=80.0)
    bedding_direction: tuple[float, float, float] = Field((0.30, 0.94, 0.0))
    mineral_radius_mm: float = Field(1.2, ge=0.2, le=5.0)
    body_albedo: float = Field(0.52, ge=0.05, le=1.0)
    weathering: float = Field(0.30, ge=0.0, le=1.0)


@register_material("M08", "石材", param_model=StoneParams,
                   applicable={"family": "stone", "grain_scale_mm": [0.5, 4.0],
                               "porosity": "low", "aggregate": True, "layers": 1,
                               "anisotropic": True},
                   notes="mineral grain with a real bedding direction; anisotropic cut faces "
                         "and weathering statistics")
def build_stone(params: dict[str, Any], rng) -> dict[str, Any]:
    p = StoneParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.6 * float(p.body_albedo)
    direction = _unit(p.bedding_direction)
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.06, base * 1.0, base * 0.94], "roughness": 0.74,
                   "ior": 1.54, "grain_amount": 0.24, "pore_amount": 0.12,
                   "aggregate_amount": 0.40, "fiber_amount": 0.22,
                   "hue_shift": [0.0, -0.01, -0.02],
                   "roughness_variation": 0.16, "pore_roughness": 0.10},
        stats={"grain_scale_mm": 2.2, "pore_scale_mm": 2.6,
               "aggregate_radius_mm": float(p.mineral_radius_mm),
               "aggregate_density_per_mm3": 0.00028, "anisotropy": 0.65,
               "correlation_length_mm": 2.2,
               "fiber_direction": list(direction), "fiber_period_mm": float(p.bedding_period_mm),
               "weathering": float(p.weathering),
               "cut_statistics": {"mode": "bedded", "correlation_length_mm": 2.2,
                                  "direction": list(direction),
                                  "note": "bedding direction is a real anisotropy axis"}},
        layers=[_body_layer(layer_id=1, material_id="M08", albedo=(base * 1.06, base, base * 0.94),
                            roughness=0.74, ior=1.54)],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M08: mineral grain + bedding direction; anisotropic cut statistics",
    )


# ---------------------------------------------------------------------------- M09 石膏
class PlasterParams(_Base):
    pore_scale_mm: float = Field(2.2, ge=0.4, le=12.0)
    body_albedo: float = Field(0.88, ge=0.3, le=1.0)
    powdering: float = Field(0.40, ge=0.0, le=1.0)


@register_material("M09", "石膏", param_model=PlasterParams,
                   applicable={"family": "plaster", "grain_scale_mm": [0.2, 1.2],
                               "porosity": "very_high", "aggregate": False, "layers": 1},
                   notes="pale porous body with powdering and erosion statistics")
def build_plaster(params: dict[str, Any], rng) -> dict[str, Any]:
    p = PlasterParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.92 * float(p.body_albedo)
    return _profile(
        salt=salt,
        appearance={"albedo": [base, base * 0.995, base * 0.985], "roughness": 0.88,
                   "ior": 1.48, "grain_amount": 0.10, "pore_amount": 0.55,
                   "aggregate_amount": 0.0, "hue_shift": [0.0, 0.0, 0.0],
                   "roughness_variation": 0.12, "pore_roughness": 0.32},
        stats={"grain_scale_mm": 0.7, "pore_scale_mm": float(p.pore_scale_mm),
               "aggregate_radius_mm": 0.0, "aggregate_density_per_mm3": 0.0,
               "anisotropy": 0.0, "correlation_length_mm": 0.7,
               "powdering": float(p.powdering),
               "cut_statistics": {"mode": "powdery", "correlation_length_mm": 0.7,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "powdering and erosion are separate statistics"}},
        layers=[_body_layer(layer_id=1, material_id="M09", albedo=(base, base * 0.995, base * 0.985),
                            roughness=0.88, ior=1.48)],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M09: porous plaster; erosion statistics only, no biomechanical or strength claim",
    )


# ---------------------------------------------------------------------------- M10 骨质
class BoneParams(_Base):
    outer_layer_mm: float = Field(0.9, ge=0.1, le=4.0)
    lamella_period_mm: float = Field(3.5, ge=0.5, le=20.0)
    lamella_direction: tuple[float, float, float] = Field((0.0, 0.0, 1.0))
    body_albedo: float = Field(0.80, ge=0.3, le=1.0)


@register_material("M10", "骨质", param_model=BoneParams,
                   applicable={"family": "bone", "grain_scale_mm": [0.2, 1.5],
                               "porosity": "high", "aggregate": False, "layers": 2,
                               "anisotropic": True},
                   notes="porous bone with an outer/inner layer difference and a directional "
                         "field; procedural statistics, no biomechanical claim")
def build_bone(params: dict[str, Any], rng) -> dict[str, Any]:
    p = BoneParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.88 * float(p.body_albedo)
    direction = _unit(p.lamella_direction)
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.08, base * 1.0, base * 0.86], "roughness": 0.62,
                   "ior": 1.55, "grain_amount": 0.16, "pore_amount": 0.42,
                   "aggregate_amount": 0.0, "fiber_amount": 0.35,
                   "hue_shift": [0.01, 0.0, -0.02],
                   "roughness_variation": 0.14, "pore_roughness": 0.26},
        stats={"grain_scale_mm": 0.9, "pore_scale_mm": 1.4, "aggregate_radius_mm": 0.0,
               "aggregate_density_per_mm3": 0.0, "anisotropy": 0.55,
               "correlation_length_mm": 0.9,
               "fiber_direction": list(direction), "fiber_period_mm": float(p.lamella_period_mm),
               "cut_statistics": {"mode": "lamellar", "correlation_length_mm": 0.9,
                                  "direction": list(direction),
                                  "note": "programme statistics only; not a biomechanical model"}},
        layers=[
            {"layer_id": 2, "name": "outer_table", "material_id": "M10", "kind": "appearance",
             "thickness_mm": float(p.outer_layer_mm),
             "albedo": [float(np.clip(base * 1.12, 0, 1)), base, base * 0.84],
             "roughness": 0.48, "ior": 1.55, "transmission": 0.0, "mode": "SHADING_LAYER"},
            _body_layer(layer_id=1, material_id="M10", albedo=(base * 1.08, base, base * 0.86),
                        roughness=0.62, ior=1.55),
        ],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M10: outer/inner layer difference and a directional field, procedural only",
    )


# ---------------------------------------------------------------------------- M11 木质
class WoodParams(_Base):
    fibre_direction: tuple[float, float, float] = Field((1.0, 0.0, 0.0))
    ring_period_mm: float = Field(5.5, ge=0.8, le=40.0, description="growth-ring spacing")
    ring_age_ratio: float = Field(0.35, ge=0.0, le=1.0, description="latewood fraction")
    body_albedo: float = Field(0.52, ge=0.05, le=1.0)
    tear_roughness: float = Field(0.70, ge=0.2, le=1.0)


@register_material("M11", "木质", param_model=WoodParams,
                   applicable={"family": "wood", "grain_scale_mm": [1.0, 8.0],
                               "porosity": "medium", "aggregate": False, "layers": 1,
                               "anisotropic": True},
                   notes="continuous fibre / growth-ring field with directional edges; "
                         "procedural tear statistics, not a crack solver")
def build_wood(params: dict[str, Any], rng) -> dict[str, Any]:
    p = WoodParams.model_validate(params)
    salt = p.salt(rng)
    base = 0.6 * float(p.body_albedo)
    direction = _unit(p.fibre_direction)
    return _profile(
        salt=salt,
        appearance={"albedo": [base * 1.55, base * 1.12, base * 0.72], "roughness": 0.58,
                   "ior": 1.5, "grain_amount": 0.28, "pore_amount": 0.26,
                   "aggregate_amount": 0.0, "fiber_amount": 0.80,
                   "hue_shift": [0.04, 0.01, -0.04],
                   "roughness_variation": 0.22, "pore_roughness": 0.24},
        stats={"grain_scale_mm": 3.0, "pore_scale_mm": 2.0, "aggregate_radius_mm": 0.0,
               "aggregate_density_per_mm3": 0.0, "anisotropy": 0.85,
               "correlation_length_mm": 3.0,
               "fiber_direction": list(direction), "fiber_period_mm": float(p.ring_period_mm),
               "latewood_fraction": float(p.ring_age_ratio),
               "tear_roughness": float(p.tear_roughness),
               "cut_statistics": {"mode": "fibrous", "correlation_length_mm": 3.0,
                                  "direction": list(direction),
                                  "note": "directional tear statistics; not a crack solver"}},
        layers=[_body_layer(layer_id=1, material_id="M11", albedo=(base * 1.55, base * 1.12, base * 0.72),
                            roughness=float(p.tear_roughness), ior=1.5)],
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M11: fibre/growth-ring field with a real direction; procedural tear statistics",
    )


# ---------------------------------------------------------------------------- M12 金属
class MetalParams(_Base):
    corrosion_thickness_mm: float = Field(0.08, ge=0.0, le=0.8)
    corrosion_albedo: tuple[float, float, float] = Field((0.30, 0.24, 0.18))
    body_albedo: float = Field(0.58, ge=0.05, le=1.0)
    specular_roughness: float = Field(0.24, ge=0.02, le=0.8)


@register_material("M12", "金属", param_model=MetalParams,
                   applicable={"family": "metal", "grain_scale_mm": [0.05, 0.6],
                               "porosity": "none", "aggregate": False, "layers": 2,
                               "cut_statistics": "procedural"},
                   notes="reflective body with a corrosion layer and procedural cut "
                         "statistics; plastic fracture is outside the core backends")
def build_metal(params: dict[str, Any], rng) -> dict[str, Any]:
    p = MetalParams.model_validate(params)
    salt = p.salt(rng)
    base = float(p.body_albedo)
    body_albedo = (base * 0.96, base * 0.98, base)
    corrosion = tuple(float(np.clip(c, 0.0, 1.0)) for c in p.corrosion_albedo)
    layers = [_body_layer(layer_id=1, material_id="M12", albedo=body_albedo,
                          roughness=float(p.specular_roughness), ior=1.6)]
    if float(p.corrosion_thickness_mm) > 0:
        layers.insert(0, {"layer_id": 2, "name": "corrosion", "material_id": "M12",
                          "kind": "appearance",
                          "thickness_mm": float(p.corrosion_thickness_mm),
                          "albedo": list(corrosion), "roughness": 0.82, "ior": 1.4,
                          "transmission": 0.0, "mode": "SHADING_LAYER"})
    return _profile(
        salt=salt,
        appearance={"albedo": list(body_albedo), "roughness": float(p.specular_roughness),
                   "ior": 1.6, "grain_amount": 0.06, "pore_amount": 0.02,
                   "aggregate_amount": 0.0, "hue_shift": [0.0, 0.0, 0.01],
                   "roughness_variation": 0.08, "pore_roughness": 0.05},
        stats={"grain_scale_mm": 0.25, "pore_scale_mm": 0.6, "aggregate_radius_mm": 0.0,
               "aggregate_density_per_mm3": 0.0, "anisotropy": 0.0,
               "correlation_length_mm": 0.25,
               "cut_statistics": {"mode": "ductile_procedural",
                                  "correlation_length_mm": 0.25,
                                  "direction": [0.0, 0.0, 1.0],
                                  "note": "procedural cut statistics only; plastic fracture is "
                                          "not part of the core backends (plan 8.1 M12)"}},
        layers=layers,
        reference=p.reference(),
        variation_scale=float(p.variation_scale),
        notes="M12: reflective body, corrosion layer, procedural cut statistics",
    )


def _unit(direction: Any) -> tuple[float, float, float]:
    vec = np.asarray(list(direction), dtype=np.float64).reshape(-1)
    if vec.size != 3 or not np.all(np.isfinite(vec)):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"direction must be 3 finite numbers, "
                                                    f"got {direction!r}", stage=STAGE)
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-12:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "direction must be non-zero", stage=STAGE)
    vec = vec / norm
    return (float(vec[0]), float(vec[1]), float(vec[2]))


__all__ = [
    "CoarseEarthenwareParams", "FineEarthenwareParams", "StonewareParams", "PorcelainParams",
    "PaintedPorcelainParams", "GlazedPotteryParams", "GlassParams", "StoneParams",
    "PlasterParams", "BoneParams", "WoodParams", "MetalParams",
    "build_coarse_earthenware", "build_fine_earthenware", "build_stoneware", "build_porcelain",
    "build_painted_porcelain", "build_glazed_pottery", "build_glass", "build_stone",
    "build_plaster", "build_bone", "build_wood", "build_metal",
]
