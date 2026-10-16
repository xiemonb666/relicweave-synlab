"""Hash-checked A12 ingest and diagnostic export for native bowl point-state runs.

This is deliberately separate from the production fragment/training pipeline.  It accepts a
verified ``forge.asset.v1`` package and a ``pgfrag.native_bowl_result.v1`` run, then emits a
research-only point-snapshot feature view plus offline physics targets.  It never turns graph
components into fragments, R2 relations, or negative labels, and it never declares PRETRAIN
eligibility.

Run with ``python -m synlab.integrations.native_bowl --help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import zipfile

import numpy as np

from ..canonical import canonical_bytes
from ..errors import ErrorCode, SynLabError
from .forge_asset import load_forge_asset


PG_RESULT_SCHEMA = "pgfrag.native_bowl_result.v1"
RUN_MANIFEST_SCHEMA = "synlab.native_bowl_run_manifest.v1"
DATASET_MANIFEST_SCHEMA = "synlab.native_bowl_research_dataset.v1"
VALIDATION_SCHEMA = "synlab.native_bowl_validation.v1"
FEATURE_VIEW_SCHEMA = "synlab.native_bowl.research_feature_view.v1"
PHYSICS_TARGET_SCHEMA = "synlab.native_bowl.physics_target.v1"

_SHA256_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_NPZ_MEMBERS = 128
_MAX_NPZ_UNCOMPRESSED_BYTES = 1024**3
_MAX_NATIVE_POINTS = 12_000
_MAX_NATIVE_STEPS = 1_000
_MAX_NATIVE_PAIRS = 2_000_000
_MAX_NATIVE_OUTPUT_BYTES = 256 * 1024**2
_MASS_RTOL = 1e-12
_ARRAYS_REQUIRED: dict[str, np.dtype[Any]] = {
    "point_id": np.dtype(np.int32),
    "x_ref_m": np.dtype(np.float64),
    "position_m": np.dtype(np.float64),
    "velocity_mps": np.dtype(np.float64),
    "damage": np.dtype(np.float32),
    "step": np.dtype(np.int32),
    "time_s": np.dtype(np.float64),
    "volume_m3": np.dtype(np.float64),
    "point_mass_kg": np.dtype(np.float64),
    "bond_i": np.dtype(np.int32),
    "bond_j": np.dtype(np.int32),
    "bond_rest_length_m": np.dtype(np.float64),
    "bond_epsilon_c": np.dtype(np.float64),
    "bond_first_break_step": np.dtype(np.int32),
    "bond_first_break_time_s": np.dtype(np.float64),
    "bond_first_break_stretch": np.dtype(np.float64),
    "bond_active_packed": np.dtype(np.uint8),
    "component_label": np.dtype(np.int32),
    "event_bond_index": np.dtype(np.int32),
    "event_step": np.dtype(np.int32),
    "event_time_s": np.dtype(np.float64),
    "event_stretch": np.dtype(np.float64),
    "event_pair_energy_J": np.dtype(np.float64),
}
_OPTIONAL_ARRAYS: dict[str, np.dtype[Any]] = {
    "native_sed_J_m3": np.dtype(np.float32),
    "acceleration_mps2": np.dtype(np.float64),
    "force_N": np.dtype(np.float64),
    "strain_energy_density_J_m3": np.dtype(np.float64),
    "kinetic_energy_J": np.dtype(np.float64),
    "pair_potential_energy_J": np.dtype(np.float64),
    "break_dissipation_cumulative_J": np.dtype(np.float64),
    "native_strain_energy_J": np.dtype(np.float64),
    "total_force_x_N": np.dtype(np.float64),
    "total_force_y_N": np.dtype(np.float64),
    "total_force_z_N": np.dtype(np.float64),
    "momentum_x_kg_m_s": np.dtype(np.float64),
    "momentum_y_kg_m_s": np.dtype(np.float64),
    "momentum_z_kg_m_s": np.dtype(np.float64),
    "angular_momentum_x_kg_m2_s": np.dtype(np.float64),
    "angular_momentum_y_kg_m2_s": np.dtype(np.float64),
    "angular_momentum_z_kg_m2_s": np.dtype(np.float64),
    "checkpoint_step": np.dtype(np.int32),
    "checkpoint_acceleration_mps2": np.dtype(np.float64),
    "checkpoint_internal_force_N": np.dtype(np.float64),
}
_FEATURE_KEYS = frozenset({"position_m"})
_FORBIDDEN_FEATURE_KEYS = frozenset({
    "point_id", "source_point_id", "feature_to_point_index", "point_order_permutation",
    "x_ref_m", "velocity_mps", "damage", "bond_i", "bond_j", "bond_active",
    "bond_active_packed",
    "bond_first_break_step", "bond_first_break_time_s", "bond_first_break_stretch",
    "event_bond_index", "event_step", "event_time_s", "event_stretch",
    "event_pair_energy_J", "component_label", "r2", "relation", "fragment_id",
    "mother_id", "object_id", "seed", "source_forge_manifest_sha256",
})


def _error(code: ErrorCode, message: str, *, field: str | None = None,
           measurements: Mapping[str, Any] | None = None) -> SynLabError:
    facts = dict(measurements or {})
    if field is not None:
        facts["field"] = field
    return SynLabError(code, message, stage="integrations.native_bowl", measurements=facts)


def _invalid(message: str, *, field: str | None = None,
             measurements: Mapping[str, Any] | None = None) -> None:
    raise _error(ErrorCode.SCHEMA_INVALID, message, field=field, measurements=measurements)


def _incomplete(message: str, *, field: str | None = None,
                 measurements: Mapping[str, Any] | None = None) -> None:
    raise _error(ErrorCode.INPUT_UNAVAILABLE, message, field=field, measurements=measurements)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _root_dir(value: str | os.PathLike[str], name: str) -> Path:
    path = Path(value)
    if path.is_symlink() or not path.is_dir():
        _incomplete(f"{name} must be an available, non-symlink directory",
                    measurements={"path": str(path)})
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        _incomplete(f"cannot resolve {name}: {exc}", measurements={"path": str(path)})


def _safe_relative(value: Any, *, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _invalid("source paths must be non-empty POSIX-relative paths", field=field,
                 measurements={"path": repr(value)})
    parts = value.split("/")
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in parts) \
            or ":" in parts[0]:
        _invalid("absolute, traversing, drive-qualified, or non-normalized path", field=field,
                 measurements={"path": value})
    return rel


def _contained_file(root: Path, value: Any, *, field: str) -> Path:
    rel = _safe_relative(value, field=field)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            _invalid("symlink source files are not allowed", field=field,
                     measurements={"path": str(rel)})
    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        _incomplete(f"source file is unavailable: {exc}", field=field,
                    measurements={"path": str(rel)})
    try:
        resolved.relative_to(root)
    except ValueError:
        _invalid("source file escapes its package root", field=field,
                 measurements={"path": str(rel)})
    if not resolved.is_file():
        _invalid("source path is not a regular file", field=field,
                 measurements={"path": str(rel)})
    return resolved


def _read_json(path: Path, *, field: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _incomplete(f"cannot read {field}: {exc}", field=field)
    if len(raw) > _MAX_JSON_BYTES:
        _invalid(f"{field} exceeds the bounded JSON size", field=field,
                 measurements={"bytes": len(raw), "max_bytes": _MAX_JSON_BYTES})
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda token: _invalid(
            f"non-finite token {token} in {field}", field=field))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _invalid(f"{field} is not valid UTF-8 JSON: {exc}", field=field)
    if not isinstance(value, dict):
        _invalid(f"{field} must be a JSON object", field=field)
    return value, raw


def _check_digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _invalid("expected a lowercase 64-character SHA-256", field=field)
    return value


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _walk_regular_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirnames):
            path = base / name
            if path.is_symlink():
                _invalid("source package contains a symlink directory",
                         measurements={"path": str(path)})
        for name in filenames:
            path = base / name
            if path.is_symlink() or not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                _invalid("source package contains a non-regular file",
                         measurements={"path": str(path)})
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _manifest_hash(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes({key: value for key, value in document.items()
                                           if key != "manifest_sha256"})).hexdigest()


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _verify_npz_container(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_NPZ_MEMBERS:
                _invalid("NPZ contains too many members", field="arrays.npz",
                         measurements={"members": len(entries)})
            total = 0
            names: set[str] = set()
            for entry in entries:
                name = entry.filename
                pure = PurePosixPath(name)
                if pure.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")) \
                        or len(pure.parts) != 1 or not name.endswith(".npy"):
                    _invalid("NPZ contains an unsafe or unexpected member name",
                             field="arrays.npz", measurements={"member": name})
                if name in names:
                    _invalid("NPZ contains a duplicate member", field="arrays.npz",
                             measurements={"member": name})
                names.add(name)
                total += entry.file_size
            if total > _MAX_NPZ_UNCOMPRESSED_BYTES:
                _invalid("NPZ uncompressed size exceeds the reader limit",
                         field="arrays.npz", measurements={"bytes": total})
    except zipfile.BadZipFile as exc:
        _invalid(f"arrays file is not a valid NPZ: {exc}", field="arrays.npz")


def _npz_arrays(path: Path) -> dict[str, np.ndarray]:
    _verify_npz_container(path)
    try:
        with np.load(path, allow_pickle=False) as archive:
            keys = set(archive.files)
            missing = sorted(set(_ARRAYS_REQUIRED) - keys)
            if missing:
                _incomplete("native PG arrays are incomplete", field="arrays.npz",
                            measurements={"missing_keys": missing})
            unknown = sorted(keys - set(_ARRAYS_REQUIRED) - set(_OPTIONAL_ARRAYS))
            if unknown:
                _invalid("native PG arrays contain unregistered keys", field="arrays.npz",
                         measurements={"unknown_keys": unknown})
            arrays = {key: np.array(archive[key], copy=True) for key in keys}
    except (OSError, ValueError, EOFError, zipfile.BadZipFile, KeyError) as exc:
        _invalid(f"cannot load native PG NPZ arrays: {exc}", field="arrays.npz")
    for key, expected_dtype in _ARRAYS_REQUIRED.items():
        if arrays[key].dtype != expected_dtype:
            _invalid("native PG array has an unexpected dtype", field=key,
                     measurements={"expected": str(expected_dtype),
                                   "actual": str(arrays[key].dtype)})
    for key, expected_dtype in _OPTIONAL_ARRAYS.items():
        if key in arrays and arrays[key].dtype != expected_dtype:
            _invalid("optional native PG audit array has an unexpected dtype", field=key,
                     measurements={"expected": str(expected_dtype),
                                   "actual": str(arrays[key].dtype)})
    packed = arrays["bond_active_packed"]
    if packed.ndim != 2:
        _invalid("packed active-graph rows must be two-dimensional byte vectors",
                 field="bond_active_packed")
    return arrays


def _unpack_active_state(packed_row: np.ndarray, bond_count: int) -> np.ndarray:
    expected_width = (bond_count + 7) // 8
    if packed_row.ndim != 1 or packed_row.shape[0] != expected_width:
        _invalid("bond_active_packed state row must have width ceil(B/8)",
                 field="bond_active_packed",
                 measurements={"shape": list(packed_row.shape), "bonds": bond_count,
                               "expected_width": expected_width})
    unpacked = np.unpackbits(packed_row, bitorder="little")
    if np.any(unpacked[bond_count:]):
        _invalid("unused packed active-graph padding bits must be zero",
                 field="bond_active_packed")
    return unpacked[:bond_count].astype(np.uint8, copy=False)


def _finite(array: np.ndarray, field: str) -> None:
    if array.dtype.kind == "f" and not np.isfinite(array).all():
        _invalid("array contains NaN or infinity", field=field)


def _validate_components(point_id: np.ndarray, bond_i: np.ndarray, bond_j: np.ndarray,
                          active: np.ndarray, labels: np.ndarray) -> None:
    point_count = int(point_id.size)
    parent = list(range(point_count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for bond_index in np.flatnonzero(active):
        union(int(bond_i[bond_index]), int(bond_j[bond_index]))
    minima: dict[int, int] = {}
    for point_index in range(point_count):
        root = find(point_index)
        source_id = int(point_id[point_index])
        minima[root] = min(minima.get(root, source_id), source_id)
    expected = np.asarray([minima[find(point_index)]
                           for point_index in range(point_count)], dtype=np.int64)
    if labels.shape != (point_count,) or not np.array_equal(
            labels.astype(np.int64, copy=False), expected):
        _invalid("component labels do not match the verified active graph", field="component_label")


def _validate_array_semantics(arrays: Mapping[str, np.ndarray], material: Mapping[str, Any],
                              geometry: Mapping[str, Any] | None = None
                              ) -> dict[str, Any]:
    for key, array in arrays.items():
        _finite(array, key)

    point_id = arrays["point_id"]
    x_ref = arrays["x_ref_m"]
    position = arrays["position_m"]
    velocity = arrays["velocity_mps"]
    damage = arrays["damage"]
    step = arrays["step"]
    time_s = arrays["time_s"]
    volume = arrays["volume_m3"]
    mass = arrays["point_mass_kg"]
    bond_i, bond_j = arrays["bond_i"], arrays["bond_j"]
    bond_count = int(bond_i.size)
    point_count = int(point_id.size)
    state_count = int(step.size)

    if point_count < 1 or state_count < 1:
        _incomplete("native run must contain at least one point and one saved state",
                    measurements={"points": point_count, "states": state_count})
    if point_count > _MAX_NATIVE_POINTS or state_count - 1 > _MAX_NATIVE_STEPS \
            or bond_count > _MAX_NATIVE_PAIRS:
        _invalid("native run exceeds the frozen point, step, or pair budget",
                 field="native run budget",
                 measurements={"points": point_count, "steps": state_count - 1,
                               "pairs": bond_count})
    if bond_i.ndim != 1 or bond_j.ndim != 1 or bond_i.shape != bond_j.shape:
        _invalid("canonical bond endpoints must be aligned one-dimensional vectors",
                 field="bond_i/bond_j")
    if point_id.shape != (point_count,) or len(np.unique(point_id)) != point_count \
            or bool(np.any(point_id < 0)):
        _invalid("point_id must be a unique, non-negative int32 vector", field="point_id")
    if x_ref.shape != (point_count, 3):
        _invalid("x_ref_m must have shape (N,3)", field="x_ref_m",
                 measurements={"shape": list(x_ref.shape), "points": point_count})
    if position.shape != (state_count, point_count, 3):
        _invalid("position_m must have shape (S,N,3)", field="position_m",
                 measurements={"shape": list(position.shape), "states": state_count,
                               "points": point_count})
    if velocity.shape != (state_count, point_count, 3):
        _invalid("velocity_mps must have shape (S,N,3)", field="velocity_mps",
                 measurements={"shape": list(velocity.shape)})
    if damage.shape != (state_count, point_count):
        _invalid("damage must have shape (S,N)", field="damage",
                 measurements={"shape": list(damage.shape)})
    if time_s.shape != (state_count,):
        _invalid("time_s must have shape (S,)", field="time_s")
    if volume.shape != (point_count,) or mass.shape != (point_count,):
        _incomplete("complete positive volume and point-mass arrays are required",
                    field="volume_m3/point_mass_kg",
                    measurements={"volume_shape": list(volume.shape),
                                  "mass_shape": list(mass.shape), "points": point_count})
    if step.ndim != 1 or step[0] != 0 or not np.array_equal(
            step.astype(np.int64), np.arange(state_count, dtype=np.int64)):
        _invalid("full native trajectory step indices must be contiguous from zero", field="step")
    if time_s[0] != 0.0:
        _invalid("full native trajectory must start at time zero", field="time_s")
    time_delta = np.diff(time_s)
    if np.any(time_delta <= 0.0):
        _invalid("time_s must be strictly increasing", field="time_s")
    if time_delta.size and not np.allclose(time_delta, time_delta[0], rtol=1e-10, atol=1e-15):
        _invalid("native full-trajectory states must use the fixed stable time step",
                 field="time_s")
    if np.any(volume <= 0.0) or np.any(mass <= 0.0):
        _invalid("point volumes and point masses must all be positive", field="volume_m3/point_mass_kg")
    if not np.allclose(position[0], x_ref, rtol=0.0, atol=1e-14):
        _invalid("initial position state must equal original reference coordinates",
                 field="position_m[0]/x_ref_m")
    if np.any(damage < -1e-7) or np.any(damage > 1.0 + 1e-7):
        _invalid("damage fractions must be in [0,1]", field="damage")
    if np.any(bond_i < 0) or np.any(bond_j >= point_count) or np.any(bond_i >= bond_j):
        _invalid("bond pairs must be 0-based canonical endpoints i<j", field="bond_i/bond_j",
                 measurements={"points": point_count})
    pairs = np.stack((bond_i, bond_j), axis=1)
    if pairs.shape[0] and np.unique(pairs, axis=0).shape[0] != bond_count:
        _invalid("bond table contains duplicate canonical pairs", field="bond_i/bond_j")
    if bond_count:
        order = np.lexsort((bond_j, bond_i))
        if not np.array_equal(order, np.arange(bond_count)):
            _invalid("bond table must be sorted by canonical endpoint pair", field="bond_i/bond_j")

    per_bond_shapes = {
        "bond_j": (bond_count,), "bond_rest_length_m": (bond_count,),
        "bond_first_break_step": (bond_count,), "bond_first_break_time_s": (bond_count,),
        "bond_first_break_stretch": (bond_count,),
    }
    for key, shape in per_bond_shapes.items():
        if arrays[key].shape != shape:
            _invalid("bond array has an invalid shape", field=key,
                     measurements={"expected": list(shape), "actual": list(arrays[key].shape)})
    active_packed = arrays["bond_active_packed"]
    if active_packed.shape != (state_count, (bond_count + 7) // 8):
        _invalid("bond_active_packed must have shape (S, ceil(B/8))",
                 field="bond_active_packed")
    if arrays["component_label"].shape != (state_count, point_count):
        _invalid("component_label must have shape (S,N)", field="component_label")
    if arrays["bond_rest_length_m"].shape != (bond_count,) \
            or np.any(arrays["bond_rest_length_m"] <= 0.0):
        _invalid("bond rest lengths must be positive", field="bond_rest_length_m")

    first_step = arrays["bond_first_break_step"]
    first_time = arrays["bond_first_break_time_s"]
    first_stretch = arrays["bond_first_break_stretch"]
    event_index = arrays["event_bond_index"]
    event_step = arrays["event_step"]
    event_time = arrays["event_time_s"]
    event_stretch = arrays["event_stretch"]
    event_count = int(event_index.size)
    if event_index.ndim != 1 or any(arrays[key].shape != (event_count,) for key in (
            "event_step", "event_time_s", "event_stretch", "event_pair_energy_J")):
        _invalid("event arrays must be aligned one-dimensional vectors", field="event_*")
    if "event_pair_energy_J" in arrays:
        if arrays["event_pair_energy_J"].shape != (event_count,) \
                or np.any(arrays["event_pair_energy_J"] < -1e-12):
            _invalid("event pair-energy audit must be a non-negative E-vector",
                     field="event_pair_energy_J")
    if arrays["bond_epsilon_c"].shape != (bond_count,) \
            or np.any(arrays["bond_epsilon_c"] <= 0.0):
        _invalid("bond_epsilon_c must be a positive value for every listed bond",
                 field="bond_epsilon_c")
    if "native_sed_J_m3" in arrays and arrays["native_sed_J_m3"].shape != (state_count, point_count):
        _invalid("native_sed_J_m3 must have shape (S,N)", field="native_sed_J_m3")
    energy_keys = {
        "kinetic_energy_J", "pair_potential_energy_J", "break_dissipation_cumulative_J",
        "native_strain_energy_J", "total_force_x_N", "total_force_y_N", "total_force_z_N",
        "momentum_x_kg_m_s", "momentum_y_kg_m_s", "momentum_z_kg_m_s",
        "angular_momentum_x_kg_m2_s", "angular_momentum_y_kg_m2_s",
        "angular_momentum_z_kg_m2_s",
    }
    for key in energy_keys & arrays.keys():
        if arrays[key].shape != (state_count,):
            _invalid("per-state ledger arrays must have shape (S,)", field=key,
                     measurements={"expected": [state_count], "actual": list(arrays[key].shape)})
    checkpoint_keys = {"checkpoint_step", "checkpoint_acceleration_mps2",
                       "checkpoint_internal_force_N"}
    present_checkpoints = checkpoint_keys & arrays.keys()
    if present_checkpoints and present_checkpoints != checkpoint_keys:
        _incomplete("checkpoint diagnostics must include step, acceleration, and internal force",
                    field="checkpoint diagnostics",
                    measurements={"missing": sorted(checkpoint_keys - present_checkpoints)})
    if present_checkpoints:
        checkpoint_step = arrays["checkpoint_step"]
        checkpoint_count = int(checkpoint_step.size)
        if checkpoint_step.ndim != 1 or np.any(checkpoint_step < 0) \
                or np.any(checkpoint_step >= state_count) \
                or (checkpoint_count > 1 and np.any(np.diff(checkpoint_step) <= 0)):
            _invalid("checkpoint steps must be increasing indices in the saved trajectory",
                     field="checkpoint_step")
        for key in ("checkpoint_acceleration_mps2", "checkpoint_internal_force_N"):
            if arrays[key].shape != (checkpoint_count, point_count, 3):
                _invalid("checkpoint point vectors must have shape (C,N,3)", field=key)

    active_zero = _unpack_active_state(active_packed[0], bond_count)
    if bond_count and not np.all(active_zero == 1):
        _invalid("listed initial bonds must be active at the first saved state; pre-excluded bonds belong outside the event table",
                 field="bond_active_packed")
    if event_count and (np.any(event_index < 0) or np.any(event_index >= bond_count)):
        _invalid("event_bond_index is outside the canonical bond table", field="event_bond_index")
    if event_count and len(np.unique(event_index)) != event_count:
        _invalid("a canonical bond may have only one first-break event", field="event_bond_index")
    if event_count and (np.any(event_time <= time_s[0]) or np.any(event_time > time_s[-1])
                        or np.any(event_step <= step[0]) or np.any(event_step >= state_count)):
        _invalid("break events must fall after the initial state and within the saved run horizon",
                 field="event_time_s/event_step")
    if event_count:
        order = np.lexsort((event_index, event_time))
        if not np.array_equal(order, np.arange(event_count)):
            _invalid("break events must be sorted by time then bond index", field="event_time_s")

    degree = np.bincount(np.concatenate((bond_i, bond_j)), minlength=point_count)
    broken_degree = np.zeros(point_count, dtype=np.int64)
    first_inactive_state = np.full(bond_count, -1, dtype=np.int64)
    active = active_zero
    expected_damage = np.zeros(point_count, dtype=np.float64)
    if not np.allclose(damage[0], expected_damage, rtol=0.0, atol=1e-6):
        _invalid("initial damage must be zero before any bond has broken", field="damage")
    _validate_components(point_id, bond_i, bond_j, active, arrays["component_label"][0])
    for state_index in range(1, state_count):
        next_active = _unpack_active_state(active_packed[state_index], bond_count)
        if np.any(next_active > active):
            _invalid("a broken bond becomes active again", field="bond_active_packed",
                     measurements={"state_index": state_index})
        newly_broken = np.flatnonzero((active == 1) & (next_active == 0))
        if newly_broken.size:
            first_inactive_state[newly_broken] = state_index
            broken_points = np.concatenate((bond_i[newly_broken], bond_j[newly_broken]))
            broken_degree += np.bincount(broken_points, minlength=point_count)
            expected_damage = np.zeros(point_count, dtype=np.float64)
            nonzero_degree = degree > 0
            expected_damage[nonzero_degree] = (broken_degree[nonzero_degree]
                                               / degree[nonzero_degree])
            if not np.allclose(damage[state_index], expected_damage, rtol=0.0, atol=1e-6):
                _invalid("damage fractions do not match the inactive-neighbor fraction in the active graph",
                         field="damage", measurements={"state_index": state_index})
            _validate_components(point_id, bond_i, bond_j, next_active,
                                 arrays["component_label"][state_index])
        else:
            if not np.allclose(damage[state_index], damage[state_index - 1],
                               rtol=0.0, atol=1e-7):
                _invalid("damage changed without an active-graph event", field="damage",
                         measurements={"state_index": state_index})
            if not np.array_equal(arrays["component_label"][state_index],
                                  arrays["component_label"][state_index - 1]):
                _invalid("component labels changed without an active-graph event",
                         field="component_label", measurements={"state_index": state_index})
        active = next_active

    event_for_bond = {int(bond): i for i, bond in enumerate(event_index)}
    for bond in range(bond_count):
        has_event = bond in event_for_bond
        recorded_step = int(first_step[bond])
        if not has_event:
            if recorded_step != -1 or first_time[bond] != -1.0 or first_stretch[bond] != -1.0 \
                    or first_inactive_state[bond] >= 0:
                _invalid("unbroken bonds must use -1 event sentinels and remain active",
                         field="bond_first_break_step", measurements={"bond_index": bond})
            continue
        event_row = event_for_bond[bond]
        event_state = int(event_step[event_row])
        if recorded_step != event_state or first_inactive_state[bond] != event_state \
                or not math.isclose(float(first_time[bond]), float(event_time[event_row]),
                                    rel_tol=0.0, abs_tol=1e-12) \
                or not math.isclose(float(first_stretch[bond]), float(event_stretch[event_row]),
                                    rel_tol=1e-9, abs_tol=1e-12):
            _invalid("bond first-break fields disagree with the event log and active graph",
                     field="bond_first_break_step", measurements={"bond_index": bond})
        if event_stretch[event_row] <= 0.0:
            _invalid("event stretch must be positive", field="event_stretch",
                     measurements={"bond_index": bond})
        if not math.isclose(float(time_s[event_state]), float(event_time[event_row]),
                            rel_tol=0.0, abs_tol=1e-12):
            _invalid("event time must match the saved full-trajectory state at event_step",
                     field="event_time_s", measurements={"bond_index": bond})
        if active_packed[event_state, bond // 8] & (1 << (bond % 8)) \
                or not (active_packed[event_state - 1, bond // 8] & (1 << (bond % 8))):
            _invalid("first-break active state must switch off at event_step",
                     field="bond_active_packed", measurements={"bond_index": bond})

    rho = material.get("rho_kg_m3")
    calibration = material.get("calibration_status")
    reported_mass = material.get("total_mass_kg")
    if isinstance(rho, bool) or not isinstance(rho, (int, float)) \
            or not math.isfinite(float(rho)) or float(rho) <= 0:
        _incomplete("material density is missing or invalid; point mass cannot be validated",
                    field="material.rho_kg_m3")
    if calibration != "UNVALIDATED_PROTOTYPE":
        _invalid("native bowl material must retain its unvalidated prototype status",
                 field="material.calibration_status",
                 measurements={"actual": calibration})
    if isinstance(reported_mass, bool) or not isinstance(reported_mass, (int, float)) \
            or not math.isfinite(float(reported_mass)) \
            or float(reported_mass) <= 0:
        _incomplete("reported total mass is required for complete mass accounting",
                    field="material.total_mass_kg")
    expected_point_mass = float(rho) * volume
    if not np.allclose(mass, expected_point_mass, rtol=_MASS_RTOL, atol=1e-24):
        _invalid("point_mass_kg does not match rho_kg_m3 * volume_m3", field="point_mass_kg",
                 measurements={"rho_kg_m3": float(rho)})
    mass_sum = float(np.sum(mass, dtype=np.float64))
    if not math.isclose(mass_sum, float(reported_mass), rel_tol=_MASS_RTOL, abs_tol=1e-18):
        _invalid("sum(point_mass_kg) does not match reported total_mass_kg",
                 field="material.total_mass_kg",
                 measurements={"point_mass_sum_kg": mass_sum,
                               "reported_mass_kg": float(reported_mass)})

    if geometry is not None:
        try:
            outer_radius = float(geometry["outer_radius_m"])
            inner_radius = float(geometry["inner_radius_m"])
            center = np.asarray(geometry["center_m"], dtype=np.float64)
            spacing = float(geometry["h_m"])
            delta = float(geometry["delta_m"])
            declared_points = int(geometry["n_points"])
            analytic_volume = float(geometry["analytic_volume_m3"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            _invalid("native geometry record is incomplete", field="geometry",
                     measurements={"error": str(exc)})
        if center.shape != (3,) or not np.isfinite(center).all() \
                or not all(math.isfinite(value) and value > 0.0 for value in (
                    outer_radius, inner_radius, spacing, delta, analytic_volume)) \
                or not 0.0 < inner_radius < outer_radius or declared_points != point_count:
            _invalid("native geometry record has invalid bounds or point count", field="geometry")
        expected_analytic_volume = 2.0 * math.pi / 3.0 * (outer_radius**3 - inner_radius**3)
        if not math.isclose(analytic_volume, expected_analytic_volume,
                            rel_tol=1e-12, abs_tol=1e-24):
            _invalid("reported analytic bowl volume does not match its SI radii",
                     field="geometry.analytic_volume_m3")
        if not np.allclose(volume, spacing**3, rtol=1e-12, atol=1e-24):
            _invalid("point volumes must match the declared h^3 quadrature",
                     field="volume_m3")
        centered = x_ref - center[None, :]
        radial = np.linalg.norm(centered, axis=1)
        if np.any(radial < inner_radius - 1e-12) or np.any(radial > outer_radius + 1e-12) \
                or np.any(x_ref[:, 2] > center[2] + 1e-12):
            _invalid("point reference coordinates fall outside the lower hemispherical shell",
                     field="x_ref_m")
        if bond_count:
            direction = x_ref[bond_j] - x_ref[bond_i]
            direction_squared = np.einsum("ij,ij->i", direction, direction)
            if np.any(direction_squared <= 0.0):
                _invalid("bond endpoint reference coordinates must be distinct",
                         field="bond_i/bond_j")
            closest_t = np.clip(-np.einsum("ij,ij->i", x_ref[bond_i] - center, direction)
                                / direction_squared, 0.0, 1.0)
            closest = x_ref[bond_i] + closest_t[:, None] * direction - center
            closest_radius = np.linalg.norm(closest, axis=1)
            if np.any(closest_radius < inner_radius - 1e-12):
                _invalid("retained initial bond segment enters the inner spherical void",
                         field="bond_i/bond_j")
            geometric_length = np.linalg.norm(direction, axis=1)
            if not np.allclose(arrays["bond_rest_length_m"], geometric_length,
                               rtol=1e-10, atol=1e-14):
                _invalid("bond rest lengths do not match original reference coordinates",
                         field="bond_rest_length_m")
        elastic_modulus = float(material.get("E_pa", float("nan")))
        poisson = float(material.get("nu", float("nan")))
        fracture_energy = float(material.get("Gc_j_m2", float("nan")))
        if not all(math.isfinite(value) and value > 0.0 for value in
                   (elastic_modulus, fracture_energy)) or not (-1.0 < poisson < 0.5):
            _incomplete("native material elasticity values are missing or invalid",
                        field="material.E_pa/nu/Gc_j_m2")
        bulk_modulus = elastic_modulus / (3.0 * (1.0 - 2.0 * poisson))
        expected_critical_stretch = math.sqrt(5.0 * fracture_energy /
                                              (9.0 * bulk_modulus * delta))
        if not np.allclose(arrays["bond_epsilon_c"], expected_critical_stretch,
                           rtol=1e-10, atol=1e-14):
            _invalid("bond critical stretch does not match the declared SI material and horizon",
                     field="bond_epsilon_c")
        if event_count:
            event_bonds = event_index.astype(np.int64, copy=False)
            event_states = event_step.astype(np.int64, copy=False)
            event_left = bond_i[event_bonds]
            event_right = bond_j[event_bonds]
            event_delta = position[event_states, event_right] - position[event_states, event_left]
            event_length = np.linalg.norm(event_delta, axis=1)
            reconstructed_stretch = (event_length - arrays["bond_rest_length_m"][event_bonds]) \
                / arrays["bond_rest_length_m"][event_bonds]
            if not np.allclose(event_stretch, reconstructed_stretch, rtol=1e-8, atol=1e-12):
                _invalid("event stretch does not match the recorded trajectory state",
                         field="event_stretch")
            bond_constant = 18.0 * bulk_modulus / (math.pi * delta**4)
            reconstructed_energy = 0.5 * bond_constant * volume[event_left] * volume[event_right] \
                * arrays["bond_rest_length_m"][event_bonds] * reconstructed_stretch**2
            if not np.allclose(arrays["event_pair_energy_J"], reconstructed_energy,
                               rtol=1e-7, atol=1e-24):
                _invalid("event pair energy does not match the native BB pair potential",
                         field="event_pair_energy_J")

    return {
        "points": point_count,
        "states": state_count,
        "bonds": bond_count,
        "break_events": event_count,
        "broken_bonds": int(np.count_nonzero(first_step >= 0)),
        "point_volume_sum_m3": float(np.sum(volume, dtype=np.float64)),
        "point_mass_sum_kg": mass_sum,
        "reported_mass_kg": float(reported_mass),
        "mass_accounting": "COMPLETE_MODEL_INPUT_ACCOUNTING",
        "density_calibration": "UNVALIDATED_PROTOTYPE",
        "component_graph_match": True,
        "damage_graph_match": True,
    }


def _read_native_run(vf_dir: str | os.PathLike[str], pg_dir: str | os.PathLike[str], *,
                     expected_vf_manifest_sha256: str | None = None,
                     expected_pg_result_sha256: str | None = None
                     ) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    vf_root = _root_dir(vf_dir, "VesselForge package")
    pg_root = _root_dir(pg_dir, "PG native result")
    asset = load_forge_asset(vf_root)
    vf_manifest_path = _contained_file(vf_root, "manifest.json", field="vf.manifest")
    vf_manifest_bytes = vf_manifest_path.read_bytes()
    vf_hash = hashlib.sha256(vf_manifest_bytes).hexdigest()
    vf_manifest, _ = _read_json(vf_manifest_path, field="vf.manifest")
    if vf_hash != asset.manifest_sha256:
        _invalid("Forge manifest digest changed during validation", field="vf.manifest_sha256")
    if expected_vf_manifest_sha256 is not None \
            and _check_digest(expected_vf_manifest_sha256, field="expected_vf_manifest_sha256") != vf_hash:
        _invalid("Forge manifest SHA-256 does not match the requested digest",
                 field="expected_vf_manifest_sha256")

    result_path = _contained_file(pg_root, "result.json", field="pg.result.json")
    result, result_raw = _read_json(result_path, field="pg.result.json")
    pg_result_hash = hashlib.sha256(result_raw).hexdigest()
    if expected_pg_result_sha256 is not None \
            and _check_digest(expected_pg_result_sha256, field="expected_pg_result_sha256") != pg_result_hash:
        _invalid("PG result metadata SHA-256 does not match the requested digest",
                 field="expected_pg_result_sha256")
    if result.get("schema") != PG_RESULT_SCHEMA:
        _invalid("unsupported PG native-bowl result schema", field="pg.result.schema",
                 measurements={"actual": result.get("schema"), "expected": PG_RESULT_SCHEMA})
    if result.get("status") != "PASS":
        _incomplete("PG native-bowl result did not complete with PASS status", field="pg.result.status",
                    measurements={"actual": result.get("status")})
    source_forge_hash = _check_digest(result.get("source_forge_manifest_sha256"),
                                      field="source_forge_manifest_sha256")
    if source_forge_hash != vf_hash:
        _invalid("PG run is not bound to this exact Forge manifest", field="source_forge_manifest_sha256",
                 measurements={"expected_vf_manifest_sha256": vf_hash,
                               "actual": source_forge_hash})

    material = result.get("material")
    if not isinstance(material, Mapping):
        _incomplete("PG material record is missing", field="material")
    arrays_record = result.get("arrays")
    if not isinstance(arrays_record, Mapping):
        _incomplete("PG result must declare its arrays.npz payload", field="arrays")
    if arrays_record.get("format") not in {"npz", "numpy_npz"}:
        _invalid("PG arrays payload format must be NPZ", field="arrays.format")
    arrays_path = _contained_file(pg_root, arrays_record.get("path"), field="arrays.path")
    declared_arrays_hash = _check_digest(arrays_record.get("sha256"), field="arrays.sha256")
    declared_arrays_bytes = arrays_record.get("bytes")
    if isinstance(declared_arrays_bytes, bool) or not isinstance(declared_arrays_bytes, int) \
            or declared_arrays_bytes < 0 or declared_arrays_bytes > _MAX_NATIVE_OUTPUT_BYTES:
        _invalid("arrays.bytes must be a non-negative integer", field="arrays.bytes")
    actual_arrays_bytes = arrays_path.stat().st_size
    actual_arrays_hash = _sha256_file(arrays_path)
    if actual_arrays_bytes != declared_arrays_bytes or actual_arrays_hash != declared_arrays_hash:
        _invalid("PG arrays payload size or SHA-256 does not match result.json",
                 field="arrays", measurements={"declared_bytes": declared_arrays_bytes,
                                                "actual_bytes": actual_arrays_bytes,
                                                "declared_sha256": declared_arrays_hash,
                                                "actual_sha256": actual_arrays_hash})

    # The PG case's prototype mechanics are frozen by, and must exactly match,
    # the material values in this byte-hash-bound Forge manifest.
    forge_material = vf_manifest.get("material")
    forge_mechanics = forge_material.get("mechanics") if isinstance(forge_material, Mapping) else None
    if not isinstance(forge_material, Mapping) or not isinstance(forge_mechanics, Mapping):
        _incomplete("Forge source material mechanics are missing", field="vf.material.mechanics")
    if forge_material.get("calibration_status") != "UNVALIDATED_PROTOTYPE":
        _invalid("Forge source material must remain UNVALIDATED_PROTOTYPE",
                 field="vf.material.calibration_status")
    for key in ("rho_kg_m3", "E_pa", "nu", "Gc_j_m2"):
        source_value = forge_mechanics.get(key)
        native_value = material.get(key)
        if isinstance(source_value, bool) or not isinstance(source_value, (int, float)) \
                or not math.isfinite(float(source_value)):
            _incomplete("Forge source material value is missing or invalid",
                        field=f"vf.material.mechanics.{key}")
        if isinstance(native_value, bool) or not isinstance(native_value, (int, float)) \
                or not math.isfinite(float(native_value)):
            _incomplete("PG native material value is missing or invalid", field=f"material.{key}")
        if float(source_value) != float(native_value):
            _invalid("PG material value does not match the hash-bound Forge source",
                     field=f"material.{key}",
                     measurements={"forge_value": float(source_value),
                                   "pg_value": float(native_value)})
    if material.get("calibration_status") != forge_material.get("calibration_status"):
        _invalid("PG material calibration status does not match the Forge source",
                 field="material.calibration_status")
    if material.get("model_mass_status") != \
            "DISCRETE_MODEL_MASS_FROM_APPROXIMATE_H3_VOLUMES_NOT_MEASURED":
        _invalid("PG point mass must be described as approximate model mass",
                 field="material.model_mass_status")

    source_asset = result.get("source_forge_asset")
    if not isinstance(source_asset, Mapping) \
            or source_asset.get("manifest_schema") != "forge.asset.v1" \
            or source_asset.get("geometry_scope") != "geometry_only" \
            or source_asset.get("declared_geometry_status") != "PASS":
        _invalid("PG result must preserve its geometry-only Forge source declaration",
                 field="source_forge_asset")

    forge_spec = vf_manifest.get("provenance", {}).get("spec") \
        if isinstance(vf_manifest.get("provenance"), Mapping) else None
    pg_geometry = result.get("geometry")
    if not isinstance(forge_spec, Mapping) or not isinstance(pg_geometry, Mapping):
        _incomplete("source bowl geometry parameters are missing", field="geometry")
    if forge_spec.get("shape", forge_spec.get("prototype_form")) not in {
            "concentric_lower_hemisphere", "concentric_lower_hemisphere_bowl"}:
        _invalid("Forge source is not the registered spherical bowl prototype",
                 field="vf.provenance.spec.shape")
    if pg_geometry.get("shape") != "concentric_lower_hemisphere_shell":
        _invalid("PG geometry must identify the concentric lower-hemisphere shell",
                 field="geometry.shape")
    try:
        geometry_pairs = (
            ("outer_radius_m", float(forge_spec["outer_radius_mm"]) * 1e-3),
            ("inner_radius_m", float(forge_spec["inner_radius_mm"]) * 1e-3),
        )
        center_mm = np.asarray(forge_spec["center_xyz_mm"], dtype=np.float64)
        center_m = np.asarray(pg_geometry["center_m"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        _invalid("source bowl geometry is incomplete", field="geometry", measurements={"error": str(exc)})
    if center_mm.shape != (3,) or center_m.shape != (3,) or not np.isfinite(center_mm).all() \
            or not np.isfinite(center_m).all():
        _invalid("bowl center must be a finite three-vector in source mm and native m",
                 field="geometry.center_m")
    for key, expected in geometry_pairs:
        actual = pg_geometry.get(key)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) \
                or not math.isfinite(float(actual)) or float(actual) != expected:
            _invalid("PG bowl radius does not match the hash-bound Forge source",
                     field=f"geometry.{key}",
                     measurements={"forge_value_m": expected, "pg_value_m": actual})
    if not np.array_equal(center_m, center_mm * 1e-3):
        _invalid("PG bowl center does not match the hash-bound Forge source",
                 field="geometry.center_m")
    native_result_meta = result.get("results")
    if not isinstance(native_result_meta, Mapping):
        _incomplete("PG run summary is missing", field="results")
    persistent_bytes = native_result_meta.get("persistent_output_bytes")
    if isinstance(persistent_bytes, bool) or not isinstance(persistent_bytes, int) \
            or not 0 <= persistent_bytes <= _MAX_NATIVE_OUTPUT_BYTES:
        _invalid("PG persistent output must remain within the frozen 256 MiB budget",
                 field="results.persistent_output_bytes")
    if "peak_raw_plus_final_bytes" in native_result_meta:
        peak_bytes = native_result_meta["peak_raw_plus_final_bytes"]
        if isinstance(peak_bytes, bool) or not isinstance(peak_bytes, int) \
                or not 0 <= peak_bytes <= _MAX_NATIVE_OUTPUT_BYTES:
            _invalid("PG raw-plus-final peak must remain within the frozen 256 MiB budget",
                     field="results.peak_raw_plus_final_bytes")
    pg_files = _walk_regular_files(pg_root)
    actual_tree_bytes = sum(path.stat().st_size for path in pg_files)
    if actual_tree_bytes > _MAX_NATIVE_OUTPUT_BYTES:
        _invalid("actual PG package files exceed the frozen 256 MiB budget",
                 field="pg package bytes",
                 measurements={"bytes": actual_tree_bytes,
                               "max_bytes": _MAX_NATIVE_OUTPUT_BYTES,
                               "files": len(pg_files)})
    if persistent_bytes > actual_tree_bytes:
        _invalid("producer persistent-byte declaration exceeds the actual PG package",
                 field="results.persistent_output_bytes",
                 measurements={"declared_bytes": persistent_bytes,
                               "actual_bytes": actual_tree_bytes})

    source_receipts = result.get("source_receipts")
    if not isinstance(source_receipts, list) or not source_receipts:
        _incomplete("PG result must carry source-byte receipts", field="source_receipts")
    verified_source_receipts: list[dict[str, Any]] = []
    seen_source_paths: set[str] = set()
    for index, record in enumerate(source_receipts):
        if not isinstance(record, Mapping):
            _invalid("each source receipt must be an object", field=f"source_receipts[{index}]")
        rel_path = record.get("path")
        if not isinstance(rel_path, str) or rel_path in seen_source_paths:
            _invalid("source receipts must have unique normalized paths",
                     field=f"source_receipts[{index}].path")
        seen_source_paths.add(rel_path)
        source_path = _contained_file(pg_root, rel_path,
                                      field=f"source_receipts[{index}].path")
        expected_hash = _check_digest(record.get("sha256"),
                                      field=f"source_receipts[{index}].sha256")
        expected_bytes = record.get("bytes")
        actual_bytes = source_path.stat().st_size
        actual_hash = _sha256_file(source_path)
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) \
                or expected_bytes < 0 or actual_bytes != expected_bytes \
                or actual_hash != expected_hash:
            _invalid("PG source receipt does not match its source snapshot bytes",
                     field=f"source_receipts[{index}]",
                     measurements={"path": rel_path, "expected_bytes": expected_bytes,
                                   "actual_bytes": actual_bytes,
                                   "expected_sha256": expected_hash,
                                   "actual_sha256": actual_hash})
        verified_source_receipts.append({"path": rel_path, "sha256": actual_hash,
                                         "bytes": actual_bytes})

    outputs = result.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        _incomplete("PG output digest list is required", field="outputs")
    verified_outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(outputs):
        if not isinstance(record, Mapping):
            _invalid("each PG output entry must be an object", field=f"outputs[{index}]")
        rel_path = record.get("path")
        if not isinstance(rel_path, str) or rel_path in seen:
            _invalid("PG outputs must have unique normalized paths", field=f"outputs[{index}].path")
        seen.add(rel_path)
        file_path = _contained_file(pg_root, rel_path, field=f"outputs[{index}].path")
        expected_hash = _check_digest(record.get("sha256"), field=f"outputs[{index}].sha256")
        expected_bytes = record.get("bytes")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
            _invalid("output bytes must be a non-negative integer", field=f"outputs[{index}].bytes")
        actual_bytes = file_path.stat().st_size
        actual_hash = _sha256_file(file_path)
        if actual_bytes != expected_bytes or actual_hash != expected_hash:
            _invalid("PG output digest does not match result.json", field=f"outputs[{index}]",
                     measurements={"path": rel_path, "expected_bytes": expected_bytes,
                                   "actual_bytes": actual_bytes,
                                   "expected_sha256": expected_hash,
                                   "actual_sha256": actual_hash})
        verified_outputs.append({"path": rel_path, "sha256": actual_hash, "bytes": actual_bytes})
    matching = [item for item in verified_outputs if item["path"] == arrays_record.get("path")]
    if len(matching) != 1 or matching[0]["sha256"] != declared_arrays_hash \
            or matching[0]["bytes"] != declared_arrays_bytes:
        _invalid("arrays payload must also appear identically in the output digest list",
                 field="outputs")

    arrays = _npz_arrays(arrays_path)
    counts = _validate_array_semantics(arrays, material, pg_geometry)
    solver = result.get("solver")
    if not isinstance(solver, Mapping) or isinstance(solver.get("steps"), bool) \
            or solver.get("steps") != counts["states"] - 1:
        _invalid("PG solver step count must match the complete saved trajectory",
                 field="solver.steps",
                 measurements={"saved_steps": counts["states"] - 1,
                               "declared_steps": (solver.get("steps")
                                                  if isinstance(solver, Mapping) else None)})
    summary_expectations = {
        "point_count": counts["points"],
        "canonical_initial_pair_count": counts["bonds"],
        "broken_pair_count": counts["break_events"],
    }
    for key, expected in summary_expectations.items():
        actual = native_result_meta.get(key)
        if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
            _invalid("PG result counts do not match the verified arrays",
                     field=f"results.{key}",
                     measurements={"expected": expected, "actual": actual})
    reported_mass_sum = native_result_meta.get("reported_point_mass_sum_kg")
    if isinstance(reported_mass_sum, bool) or not isinstance(reported_mass_sum, (int, float)) \
            or not math.isclose(float(reported_mass_sum), counts["point_mass_sum_kg"],
                                rel_tol=_MASS_RTOL, abs_tol=1e-18):
        _invalid("PG summary mass does not match complete point mass coverage",
                 field="results.reported_point_mass_sum_kg")
    report = {
        "schema": VALIDATION_SCHEMA,
        "status": "SOURCE_VERIFIED_DIAGNOSTIC_ONLY",
        "source": {
            "vf_manifest_sha256": vf_hash,
            "pg_result_sha256": pg_result_hash,
            "pg_arrays_sha256": actual_arrays_hash,
            "pg_result_schema": PG_RESULT_SCHEMA,
            "source_forge_manifest_sha256": source_forge_hash,
        },
        "counts": {**counts,
                    "pg_package_file_count": len(pg_files),
                    "pg_package_total_bytes": actual_tree_bytes,
                    "pg_source_receipt_count": len(verified_source_receipts)},
        "qualification": {
            "dataset_kind": "NATIVE_BOWL_POINT_STATE_DIAGNOSTIC",
            "feature_view": "RESEARCH_ONLY",
            "observation_kind": "SIMULATION_POINT_SNAPSHOT",
            "rig_obtainable": False,
            "production_physical_pass": False,
            "physical_validation_status": "UNKNOWN",
            "fracture_surface_status": "UNKNOWN",
            "physical_fragments_status": "UNKNOWN",
            "r2_status": "UNKNOWN",
            "pretrain_eligible": False,
        },
        "outputs_verified": verified_outputs,
    }
    return result, arrays, report


def validate_native_bowl_run(
    vf_dir: str | os.PathLike[str],
    pg_dir: str | os.PathLike[str],
    *,
    expected_vf_manifest_sha256: str | None = None,
    expected_pg_result_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate VF/PG package hashes, native point arrays, event history, and active graph.

    Passing this validator certifies source binding and internal dataset consistency only.  It
    does not certify a crack surface, physical fragments, R2 labels, calibration, or deployment.
    """
    _, _, report = _read_native_run(
        vf_dir, pg_dir,
        expected_vf_manifest_sha256=expected_vf_manifest_sha256,
        expected_pg_result_sha256=expected_pg_result_sha256,
    )
    return report


def _copy_package_tree(source: Path, destination: Path) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=False)
    files = _walk_regular_files(source)
    copied: list[dict[str, Any]] = []
    for source_file in files:
        rel = source_file.relative_to(source)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
        copied.append({"path": rel.as_posix(), "bytes": target.stat().st_size,
                       "sha256": _sha256_file(target)})
    return copied


def _assert_separate_destination(output: Path, *sources: Path) -> None:
    out_abs = output.resolve(strict=False)
    for source in sources:
        src_abs = source.resolve(strict=True)
        if _path_is_within(out_abs, src_abs) or _path_is_within(src_abs, out_abs):
            _invalid("output and input package directories must be disjoint",
                     measurements={"output": str(out_abs), "input": str(src_abs)})


def ingest_native_bowl_run(
    vf_dir: str | os.PathLike[str],
    pg_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    expected_vf_manifest_sha256: str | None = None,
    expected_pg_result_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify and copy one source run into a new, immutable A12 diagnostic package.

    Existing output directories are never overwritten.  Source files are copied only after
    validation, then validated again from the package copy before its manifest is committed.
    """
    vf_root = _root_dir(vf_dir, "VesselForge package")
    pg_root = _root_dir(pg_dir, "PG native result")
    output = Path(output_dir)
    _assert_separate_destination(output, vf_root, pg_root)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing native-bowl output: {output}")
    _, _, report = _read_native_run(
        vf_root, pg_root,
        expected_vf_manifest_sha256=expected_vf_manifest_sha256,
        expected_pg_result_sha256=expected_pg_result_sha256,
    )
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=parent))
    try:
        sources = stage / "sources"
        vf_copy = sources / "forge_asset"
        pg_copy = sources / "pg_run"
        vf_files = _copy_package_tree(vf_root, vf_copy)
        pg_files = _copy_package_tree(pg_root, pg_copy)
        # Re-read the copied producer records: the committed package must describe the bytes it
        # actually contains, not a source directory that could change during the copy.
        copied_report = validate_native_bowl_run(vf_copy, pg_copy)
        if copied_report["source"] != report["source"]:
            _invalid("source package changed while the ingest copy was being made")
        manifest: dict[str, Any] = {
            "schema": RUN_MANIFEST_SCHEMA,
            "status": "SOURCE_VERIFIED_DIAGNOSTIC_ONLY",
            "source": copied_report["source"],
            "counts": copied_report["counts"],
            "qualification": copied_report["qualification"],
            "source_files": {
                "forge_asset": vf_files,
                "pg_run": pg_files,
            },
            "source_roots": {
                "forge_asset": "sources/forge_asset",
                "pg_run": "sources/pg_run",
            },
            "limitations": [
                "SIMULATION_POINT_SNAPSHOT is a research feature view, not a rig-obtainable scan.",
                "velocity, damage, IDs, reference positions, events, active graph, and component labels are offline physics targets.",
                "No crack surface, physical fragments, R2, negative labels, or PRETRAIN eligibility is inferred.",
                "Material density is an unvalidated prototype input; complete point-mass accounting is not measured mass validation.",
            ],
        }
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        _write_json(stage / "run_manifest.json", manifest)
        # Verify the copy and manifest before exposing the final output path.
        _verify_manifest_files(stage, manifest, file_list_key="source_files")
        validate_ingested_native_bowl_run(stage)
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing native-bowl output: {output}")
        stage.rename(output)
        return manifest
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def _verify_manifest_files(root: Path, manifest: Mapping[str, Any], *,
                           file_list_key: str) -> None:
    groups = manifest.get(file_list_key)
    if not isinstance(groups, Mapping):
        _invalid("file digest groups are missing", field=file_list_key)
    if file_list_key == "source_files" and set(groups) != {"forge_asset", "pg_run"}:
        _invalid("ingest source file groups must contain exactly Forge and PG packages",
                 field="source_files")
    seen_paths: set[str] = set()
    for group_name, records in groups.items():
        if not isinstance(records, list):
            _invalid("file digest group must be a list", field=f"{file_list_key}.{group_name}")
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                _invalid("file digest record must be an object", field=f"{file_list_key}.{group_name}[{index}]")
            rel = _safe_relative(record.get("path"), field=f"{file_list_key}.{group_name}[{index}].path")
            full_relative = (f"sources/{group_name}/{rel.as_posix()}"
                             if file_list_key == "source_files" else rel.as_posix())
            if full_relative in seen_paths:
                _invalid("file inventory contains a duplicate path", field=file_list_key,
                         measurements={"path": full_relative})
            seen_paths.add(full_relative)
            path = _contained_file(root, f"sources/{group_name}/{rel.as_posix()}"
                                   if file_list_key == "source_files" else rel.as_posix(),
                                   field=f"{file_list_key}.{group_name}[{index}].path")
            expected_hash = _check_digest(record.get("sha256"), field=f"{file_list_key}.{group_name}[{index}].sha256")
            expected_bytes = record.get("bytes")
            if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) \
                    or expected_bytes < 0:
                _invalid("file byte count must be a non-negative integer", field=file_list_key)
            if path.stat().st_size != expected_bytes or _sha256_file(path) != expected_hash:
                _invalid("copied file does not match its manifest digest", field=file_list_key,
                         measurements={"path": str(path)})
    if file_list_key == "source_files":
        sources_root = root / "sources"
        if sources_root.is_symlink() or not sources_root.is_dir():
            _invalid("ingest sources directory is missing or unsafe", field="sources")
        actual_paths = {f"sources/{path.relative_to(sources_root).as_posix()}"
                        for path in _walk_regular_files(sources_root)}
        if actual_paths != seen_paths:
            _invalid("source file inventory does not exactly cover copied source bytes",
                     field="source_files",
                     measurements={"unlisted": sorted(actual_paths - seen_paths),
                                   "missing": sorted(seen_paths - actual_paths)})


def validate_ingested_native_bowl_run(run_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Revalidate the immutable source package and its manifest after ingest."""
    root = _root_dir(run_dir, "A12 native-bowl ingest package")
    manifest_path = _contained_file(root, "run_manifest.json", field="run_manifest.json")
    manifest, _ = _read_json(manifest_path, field="run_manifest.json")
    if manifest.get("schema") != RUN_MANIFEST_SCHEMA:
        _invalid("unsupported A12 native-bowl run manifest", field="run_manifest.schema")
    if manifest.get("status") != "SOURCE_VERIFIED_DIAGNOSTIC_ONLY":
        _invalid("ingest package status must remain diagnostic-only", field="run_manifest.status")
    if manifest.get("manifest_sha256") != _manifest_hash(manifest):
        _invalid("ingest manifest SHA-256 mismatch", field="run_manifest.manifest_sha256")
    _verify_manifest_files(root, manifest, file_list_key="source_files")
    source_roots = manifest.get("source_roots")
    if not isinstance(source_roots, Mapping):
        _invalid("ingest source roots are missing", field="source_roots")
    vf_relative = _safe_relative(source_roots.get("forge_asset"), field="source_roots.forge_asset")
    pg_relative = _safe_relative(source_roots.get("pg_run"), field="source_roots.pg_run")
    vf_root = _contained_file(root, f"{vf_relative.as_posix()}/manifest.json", field="source_roots.forge_asset")
    pg_result = _contained_file(root, f"{pg_relative.as_posix()}/result.json", field="source_roots.pg_run")
    report = validate_native_bowl_run(vf_root.parent, pg_result.parent)
    if report["source"] != manifest.get("source") or report["counts"] != manifest.get("counts"):
        _invalid("revalidated source evidence differs from ingest manifest", field="source/counts")
    if report["qualification"] != manifest.get("qualification"):
        _invalid("ingest qualification differs from the fail-closed source result",
                 field="qualification")
    return report


def _proper_rotation(rng: np.random.Generator) -> np.ndarray:
    """Sample a deterministic proper rotation from the supplied RNG."""
    u1, u2, u3 = rng.random(3)
    x = math.sqrt(1.0 - u1) * math.sin(2.0 * math.pi * u2)
    y = math.sqrt(1.0 - u1) * math.cos(2.0 * math.pi * u2)
    z = math.sqrt(u1) * math.sin(2.0 * math.pi * u3)
    w = math.sqrt(u1) * math.cos(2.0 * math.pi * u3)
    return np.asarray([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def _save_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    with path.open("wb") as stream:
        np.savez_compressed(stream, **arrays)


@dataclass(frozen=True, slots=True)
class NativeBowlDataset:
    """Small loader result for the research feature view and offline physics targets."""

    manifest: Mapping[str, Any]
    research_features: Mapping[str, np.ndarray]
    physics_targets: Mapping[str, np.ndarray]

    def aligned_targets(self) -> dict[str, np.ndarray]:
        """Align offline velocity/damage to feature rows for per-state diagnostics.

        Velocity is returned in the independent sensor frame of each feature snapshot;
        source ``physics_targets['velocity_mps']`` remains in the native world frame.
        Independent per-state frames and permutations do not define point tracks.
        """
        state_indices = self.physics_targets["selected_state_index"].astype(np.int64, copy=False)
        point_indices = self.physics_targets["feature_to_point_index"].astype(np.int64, copy=False)
        rotation = self.physics_targets["frame_rotation_world_to_sensor"]
        aligned_velocity_world = self.physics_targets["velocity_mps"][
            state_indices[:, None], point_indices]
        aligned_velocity = np.matmul(aligned_velocity_world, np.swapaxes(rotation, 1, 2))
        aligned_damage = self.physics_targets["damage"][state_indices[:, None], point_indices]
        if aligned_velocity.shape[:2] != point_indices.shape or aligned_damage.shape != point_indices.shape:
            _invalid("offline targets cannot be aligned to anonymous features")
        return {"velocity_mps": aligned_velocity, "damage": aligned_damage}


def export_native_bowl_dataset(
    run_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    seed: int,
    state_indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Export anonymous research coordinates and a separate offline physics-target package.

    Each state receives an independent random proper sensor frame and a fresh point permutation.
    Only current positions appear in ``research_feature_view.npz``.  Simulation timestamps,
    point IDs, reference coordinates, velocities, damage, event data, active graph, component
    labels, frame transforms, and feature-to-source alignment are saved only in
    ``physics_target.npz``.  Independent per-state frames are anonymous snapshots, not tracks.
    """
    report = validate_ingested_native_bowl_run(run_dir)
    root = Path(run_dir).resolve(strict=True)
    run_manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    pg_result_path = _contained_file(root, "sources/pg_run/result.json", field="pg.result.json")
    pg_result_raw = pg_result_path.read_bytes()
    if hashlib.sha256(pg_result_raw).hexdigest() != report["source"]["pg_result_sha256"]:
        _invalid("PG result bytes changed after run validation", field="pg.result.json")
    pg_result = json.loads(pg_result_raw.decode("utf-8"))
    arrays_record = pg_result["arrays"]
    arrays_path = _contained_file(root / "sources" / "pg_run", arrays_record["path"], field="arrays.path")
    if _sha256_file(arrays_path) != report["source"]["pg_arrays_sha256"]:
        _invalid("PG arrays bytes changed after run validation", field="arrays.npz")
    arrays = _npz_arrays(arrays_path)
    state_count, point_count = arrays["position_m"].shape[:2]
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        _invalid("seed must be a non-negative integer", field="seed")
    if state_indices is None:
        selected = np.arange(state_count, dtype=np.int64)
    else:
        selected = np.asarray(list(state_indices), dtype=np.int64)
    if selected.ndim != 1 or selected.size < 2 or np.any(selected < 0) \
            or np.any(selected >= state_count) or np.any(np.diff(selected) <= 0):
        _invalid("export requires at least two unique, increasing saved state indices",
                 field="state_indices", measurements={"states": state_count})

    output = Path(output_dir)
    _assert_separate_destination(output, root)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing native-bowl dataset: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        rng = np.random.default_rng(int(seed))
        feature_to_point = np.empty((selected.size, point_count), dtype=np.int32)
        rotations = np.empty((selected.size, 3, 3), dtype=np.float64)
        translations = np.empty((selected.size, 3), dtype=np.float64)
        feature_position = np.empty((selected.size, point_count, 3), dtype=np.float64)
        for output_state, source_state in enumerate(selected.tolist()):
            rotation = _proper_rotation(rng)
            scale = max(float(np.linalg.norm(np.ptp(arrays["position_m"][source_state], axis=0))),
                        1e-9)
            translation = rng.uniform(-scale, scale, size=3).astype(np.float64)
            permutation = rng.permutation(point_count).astype(np.int32)
            transformed = arrays["position_m"][source_state] @ rotation.T + translation
            feature_position[output_state] = transformed[permutation]
            feature_to_point[output_state] = permutation
            rotations[output_state] = rotation
            translations[output_state] = translation

        feature_arrays = {"position_m": feature_position}
        if set(feature_arrays) != _FEATURE_KEYS or set(feature_arrays) & _FORBIDDEN_FEATURE_KEYS:
            _invalid("internal feature export violates the research-view allowlist")
        _save_npz(stage / "research_feature_view.npz", feature_arrays)

        target_arrays = {key: np.array(value, copy=True) for key, value in arrays.items()}
        target_arrays.update({
            "selected_state_index": selected.astype(np.int32),
            "feature_to_point_index": feature_to_point,
            "frame_rotation_world_to_sensor": rotations,
            "frame_translation_world_to_sensor_m": translations,
        })
        _save_npz(stage / "physics_target.npz", target_arrays)

        feature_hash = _sha256_file(stage / "research_feature_view.npz")
        target_hash = _sha256_file(stage / "physics_target.npz")
        dataset_manifest: dict[str, Any] = {
            "schema": DATASET_MANIFEST_SCHEMA,
            "status": "DIAGNOSTIC_ONLY",
            "output_kind": "RESEARCH_ONLY_POINT_SNAPSHOT_DATASET_NO_SHARDS",
            "purpose": "native point-snapshot physics diagnostic; no production retrieval training",
            "source_run_manifest_sha256": run_manifest["manifest_sha256"],
            "source": report["source"],
            "seed": int(seed),
            "selected_state_index": selected.tolist(),
            "counts": {"feature_states": int(selected.size), "points_per_state": point_count,
                       "source_states": state_count, "bonds": report["counts"]["bonds"],
                       "break_events": report["counts"]["break_events"]},
            "research_feature_view": {
                "schema": FEATURE_VIEW_SCHEMA,
                "file": "research_feature_view.npz",
                "sha256": feature_hash,
                "bytes": (stage / "research_feature_view.npz").stat().st_size,
                "arrays": sorted(feature_arrays),
                "observation_kind": "SIMULATION_POINT_SNAPSHOT",
                "coordinate_frame": "INDEPENDENT_RANDOM_SENSOR_FRAME_PER_STATE",
                "point_order": "INDEPENDENT_RANDOM_PERMUTATION_PER_STATE",
                "temporal_semantics": "INDEPENDENT_SNAPSHOTS; NO SIMULATION TIME; POINTS ARE NOT TRACKED",
                "rig_obtainable": False,
                "research_only": True,
                "contains_point_identity": False,
                "contains_velocity_or_damage": False,
                "contains_events_or_graph": False,
                "contains_physics_target": False,
                "feature_allowlist": sorted(_FEATURE_KEYS),
            },
            "physics_target": {
                "schema": PHYSICS_TARGET_SCHEMA,
                "file": "physics_target.npz",
                "sha256": target_hash,
                "bytes": (stage / "physics_target.npz").stat().st_size,
                "arrays": sorted(target_arrays),
                "access": "OFFLINE_ONLY",
                "contains_point_identity": True,
                "contains_damage_velocity_events_active_graph_components": True,
                "alignment_field": "feature_to_point_index",
                "material": pg_result["material"],
                "geometry": pg_result["geometry"],
                "source_velocity_frame": "NATIVE_WORLD_FRAME",
                "aligned_velocity_frame": "INDEPENDENT_RANDOM_SENSOR_FRAME_PER_STATE",
            },
            "qualification": {
                "physical_validation_status": "UNKNOWN",
                "fracture_surface_status": "UNKNOWN",
                "physical_fragments_status": "UNKNOWN",
                "r2_status": "UNKNOWN",
                "relation_labels": "NOT_GENERATED",
                "negative_labels": "NOT_GENERATED",
                "production_physical_pass": False,
                "deployment_eligible": False,
                "pretrain_eligible": False,
            },
        }
        dataset_manifest["manifest_sha256"] = _manifest_hash(dataset_manifest)
        _write_json(stage / "dataset_manifest.json", dataset_manifest)
        # Smoke-load before committing a visible output directory.
        load_native_bowl_dataset(stage)
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing native-bowl dataset: {output}")
        stage.rename(output)
        return dataset_manifest
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def _load_npz_verified(path: Path, expected_sha256: str, *, field: str) -> dict[str, np.ndarray]:
    if _sha256_file(path) != expected_sha256:
        _invalid("dataset payload SHA-256 mismatch", field=field)
    try:
        _verify_npz_container(path)
        with np.load(path, allow_pickle=False) as archive:
            return {key: np.array(archive[key], copy=True) for key in archive.files}
    except (OSError, ValueError, EOFError) as exc:
        _invalid(f"cannot load dataset payload: {exc}", field=field)


def load_native_bowl_dataset(dataset_dir: str | os.PathLike[str]) -> NativeBowlDataset:
    """Hash-check and load a research-only point snapshot package, never a training shard."""
    root = _root_dir(dataset_dir, "native-bowl dataset")
    manifest_path = _contained_file(root, "dataset_manifest.json", field="dataset_manifest.json")
    manifest, _ = _read_json(manifest_path, field="dataset_manifest.json")
    if manifest.get("schema") != DATASET_MANIFEST_SCHEMA or manifest.get("status") != "DIAGNOSTIC_ONLY":
        _invalid("unsupported or non-diagnostic native-bowl dataset", field="dataset_manifest.schema/status")
    if manifest.get("output_kind") != "RESEARCH_ONLY_POINT_SNAPSHOT_DATASET_NO_SHARDS":
        _invalid("native bowl output must remain an observation-only research dataset",
                 field="dataset_manifest.output_kind")
    if manifest.get("manifest_sha256") != _manifest_hash(manifest):
        _invalid("dataset manifest SHA-256 mismatch", field="manifest_sha256")
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        _incomplete("source digest binding is required", field="source")
    for key in ("vf_manifest_sha256", "pg_result_sha256", "pg_arrays_sha256",
                "source_forge_manifest_sha256"):
        _check_digest(source.get(key), field=f"source.{key}")
    if source.get("source_forge_manifest_sha256") != source.get("vf_manifest_sha256"):
        _invalid("PG/VF source binding is inconsistent", field="source.source_forge_manifest_sha256")
    _check_digest(manifest.get("source_run_manifest_sha256"), field="source_run_manifest_sha256")
    qualification = manifest.get("qualification")
    if not isinstance(qualification, Mapping) \
            or any(qualification.get(key) != "UNKNOWN" for key in (
                "physical_validation_status", "fracture_surface_status",
                "physical_fragments_status", "r2_status")) \
            or qualification.get("pretrain_eligible") is not False \
            or qualification.get("deployment_eligible") is not False \
            or qualification.get("production_physical_pass") is not False \
            or qualification.get("relation_labels") != "NOT_GENERATED" \
            or qualification.get("negative_labels") != "NOT_GENERATED":
        _invalid("dataset qualification must keep physical/R2 and PRETRAIN status unpromoted",
                 field="qualification")
    feature_meta = manifest.get("research_feature_view")
    target_meta = manifest.get("physics_target")
    if not isinstance(feature_meta, Mapping) or not isinstance(target_meta, Mapping):
        _invalid("dataset must declare separate feature and physics-target views")
    if feature_meta.get("schema") != FEATURE_VIEW_SCHEMA or feature_meta.get("research_only") is not True \
            or feature_meta.get("rig_obtainable") is not False \
            or feature_meta.get("observation_kind") != "SIMULATION_POINT_SNAPSHOT" \
            or feature_meta.get("contains_point_identity") is not False \
            or feature_meta.get("contains_velocity_or_damage") is not False \
            or feature_meta.get("contains_events_or_graph") is not False \
            or feature_meta.get("contains_physics_target") is not False \
            or feature_meta.get("temporal_semantics") != \
                "INDEPENDENT_SNAPSHOTS; NO SIMULATION TIME; POINTS ARE NOT TRACKED":
        _invalid("point snapshots must remain explicitly research-only", field="research_feature_view")
    if feature_meta.get("coordinate_frame") != "INDEPENDENT_RANDOM_SENSOR_FRAME_PER_STATE" \
            or feature_meta.get("point_order") != "INDEPENDENT_RANDOM_PERMUTATION_PER_STATE":
        _invalid("feature snapshots must use independent per-state sensor frames and permutations",
                 field="research_feature_view")
    if feature_meta.get("arrays") != sorted(_FEATURE_KEYS) or set(feature_meta.get("arrays", [])) & _FORBIDDEN_FEATURE_KEYS:
        _invalid("research feature view violates the allowlist", field="research_feature_view.arrays")
    if target_meta.get("schema") != PHYSICS_TARGET_SCHEMA or target_meta.get("access") != "OFFLINE_ONLY":
        _invalid("physics targets must remain offline-only", field="physics_target")
    if target_meta.get("contains_point_identity") is not True \
            or target_meta.get("source_velocity_frame") != "NATIVE_WORLD_FRAME" \
            or target_meta.get("aligned_velocity_frame") != \
                "INDEPENDENT_RANDOM_SENSOR_FRAME_PER_STATE" \
            or not isinstance(target_meta.get("material"), Mapping) \
            or not isinstance(target_meta.get("geometry"), Mapping):
        _invalid("offline targets must declare identity and vector-frame semantics",
                 field="physics_target")
    feature_path = _contained_file(root, feature_meta.get("file"), field="research_feature_view.file")
    target_path = _contained_file(root, target_meta.get("file"), field="physics_target.file")
    for path, meta, field in ((feature_path, feature_meta, "research_feature_view"),
                              (target_path, target_meta, "physics_target")):
        if path.stat().st_size != meta.get("bytes"):
            _invalid("dataset payload byte count mismatch", field=field)
    features = _load_npz_verified(feature_path, _check_digest(feature_meta.get("sha256"), field="research_feature_view.sha256"),
                                  field="research_feature_view")
    targets = _load_npz_verified(target_path, _check_digest(target_meta.get("sha256"), field="physics_target.sha256"),
                                 field="physics_target")
    if set(features) != _FEATURE_KEYS or set(features) & _FORBIDDEN_FEATURE_KEYS:
        _invalid("research feature NPZ contains fields outside its strict allowlist",
                 field="research_feature_view.npz",
                 measurements={"keys": sorted(features)})
    required_targets = set(_ARRAYS_REQUIRED) | {
        "selected_state_index", "feature_to_point_index", "frame_rotation_world_to_sensor",
        "frame_translation_world_to_sensor_m",
    }
    if not required_targets.issubset(targets):
        _incomplete("offline physics-target NPZ is missing required source arrays",
                    field="physics_target.npz",
                    measurements={"missing": sorted(required_targets - set(targets))})
    allowed_targets = required_targets | set(_OPTIONAL_ARRAYS)
    if set(targets) - allowed_targets:
        _invalid("offline target payload contains unregistered arrays", field="physics_target.npz",
                 measurements={"unknown": sorted(set(targets) - allowed_targets)})
    for key, dtype in {**_ARRAYS_REQUIRED, **_OPTIONAL_ARRAYS}.items():
        if key in targets and targets[key].dtype != dtype:
            _invalid("offline target array has an unregistered dtype", field=f"physics_target.{key}",
                     measurements={"expected": str(dtype), "actual": str(targets[key].dtype)})
    for key, dtype in (("selected_state_index", np.dtype(np.int32)),
                       ("feature_to_point_index", np.dtype(np.int32)),
                       ("frame_rotation_world_to_sensor", np.dtype(np.float64)),
                       ("frame_translation_world_to_sensor_m", np.dtype(np.float64))):
        if targets[key].dtype != dtype:
            _invalid("offline alignment array has an unregistered dtype",
                     field=f"physics_target.{key}",
                     measurements={"expected": str(dtype), "actual": str(targets[key].dtype)})
    _validate_array_semantics(targets, target_meta["material"], target_meta["geometry"])
    if target_meta.get("arrays") != sorted(targets):
        _invalid("physics-target array inventory does not match its NPZ payload",
                 field="physics_target.arrays")
    if feature_meta.get("arrays") != sorted(features):
        _invalid("feature array inventory does not match its NPZ payload",
                 field="research_feature_view.arrays")
    if set(features) != _FEATURE_KEYS:
        _invalid("research feature NPZ contains fields outside its strict allowlist",
                 field="research_feature_view.npz",
                 measurements={"keys": sorted(features)})
    position = features["position_m"]
    selected = targets["selected_state_index"]
    point_map = targets["feature_to_point_index"]
    source_states, point_count = targets["position_m"].shape[:2]
    feature_count = int(position.shape[0]) if position.ndim >= 1 else 0
    if position.dtype != np.float64 \
            or selected.dtype != np.int32 or point_map.dtype != np.int32:
        _invalid("feature and alignment arrays must use their registered dtypes",
                 field="dataset dtypes")
    if position.ndim != 3 or position.shape[2] != 3 \
            or selected.shape != (feature_count,) or point_map.shape != position.shape[:2] \
            or position.shape[1] != point_count or feature_count < 2 \
            or np.any(selected < 0) or np.any(selected >= source_states) \
            or np.any(np.diff(selected.astype(np.int64)) <= 0):
        _invalid("feature and target dimensions do not align", field="dataset dimensions")
    if not np.isfinite(position).all():
        _invalid("research feature view contains non-finite values", field="research_feature_view")
    if point_map.dtype != np.int32 or np.any(point_map < 0) or np.any(point_map >= point_count):
        _invalid("offline feature-to-point alignment map is invalid", field="feature_to_point_index")
    if any(not np.array_equal(np.sort(row), np.arange(point_count, dtype=np.int32))
           for row in point_map):
        _invalid("each feature state must carry one complete randomized point permutation",
                 field="feature_to_point_index")
    if manifest.get("selected_state_index") != selected.astype(int).tolist():
        _invalid("selected state list does not match the offline alignment map",
                 field="selected_state_index")
    rotations = targets["frame_rotation_world_to_sensor"]
    translations = targets["frame_translation_world_to_sensor_m"]
    if rotations.dtype != np.float64 or rotations.shape != (feature_count, 3, 3) \
            or translations.dtype != np.float64 or translations.shape != (feature_count, 3) \
            or not np.isfinite(rotations).all() or not np.isfinite(translations).all():
        _invalid("sensor frame transforms must be finite and aligned with feature states",
                 field="frame_rotation_world_to_sensor")
    gram = rotations @ np.swapaxes(rotations, 1, 2)
    determinants = np.linalg.det(rotations)
    if not np.allclose(gram, np.eye(3)[None, :, :], rtol=0.0, atol=1e-10) \
            or not np.allclose(determinants, 1.0, rtol=0.0, atol=1e-10):
        _invalid("sensor transforms must be proper rotations", field="frame_rotation_world_to_sensor")
    expected_position = targets["position_m"][selected.astype(np.int64)]
    expected_position = expected_position @ np.swapaxes(rotations, 1, 2)
    expected_position += translations[:, None, :]
    expected_position = np.take_along_axis(expected_position, point_map[:, :, None], axis=1)
    if not np.allclose(position, expected_position, rtol=0.0, atol=1e-12):
        _invalid("research snapshots do not match the aligned native states and sensor frames",
                 field="research_feature_view")
    expected_files = {"dataset_manifest.json", feature_path.relative_to(root).as_posix(),
                      target_path.relative_to(root).as_posix()}
    actual_files = {path.relative_to(root).as_posix() for path in _walk_regular_files(root)}
    if actual_files != expected_files:
        _invalid("research dataset package contains unregistered payloads or shards",
                 field="dataset files",
                 measurements={"expected": sorted(expected_files),
                               "actual": sorted(actual_files)})
    return NativeBowlDataset(manifest=manifest, research_features=features, physics_targets=targets)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="hash-check a VF and native PG run")
    validate.add_argument("--vf-dir", required=True)
    validate.add_argument("--pg-dir", required=True)
    validate.add_argument("--expected-vf-manifest-sha256")
    validate.add_argument("--expected-pg-result-sha256")

    ingest = subparsers.add_parser("ingest", help="copy a verified source run into a new A12 package")
    ingest.add_argument("--vf-dir", required=True)
    ingest.add_argument("--pg-dir", required=True)
    ingest.add_argument("--out", required=True)
    ingest.add_argument("--expected-vf-manifest-sha256")
    ingest.add_argument("--expected-pg-result-sha256")

    export = subparsers.add_parser("export", help="export research features and offline physics targets")
    export.add_argument("--run", required=True, help="directory written by the ingest command")
    export.add_argument("--out", required=True)
    export.add_argument("--seed", required=True, type=int)
    export.add_argument("--state-indices", help="comma-separated increasing source-state indices")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_native_bowl_run(
                args.vf_dir, args.pg_dir,
                expected_vf_manifest_sha256=args.expected_vf_manifest_sha256,
                expected_pg_result_sha256=args.expected_pg_result_sha256,
            )
        elif args.command == "ingest":
            result = ingest_native_bowl_run(
                args.vf_dir, args.pg_dir, args.out,
                expected_vf_manifest_sha256=args.expected_vf_manifest_sha256,
                expected_pg_result_sha256=args.expected_pg_result_sha256,
            )
        else:
            if args.state_indices is None:
                indices = None
            else:
                try:
                    indices = [int(token.strip()) for token in args.state_indices.split(",")]
                except ValueError:
                    _invalid("--state-indices must be comma-separated integers", field="state_indices")
            result = export_native_bowl_dataset(args.run, args.out, seed=args.seed,
                                                state_indices=indices)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except SynLabError as exc:
        print(json.dumps({"status": "FAILED", "error": exc.to_dict()}, ensure_ascii=False,
                         indent=2, sort_keys=True))
        return 2
    except (OSError, FileExistsError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
