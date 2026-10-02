"""Public façade of the material / layer model (plan 8, frozen contract in
``docs/a12/interfaces.md`` section 2).

Exported functions
------------------
``build_material_profile(material_id, params, rng) -> dict``
    Freeze one material: appearance, geometric statistics, procedural cut statistics and the
    layer stack.  Uncalibrated mechanical parameters are recorded as ``UNKNOWN`` with a reason,
    never as a number.
``material_at(profile, points_mm, surface_tag) -> MaterialSample``
    **Pure function of the mother coordinates.**  Two fragments that were adjacent before the
    break query the same field and therefore agree along their shared boundary: no randomness
    is drawn at query time, and nothing depends on which fragment is asking.
``layer_combo(combo_id, params, rng) -> list[LayerSpec]``
    One of the four frozen layer stacks (L01..L04), as ordered ``LayerSpec`` entries.  The
    per-layer material bodies (real thickness, watertight solid) come from
    :mod:`synlab.materials.layers`; ``SHADING_LAYER`` entries only change appearance.
``commit_material(store, profile, *, lineage_id, split, ancestry=()) -> AssetRecord``
``load_material(store, asset_id) -> dict``
    Round-trip through the content-addressed store with ``role="material_profile"`` and
    ``meta["material_id"]``.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..registry import REGISTRY, RegistryEntry
from ..roles import (FRAME_WORLD, ROLE_MATERIAL_PROFILE, SCHEMA_MATERIAL, UNIT_MM)
from ..schemas.runtime import LayerSpec, MaterialSample
from ..storage.store import AssetStore, AssetRecord, QA_PASS
from . import catalogue  # noqa: F401  (import registers M01..M12 and L01..L04)
from .fields import field_stack

STAGE = "materials.api"

#: Layer modes (plan 8.2): appearance only, or a real geometric body.
MODE_SHADING = "SHADING_LAYER"
MODE_GEOMETRIC = "GEOMETRIC_LAYER"

#: Mechanical quantities that this programme cannot calibrate; they are reported as UNKNOWN.
UNCALIBRATED_MECHANICS: tuple[str, ...] = (
    "youngs_modulus_gpa", "poisson_ratio", "fracture_toughness_mpa_sqrt_m",
    "flexural_strength_mpa", "density_kg_m3",
)
UNKNOWN_REASON = ("no calibrated test campaign exists in this programme; noise amplitude is "
                  "not a mechanical property (plan 8.1)")

TAG_INNER = "inner_wall"
TAG_INTERFACE = "interface"
TAG_ATTACHMENT = "attachment"


# ---------------------------------------------------------------------------------------
# registry helpers
# ---------------------------------------------------------------------------------------
def material_entry(material_id: str) -> RegistryEntry:
    if not REGISTRY.has("material", material_id):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unregistered material id {material_id!r}",
                          stage=STAGE, measurements={"registered": REGISTRY.ids("material")})
    return REGISTRY.get("material", material_id)


def combo_entry(combo_id: str) -> RegistryEntry:
    if not REGISTRY.has("layer_combo", combo_id):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unregistered layer combo {combo_id!r}",
                          stage=STAGE, measurements={"registered": REGISTRY.ids("layer_combo")})
    return REGISTRY.get("layer_combo", combo_id)


def material_ids() -> list[str]:
    return REGISTRY.ids("material")


def combo_ids() -> list[str]:
    return REGISTRY.ids("layer_combo")


def canonical_material_params(material_id: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
    entry = material_entry(material_id)
    model = entry.param_model
    raw = dict(params or {})
    if model is None:  # pragma: no cover - every registered material ships a model
        return raw
    allowed = set(model.model_fields)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{material_id}: unknown material parameters {unknown}",
                          stage=f"{STAGE}.params",
                          measurements={"allowed": sorted(allowed)})
    try:
        return _jsonable(model.model_validate(raw).model_dump(mode="python"))
    except Exception as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{material_id}: invalid parameters: {exc}",
                          stage=f"{STAGE}.params") from exc


def _jsonable(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        return {str(k): _jsonable(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_jsonable(v) for v in payload]
    if isinstance(payload, (np.floating, np.integer, np.bool_)):
        return payload.item()
    return payload


# ---------------------------------------------------------------------------------------
# profile construction
# ---------------------------------------------------------------------------------------
def build_material_profile(material_id: str, params: dict, rng) -> dict:
    """Freeze one material profile (plan 8.1).  Deterministic given ``rng``."""
    entry = material_entry(material_id)
    clean = canonical_material_params(material_id, params)
    if rng is not None and not isinstance(rng, np.random.Generator):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "rng must be a numpy.random.Generator",
                          stage=f"{STAGE}.build_material_profile")
    builder = REGISTRY.resolve_builder("material", material_id)
    draft = builder(clean, rng)
    if not isinstance(draft, Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{material_id}: material builder must return a mapping",
                          stage=f"{STAGE}.build_material_profile")
    profile = _jsonable(dict(draft))
    profile["material_id"] = material_id
    profile["material_name"] = entry.name
    profile["schema"] = SCHEMA_MATERIAL
    profile["units"] = {"length": "mm", "albedo": "linear_rgb_0_1", "ior": "1"}
    profile["material_params"] = clean
    profile["field_kernel"] = "value_noise+aggregate+fiber"
    profile["provenance"] = {
        "source_kind": "SYNTHETIC",
        "note": "procedural statistics; not a measured distribution of any real collection",
    }
    mechanics = dict(profile.get("mechanics") or {})
    for key in UNCALIBRATED_MECHANICS:
        mechanics.setdefault(key, None)
    mechanics["status"] = "UNKNOWN"
    mechanics["reason"] = UNKNOWN_REASON
    profile["mechanics"] = mechanics
    layers = list(profile.get("layers") or [])
    profile["layers"] = layers
    profile["layer_ids"] = [int(layer["layer_id"]) for layer in layers]
    profile["outer_layer_id"] = int(layers[0]["layer_id"]) if layers else 0
    profile["appearance_ids"] = [int(layer["layer_id"]) for layer in layers
                                 if layer.get("kind") == "appearance"]
    profile["profile_hash"] = _profile_hash(profile)
    validate_profile(profile)
    return profile


def _profile_hash(profile: Mapping[str, Any]) -> str:
    from ..canonical import hash_json

    payload = {k: v for k, v in profile.items() if k != "profile_hash"}
    return hash_json(_jsonable(payload))


def validate_profile(profile: Mapping[str, Any]) -> None:
    """Structural validation: ids, layers, statistics and the reference outer surface."""
    for key in ("material_id", "appearance", "stats", "mechanics", "layers", "outer_reference"):
        if key not in profile:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"material profile is missing {key!r}", stage=STAGE,
                              measurements={"present": sorted(profile)})
    if not profile["layers"]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "material profile has no layers", stage=STAGE)
    ids = [int(layer["layer_id"]) for layer in profile["layers"]]
    # the frozen contract is "outermost layer wins": layers are stored outermost first, so the
    # ids descend and the outermost surface carries the highest non-zero id
    if ids != sorted(set(ids), reverse=True) or min(ids) < 1:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"layer ids must be unique, positive and descending (outermost "
                          f"first), got {ids}", stage=STAGE)
    for layer in profile["layers"]:
        if float(layer.get("thickness_mm", 0.0)) < 0.0:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"layer {layer.get('layer_id')} has a negative thickness",
                              stage=STAGE)
        if layer.get("kind") not in ("appearance", "geometric", "base"):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"layer {layer.get('layer_id')} has kind {layer.get('kind')!r}",
                              stage=STAGE)
        albedo = layer.get("albedo")
        if albedo is None or len(albedo) != 3 or any(float(c) < 0.0 or float(c) > 1.0
                                                     for c in albedo):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"layer {layer.get('layer_id')} albedo must be linear RGB in [0,1]",
                              stage=STAGE, measurements={"albedo": albedo})
    if profile["mechanics"].get("status") != "UNKNOWN":
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "uncalibrated mechanics must be recorded as UNKNOWN (plan 8.1)",
                          stage=STAGE)
    reference = profile["outer_reference"]
    for key in ("r_outer_mm", "r_inner_mm", "z_floor_mm", "z_rim_mm"):
        if key not in reference:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"material profile reference is missing {key!r}", stage=STAGE)


def default_material_params(material_id: str) -> dict[str, Any]:
    return canonical_material_params(material_id, {})


# ---------------------------------------------------------------------------------------
# the pure field query
# ---------------------------------------------------------------------------------------
def material_at(profile: Mapping[str, Any], points_mm: Any,
                surface_tag: Any) -> MaterialSample:
    """Sample the frozen material field at mother millimetres (plan 8.1).

    This is a pure function: it draws no randomness, keeps no state, and depends only on the
    profile and the query coordinates.  Grain, pores and colour therefore continue across a
    fracture boundary, because both fragments evaluate the same closed-form field.
    """
    if not isinstance(profile, Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "material_at needs a material profile dict",
                          stage=f"{STAGE}.material_at")
    pts = np.atleast_2d(np.asarray(points_mm, dtype=np.float64))
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"points_mm must be (N,3), got {np.shape(points_mm)}",
                          stage=f"{STAGE}.material_at")
    if not np.all(np.isfinite(pts)):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "points_mm contains non-finite values",
                          stage=f"{STAGE}.material_at")
    n = pts.shape[0]
    tags = _normalise_tags(surface_tag, n)
    stats = dict(profile.get("stats") or {})
    appearance = dict(profile.get("appearance") or {})
    layers = sorted((dict(layer) for layer in (profile.get("layers") or [])),
                    key=lambda layer: int(layer["layer_id"]), reverse=True)
    if not layers:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "material profile has no layers",
                          stage=f"{STAGE}.material_at")
    reference = dict(profile.get("outer_reference") or {})
    seed_salt = int(profile.get("field_salt", 0))

    fields = field_stack(
        pts, seed_salt=seed_salt,
        grain_scale_mm=float(stats.get("grain_scale_mm", 2.0)),
        pore_scale_mm=float(stats.get("pore_scale_mm", 3.0)),
        aggregate_radius_mm=float(stats.get("aggregate_radius_mm", 0.0)),
        aggregate_density=float(stats.get("aggregate_density_per_mm3", 0.0)),
        fiber_direction=stats.get("fiber_direction"),
        fiber_period_mm=float(stats.get("fiber_period_mm", 0.0)),
    )
    grain, porosity, spots = fields["grain"], fields["porosity"], fields["spots"]
    direction = fields["direction"]

    depth = _layer_depths(pts, tags, reference, layers)
    layer_ids, active = _assign_layers(depth, tags, layers)
    layer_index = np.zeros(n, dtype=np.int64)
    order = {int(layer["layer_id"]): i for i, layer in enumerate(layers)}
    for k in range(n):
        layer_index[k] = order.get(int(layer_ids[k]), len(layers) - 1)

    albedos = np.asarray([layer["albedo"] for layer in layers], dtype=np.float64)
    roughness = np.asarray([float(layer["roughness"]) for layer in layers], dtype=np.float64)
    iors = np.asarray([float(layer.get("ior", 1.5)) for layer in layers], dtype=np.float64)

    base = albedos[layer_index]
    grain_amount = float(appearance.get("grain_amount", 0.18))
    pore_amount = float(appearance.get("pore_amount", 0.25))
    aggregate_amount = float(appearance.get("aggregate_amount", 0.0))
    fiber_amount = float(appearance.get("fiber_amount", 0.0))
    hue_shift = np.asarray(appearance.get("hue_shift", [0.0, 0.0, 0.0]), dtype=np.float64)
    variation = ((grain - 0.5)[:, None] * grain_amount
                 + (spots - 0.5)[:, None] * aggregate_amount
                 + (porosity - 0.5)[:, None] * pore_amount
                 + (np.abs(direction[:, 2]) - 0.5)[:, None] * fiber_amount * 0.3)
    albedo = np.clip(base * (1.0 + variation) + hue_shift[None, :] * (variation * 0.25), 0.0, 1.0)
    # exposed (uncoated) surfaces are the *base* material: the coating albedo is not reused
    albedo[~active] = np.clip(
        np.asarray(layers[-1]["albedo"], dtype=np.float64)[None, :]
        * (1.0 + variation[~active]), 0.0, 1.0)
    rough = np.where(active, roughness[layer_index], roughness[-1])
    rough = np.clip(rough + (grain - 0.5) * float(appearance.get("roughness_variation", 0.12))
                    + porosity * float(appearance.get("pore_roughness", 0.20)), 0.02, 1.0)
    ior_out = np.where(active, iors[layer_index], iors[-1])
    if not np.all(active):
        # inner walls and new interfaces expose fresh body material with a slightly higher
        # micro-roughness (a broken surface is not a polished one)
        rough[~active] = np.clip(rough[~active] + 0.06, 0.02, 1.0)
    grain_out = np.clip(grain * (1.0 - 0.6 * porosity) + spots * 0.4, 0.0, 1.0)
    grain_out[~active] = np.clip(grain_out[~active] + 0.15, 0.0, 1.0)
    return MaterialSample(
        layer_id=np.asarray(layer_ids, dtype=np.int32),
        albedo=np.asarray(albedo, dtype=np.float32),
        roughness=np.asarray(rough, dtype=np.float32),
        direction=np.asarray(direction, dtype=np.float32),
        grain=np.asarray(grain_out, dtype=np.float32),
        porosity=np.asarray(porosity, dtype=np.float32),
        ior=np.asarray(ior_out, dtype=np.float32),
        layer_depth_mm=np.asarray(depth, dtype=np.float32),
    )


def _normalise_tags(surface_tag: Any, n: int) -> np.ndarray:
    if isinstance(surface_tag, str):
        return np.array([surface_tag] * n, dtype=object)
    arr = np.asarray(surface_tag)
    if arr.ndim == 0:
        return np.array([str(arr)] * n, dtype=object)
    arr = arr.astype(object).ravel()
    if arr.shape[0] != n:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"surface_tag has {arr.shape[0]} entries for {n} points",
                          stage=f"{STAGE}.material_at")
    return arr


def _layer_depths(points: np.ndarray, tags: np.ndarray, reference: Mapping[str, Any],
                  layers: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Depth below the outermost surface, in millimetres, for every query point."""
    depth = np.zeros(points.shape[0], dtype=np.float64)
    coated = _coatable_mask(tags)
    if not np.any(coated):
        return depth
    mode = str(reference.get("mode", "revolve"))
    if mode == "revolve":
        radius = np.hypot(points[:, 0], points[:, 1])
        depth = np.maximum(0.0, float(reference.get("r_outer_mm", 0.0)) - radius)
    elif mode == "slab":
        axis = int(reference.get("normal_axis", 2))
        depth = np.maximum(0.0, float(reference.get("face_position_mm", 0.0)) - points[:, axis])
    else:
        centre = np.asarray(reference.get("centre_mm", [0.0, 0.0, 0.0]), dtype=np.float64)
        depth = np.maximum(0.0, float(reference.get("outer_radius_mm", 0.0))
                           - np.linalg.norm(points - centre[None, :], axis=1))
    return depth


def _coatable_mask(tags: np.ndarray) -> np.ndarray:
    """Coating exists on outer surfaces only (plan 8.2: a new section exposes the body)."""
    lowered = np.array([str(t) for t in tags], dtype=object)
    mask = np.ones(len(lowered), dtype=bool)
    for kind in (TAG_INNER, TAG_INTERFACE):
        mask &= lowered != kind
    return mask


def _assign_layers(depth: np.ndarray, tags: np.ndarray,
                   layers: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """Outermost layer wins; ``layers`` is ordered outermost first.

    A point that is not on a coatable surface (inner wall, new fracture interface, the
    attachment) always reports the innermost entry, which is the body material: the plan
    requires a new section to expose the body and forbids reusing the decoration on it.
    """
    ids = np.asarray([int(layer["layer_id"]) for layer in layers], dtype=np.int32)
    active = _coatable_mask(tags)
    out = np.full(depth.shape[0], int(ids[-1]), dtype=np.int32)
    remaining = np.ones(depth.shape[0], dtype=bool)
    cursor = np.zeros(depth.shape[0], dtype=np.float64)
    for index, layer in enumerate(layers[:-1]):
        thickness = float(layer.get("thickness_mm", 0.0))
        if thickness <= 0:
            continue
        inside = remaining & (depth < cursor + thickness)
        out[inside] = int(ids[index])
        remaining &= ~inside
        cursor = np.where(remaining, cursor + thickness, cursor)
    out[~active] = int(ids[-1])
    return out, active


# ---------------------------------------------------------------------------------------
# layer stacks (plan 8.2)
# ---------------------------------------------------------------------------------------
def layer_combo(combo_id: str, params: dict | None, rng) -> list[LayerSpec]:
    """Return the ordered ``LayerSpec`` stack of one of the four frozen layer combinations."""
    entry = combo_entry(combo_id)
    clean = dict(params or {})
    if rng is not None and not isinstance(rng, np.random.Generator):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "rng must be a numpy.random.Generator",
                          stage=f"{STAGE}.layer_combo")
    model = entry.param_model
    if model is not None:
        allowed = set(model.model_fields)
        unknown = sorted(set(clean) - allowed)
        if unknown:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{combo_id}: unknown layer parameters {unknown}",
                              stage=f"{STAGE}.layer_combo",
                              measurements={"allowed": sorted(allowed)})
        try:
            clean = _jsonable(model.model_validate(clean).model_dump(mode="python"))
        except Exception as exc:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{combo_id}: invalid parameters: {exc}",
                              stage=f"{STAGE}.layer_combo") from exc
    builder = REGISTRY.resolve_builder("layer_combo", combo_id)
    specs = builder(clean, rng)
    if not specs:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{combo_id}: layer stack is empty",
                          stage=f"{STAGE}.layer_combo")
    ids = [int(spec.layer_id) for spec in specs]
    if ids != sorted(set(ids)) or min(ids) < 1:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{combo_id}: layer ids must be unique, positive and ascending "
                          f"(body first, outermost last), got {ids}",
                          stage=f"{STAGE}.layer_combo")
    modes = {spec.mode for spec in specs}
    unknown_modes = modes - {MODE_SHADING, MODE_GEOMETRIC}
    if unknown_modes:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{combo_id}: unknown layer modes {sorted(unknown_modes)}",
                          stage=f"{STAGE}.layer_combo")
    if specs[0].mode != MODE_SHADING:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{combo_id}: the body layer must be SHADING_LAYER "
                          "(plan 8.2: a shading layer never claims a geometric body)",
                          stage=f"{STAGE}.layer_combo",
                          measurements={"first_mode": specs[0].mode})
    return specs


def combo_definition(combo_id: str) -> dict[str, Any]:
    """Full definition of a layer stack (materials, colours, thickness policy, QA gates)."""
    entry = combo_entry(combo_id)
    definition = (entry.applicable or {}).get("definition")
    if not isinstance(definition, Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{combo_id}: registry entry has no layer definition",
                          stage=f"{STAGE}.combo_definition")
    return copy.deepcopy(dict(definition))


def combo_geometric_layers(combo_id: str, params: dict | None = None,
                           rng: Any = None) -> list[dict[str, Any]]:
    """The GEOMETRIC_LAYER members of a combo, with their material statistics and QA gates."""
    definition = combo_definition(combo_id)
    specs = {int(spec.layer_id): spec for spec in layer_combo(combo_id, params or {}, rng)}
    out: list[dict[str, Any]] = []
    for entry in definition.get("layers", []):
        layer_id = int(entry["layer_id"])
        spec = specs.get(layer_id)
        if spec is None or spec.mode != MODE_GEOMETRIC:
            continue
        out.append({
            "layer_id": layer_id,
            "name": spec.name,
            "material_id": spec.material_id,
            "thickness_mm": float(spec.thickness_mm),
            "min_thickness_mm": float(entry.get("min_thickness_mm", 0.15)),
            "albedo": tuple(float(c) for c in entry.get("albedo", spec.albedo)),
            "roughness": float(entry.get("roughness", spec.roughness)),
            "ior": float(entry.get("ior", spec.ior)),
            "transmission": float(entry.get("transmission", spec.transmission)),
            "mode": spec.mode,
            "stats": _jsonable(dict(entry.get("stats") or {})),
        })
    return out


# ---------------------------------------------------------------------------------------
# store round-trip
# ---------------------------------------------------------------------------------------
def commit_material(store: AssetStore, profile: Mapping[str, Any], *, lineage_id: str,
                    split: str, ancestry: Iterable[str] = ()) -> AssetRecord:
    """Persist one material profile as ``role="material_profile"``."""
    if not isinstance(store, AssetStore):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "commit_material needs an AssetStore",
                          stage=f"{STAGE}.commit_material")
    if not isinstance(profile, Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "commit_material needs a profile dict",
                          stage=f"{STAGE}.commit_material")
    validate_profile(profile)
    material_id = str(profile["material_id"])
    material_entry(material_id)
    payload = {"profile": np.frombuffer(
        json.dumps(_jsonable(dict(profile)), ensure_ascii=False, sort_keys=True).encode("utf-8"),
        dtype=np.uint8)}
    meta = {
        "material_id": material_id,
        "material_name": profile.get("material_name", ""),
        "schema": SCHEMA_MATERIAL,
        "profile_hash": profile.get("profile_hash", ""),
        "layer_ids": list(profile.get("layer_ids") or []),
        "field_salt": int(profile.get("field_salt", 0)),
        "stats": _jsonable(dict(profile.get("stats") or {})),
        "mechanics_status": str((profile.get("mechanics") or {}).get("status", "UNKNOWN")),
        "provenance": _jsonable(dict(profile.get("provenance") or {})),
    }
    return store.commit_asset(
        role=ROLE_MATERIAL_PROFILE, schema=SCHEMA_MATERIAL, unit=UNIT_MM, frame=FRAME_WORLD,
        payload=payload, meta=meta,
        qa={"ok": True, "checks": {"structure": True, "layer_ids": meta["layer_ids"],
                                   "mechanics": meta["mechanics_status"]},
            "metrics": {"layers": len(meta["layer_ids"]),
                        "profile_hash": meta["profile_hash"]}},
        qa_status=QA_PASS, ancestry=list(ancestry), lineage_id=lineage_id, split=split,
    )


def load_material(store: AssetStore, asset_id: str) -> dict:
    """Read a material profile back (byte-identical JSON payload)."""
    if not isinstance(store, AssetStore):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "load_material needs an AssetStore",
                          stage=f"{STAGE}.load_material")
    record = store.get_asset(asset_id)
    if record.role != ROLE_MATERIAL_PROFILE:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} has role {record.role!r}, expected "
                          f"{ROLE_MATERIAL_PROFILE!r}", stage=f"{STAGE}.load_material")
    arrays = store.load_arrays(asset_id)
    if "profile" not in arrays:
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"asset {asset_id} has no stored profile payload",
                          stage=f"{STAGE}.load_material")
    try:
        profile = json.loads(np.asarray(arrays["profile"], dtype=np.uint8).tobytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"asset {asset_id} profile payload is not valid JSON: {exc}",
                          stage=f"{STAGE}.load_material") from exc
    expected = record.meta.get("profile_hash")
    if expected and str(profile.get("profile_hash")) != str(expected):
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"asset {asset_id} profile hash mismatch",
                          stage=f"{STAGE}.load_material",
                          measurements={"stored": expected,
                                        "payload": profile.get("profile_hash")})
    profile["loaded_from_asset"] = asset_id
    return profile


__all__ = [
    "build_material_profile", "material_at", "layer_combo", "commit_material", "load_material",
    "combo_definition", "combo_geometric_layers", "validate_profile", "material_ids",
    "combo_ids", "material_entry", "combo_entry", "default_material_params",
    "canonical_material_params", "MODE_SHADING", "MODE_GEOMETRIC", "UNCALIBRATED_MECHANICS",
]
