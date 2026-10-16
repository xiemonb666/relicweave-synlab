"""Façade of the pattern module (plan 9.1).

Exported entry points (frozen interface, ``docs/a12/interfaces.md`` §2):

* :func:`build_pattern` - draw every coefficient once and freeze a :class:`PatternRecipe`
* :func:`evaluate` - pure channel query; **never** draws randomness
* :func:`apply_pattern_geometry` - real relief / engraving on the complete mother body
* :func:`audit_pattern` - seam / scale / determinism / inheritance / geometry audit
* :func:`commit_pattern`, :func:`load_pattern` - asset store round trip

Nothing here returns fabricated data: a missing chart, a missing font/SVG, an
unsatisfiable dot density or a too-deep engraving raises a structured ``SynLabError``.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import (Chart, MotherGeometry, PatternChannels, PatternRecipe,
                               SurfaceTag)
from .builders import (BuildContext, build_aux_layer, field_context, freeze_family,
                       normalize_basis_on_samples)
from .charts import (ChartFrame, region_area_mm2, region_weight, resolve_frame, surface_samples,
                     tag_index, to_chart_mm)
from .fields import (WarpField, footprint_policy, jacobian_report, measure_spectrum,
                     sample_fourier_basis, weighted_stats)
from .layers import FieldOut, build_field
from .params import (APPEARANCE_FAMILIES, FAMILY_MODELS, FAMILY_NAMES, GEOMETRIC_FAMILIES,
                     PALETTE_IDS, PatternSpec, StrictModel, palette_payload)
from .serialize import (CHANNELS, MODULE_VERSION, channels_payload, recipe_from_dict,
                        recipe_hash, recipe_payload, recipe_to_dict, resource_hash)

DEFAULT_SAMPLE_DENSITY = 0.06          # samples per mm^2 for mother-relative measurements
MAX_SAMPLES = 4000
MIN_SAMPLES = 200
AUX_KINDS = ("AUX_TINT", "AUX_SPECKLE", "AUX_BAND")

__all__ = [
    "build_pattern", "evaluate", "apply_pattern_geometry", "audit_pattern",
    "commit_pattern", "load_pattern", "pattern_field", "recipe_hash", "recipe_to_dict",
    "recipe_from_dict", "FAMILY_MODELS", "FAMILY_NAMES", "PALETTE_IDS",
]


# ---------------------------------------------------------------------------------------
# spec handling
# ---------------------------------------------------------------------------------------
def _coerce_spec(spec: Any) -> PatternSpec:
    if spec is None:
        return PatternSpec()
    if isinstance(spec, PatternSpec):
        return spec
    if isinstance(spec, StrictModel):
        return PatternSpec(**spec.model_dump())
    if isinstance(spec, str):
        return PatternSpec(family=spec)
    if isinstance(spec, dict):
        try:
            return PatternSpec(**spec)
        except Exception as exc:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"pattern spec rejected: {exc}",
                              stage="patterns.api.build_pattern") from exc
    raise SynLabError(ErrorCode.SCHEMA_INVALID,
                      f"unsupported pattern spec type {type(spec)!r}",
                      stage="patterns.api.build_pattern")


def _rng_ref(rng: np.random.Generator) -> str:
    try:
        state = rng.bit_generator.state
    except AttributeError as exc:  # pragma: no cover - defensive
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "rng must be a numpy.random.Generator with PCG64 state",
                          stage="patterns.api._rng_ref") from exc
    return "pcg64:" + hash_json(state).split(":", 1)[-1][:24]


def _require_rng(rng: Any, spec: PatternSpec) -> np.random.Generator:
    if rng is None:
        if spec.seed_ref:
            digest = hashlib.sha256(spec.seed_ref.encode("utf-8")).digest()
            return np.random.default_rng(int.from_bytes(digest[:8], "little"))
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "build_pattern needs an explicit rng sub-stream "
            "(synlab.seeds.make_rng(master_seed, lineage_id, 'pattern')) or spec.seed_ref",
            stage="patterns.api.build_pattern")
    if not isinstance(rng, np.random.Generator):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"rng must be numpy.random.Generator, got {type(rng)!r}",
                          stage="patterns.api.build_pattern")
    return rng


def _select_family(spec: PatternSpec, rng: np.random.Generator) -> tuple[str, dict[str, Any]]:
    if spec.family:
        family = str(spec.family).upper()
        if family not in FAMILY_MODELS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown pattern family {spec.family!r}; "
                              f"known: {sorted(FAMILY_MODELS)}",
                              stage="patterns.api.build_pattern")
        return family, {"mode": "explicit"}
    quota = str(spec.quota_class)
    if quota == "PLAIN":
        return "PAT01", {"mode": "quota_PLAIN"}
    if quota == "STRONG_REPEAT":
        pool = ["PAT04", "PAT07", "PAT08", "PAT09"]
        return pool[int(rng.integers(0, len(pool)))], {"mode": "quota_STRONG_REPEAT"}
    pool = list(FAMILY_MODELS)
    return pool[int(rng.integers(0, len(pool)))], {"mode": "uniform_over_16"}


def _select_palette(spec: PatternSpec, rng: np.random.Generator) -> dict[str, Any]:
    if spec.palette_id:
        if spec.palette_id not in PALETTE_IDS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown palette {spec.palette_id!r}; known: {list(PALETTE_IDS)}",
                              stage="patterns.api.build_pattern")
        palette_id = spec.palette_id
    else:
        palette_id = PALETTE_IDS[int(rng.integers(0, len(PALETTE_IDS)))]
    return palette_payload(palette_id)


def _select_frame(mother: MotherGeometry, spec: PatternSpec, rng: np.random.Generator
                  ) -> tuple[ChartFrame, dict[str, Any]]:
    charts = list(mother.charts or [])
    if not charts:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"mother {mother.mother_id!r} has no chart; the pattern layer "
                          "cannot invent one", stage="patterns.api.build_pattern")
    if spec.surface_tag:
        frame = resolve_frame(mother, spec.surface_tag)
        return frame, {"mode": "explicit", "tag": frame.tag_name}
    by_name = {mother.tag_name(t): c for c in charts for t in c.surface_tags}
    if "outer_wall" in by_name:
        return resolve_frame(mother, "outer_wall"), {"mode": "prefer_outer_wall",
                                                     "tag": "outer_wall"}
    best = max(charts, key=lambda c: float(c.area_mm2 or 0.0))
    tag = int(best.surface_tags[0])
    return resolve_frame(mother, tag), {"mode": "largest_chart", "tag": mother.tag_name(tag)}


def _region_for(frame: ChartFrame, spec: PatternSpec, rng: np.random.Generator) -> dict[str, Any]:
    span = frame.s_span_mm
    margin = float(spec.region.s_margin_frac)
    jitter_lo = float(rng.uniform(0.0, 0.5 * margin + 1e-9))
    jitter_hi = float(rng.uniform(0.0, 0.5 * margin + 1e-9))
    s_lo = frame.s_min_mm + (margin + jitter_lo) * span
    s_hi = frame.s_max_mm - (margin + jitter_hi) * span
    if s_hi - s_lo < max(3.0, 0.05 * span):
        s_lo, s_hi = frame.s_min_mm + 0.1 * span, frame.s_max_mm - 0.1 * span
    return {
        "surface_tag": frame.tag_name,
        "chart": frame.name,
        "s_min_mm": float(s_lo), "s_max_mm": float(s_hi),
        "feather_mm": float(spec.region.feather_mm),
        "u_min": 0.0, "u_max": 1.0,
        "s_margin_frac": margin,
        "s_margin_jitter": [jitter_lo, jitter_hi],
        "legal_boundary": "hard s range with a smoothstep feather of feather_mm; the azimuthal "
                          "axis is periodic and has no boundary",
    }


def _sample_mother_points(mother: MotherGeometry, frame: ChartFrame, rng: np.random.Generator
                          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    area = region_area_mm2(frame, mother, {"s_min_mm": frame.s_min_mm, "s_max_mm": frame.s_max_mm})
    count = int(np.clip(round(max(area, 1.0) * DEFAULT_SAMPLE_DENSITY), MIN_SAMPLES, MAX_SAMPLES))
    points, face_index = surface_samples(mother, count, rng, tag=frame.tag)
    source = "trimesh.Trimesh.sample (area weighted, tagged faces)"
    if points.shape[0] < 32:
        faces = np.asarray(mother.mesh.faces)
        mask = np.asarray(mother.face_surface_tag) == int(frame.tag)
        if np.any(mask):
            points = np.asarray(mother.mesh.triangles[mask]).mean(axis=1)
            face_index = np.flatnonzero(mask)
            source = "face centroids of the tagged surface (too few sampled points)"
    if points.shape[0] == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"no measurable surface for tag {frame.tag_name!r}",
                          stage="patterns.api.build_pattern")
    x_mm, s_mm = to_chart_mm(frame, points)
    keep = (s_mm >= frame.s_min_mm - 1e-9) & (s_mm <= frame.s_max_mm + 1e-9)
    points, x_mm, s_mm = points[keep], x_mm[keep], s_mm[keep]
    weights = np.asarray(mother.mesh.area_faces, dtype=np.float64)[face_index[keep]]
    if points.shape[0] == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "sampled points fell outside the chart range",
                          stage="patterns.api.build_pattern")
    return points, x_mm, s_mm, weights, {"count": int(points.shape[0]), "source": source,
                                         "region_area_mm2": float(area),
                                         "density_per_mm2": DEFAULT_SAMPLE_DENSITY}


def _footprint(mother: MotherGeometry, spec: PatternSpec, *, line_width_mm: float) -> dict[str, Any]:
    edges = np.asarray(mother.mesh.faces)
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)
    lengths = np.linalg.norm(verts[edges[:, 1]] - verts[edges[:, 0]], axis=1)
    mesh_edge = float(np.median(lengths))
    return footprint_policy(line_width_mm, request_mm=spec.footprint_mm,
                            texture_mm_per_px=spec.texture_mm_per_px, mesh_edge_mm=mesh_edge)


def _warp_for(spec: PatternSpec, frame: ChartFrame, rng: np.random.Generator,
              footprint_mm: float) -> tuple[WarpField, dict[str, Any]]:
    if spec.warp is None or not spec.warp.enabled or spec.warp.amplitude_mm <= 0:
        return WarpField(), {"enabled": False,
                             "report": jacobian_report(WarpField(), x_period_mm=float(frame.x_period_mm or 1.0),
                                                       s_min_mm=frame.s_min_mm, s_max_mm=frame.s_max_mm)}
    amplitude = float(spec.warp.amplitude_mm)
    wavelength = max(float(spec.warp.wavelength_mm), 4.0 * footprint_mm)
    attempts: list[dict[str, Any]] = []
    for attempt in range(3):
        components = []
        for band in range(int(spec.warp.components)):
            basis = sample_fourier_basis(rng, x_period_mm=float(frame.x_period_mm),
                                         base_wavelength_mm=wavelength * (2.0 ** band),
                                         n_bands=1, components_per_band=1, base_amplitude=amplitude)
            components.extend(basis.components)
        warp = WarpField(components=components, amplitude_mm=amplitude, wavelength_mm=wavelength)
        report = jacobian_report(warp, x_period_mm=float(frame.x_period_mm),
                                 s_min_mm=frame.s_min_mm, s_max_mm=frame.s_max_mm)
        attempts.append({"attempt": attempt, "amplitude_mm": amplitude, **report})
        if report["positive"] and report["jacobian_min_singular"] > 0.2:
            report["attempts"] = attempts
            report["units"] = {"amplitude": "mm", "wavelength": "mm",
                               "jacobian": "dimensionless (chart mm)"}
            return warp, {"enabled": True, "report": report}
        amplitude *= 0.5
    return WarpField(), {"enabled": False, "reason": "warp rejected: Jacobian not positive "
                                                    "with a safe minimum singular value",
                         "attempts": attempts}


# ---------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------
def build_pattern(mother: MotherGeometry, spec: Any = None,
                  rng: np.random.Generator | None = None) -> PatternRecipe:
    """Draw every coefficient once and freeze a :class:`PatternRecipe`."""
    if not isinstance(mother, MotherGeometry):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"build_pattern expects a MotherGeometry, got {type(mother)!r}",
                          stage="patterns.api.build_pattern")
    spec_obj = _coerce_spec(spec)
    generator = _require_rng(rng, spec_obj)
    seed_ref = spec_obj.seed_ref or _rng_ref(generator)

    family, family_selection = _select_family(spec_obj, generator)
    complexity = int(spec_obj.complexity or generator.integers(1, 4))
    palette = _select_palette(spec_obj, generator)
    frame, frame_selection = _select_frame(mother, spec_obj, generator)
    region = _region_for(frame, spec_obj, generator)
    samples, sample_x, sample_s, sample_w, sample_report = _sample_mother_points(
        mother, frame, generator)

    defaults: dict[str, Any] = {
        "complexity": complexity,
        "line_width_mm": float(generator.uniform(0.9, 2.2)),
        "spacing_mm": float(generator.uniform(8.0, 22.0)),
    }
    merged = {**defaults, **dict(spec_obj.params or {})}
    line_width = float(merged["line_width_mm"])
    footprint = _footprint(mother, spec_obj, line_width_mm=line_width)

    warp, warp_info = _warp_for(spec_obj, frame, generator, footprint["footprint_mm"])
    height_spec = _height_policy(spec_obj, family, dict(spec_obj.params or {}))

    ctx = BuildContext(
        mother=mother, frame=frame, palette=palette, region=region, complexity=complexity,
        line_width_mm=line_width, footprint_mm=float(footprint["footprint_mm"]),
        footprint_source=str(footprint["source"]), texture_mm_per_px=spec_obj.texture_mm_per_px,
        samples=samples, sample_x=sample_x, sample_s=sample_s, sample_w=sample_w,
        warp=warp, warp_report=warp_info, rng=generator, height=height_spec)
    params = freeze_family(family, merged, ctx)

    # measured band energy of the frozen continuous fields (real, on the mother surface)
    measured: dict[str, Any] = {}
    for key in ("basis", "blotch", "speckle", "roughness", "ripple"):
        payload = params.get(key)
        if isinstance(payload, dict) and "components" in payload:
            from .fields import FourierBasis as _FB

            basis = _FB.from_dict(payload)
            from .builders import measured_field_report

            measured[key] = measured_field_report(basis, ctx)
    params["measured"] = measured
    params["region_sample_report"] = sample_report
    params["footprint"] = footprint

    aux_layers, aux_info = _aux_layers(spec_obj, ctx, family)
    field = build_field(family, params)
    # a family may have tightened the footprint for its own feature width; the query
    # context must use exactly the frozen per-family value so that the build-time
    # spectrum measurement and query-time evaluation describe the same field
    effective_footprint = float(params.get("footprint_mm", footprint["footprint_mm"]))
    field_ctx = field_context(
        {"chart": {"x_period_mm": float(frame.x_period_mm or frame.s_span_mm),
                   "s_periodic": bool(frame.s_periodic)},
         "regions": [region], "footprint_mm": effective_footprint},
        palette, warp)

    def modulation(x_mm: np.ndarray, s_mm: np.ndarray) -> np.ndarray:
        out = _composite(field, aux_layers, x_mm, s_mm, field_ctx)[0]
        return out.modulation

    spectrum = measure_spectrum(modulation, x_period_mm=float(frame.x_period_mm or frame.s_span_mm),
                                s_min_mm=float(region["s_min_mm"]),
                                s_max_mm=float(region["s_max_mm"]),
                                s_periodic=bool(frame.s_periodic))
    params["spectrum"] = spectrum

    height = _finalise_height(height_spec, family, params, frame, spec_obj)
    meta: dict[str, Any] = {
        "module": "synlab.patterns",
        "module_version": MODULE_VERSION,
        "family_name": FAMILY_NAMES.get(family, family),
        "family_selection": family_selection,
        "palette": palette,
        "palette_id": palette["palette_id"],
        "color_space": palette["color_space"],
        "chart": frame.as_dict(),
        "regions": [region],
        "region_area_mm2": float(region_area_mm2(frame, mother, region)),
        "height": height,
        "warp": {"enabled": bool(warp_info.get("enabled")), "report": warp_info.get("report"),
                 "reason": warp_info.get("reason"), **warp.as_dict()},
        "bands": params.get("measured", {}),
        "spectrum": spectrum,
        "footprint_mm": effective_footprint,
        "footprint_requested_mm": float(footprint["footprint_mm"]),
        "footprint_source": str(params.get("footprint_source", footprint["source"])),
        "aux_layers": aux_layers,
        "aux_info": aux_info,
        "sample_report": sample_report,
        "channels": list(CHANNELS),
        "surface_tag_selection": frame_selection,
        "geometry_before_fracture": True,
        "appearance_only_normal_map": False,
        "new_fracture_surface": ("body material only; the pattern layer is not applied to "
                                 "'interface' surfaces (see synlab.materials.material_at)"),
        "material_integration": "PENDING: composite with synlab.materials.material_at once the "
                               "materials module lands; the body colour used here comes from "
                               "the recipe palette",
        "library_versions": _library_versions(),
    }
    recipe = PatternRecipe(
        family_id=family, seed_ref=seed_ref, params=params,
        palette=[tuple(palette["body"])] + [tuple(p) for p in palette["paints"]],
        channels=CHANNELS, version=MODULE_VERSION, resource_hash="", meta=meta)
    recipe.resource_hash = resource_hash(_resource_entries(params), params)
    recipe.meta["recipe_hash"] = recipe_hash(recipe)
    return recipe


def _resource_entries(params: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    font = params.get("font")
    if isinstance(font, dict):
        entries.append({"kind": "font", "font_id": font.get("font_id"),
                        "hash": font.get("sha256"), "license_ref": font.get("license_ref"),
                        "family": font.get("family"), "style": font.get("style")})
    if params.get("symbol_source") == "svg_path":
        entries.append({"kind": "svg", "hash": params.get("resource_hash"),
                        "license_ref": params.get("license_ref")})
    if not entries:
        entries.append({"kind": "NONE", "detail": "family has no external resource"})
    return entries


def _library_versions() -> dict[str, str]:
    import PIL
    import scipy
    import shapely
    import svgpathtools
    import trimesh

    return {
        "numpy": np.__version__, "scipy": scipy.__version__, "pillow": PIL.__version__,
        "shapely": shapely.__version__, "trimesh": trimesh.__version__,
        "svgpathtools": getattr(svgpathtools, "__version__", "1.8"),
    }


def _height_policy(spec: PatternSpec, family: str, params: dict[str, Any]) -> dict[str, Any]:
    explicit = spec.height
    if family == "PAT14":
        mode = "relief"
    elif family == "PAT15":
        mode = "engrave"
    elif family == "PAT16":
        mode = "none"
    else:
        mode = "none"
    if explicit is not None and explicit.mode != "none":
        if mode == "none":
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"family {family} is appearance-only; a {explicit.mode} height policy is only "
                "valid for PAT14/PAT15 (or PAT16 with allow_geometry=True)",
                stage="patterns.api.build_pattern")
        if mode != explicit.mode:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"height mode {explicit.mode!r} contradicts family {family}",
                              stage="patterns.api.build_pattern")
    profile = explicit.profile if explicit is not None else "smoothstep"
    power = float(explicit.power) if explicit is not None else float(params.get("power", 1.0))
    max_fraction = (float(explicit.max_wall_fraction) if explicit is not None
                    else float(params.get("max_wall_fraction", 0.25)))
    amplitude = 0.0
    if mode == "relief":
        amplitude = float(explicit.amplitude_mm) if explicit is not None and explicit.amplitude_mm > 0 \
            else float(params.get("height_mm", 1.0))
    elif mode == "engrave":
        amplitude = float(explicit.amplitude_mm) if explicit is not None and explicit.amplitude_mm > 0 \
            else float(params.get("depth_mm", 0.6))
    return {"mode": mode, "amplitude_mm": amplitude, "profile": profile, "power": power,
            "max_wall_fraction": max_fraction, "target_tags": [],
            "policy": "GEOMETRY_BEFORE_FRACTURE: applied to the complete mother before any cut",
            "appearance_only_normal_map": False,
            "units": {"amplitude": "mm", "max_wall_fraction": "1"}}


def _finalise_height(height: dict[str, Any], family: str, params: dict[str, Any],
                     frame: ChartFrame, spec: PatternSpec) -> dict[str, Any]:
    out = dict(height)
    out["target_tags"] = [frame.tag_name]
    out["family"] = family
    if family == "PAT16":
        geometry_index = params.get("geometry_layer")
        if geometry_index is None:
            out["mode"] = "none"
            out["amplitude_mm"] = 0.0
        else:
            sub = params["layers"][int(geometry_index)]
            sub_family = str(sub["family"])
            out["mode"] = "relief" if sub_family == "PAT14" else "engrave"
            sub_params = dict(sub.get("params") or {})
            out["amplitude_mm"] = float(sub_params.get("height_mm", sub_params.get("depth_mm", 0.5)))
            out["power"] = float(sub_params.get("power", 1.0))
            out["max_wall_fraction"] = float(sub_params.get("max_wall_fraction", 0.25))
            out["geometry_layer_index"] = int(geometry_index)
    if out["mode"] != "none" and spec.height is not None:
        if spec.height.amplitude_mm > 0:
            out["amplitude_mm"] = float(spec.height.amplitude_mm)
        out["profile"] = spec.height.profile
        out["max_wall_fraction"] = float(spec.height.max_wall_fraction)
    # Smallest *geometric* feature the displacement field really has: the relief mask
    # feather (the transition width of the smoothstep mask) or the engraved groove width.
    # The mesh refinement rule uses this instead of the finest colour harmonic, because the
    # colour spectrum of a stroke set says nothing about how finely the height field must be
    # sampled on the surface.
    feature = out.get("geometry_feature_mm")
    if feature is None:
        if family == "PAT14":
            feature = float(params.get("mask_feather_mm") or 1.0)
        elif family == "PAT15":
            feature = float(params.get("line_width_mm") or 1.0)
        elif family == "PAT16" and out.get("geometry_layer_index") is not None:
            sub_params = dict(params["layers"][int(out["geometry_layer_index"])].get("params") or {})
            feature = float(sub_params.get("mask_feather_mm")
                            or sub_params.get("line_width_mm") or 1.0)
    if feature is not None and out["mode"] != "none":
        out["geometry_feature_mm"] = float(feature)
    out["max_slope_estimate"] = _slope_estimate(params, frame, out)
    return out


def _slope_estimate(params: dict[str, Any], frame: ChartFrame, height: dict[str, Any]) -> dict[str, Any]:
    feather = params.get("mask_feather_mm") or params.get("line_width_mm") or 1.0
    amplitude = float(height.get("amplitude_mm", 0.0))
    slope = amplitude / max(float(feather), 1e-6)
    return {"max_slope": float(slope), "units": "mm/mm",
            "basis": f"amplitude {amplitude:.3f} mm over the frozen mask feather {float(feather):.3f} mm"}


def _aux_layers(spec: PatternSpec, ctx: BuildContext, family: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not spec.allow_aux_layers or spec.max_aux_layers <= 0 or family == "PAT01":
        return [], {"enabled": False, "reason": "disabled by spec or plain family"}
    if family == "PAT16":
        return [], {"enabled": False, "reason": "PAT16 composes its own layers"}
    count = int(ctx.rng.integers(0, int(spec.max_aux_layers) + 1))
    kinds = list(AUX_KINDS)
    ctx.rng.shuffle(kinds)
    layers = []
    for index in range(count):
        kind = kinds[index % len(kinds)]
        payload = build_aux_layer(kind, ctx, rng=ctx.sub_rng(f"aux-{kind}"))
        payload["weight"] = float(ctx.rng.uniform(0.5, 1.0))
        layers.append(payload)
    return layers, {"enabled": bool(layers), "count": len(layers), "kinds": [p["kind"] for p in layers],
                    "max_aux_layers": int(spec.max_aux_layers)}


# ---------------------------------------------------------------------------------------
# evaluate (pure)
# ---------------------------------------------------------------------------------------
def _context(recipe: PatternRecipe):
    meta = recipe.meta or {}
    warp = WarpField.from_dict(meta.get("warp"))
    return field_context(meta, dict(meta.get("palette") or {}), warp)


def _composite(field, aux_layers: Sequence[dict[str, Any]], x_mm: np.ndarray,
               s_mm: np.ndarray, ctx) -> tuple[FieldOut, Any]:
    out = field.process(x_mm, s_mm, ctx)
    for aux in aux_layers:
        extra = build_field(str(aux["family"]), dict(aux)).process(x_mm, s_mm, ctx)
        alpha = np.clip(extra.coverage * float(aux.get("weight", 1.0)), 0.0, 1.0)
        out.paint = out.paint * (1.0 - alpha[:, None]) + extra.paint * alpha[:, None]
        out.roughness = out.roughness * (1.0 - alpha) + extra.roughness * alpha
        out.coverage = np.clip(out.coverage + alpha * (1.0 - out.coverage), 0.0, 1.0)
        out.modulation = np.maximum(out.modulation, extra.modulation * (alpha > 0))
    return out, ctx


def pattern_field(recipe: PatternRecipe, x_mm: np.ndarray, s_mm: np.ndarray) -> FieldOut:
    """Frozen composite field in chart millimetres (used by the audit and by tools)."""
    ctx = _context(recipe)
    field = build_field(recipe.family_id, recipe.params)
    out, _ = _composite(field, list((recipe.meta or {}).get("aux_layers") or []), x_mm, s_mm, ctx)
    return out


def _body_channels(recipe: PatternRecipe, n: int, reason: str, tag_name: str) -> PatternChannels:
    meta = recipe.meta or {}
    palette = dict(meta.get("palette") or {})
    body = np.asarray(palette.get("body", recipe.palette[0] if recipe.palette else (0.5, 0.5, 0.5)),
                      dtype=np.float64)
    return PatternChannels(
        albedo=np.tile(body.astype(np.float32), (n, 1)),
        roughness=np.full(n, float(palette.get("body_roughness", 0.6)), dtype=np.float32),
        height_mm=np.zeros(n, dtype=np.float32),
        pattern_region=np.zeros(n, dtype=np.uint8),
        meta={"family_id": recipe.family_id, "surface_tag": tag_name, "unpatterned_reason": reason,
              "body_albedo_source": "recipe palette body colour",
              "material_integration": "PENDING: synlab.materials.material_at",
              "recipe_hash": meta.get("recipe_hash", "")})


def _point_tags(mother: MotherGeometry, surface_tag: Any, n: int
                ) -> tuple[np.ndarray | None, str]:
    """Resolve the ``surface_tag`` argument: one tag for all points, or one tag per point.

    The fracture pipeline queries every mother vertex at once and passes a per-point tag
    array, so both forms are part of the frozen interface.  Values are never guessed: an
    unknown tag name or index raises a structured error.
    """
    if isinstance(surface_tag, (np.ndarray, list, tuple)):
        arr = np.asarray(surface_tag)
        if arr.ndim == 0:
            return None, mother.tag_name(tag_index(mother, arr.item()))
        if arr.ndim != 1 or arr.shape[0] != int(n):
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"surface_tag array must be (N,) with N={int(n)} points, got {arr.shape}",
                stage="patterns.api.evaluate")
        if arr.dtype.kind in "US":
            unique, inverse = np.unique(arr.astype(str), return_inverse=True)
            resolved = np.array([tag_index(mother, str(name)) for name in unique], dtype=np.int64)
        else:
            unique, inverse = np.unique(arr.astype(np.int64), return_inverse=True)
            resolved = np.array([tag_index(mother, int(value)) for value in unique], dtype=np.int64)
        values = resolved[np.asarray(inverse, dtype=np.int64)]
        names = sorted({mother.tag_name(int(value)) for value in np.unique(values)})
        return values, (names[0] if len(names) == 1 else "mixed[" + ",".join(names) + "]")
    if isinstance(surface_tag, str) and surface_tag == "interface":
        # a fresh fracture surface has no face on the intact mother: it is a virtual tag
        # whose channels are the body material (plan 9.1 step 6)
        return None, "interface"
    return None, mother.tag_name(tag_index(mother, surface_tag))


def evaluate(recipe: PatternRecipe, mother: MotherGeometry, points_mm: np.ndarray,
             surface_tag: int | str | np.ndarray) -> PatternChannels:
    """Evaluate the frozen pattern at mother millimetres.  Pure: no randomness is drawn."""
    if not isinstance(recipe, PatternRecipe):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"evaluate expects a PatternRecipe, got {type(recipe)!r}",
                          stage="patterns.api.evaluate")
    pts = np.asarray(points_mm, dtype=np.float64)
    if pts.size == 0:
        pts = np.zeros((0, 3), dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"points_mm must be (N,3), got {pts.shape}",
                          stage="patterns.api.evaluate")
    n = pts.shape[0]

    meta = recipe.meta or {}
    regions = list(meta.get("regions") or [])
    tag_values, tag_label = _point_tags(mother, surface_tag, n)
    if tag_values is None and tag_label == "interface":
        channels = _body_channels(recipe, n, "new_fracture_surface_exposes_body", "interface")
        channels.meta["policy"] = ("fresh fracture surfaces expose the body material and never "
                                   "inherit the painted pattern (plan 9.1 step 6)")
        return channels
    if not regions:
        return _body_channels(recipe, n, "recipe_has_no_region", tag_label)
    region = regions[0]
    region_tag_name = str(region.get("surface_tag"))
    try:
        region_tag = tag_index(mother, region_tag_name)
    except SynLabError:
        return _body_channels(recipe, n, f"region_tag_unknown:{region_tag_name}", tag_label)
    in_region_tag: np.ndarray | None = None
    if tag_values is None:
        if region_tag_name != tag_label:
            return _body_channels(recipe, n, "surface_outside_recipe_regions", tag_label)
    else:
        in_region_tag = tag_values == int(region_tag)
        if not bool(np.any(in_region_tag)):
            return _body_channels(recipe, n, "no_point_lies_on_the_recipe_region", tag_label)
    chart = mother.chart_for_tag(region_tag)
    if chart is None:
        return _body_channels(recipe, n, "mother_has_no_chart_for_tag", tag_label)
    frame = resolve_frame(mother, region_tag)
    frozen_period = float((meta.get("chart") or {}).get("x_period_mm") or 0.0)
    actual_period = float(frame.x_period_mm or 0.0)
    if frozen_period > 0 and actual_period > 0 \
            and abs(actual_period - frozen_period) > 1e-6 * frozen_period:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"mother chart period {actual_period:.6g} mm does not match the frozen recipe "
            f"period {frozen_period:.6g} mm: the recipe belongs to a different mother",
            stage="patterns.api.evaluate")
    x_mm, s_mm = to_chart_mm(frame, pts)
    weight = region_weight(frame, pts, x_mm, s_mm, region)
    if in_region_tag is not None:
        weight = weight * in_region_tag.astype(np.float64)

    palette = dict(meta.get("palette") or {})
    ctx = field_context(meta, palette, WarpField.from_dict(meta.get("warp")))
    field = build_field(recipe.family_id, recipe.params)
    out, _ = _composite(field, list(meta.get("aux_layers") or []), x_mm, s_mm, ctx)

    coverage = np.clip(out.coverage * weight, 0.0, 1.0)
    body = np.asarray(palette.get("body", recipe.palette[0]), dtype=np.float64)
    body_roughness = float(palette.get("body_roughness", 0.6))
    albedo = body[None, :] * (1.0 - coverage[:, None]) + out.paint * coverage[:, None]
    roughness = body_roughness * (1.0 - coverage) + out.roughness * coverage
    height = out.height_mm * weight
    region_mask = ((weight > 0.02) & (coverage > 0.02)).astype(np.uint8)

    return PatternChannels(
        albedo=np.clip(albedo, 0.0, 1.0).astype(np.float32),
        roughness=np.clip(roughness, 0.0, 1.0).astype(np.float32),
        height_mm=height.astype(np.float32),
        pattern_region=region_mask,
        meta={
            "family_id": recipe.family_id,
            "family_name": meta.get("family_name", recipe.family_id),
            "surface_tag": region_tag_name,
            "surface_tag_argument": tag_label,
            "points_on_region": (int(n) if in_region_tag is None else int(in_region_tag.sum())),
            "chart": frame.name,
            "x_period_mm": float(frame.x_period_mm or 0.0),
            "n_points": int(n),
            "footprint_mm": float(meta.get("footprint_mm", 0.0)),
            "aa_formula": "alpha = 1 - smoothstep(w/2-footprint, w/2+footprint, distance_mm)",
            "coverage_stats": weighted_stats(coverage, np.ones(n)),
            "height_stats_mm": {"min": float(height.min()) if n else 0.0,
                                "max": float(height.max()) if n else 0.0,
                                "mean_abs": float(np.abs(height).mean()) if n else 0.0},
            "height_policy": meta.get("height", {}),
            "region": region,
            "palette_id": meta.get("palette_id"),
            "color_space": meta.get("color_space"),
            "version": recipe.version,
            "recipe_hash": meta.get("recipe_hash", ""),
            "rng": "NONE: evaluate is a pure function of the frozen recipe",
            "new_fracture_surface": ("points whose tag is not the recipe region keep the body "
                                     "colour and carry zero pattern coverage"),
            "units": {"albedo": "linear rgb", "roughness": "1", "height_mm": "mm"},
        })


# ---------------------------------------------------------------------------------------
# re-exports that need the modules above
# ---------------------------------------------------------------------------------------
from .audit import audit_pattern  # noqa: E402  (import after the façade helpers)
from .commit import commit_pattern, load_pattern  # noqa: E402
from .geometry import apply_pattern_geometry  # noqa: E402
