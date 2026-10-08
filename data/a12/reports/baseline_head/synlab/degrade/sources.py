"""Source bundles, output references and payload (de)serialisation for degradation axes.

A degradation axis is a pure function of ``(source, level, basis)``.  Every axis in this
package therefore consumes a :class:`SourceBundle` (a content-hashed payload dictionary)
and returns another one, wrapped into an :class:`OutputRef` by :mod:`synlab.degrade.api`.

Contract highlights (plan 15.7, 30.9):

* level 0 is a *true identity*: the returned bundle keeps the exact source payload
  objects, the content hash is unchanged and, when the source lives in an asset store,
  the original ``asset_id`` is returned instead of re-committing re-serialised bytes;
* arrays and meshes are hashed by content (:func:`synlab.canonical.array_hash`) so an
  "unchanged geometry hash" claim is verifiable rather than asserted;
* payloads that contain callables (e.g. the injected scene renderer for I06/I07) can be
  flattened for storage, and the dropped keys are reported instead of silently lost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from ..canonical import array_hash, hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import FRAME_WORLD, UNIT_MM

# ---------------------------------------------------------------- source kinds
KIND_CLEAN = "CLEAN"
KIND_PHYSICAL = "PHYSICAL"
KIND_IMAGE = "IMAGE"
KIND_OBS = "OBS"
KIND_GEOMETRY = "GEOMETRY"
KIND_MESH = "MESH"
KIND_MODALITY = "MODALITY"
KIND_CONTEXT = "CONTEXT"
KIND_QUALITY = "QUALITY"
KIND_PROFILE = "PROFILE"

SOURCE_KINDS = (KIND_CLEAN, KIND_PHYSICAL, KIND_IMAGE, KIND_OBS, KIND_GEOMETRY, KIND_MESH,
                KIND_MODALITY, KIND_CONTEXT, KIND_QUALITY, KIND_PROFILE)

#: Payload key used to record the declared input encoding of an image payload.
ENCODING_LINEAR = "LINEAR"
ENCODING_GAMMA = "GAMMA_SRGB"

# ---------------------------------------------------------------------------- payload vocabulary
# Frozen key names shared by every axis implementation, the store round-trip and the tests.
#
# IMAGE    : ``frames``   list of dicts: ``view_id`` (str), ``rgb`` (H,W,3) uint8,
#                         ``rgb_linear`` (H,W,3) float32 (pre-response sensor linear),
#                         ``encoding`` (LINEAR|GAMMA_SRGB, required for sensor axes),
#                         ``K`` (3,3) float64, ``T_WC`` (4,4) float64,
#                         ``depth_z`` (H,W) float32 mm (optional), ``valid`` (bool).
#           ``exposure_gain`` (float, photons-per-unit before shot noise, optional),
#           ``renderer`` (callable, I06/I07 only; cannot be stored -> reported when dropped).
# SCENE    : ``scene`` dict (lights/BRDF/occluders); changed only through the injected renderer.
# GEOMETRY : ``points`` (N,3) float64 mm, ``normals`` (N,3) float64, ``point_valid`` (N,) bool,
#           ``point_view`` (N,) int32 -> ``frames``, ``frames`` list of per-view dicts
#           (``view_id``, ``T_WC`` (4,4), ``K`` (3,3), ``depth_z`` (H,W) float32, ``mask`` (H,W) bool),
#           ``mesh`` (trimesh, fused observed surface, optional), ``roi`` (N,) bool,
#           ``priority_order`` (N,) int32 (frozen nested deletion order),
#           ``reference_points`` (N,3) float64 research reference (audit only),
#           ``scale_ratio`` (float), ``K`` (3,3), ``dist`` (k,) float64,
#           ``clean_geometry_hash`` (str, optional provenance guard).
# OBS      : ``modalities`` dict[str, {"present": bool, "data": ndarray}],
#           ``observed_est`` {"kind": "regression"|"probability", "values": (N,) or (N,C),
#                             "labels": (N,) int (observed labels only)},
#           ``context`` dict[str, Any], ``mask`` (H,W) bool, ``mask_reference`` (H,W) bool,
#           ``crop`` (x0,y0,w,h), ``K`` (3,3), ``profile`` {"camera"/"light"/"isp": dict}.
# APPEARANCE: ``texel_albedo`` (N,3) float32, ``texel_substrate_albedo`` (N,3) float32,
#           ``texel_area_mm2`` (N,) float64, ``texel_layer`` (N,) int32 (0 = substrate),
#           ``texel_roughness`` (N,) float32, ``texel_uv_mm`` (N,2) float64 (optional),
#           ``pattern_region`` (N,) bool, ``mesh`` (trimesh -> geometry hash guard).
# PHYSICAL : ``clean_truth`` (CleanTruth), ``fragment`` (Fragment), ``mesh`` (trimesh).
PAYLOAD_KEYS = {
    KIND_IMAGE: ("frames", "exposure_gain", "renderer", "scene"),
    KIND_GEOMETRY: ("points", "normals", "point_valid", "point_view", "frames", "mesh", "roi",
                    "priority_order", "reference_points", "scale_ratio", "K", "dist",
                    "clean_geometry_hash"),
    KIND_OBS: ("modalities", "observed_est", "context", "mask", "mask_reference", "crop", "K",
               "profile"),
    KIND_PHYSICAL: ("clean_truth", "fragment", "mesh"),
}


def is_mesh(value: Any) -> bool:
    return hasattr(value, "vertices") and hasattr(value, "faces")


def mesh_geometry_hash(mesh: Any) -> str:
    """Content hash of a mesh *geometry* (vertices/faces/face attributes).

    Used for the P05/P06/G08 claim "the physical/clean geometry hash is unchanged":
    the claim is checked against this hash, not against a flag.
    """
    if not is_mesh(mesh):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"not a mesh: {type(mesh)!r}",
                          stage="degrade.sources")
    payload = {
        "vertices": array_hash(np.asarray(mesh.vertices)),
        "faces": array_hash(np.asarray(mesh.faces)),
    }
    attrs = dict((getattr(mesh, "metadata", None) or {}).get("face_attr_arrays") or {})
    payload["face_attrs"] = {str(k): array_hash(np.asarray(v)) for k, v in sorted(attrs.items())}
    return hash_json(payload)


def freeze_value(value: Any, path: str = "") -> Any:
    """Deterministically convert a payload value into JSON-canonical data."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"NaN/Inf in payload at {path}",
                              stage="degrade.sources")
        return out
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"NaN/Inf in payload at {path}",
                              stage="degrade.sources")
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, np.ndarray):
        return {"__array__": array_hash(value), "dtype": str(value.dtype),
                "shape": list(value.shape)}
    if is_mesh(value):
        entry = {
            "__mesh__": array_hash(np.asarray(value.vertices)),
            "__faces__": array_hash(np.asarray(value.faces)),
            "n_vertices": int(len(value.vertices)), "n_faces": int(len(value.faces)),
        }
        attrs = dict((getattr(value, "metadata", None) or {}).get("face_attr_arrays") or {})
        if attrs:
            entry["face_attrs"] = {str(k): array_hash(np.asarray(v)) for k, v in sorted(attrs.items())}
        return entry
    if isinstance(value, dict):
        return {str(k): freeze_value(v, f"{path}.{k}") for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [freeze_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, Path):
        return str(value)
    if callable(value):
        return {"__callable__": f"{getattr(value, '__module__', '')}.{getattr(value, '__name__', type(value).__name__)}"}
    return {"__repr__": f"{type(value).__module__}.{type(value).__name__}"}


@dataclass
class SourceBundle:
    """Content-hashed input of one degradation step."""

    source_kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    asset_id: str | None = None
    role: str = ""
    schema: str = ""
    unit: str = UNIT_MM
    frame: str = FRAME_WORLD
    lineage_id: str | None = None
    fragment_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown source_kind {self.source_kind!r}; expected one of {SOURCE_KINDS}",
                              stage="degrade.sources")

    # ------------------------------------------------------------------ helpers
    def content_hash(self) -> str:
        """Stable hash of the payload content (arrays/meshes included by content)."""
        return hash_json({
            "source_kind": self.source_kind,
            "payload": freeze_value(self.payload),
            "unit": self.unit,
            "frame": self.frame,
        })

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.payload:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"source payload for {self.source_kind} requires {key!r}; available keys: "
                f"{sorted(self.payload)}",
                stage="degrade.sources",
            )
        return self.payload[key]

    def with_payload(self, **updates: Any) -> "SourceBundle":
        """Shallow copy with payload updates; unlisted payload objects are shared, not copied."""
        payload = dict(self.payload)
        payload.update(updates)
        return replace(self, payload=payload)

    def without(self, *keys: str) -> "SourceBundle":
        payload = {k: v for k, v in self.payload.items() if k not in keys}
        return replace(self, payload=payload)

    def describe(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind, "asset_id": self.asset_id, "role": self.role,
            "unit": self.unit, "frame": self.frame, "fragment_id": self.fragment_id,
            "payload_keys": sorted(self.payload), "content_hash": self.content_hash(),
        }


@dataclass
class OutputRef:
    """Reference to the result of one degradation step."""

    source_kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    identity: bool = False
    asset_id: str | None = None
    role: str = ""
    schema: str = ""
    unit: str = UNIT_MM
    frame: str = FRAME_WORLD
    source_hash: str = ""
    notes: str = ""

    def as_bundle(self) -> SourceBundle:
        return SourceBundle(source_kind=self.source_kind, payload=self.payload, asset_id=self.asset_id,
                            role=self.role, unit=self.unit, frame=self.frame)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind, "content_hash": self.content_hash,
            "identity": self.identity, "asset_id": self.asset_id, "role": self.role,
            "unit": self.unit, "frame": self.frame, "source_hash": self.source_hash,
            "notes": self.notes,
        }


def identity_output(source: SourceBundle, *, notes: str = "level 0 identity: source returned unchanged") -> OutputRef:
    """The level-0 contract: same payload objects, same hash, same asset reference."""
    return OutputRef(
        source_kind=source.source_kind, payload=source.payload, content_hash=source.content_hash(),
        identity=True, asset_id=source.asset_id, role=source.role, unit=source.unit,
        frame=source.frame, source_hash=source.content_hash(), notes=notes,
    )


def output_from(source: SourceBundle, result: SourceBundle, *, notes: str = "",
                asset_id: str | None = None) -> OutputRef:
    return OutputRef(
        source_kind=result.source_kind, payload=result.payload, content_hash=result.content_hash(),
        identity=False, asset_id=asset_id, role=result.role, unit=result.unit,
        frame=result.frame, source_hash=source.content_hash(), notes=notes,
    )


# ---------------------------------------------------------------- store flattening
def flatten_payload(payload: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any], list[str]]:
    """Split a payload into store arrays, JSON metadata and non-storable keys."""
    arrays: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {}
    dropped: list[str] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, np.ndarray):
            arrays[prefix] = np.ascontiguousarray(value)
            return
        if is_mesh(value):
            arrays[f"{prefix}.vertices"] = np.ascontiguousarray(np.asarray(value.vertices, dtype=np.float64))
            arrays[f"{prefix}.faces"] = np.ascontiguousarray(np.asarray(value.faces, dtype=np.int32))
            attrs = dict((getattr(value, "metadata", None) or {}).get("face_attr_arrays") or {})
            for name, arr in attrs.items():
                arrays[f"{prefix}.face__{name}"] = np.ascontiguousarray(np.asarray(arr))
            return
        if isinstance(value, dict):
            for key in sorted(value, key=str):
                walk(f"{prefix}.{key}", value[key])
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(f"{prefix}.{index}", item)
            return
        if value is None or isinstance(value, (str, int, float, bool, np.integer, np.floating, np.bool_)):
            meta[prefix] = freeze_value(value, prefix)
            return
        if callable(value):
            dropped.append(prefix)
            return
        meta[prefix] = freeze_value(value, prefix)

    for key in sorted(payload, key=str):
        walk(f"payload.{key}", payload[key])
    return arrays, meta, dropped


def unflatten_payload(arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> dict[str, Any]:
    """Inverse of :func:`flatten_payload` for arrays + metadata (dropped keys are absent)."""
    root: dict[str, Any] = {}

    def put(path: str, value: Any) -> None:
        parts = [part for part in path.split(".") if part != ""]
        if parts and parts[0] == "payload":
            parts = parts[1:]
        node: Any = root
        for position, part in enumerate(parts[:-1]):
            # A container is a list only when the *next* path element is an index; a list of
            # records (``frames.0.K``) therefore rebuilds as list -> dict -> value, which the
            # previous version mis-built as list -> list and then failed on the string key.
            next_is_index = parts[position + 1].isdigit()
            if isinstance(node, list):
                index = int(part)
                while len(node) <= index:
                    node.append(None)
                if not isinstance(node[index], (dict, list)):
                    node[index] = [] if next_is_index else {}
                node = node[index]
                continue
            key: Any = int(part) if part.isdigit() and next_is_index else part
            child = node.get(key)
            if not isinstance(child, (dict, list)):
                child = [] if next_is_index else {}
                node[key] = child
            node = child
        last = parts[-1]
        if isinstance(node, list):
            index = int(last)
            while len(node) <= index:
                node.append(None)
            node[index] = value
        else:
            node[last] = value

    mesh_prefixes: set[str] = set()
    for key in arrays:
        if key.endswith(".vertices") or key.endswith(".faces"):
            mesh_prefixes.add(key.rsplit(".", 1)[0])
    for prefix in sorted(mesh_prefixes):
        verts = arrays.get(f"{prefix}.vertices")
        faces = arrays.get(f"{prefix}.faces")
        if verts is None or faces is None:
            continue
        import trimesh

        mesh = trimesh.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                               faces=np.asarray(faces, dtype=np.int64), process=False)
        attrs = {k[len(prefix) + len(".face__"):]: v for k, v in arrays.items()
                 if k.startswith(f"{prefix}.face__")}
        mesh.metadata = dict(mesh.metadata or {})
        if attrs:
            mesh.metadata["face_attr_arrays"] = attrs
        put(prefix, mesh)
    for key, value in arrays.items():
        if key in {f"{p}.vertices" for p in mesh_prefixes} | {f"{p}.faces" for p in mesh_prefixes}:
            continue
        if any(key.startswith(f"{p}.face__") for p in mesh_prefixes):
            continue
        put(key, value)
    for key, value in meta.items():
        put(key, value)
    return root


def commit_source(store: Any, source: SourceBundle, *, role: str, schema: str,
                  lineage_id: str | None = None, split: str | None = None,
                  qa: dict[str, Any] | None = None, meta: dict[str, Any] | None = None) -> Any:
    """Commit a source/output bundle to an :class:`synlab.storage.store.AssetStore`."""
    arrays, extra_meta, dropped = flatten_payload(source.payload)
    payload: dict[str, Any] = dict(arrays)
    merged = dict(extra_meta)
    merged.update({
        "source_kind": source.source_kind,
        "payload_meta": extra_meta,
        "dropped_non_storable_keys": dropped,
        "content_hash": source.content_hash(),
    })
    if dropped:
        # honest: a callable cannot be stored; the asset records that it was dropped
        merged["storable"] = False
    return store.commit_asset(
        role=role or source.role or "degradation_output", schema=schema, unit=source.unit,
        frame=source.frame, payload=payload, meta={**merged, **(meta or {})}, qa=qa or {},
        lineage_id=lineage_id if lineage_id is not None else source.lineage_id, split=split,
    )


def load_source(store: Any, asset_id: str, record: Any | None = None) -> SourceBundle:
    """Reconstruct a bundle that was committed by :func:`commit_source`."""
    record = record or store.get_asset(asset_id)
    arrays = store.load_arrays(asset_id)
    meta = dict(record.meta or {})
    payload_meta = dict(meta.pop("payload_meta", {}) or {})
    meta.pop("dropped_non_storable_keys", None)
    meta.pop("content_hash", None)
    rewritten: dict[str, np.ndarray] = {}
    for key, value in arrays.items():
        # store arrays live under the payload path already (payload.<...>)
        rewritten[key if key.startswith("payload.") else f"payload.{key}"] = value
    payload = unflatten_payload(rewritten, payload_meta)
    return SourceBundle(source_kind=meta.get("source_kind", KIND_MESH), payload=payload,
                        asset_id=asset_id, role=record.role, schema=record.schema,
                        unit=record.unit, frame=record.frame, lineage_id=record.lineage_id)
