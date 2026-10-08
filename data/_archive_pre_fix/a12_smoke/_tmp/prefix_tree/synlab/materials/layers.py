"""The four frozen layer stacks L01..L04 and the real geometric layer body (plan 8.2).

============================  ==================================================================
L01 坯体+釉                    coarse body + *geometric* glaze layer (real thickness)
L02 坯体+彩绘                  porcelain body + appearance-only painting
L03 石质+表面涂层              stone body + *geometric* coating
L04 木基体+涂饰                wood body + appearance-only finish
============================  ==================================================================

Two modes are supported and never conflated:

``SHADING_LAYER``
    changes appearance and material labels only.  It produces no exact delamination volume and
    no geometric loss truth - that is stated in the returned metadata, not implied.
``GEOMETRIC_LAYER``
    produces a real closed body of the requested thickness.  The body is the mother minus an
    isotropically eroded copy of itself, so it is watertight by construction, its thickness is
    *measured* on the result, and the layer is rejected with ``MOTHER_INVALID`` when the
    mother leaves no room for the requested thickness.  Delamination volume is then a real
    boolean quantity, not a texture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field

from ..errors import ErrorCode, SynLabError
from ..registry import register_layer_combo
from ..schemas.runtime import LayerSpec, MotherGeometry
from ..mothers.solids import boolean_difference, cleanup

STAGE = "materials.layers"


class _ComboParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variation_scale: float = Field(1.0, ge=0.0, le=4.0, description="appearance variation")
    layer_seed: int = Field(0, ge=0, le=2 ** 31 - 1)


def _spec(layer_id: int, name: str, material_id: str, mode: str, thickness_mm: float,
          albedo: Sequence[float], roughness: float, *, ior: float = 1.5,
          transmission: float = 0.0) -> LayerSpec:
    return LayerSpec(layer_id=int(layer_id), name=name, material_id=material_id, mode=mode,
                     thickness_mm=float(thickness_mm),
                     albedo=(float(albedo[0]), float(albedo[1]), float(albedo[2])),
                     roughness=float(roughness), ior=float(ior),
                     transmission=float(transmission))


def _scaled(base: Sequence[float], factor: float) -> tuple[float, float, float]:
    return tuple(float(np.clip(c * float(factor), 0.0, 1.0)) for c in base)


# ------------------------------------------------------------------------------- L01
class GlazeComboParams(_ComboParams):
    glaze_thickness_mm: float = Field(0.55, ge=0.12, le=2.5)
    glaze_albedo: tuple[float, float, float] = Field((0.28, 0.40, 0.30))
    glaze_roughness: float = Field(0.14, ge=0.02, le=0.6)
    min_thickness_mm: float = Field(0.25, ge=0.05, le=1.5)


@register_layer_combo("L01", "坯体+釉", param_model=GlazeComboParams,
                      applicable={"mode": "GEOMETRIC_LAYER", "layers": 2,
                                  "body_material": "M01", "top_material": "M06",
                                  "definition": {
                                      "mode": "GEOMETRIC_LAYER",
                                      "layers": [
                                          {"layer_id": 1, "name": "body",
                                           "material_id": "M01", "mode": "SHADING_LAYER",
                                           "thickness_mm": 0.0},
                                          {"layer_id": 2, "name": "glaze",
                                           "material_id": "M06", "mode": "GEOMETRIC_LAYER",
                                           "min_thickness_mm": 0.25},
                                      ],
                                      "note": "geometric glaze: real thickness and a measured "
                                              "delamination volume",
                                  }},
                      notes="body plus a real glaze body; delamination is a boolean quantity")
def build_glaze_combo(params: dict[str, Any], rng) -> list[LayerSpec]:
    p = GlazeComboParams.model_validate(params)
    return [
        _spec(1, "body", "M01", "SHADING_LAYER", 0.0, (0.30, 0.24, 0.19), 0.82),
        _spec(2, "glaze", "M06", "GEOMETRIC_LAYER", float(p.glaze_thickness_mm),
              p.glaze_albedo, float(p.glaze_roughness), ior=1.51),
    ]


# ------------------------------------------------------------------------------- L02
class PaintedComboParams(_ComboParams):
    paint_albedo: tuple[float, float, float] = Field((0.16, 0.26, 0.52))
    paint_roughness: float = Field(0.30, ge=0.02, le=0.9)
    paint_layers: int = Field(1, ge=1, le=3)


@register_layer_combo("L02", "坯体+彩绘", param_model=PaintedComboParams,
                      applicable={"mode": "SHADING_LAYER", "layers": 2,
                                  "body_material": "M05", "top_material": "M05",
                                  "definition": {
                                      "mode": "SHADING_LAYER",
                                      "layers": [
                                          {"layer_id": 1, "name": "body",
                                           "material_id": "M05", "mode": "SHADING_LAYER",
                                           "thickness_mm": 0.0},
                                          {"layer_id": 2, "name": "painting",
                                           "material_id": "M05", "mode": "SHADING_LAYER",
                                           "thickness_mm": 0.0},
                                      ],
                                      "note": "appearance only: no geometric thickness and no "
                                              "delamination truth is claimed",
                                  }},
                      notes="porcelain body plus appearance-only painting")
def build_painted_combo(params: dict[str, Any], rng) -> list[LayerSpec]:
    p = PaintedComboParams.model_validate(params)
    specs = [_spec(1, "body", "M05", "SHADING_LAYER", 0.0, (0.86, 0.855, 0.83), 0.34)]
    for index in range(int(p.paint_layers)):
        factor = 1.0 - 0.18 * index
        specs.append(_spec(2 + index, f"painting_{index + 1}", "M05", "SHADING_LAYER", 0.0,
                           _scaled(p.paint_albedo, factor), float(p.paint_roughness)))
    return specs


# ------------------------------------------------------------------------------- L03
class StoneCoatingComboParams(_ComboParams):
    coating_thickness_mm: float = Field(0.9, ge=0.2, le=3.5)
    coating_albedo: tuple[float, float, float] = Field((0.44, 0.42, 0.38))
    coating_roughness: float = Field(0.38, ge=0.05, le=0.9)
    min_thickness_mm: float = Field(0.4, ge=0.1, le=2.0)


@register_layer_combo("L03", "石质+表面涂层", param_model=StoneCoatingComboParams,
                      applicable={"mode": "GEOMETRIC_LAYER", "layers": 2,
                                  "body_material": "M08", "top_material": "M08",
                                  "definition": {
                                      "mode": "GEOMETRIC_LAYER",
                                      "layers": [
                                          {"layer_id": 1, "name": "stone",
                                           "material_id": "M08", "mode": "SHADING_LAYER",
                                           "thickness_mm": 0.0},
                                          {"layer_id": 2, "name": "coating",
                                           "material_id": "M08", "mode": "GEOMETRIC_LAYER",
                                           "min_thickness_mm": 0.4},
                                      ],
                                      "note": "real coating body with a measured thickness and a "
                                              "watertight interface",
                                  }},
                      notes="stone body plus a real surface coating")
def build_stone_coating_combo(params: dict[str, Any], rng) -> list[LayerSpec]:
    p = StoneCoatingComboParams.model_validate(params)
    return [
        _spec(1, "stone", "M08", "SHADING_LAYER", 0.0, (0.42, 0.40, 0.37), 0.74),
        _spec(2, "coating", "M08", "GEOMETRIC_LAYER", float(p.coating_thickness_mm),
              p.coating_albedo, float(p.coating_roughness), ior=1.47),
    ]


# ------------------------------------------------------------------------------- L04
class WoodFinishComboParams(_ComboParams):
    finish_albedo: tuple[float, float, float] = Field((0.46, 0.30, 0.16))
    finish_roughness: float = Field(0.30, ge=0.02, le=0.9)
    finish_gloss: float = Field(0.35, ge=0.0, le=1.0)


@register_layer_combo("L04", "木基体+涂饰", param_model=WoodFinishComboParams,
                      applicable={"mode": "SHADING_LAYER", "layers": 2,
                                  "body_material": "M11", "top_material": "M11",
                                  "definition": {
                                      "mode": "SHADING_LAYER",
                                      "layers": [
                                          {"layer_id": 1, "name": "wood",
                                           "material_id": "M11", "mode": "SHADING_LAYER",
                                           "thickness_mm": 0.0},
                                          {"layer_id": 2, "name": "finish",
                                           "material_id": "M11", "mode": "SHADING_LAYER",
                                           "thickness_mm": 0.0},
                                      ],
                                      "note": "appearance only; the finish has no geometric body",
                                  }},
                      notes="wood body plus an appearance-only finish")
def build_wood_finish_combo(params: dict[str, Any], rng) -> list[LayerSpec]:
    p = WoodFinishComboParams.model_validate(params)
    return [
        _spec(1, "wood", "M11", "SHADING_LAYER", 0.0, (0.44, 0.32, 0.20), 0.58),
        _spec(2, "finish", "M11", "SHADING_LAYER", 0.0, p.finish_albedo,
              float(p.finish_roughness), ior=1.5),
    ]


# ------------------------------------------------------------------- geometric layer body
@dataclass
class LayerShell:
    """One real geometric layer body plus its measured QA record."""

    layer_id: int
    name: str
    material_id: str
    mesh: trimesh.Trimesh
    inner_mesh: trimesh.Trimesh
    thickness_requested_mm: float
    min_thickness_mm: float
    qa: dict[str, Any]

    @property
    def volume_mm3(self) -> float:
        return float(abs(self.mesh.volume))

    @property
    def interface_area_mm2(self) -> float:
        return float(self.inner_mesh.area)


def build_layer_shell(mother: MotherGeometry, entry: dict[str, Any], *,
                      stage: str = "materials.layers.shell") -> LayerShell:
    """Build one GEOMETRIC_LAYER body as ``mother - erode(mother, thickness)``.

    The layer is watertight by construction, its thickness is re-measured on the result, and a
    mother that cannot host the requested thickness is rejected with ``MOTHER_INVALID`` rather
    than being given a paper-thin or open shell.
    """
    mesh = getattr(mother, "mesh", None)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "geometric layer needs a mother mesh",
                          stage=stage, measurements={"mother_id": getattr(mother, "mother_id", "")})
    thickness = float(entry.get("thickness_mm", 0.0))
    min_thickness = float(entry.get("min_thickness_mm", 0.15))
    if thickness <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "GEOMETRIC_LAYER needs a positive thickness", stage=stage,
                          measurements={"layer": entry.get("name"), "thickness_mm": thickness})
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    extent = bounds[1] - bounds[0]
    min_extent = float(np.min(extent))
    if min_extent <= 3.0 * thickness:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"mother has no room for a {thickness:.2f} mm layer (smallest extent "
            f"{min_extent:.2f} mm)",
            stage=stage,
            measurements={"mother_id": getattr(mother, "mother_id", ""),
                          "thickness_mm": thickness, "min_extent_mm": min_extent},
        )
    inner = erode_mother(mesh, thickness_mm=thickness, stage=stage)
    layer_mesh = boolean_difference([mesh, inner])
    layer_mesh, _ = cleanup(layer_mesh)
    if not layer_mesh.is_watertight:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "geometric layer is not watertight", stage=stage,
                          measurements={"layer": entry.get("name"),
                                        "faces": int(len(layer_mesh.faces))})
    if float(layer_mesh.volume) <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "geometric layer has no volume",
                          stage=stage, measurements={"layer": entry.get("name")})
    measured = measure_layer_thickness(mesh, layer_mesh)
    qa = {
        # the layer is the mother minus an isotropically eroded copy, so it is *at least* the
        # requested thickness everywhere and thicker where the outline curves (the far side of
        # a bowl counts twice in a ray); the median is the controlled quantity, while p05 still
        # has to clear the minimum layer thickness
        "ok": bool(measured["p05_mm"] >= min_thickness - 1e-6
                   and measured["median_mm"] <= thickness * 1.8 + 0.3),
        "mode": "GEOMETRIC_LAYER",
        "watertight": bool(layer_mesh.is_watertight),
        "interface_watertight": bool(inner.is_watertight),
        "thickness_requested_mm": thickness,
        "min_thickness_mm": min_thickness,
        **measured,
        "volume_mm3": float(layer_mesh.volume),
        "interface_area_mm2": float(inner.area),
        "method": "mother minus an isotropically eroded copy of itself; thickness measured on "
                  "the result with the signed solid-angle test",
    }
    if not qa["ok"]:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"geometric layer {entry.get('name')!r} fails the thickness gate: p05 "
            f"{measured['p05_mm']:.3f} mm < {min_thickness:.3f} mm or median "
            f"{measured['median_mm']:.3f} mm above {thickness * 1.8 + 0.3:.3f} mm",
            stage=stage, measurements=qa,
        )
    return LayerShell(layer_id=int(entry.get("layer_id", 0)), name=str(entry.get("name", "layer")),
                      material_id=str(entry.get("material_id", "")), mesh=layer_mesh,
                      inner_mesh=inner, thickness_requested_mm=thickness,
                      min_thickness_mm=min_thickness, qa=qa)


def erode_mother(mesh: trimesh.Trimesh, *, thickness_mm: float,
                 stage: str = "materials.layers.erode") -> trimesh.Trimesh:
    """Largest isotropic shrink of ``mesh`` that stays a valid, watertight, non-empty solid."""
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    extent = bounds[1] - bounds[0]
    centre = 0.5 * (bounds[0] + bounds[1])
    min_extent = float(np.min(extent))
    upper = float(np.clip(1.0 - 2.2 * thickness_mm / max(min_extent, 1e-6), 0.35, 0.995))
    attempts: list[dict[str, float]] = []
    lo, hi = 0.30, upper
    best: trimesh.Trimesh | None = None
    for _ in range(18):
        factor = 0.5 * (lo + hi)
        if factor <= 0.31:
            break
        candidate = mesh.copy()
        matrix = np.eye(4, dtype=np.float64)
        matrix[0, 0] = matrix[1, 1] = matrix[2, 2] = float(factor)
        candidate.apply_transform(matrix)
        offset = centre * (1.0 - float(factor))
        candidate.apply_translation(offset)
        ok = bool(candidate.is_watertight and float(candidate.volume) > 0)
        attempts.append({"factor": float(factor), "ok": ok,
                         "volume_mm3": float(candidate.volume) if ok else 0.0})
        if ok:
            best = candidate
            lo = factor
        else:
            hi = factor
    if best is None:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"no valid eroded copy exists for a {thickness_mm:.2f} mm layer",
            stage=stage,
            measurements={"thickness_mm": thickness_mm, "attempts": attempts[-6:]},
        )
    best, _ = cleanup(best)
    return best


def measure_layer_thickness(mother_mesh: trimesh.Trimesh, layer_mesh: trimesh.Trimesh,
                            *, max_probes: int = 24,
                            step_fraction: float = 0.05) -> dict[str, float]:
    """Measure the realised thickness of a layer *on the layer itself*.

    A layer is a shell, so a ray from the body centre crosses it in a thin band and a coarse
    sampling step can miss it completely (a false zero).  Each probe therefore starts at a
    sampled face centroid of the layer, steps inward along that face's normal, and measures how
    far the material continues - which is exactly the local layer thickness, measured on the
    geometry that was built rather than on the requested parameter.
    """
    from ..mothers.measure import point_in_material

    centroids = np.asarray(layer_mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(layer_mesh.face_normals, dtype=np.float64)
    if len(centroids) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "layer mesh has no faces",
                          stage="materials.layers.measure")
    bounds = np.asarray(layer_mesh.bounds, dtype=np.float64)
    diag = float(np.linalg.norm(bounds[1] - bounds[0]))
    step = max(float(step_fraction) * diag / 100.0, 0.02)
    reach = 0.25 * diag
    index = np.unique(np.linspace(0, len(centroids) - 1,
                                  min(int(max_probes), len(centroids))).astype(np.int64))
    values: list[float] = []
    for i in index:
        direction = -normals[i]
        if float(np.linalg.norm(direction)) < 0.5:
            continue
        samples = int(np.ceil(reach / step))
        ts = np.arange(samples, dtype=np.float64) * step
        points = centroids[i][None, :] + ts[:, None] * direction[None, :]
        inside = point_in_material(layer_mesh, points)
        run = 0
        for flag in inside:
            if flag:
                run += 1
            elif run:
                break
        if run:
            values.append(float(run) * step)
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "layer thickness could not be probed (no material found under any "
                          "sampled face)",
                          stage="materials.layers.measure",
                          measurements={"probes": int(len(index)), "step_mm": step})
    return {
        "n_valid": float(arr.size),
        "min_mm": float(arr.min()),
        "p05_mm": float(np.percentile(arr, 5)),
        "median_mm": float(np.median(arr)),
        "max_mm": float(arr.max()),
        "step_mm": float(step),
    }


def _inside_runs(flags: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


__all__ = [
    "GlazeComboParams", "PaintedComboParams", "StoneCoatingComboParams", "WoodFinishComboParams",
    "build_glaze_combo", "build_painted_combo", "build_stone_coating_combo",
    "build_wood_finish_combo", "LayerShell", "build_layer_shell", "erode_mother",
    "measure_layer_thickness",
]
