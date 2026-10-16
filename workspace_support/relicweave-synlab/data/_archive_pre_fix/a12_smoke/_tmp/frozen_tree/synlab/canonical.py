"""Canonical serialisation, content hashing and code fingerprints (plan section 5.2)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return {"__ndarray__": array_hash(obj)}
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "model_dump"):
        return _jsonable(obj.model_dump(mode="json"))
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("canonical JSON forbids NaN/Inf")
        return obj
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, no NaN/Inf."""
    return json.dumps(
        _jsonable(obj), ensure_ascii=False, separators=(",", ":"),
        sort_keys=True, allow_nan=False,
    )


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_bytes(data: bytes, prefix: str = "sha256:") -> str:
    return prefix + sha256_hex(data)


def hash_json(obj: Any) -> str:
    return hash_bytes(canonical_bytes(obj))


def array_hash(arr: np.ndarray) -> str:
    """Hash dtype + shape + raw little-endian bytes of a numeric array."""
    a = np.ascontiguousarray(arr)
    if a.dtype.byteorder == ">" or (a.dtype.byteorder == "=" and not np.little_endian):
        a = a.astype(a.dtype.newbyteorder("<"), copy=False)
    h = hashlib.sha256()
    h.update(str(a.dtype.str).encode("ascii"))
    h.update(b"|")
    h.update(",".join(str(d) for d in a.shape).encode("ascii"))
    h.update(b"|")
    h.update(a.tobytes(order="C"))
    return "sha256:" + h.hexdigest()


def hash_file(path: str | os.PathLike[str], chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return "sha256:" + h.hexdigest()


def hash_tree(root: str | os.PathLike[str], *, suffix_filter: tuple[str, ...] = ()) -> str:
    """Hash a directory tree by relative path + file content hash (sorted)."""
    root = Path(root)
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if suffix_filter and not path.name.endswith(suffix_filter):
            continue
        entries.append((str(path.relative_to(root)).replace("\\", "/"), hash_file(path)))
    return hash_json(entries)


def interpret_hash(role: str, schema: str, unit: str, frame: str, payload_hash: str,
                   extra: dict[str, Any] | None = None) -> str:
    """Semantic interpretation hash: same bytes may carry different meanings (plan 30.17)."""
    return hash_json({
        "role": role, "schema": schema, "unit": unit, "frame": frame,
        "payload": payload_hash, "extra": extra or {},
    })


def code_fingerprint(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Commit + dirty diff + untracked source + config content hash (plan 5.2).

    Falls back to a tree hash when git is unavailable so that a reproducible
    fingerprint always exists; the fallback is recorded explicitly.
    """
    root = Path(repo_root)
    info: dict[str, Any] = {"git": False, "commit": None, "dirty": None, "diff_hash": None}
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if commit.returncode == 0:
            info["git"] = True
            info["commit"] = commit.stdout.strip()
            diff = subprocess.run(
                ["git", "-C", str(root), "diff", "HEAD"],
                capture_output=True, text=True, timeout=60, check=False,
            )
            out = diff.stdout or ""
            info["dirty"] = bool(out.strip())
            info["diff_hash"] = hash_bytes(out.encode("utf-8", "replace"))
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=60, check=False,
            )
            untracked = []
            for line in (status.stdout or "").splitlines():
                if line.startswith("?? "):
                    untracked.append(line[3:].strip())
            info["untracked"] = sorted(untracked)
    except (OSError, subprocess.SubprocessError):
        info["git"] = False
    src = root / "synlab"
    if src.is_dir():
        info["source_tree_hash"] = hash_tree(src, suffix_filter=(".py",))
    return info


def fingerprint_hash(fp: dict[str, Any]) -> str:
    return hash_json(fp)


def job_id_hash(*, stage: str, canonical_spec: str, input_hashes: list[str],
                code_fp: str, backend_fps: dict[str, Any], schema_versions: dict[str, str]) -> str:
    """job_id = hash(stage + spec + inputs + code + backends + schema versions)."""
    return hash_json({
        "stage": stage,
        "spec": canonical_spec,
        "inputs": sorted(input_hashes),
        "code": code_fp,
        "backends": backend_fps,
        "schemas": schema_versions,
    })
