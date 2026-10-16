"""Hash-checked native cohesive-fragment observation and research-data adapter.

This adapter consumes the complete result of ``pgfrag.cohesive_fragments``. It validates the
native T4/component/surface accounting, renders each closed native surface through A12's NumPy
sensor renderer, and exports anonymous RGB-D/point-cloud observations separately from offline
native targets. A topologically closed fragment here is not a calibrated material result or a
production/training qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any, Mapping, Sequence
import zipfile

import numpy as np

from ..canonical import canonical_bytes
from ..errors import ErrorCode, SynLabError


SOURCE_SCHEMA = "pgfrag.native_cohesive_fragments.v1"
DATASET_SCHEMA = "synlab.native_cohesive_research_dataset.v1"
FEATURE_SCHEMA = "synlab.native_cohesive.sensor_features.v1"
TARGET_SCHEMA = "synlab.native_cohesive.offline_targets.v1"
_SHA256_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_PACKET_BYTES = 512 * 1024 * 1024
_MAX_NPZ_MEMBERS = 64
_MAX_NPZ_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_MAX_NATIVE_NODES = 100_000
_MAX_NATIVE_TETS = 1_000_000
_MAX_NATIVE_FACES = 1_000_000
_MAX_IMAGE_PIXELS = 512 * 512
_FEATURE_KEYS = frozenset({
    "rgb_u8", "depth_m", "point_xyz_sensor_m", "normal_sensor", "normal_valid",
    "view_point_offsets",
})
_STATE_KEYS = frozenset({
    "rest_nodes_m", "current_nodes_m", "velocity_mps", "tets", "triangles_native",
    "face_component", "face_kind", "face_parent_id", "native_to_source",
    "face_region_code", "face_color_linear_rgb", "cohesive_native",
    "cohesive_damage_qp", "cohesive_traction_Pa", "cohesive_opening_m",
})
_OPTIONAL_STATE_KEYS = frozenset({"cohesive_contact_traction_Pa"})
_REGION_BASES = (1, 2, 3)
_FAILED_REGION = 255


def _error(code: ErrorCode, message: str, *, field: str | None = None,
           measurements: Mapping[str, Any] | None = None) -> SynLabError:
    facts = dict(measurements or {})
    if field is not None:
        facts["field"] = field
    return SynLabError(code, message, stage="integrations.native_cohesive", measurements=facts)


def _invalid(message: str, *, field: str | None = None,
             measurements: Mapping[str, Any] | None = None) -> None:
    raise _error(ErrorCode.SCHEMA_INVALID, message, field=field, measurements=measurements)


def _unavailable(message: str, *, field: str | None = None,
                  measurements: Mapping[str, Any] | None = None) -> None:
    raise _error(ErrorCode.INPUT_UNAVAILABLE, message, field=field, measurements=measurements)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _root(value: str | os.PathLike[str], label: str) -> Path:
    path = Path(value)
    if path.is_symlink() or not path.is_dir():
        _unavailable(f"{label} must be an available non-symlink directory",
                     measurements={"path": str(path)})
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        _unavailable(f"cannot resolve {label}: {exc}", measurements={"path": str(path)})


def _safe_relative(value: Any, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _invalid("package paths must be non-empty POSIX relative paths", field=field)
    parts = value.split("/")
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in parts) \
            or ":" in parts[0]:
        _invalid("absolute, traversing, drive-qualified, or non-normalized path", field=field,
                 measurements={"path": value})
    return rel


def _contained_file(root: Path, value: Any, field: str) -> Path:
    rel = _safe_relative(value, field)
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _invalid("symlink payloads are not permitted", field=field,
                     measurements={"path": str(rel)})
    try:
        resolved = cursor.resolve(strict=True)
    except OSError as exc:
        _unavailable(f"declared payload is missing: {exc}", field=field,
                     measurements={"path": str(rel)})
    try:
        resolved.relative_to(root)
    except ValueError:
        _invalid("payload escapes its package root", field=field,
                 measurements={"path": str(rel)})
    if not resolved.is_file():
        _invalid("payload path is not a regular file", field=field,
                 measurements={"path": str(rel)})
    return resolved


def _walk_files(root: Path) -> set[str]:
    found: set[str] = set()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirnames):
            if (base / name).is_symlink():
                _invalid("package contains a symlink directory", measurements={
                    "path": str(base / name)})
        for name in filenames:
            path = base / name
            if path.is_symlink() or not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                _invalid("package contains a symlink or non-regular file",
                         measurements={"path": str(path)})
            found.add(path.relative_to(root).as_posix())
    return found


def _read_json(path: Path, field: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _unavailable(f"cannot read {field}: {exc}", field=field)
    if len(raw) > _MAX_JSON_BYTES:
        _invalid("JSON payload exceeds the bounded size", field=field,
                 measurements={"bytes": len(raw), "limit": _MAX_JSON_BYTES})
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda item: _invalid(
            f"non-finite JSON value {item}", field=field))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _invalid(f"payload is not valid UTF-8 JSON: {exc}", field=field)
    if not isinstance(value, dict):
        _invalid("JSON payload root must be an object", field=field)
    return value, raw


def _manifest_digest(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(canonical_bytes({key: item for key, item in value.items()
                                          if key != "manifest_sha256"}))


def _source_physics_review(source_manifest: Mapping[str, Any],
                           source_sha256: str,
                           explicit_review: Mapping[str, Any] | None = None
                           ) -> dict[str, Any]:
    """Bind an optional caller/source-packet control review to this exact frozen case."""
    qualification = source_manifest.get("qualification")
    packet_status = qualification.get("physical_control_status") \
        if isinstance(qualification, Mapping) else None
    if explicit_review is not None:
        review = dict(explicit_review)
        if review.get("source_case_sha256") != source_sha256:
            _invalid("physical-control review must bind the exact frozen source case",
                     field="source_physics_review.source_case_sha256")
        status = review.get("physical_control_status")
        if not isinstance(status, str) or not status.strip():
            _invalid("physical-control review needs a non-empty status",
                     field="source_physics_review.physical_control_status")
        if isinstance(packet_status, str) and packet_status.strip() \
                and packet_status != status:
            _invalid("caller review cannot override source-packet control qualification",
                     field="source_physics_review.physical_control_status")
        review["review_origin"] = "EXPORT_CALLER_REVIEW_BOUND_TO_SOURCE_CASE"
        return review
    return {"source_case_sha256": source_sha256,
            "physical_control_status": packet_status if isinstance(packet_status, str)
            and packet_status.strip() else "NOT_REVIEWED",
            "review_origin": "SOURCE_PACKET_QUALIFICATION"
            if isinstance(packet_status, str) and packet_status.strip() else "UNREVIEWED",
            "evidence_source": "SOURCE_PACKET_QUALIFICATION"
            if isinstance(packet_status, str) and packet_status.strip() else "UNREVIEWED"}


def _verify_npz_container(path: Path, field: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        _invalid(f"NPZ is not a valid ZIP container: {exc}", field=field)
    if len(entries) > _MAX_NPZ_MEMBERS:
        _invalid("NPZ contains too many members", field=field,
                 measurements={"members": len(entries), "limit": _MAX_NPZ_MEMBERS})
    names: set[str] = set()
    total = 0
    for entry in entries:
        name = entry.filename
        pure = PurePosixPath(name)
        if pure.is_absolute() or len(pure.parts) != 1 or not name.endswith(".npy") \
                or any(part in ("", ".", "..") for part in name.split("/")):
            _invalid("NPZ contains an unsafe member name", field=field,
                     measurements={"member": name})
        if name in names:
            _invalid("NPZ contains a duplicate member", field=field,
                     measurements={"member": name})
        names.add(name)
        total += entry.file_size
    if total > _MAX_NPZ_UNCOMPRESSED_BYTES:
        _invalid("NPZ uncompressed size exceeds its bound", field=field,
                 measurements={"bytes": total, "limit": _MAX_NPZ_UNCOMPRESSED_BYTES})


def _load_npz(path: Path, field: str) -> dict[str, np.ndarray]:
    _verify_npz_container(path, field)
    try:
        with np.load(path, allow_pickle=False) as source:
            values = {key: np.array(source[key], copy=True) for key in source.files}
    except (OSError, ValueError, EOFError, KeyError) as exc:
        _invalid(f"cannot load safe numeric NPZ: {exc}", field=field)
    if any(value.dtype.hasobject for value in values.values()):
        _invalid("NPZ object arrays are not permitted", field=field)
    return values


def _int_array(value: np.ndarray, field: str, ndim: int) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != ndim or array.dtype.kind not in "iu" or array.dtype.kind == "b":
        _invalid("array must be an integer array with the registered rank", field=field,
                 measurements={"shape": list(array.shape), "dtype": str(array.dtype)})
    return array.astype(np.int64, copy=False)


def _finite_array(value: np.ndarray, field: str, shape: tuple[int, ...] | None = None) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or array.dtype.hasobject:
        _invalid("array must have a numeric dtype", field=field)
    if shape is not None and array.shape != shape:
        _invalid("array shape does not match its contract", field=field,
                 measurements={"expected": list(shape), "actual": list(array.shape)})
    if not np.isfinite(array).all():
        _invalid("array contains NaN or infinity", field=field)
    return array


def _source_record(root: Path, source_manifest: Mapping[str, Any], source_raw: bytes
                   ) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any],
                              dict[str, Any], dict[str, Any] | None]:
    if source_manifest.get("schema") != SOURCE_SCHEMA:
        _invalid("unsupported native cohesive source schema", field="manifest.schema",
                 measurements={"actual": source_manifest.get("schema")})
    records = source_manifest.get("files")
    if not isinstance(records, Mapping):
        _invalid("source files map is required", field="manifest.files")
    required = {"fragments.json", "state.npz", "forge_manifest.json"}
    if not required.issubset(records):
        _unavailable("native source packet is missing required records",
                     field="manifest.files", measurements={
                         "missing": sorted(required - set(records))})

    paths: dict[str, Path] = {}
    verified_records: dict[str, dict[str, Any]] = {}
    total_source_bytes = 0
    for rel_value, record in records.items():
        rel = _safe_relative(rel_value, "manifest.files.path").as_posix()
        if rel == "manifest.json" or not isinstance(record, Mapping):
            _invalid("manifest file entry is malformed or self-referential",
                     field=f"manifest.files.{rel}")
        digest = record.get("sha256")
        count = record.get("bytes")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest) \
                or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            _invalid("file entries require a lowercase SHA-256 and byte count",
                     field=f"manifest.files.{rel}")
        total_source_bytes += count
        if total_source_bytes > _MAX_SOURCE_PACKET_BYTES:
            _invalid("source packet exceeds the bounded total byte budget",
                     field="manifest.files",
                     measurements={"bytes": total_source_bytes,
                                   "limit": _MAX_SOURCE_PACKET_BYTES})
        path = _contained_file(root, rel, f"manifest.files.{rel}")
        if path.stat().st_size != count or _sha256_file(path) != digest:
            _invalid("source file hash or byte count mismatch", field=f"manifest.files.{rel}")
        paths[rel] = path
        verified_records[rel] = {"sha256": digest, "bytes": count}
    actual_files = _walk_files(root)
    expected_files = set(records) | {"manifest.json"}
    if actual_files != expected_files:
        _invalid("source packet has unregistered or missing files", field="source files",
                 measurements={"expected": sorted(expected_files),
                               "actual": sorted(actual_files)})

    source = source_manifest.get("source")
    if not isinstance(source, Mapping):
        _invalid("native source hash bindings are required", field="manifest.source")
    source_digests: dict[str, str] = {}
    for key in ("run_receipt_sha256", "frozen_case_sha256", "forge_manifest_sha256"):
        digest = source.get(key)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            _invalid("source binding requires a lowercase SHA-256", field=f"source.{key}")
        source_digests[key] = digest
    forge_raw = paths["forge_manifest.json"].read_bytes()
    if _sha256_bytes(forge_raw) != source_digests["forge_manifest_sha256"]:
        _invalid("forge manifest bytes do not match the source binding",
                 field="source.forge_manifest_sha256")
    for candidates, digest_key in ((("receipt.json", "run_receipt.json"),
                                    "run_receipt_sha256"),
                                   (("case.json", "frozen_case.json"),
                                    "frozen_case_sha256")):
        for candidate in candidates:
            if candidate in paths and verified_records[candidate]["sha256"] != source_digests[digest_key]:
                _invalid("embedded source bytes disagree with their source binding",
                         field=f"source.{digest_key}")
    fragments, _ = _read_json(paths["fragments.json"], "fragments.json")
    forge_manifest, _ = _read_json(paths["forge_manifest.json"], "forge_manifest.json")
    case_path = next((paths[name] for name in ("case.json", "frozen_case.json")
                      if name in paths), None)
    case = _read_json(case_path, "case.json")[0] if case_path is not None else None
    if forge_manifest.get("schema") != "forge.asset.v1":
        _invalid("source material record must retain its forge.asset.v1 schema",
                 field="forge_manifest.schema")
    state = _load_npz(paths["state.npz"], "state.npz")
    missing_state = _STATE_KEYS - set(state)
    unknown_state = set(state) - _STATE_KEYS - _OPTIONAL_STATE_KEYS
    if missing_state or unknown_state:
        _invalid("state NPZ keys do not match the native cohesive adapter schema",
                 field="state.npz", measurements={"missing": sorted(missing_state),
                                                  "unknown": sorted(unknown_state)})
    qualification = source_manifest.get("qualification")
    if not isinstance(qualification, Mapping):
        _invalid("source qualification object is required", field="manifest.qualification")
    qualification_text = json.dumps(qualification, sort_keys=True).lower()
    if "preinserted_weak_seam" not in qualification_text or "uncalibrated" not in qualification_text:
        _invalid("source must explicitly identify the preinserted uncalibrated weak seam",
                 field="manifest.qualification")
    if qualification.get("physical_pass") is True or qualification.get("production_physical_pass") is True \
            or qualification.get("pretrain_eligible") is True \
            or qualification.get("deployment_eligible") is True:
        _invalid("source qualification cannot claim physical, PRETRAIN, or deployment PASS",
                 field="manifest.qualification")
    _validate_native_data(fragments, state, forge_manifest, case)
    return (dict(source_manifest), state, fragments, forge_manifest, case)


def _tet_volumes(nodes: np.ndarray, tets: np.ndarray, field: str) -> np.ndarray:
    p = nodes[tets]
    volumes = np.einsum("ij,ij->i", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]),
                        p[:, 3] - p[:, 0]) / 6.0
    if not np.isfinite(volumes).all() or np.any(volumes <= 0.0):
        _invalid("native tetrahedra must have finite positive signed volume", field=field,
                 measurements={"minimum_signed_volume_m3": float(np.min(volumes, initial=np.inf))})
    return volumes


def _edge_closure(triangles: np.ndarray, component_index: int) -> dict[str, int]:
    incidence: dict[tuple[int, int], list[int]] = {}
    for triangle in triangles:
        for left, right in ((int(triangle[0]), int(triangle[1])),
                            (int(triangle[1]), int(triangle[2])),
                            (int(triangle[2]), int(triangle[0]))):
            key = (min(left, right), max(left, right))
            incidence.setdefault(key, []).append(1 if left < right else -1)
    bad_count = sum(len(v) != 2 for v in incidence.values())
    bad_orientation = sum(len(v) == 2 and sum(v) != 0 for v in incidence.values())
    if not incidence or bad_count or bad_orientation:
        _invalid("native boundary edges are not a closed oriented two-manifold",
                 field=f"components[{component_index}].boundary_edges",
                 measurements={"edges": len(incidence), "bad_incidence": bad_count,
                               "bad_orientation": bad_orientation})
    return {"edges": len(incidence), "bad_incidence": bad_count,
            "bad_orientation": bad_orientation}


def _triangle_sign(triangle: Sequence[int]) -> int:
    values = [int(value) for value in triangle]
    inversions = sum(values[left] > values[right]
                     for left in range(3) for right in range(left + 1, 3))
    return -1 if inversions % 2 else 1


def _tet_boundary_signature(nodes: np.ndarray, tets: np.ndarray, tet_rows: np.ndarray,
                            component_index: int) -> dict[tuple[int, int, int], int]:
    """Rebuild an oriented boundary from T4 incidence, without trusting surface records."""
    incidence: dict[tuple[int, int, int], list[int]] = {}
    xyz = np.asarray(nodes, dtype=np.float64)
    for row in tet_rows:
        tet = np.asarray(tets[int(row)], dtype=np.int64)
        center = xyz[tet].mean(axis=0)
        for omitted in range(4):
            face = [int(tet[index]) for index in range(4) if index != omitted]
            points = xyz[face]
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            if float(np.dot(normal, points.mean(axis=0) - center)) < 0.0:
                face[1], face[2] = face[2], face[1]
            key = tuple(sorted(face))
            incidence.setdefault(key, []).append(_triangle_sign(face))
    boundary: dict[tuple[int, int, int], int] = {}
    for key, orientations in incidence.items():
        if len(orientations) == 1:
            boundary[key] = orientations[0]
        elif len(orientations) == 2 and sum(orientations) == 0:
            continue
        else:
            _invalid("T4 face incidence is non-manifold or internally misoriented",
                     field=f"components[{component_index}].tet_face_incidence",
                     measurements={"face": list(key), "incidence": len(orientations),
                                   "orientation_sum": int(sum(orientations))})
    return boundary


def _rotate_vectors_to_sensor(vectors_native: np.ndarray, rotation_native_to_sensor: np.ndarray
                              ) -> np.ndarray:
    """Rotate row-vector XYZ targets into the corresponding sensor frame."""
    values = np.asarray(vectors_native, dtype=np.float64)
    rotation = np.asarray(rotation_native_to_sensor, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or rotation.shape != (3, 3):
        _invalid("vector rotation requires (N,3) vectors and one (3,3) rotation",
                 field="sensor vector rotation")
    return values @ rotation.T


def _native_material(forge_manifest: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    material = forge_manifest.get("material")
    if not isinstance(material, Mapping):
        _invalid("forge material is required for complete mass accounting", field="material")
    mechanics = material.get("mechanics")
    if not isinstance(mechanics, Mapping):
        _invalid("forge material mechanics are required", field="material.mechanics")
    rho = mechanics.get("rho_kg_m3")
    if isinstance(rho, bool) or not isinstance(rho, (int, float)) \
            or not np.isfinite(float(rho)) or float(rho) <= 0:
        _invalid("positive bulk density is required for mass coverage",
                 field="material.mechanics.rho_kg_m3")
    ornament = forge_manifest.get("ornament")
    recipe = ornament.get("recipe") if isinstance(ornament, Mapping) else None
    if not isinstance(recipe, Mapping):
        _invalid("source appearance recipe is required", field="ornament.recipe")
    if recipe.get("coordinate_map") != "world_xyz_rest_mm; band centers use global Z":
        _invalid("source recipe coordinate_map must be honored as recorded",
                 field="ornament.recipe.coordinate_map",
                 measurements={"actual": recipe.get("coordinate_map")})
    if recipe.get("geometry_relief_mm") != 0.0 \
            or recipe.get("historical_style_validation") != "NOT_VALIDATED":
        _invalid("appearance recipe must remain painted, zero-relief, and unvalidated",
                 field="ornament.recipe")
    palette = recipe.get("palette_linear_rgb")
    bands = recipe.get("bands")
    regions = recipe.get("target_region_codes")
    if not isinstance(palette, Mapping) or "base" not in palette \
            or not isinstance(bands, list) or not bands \
            or not isinstance(regions, list) or not regions:
        _invalid("source appearance recipe palette, bands, and regions are incomplete",
                 field="ornament.recipe")
    for name, color in palette.items():
        value = _finite_array(np.asarray(color), f"ornament.recipe.palette_linear_rgb.{name}", (3,))
        if np.any(value < 0.0) or np.any(value > 1.0):
            _invalid("appearance palette values must be linear RGB in [0,1]",
                     field=f"ornament.recipe.palette_linear_rgb.{name}")
    for index, band in enumerate(bands):
        if not isinstance(band, Mapping):
            _invalid("appearance bands must be objects", field=f"ornament.recipe.bands[{index}]")
        center, width, color = band.get("center_z_mm"), band.get("width_mm"), band.get("color")
        if isinstance(center, bool) or not isinstance(center, (int, float)) \
                or not np.isfinite(float(center)) or isinstance(width, bool) \
                or not isinstance(width, (int, float)) or not np.isfinite(float(width)) \
                or float(width) <= 0 or not isinstance(color, str) or color not in palette \
                or color == "base":
            _invalid("appearance band has invalid z, width, or palette reference",
                     field=f"ornament.recipe.bands[{index}]")
    target_regions = _int_array(np.asarray(regions), "ornament.recipe.target_region_codes", 1)
    if not np.array_equal(target_regions, np.asarray([1], dtype=np.int64)):
        _invalid("the source three-band recipe is painted only on outer region code 1",
                 field="ornament.recipe.target_region_codes")
    return float(rho), dict(recipe)


def _validate_native_data(fragments: Mapping[str, Any], state: Mapping[str, np.ndarray],
                          forge_manifest: Mapping[str, Any],
                          case: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rest = _finite_array(state["rest_nodes_m"], "rest_nodes_m")
    current = _finite_array(state["current_nodes_m"], "current_nodes_m")
    velocity = _finite_array(state["velocity_mps"], "velocity_mps")
    if rest.ndim != 2 or rest.shape[1] != 3 or not 1 <= rest.shape[0] <= _MAX_NATIVE_NODES \
            or current.shape != rest.shape or velocity.shape != rest.shape:
        _invalid("native node state arrays must be finite aligned (N,3)",
                 field="rest_nodes_m/current_nodes_m/velocity_mps")
    tets = _int_array(state["tets"], "tets", 2)
    triangles = _int_array(state["triangles_native"], "triangles_native", 2)
    if tets.shape[1:] != (4,) or tets.shape[0] < 1 or tets.shape[0] > _MAX_NATIVE_TETS \
            or np.any(tets < 0) or np.any(tets >= rest.shape[0]):
        _invalid("native T4 connectivity is invalid or exceeds the bound", field="tets")
    if triangles.shape[1:] != (3,) or triangles.shape[0] < 1 \
            or triangles.shape[0] > _MAX_NATIVE_FACES \
            or np.any(triangles < 0) or np.any(triangles >= rest.shape[0]):
        _invalid("native boundary triangle connectivity is invalid", field="triangles_native")
    face_count = triangles.shape[0]
    face_component = _int_array(state["face_component"], "face_component", 1)
    face_parent = _int_array(state["face_parent_id"], "face_parent_id", 1)
    face_kind_raw = np.asarray(state["face_kind"])
    region_raw = np.asarray(state["face_region_code"])
    colors = _finite_array(state["face_color_linear_rgb"], "face_color_linear_rgb",
                           (face_count, 3))
    if face_component.shape != (face_count,) or face_parent.shape != (face_count,) \
            or face_kind_raw.shape != (face_count,) or face_kind_raw.dtype.kind not in "iu" \
            or region_raw.shape != (face_count,) or region_raw.dtype.kind not in "iu":
        _invalid("face channels must be aligned with native boundary triangles",
                 field="face_component/face_kind/face_parent_id/face_region_code")
    face_kind = face_kind_raw.astype(np.int64, copy=False)
    regions = region_raw.astype(np.int64, copy=False)
    if np.any(~np.isin(face_kind, (0, 1))) \
            or np.any(~np.isin(regions, (*_REGION_BASES, _FAILED_REGION))) \
            or np.any((face_kind == 0) & (face_parent != -1)) \
            or np.any((face_kind == 1) & (face_parent < 0)) \
            or np.any((face_kind == 0) & (regions == _FAILED_REGION)) \
            or np.any((face_kind == 1) & (regions != _FAILED_REGION)):
        _invalid("native face kind, parent facet, and appearance region disagree",
                 field="face_kind/face_parent_id/face_region_code")
    if np.any(colors < 0.0) or np.any(colors > 1.0):
        _invalid("fallback appearance colors must be finite linear RGB in [0,1]",
                 field="face_color_linear_rgb")
    ancestry = _int_array(state["native_to_source"], "native_to_source", 1)
    if ancestry.shape != (rest.shape[0],) or np.any(ancestry < 0):
        _invalid("native-to-source ancestry must map every native node", field="native_to_source")
    cohesive = _int_array(state["cohesive_native"], "cohesive_native", 2)
    cohesive_damage = _finite_array(state["cohesive_damage_qp"], "cohesive_damage_qp")
    cohesive_traction = _finite_array(state["cohesive_traction_Pa"],
                                      "cohesive_traction_Pa")
    contact_traction = None
    if "cohesive_contact_traction_Pa" in state:
        contact_traction = _finite_array(state["cohesive_contact_traction_Pa"],
                                         "cohesive_contact_traction_Pa")
    cohesive_opening = _finite_array(state["cohesive_opening_m"], "cohesive_opening_m")
    if cohesive.shape[1:] != (6,) or cohesive.shape[0] < 1 \
            or cohesive.shape[0] > _MAX_NATIVE_FACES \
            or np.any(cohesive < 0) or np.any(cohesive >= rest.shape[0]) \
            or cohesive_damage.shape != (cohesive.shape[0], 3) \
            or cohesive_traction.shape != (cohesive.shape[0], 3, 3) \
            or cohesive_opening.shape != (cohesive.shape[0], 3, 3) \
            or np.any(cohesive_damage < 0.0) or np.any(cohesive_damage > 1.0):
        _invalid("native cohesive connectivity and three-QP state arrays must align",
                 field="cohesive_native/cohesive_damage_qp/cohesive_traction_Pa/cohesive_opening_m")
    if contact_traction is not None and contact_traction.shape != (cohesive.shape[0], 3, 3):
        _invalid("native contact traction must align with all facets and three QPs",
                 field="cohesive_contact_traction_Pa")
    interface = case.get("interface") if isinstance(case, Mapping) else None
    if interface is not None and not isinstance(interface, Mapping):
        _invalid("case interface metadata must be an object",
                 field="case.interface")
    penalty = interface.get("penalty_Pa_m") if isinstance(interface, Mapping) else None
    if penalty is not None and (isinstance(penalty, bool)
            or not isinstance(penalty, (int, float)) or not np.isfinite(float(penalty))
            or float(penalty) < 0.0):
        _invalid("case interface penalty must be finite and non-negative",
                 field="case.interface.penalty_Pa_m")
    if penalty is not None and float(penalty) > 0.0 and contact_traction is None:
        _invalid("positive interface contact penalty requires raw cohesive contact traction",
                 field="cohesive_contact_traction_Pa")
    for facet_row, connectivity in enumerate(cohesive):
        if len(set(int(value) for value in connectivity[:3])) != 3 \
                or len(set(int(value) for value in connectivity[3:])) != 3 \
                or set(int(value) for value in connectivity[:3]) & \
                set(int(value) for value in connectivity[3:]):
            _invalid("each cohesive facet must contain two disjoint three-node sides",
                     field=f"cohesive_native[{facet_row}]")

    rest_volumes = _tet_volumes(rest, tets, "rest_nodes_m/tets")
    current_volumes = _tet_volumes(current, tets, "current_nodes_m/tets")
    components = fragments.get("components")
    if not isinstance(components, list) or not components:
        _invalid("native fragment extractor components are required", field="fragments.components")
    if fragments.get("all_components_qualified_closed_mechanical_fragments") is not True \
            or fragments.get("complete_tet_volume_coverage") is not True:
        _invalid("source extractor did not qualify complete native closed components",
                 field="fragments qualification")
    for key, array in (("rest_nodes", rest), ("current_nodes", current), ("native_tets", tets),
                       ("native_node_to_source", ancestry)):
        source_value = fragments.get(key)
        if source_value is None:
            _invalid("complete native extractor return is required", field=f"fragments.{key}")
        source_array = np.asarray(source_value)
        if source_array.shape != array.shape or not np.allclose(
                source_array.astype(np.float64), array.astype(np.float64), rtol=0.0, atol=1e-12):
            _invalid("state NPZ and complete extractor JSON disagree", field=f"fragments.{key}")

    global_faces = fragments.get("boundary_faces")
    if not isinstance(global_faces, list) or len(global_faces) != face_count:
        _invalid("boundary face records must cover every global native triangle",
                 field="fragments.boundary_faces")
    face_seen = np.zeros(face_count, dtype=bool)
    face_record_by_index: dict[int, Mapping[str, Any]] = {}
    for record in global_faces:
        if not isinstance(record, Mapping):
            _invalid("boundary face record must be an object", field="fragments.boundary_faces")
        index = record.get("global_face_index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < face_count \
                or face_seen[index]:
            _invalid("global boundary face indices must be unique and in range",
                     field="boundary_faces.global_face_index")
        face_seen[index] = True
        face_record_by_index[index] = record
        tri = _int_array(np.asarray(record.get("native_node_ids")),
                         f"boundary_faces[{index}].native_node_ids", 1)
        if tri.shape != (3,) or not np.array_equal(tri, triangles[index]):
            _invalid("boundary face orientation must match the native triangle array",
                     field=f"boundary_faces[{index}].native_node_ids")
        component = record.get("component_index")
        if component != int(face_component[index]):
            _invalid("boundary face component does not match its array channel",
                     field=f"boundary_faces[{index}].component_index")
        kind_expected = "original_exterior" if face_kind[index] == 0 else "failed_cohesive_interface"
        if record.get("surface_kind") != kind_expected:
            _invalid("boundary surface kind does not match face_kind", field=f"boundary_faces[{index}]")
        if record.get("source_exterior_ancestry_verified") is not True:
            _invalid("native boundary face must retain extractor-verified source ancestry",
                     field=f"boundary_faces[{index}].source_exterior_ancestry_verified")
        facet_row = record.get("facet_row")
        if (face_kind[index] == 0 and facet_row is not None) \
                or (face_kind[index] == 1 and facet_row != int(face_parent[index])):
            _invalid("boundary face facet row does not match face_parent_id",
                     field=f"boundary_faces[{index}].facet_row")
    if not face_seen.all():
        _invalid("global boundary face records are incomplete", field="fragments.boundary_faces")

    # Preserve the extractor's paired failed-interface ancestry. A topological split alone
    # cannot establish which faces came from native cohesive failure.
    failed_pairs = fragments.get("failed_interface_face_pairs")
    facet_evidence = fragments.get("facet_failure_evidence")
    if not isinstance(failed_pairs, list) or not isinstance(facet_evidence, list):
        _invalid("native failed-interface pairs and facet evidence are required",
                 field="fragments.failed_interface_face_pairs/facet_failure_evidence")
    evidence_by_row: dict[int, Mapping[str, Any]] = {}
    failure_thresholds = fragments.get("failure_thresholds")
    if not isinstance(failure_thresholds, Mapping):
        _invalid("native failure thresholds are required to recompute facet gates",
                 field="fragments.failure_thresholds")
    damage_tolerance = failure_thresholds.get("damage_tolerance")
    damage_threshold = failure_thresholds.get("damage_threshold_inclusive")
    traction_tolerance = failure_thresholds.get("traction_norm_tolerance_inclusive")
    if isinstance(damage_tolerance, bool) or not isinstance(damage_tolerance, (int, float)) \
            or not np.isfinite(float(damage_tolerance)) or not 0.0 <= float(damage_tolerance) <= 1.0 \
            or isinstance(damage_threshold, bool) or not isinstance(damage_threshold, (int, float)) \
            or not np.isfinite(float(damage_threshold)) \
            or not np.isclose(float(damage_threshold), 1.0 - float(damage_tolerance),
                              rtol=0.0, atol=1e-15) \
            or isinstance(traction_tolerance, bool) \
            or not isinstance(traction_tolerance, (int, float)) \
            or not np.isfinite(float(traction_tolerance)) or float(traction_tolerance) < 0.0 \
            or failure_thresholds.get("facet_fails_only_if_all_qps_pass_both") is not True:
        _invalid("damage/traction thresholds or all-QP failure rule are invalid",
                 field="fragments.failure_thresholds")
    damage_threshold = float(damage_threshold)
    traction_tolerance = float(traction_tolerance)
    qp_counts: set[int] = set()
    recomputed_failed_rows: set[int] = set()
    qp_joint_pass_count = 0
    qp_sample_count = 0
    for evidence in facet_evidence:
        if not isinstance(evidence, Mapping):
            _invalid("facet failure evidence must contain objects",
                     field="fragments.facet_failure_evidence")
        facet_row = evidence.get("facet_row")
        if isinstance(facet_row, bool) or not isinstance(facet_row, int) or facet_row < 0 \
                or facet_row in evidence_by_row:
            _invalid("facet evidence rows must be unique non-negative integers",
                     field="facet_failure_evidence.facet_row")
        if facet_row >= cohesive.shape[0]:
            _invalid("facet evidence row is outside native cohesive state",
                     field=f"facet_failure_evidence[{facet_row}].facet_row")
        evidence_by_row[facet_row] = evidence
        damage_qp = _finite_array(np.asarray(evidence.get("damage_qp")),
                                  f"facet_failure_evidence[{facet_row}].damage_qp")
        traction_norm_qp = _finite_array(
            np.asarray(evidence.get("traction_norm_qp")),
            f"facet_failure_evidence[{facet_row}].traction_norm_qp")
        if damage_qp.ndim != 1 or traction_norm_qp.ndim != 1 \
                or damage_qp.size == 0 or damage_qp.shape != traction_norm_qp.shape \
                or np.any(damage_qp < 0.0) or np.any(damage_qp > 1.0) \
                or np.any(traction_norm_qp < 0.0):
            _invalid("each facet needs aligned finite damage and traction-norm QP values",
                     field=f"facet_failure_evidence[{facet_row}].damage_qp/traction_norm_qp")
        effective_traction = cohesive_traction if contact_traction is None else \
            cohesive_traction + contact_traction
        state_traction_norm = np.linalg.norm(effective_traction[facet_row], axis=1)
        if not np.array_equal(cohesive_damage[facet_row], damage_qp) \
                or not np.allclose(state_traction_norm, traction_norm_qp,
                                   rtol=1e-12, atol=1e-15):
            _invalid("facet QP evidence disagrees with the byte-verified native cohesive state",
                     field=f"cohesive_damage_qp/cohesive_traction_Pa[{facet_row}]")
        side_a_nodes = _int_array(np.asarray(evidence.get("side_a_native_node_ids")),
                                  f"facet_failure_evidence[{facet_row}].side_a_native_node_ids", 1)
        side_b_nodes = _int_array(np.asarray(evidence.get("side_b_native_node_ids")),
                                  f"facet_failure_evidence[{facet_row}].side_b_native_node_ids", 1)
        native_side_a = cohesive[facet_row, :3]
        native_side_b = cohesive[facet_row, 3:]
        if side_a_nodes.shape != (3,) or side_b_nodes.shape != (3,) \
                or not np.array_equal(side_a_nodes, native_side_a) \
                or not np.array_equal(side_b_nodes, native_side_b):
            _invalid("facet QP evidence sides must preserve raw native COH connectivity",
                     field=f"facet_failure_evidence[{facet_row}].side_native_node_ids")
        pairs_native = evidence.get("paired_native_node_ids")
        if not isinstance(pairs_native, list) or len(pairs_native) != 3:
            _invalid("each failed facet must preserve its three native-to-source node pairs",
                     field=f"facet_failure_evidence[{facet_row}].paired_native_node_ids")
        paired_left: set[int] = set()
        paired_right: set[int] = set()
        for pair_nodes in pairs_native:
            if not isinstance(pair_nodes, list) or len(pair_nodes) != 2:
                _invalid("native cohesive node ancestry pairs must contain two node IDs",
                         field=f"facet_failure_evidence[{facet_row}].paired_native_node_ids")
            left, right = pair_nodes
            if isinstance(left, bool) or not isinstance(left, int) \
                    or isinstance(right, bool) or not isinstance(right, int) \
                    or left not in native_side_a or right not in native_side_b \
                    or int(ancestry[left]) != int(ancestry[right]) \
                    or not np.array_equal(rest[left], rest[right]) \
                    or left in paired_left or right in paired_right:
                _invalid("cohesive node pairs disagree with native source ancestry/rest geometry",
                         field=f"facet_failure_evidence[{facet_row}].paired_native_node_ids")
            paired_left.add(left)
            paired_right.add(right)
        if paired_left != set(int(value) for value in native_side_a) \
                or paired_right != set(int(value) for value in native_side_b):
            _invalid("paired node ancestry must cover both complete cohesive sides",
                     field=f"facet_failure_evidence[{facet_row}].paired_native_node_ids")
        qp_counts.add(int(damage_qp.size))
        damage_pass = damage_qp >= damage_threshold
        traction_pass = traction_norm_qp <= traction_tolerance
        joint_pass = damage_pass & traction_pass
        qp_joint_pass_count += int(np.count_nonzero(joint_pass))
        qp_sample_count += int(joint_pass.size)
        for key, expected in (("qp_damage_pass", damage_pass),
                              ("qp_traction_pass", traction_pass),
                              ("qp_joint_failure_pass", joint_pass)):
            actual = np.asarray(evidence.get(key))
            if actual.dtype.kind != "b" or actual.shape != expected.shape \
                    or not np.array_equal(actual, expected):
                _invalid("recorded QP gate flags disagree with numeric failure evidence",
                         field=f"facet_failure_evidence[{facet_row}].{key}")
        expected_failed = bool(np.all(joint_pass))
        if evidence.get("failed") is not expected_failed:
            _invalid("facet failure must be recomputed from every QP and both thresholds",
                     field=f"facet_failure_evidence[{facet_row}].failed")
        if expected_failed:
            recomputed_failed_rows.add(facet_row)
    if len(qp_counts) > 1:
        _invalid("native facets must use a consistent quadrature-point count",
                 field="fragments.facet_failure_evidence",
                 measurements={"quadrature_points_per_facet": sorted(qp_counts)})
    declared_cohesive_count = fragments.get("native_cohesive_facet_count")
    if declared_cohesive_count != cohesive.shape[0] \
            or len(evidence_by_row) != cohesive.shape[0] \
            or set(evidence_by_row) != set(range(cohesive.shape[0])):
        _invalid("failure evidence must cover every native cohesive facet",
                 field="fragments.native_cohesive_facet_count")
    declared_failed_rows = fragments.get("failed_facet_rows")
    if declared_failed_rows is None or _int_array(np.asarray(declared_failed_rows),
                                                   "fragments.failed_facet_rows", 1).tolist() \
            != sorted(recomputed_failed_rows):
        _invalid("failed facet row inventory disagrees with recomputed QP gates",
                 field="fragments.failed_facet_rows")
    paired_rows: set[int] = set()
    paired_faces: set[int] = set()
    for pair in failed_pairs:
        if not isinstance(pair, Mapping):
            _invalid("failed interface pair records must be objects",
                     field="fragments.failed_interface_face_pairs")
        facet_row = pair.get("facet_row")
        side_faces = (pair.get("side_a_boundary_face_index"),
                      pair.get("side_b_boundary_face_index"))
        side_components = (pair.get("side_a_component_index"),
                           pair.get("side_b_component_index"))
        if isinstance(facet_row, bool) or not isinstance(facet_row, int) \
                or facet_row < 0 or facet_row in paired_rows \
                or facet_row not in evidence_by_row:
            _invalid("failed interface facet rows must match unique failure evidence",
                     field="failed_interface_face_pairs.facet_row")
        evidence = evidence_by_row[facet_row]
        if evidence.get("failed") is not True or facet_row not in recomputed_failed_rows:
            _invalid("paired failed interfaces require positive extractor failure evidence",
                     field=f"facet_failure_evidence[{facet_row}].failed")
        parent_facet_id = pair.get("parent_facet_id")
        if isinstance(parent_facet_id, bool) or not isinstance(parent_facet_id, int) \
                or evidence.get("parent_facet_id") != parent_facet_id:
            _invalid("failed interface pair must preserve its source parent facet identity",
                     field=f"failed_interface_face_pairs[{facet_row}].parent_facet_id")
        if len(side_faces) != 2 or len(side_components) != 2 \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or not 0 <= value < face_count for value in side_faces) \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or not 0 <= value < len(components) for value in side_components) \
                or side_faces[0] == side_faces[1] or side_faces[0] in paired_faces \
                or side_faces[1] in paired_faces:
            _invalid("failed interface sides must uniquely reference valid boundary faces",
                     field=f"failed_interface_face_pairs[{facet_row}]")
        native_side_a = set(int(value) for value in cohesive[facet_row, :3])
        native_side_b = set(int(value) for value in cohesive[facet_row, 3:])
        pair_side_a = _int_array(np.asarray(pair.get("side_a_native_node_ids")),
                                 f"failed_interface_face_pairs[{facet_row}].side_a_native_node_ids", 1)
        pair_side_b = _int_array(np.asarray(pair.get("side_b_native_node_ids")),
                                 f"failed_interface_face_pairs[{facet_row}].side_b_native_node_ids", 1)
        if pair_side_a.shape != (3,) or pair_side_b.shape != (3,) \
                or set(int(value) for value in pair_side_a) != native_side_a \
                or set(int(value) for value in pair_side_b) != native_side_b:
            _invalid("failed boundary pair must retain both raw cohesive connectivity sides",
                     field=f"failed_interface_face_pairs[{facet_row}].side_native_node_ids")
        for side, face_index, component_index in (("a", side_faces[0], side_components[0]),
                                                   ("b", side_faces[1], side_components[1])):
            record = face_record_by_index[face_index]
            side_nodes = _int_array(np.asarray(pair.get(f"side_{side}_native_node_ids")),
                                    f"failed_interface_face_pairs[{facet_row}].side_{side}_native_node_ids",
                                    1)
            if face_kind[face_index] != 1 or face_parent[face_index] != facet_row \
                    or face_component[face_index] != component_index \
                    or record.get("facet_row") != facet_row \
                    or record.get("parent_facet_id") != parent_facet_id \
                    or not np.array_equal(side_nodes, triangles[face_index]):
                _invalid("failed interface pair disagrees with native boundary face ancestry",
                         field=f"failed_interface_face_pairs[{facet_row}].side_{side}")
        paired_rows.add(facet_row)
        paired_faces.update(side_faces)
    failed_rows = set(int(row) for row in np.unique(face_parent[face_kind == 1]))
    failed_face_indices = set(np.flatnonzero(face_kind == 1).tolist())
    if paired_rows != failed_rows or paired_faces != failed_face_indices:
        _invalid("failed interface pairs must cover every and only failed cohesive boundary face",
                 field="fragments.failed_interface_face_pairs",
                 measurements={"paired_facets": len(paired_rows),
                               "failed_facets": len(failed_rows),
                               "paired_faces": len(paired_faces),
                               "failed_faces": len(failed_face_indices)})
    for facet_row, evidence in evidence_by_row.items():
        if bool(evidence.get("failed")) != (facet_row in paired_rows):
            _invalid("facet evidence failure flags disagree with paired native surfaces",
                     field=f"facet_failure_evidence[{facet_row}].failed")

    component_count = len(components)
    if np.any(face_component < 0) or np.any(face_component >= component_count):
        _invalid("face_component contains unknown component indices", field="face_component")
    if not np.array_equal(np.unique(face_component), np.arange(component_count)):
        _invalid("every component must carry native boundary triangles", field="face_component")
    tet_coverage = np.zeros(tets.shape[0], dtype=np.uint8)
    node_owner = np.full(rest.shape[0], -1, dtype=np.int64)
    total_rest = 0.0
    total_current = 0.0
    component_edge_audits: list[dict[str, int]] = []
    for expected_index, component in enumerate(components):
        if not isinstance(component, Mapping) or component.get("component_index") != expected_index \
                or component.get("qualified_closed_mechanical_fragment") is not True:
            _invalid("all component records must be indexed and extractor-qualified",
                     field=f"components[{expected_index}]")
        tet_rows = _int_array(np.asarray(component.get("tet_rows")),
                              f"components[{expected_index}].tet_rows", 1)
        node_ids = _int_array(np.asarray(component.get("native_node_ids")),
                              f"components[{expected_index}].native_node_ids", 1)
        face_ids = _int_array(np.asarray(component.get("face_indices")),
                              f"components[{expected_index}].face_indices", 1)
        if tet_rows.size == 0 or np.any(tet_rows < 0) or np.any(tet_rows >= tets.shape[0]) \
                or np.any(tet_coverage[tet_rows] != 0):
            _invalid("component T4 rows must partition the native tetrahedra",
                     field=f"components[{expected_index}].tet_rows")
        tet_coverage[tet_rows] = 1
        owned_nodes = np.unique(tets[tet_rows].reshape(-1))
        if not np.array_equal(np.unique(node_ids), owned_nodes) or np.any(node_ids < 0) \
                or np.any(node_ids >= rest.shape[0]):
            _invalid("component native nodes do not match its T4 rows",
                     field=f"components[{expected_index}].native_node_ids")
        if np.any(node_owner[node_ids] != -1):
            _invalid("qualified components cannot share native nodes",
                     field=f"components[{expected_index}].native_node_ids")
        node_owner[node_ids] = expected_index
        expected_face_ids = np.flatnonzero(face_component == expected_index).astype(np.int64)
        if not np.array_equal(face_ids, expected_face_ids):
            _invalid("component face indices do not match the global face_component channel",
                     field=f"components[{expected_index}].face_indices")
        comp_triangles = triangles[face_ids]
        comp_native_triangles = component.get("oriented_native_triangles")
        if comp_native_triangles is None or not np.array_equal(
                np.asarray(comp_native_triangles, dtype=np.int64), comp_triangles):
            _invalid("component oriented triangles differ from native boundary records",
                     field=f"components[{expected_index}].oriented_native_triangles")
        component_boundary = component.get("boundary_faces")
        if not isinstance(component_boundary, list) or [item.get("global_face_index")
                for item in component_boundary if isinstance(item, Mapping)] != face_ids.tolist():
            _invalid("component boundary records do not match its face indices",
                     field=f"components[{expected_index}].boundary_faces")
        tet_boundary = _tet_boundary_signature(rest, tets, tet_rows, expected_index)
        observed_boundary: dict[tuple[int, int, int], int] = {}
        for triangle in comp_triangles:
            key = tuple(sorted(int(node) for node in triangle))
            if key in observed_boundary:
                _invalid("native component surface repeats an unordered triangle",
                         field=f"components[{expected_index}].oriented_native_triangles",
                         measurements={"triangle": list(key)})
            observed_boundary[key] = _triangle_sign(triangle)
        if observed_boundary != tet_boundary:
            _invalid("component triangles do not equal the oriented T4-incidence boundary",
                     field=f"components[{expected_index}].oriented_native_triangles",
                     measurements={"t4_boundary_faces": len(tet_boundary),
                                   "recorded_boundary_faces": len(observed_boundary),
                                   "missing_faces": len(set(tet_boundary) - set(observed_boundary)),
                                   "extra_or_reoriented_faces": len(
                                       set(observed_boundary) - set(tet_boundary)) + sum(
                                           observed_boundary[key] != tet_boundary[key]
                                           for key in set(observed_boundary) & set(tet_boundary))})
        edge_audit = _edge_closure(comp_triangles, expected_index)
        component_edge_audits.append(edge_audit)
        rest_volume = float(rest_volumes[tet_rows].sum(dtype=np.float64))
        current_volume = float(current_volumes[tet_rows].sum(dtype=np.float64))
        if not np.isclose(rest_volume, float(component.get("rest_bulk_volume")),
                          rtol=1e-10, atol=1e-15) \
                or not np.isclose(current_volume, float(component.get("current_bulk_volume")),
                                  rtol=1e-10, atol=1e-15):
            _invalid("component native bulk volumes do not match T4 recomputation",
                     field=f"components[{expected_index}].bulk_volume")
        total_rest += rest_volume
        total_current += current_volume
    if not np.all(tet_coverage == 1) or np.any(node_owner == -1):
        _invalid("native T4 or node coverage is incomplete", field="component coverage")
    if not np.isclose(total_rest, float(fragments.get("total_rest_bulk_volume")),
                      rtol=1e-10, atol=1e-15) \
            or not np.isclose(total_current, float(fragments.get("total_current_bulk_volume")),
                              rtol=1e-10, atol=1e-15):
        _invalid("component volume totals do not cover the native bulk mesh",
                 field="fragments volume coverage")
    rho, recipe = _native_material(forge_manifest)
    # When the source declares the bowl radii, audit the region codes against the actual
    # rest-state triangle vertices. These codes control only the renderer's appearance.
    provenance = forge_manifest.get("provenance")
    spec = provenance.get("spec") if isinstance(provenance, Mapping) else None
    if isinstance(spec, Mapping) and all(key in spec for key in
                                         ("center_xyz_mm", "outer_radius_mm", "inner_radius_mm")):
        center_mm = _finite_array(np.asarray(spec["center_xyz_mm"]),
                                  "provenance.spec.center_xyz_mm", (3,))
        radii_mm = (spec["outer_radius_mm"], spec["inner_radius_mm"])
        if any(isinstance(radius, bool) or not isinstance(radius, (int, float))
               or not np.isfinite(float(radius)) or float(radius) <= 0 for radius in radii_mm):
            _invalid("bowl radii must be finite positive millimetres",
                     field="provenance.spec.outer_radius_mm/inner_radius_mm")
        radius_m = np.linalg.norm(rest - center_mm[None, :] / 1000.0, axis=1)
        for region, radius in ((1, float(radii_mm[0]) / 1000.0),
                               (2, float(radii_mm[1]) / 1000.0)):
            mask = (regions == region) & (face_kind == 0)
            if mask.any() and np.any(np.abs(radius_m[triangles[mask]] - radius) > 1e-8):
                _invalid("bowl appearance region does not match every rest triangle vertex",
                         field=f"face_region_code[{region}]")
        rim = (regions == 3) & (face_kind == 0)
        if rim.any():
            center_z_m = float(center_mm[2]) / 1000.0
            if np.any(np.abs(rest[triangles[rim], 2] - center_z_m) > 1e-8):
                _invalid("rim appearance region does not match the source rest plane",
                         field="face_region_code[3]")
    component_mass = float(rho * total_rest)
    if not np.isclose(sum(float(rho * rest_volumes[
            _int_array(np.asarray(component["tet_rows"]), "component.tet_rows", 1)].sum())
            for component in components), component_mass, rtol=1e-12, atol=1e-18):
        _invalid("component bulk mass does not cover source density times full rest volume",
                 field="component mass coverage")
    return {"nodes": int(rest.shape[0]), "tets": int(tets.shape[0]),
            "boundary_faces": face_count, "components": component_count,
            "failed_cohesive_faces": int(np.count_nonzero(face_kind == 1)),
            "native_cohesive_facets": len(evidence_by_row),
            "recomputed_failed_facets": len(recomputed_failed_rows),
            "qp_samples_with_both_failure_criteria": qp_joint_pass_count,
            "qp_sample_count": qp_sample_count,
            "quadrature_points_per_facet": next(iter(qp_counts), 0),
            "contact_traction_present": contact_traction is not None,
            "interface_penalty_Pa_m": float(penalty) if penalty is not None else None,
            "total_rest_bulk_volume_m3": total_rest,
            "total_current_bulk_volume_m3": total_current,
            "rho_kg_m3": rho, "total_rest_bulk_mass_kg": component_mass,
            "component_edge_audits": component_edge_audits,
            "appearance_pattern_id": str(recipe.get("pattern_id", "unspecified")),
            "appearance_coordinate_map": str(recipe["coordinate_map"])}


def validate_native_cohesive_fragments(source_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Verify all source file digests, exact ancestry, T4 mass coverage, and closed surfaces."""
    root = _root(source_dir, "native cohesive source packet")
    manifest, raw = _read_json(_contained_file(root, "manifest.json", "manifest.json"),
                               "manifest.json")
    loaded_manifest, state, fragments, forge, _case = _source_record(root, manifest, raw)
    arrays_report = _validate_native_data(fragments, state, forge, _case)
    source = dict(loaded_manifest["source"])
    source["source_manifest_sha256"] = _sha256_bytes(raw)
    return {"ok": True, "status": "SOURCE_VERIFIED_RESEARCH_ONLY",
            "source": source, "counts": arrays_report,
            "qualification": {"topology": "CLOSED_NATIVE_BOUNDARIES_VALIDATED",
                              "material_calibration_status": "UNCALIBRATED",
                              "physical_pass": False, "pretrain_eligible": False,
                              "deployment_eligible": False}}


@dataclass(frozen=True, slots=True)
class _RestWorldZAppearanceSampler:
    """Private renderer callback for the source-declared global-rest-Z paint recipe."""

    faces: np.ndarray
    rest_xyz_mm: np.ndarray
    face_regions: np.ndarray
    palette: Mapping[str, Sequence[float]]
    bands: Sequence[Mapping[str, Any]]
    target_regions: frozenset[int]

    def sample_albedo(self, face_indices: np.ndarray, barycentric: np.ndarray,
                      fallback_linear_rgb: np.ndarray) -> np.ndarray:
        ids = np.asarray(face_indices, dtype=np.int64).reshape(-1)
        bary = np.asarray(barycentric, dtype=np.float64).reshape(-1, 3)
        fallback = np.asarray(fallback_linear_rgb, dtype=np.float64).reshape(-1, 3)
        if bary.shape[0] != ids.size or fallback.shape[0] != ids.size \
                or np.any(ids < 0) or np.any(ids >= self.faces.shape[0]):
            _invalid("raster appearance callback received invalid face/barycentric rows",
                     field="appearance sampler")
        output = fallback.copy()
        selected = np.isin(self.face_regions[ids], np.asarray(sorted(self.target_regions)))
        if not selected.any():
            return output
        local_ids = ids[selected]
        rest_triangles = self.rest_xyz_mm[self.faces[local_ids]]
        rest_z = np.einsum("ni,ni->n", bary[selected], rest_triangles[:, :, 2])
        base = np.asarray(self.palette["base"], dtype=np.float64)
        output[selected] = base
        for band in self.bands:
            center, width = float(band["center_z_mm"]), float(band["width_mm"])
            in_band = np.abs(rest_z - center) <= width / 2.0
            if in_band.any():
                output[np.flatnonzero(selected)[in_band]] = np.asarray(
                    self.palette[str(band["color"])], dtype=np.float64)
        return output


def _proper_rotation(rng: np.random.Generator) -> np.ndarray:
    quaternion = rng.normal(size=4)
    quaternion /= np.linalg.norm(quaternion)
    w, x, y, z = quaternion
    return np.asarray([
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w),
         2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z),
         2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w),
         1.0 - 2.0 * (x * x + y * y)],
    ], dtype=np.float64)


def _depth_normals(depth_m: np.ndarray, K: np.ndarray, valid: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray]:
    h, w = depth_m.shape
    v, u = np.mgrid[0:h, 0:w]
    z = np.asarray(depth_m, dtype=np.float64)
    points = np.stack([(u - K[0, 2]) * z / K[0, 0],
                       (v - K[1, 2]) * z / K[1, 1], z], axis=-1)
    normals = np.zeros((h, w, 3), dtype=np.float64)
    mask = np.zeros((h, w), dtype=bool)
    if h < 3 or w < 3:
        return normals.astype(np.float32), mask
    center_z = z[1:-1, 1:-1]
    neighbours_ok = (valid[1:-1, :-2] & valid[1:-1, 2:] & valid[:-2, 1:-1]
                     & valid[2:, 1:-1])
    depth_limit = np.maximum(0.0005, center_z * 0.02)
    same_surface = (np.abs(z[1:-1, :-2] - center_z) <= depth_limit) \
        & (np.abs(z[1:-1, 2:] - center_z) <= depth_limit) \
        & (np.abs(z[:-2, 1:-1] - center_z) <= depth_limit) \
        & (np.abs(z[2:, 1:-1] - center_z) <= depth_limit)
    dx = points[1:-1, 2:] - points[1:-1, :-2]
    dy = points[2:, 1:-1] - points[:-2, 1:-1]
    raw = np.cross(dx, dy)
    length = np.linalg.norm(raw, axis=-1)
    good = neighbours_ok & same_surface & np.isfinite(raw).all(axis=-1) & (length > 1e-10)
    unit = np.divide(raw, np.maximum(length[..., None], 1e-30))
    away = np.einsum("ijk,ijk->ij", unit, points[1:-1, 1:-1]) > 0.0
    unit[away] *= -1.0
    normals[1:-1, 1:-1] = np.where(good[..., None], unit, 0.0)
    mask[1:-1, 1:-1] = good
    return normals.astype(np.float32), mask


def _barycentric(point: np.ndarray, triangle: np.ndarray) -> np.ndarray:
    a, b, c = triangle
    v0, v1, v2 = b - a, c - a, point - a
    d00, d01, d11 = np.dot(v0, v0), np.dot(v0, v1), np.dot(v1, v1)
    d20, d21 = np.dot(v2, v0), np.dot(v2, v1)
    denom = d00 * d11 - d01 * d01
    if not np.isfinite(denom) or denom <= 1e-24:
        _invalid("rendered source triangle is degenerate", field="native triangle")
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    return np.asarray([1.0 - v - w, v, w], dtype=np.float64)


def _render_component(state: Mapping[str, np.ndarray], fragments: Mapping[str, Any],
                      forge: Mapping[str, Any], component_index: int,
                      rng: np.random.Generator, image_size: tuple[int, int]
                      ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    from ..observe.imaging import ImagingSpec, apply_imaging_chain
    from ..observe.render import (BACKEND_SOFTWARE, LightSpec, MaterialSpec, RenderSpec,
                                  Scene, render_view)
    from ..schemas.runtime import ViewFrame

    width, height = map(int, image_size)
    if width < 16 or height < 16 or width * height > _MAX_IMAGE_PIXELS:
        _invalid("observation resolution is outside the render budget", field="image_size",
                 measurements={"width": width, "height": height,
                               "max_pixels": _MAX_IMAGE_PIXELS})
    record = fragments["components"][component_index]
    face_ids = np.asarray(record["face_indices"], dtype=np.int64)
    faces = np.asarray(state["triangles_native"], dtype=np.int32)[face_ids]
    rest_m = np.asarray(state["rest_nodes_m"], dtype=np.float64)
    current_m = np.asarray(state["current_nodes_m"], dtype=np.float64)
    rest_mm = rest_m * 1000.0
    current_mm = current_m * 1000.0
    colors = np.asarray(state["face_color_linear_rgb"], dtype=np.float32)[face_ids]
    regions = np.asarray(state["face_region_code"], dtype=np.uint8)[face_ids]
    recipe = _native_material(forge)[1]
    material = forge["material"]
    appearance = material.get("appearance", {}) if isinstance(material, Mapping) else {}
    roughness = np.full(face_ids.size, float(appearance.get("roughness", 0.78)), dtype=np.float32)
    scene = Scene(
        name="native_cohesive_surface",
        vertices=current_mm,
        faces=faces.astype(np.int32),
        surface_tag=np.asarray(state["face_kind"], dtype=np.int16)[face_ids],
        material=MaterialSpec(colors, roughness),
        face_id=face_ids.astype(np.int32),
        meta={"coordinate_units": "mm", "appearance_boundary": "PRIVATE_RENDER_CALL_ONLY"},
    )
    palette = dict(recipe["palette_linear_rgb"])
    sampler = _RestWorldZAppearanceSampler(
        faces=faces.astype(np.int64), rest_xyz_mm=rest_mm,
        face_regions=regions.astype(np.int64), palette=palette,
        bands=list(recipe["bands"]),
        target_regions=frozenset(int(x) for x in recipe["target_region_codes"]),
    )
    node_ids = np.asarray(record["native_node_ids"], dtype=np.int64)
    component_points = current_mm[node_ids]
    center = component_points.mean(axis=0)
    radius = float(np.linalg.norm(component_points - center, axis=1).max(initial=1.0))
    # A new proper object-to-sensor frame is drawn for every view. The transform stays offline.
    rotation = _proper_rotation(rng)
    distance_mm = max(2.8 * radius, 15.0)
    target_center = np.asarray([0.0, 0.0, distance_mm], dtype=np.float64)
    translation_mm = target_center - rotation @ center
    object_pose = np.eye(4, dtype=np.float64)
    object_pose[:3, :3] = rotation
    object_pose[:3, 3] = translation_mm
    focal_px = float(min(width, height) * 0.95)
    K = np.asarray([[focal_px, 0.0, (width - 1.0) / 2.0],
                    [0.0, focal_px, (height - 1.0) / 2.0],
                    [0.0, 0.0, 1.0]], dtype=np.float64)
    frame = ViewFrame(
        view_id="anonymous_sensor_view", K=K, T_WC=np.eye(4, dtype=np.float64),
        image_size=(width, height), profile_id="native_cohesive_sensor_sim",
        tier="SIMULATED", u_position_mm=0.0, working_distance_mm=distance_mm,
        focus_setting="fixed_synthetic", source_kind="SENSOR_SIM",
        meta={"focal_length_mm": 4.0, "f_number": 8.0},
    )
    light = LightSpec(direction=np.asarray([0.28, -0.38, -1.0], dtype=np.float64),
                      color=np.ones(3, dtype=np.float64),
                      ambient=np.asarray([0.25, 0.25, 0.25], dtype=np.float64))
    render_spec = RenderSpec(supersample=1, near_mm=0.5,
                             far_mm=distance_mm + 3.0 * radius,
                             max_pixels=_MAX_IMAGE_PIXELS,
                             focal_length_mm=4.0, f_number=8.0)
    rendered = render_view(scene, frame, light=light, spec=render_spec,
                           object_pose=object_pose, backend=BACKEND_SOFTWARE,
                           _appearance_sampler=sampler)
    imaged = apply_imaging_chain(
        rendered.rgb_linear, K=K, dist=None, uncertain_mask=rendered.uncertain_mask,
        depth_z=rendered.depth_z, focus_distance_mm=distance_mm,
        rng=rng, spec=ImagingSpec(response="SRGB", bit_depth=8, encode="NONE",
                                  sensor_noise_enabled=False),
    )
    depth_m = np.asarray(rendered.depth_z, dtype=np.float32) / np.float32(1000.0)
    visible = (np.asarray(rendered.id_map) >= 0) & (np.asarray(rendered.visibility) > 0) \
        & np.isfinite(depth_m) & ~np.asarray(rendered.uncertain_mask, dtype=bool)
    depth_m = np.where(visible, depth_m, np.nan).astype(np.float32)
    normals, normal_valid = _depth_normals(depth_m, K, visible)
    pixels_yx = np.argwhere(visible)
    if pixels_yx.shape[0] < 8:
        _invalid("sensor render produced too few unambiguous visible samples",
                 field="observation.visible_points",
                 measurements={"component_index": component_index,
                               "visible_points": int(pixels_yx.shape[0])})
    pixels_yx = pixels_yx[rng.permutation(pixels_yx.shape[0])]
    ys, xs = pixels_yx[:, 0], pixels_yx[:, 1]
    z = depth_m[ys, xs].astype(np.float64)
    point_xyz = np.stack([(xs - K[0, 2]) * z / K[0, 0],
                          (ys - K[1, 2]) * z / K[1, 1], z], axis=1)
    rendered_face = np.asarray(rendered.id_map, dtype=np.int64)[ys, xs]
    # The renderer returns native/global face IDs, never a fabricated volume-cell label.
    world_points_mm = point_xyz * 1000.0
    native_pose_points_mm = (world_points_mm - translation_mm[None, :]) @ rotation
    per_point_bary = np.empty((ys.size, 3), dtype=np.float64)
    for row, global_face in enumerate(rendered_face.tolist()):
        per_point_bary[row] = _barycentric(
            native_pose_points_mm[row], current_mm[faces[np.flatnonzero(face_ids == global_face)[0]]])
    source_nodes = np.asarray(state["native_to_source"], dtype=np.int64)
    point_native_nodes = np.asarray(state["triangles_native"], dtype=np.int64)[rendered_face]
    target_current = np.einsum("ni,nij->nj", per_point_bary,
                               current_m[point_native_nodes])
    target_rest = np.einsum("ni,nij->nj", per_point_bary,
                            rest_m[point_native_nodes])
    target_velocity = np.einsum("ni,nij->nj", per_point_bary,
                                np.asarray(state["velocity_mps"])[point_native_nodes])
    target_velocity_sensor = _rotate_vectors_to_sensor(target_velocity, rotation)
    face_kind = np.asarray(state["face_kind"], dtype=np.uint8)[rendered_face]
    face_parent = np.asarray(state["face_parent_id"], dtype=np.int32)[rendered_face]
    face_component = np.asarray(state["face_component"], dtype=np.int32)[rendered_face]
    normals_valid = normal_valid[ys, xs]
    offset_features = {
        "rgb_u8": np.asarray(imaged.image, dtype=np.uint8),
        "depth_m": depth_m,
        "point_xyz_sensor_m": point_xyz.astype(np.float32),
        "normal_sensor": normals[ys, xs].astype(np.float32),
        "normal_valid": normals_valid.astype(bool),
    }
    offset_targets = {
        "point_pixel_xy": np.stack([xs, ys], axis=1).astype(np.int32),
        "point_face_index": rendered_face.astype(np.int32),
        "point_component_index": face_component,
        "point_surface_kind": face_kind,
        "point_parent_facet_id": face_parent,
        "point_native_node_ids": point_native_nodes.astype(np.int32),
        "point_source_node_ids": source_nodes[point_native_nodes].astype(np.int64),
        "point_barycentric": per_point_bary,
        "point_rest_position_m": target_rest,
        "point_current_position_m": target_current,
        "point_velocity_mps": target_velocity,
        "point_velocity_sensor_mps": target_velocity_sensor,
        "view_face_id_map": np.asarray(rendered.id_map, dtype=np.int32),
        "view_rotation_native_to_sensor": rotation,
        "view_translation_native_to_sensor_m": (translation_mm / 1000.0),
        "view_intrinsics_px": K,
        "view_component_index": np.asarray(component_index, dtype=np.int32),
    }
    return offset_features, offset_targets


def _write_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    with path.open("wb") as stream:
        np.savez_compressed(stream, **{key: np.asarray(value) for key, value in arrays.items()})


def _source_for_export(source_dir: Path) -> tuple[dict[str, Any], dict[str, np.ndarray],
                                                  dict[str, Any], dict[str, Any], dict[str, bytes]]:
    manifest, manifest_raw = _read_json(_contained_file(source_dir, "manifest.json", "manifest.json"),
                                        "manifest.json")
    source_manifest, state, fragments, forge, _case = _source_record(
        source_dir, manifest, manifest_raw)
    # Retain the complete byte-verified packet, not only the arrays needed for rendering.
    # This gives offline reviewers the exact run/artifact ancestry behind each observation.
    raw_files = {"source_packet/manifest.json": manifest_raw}
    for source_name in sorted(source_manifest["files"]):
        raw_files[f"source_packet/{source_name}"] = _contained_file(
            source_dir, source_name, f"manifest.files.{source_name}").read_bytes()
    return source_manifest, state, fragments, forge, raw_files


def export_native_cohesive_dataset(
    source_dir: str | os.PathLike[str], output_dir: str | os.PathLike[str], *, seed: int,
    views_per_component: int = 3, image_size: tuple[int, int] = (96, 96),
    physical_control_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, render, and write a research-only RGB-D/point-cloud dataset.

    Sensor-space image and point arrays contain no native IDs or labels. Exact component,
    surface, ancestry, transform, point-permutation, and physics records stay in the offline
    target/truth payloads. Every view receives an independent proper object-to-sensor frame.
    """
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or int(seed) < 0:
        _invalid("seed must be a non-negative integer", field="seed")
    if isinstance(views_per_component, bool) or not isinstance(views_per_component, int) \
            or not 1 <= views_per_component <= 16:
        _invalid("views_per_component must be an integer in [1,16]", field="views_per_component")
    source_root = _root(source_dir, "native cohesive source packet")
    source_report = validate_native_cohesive_fragments(source_root)
    source_manifest, state, fragments, forge, raw_files = _source_for_export(source_root)
    physics_review = _source_physics_review(
        source_manifest, source_report["source"]["frozen_case_sha256"],
        physical_control_review)
    width, height = map(int, image_size)
    if width * height > _MAX_IMAGE_PIXELS:
        _invalid("observation resolution exceeds the render budget", field="image_size")
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite native cohesive dataset: {output}")
    if output.resolve(strict=False) == source_root or source_root in output.resolve(strict=False).parents:
        _invalid("dataset output may not be inside the source packet", field="output_dir")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        rng = np.random.default_rng(int(seed))
        feature_views: list[dict[str, np.ndarray]] = []
        target_views: list[dict[str, np.ndarray]] = []
        for component_index in range(len(fragments["components"])):
            for _view in range(views_per_component):
                feature, target = _render_component(state, fragments, forge,
                                                    component_index, rng, (width, height))
                feature_views.append(feature)
                target_views.append(target)
        point_counts = np.asarray([view["point_xyz_sensor_m"].shape[0]
                                    for view in feature_views], dtype=np.int64)
        offsets = np.concatenate([np.zeros(1, dtype=np.int64), np.cumsum(point_counts)])
        features = {
            "rgb_u8": np.stack([view["rgb_u8"] for view in feature_views]).astype(np.uint8),
            "depth_m": np.stack([view["depth_m"] for view in feature_views]).astype(np.float32),
            "point_xyz_sensor_m": np.concatenate(
                [view["point_xyz_sensor_m"] for view in feature_views]).astype(np.float32),
            "normal_sensor": np.concatenate(
                [view["normal_sensor"] for view in feature_views]).astype(np.float32),
            "normal_valid": np.concatenate(
                [view["normal_valid"] for view in feature_views]).astype(bool),
            "view_point_offsets": offsets.astype(np.int64),
        }
        targets: dict[str, np.ndarray] = {key: np.array(value, copy=True)
                                          for key, value in state.items()}
        point_keys = tuple(key for key in target_views[0]
                           if key.startswith("point_"))
        for key in point_keys:
            targets[key] = np.concatenate([view[key] for view in target_views], axis=0)
        view_keys = tuple(key for key in target_views[0] if key.startswith("view_"))
        for key in view_keys:
            targets[key] = np.stack([view[key] for view in target_views], axis=0)
        targets["view_point_offsets"] = offsets.astype(np.int64)
        features_path = stage / "research_features.npz"
        target_path = stage / "offline_targets.npz"
        _write_npz(features_path, features)
        _write_npz(target_path, targets)
        truth_root = stage / "offline_truth"
        truth_root.mkdir()
        for name, raw in raw_files.items():
            truth_path = truth_root / PurePosixPath(name)
            truth_path.parent.mkdir(parents=True, exist_ok=True)
            truth_path.write_bytes(raw)
        files: dict[str, dict[str, Any]] = {}
        for relative in ("research_features.npz", "offline_targets.npz",
                         *(f"offline_truth/{name}" for name in sorted(raw_files))):
            path = stage / relative
            files[relative] = {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
        recipe = forge["ornament"]["recipe"]
        manifest: dict[str, Any] = {
            "schema": DATASET_SCHEMA,
            "status": "RESEARCH_ONLY_UNCALIBRATED",
            "output_kind": "SYNTHETIC_SENSOR_RGBD_CLOSED_FRAGMENT_RESEARCH_DATASET",
            "seed": int(seed),
            "counts": {"components": len(fragments["components"]),
                       "views": len(feature_views), "points": int(point_counts.sum()),
                       "tets": int(state["tets"].shape[0]),
                       "native_boundary_faces": int(state["triangles_native"].shape[0]),
                       "native_cohesive_facets": source_report["counts"]["native_cohesive_facets"],
                       "recomputed_failed_facets": source_report["counts"]["recomputed_failed_facets"],
                       "qp_samples_with_both_failure_criteria": source_report["counts"][
                           "qp_samples_with_both_failure_criteria"],
                       "qp_sample_count": source_report["counts"]["qp_sample_count"]},
            "source": source_report["source"],
            "source_packet_schema": SOURCE_SCHEMA,
            "source_physics_review": physics_review,
            "source_group": {
                "source_group_id": f"native-cohesive-{source_report['source']['frozen_case_sha256']}",
                "parent_case_sha256": source_report["source"]["frozen_case_sha256"],
                "simulation_event_id": source_report["source"]["run_receipt_sha256"],
                "split": "UNASSIGNED_RESEARCH",
                "split_policy": "KEEP_ALL_VIEWS_AND_FRAGMENTS_FROM_SOURCE_GROUP_TOGETHER",
                "training_or_performance_pass": "NOT_RUN",
            },
            "qualification": {
                "native_topology": "CLOSED_NATIVE_BOUNDARIES_VALIDATED",
                "fracture_origin": "PREINSERTED_WEAK_SEAM",
                "material_calibration_status": "UNCALIBRATED",
                "physical_control_status": physics_review["physical_control_status"],
                "physical_pass": False,
                "production_a12_complete": False,
                "relation_labels": "NOT_GENERATED",
                "pretrain_eligible": False,
                "deployment_eligible": False,
                "rig_obtainable": False,
                "rig_obtainability_status": "IDEAL_SOFTWARE_RGBD_RESEARCH_PROXY_NOT_RIG_VALIDATED",
                "split": "UNASSIGNED_RESEARCH",
                "outstanding": ["material calibration", "mesh sensitivity",
                                "homogeneous fracture-path validation", "contact validation"],
            },
            "appearance": {"pattern_id": str(recipe.get("pattern_id", "unspecified")),
                           "recipe_coordinate_map": str(recipe["coordinate_map"]),
                           "painted_region_codes": [1],
                           "render_sampling": "PRIVATE_CONTINUOUS_GLOBAL_REST_Z_BAND_ADAPTER",
                           "region_codes": {"outer": 1, "inner": 2, "rim": 3,
                                            "failed_cohesive_crack": 255}},
            "research_features": {
                "schema": FEATURE_SCHEMA, "file": "research_features.npz",
                "arrays": sorted(features), "access": "SYNTHETIC_OBSERVABLES_ONLY",
                "sensor_channels": ["RGB", "depth", "camera_frame_point_cloud",
                                    "depth_estimated_normals"],
                "rig_obtainable": False,
                "sensor_model": "IDEAL_SOFTWARE_RGBD; CAMERA_FRAME_XYZ_IS_BACKPROJECTED_FROM_DEPTH; NO_CAPTURE_NOISE_OR_RIG_VALIDATION",
                "contains_native_identity": False, "contains_rest_coordinates": False,
                "contains_damage_or_velocity": False, "contains_ancestry_or_labels": False,
                "contains_transform_truth": False,
                "point_order": "INDEPENDENT_RANDOM_PERMUTATION_PER_VIEW",
                "sensor_frame": "INDEPENDENT_RANDOM_PROPER_FRAME_PER_VIEW",
                "renderer": "synlab.observe.render.render_view (SOFTWARE_RASTERIZER)",
                "observation_model": "synlab.observe.imaging.apply_imaging_chain; synthetic RGB-D",
            },
            "offline_targets": {
                "schema": TARGET_SCHEMA, "file": "offline_targets.npz",
                "arrays": sorted(targets), "access": "OFFLINE_ONLY",
                "contains_native_identity": True, "contains_rest_current_state": True,
                "contains_velocity": True, "contains_component_and_face_ancestry": True,
                "contains_view_transforms_and_feature_alignment": True,
                "point_position_frame": "NATIVE_SOURCE_WORLD_METRES",
                "point_velocity_mps_frame": "NATIVE_SOURCE_WORLD",
                "point_velocity_sensor_mps_frame": "PER_VIEW_RANDOM_SENSOR_FRAME",
                "alignment": "view_point_offsets + point_pixel_xy + point face/barycentric ancestry",
            },
            "files": files,
        }
        manifest["manifest_sha256"] = _manifest_digest(manifest)
        (stage / "manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
        load_native_cohesive_dataset(stage)
        if output.exists():
            raise FileExistsError(f"refusing to overwrite native cohesive dataset: {output}")
        stage.rename(output)
        return manifest
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


@dataclass(frozen=True, slots=True)
class NativeCohesiveDataset:
    manifest: Mapping[str, Any]
    research_features: Mapping[str, np.ndarray]
    offline_targets: Mapping[str, np.ndarray]

    def aligned_targets(self) -> dict[str, np.ndarray]:
        """Return offline per-point labels in the same anonymous point-row order."""
        keys = ("point_surface_kind", "point_parent_facet_id", "point_component_index",
                "point_source_node_ids", "point_barycentric", "point_velocity_mps",
                "point_velocity_sensor_mps")
        return {key: self.offline_targets[key] for key in keys}


def _load_npz_verified(path: Path, record: Mapping[str, Any], field: str
                       ) -> dict[str, np.ndarray]:
    if path.stat().st_size != record.get("bytes") or _sha256_file(path) != record.get("sha256"):
        _invalid("research dataset file bytes or SHA-256 do not match its manifest", field=field)
    return _load_npz(path, field)


def _validate_export_alignment(features: Mapping[str, np.ndarray], targets: Mapping[str, np.ndarray],
                               manifest: Mapping[str, Any], root: Path) -> None:
    if set(features) != _FEATURE_KEYS:
        _invalid("research features contain fields outside the strict sensory allowlist",
                 field="research_features.npz", measurements={"keys": sorted(features)})
    source_keys = _STATE_KEYS | (_OPTIONAL_STATE_KEYS & set(targets))
    target_required = source_keys | {
        "point_pixel_xy", "point_face_index", "point_component_index", "point_surface_kind",
        "point_parent_facet_id", "point_native_node_ids", "point_source_node_ids",
        "point_barycentric", "point_rest_position_m", "point_current_position_m",
        "point_velocity_mps", "point_velocity_sensor_mps", "view_face_id_map",
        "view_rotation_native_to_sensor",
        "view_translation_native_to_sensor_m", "view_intrinsics_px", "view_component_index",
        "view_point_offsets",
    }
    if set(targets) != target_required:
        _invalid("offline target arrays do not match their registered schema",
                 field="offline_targets.npz", measurements={"missing": sorted(target_required - set(targets)),
                                                              "unknown": sorted(set(targets) - target_required)})
    rgb = np.asarray(features["rgb_u8"])
    depth = np.asarray(features["depth_m"])
    points = np.asarray(features["point_xyz_sensor_m"])
    normals = np.asarray(features["normal_sensor"])
    normal_valid = np.asarray(features["normal_valid"])
    offsets = np.asarray(features["view_point_offsets"])
    if rgb.dtype != np.uint8 or rgb.ndim != 4 or rgb.shape[-1] != 3:
        _invalid("RGB feature tensor must be uint8 (V,H,W,3)", field="rgb_u8")
    views, height, width = rgb.shape[:3]
    if depth.dtype != np.float32 or depth.shape != (views, height, width) \
            or np.isinf(depth).any() or np.any(depth[np.isfinite(depth)] <= 0.0):
        _invalid("depth feature tensor must be positive camera-Z metres or NaN background",
                 field="depth_m")
    if points.dtype != np.float32 or points.ndim != 2 or points.shape[1] != 3 \
            or not np.isfinite(points).all():
        _invalid("observed point cloud must be finite float32 camera-frame metres",
                 field="point_xyz_sensor_m")
    if normals.dtype != np.float32 or normals.shape != points.shape \
            or not np.isfinite(normals).all() or normal_valid.dtype != np.bool_ \
            or normal_valid.shape != (points.shape[0],):
        _invalid("depth-derived normals and validity must align with point-cloud rows",
                 field="normal_sensor/normal_valid")
    if offsets.dtype != np.int64 or offsets.shape != (views + 1,) or offsets[0] != 0 \
            or offsets[-1] != points.shape[0] or np.any(np.diff(offsets) < 8):
        _invalid("per-view point offsets must partition all anonymous points", field="view_point_offsets")
    target_offsets = np.asarray(targets["view_point_offsets"])
    if not np.array_equal(offsets, target_offsets):
        _invalid("feature and target point permutations do not align", field="view_point_offsets")

    node_count = int(np.asarray(targets["rest_nodes_m"]).shape[0])
    triangle = _int_array(np.asarray(targets["triangles_native"]), "triangles_native", 2)
    face_component = _int_array(np.asarray(targets["face_component"]), "face_component", 1)
    face_kind = _int_array(np.asarray(targets["face_kind"]), "face_kind", 1)
    face_parent = _int_array(np.asarray(targets["face_parent_id"]), "face_parent_id", 1)
    native_to_source = _int_array(np.asarray(targets["native_to_source"]), "native_to_source", 1)
    if triangle.shape[1:] != (3,) or np.any(triangle < 0) or np.any(triangle >= node_count):
        _invalid("offline native triangles have invalid node indices", field="triangles_native")
    rotation = np.asarray(targets["view_rotation_native_to_sensor"])
    translation = np.asarray(targets["view_translation_native_to_sensor_m"])
    intrinsics = np.asarray(targets["view_intrinsics_px"])
    face_map = np.asarray(targets["view_face_id_map"])
    comp_view = _int_array(np.asarray(targets["view_component_index"]), "view_component_index", 1)
    if rotation.dtype != np.float64 or rotation.shape != (views, 3, 3) \
            or translation.dtype != np.float64 or translation.shape != (views, 3) \
            or intrinsics.dtype != np.float64 or intrinsics.shape != (views, 3, 3) \
            or face_map.dtype != np.int32 or face_map.shape != (views, height, width) \
            or comp_view.shape != (views,):
        _invalid("offline view-frame targets do not align with observation views",
                 field="offline view arrays")
    if not all(np.isfinite(value).all() for value in (rotation, translation, intrinsics)):
        _invalid("offline view transforms must be finite", field="offline view arrays")
    gram = rotation @ np.swapaxes(rotation, 1, 2)
    if not np.allclose(gram, np.eye(3)[None, :, :], rtol=0.0, atol=1e-9) \
            or not np.allclose(np.linalg.det(rotation), 1.0, rtol=0.0, atol=1e-9):
        _invalid("native-to-sensor transforms must be proper rotations",
                 field="view_rotation_native_to_sensor")
    if np.any(face_map < -1) or np.any(face_map >= triangle.shape[0]):
        _invalid("offline face maps contain unknown global native face indices",
                 field="view_face_id_map")
    if np.any((face_map >= 0) & (face_component[np.maximum(face_map, 0)] !=
                                 np.broadcast_to(comp_view[:, None, None], face_map.shape))):
        _invalid("rendered face maps cross fragment components", field="view_face_id_map")

    n_points = points.shape[0]
    for key, shape in (("point_pixel_xy", (n_points, 2)), ("point_face_index", (n_points,)),
                       ("point_component_index", (n_points,)), ("point_surface_kind", (n_points,)),
                       ("point_parent_facet_id", (n_points,)), ("point_native_node_ids", (n_points, 3)),
                       ("point_source_node_ids", (n_points, 3)), ("point_barycentric", (n_points, 3)),
                       ("point_rest_position_m", (n_points, 3)),
                       ("point_current_position_m", (n_points, 3)),
                       ("point_velocity_mps", (n_points, 3)),
                       ("point_velocity_sensor_mps", (n_points, 3))):
        if np.asarray(targets[key]).shape != shape:
            _invalid("per-point offline target does not align with the anonymous cloud",
                     field=key, measurements={"expected": list(shape),
                                              "actual": list(np.asarray(targets[key]).shape)})
    pixel_xy = _int_array(np.asarray(targets["point_pixel_xy"]), "point_pixel_xy", 2)
    point_face = _int_array(np.asarray(targets["point_face_index"]), "point_face_index", 1)
    point_component = _int_array(np.asarray(targets["point_component_index"]),
                                 "point_component_index", 1)
    point_nodes = _int_array(np.asarray(targets["point_native_node_ids"]),
                             "point_native_node_ids", 2)
    bary = _finite_array(targets["point_barycentric"], "point_barycentric", (n_points, 3))
    if np.any(pixel_xy[:, 0] < 0) or np.any(pixel_xy[:, 0] >= width) \
            or np.any(pixel_xy[:, 1] < 0) or np.any(pixel_xy[:, 1] >= height) \
            or np.any(point_face < 0) or np.any(point_face >= triangle.shape[0]) \
            or np.any(point_nodes < 0) or np.any(point_nodes >= node_count):
        _invalid("offline point-to-image/native alignment contains out-of-range indices",
                 field="point_pixel_xy/point_face_index/point_native_node_ids")
    if not np.allclose(bary.sum(axis=1), 1.0, rtol=0.0, atol=1e-7) \
            or np.any(bary < -1e-7) or np.any(bary > 1.0 + 1e-7):
        _invalid("point-to-face barycentric coordinates are invalid", field="point_barycentric")
    if not np.array_equal(point_nodes, triangle[point_face]):
        _invalid("point face ancestry disagrees with native boundary triangles",
                 field="point_native_node_ids")
    if not np.array_equal(point_component, face_component[point_face]) \
            or not np.array_equal(np.asarray(targets["point_surface_kind"], dtype=np.int64),
                                  face_kind[point_face]) \
            or not np.array_equal(np.asarray(targets["point_parent_facet_id"], dtype=np.int64),
                                  face_parent[point_face]) \
            or not np.array_equal(np.asarray(targets["point_source_node_ids"], dtype=np.int64),
                                  native_to_source[point_nodes]):
        _invalid("offline point targets disagree with component/surface/source ancestry",
                 field="point target ancestry")
    rest_nodes = _finite_array(targets["rest_nodes_m"], "offline.rest_nodes_m")
    current_nodes = _finite_array(targets["current_nodes_m"], "offline.current_nodes_m")
    velocity = _finite_array(targets["velocity_mps"], "offline.velocity_mps")
    expected_rest = np.einsum("ni,nij->nj", bary, rest_nodes[point_nodes])
    expected_current = np.einsum("ni,nij->nj", bary, current_nodes[point_nodes])
    expected_velocity = np.einsum("ni,nij->nj", bary, velocity[point_nodes])
    if not np.allclose(targets["point_rest_position_m"], expected_rest, rtol=0.0, atol=1e-10) \
            or not np.allclose(targets["point_current_position_m"], expected_current,
                               rtol=0.0, atol=1e-10) \
            or not np.allclose(targets["point_velocity_mps"], expected_velocity,
                               rtol=0.0, atol=1e-10):
        _invalid("per-point offline targets do not match native barycentric values",
                 field="point physics alignment")
    view_rows = np.repeat(np.arange(views, dtype=np.int64), np.diff(offsets))
    expected_sensor_velocity = np.einsum(
        "nij,nj->ni", rotation[view_rows], np.asarray(targets["point_velocity_mps"]))
    if not np.allclose(targets["point_velocity_sensor_mps"], expected_sensor_velocity,
                       rtol=0.0, atol=1e-12):
        _invalid("sensor-frame velocity targets must rotate native vectors, not positions",
                 field="point_velocity_sensor_mps")
    xs, ys = pixel_xy[:, 0], pixel_xy[:, 1]
    if not np.array_equal(face_map[view_rows, ys, xs], point_face):
        _invalid("offline face IDs do not match rendered sensor pixels", field="point_face_index")
    if not np.allclose(depth[view_rows, ys, xs], points[:, 2], rtol=0.0, atol=1e-6):
        _invalid("sensor points and observed depth do not agree", field="point_xyz_sensor_m")
    for view_index in range(views):
        start, end = int(offsets[view_index]), int(offsets[view_index + 1])
        x_view, y_view = xs[start:end], ys[start:end]
        if np.unique(y_view * width + x_view).size != end - start:
            _invalid("each view point cloud must use a random permutation without duplicate pixels",
                     field="point_pixel_xy")
        z = depth[view_index, y_view, x_view]
        K = intrinsics[view_index]
        expected_sensor = np.stack([(x_view - K[0, 2]) * z / K[0, 0],
                                    (y_view - K[1, 2]) * z / K[1, 1], z], axis=1)
        if not np.allclose(points[start:end], expected_sensor, rtol=0.0, atol=1e-6):
            _invalid("point cloud must be unprojected from observable depth in sensor coordinates",
                     field="point_xyz_sensor_m")
        world_rows = (points[start:end].astype(np.float64) * 1000.0 -
                      translation[view_index][None, :] * 1000.0) @ rotation[view_index]
        if not np.allclose(world_rows / 1000.0, expected_current[start:end],
                           rtol=0.0, atol=2e-5):
            _invalid("offline random sensor frame does not align point targets to native current state",
                     field="view_rotation_native_to_sensor")
    qualification = manifest.get("qualification")
    if not isinstance(qualification, Mapping) or qualification.get("physical_pass") is not False \
            or qualification.get("pretrain_eligible") is not False \
            or qualification.get("deployment_eligible") is not False \
            or qualification.get("material_calibration_status") != "UNCALIBRATED" \
            or qualification.get("rig_obtainable") is not False \
            or qualification.get("split") != "UNASSIGNED_RESEARCH":
        _invalid("dataset qualification must remain research-only and uncalibrated",
                 field="qualification")
    source = manifest.get("source")
    physics_review = manifest.get("source_physics_review")
    if not isinstance(source, Mapping) or not isinstance(physics_review, Mapping) \
            or physics_review.get("source_case_sha256") != source.get("frozen_case_sha256") \
            or not isinstance(physics_review.get("physical_control_status"), str) \
            or qualification.get("physical_control_status") != \
            physics_review.get("physical_control_status"):
        _invalid("source physical-control caveat must bind to the frozen case and qualification",
                 field="source_physics_review/qualification.physical_control_status")
    review_origin = physics_review.get("review_origin")
    if review_origin in {"SOURCE_PACKET_QUALIFICATION", "UNREVIEWED"}:
        source_packet_manifest, _ = _read_json(
            _contained_file(root, "offline_truth/source_packet/manifest.json",
                            "source packet manifest"), "source packet manifest")
        source_qualification = source_packet_manifest.get("qualification")
        inherited_status = source_qualification.get("physical_control_status") \
            if isinstance(source_qualification, Mapping) else None
        expected_status = inherited_status if isinstance(inherited_status, str) \
            and inherited_status.strip() else "NOT_REVIEWED"
        if physics_review.get("physical_control_status") != expected_status \
                or physics_review.get("review_origin") != (
                    "SOURCE_PACKET_QUALIFICATION" if expected_status != "NOT_REVIEWED"
                    else "UNREVIEWED"):
            _invalid("packet-inherited physical-control status disagrees with source packet",
                     field="source_physics_review")
    elif review_origin != "EXPORT_CALLER_REVIEW_BOUND_TO_SOURCE_CASE":
        _invalid("physical-control review origin is unsupported",
                 field="source_physics_review.review_origin")


def load_native_cohesive_dataset(dataset_dir: str | os.PathLike[str]) -> NativeCohesiveDataset:
    """Verify hashes and load sensory features separately from offline native targets."""
    root = _root(dataset_dir, "native cohesive research dataset")
    manifest, _ = _read_json(_contained_file(root, "manifest.json", "manifest.json"),
                             "manifest.json")
    if manifest.get("schema") != DATASET_SCHEMA \
            or manifest.get("status") != "RESEARCH_ONLY_UNCALIBRATED" \
            or manifest.get("manifest_sha256") != _manifest_digest(manifest):
        _invalid("unsupported, promoted, or corrupt native cohesive dataset manifest",
                 field="manifest.schema/status/manifest_sha256")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        _invalid("dataset output files map is required", field="manifest.files")
    expected = set(files) | {"manifest.json"}
    actual = _walk_files(root)
    if actual != expected:
        _invalid("research dataset contains unregistered files", field="dataset files",
                 measurements={"expected": sorted(expected), "actual": sorted(actual)})
    for key in ("run_receipt_sha256", "frozen_case_sha256", "forge_manifest_sha256",
                "source_manifest_sha256"):
        digest = (manifest.get("source") or {}).get(key)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            _invalid("dataset source lineage must retain all source hashes", field=f"source.{key}")
    source_group = manifest.get("source_group")
    source = manifest.get("source")
    if not isinstance(source_group, Mapping) \
            or source_group.get("parent_case_sha256") != source.get("frozen_case_sha256") \
            or source_group.get("simulation_event_id") != source.get("run_receipt_sha256") \
            or source_group.get("source_group_id") != \
            f"native-cohesive-{source.get('frozen_case_sha256')}" \
            or source_group.get("split") != "UNASSIGNED_RESEARCH" \
            or source_group.get("split_policy") != \
            "KEEP_ALL_VIEWS_AND_FRAGMENTS_FROM_SOURCE_GROUP_TOGETHER" \
            or source_group.get("training_or_performance_pass") != "NOT_RUN":
        _invalid("views and fragments from one simulation must remain one unassigned source group",
                 field="source_group")
    feature_meta = manifest.get("research_features")
    target_meta = manifest.get("offline_targets")
    if not isinstance(feature_meta, Mapping) or feature_meta.get("schema") != FEATURE_SCHEMA \
            or feature_meta.get("access") != "SYNTHETIC_OBSERVABLES_ONLY" \
            or feature_meta.get("contains_native_identity") is not False \
            or feature_meta.get("contains_rest_coordinates") is not False \
            or feature_meta.get("contains_damage_or_velocity") is not False \
            or feature_meta.get("contains_ancestry_or_labels") is not False \
            or feature_meta.get("contains_transform_truth") is not False \
            or feature_meta.get("rig_obtainable") is not False \
            or feature_meta.get("sensor_model") != \
            "IDEAL_SOFTWARE_RGBD; CAMERA_FRAME_XYZ_IS_BACKPROJECTED_FROM_DEPTH; NO_CAPTURE_NOISE_OR_RIG_VALIDATION":
        _invalid("feature view must remain observable-only and anonymous", field="research_features")
    if not isinstance(target_meta, Mapping) or target_meta.get("schema") != TARGET_SCHEMA \
            or target_meta.get("access") != "OFFLINE_ONLY":
        _invalid("native truth and alignment targets must remain offline-only",
                 field="offline_targets")
    feature_rel = _safe_relative(feature_meta.get("file"), "research_features.file").as_posix()
    target_rel = _safe_relative(target_meta.get("file"), "offline_targets.file").as_posix()
    if feature_rel not in files or target_rel not in files:
        _invalid("feature/target file references must be in the manifest files map",
                 field="research_features.file/offline_targets.file")
    feature_meta_record = files[feature_rel]
    target_meta_record = files[target_rel]
    features = _load_npz_verified(_contained_file(root, feature_rel, feature_rel),
                                  feature_meta_record, feature_rel)
    targets = _load_npz_verified(_contained_file(root, target_rel, target_rel),
                                 target_meta_record, target_rel)
    if sorted(features) != feature_meta.get("arrays") or sorted(targets) != target_meta.get("arrays"):
        _invalid("array inventory does not match the declared dataset schemas",
                 field="array inventory")
    _validate_export_alignment(features, targets, manifest, root)
    return NativeCohesiveDataset(manifest=manifest, research_features=features,
                                 offline_targets=targets)


__all__ = [
    "SOURCE_SCHEMA", "DATASET_SCHEMA", "FEATURE_SCHEMA", "TARGET_SCHEMA",
    "NativeCohesiveDataset", "validate_native_cohesive_fragments",
    "export_native_cohesive_dataset", "load_native_cohesive_dataset",
]
