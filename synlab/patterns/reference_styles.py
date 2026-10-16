"""Small, source-grounded style adapters for the existing pattern pipeline.

These adapters turn a documented object/process into an ordinary frozen
``PatternRecipe``. They deliberately do not infer a training distribution from a handful
of photographs, measure color from uncalibrated images, or claim exact reconstruction.
The pattern is evaluated only on a resolved, periodic ``outer_wall`` chart; the caller's
mother remains the source of the chart and millimetre scale.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import MotherGeometry, PatternChannels, PatternRecipe
from ..seeds import make_rng, seed_ref as make_seed_ref
from .api import build_pattern, evaluate
from .charts import resolve_frame, tag_index
from .params import PatternSpec, RegionSpec
from .serialize import recipe_hash, resource_hash as frozen_resource_hash

GENERATION_MODE = "SYNTHETIC_REFERENCE_GUIDED"
_OUTER_WALL = "outer_wall"

# These are design proxies in linear sRGB primaries, selected from source descriptions
# only. They are not sampled from photographs or measured reflectance data.
_DESIGN_PALETTES: dict[str, dict[str, Any]] = {
    "daily_hasami_tokusa": {
        "palette_id": "reference_tokusa_sandy_rust_proxy",
        "body": [0.68, 0.57, 0.43],
        "paints": [[0.12, 0.055, 0.034], [0.25, 0.105, 0.052], [0.42, 0.24, 0.13]],
        "body_roughness": 0.68,
        "paint_roughness": 0.48,
        "color_space": "linear_srgb_primaries",
        "tradition": "source-described sandy iron-heavy body and rusty underglaze; uncalibrated design proxy",
    },
    "historical_met_jun_plain": {
        "palette_id": "reference_jun_bluegrey_proxy",
        "body": [0.30, 0.36, 0.42],
        "paints": [[0.30, 0.36, 0.42]],
        "body_roughness": 0.42,
        "paint_roughness": 0.38,
        "color_space": "linear_srgb_primaries",
        "tradition": "source-described blue-gray glaze; uncalibrated design proxy",
    },
}

_BUILDABLE: dict[str, dict[str, Any]] = {
    "daily_hasami_tokusa": {
        "style_id": "daily_hasami_tokusa",
        "display_name": "Hasami Sabi Togusa rice bowl stripes",
        "evidence_status": "SOURCE_DESCRIPTION_AND_PRODUCT_PHOTOGRAPH_REVIEWED",
        "render_status": GENERATION_MODE,
        "source": {
            "title": "Rice Bowl / SABI TOGUSA",
            "url": "https://www.hasamiyaki.jp/en/item/sabitokusa-chawan/",
            "publisher": "Maruhiro / HASAMI",
            "reported_object": "13 cm diameter x 6 cm, 300 cc pottery rice bowl; Rizaemon Kiln, Hasami",
        },
        "process": "Maker describes hand-painted tokusa vertical stripes on a sandy, iron-heavy body with rusty underglaze.",
        "motif_and_meaning": "The maker connects tokusa to horsetail grass and its upward growth; the series text associates the motif with success and prosperity. This is source-reported context, not a claim about every tokusa use.",
        "visual_notes": "The reviewed product image shows repeated narrow, dark vertical strokes on the exterior bowl wall and an undecorated light interior. The exact stroke count, widths, spacing, and paint chemistry are not reported.",
        "pattern_mapping": {
            "family": "PAT03",
            "allowed_families": ["PAT03"],
            "surface_tag": _OUTER_WALL,
            "zone": "outer-wall body with a modest edge margin; stripes follow the meridian and repeat around azimuth",
            "params": {"tilt_deg": 0.0, "n_groups": 1, "thin_ratio": 1.0},
            "defaults": {"line_width_mm": 1.0, "spacing_mm": 10.0, "s_margin_frac": 0.10},
            "override_ranges": {"line_width_mm": [0.5, 3.0], "spacing_mm": [5.0, 30.0], "s_margin_frac": [0.0, 0.35]},
        },
        "palette": {
            "palette_id": _DESIGN_PALETTES["daily_hasami_tokusa"]["palette_id"],
            "status": "SOURCE_DESCRIPTION_GUIDED_UNCALIBRATED_DESIGN_PROXY",
            "limits": "No photo-derived RGB, reflectance, glaze BRDF, brush-bleed or pigment-diffusion calibration.",
        },
        "known": [
            "The product is a daily-use rice bowl; page gives diameter, height, capacity, maker and place.",
            "The maker names the hand-painted vertical tokusa motif and its horsetail reference.",
            "Pattern surface is the exterior wall; its circumferential repetition is implemented with PAT03's periodic integer count.",
        ],
        "unknown": [
            "Exact stripe count, spacing, width, brush profile, stroke order, pigment composition and firing schedule.",
            "Calibrated color, reflectance, glaze thickness, surface roughness and batch-to-batch variation.",
            "Full wall section and exact product meridian.",
        ],
    },
    "historical_met_jun_plain": {
        "style_id": "historical_met_jun_plain",
        "display_name": "Met 18.56.44 plain Jun-glazed bowl surface",
        "evidence_status": "CATALOGUE_DESCRIPTION_AND_PRODUCT_PHOTOGRAPH_REVIEWED",
        "render_status": GENERATION_MODE,
        "source": {
            "title": "Bowl, 18.56.44",
            "url": "https://www.metmuseum.org/art/collection/search/52389",
            "publisher": "The Metropolitan Museum of Art",
            "reported_object": "China, Jin dynasty (1115-1234), 12th-13th century; stoneware with blue-gray glaze; H 54 mm, rim D 111 mm, foot D 54 mm; Met Open Access / Public Domain image",
        },
        "process": "Catalogue identifies stoneware with blue-gray glaze (Jun ware). It does not give this bowl's glaze recipe or firing schedule.",
        "motif_and_meaning": "No painted or incised motif is documented for this catalogued bowl; this adapter encodes an unpatterned outer-wall field only.",
        "visual_notes": "The reviewed official photograph shows a continuous blue-gray surface on the bowl. This is a qualitative visual observation, not calibrated color or a section drawing.",
        "pattern_mapping": {
            "family": "PAT01",
            "allowed_families": ["PAT01"],
            "surface_tag": _OUTER_WALL,
            "zone": "full measured outer-wall chart; no motif overlay",
            "params": {"low_freq_color": False, "roughness_variation": 0.0},
            "defaults": {"s_margin_frac": 0.0},
            "override_ranges": {"s_margin_frac": [0.0, 0.20]},
        },
        "palette": {
            "palette_id": _DESIGN_PALETTES["historical_met_jun_plain"]["palette_id"],
            "status": "SOURCE_DESCRIPTION_GUIDED_UNCALIBRATED_DESIGN_PROXY",
            "limits": "A flat blue-gray PAT01 albedo proxy only; no glaze layer, pooling, opalescence, crazing, chemistry, thickness or firing physics.",
        },
        "known": [
            "The Met records the period, stoneware, blue-gray Jun glaze, height, rim diameter and foot diameter.",
            "The adapter contributes no geometric decoration and selects only the named exterior wall chart.",
        ],
        "unknown": [
            "Complete section, local wall thickness, glaze chemistry/thickness, firing schedule and calibrated BRDF/color.",
            "The catalogue does not document an object-specific motif or a glaze distribution for this single bowl.",
        ],
    },
}

_RESEARCH_CANDIDATES: dict[str, dict[str, Any]] = {
    "research_met_hacilar_chevron": {
        "style_id": "research_met_hacilar_chevron",
        "display_name": "Met 64.286.3 Hacilar painted vessel (research only)",
        "evidence_status": "PRIMARY_CATALOGUE_DESCRIPTION_REVIEWED_NOT_MAPPED_TO_RENDERABLE_SOURCE_ZONES",
        "render_status": "RESEARCH_ONLY_NOT_BUILDABLE",
        "source": {
            "title": "Vessel, 64.286.3",
            "url": "https://www.metmuseum.org/art/collection/search/325698",
            "publisher": "The Metropolitan Museum of Art",
            "reported_object": "Southwestern Anatolia, ca. 5600-5400 BCE; ceramic, paint; 112 x 106 x 106 mm; Met Open Access / Public Domain image",
        },
        "process": "The catalogue describes hand-made, thin-walled ceramic decorated with red paint on cream slip; workshop production is noted, but this object's pigment recipe and painting sequence are not reported.",
        "motif_and_meaning": "The source describes two red horizontal rim bands, vertical chevrons in groups of three, and concentric circles around two side projections. It calls the red-on-cream geometric scheme characteristic of Hacilar, while noting the vessel's site is unidentified. No broader symbolic meaning is asserted.",
        "visual_notes": "A direct photograph was reviewed. The composition is on the vessel exterior and has a rim-framing pair plus grouped vertical chevrons; side projections have concentric-circle decoration. No pattern code is enabled because the current generic outer-wall recipe cannot faithfully map the rim and projection zones on an arbitrary mother.",
        "pattern_mapping": {
            "family": None,
            "allowed_families": [],
            "surface_tag": None,
            "zone": "unresolved: rim, exterior wall and projection zones need separate measured charts",
            "blocked_reason": "Do not substitute PAT07 triangles for chevrons, PAT10 foliage for another motif, or place an interior field on an outer-wall chart. A source-bound mapped motif and geometry-compatible zone layout are required.",
        },
        "palette": {"status": "NOT_IMPLEMENTED", "limits": "No invented red/cream colors are attached to a buildable recipe."},
        "known": [
            "Source description documents the pattern, process family, placement and object dimensions.",
            "The documented decoration is exterior; the reported vessel has side projections.",
        ],
        "unknown": [
            "Object-specific archaeological site, exact chevron proportions/count, pigment composition and application sequence.",
            "How the current target mother charts would represent rim and projection surfaces; no source-aligned recipe is emitted.",
        ],
    }
}


def _all_records() -> dict[str, dict[str, Any]]:
    return {**_BUILDABLE, **_RESEARCH_CANDIDATES}


def list_reference_styles(*, include_research: bool = False) -> tuple[dict[str, Any], ...]:
    """List buildable source-guided styles, optionally including blocked research records."""
    records = _BUILDABLE if not include_research else _all_records()
    return tuple(copy.deepcopy(records[key]) for key in sorted(records))


def reference_style_record(style_id: str) -> dict[str, Any]:
    """Return a detached evidence/mapping record for one buildable or research style."""
    try:
        return copy.deepcopy(_all_records()[str(style_id)])
    except KeyError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown reference style {style_id!r}; known: {sorted(_all_records())}",
                          stage="patterns.reference_styles.reference_style_record") from exc


def _resolve_outer_frame(mother: MotherGeometry):
    if not isinstance(mother, MotherGeometry):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"reference pattern needs a MotherGeometry, got {type(mother)!r}",
                          stage="patterns.reference_styles.build_reference_pattern")
    tag = tag_index(mother, _OUTER_WALL)
    if not np.any(np.asarray(mother.face_surface_tag, dtype=np.int64) == int(tag)):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "mother has an outer_wall name but no faces carry that tag",
                          stage="patterns.reference_styles.build_reference_pattern")
    frame = resolve_frame(mother, _OUTER_WALL)
    if not frame.u_periodic or frame.x_period_mm is None or frame.x_period_mm <= 0.0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "reference exterior styles need a measured periodic outer-wall chart",
                          stage="patterns.reference_styles.build_reference_pattern")
    if frame.s_span_mm <= 3.0 or frame.area_mm2 <= 0.0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "outer-wall chart has no usable measured profile span/area",
                          stage="patterns.reference_styles.build_reference_pattern")
    return frame


def _validate_overrides(style_id: str, overrides: dict[str, Any] | None) -> dict[str, float]:
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "overrides must be a dictionary",
                          stage="patterns.reference_styles.build_reference_pattern")
    allowed = set(_BUILDABLE[style_id]["pattern_mapping"]["override_ranges"])
    rejected = sorted(set(overrides) - allowed)
    if rejected:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unsupported or source-migrating reference-style overrides: {rejected}; "
                          f"allowed: {sorted(allowed)}",
                          stage="patterns.reference_styles.build_reference_pattern")
    validated: dict[str, float] = {}
    for key, raw in overrides.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"override {key!r} must be a finite number",
                              stage="patterns.reference_styles.build_reference_pattern")
        value = float(raw)
        lo, hi = _BUILDABLE[style_id]["pattern_mapping"]["override_ranges"][key]
        if not lo <= value <= hi:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"override {key!r}={value} outside documented range [{lo}, {hi}]",
                              stage="patterns.reference_styles.build_reference_pattern")
        validated[key] = value
    return validated


def _attach_reference_palette(recipe: PatternRecipe, style_id: str) -> None:
    palette = copy.deepcopy(_DESIGN_PALETTES[style_id])
    recipe.meta["palette"] = palette
    recipe.meta["palette_id"] = str(palette["palette_id"])
    recipe.meta["color_space"] = str(palette["color_space"])
    recipe.palette = [tuple(float(value) for value in palette["body"])] + [
        tuple(float(value) for value in colour) for colour in palette["paints"]
    ]
    if recipe.family_id == "PAT01":
        # PlainField freezes these two values in its family payload, unlike stripe paint
        # colors which are resolved from the frozen recipe palette at query time.
        recipe.params["base_color"] = [float(value) for value in palette["body"]]
        recipe.params["base_roughness"] = float(palette["body_roughness"])
    # The public recipe resource hash covers its frozen coefficient payload; this adapter
    # uses no external files, so recompute it with the same NONE resource record as build.
    recipe.resource_hash = frozen_resource_hash(
        [{"kind": "NONE", "detail": "family has no external resource"}], recipe.params)


def build_reference_pattern(mother: MotherGeometry, style_id: str, seed: int,
                            overrides: dict[str, Any] | None = None) -> PatternRecipe:
    """Build one existing ``PatternRecipe`` under a source-bound style contract.

    The output is directly consumable by ``synlab.patterns.api.evaluate`` and the normal
    pattern serialization/audit functions. Family, process, palette mapping and surface tag
    are fixed by the selected source record; only its explicitly documented numeric design
    ranges are caller-adjustable.
    """
    style_id = str(style_id)
    if style_id in _RESEARCH_CANDIDATES:
        candidate = _RESEARCH_CANDIDATES[style_id]
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{style_id!r} is research-only: "
                          f"{candidate['pattern_mapping']['blocked_reason']}",
                          stage="patterns.reference_styles.build_reference_pattern")
    if style_id not in _BUILDABLE:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown buildable reference style {style_id!r}; "
                          f"known: {sorted(_BUILDABLE)}",
                          stage="patterns.reference_styles.build_reference_pattern")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "seed must be an integer",
                          stage="patterns.reference_styles.build_reference_pattern")
    frame = _resolve_outer_frame(mother)
    user = _validate_overrides(style_id, overrides)
    style = _BUILDABLE[style_id]
    mapping = style["pattern_mapping"]
    defaults = dict(mapping["defaults"])
    defaults.update(user)
    params = dict(mapping["params"])
    family = str(mapping["family"])
    if family == "PAT03":
        params.update({"line_width_mm": defaults["line_width_mm"],
                       "spacing_mm": defaults["spacing_mm"]})
    region = RegionSpec(surface_tag=_OUTER_WALL,
                        s_margin_frac=float(defaults["s_margin_frac"]),
                        feather_mm=(1.0 if family == "PAT03" else 0.0))
    seed_path = (mother.mother_id or mother.vessel_id or "mother", style_id, "pattern")
    rng = make_rng(int(seed), *seed_path)
    spec = PatternSpec(
        family=family,
        complexity=1,
        palette_id=("iron_slip" if style_id == "daily_hasami_tokusa" else "ash_grey"),
        surface_tag=_OUTER_WALL,
        region=region,
        allow_aux_layers=False,
        max_aux_layers=0,
        quota_class="PLAIN" if family == "PAT01" else "STRONG_REPEAT",
        seed_ref=make_seed_ref(int(seed), *seed_path),
        params=params,
    )
    recipe = build_pattern(mother, spec, rng)
    _attach_reference_palette(recipe, style_id)
    reference_metadata = {
        "style_id": style_id,
        "generation_mode": GENERATION_MODE,
        "evidence_status": style["evidence_status"],
        "source_url": style["source"]["url"],
        "process": style["process"],
        "motif_and_meaning": style["motif_and_meaning"],
        "surface_tag": _OUTER_WALL,
        "mapping": copy.deepcopy(mapping),
        "palette_status": style["palette"]["status"],
        "palette_limits": style["palette"]["limits"],
        "known": list(style["known"]),
        "unknown": list(style["unknown"]),
        "mother_id": mother.mother_id,
        "mother_vessel_id": mother.vessel_id,
        "chart": frame.as_dict(),
        "caller_overrides": user,
        "distribution_claim": "none; defaults are documented recipe choices, not learned estimates",
    }
    recipe.meta["reference_style"] = reference_metadata
    recipe.meta["recipe_hash"] = recipe_hash(recipe)
    return recipe


def sample_reference_style(mother: MotherGeometry, style_id: str,
                           points_mm: np.ndarray, surface_tag: int | str | np.ndarray,
                           seed: int, overrides: dict[str, Any] | None = None
                           ) -> tuple[PatternRecipe, PatternChannels]:
    """Build a source-bound recipe and evaluate it with the standard pure evaluator.

    ``surface_tag`` must be the source recipe's exterior tag (or an all-exterior array).
    For mixed tags and fracture interfaces use ``evaluate`` directly so its normal body
    material fallback remains explicit.
    """
    if isinstance(surface_tag, np.ndarray):
        values = np.asarray(surface_tag)
        if values.ndim != 1:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "surface_tag array must be one-dimensional",
                              stage="patterns.reference_styles.sample_reference_style")
        names = {mother.tag_name(int(tag_index(mother, value.item())))
                 for value in np.unique(values)}
        if names != {_OUTER_WALL}:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "reference style samples are restricted to outer_wall",
                              stage="patterns.reference_styles.sample_reference_style")
    else:
        if mother.tag_name(int(tag_index(mother, surface_tag))) != _OUTER_WALL:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "reference style samples are restricted to outer_wall",
                              stage="patterns.reference_styles.sample_reference_style")
    recipe = build_reference_pattern(mother, style_id, seed, overrides)
    return recipe, evaluate(recipe, mother, np.asarray(points_mm, dtype=np.float64), surface_tag)


__all__ = [
    "GENERATION_MODE",
    "build_reference_pattern",
    "list_reference_styles",
    "reference_style_record",
    "sample_reference_style",
]
