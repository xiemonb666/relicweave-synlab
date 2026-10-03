"""Strict validator for the v2 deployment view of an A12 training package.

The manifest field scan in :mod:`synlab.storage.export` is useful evidence, but it is not a
deployment schema.  This module validates the files that were actually written against a closed
container contract.  A future container or field requires a new deploy-schema version.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..errors import ErrorCode, SynLabError

DEPLOY_SCHEMA = "synlab.training_package_deploy.v2"
OPAQUE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_RAW_ID_RE = re.compile(r"(?:LIN\d+_[A-Z0-9_+.-]+|q::[^/\\\s]+)", re.IGNORECASE)

DEPLOY_OBS_ARRAYS = frozenset({
    "tiles", "valid", "view_pos", "depth_z", "deployment_mask", "uncertain_mask", "roi", "K",
})
GEOMETRY_ARRAYS = frozenset({
    "points", "normals", "point_valid", "normal_valid", "scale_valid", "frame_id",
})
TOKEN_ARRAYS = frozenset({"tokens", "token_valid", "token_view", "token_input", "tile_valid"})


def _invalid(reason: str, *, evidence: list[str] | None = None) -> SynLabError:
    return SynLabError(
        ErrorCode.LEAKAGE_DETECTED,
        f"INVALID_DEPLOY_TRUTH_LEAK: {reason}",
        stage="storage.deploy_boundary.validate",
        evidence_refs=evidence or [],
    )


def is_opaque_id(value: Any) -> bool:
    return bool(OPAQUE_ID_RE.fullmatch(str(value)))


def validate_deploy_package(root: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all deployment files, identities, array schemas and raw-id side channels.

    The validator deliberately ignores the research tree.  Deploy-mode callers therefore never
    need to load the research mapping to determine whether the public view is well formed.
    """
    package_root = Path(root)
    if manifest.get("deploy_schema") != DEPLOY_SCHEMA:
        version = manifest.get("deploy_schema")
        raise _invalid(f"unsupported or missing deploy_schema {version!r}; migrate to {DEPLOY_SCHEMA}")
    deploy_root = package_root / "deploy"
    if not deploy_root.is_dir():
        raise _invalid("deploy view is missing", evidence=["deploy"])

    files = {p.relative_to(deploy_root).as_posix() for p in deploy_root.rglob("*") if p.is_file()}
    query_files = files & {"queries.parquet", "queries.json"}
    if len(query_files) != 1:
        raise _invalid("deploy must contain exactly one queries.parquet or queries.json",
                       evidence=sorted(query_files))
    required = {
        "deploy_index.json", "obs/index.json", "geometry/index.json", "tokens/index.json",
    }
    missing = sorted(required - files)
    if missing:
        raise _invalid("required deploy container is missing", evidence=missing)
    allowed_exact = required | query_files
    allowed_patterns = (
        re.compile(r"^obs/shard_[0-9]{4}\.tar$"),
        re.compile(r"^geometry/shard_[0-9]{4}\.npz$"),
        re.compile(r"^tokens/shard_[0-9]{4}\.npz$"),
    )
    unknown = sorted(path for path in files if path not in allowed_exact
                     and not any(pattern.fullmatch(path) for pattern in allowed_patterns))
    if unknown:
        raise _invalid("unrecognized deployment file(s)", evidence=unknown)

    declared = {str(row.get("path", "")).removeprefix("deploy/")
                for row in manifest.get("files", [])
                if str(row.get("path", "")).startswith("deploy/")}
    if declared != files:
        raise _invalid("actual deploy files do not match manifest file inventory",
                       evidence=sorted(files ^ declared))

    query_path = deploy_root / next(iter(query_files))
    query_rows, query_columns = _read_table(query_path)
    allowed_query_columns = {"opaque_id", "bag_id"}
    if not query_columns or not query_columns <= allowed_query_columns or "opaque_id" not in query_columns:
        raise _invalid("query roster has unsupported columns", evidence=sorted(query_columns))
    opaque_ids: set[str] = set()
    for row_number, row in enumerate(query_rows):
        if set(row) != query_columns:
            raise _invalid(f"query row {row_number} does not match its declared columns")
        opaque = str(row.get("opaque_id", ""))
        if not is_opaque_id(opaque) or opaque in opaque_ids:
            raise _invalid(f"query row {row_number} has a missing, invalid, or duplicate opaque_id")
        opaque_ids.add(opaque)
        if "bag_id" in row and row["bag_id"] is not None and not isinstance(row["bag_id"], str):
            raise _invalid(f"query row {row_number} bag_id must be a string")
        _scan_raw_ids(row, f"{query_path.relative_to(package_root).as_posix()}[{row_number}]")

    deploy_index = _read_json(deploy_root / "deploy_index.json", "deploy_index.json")
    _exact_keys(deploy_index, {"schema", "rows"}, "deploy_index.json")
    if deploy_index.get("schema") != "synlab.deploy_index.v2" or not isinstance(deploy_index["rows"], dict):
        raise _invalid("deploy_index.json schema or rows object is invalid")

    obs_index = _read_json(deploy_root / "obs" / "index.json", "obs/index.json")
    _exact_keys(obs_index, {"schema", "channels", "rows"}, "obs/index.json")
    if obs_index.get("schema") != "synlab.obs_index.v2" or not isinstance(obs_index["rows"], dict):
        raise _invalid("obs/index.json schema or rows object is invalid")
    if not isinstance(obs_index["channels"], list):
        raise _invalid("obs/index.json channels must be a list")
    declared_channels = {str(name) for name in obs_index["channels"]}
    if (not declared_channels <= DEPLOY_OBS_ARRAYS or
            not {"tiles", "valid", "view_pos"} <= declared_channels):
        raise _invalid("obs/index.json declares unsupported or incomplete channels",
                       evidence=sorted(declared_channels))

    geometry_index = _read_json(deploy_root / "geometry" / "index.json", "geometry/index.json")
    _exact_keys(geometry_index, {"schema", "arrays", "rows"}, "geometry/index.json")
    if (geometry_index.get("schema") != "synlab.geometry_index.v2" or
            set(geometry_index.get("arrays") or []) != GEOMETRY_ARRAYS or
            not isinstance(geometry_index.get("rows"), dict)):
        raise _invalid("geometry/index.json schema, arrays, or rows are invalid")

    token_index = _read_json(deploy_root / "tokens" / "index.json", "tokens/index.json")
    _exact_keys(token_index, {"schema", "token_dim", "rows"}, "tokens/index.json")
    if (token_index.get("schema") != "synlab.token_index.v2" or
            not isinstance(token_index.get("rows"), dict)):
        raise _invalid("tokens/index.json schema or rows object is invalid")
    if int(token_index.get("token_dim", 0)) != 256:
        raise _invalid("tokens/index.json token_dim is unsupported")

    indices = {
        "deploy_index": deploy_index["rows"],
        "obs": obs_index["rows"],
        "geometry": geometry_index["rows"],
        "tokens": token_index["rows"],
    }
    for name, rows in indices.items():
        for opaque in rows:
            if not is_opaque_id(opaque):
                raise _invalid(f"{name} index key is not an opaque id", evidence=[str(opaque)])
            _scan_raw_ids(str(opaque), f"{name} index key")
    if set(indices["deploy_index"]) != opaque_ids:
        raise _invalid("deploy roster and deploy_index identities differ")
    if set(indices["obs"]) != opaque_ids or set(indices["tokens"]) != opaque_ids:
        raise _invalid("observation/token index identities differ from query roster")
    if not set(indices["geometry"]) <= opaque_ids:
        raise _invalid("geometry index names an opaque id absent from the query roster")

    shard_references: dict[str, set[str]] = {"obs": set(), "geometry": set(), "tokens": set()}
    for opaque, row in indices["deploy_index"].items():
        _exact_keys(row, {"obs_shard", "geometry_shard", "token_shard"},
                    f"deploy_index.rows.{opaque}")
        for kind, key in (("obs", "obs_shard"), ("geometry", "geometry_shard"),
                          ("tokens", "token_shard")):
            path = row[key]
            if path is not None:
                if not isinstance(path, str) or path not in files:
                    raise _invalid(f"deploy_index references an undeclared {kind} shard")
                if indices[kind].get(opaque, {}).get("shard") != path:
                    raise _invalid(f"deploy_index and {kind} index disagree for {opaque}")
                shard_references[kind].add(path)

    for kind, prefix, suffix in (("obs", "obs/", ".tar"),
                                 ("geometry", "geometry/", ".npz"),
                                 ("tokens", "tokens/", ".npz")):
        actual = {path for path in files if path.startswith(prefix) and path.endswith(suffix)
                  and "/shard_" in path}
        if actual != shard_references[kind]:
            raise _invalid(f"unreferenced or missing {kind} shard",
                           evidence=sorted(actual ^ shard_references[kind]))

    _validate_index_rows("obs", indices["obs"], opaque_ids, files)
    _validate_index_rows("geometry", indices["geometry"], opaque_ids, files)
    _validate_index_rows("tokens", indices["tokens"], opaque_ids, files)
    _validate_npz_shards(deploy_root, "geometry", shard_references["geometry"], indices["geometry"])
    _validate_npz_shards(deploy_root, "tokens", shard_references["tokens"], indices["tokens"])
    _validate_obs_shards(deploy_root, shard_references["obs"], indices["obs"], declared_channels)

    # A closed set of field names is primary.  This independent content guard catches a known
    # source identifier accidentally copied into an otherwise permitted free-text value.
    for rel in sorted(files):
        path = deploy_root / Path(rel)
        if path.suffix.lower() == ".json":
            _scan_raw_ids(_read_json(path, rel), rel)
        elif path.suffix.lower() == ".parquet":
            for i, row in enumerate(query_rows):
                _scan_raw_ids(row, f"{rel}[{i}]")
        elif path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as data:
                for key in data.files:
                    _scan_raw_ids(key, f"{rel} array key")
                    _scan_array_strings(data[key], f"{rel}:{key}")
        elif path.suffix.lower() == ".tar":
            with tarfile.open(path, "r") as tar:
                for member in tar.getmembers():
                    _scan_raw_ids(member.name, f"{rel} member")
    return {"schema": DEPLOY_SCHEMA, "ok": True, "opaque_queries": len(opaque_ids),
            "deploy_files": len(files), "channels": sorted(declared_channels)}


def _read_table(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq

        table = pq.read_table(path)
        rows = [dict(row) for row in table.to_pylist()]
        return rows, {str(name) for name in table.schema.names}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(f"query roster cannot be parsed: {exc}", evidence=[str(path)]) from exc
    if not isinstance(raw, list):
        raise _invalid("query roster JSON must be a list", evidence=[str(path)])
    rows = [dict(row) for row in raw if isinstance(row, Mapping)]
    if len(rows) != len(raw):
        raise _invalid("query roster contains a non-object row", evidence=[str(path)])
    columns = set().union(*(row.keys() for row in rows)) if rows else set()
    return rows, {str(key) for key in columns}


def _read_json(path: Path, evidence: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(f"{evidence} cannot be parsed: {exc}", evidence=[evidence]) from exc
    if not isinstance(value, dict):
        raise _invalid(f"{evidence} must contain a JSON object", evidence=[evidence])
    return value


def _exact_keys(node: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(node) != expected:
        raise _invalid(f"{where} fields do not match the v2 allowlist",
                       evidence=[f"unexpected={sorted(set(node) - expected)}",
                                 f"missing={sorted(expected - set(node))}"])


def _validate_index_rows(kind: str, rows: Mapping[str, Any], opaque_ids: set[str],
                         files: set[str]) -> None:
    schemas = {
        "obs": {"shard", "views", "shape", "hash", "channels", "view_pos_source"},
        "geometry": {"shard", "n_points", "frames", "frame_id_source",
                     "frame_id_unmatched", "frame_id_match_fraction", "points_hash"},
        "tokens": {"shard", "tokens", "token_dim", "tokens_hash", "views", "tile_shape"},
    }
    for opaque, row in rows.items():
        if not isinstance(row, Mapping):
            raise _invalid(f"{kind} row {opaque} is not an object")
        _exact_keys(row, schemas[kind], f"{kind}.rows.{opaque}")
        shard = str(row.get("shard", ""))
        if shard not in files:
            raise _invalid(f"{kind} row references a missing shard", evidence=[shard])
        if kind == "obs":
            if not isinstance(row.get("channels"), list):
                raise _invalid(f"obs row {opaque} channels must be a list")
            channels = set(map(str, row["channels"]))
            if channels - DEPLOY_OBS_ARRAYS or not {"tiles", "valid", "view_pos"} <= channels:
                raise _invalid(f"obs row {opaque} declares unsupported channels",
                               evidence=sorted(channels))
            if list(row.get("shape") or [])[:1] != [int(row.get("views", -1))]:
                raise _invalid(f"obs row {opaque} shape and views disagree")
        elif kind == "geometry":
            if int(row.get("n_points", -1)) < 0 or int(row.get("frame_id_unmatched", -1)) < 0:
                raise _invalid(f"geometry row {opaque} contains invalid counts")
        elif kind == "tokens":
            if int(row.get("token_dim", 0)) != 256 or int(row.get("tokens", -1)) < 0:
                raise _invalid(f"token row {opaque} contains invalid dimensions")
            tile_shape = row.get("tile_shape")
            if (not isinstance(tile_shape, list) or len(tile_shape) != 3 or
                    int(row.get("views", 0)) != int(tile_shape[0]) or
                    any(int(value) <= 0 for value in tile_shape)):
                raise _invalid(f"token row {opaque} has invalid tile dimensions")
        _scan_raw_ids(row, f"{kind}.rows.{opaque}")


def _validate_npz_shards(deploy_root: Path, kind: str, shards: set[str],
                         rows: Mapping[str, Any]) -> None:
    array_allowlist = GEOMETRY_ARRAYS if kind == "geometry" else TOKEN_ARRAYS
    seen: set[str] = set()
    for rel in sorted(shards):
        path = deploy_root / rel
        with np.load(path, allow_pickle=False) as data:
            for name in data.files:
                if "__" not in name:
                    raise _invalid(f"{kind} NPZ key has no opaque identity prefix",
                                   evidence=[f"{rel}:{name}"])
                opaque, array_name = name.split("__", 1)
                if not is_opaque_id(opaque) or array_name not in array_allowlist:
                    raise _invalid(f"{kind} NPZ key is outside the v2 allowlist",
                                   evidence=[f"{rel}:{name}"])
                if rows.get(opaque, {}).get("shard") != rel:
                    raise _invalid(f"{kind} NPZ key is absent from its index",
                                   evidence=[f"{rel}:{name}"])
                _validate_array(kind, array_name, data[name], rows[opaque])
                seen.add(f"{opaque}__{array_name}")
    for opaque, row in rows.items():
        expected = array_allowlist
        # v2 emits the six geometry arrays and all five token arrays as fixed groups.
        absent = sorted(f"{opaque}__{name}" for name in expected
                        if f"{opaque}__{name}" not in seen)
        if absent:
            raise _invalid(f"{kind} NPZ is missing allowlisted arrays", evidence=absent)


def _validate_array(kind: str, name: str, array: np.ndarray, row: Mapping[str, Any]) -> None:
    dtype = str(array.dtype)
    if kind == "geometry":
        expected_dtype = {"points": "float32", "normals": "float32", "point_valid": "bool",
                          "normal_valid": "bool", "scale_valid": "bool", "frame_id": "int32"}[name]
        n = int(row["n_points"])
        shape = (n, 3) if name in {"points", "normals"} else (n,)
    else:
        expected_dtype = {"tokens": "float32", "token_valid": "bool", "token_view": "int32",
                          "token_input": "float32", "tile_valid": "bool"}[name]
        n = int(row["tokens"])
        if name == "tile_valid":
            shape = tuple(map(int, row["tile_shape"]))
        else:
            shape = (n, 256) if name == "tokens" else (n,)
    if dtype != expected_dtype or tuple(array.shape) != shape or array.dtype.hasobject:
        raise _invalid(f"{kind} array {name} has unsupported dtype or dimensions",
                       evidence=[f"actual={dtype}{tuple(array.shape)} expected={expected_dtype}{shape}"])
    _scan_array_strings(array, f"{kind}:{name}")


def _validate_obs_shards(deploy_root: Path, shards: set[str], rows: Mapping[str, Any],
                         declared_channels: set[str]) -> None:
    seen: set[tuple[str, str]] = set()
    for rel in sorted(shards):
        path = deploy_root / rel
        with tarfile.open(path, "r") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    raise _invalid("observation TAR may contain files only", evidence=[member.name])
                parts = member.name.split("/")
                if len(parts) != 2 or not is_opaque_id(parts[0]) or not parts[1].endswith(".npy"):
                    raise _invalid("observation TAR member path is outside the v2 allowlist",
                                   evidence=[member.name])
                opaque, array_name = parts[0], parts[1][:-4]
                if array_name not in declared_channels or array_name not in DEPLOY_OBS_ARRAYS:
                    raise _invalid("observation TAR carries an undeclared channel",
                                   evidence=[member.name])
                if rows.get(opaque, {}).get("shard") != rel:
                    raise _invalid("observation TAR member is absent from its index",
                                   evidence=[member.name])
                stream = tar.extractfile(member)
                if stream is None:
                    raise _invalid("observation TAR member could not be read", evidence=[member.name])
                try:
                    array = np.load(io.BytesIO(stream.read()), allow_pickle=False)
                except Exception as exc:  # noqa: BLE001 - invalid container is a boundary failure
                    raise _invalid(f"observation TAR array cannot be decoded: {exc}",
                                   evidence=[member.name]) from exc
                _validate_obs_array(array_name, array, rows[opaque])
                seen.add((opaque, array_name))
    for opaque, row in rows.items():
        channels = set(map(str, row["channels"]))
        if not channels <= declared_channels:
            raise _invalid(f"obs row {opaque} declares a channel absent from top-level index")
        absent = sorted(name for name in channels if (opaque, name) not in seen)
        extra = sorted(name for key, name in seen if key == opaque and name not in channels)
        if absent or extra:
            raise _invalid(f"observation TAR/index channels disagree for {opaque}",
                           evidence=[*absent, *extra])


def _validate_obs_array(name: str, array: np.ndarray, row: Mapping[str, Any]) -> None:
    views, height, width, _channels = map(int, row["shape"])
    n = views
    shapes = {
        "tiles": ((views, height, width, 3), "uint8"),
        "valid": ((views, height, width), "bool"),
        "view_pos": ((views,), "float32"),
        "depth_z": ((views, height, width), "float32"),
        "deployment_mask": ((views, height, width), "bool"),
        "uncertain_mask": ((views, height, width), "bool"),
        "roi": ((views, height, width), "bool"),
        "K": ((views, 3, 3), "float64"),
    }
    shape, dtype = shapes[name]
    if tuple(array.shape) != shape or str(array.dtype) != dtype or array.dtype.hasobject:
        raise _invalid(f"observation array {name} has unsupported dtype or dimensions",
                       evidence=[f"actual={array.dtype}{tuple(array.shape)} expected={dtype}{shape}"])
    _scan_array_strings(array, f"obs:{name}")


def _scan_raw_ids(value: Any, where: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _scan_raw_ids(str(key), where)
            _scan_raw_ids(item, where)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _scan_raw_ids(item, where)
    elif isinstance(value, str) and _RAW_ID_RE.search(value):
        raise _invalid("source fragment identity or query alias appears in deployment content",
                       evidence=[where])


def _scan_array_strings(array: np.ndarray, where: str) -> None:
    if array.dtype.kind in {"U", "S", "O"}:
        _scan_raw_ids(array.tolist(), where)


__all__ = ["DEPLOY_SCHEMA", "DEPLOY_OBS_ARRAYS", "GEOMETRY_ARRAYS", "TOKEN_ARRAYS",
           "is_opaque_id", "validate_deploy_package"]
