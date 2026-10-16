"""Source-conditioned ceramic material recipes for the first A12 style slice.

The registered M01..M12 catalogue remains the procedural material engine.  This module binds
three of those bodies to named, documented object/style references while making the boundary
between source facts and design choices explicit.  It does not calibrate optical or mechanical
properties from photographs or museum metadata.

Public API
----------
``list_reference_materials()``
    Return JSON-safe summaries of the available source-conditioned recipes.
``reference_material(style_id, controls=None, seed=0)``
    Build the existing material profile and attach object, evidence, and control provenance.
``sample_reference_material(profile, points_mm, surface_tag)``
    Query the mother-coordinate field and include transmission from the selected layer. Pass
    ``depth_mm`` only with the explicit ``volume`` tag when volume sampling is needed.
``process_compatibility(material_class, process)``
    Assess a named surface process against a substrate class without treating unknown firing
    history as a fact.

Reference profiles use a versioned ``original_surface_tags`` policy: original outer wall,
inner wall, and rim faces can carry an appearance-only finish, while foot/base and new fracture
faces expose the body. Surface queries always have zero query depth. A separate explicit
``volume`` query may supply ``depth_mm`` to select a layer for a renderer; the design band is
not a measured or physical glaze thickness. Use :mod:`synlab.materials.layers` when an actual
geometric body is required.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..seeds import make_rng, seed_ref
from .api import MODE_SHADING, build_material_profile, material_at, validate_profile

STAGE = "materials.reference_materials"
SCHEMA_REFERENCE_MATERIAL = "shardforge.reference_material_profile.v1"
REFERENCE_SURFACE_POLICY_VERSION = 1
REFERENCE_FIELD_KERNEL_VERSION = 2


# Values in ``default_controls`` are rendering/design defaults.  The cited objects do not have
# measured spectral reflectance, roughness, IOR, or glaze-thickness records.
_RECIPES: dict[str, dict[str, Any]] = {
    "daily_aberdeen_porcelain_celadon": {
        "name": "Daily footed porcelain bowl with celadon",
        "material_id": "M04",
        "material_class": "porcelain",
        "source": {
            "source_id": "aberdeen_ABDMS095708.121",
            "institution": "Aberdeen City Museums and Galleries",
            "object_id": "ABDMS095708.121",
            "title": "Porcelain Small Footed Bowl",
            "url": "https://emuseum.aberdeencity.gov.uk/objects/186848/porcelain-small-footed-bowl",
            "facts": [
                {"field": "medium", "value": "Limoges porcelain and celadon",
                 "evidence": "object record"},
                {"field": "maker", "value": "Chris Keenan", "evidence": "object record"},
                {"field": "date", "value": "2007–2009", "evidence": "object record"},
                {"field": "height_mm", "value": 53, "evidence": "object record"},
                {"field": "overall_diameter_mm", "value": 108, "evidence": "object record"},
                {"field": "foot_ring_diameter_mm", "value": 31, "evidence": "object record"},
                {"field": "visual_observation", "value":
                 "pale blue-green interior and exterior, dark rust upper band, pale foot",
                 "evidence": "qualitative observation of the primary object photographs; not colorimetry"},
            ],
            "unknowns": [
                "full inner and outer meridian",
                "wall, base, rim, and foot cross-sections",
                "forming and firing schedule",
                "celadon glaze chemistry and measured thickness",
                "spectral reflectance, roughness, and index of refraction",
                "lot-specific mechanical properties",
            ],
            "accessed_date": "2026-10-15",
            "rights_note": "The object page identifies copyrighted images; this recipe records metadata and qualitative observations only.",
        },
        "default_controls": {
            "body_albedo_linear_rgb": [0.774, 0.770, 0.751],
            "body_roughness": 0.34,
            "body_ior": 1.56,
            "grain_scale_mm": 0.18,
            "pore_scale_mm": 0.50,
            "grain_amount": 0.04,
            "pore_amount": 0.03,
            "coating_albedo_linear_rgb": [0.34, 0.49, 0.44],
            "coating_roughness": 0.14,
            "coating_ior": 1.51,
            "coating_transmission": 0.02,
            "coating_band_mm": 0.22,
        },
        "control_facts": {
            "coating_present": "Celadon is named in the object medium; layer geometry and properties are not specified.",
        },
        "reference_dimensions_mm": {"r_outer_mm": 54.0, "z_rim_mm": 53.0},
        "coated_surface_tags": ["outer_wall", "inner_wall", "rim"],
        "bare_body_surface_tags": ["foot", "base", "interface", "attachment"],
    },
    "historical_met_jun_stoneware_glaze": {
        "name": "Jun ware blue-gray glazed stoneware bowl",
        "material_id": "M03",
        "material_class": "stoneware",
        "source": {
            "source_id": "met_18.56.44",
            "institution": "The Metropolitan Museum of Art",
            "object_id": "18.56.44",
            "title": "Bowl",
            "url": "https://www.metmuseum.org/art/collection/search/52389",
            "facts": [
                {"field": "medium", "value": "Stoneware with blue-gray glaze (Jun ware)",
                 "evidence": "object record"},
                {"field": "date", "value": "12th–13th century", "evidence": "object record"},
                {"field": "height_mm", "value": 54, "evidence": "object record"},
                {"field": "diameter_mm", "value": 111, "evidence": "object record"},
                {"field": "rim_diameter_mm", "value": 111, "evidence": "object record"},
                {"field": "foot_diameter_mm", "value": 54, "evidence": "object record"},
            ],
            "unknowns": [
                "full inner and outer meridian",
                "wall, base, rim, and foot cross-sections",
                "forming and firing schedule",
                "glaze chemistry and measured thickness",
                "spectral reflectance, roughness, and index of refraction",
                "lot-specific mechanical properties",
            ],
            "accessed_date": "2026-10-15",
            "rights_note": "The Met marks the object image Public Domain and its Open Access data available for reuse.",
        },
        "default_controls": {
            "body_albedo_linear_rgb": [0.22, 0.25, 0.27],
            "body_roughness": 0.52,
            "body_ior": 1.54,
            "grain_scale_mm": 0.80,
            "pore_scale_mm": 6.0,
            "grain_amount": 0.08,
            "pore_amount": 0.06,
            "coating_albedo_linear_rgb": [0.27, 0.37, 0.47],
            "coating_roughness": 0.16,
            "coating_ior": 1.52,
            "coating_transmission": 0.0,
            "coating_band_mm": 0.35,
        },
        "control_facts": {
            "coating_present": "The medium names a blue-gray glaze; layer geometry and properties are not specified.",
        },
        "reference_dimensions_mm": {"r_outer_mm": 55.5, "z_rim_mm": 54.0},
        "coated_surface_tags": ["outer_wall", "inner_wall", "rim"],
        "bare_body_surface_tags": ["foot", "base", "interface", "attachment"],
    },
    "historical_met_50899_porcelain_clear_underglaze": {
        "name": "Met 50899 porcelain with clear-glaze appearance proxy",
        "material_id": "M04",
        "material_class": "porcelain",
        "source": {
            "source_id": "met_29.149.50",
            "institution": "The Metropolitan Museum of Art",
            "object_id": "50899",
            "accession_number": "29.149.50",
            "title": "Vase with dragon",
            "url": "https://www.metmuseum.org/art/collection/search/50899",
            "facts": [
                {"field": "object_name", "value": "Vase", "evidence": "object record"},
                {"field": "accession_number", "value": "29.149.50",
                 "evidence": "object record"},
                {"field": "culture", "value": "China", "evidence": "object record"},
                {"field": "date", "value":
                 "late 18th century; Qianlong period (1736–95), Qing dynasty (1644–1911)",
                 "evidence": "object record"},
                {"field": "medium", "value":
                 "Porcelain painted in underglaze cobalt blue (Jingdezhen ware)",
                 "evidence": "object record"},
                {"field": "height_mm", "value": 184, "evidence": "object record"},
                {"field": "object_image_rights", "value": "Public Domain",
                 "evidence": "object record"},
                {"field": "visual_observation", "value":
                 "the retained O2 photograph shows a pale warm-white body, blue decoration, and bright surface reflections",
                 "evidence": "qualitative observation of the primary object photograph; illumination, camera, and surface response are not separated; not colorimetry"},
            ],
            "unknowns": [
                "overall diameter, maximum width, full inner and outer meridian, and local cross-sections",
                "whether a distinct clear glaze layer is present and its composition or measured thickness",
                "forming and firing schedule",
                "spectral reflectance, roughness, and index of refraction",
                "lot-specific mechanical properties",
            ],
            "accessed_date": "2026-10-15",
            "rights_note": "The Met object page identifies the object image as Public Domain; the photograph is used only for qualitative appearance context.",
            "visual_observation_boundary": "The pale warm-white body and bright reflections are photograph observations only; no white-point, colorimetry, gloss, or glaze property is inferred.",
        },
        "default_controls": {
            "body_albedo_linear_rgb": [0.88, 0.86, 0.80],
            "body_roughness": 0.36,
            "body_ior": 1.56,
            "grain_scale_mm": 0.18,
            "pore_scale_mm": 0.50,
            "grain_amount": 0.03,
            "pore_amount": 0.02,
            "coating_albedo_linear_rgb": [0.96, 0.95, 0.91],
            "coating_roughness": 0.11,
            "coating_ior": 1.50,
            "coating_transmission": 0.02,
            "coating_band_mm": 0.20,
        },
        "control_facts": {
            "coating_present_status": "DESIGN_CHOICE",
            "coating_present_note": "A clear/pale appearance-only layer is a rendering proxy; the object record names underglaze cobalt but does not describe a distinct clear-glaze layer or its properties.",
        },
        "source_decoration": {
            "process": "underglaze_cobalt",
            "fact": "Porcelain painted in underglaze cobalt blue (Jingdezhen ware)",
        },
        "reference_dimensions_mm": {"r_outer_mm": None, "z_rim_mm": 184.0},
        "geometry_note": "Only source height is known. It is retained as metadata; no diameter is invented and material sampling does not rescale or reconstruct object geometry.",
        "surface_layer_name": "clear_glaze_appearance_proxy",
        "layer_semantics_note": "The clear/pale appearance-only layer is a design proxy and is not a claim about glaze chemistry, physical thickness, or a separately documented clear glaze.",
        "coated_surface_tags": ["outer_wall", "inner_wall", "rim"],
        "bare_body_surface_tags": ["foot", "base", "new_fracture", "interface", "attachment"],
    },
    "historical_smithsonian_colonoware_unglazed": {
        "name": "Colonoware unglazed earthenware pot",
        "material_id": "M02",
        "material_class": "earthenware",
        "source": {
            "source_id": "smithsonian_NMAAHC_2017.108.1.1",
            "institution": "Smithsonian National Museum of African American History and Culture",
            "object_id": "2017.108.1.1",
            "title": "Colonoware pot, Cooper River, Charleston County, SC",
            "url": "https://3d.si.edu/object/3d/colonoware-pot-cooper-river-charleston-county-sc%3A79da3e3f-3ad7-41de-8956-e891d88a3c5f",
            "catalogue_url": "https://nmaahc.si.edu/object/nmaahc_2017.108.1.1",
            "facts": [
                {"field": "medium", "value": "clay, glue, plaster of Paris and paint",
                 "evidence": "object record"},
                {"field": "material_classification", "value":
                 "ceramic pottery; earthenware is the adapter's broad design classification",
                 "evidence": "adapter classification, not a petrographic analysis"},
                {"field": "surface", "value": "unglazed", "evidence": "object record"},
                {"field": "date", "value": "about 1700–1800", "evidence": "object record"},
                {"field": "height_mm", "value": 230, "evidence": "object record"},
                {"field": "diameter_mm", "value": 267, "evidence": "object record"},
                {"field": "qualitative_form", "value": "rounded body, rounded base, narrow neck, slightly flared rim",
                 "evidence": "object record"},
                {"field": "decoration", "value":
                 "stippling band around the neck, irregular vertical stippled lines, outlined geometric shapes, and circular marks",
                 "evidence": "object record"},
                {"field": "condition", "value":
                 "cross-mended breaks and plaster base repair; dark stains, paint marks, and localized losses are described",
                 "evidence": "object record"},
            ],
            "unknowns": [
                "clay recipe, temper, and particle-size distribution",
                "forming and firing schedule",
                "porosity and moisture condition",
                "spectral reflectance, roughness, and index of refraction",
                "lot-specific mechanical properties",
                "mesh scale, wall thickness, and complete internal surface coverage",
            ],
            "accessed_date": "2026-10-15",
            "rights_note": "The Smithsonian 3D page identifies public-domain/CC0 reuse; preserve Smithsonian attribution.",
        },
        "default_controls": {
            "body_albedo_linear_rgb": [0.38, 0.22, 0.13],
            "body_roughness": 0.78,
            "body_ior": 1.52,
            "grain_scale_mm": 0.55,
            "pore_scale_mm": 1.1,
            "grain_amount": 0.12,
            "pore_amount": 0.20,
        },
        "control_facts": {},
        "reference_dimensions_mm": {"r_outer_mm": 133.5, "z_rim_mm": 230.0},
        "coated_surface_tags": [],
        "bare_body_surface_tags": ["outer_wall", "inner_wall", "rim", "foot", "base",
                                    "interface", "attachment"],
    },
}

_COMMON_CONTROLS = {
    "body_albedo_linear_rgb", "body_roughness", "body_ior", "grain_scale_mm",
    "pore_scale_mm", "grain_amount", "pore_amount", "aggregate_radius_mm",
    "aggregate_density_per_mm3",
}
_COATING_CONTROLS = {
    "coating_albedo_linear_rgb", "coating_roughness", "coating_ior",
    "coating_transmission", "coating_band_mm",
}


def list_reference_materials() -> list[dict[str, Any]]:
    """List the source-conditioned recipes in stable ID order."""
    rows: list[dict[str, Any]] = []
    for style_id, recipe in sorted(_RECIPES.items()):
        rows.append({
            "style_id": style_id,
            "name": recipe["name"],
            "material_id": recipe["material_id"],
            "material_class": recipe["material_class"],
            "material_class_evidence_status": (
                "DESIGN_CLASSIFICATION"
                if style_id == "historical_smithsonian_colonoware_unglazed" else "SOURCE_FACT"),
            "source_id": recipe["source"]["source_id"],
            "source_url": recipe["source"]["url"],
            "source_material_facts": copy.deepcopy(recipe["source"]["facts"]),
            "optical_measurements": "UNKNOWN",
            "mechanics": "UNKNOWN",
        })
    return rows


def reference_material(style_id: str, controls: Mapping[str, Any] | None = None,
                       seed: int = 0) -> dict[str, Any]:
    """Build a deterministic, source-bound material profile for one named object style.

    ``controls`` exposes shared body controls and, for the two glazed references, dedicated
    coating controls. Every numeric optical or procedural value is tagged ``DESIGN_CHOICE``
    unless it is a categorical object fact, such as the named presence of a glaze.
    """
    if style_id not in _RECIPES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown reference material style {style_id!r}", stage=STAGE,
                          measurements={"available": sorted(_RECIPES)})
    recipe = _RECIPES[style_id]
    supplied = dict(controls or {})
    allowed = set(_COMMON_CONTROLS)
    has_coating = any("coating" in key for key in recipe["default_controls"])
    if has_coating:
        allowed |= _COATING_CONTROLS
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{style_id}: unknown controls {unknown}", stage=f"{STAGE}.controls",
                          measurements={"allowed": sorted(allowed)})

    chosen = copy.deepcopy(recipe["default_controls"])
    chosen.update(supplied)
    _validate_controls(style_id, chosen)

    # Reuse the catalogue profile builder and preserve its coordinate-continuous field salt.
    profile = build_material_profile(
        recipe["material_id"], {}, make_rng(int(seed), "material", style_id))
    layers = profile["layers"]
    body_index = next((i for i, layer in enumerate(layers)
                       if layer.get("kind") == "base"), len(layers) - 1)
    body = layers[body_index]
    body["albedo"] = list(chosen["body_albedo_linear_rgb"])
    body["roughness"] = float(chosen["body_roughness"])
    body["ior"] = float(chosen["body_ior"])
    body["transmission"] = 0.0

    profile["stats"]["grain_scale_mm"] = float(chosen["grain_scale_mm"])
    profile["stats"]["pore_scale_mm"] = float(chosen["pore_scale_mm"])
    profile["stats"]["aggregate_radius_mm"] = float(chosen.get("aggregate_radius_mm", 0.0))
    profile["stats"]["aggregate_density_per_mm3"] = float(
        chosen.get("aggregate_density_per_mm3", 0.0))
    profile["appearance"]["grain_amount"] = float(chosen["grain_amount"])
    profile["appearance"]["pore_amount"] = float(chosen["pore_amount"])
    profile["appearance"]["albedo"] = list(chosen["body_albedo_linear_rgb"])
    profile["appearance"]["roughness"] = float(chosen["body_roughness"])
    profile["appearance"]["ior"] = float(chosen["body_ior"])

    surface_layer: dict[str, Any] | None = None
    if has_coating:
        surface_layer = next((layer for layer in layers if layer is not body), None)
        if surface_layer is None:  # pragma: no cover - catalogue style contract
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{style_id}: coated recipe has no surface layer", stage=STAGE)
        surface_layer.update({
            "name": recipe.get("surface_layer_name", "source_named_surface_finish"),
            "kind": "appearance",
            "mode": MODE_SHADING,
            "albedo": list(chosen["coating_albedo_linear_rgb"]),
            "roughness": float(chosen["coating_roughness"]),
            "ior": float(chosen["coating_ior"]),
            "transmission": float(chosen["coating_transmission"]),
            # Surface queries ignore this value. It only selects the appearance layer for an
            # explicit volume-depth query, and is not a physical glaze thickness.
            "thickness_mm": float(chosen["coating_band_mm"]),
        })

    # Source-conditioned profiles classify original mesh faces by their semantic surface tag.
    # This avoids treating the radial distance from a cylinder as glaze thickness on a rounded
    # vessel. These reference dimensions are envelope facts, not a reconstructed meridian.
    dimensions = recipe["reference_dimensions_mm"]
    profile["outer_reference"] = {
        "mode": "original_surface_tags",
        "r_outer_mm": (None if dimensions.get("r_outer_mm") is None
                        else float(dimensions["r_outer_mm"])),
        "r_inner_mm": (None if dimensions.get("r_outer_mm") is None else 0.0),
        "z_floor_mm": 0.0,
        "z_rim_mm": float(dimensions["z_rim_mm"]),
        "note": recipe.get(
            "geometry_note",
            "source envelope dimensions only; coating is queried by original semantic face tags"),
    }
    profile["coating_surface_policy"] = {
        "version": REFERENCE_SURFACE_POLICY_VERSION,
        "mode": "original_surface_tags",
        "coated_tags": list(recipe["coated_surface_tags"]),
        "bare_body_tags": list(recipe["bare_body_surface_tags"]),
        "volume_tag": "volume",
        "surface_query_depth_mm": 0.0,
        "volume_query_depth": "EXPLICIT_CALLER_DEPTH_REQUIRED",
    }
    # Version 1 of the field kernel had signed arithmetic right-shifts in its 64-bit hash.
    # Reference recipes opt in to the corrected unsigned SplitMix64 hash. Existing catalogue
    # profiles keep their historical field output because missing version means version 1.
    profile["field_kernel_version"] = REFERENCE_FIELD_KERNEL_VERSION
    profile["field_kernel"] = "value_noise+aggregate+fiber;splitmix64-logical-u64-v2"

    controls_evidence: dict[str, dict[str, Any]] = {}
    for key, value in chosen.items():
        controls_evidence[key] = {
            "value": copy.deepcopy(value),
            "status": "DESIGN_CHOICE",
            "unit": _control_unit(key),
            "source_measurement": None,
        }
    if has_coating:
        coating_presence_status = recipe["control_facts"].get(
            "coating_present_status", "SOURCE_FACT")
        controls_evidence["coating_present"] = {
            "value": True,
            "status": coating_presence_status,
            "unit": "categorical",
            "source_measurement": recipe["control_facts"].get("coating_present"),
        }
        if "coating_present_note" in recipe["control_facts"]:
            controls_evidence["coating_present"]["note"] = \
                recipe["control_facts"]["coating_present_note"]
        controls_evidence["physical_glaze_thickness_mm"] = {
            "value": None,
            "status": "UNKNOWN",
            "unit": "mm",
            "source_measurement": None,
        }

    profile["provenance"] = {
        "source_kind": "SOURCE_CONDITIONED_DESIGN",
        "note": ("Object identity, medium/finish labels, and listed dimensions come from the "
                 "linked primary object record. Numeric appearance and field parameters are "
                 "design choices, not measured distributions or optical properties."),
        "source_id": recipe["source"]["source_id"],
        "source_url": recipe["source"]["url"],
    }
    process_record = {
        "source_material_class": (
            "DESIGN_CLASSIFICATION"
            if style_id == "historical_smithsonian_colonoware_unglazed" else "SOURCE_FACT"),
        "forming_process": "SOURCE_FACT"
        if style_id == "daily_aberdeen_porcelain_celadon" else "UNKNOWN",
        "firing_schedule": "UNKNOWN",
        "glaze_chemistry": "UNKNOWN" if has_coating else "NOT_APPLICABLE_TO_UNGLAZED_SOURCE",
    }
    if "source_decoration" in recipe:
        decoration = recipe["source_decoration"]
        process_record["source_named_decoration"] = {
            "process": decoration["process"],
            "status": "SOURCE_FACT",
            "source_measurement": decoration["fact"],
            "compatibility": process_compatibility(recipe["material_class"],
                                                     decoration["process"]),
            "appearance_composition": "SEPARATE_FROM_SUBSTRATE_PROFILE",
        }
    profile["source_conditioned"] = {
        "schema": SCHEMA_REFERENCE_MATERIAL,
        "style_id": style_id,
        "style_name": recipe["name"],
        "material_class": recipe["material_class"],
        "material_class_evidence_status": (
            "DESIGN_CLASSIFICATION"
            if style_id == "historical_smithsonian_colonoware_unglazed" else "SOURCE_FACT"),
        "source_object": copy.deepcopy(recipe["source"]),
        "controls": controls_evidence,
        "optical_measurements_status": "UNKNOWN",
        "mechanics_status": "UNKNOWN",
        "process_compatibility": process_record,
        "layer_semantics": ({
            "mode": MODE_SHADING,
            "surface_policy": "original_surface_tags-v1",
            "coated_surface_tags": list(recipe["coated_surface_tags"]),
            "bare_body_surface_tags": list(recipe["bare_body_surface_tags"]),
            "surface_query_depth_mm": 0.0,
            "volume_query_depth": "EXPLICIT_CALLER_DEPTH_REQUIRED",
            "depth_band_parameter": "DESIGN_CHOICE_FOR_EXPLICIT_VOLUME_QUERY_ONLY",
            "physical_solid_status": "NOT_CREATED",
            "physical_thickness_status": "UNKNOWN",
            "note": recipe.get(
                "layer_semantics_note",
                "Original coated surface tags change sampled appearance only; no solid glaze is modeled."),
        } if has_coating else {
            "mode": MODE_SHADING,
            "surface_policy": "original_surface_tags-v1",
            "coated_surface_tags": [],
            "bare_body_surface_tags": list(recipe["bare_body_surface_tags"]),
            "surface_query_depth_mm": 0.0,
            "physical_solid_status": "NOT_APPLICABLE_SOURCE_IS_UNGLAZED",
        }),
        "profile_seed": int(seed),
        "seed_ref": seed_ref(int(seed), "material", style_id),
    }
    profile["profile_hash"] = _profile_hash(profile)
    validate_profile(profile)
    return profile


def sample_reference_material(profile: Mapping[str, Any], points_mm: Any,
                              surface_tag: Any, *, depth_mm: Any | None = None) -> dict[str, Any]:
    """Return the pure material sample plus transmission and selected layer names.

    The transmission values are read from the profile's selected layer because the frozen
    ``MaterialSample`` schema predates an explicit transmission channel. A ``depth_mm`` override
    is available only for explicit ``volume`` queries on versioned reference profiles.
    """
    sample = material_at(profile, points_mm, surface_tag, depth_mm=depth_mm)
    layers_by_id = {int(layer["layer_id"]): layer for layer in profile.get("layers", [])}
    selected = [layers_by_id[int(layer_id)] for layer_id in sample.layer_id]
    return {
        "layer_id": np.asarray(sample.layer_id).tolist(),
        "layer_name": [str(layer.get("name", "")) for layer in selected],
        "albedo": np.asarray(sample.albedo).tolist(),
        "roughness": np.asarray(sample.roughness).tolist(),
        "transmission": [float(layer.get("transmission", 0.0)) for layer in selected],
        "ior": np.asarray(sample.ior).tolist(),
        "grain": np.asarray(sample.grain).tolist(),
        "porosity": np.asarray(sample.porosity).tolist(),
        "direction": np.asarray(sample.direction).tolist(),
        "layer_depth_mm": np.asarray(sample.layer_depth_mm).tolist(),
    }


def process_compatibility(material_class: str, process: str) -> dict[str, Any]:
    """Return a concise substrate/process assessment with its evidence boundary.

    ``ceramic_glaze_firing`` means firing a glaze onto a clay ceramic body.  Metal enamelling
    is a different process; this check deliberately does not classify it as ceramic glazing.
    ``surface_paint`` is an appearance-only operation. ``engrave_body`` changes geometry and
    is therefore recorded as a geometric design operation.
    """
    material = str(material_class).strip().lower()
    operation = str(process).strip().lower()
    ceramics = {"earthenware", "stoneware", "porcelain"}
    if operation == "ceramic_glaze_firing":
        if material in ceramics:
            return {"material_class": material, "process": operation,
                    "status": "COMPATIBLE_SUBSTRATE_CLASS",
                    "effect_scope": "surface_finish",
                    "basis": "clay ceramic substrate class; object-specific firing compatibility remains unknown"}
        if material in {"wood", "metal"}:
            return {"material_class": material, "process": operation,
                    "status": "INCOMPATIBLE_FOR_CLAY_BODY_GLAZE",
                    "effect_scope": "not_applied",
                    "basis": "the named process requires a clay ceramic body; metal vitreous enamelling is a separate process"}
    elif operation == "surface_paint":
        if material in ceramics | {"wood", "metal"}:
            return {"material_class": material, "process": operation,
                    "status": "COMPATIBLE_AS_APPEARANCE_OPERATION",
                    "effect_scope": "SHADING_LAYER",
                    "basis": "generic surface appearance operation; no object-specific paint recipe is asserted"}
    elif operation == "underglaze_cobalt":
        if material in ceramics:
            return {"material_class": material, "process": operation,
                    "status": "COMPATIBLE_SUBSTRATE_CLASS",
                    "effect_scope": "SEPARATE_APPEARANCE_LAYER",
                    "basis": "ceramic substrate class supports a separately composed underglaze-cobalt appearance; object-specific pigment formulation and firing behavior remain unknown"}
        if material in {"wood", "metal"}:
            return {"material_class": material, "process": operation,
                    "status": "INCOMPATIBLE_FOR_CERAMIC_UNDERGLAZE",
                    "effect_scope": "not_applied",
                    "basis": "the named underglaze process is modeled for a clay ceramic substrate; metal enamelling and painting are separate operations"}
    elif operation == "engrave_body":
        if material in ceramics | {"wood", "metal"}:
            return {"material_class": material, "process": operation,
                    "status": "GEOMETRY_CHANGING_DESIGN_OPERATION",
                    "effect_scope": "GEOMETRIC_LAYER",
                    "basis": "engraving removes or displaces substrate; material-specific tool/process limits are unknown"}
    return {"material_class": material, "process": operation, "status": "UNKNOWN",
            "effect_scope": "UNKNOWN", "basis": "no compatibility rule is defined for this pair"}


def _validate_controls(style_id: str, controls: Mapping[str, Any]) -> None:
    for key, value in controls.items():
        if key.endswith("_linear_rgb"):
            if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
                    or len(value) != 3):
                _invalid(style_id, key, value, "must be a 3-component linear RGB value")
            numbers = [_numeric_control(style_id, key, component) for component in value]
            if any(not math.isfinite(component) or not 0.0 <= component <= 1.0
                   for component in numbers):
                _invalid(style_id, key, value, "components must be finite and in [0,1]")
        elif key in ("body_roughness", "coating_roughness", "grain_amount", "pore_amount",
                     "coating_transmission"):
            number = _numeric_control(style_id, key, value)
            low = 0.02 if key.endswith("roughness") else 0.0
            if not math.isfinite(number) or not low <= number <= 1.0:
                _invalid(style_id, key, value, f"must be finite and in [{low},1]")
        elif key in ("body_ior", "coating_ior"):
            number = _numeric_control(style_id, key, value)
            if not math.isfinite(number) or not 1.0 <= number <= 3.0:
                _invalid(style_id, key, value, "must be finite and in [1,3]")
        elif key in ("grain_scale_mm", "pore_scale_mm", "coating_band_mm"):
            number = _numeric_control(style_id, key, value)
            if not math.isfinite(number) or number <= 0.0:
                _invalid(style_id, key, value, "must be finite and positive")
        elif key == "aggregate_radius_mm":
            number = _numeric_control(style_id, key, value)
            if not math.isfinite(number) or number < 0.0:
                _invalid(style_id, key, value, "must be finite and non-negative")
        elif key == "aggregate_density_per_mm3":
            number = _numeric_control(style_id, key, value)
            if not math.isfinite(number) or number < 0.0:
                _invalid(style_id, key, value, "must be finite and non-negative")


def _invalid(style_id: str, key: str, value: Any, message: str) -> None:
    raise SynLabError(ErrorCode.SCHEMA_INVALID,
                      f"{style_id}: {key} {message}", stage=f"{STAGE}.controls",
                      measurements={"control": key, "value": value})


def _numeric_control(style_id: str, key: str, value: Any) -> float:
    if isinstance(value, bool):
        _invalid(style_id, key, value, "must be numeric, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _invalid(style_id, key, value, "must be numeric")
    if not math.isfinite(number):
        _invalid(style_id, key, value, "must be finite")
    return number


def _control_unit(key: str) -> str:
    if key.endswith("_linear_rgb"):
        return "linear_rgb_0_1"
    if key.endswith("_mm"):
        return "mm"
    if key.endswith("_per_mm3"):
        return "mm^-3"
    if key.endswith("_ior"):
        return "1"
    return "1"


def _profile_hash(profile: Mapping[str, Any]) -> str:
    return hash_json({key: value for key, value in profile.items() if key != "profile_hash"})


__all__ = ["SCHEMA_REFERENCE_MATERIAL", "list_reference_materials", "reference_material",
           "sample_reference_material", "process_compatibility"]
