"""Research-facing design spaces over the registered A12 mother generators.

This module reads the existing vessel registry and delegates all construction to
``mothers.api.create_mother``.  It does not define replacement generators or claim that
the registered parameter ranges match measured everyday or archaeological objects.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..seeds import make_rng
from . import api as mothers_api


# These are parameter recipes for exercising the design space. Their names describe
# numeric changes only; none is an archaeological or manufacturing attribution.
_STYLE_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "V01": {
        "shallow_wide": {"depth_ratio": 0.30, "rim_flare": 0.20},
        "deep_bowl": {"depth_ratio": 0.62, "rim_flare": 0.04},
    },
    "V04": {
        "tall_cup": {"height_mm": 145.0, "belly_ratio": 1.12,
                     "handle_span_ratio": 0.95},
        "short_cup": {"height_mm": 70.0, "belly_ratio": 0.88,
                       "handle_span_ratio": 0.68},
    },
    "V06": {
        "narrow_mouth": {"mouth_ratio": 0.34, "shoulder_position": 0.70},
        "wide_mouth": {"mouth_ratio": 0.78, "shoulder_position": 0.52},
    },
    "V09": {
        "long_spout": {"spout_length_mm": 120.0, "spout_angle_deg": 35.0},
        "short_spout": {"spout_length_mm": 55.0, "spout_angle_deg": 18.0},
    },
}


@dataclass(frozen=True)
class DesignSpaceResult:
    """One deterministic build plus the user request and canonical values it used."""

    mother: Any
    vessel_id: str
    material_id: str
    seed: int
    style_preset: str | None
    requested_values: dict[str, Any]
    resolved_canonical_values: dict[str, Any]
    realized_values: dict[str, Any]
    parameter_adjustments: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly build record without serializing the mesh."""
        applicable = mothers_api.vessel_entry(self.vessel_id).applicable or {}
        return {
            "schema": "a12_design_space.v1",
            "vessel_id": self.vessel_id,
            "material_id": self.material_id,
            "seed": self.seed,
            "style_preset": self.style_preset,
            "requested_values": copy.deepcopy(self.requested_values),
            "resolved_canonical_values": copy.deepcopy(self.resolved_canonical_values),
            "realized_values": copy.deepcopy(self.realized_values),
            "parameter_adjustments": copy.deepcopy(self.parameter_adjustments),
            "geometry_hash": mothers_api.geometry_hash(self.mother.mesh),
            "bounds_mm": np.asarray(self.mother.mesh.bounds, dtype=float).tolist(),
            "volume_mm3": float(self.mother.volume_mm3),
            "evidence_status": {
                "source_class": "SYNTHETIC_CONTROL",
                "validation_status": "PARAMETRIC_CANDIDATE",
                "real_world_validation": "NOT_ESTABLISHED",
                "archaeological_attribution": False,
                "source_dimensions": None,
                "visual_style": None,
                "generator_assumption": applicable.get("family"),
            },
        }


def parameter_space(vessel_id: str) -> dict[str, Any]:
    """Describe one registered model's fields, using its schema and registry metadata.

    ``common_parameters`` are fields inherited from this model's nearest shared parameter
    base. ``type_specific_parameters`` are fields declared by this vessel model. A
    separately reported occurrence count shows same-named fields elsewhere in the catalogue;
    shared names do not make unrelated model fields interchangeable.
    """
    entry = mothers_api.vessel_entry(vessel_id)
    model = entry.param_model
    if model is None:  # pragma: no cover - all 24 registered models have schemas
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{vessel_id}: registered vessel has no parameter model",
                          stage="mothers.design_space.parameter_space")

    field_counts = _field_occurrence_counts()
    inherited_fields = _inherited_parameter_fields(model)
    schema = model.model_json_schema()
    schema_fields = schema.get("properties", {})
    defaults = mothers_api.default_params(vessel_id)
    declared_shape = set(mothers_api.shape_parameters(vessel_id))
    parameters: list[dict[str, Any]] = []
    for name, field in model.model_fields.items():
        shape = schema_fields.get(name, {})
        count = field_counts.get(name, 1)
        parameters.append({
            "name": name,
            "type": _field_type(field.annotation),
            "unit": _field_unit(name, field.annotation, field.description),
            "description": field.description,
            "bounds": {
                "minimum": shape.get("minimum"),
                "maximum": shape.get("maximum"),
            },
            "default": copy.deepcopy(defaults[name]),
            "default_source": ("registered_model_default" if not field.is_required()
                               else "api_schema_midpoint_or_existing_fallback"),
            "required_in_model": bool(field.is_required()),
            "scope": "common" if name in inherited_fields else "type_specific",
            "scope_basis": "nearest_shared_parameter_base",
            "registered_model_count": count,
            "shape_effect": {
                "registry_declared_shape_driver": name in declared_shape,
                "behavioral_probe": "not_measured",
            },
        })

    applicable = copy.deepcopy(entry.applicable or {})
    source_class = "SYNTHETIC_CONTROL"
    validation_status = "PARAMETRIC_CANDIDATE"
    return {
        "vessel_id": entry.id,
        "name": entry.name,
        "registry_version": entry.version,
        "registry_status": entry.status,
        "family": applicable.get("family"),
        "common_parameters": [p["name"] for p in parameters if p["scope"] == "common"],
        "type_specific_parameters": [p["name"] for p in parameters
                                     if p["scope"] == "type_specific"],
        "parameters": parameters,
        "style_presets": style_presets(vessel_id),
        "evidence_status": {
            "source_class": source_class,
            "validation_status": validation_status,
            "real_world_validation": "NOT_ESTABLISHED",
            "archaeological_attribution": False,
            "source_dimensions": None,
            "visual_style": None,
            "generator_assumption": applicable.get("family"),
            "parameter_bounds_meaning": "registered generator constraints; not source-measured dimensions",
        },
    }


def style_presets(vessel_id: str) -> dict[str, dict[str, Any]]:
    """Return this module's named parameter recipes for a vessel, if any."""
    mothers_api.vessel_entry(vessel_id)  # validate the ID even when it has no recipes
    return copy.deepcopy(_STYLE_PRESETS.get(vessel_id, {}))


def build_designed_mother(
    vessel_id: str,
    material_id: str = "M01",
    *,
    base_params: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    style_preset: str | None = None,
    seed: int = 0,
    mother_id: str = "",
) -> DesignSpaceResult:
    """Build from defaults, an optional recipe, a base mapping and explicit overrides.

    Precedence is: registered defaults < named recipe < ``base_params`` < ``overrides``.
    Both user mappings are validated as mappings of fields declared by this vessel. Any
    generator repair is returned in ``parameter_adjustments`` and embedded in mother
    metadata so a caller can see the requested, canonical and realized values separately.
    """
    entry = mothers_api.vessel_entry(vessel_id)
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "seed must be an integer for deterministic replay",
                          stage="mothers.design_space.build",
                          measurements={"seed": repr(seed)})
    if not isinstance(material_id, str) or not material_id:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "material_id must be a non-empty string",
                          stage="mothers.design_space.build")

    base = _mapping_or_empty("base_params", base_params)
    explicit = _mapping_or_empty("overrides", overrides)
    declared = set(mothers_api.declared_fields(vessel_id))
    _reject_unknown_fields(vessel_id, "base_params", base, declared)
    _reject_unknown_fields(vessel_id, "overrides", explicit, declared)

    recipe: dict[str, Any] = {}
    if style_preset is not None:
        if not isinstance(style_preset, str):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "style_preset must be a recipe name string",
                              stage="mothers.design_space.build",
                              measurements={"style_preset": repr(style_preset)})
        available = style_presets(vessel_id)
        if style_preset not in available:
            raise SynLabError(
                ErrorCode.MOTHER_INVALID,
                f"{vessel_id}: unknown style preset {style_preset!r}; "
                f"available recipes: {sorted(available)}",
                stage="mothers.design_space.build",
                measurements={"vessel_id": vessel_id, "style_preset": style_preset,
                              "available": sorted(available)},
            )
        recipe = available[style_preset]
        _reject_unknown_fields(vessel_id, f"style_preset:{style_preset}", recipe, declared)

    requested = {
        "base_params": copy.deepcopy(base),
        "style_preset": style_preset,
        "style_recipe": copy.deepcopy(recipe),
        "explicit_overrides": copy.deepcopy(explicit),
    }
    combined: dict[str, Any] = mothers_api.default_params(vessel_id)
    combined.update(recipe)
    combined.update(base)
    combined.update(explicit)
    try:
        canonical = mothers_api.canonical_params(vessel_id, combined)
    except SynLabError as exc:
        _raise_with_design_context(exc, vessel_id, combined)

    normalizations = []
    for name, requested_value in combined.items():
        resolved_value = canonical[name]
        if not _same_typed_value(requested_value, resolved_value):
            normalizations.append({
                "parameter": name,
                "requested_value": copy.deepcopy(requested_value),
                "resolved_value": copy.deepcopy(resolved_value),
                "stage": "canonicalization",
                "kind": "coercion_or_clamp",
            })

    try:
        mother = mothers_api.create_mother(
            vessel_id, material_id, canonical,
            make_rng(int(seed), "a12_design_space", vessel_id, material_id),
            mother_id=mother_id or f"{vessel_id}-{material_id}-design-{int(seed)}",
        )
    except SynLabError as exc:
        _raise_with_design_context(exc, vessel_id, combined)

    realized = copy.deepcopy(mother.params)
    for name, value in canonical.items():
        if name in realized and not _same_typed_value(value, realized[name]):
            normalizations.append({
                "parameter": name,
                "requested_value": copy.deepcopy(value),
                "resolved_value": copy.deepcopy(realized[name]),
                "stage": "create_mother_repair",
                "kind": "generator_repair",
            })

    design_record = {
        "schema": "a12_design_space.v1",
        "source_class": "SYNTHETIC_CONTROL",
        "validation_status": "PARAMETRIC_CANDIDATE",
        "real_world_validation": "NOT_ESTABLISHED",
        "archaeological_attribution": False,
        "source_dimensions": None,
        "visual_style": None,
        "generator_assumption": (entry.applicable or {}).get("family"),
        "seed": int(seed),
        "style_preset": style_preset,
        "requested_values": copy.deepcopy(requested),
        "resolved_canonical_values": copy.deepcopy(canonical),
        "realized_values": copy.deepcopy(realized),
        "parameter_adjustments": copy.deepcopy(normalizations),
    }
    mother.meta["design_space"] = design_record
    return DesignSpaceResult(
        mother=mother,
        vessel_id=vessel_id,
        material_id=material_id,
        seed=int(seed),
        style_preset=style_preset,
        requested_values=requested,
        resolved_canonical_values=canonical,
        realized_values=realized,
        parameter_adjustments=normalizations,
    )


def probe_parameter_effect(
    vessel_id: str,
    parameter: str,
    value: Any,
    *,
    base_params: Mapping[str, Any] | None = None,
    material_id: str = "M01",
    seed: int = 0,
) -> dict[str, Any]:
    """Compare a one-field request with the same-seed baseline using actual meshes.

    ``base_params`` can enable conditional controls (for example a non-zero hole count).
    This performs two real builds and reports measured mesh hashes, bounds and volume; it is
    intentionally explicit because the registered metadata alone cannot prove an effect.
    """
    space = parameter_space(vessel_id)
    field_names = {item["name"] for item in space["parameters"]}
    if parameter not in field_names:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{vessel_id}: cannot probe undeclared parameter {parameter!r}",
                          stage="mothers.design_space.probe",
                          measurements={"parameter": parameter,
                                        "declared_fields": sorted(field_names)})
    baseline = build_designed_mother(vessel_id, material_id, base_params=base_params,
                                     seed=seed)
    variant = build_designed_mother(vessel_id, material_id, base_params=base_params,
                                    overrides={parameter: value}, seed=seed)
    base_mesh = baseline.mother.mesh
    variant_mesh = variant.mother.mesh
    base_hash = mothers_api.geometry_hash(base_mesh)
    variant_hash = mothers_api.geometry_hash(variant_mesh)
    base_bounds = np.asarray(base_mesh.bounds, dtype=float)
    variant_bounds = np.asarray(variant_mesh.bounds, dtype=float)
    return {
        "vessel_id": vessel_id,
        "parameter": parameter,
        "baseline_value": baseline.realized_values[parameter],
        "requested_value": value,
        "realized_value": variant.realized_values[parameter],
        "registry_declared_shape_driver": next(
            p["shape_effect"]["registry_declared_shape_driver"]
            for p in space["parameters"] if p["name"] == parameter),
        "behavioral_probe": "measured_same_seed_mesh_comparison",
        "changes_mesh": base_hash != variant_hash,
        "baseline_geometry_hash": base_hash,
        "variant_geometry_hash": variant_hash,
        "baseline_bounds_mm": base_bounds.tolist(),
        "variant_bounds_mm": variant_bounds.tolist(),
        "baseline_volume_mm3": float(baseline.mother.volume_mm3),
        "variant_volume_mm3": float(variant.mother.volume_mm3),
        "baseline_face_count": int(len(base_mesh.faces)),
        "variant_face_count": int(len(variant_mesh.faces)),
        "base_parameter_adjustments": baseline.parameter_adjustments,
        "variant_parameter_adjustments": variant.parameter_adjustments,
    }


def _field_occurrence_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for vessel_id in mothers_api.vessel_ids():
        for name in mothers_api.declared_fields(vessel_id):
            counts[name] = counts.get(name, 0) + 1
    return counts


def _inherited_parameter_fields(model: Any) -> set[str]:
    """Find fields owned by the closest non-empty pydantic base model, if present."""
    for base in model.__mro__[1:]:
        fields = getattr(base, "model_fields", None)
        if fields:
            return set(fields)
    return set()


def _field_type(annotation: Any) -> str:
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is str:
        return "string"
    return getattr(annotation, "__name__", str(annotation))


def _field_unit(name: str, annotation: Any, description: str | None) -> str | None:
    if annotation is bool:
        return None
    if name.endswith("_mm"):
        return "mm"
    if name.endswith("_deg"):
        return "degree"
    if annotation is int or name.endswith(("_count", "_lobes", "_rows", "_columns", "_sides")):
        return "count"
    if ("ratio" in name or "factor" in name or "amplitude" in name
            or "eccentricity" in name or "squareness" in name
            or (description and any(token in description.lower()
                                    for token in ("fraction", "ratio", "exponent")))):
        return "dimensionless"
    return "dimensionless" if annotation in (float, int) else None


def _mapping_or_empty(name: str, value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{name} must be a mapping of declared parameter names to values",
                          stage="mothers.design_space.build",
                          measurements={"argument": name, "got": type(value).__name__})
    return dict(value)


def _reject_unknown_fields(vessel_id: str, source: str, values: Mapping[str, Any],
                           declared: set[str]) -> None:
    non_string = [repr(key) for key in values if not isinstance(key, str)]
    if non_string:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"{vessel_id}: {source} parameter names must be strings",
            stage="mothers.design_space.validate",
            measurements={"vessel_id": vessel_id, "source": source,
                          "non_string_fields": non_string},
        )
    unknown = sorted(set(values) - declared)
    if unknown:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"{vessel_id}: {source} contains undeclared parameter(s): {', '.join(unknown)}",
            stage="mothers.design_space.validate",
            measurements={"vessel_id": vessel_id, "source": source,
                          "unknown_fields": unknown, "declared_fields": sorted(declared)},
        )


def _raise_with_design_context(exc: SynLabError, vessel_id: str,
                               requested: Mapping[str, Any]) -> None:
    """Add the complete request and implicated model fields to an existing API error."""
    measurements = copy.deepcopy(exc.measurements)
    implicated = sorted({key for key in measurements if key in requested})
    message = exc.message
    lower = message.lower()
    for name in mothers_api.declared_fields(vessel_id):
        if re.search(rf"(?<![a-zA-Z0-9_]){re.escape(name)}(?![a-zA-Z0-9_])", message):
            implicated.append(name)
    if "neck radius" in lower or "neck cannot hold" in lower:
        implicated.extend(name for name in ("mouth_ratio", "neck_ratio", "wall_mm",
                                             "diameter_mm") if name in requested)
    if "base thickness" in lower or "curvature" in lower:
        implicated.extend(name for name in ("base_mm", "wall_mm", "depth_mm",
                                             "depth_ratio") if name in requested)
    implicated = sorted(set(implicated))
    if implicated:
        message = (f"{vessel_id}: infeasible parameter combination involving "
                   f"{', '.join(implicated)}: {exc.message}")
    measurements.update({
        "vessel_id": vessel_id,
        "requested_values": copy.deepcopy(dict(requested)),
        "parameter_fields": implicated,
        "existing_generator_message": exc.message,
    })
    raise SynLabError(exc.code, message, stage=exc.stage,
                      attempt=exc.attempt, retryable=exc.retryable,
                      seed_ref=exc.seed_ref, config_hash=exc.config_hash,
                      evidence_refs=exc.evidence_refs, measurements=measurements,
                      reproduce_command=exc.reproduce_command) from exc


def _same_typed_value(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, (np.integer, np.floating)):
        return bool(left == right)
    return left == right


__all__ = [
    "DesignSpaceResult", "build_designed_mother", "parameter_space",
    "probe_parameter_effect", "style_presets",
]
