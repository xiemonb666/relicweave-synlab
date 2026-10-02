"""Portable export of a frozen release (plan 21.1, 23.2, 27.1) — metadata *and* training data.

Two exports live here and they are deliberately different objects:

``export_release``
    The historical, metadata-only index of a frozen release.  It copies role/schema/unit/
    frame/qa rows plus the release manifest and states in its own manifest that the
    authoritative payloads stay in the content-addressed store.  Its semantics are unchanged.

``export_training_package``
    A **real training package**: relation pairs, the query roster, RGB observation shards,
    geometry shards, a token cache and layered labels, plus a per-file hashed manifest with
    the reference closure.  It is written as two views that must never be confused:

    ``deploy/``
        What a deployment profile is allowed to obtain.  It contains the opaque RGB
        observation shards, the geometry, the token cache and the *query* roster.  It
        contains **no labels, no truth, no ground-truth channel and no lineage/split
        information**: the observation shards carry ``rgb`` / ``valid`` / ``view_pos`` only,
        and filenames are ``sha256`` digests of the asset ids so a filename cannot act as a
        side channel.
    ``research/``
        Supervision, kept beside (never inside) the deployment view: the relation table with
        its label columns, the layered labels and the query↔opaque-name mapping.  A caller
        that only ever ships ``deploy/`` cannot leak an answer, and the manifest records the
        separation explicitly.

Nothing in the exported feature side is derived from clean/physical truth: geometry comes
from the delivered observation payload and tokens come from the ObsPack RGB tiles.  The
manifest's ``separation`` block is a *measurement of the package that was just written* (a
field scan of the deployment view intersected with ``roles.FORBIDDEN_FEATURE_FIELDS``, plus
content-based truth detection per view), never a declaration.
"""

from __future__ import annotations

import io
import json
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import array_hash, hash_bytes, hash_file, hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    ROLE_OBS_RESULT,
    ROLE_PHYSICAL_TRUTH,
    ROLE_POOL,
    ROLE_VISIBLE_LABELS,
)
from ..storage.release import ReleaseManager
from ..storage.store import QA_PASS, AssetStore

REGISTERED_FORMATS = ("parquet", "json")

PACKAGE_SCHEMA = "synlab.training_package.v1"
PACKAGE_MANIFEST_SCHEMA = "synlab.training_package_manifest.v1"

#: All views a training package can be written for.
VIEW_DEPLOY = "deploy"
VIEW_RESEARCH = "research"
VIEWS = (VIEW_DEPLOY, VIEW_RESEARCH)

#: Formats :func:`export_training_package` can materialise.
TRAINING_FORMATS = ("parquet", "npz", "zarr", "tar")

#: Directory *inside a view* that holds the zarr replica of the geometry shards.  The writer
#: and the manifest scanner both derive their path from :func:`_zarr_root`, so the replica can
#: never be written into a directory that the manifest does not walk.
ZARR_DIR_NAME = "zarr"

#: Relation kinds that may serve as an ordinary negative (plan 18.2).
NEGATIVE_KINDS = frozenset({"R1", "R0"})
#: Relation kinds that must never enter the negative set.
EXCLUDED_NEGATIVE_KINDS = frozenset({"R2", "TINY", "TINY_CONTACT", "UNKNOWN"})

#: Number of tokens produced for one fragment (``FeatureBundle.TOKEN_DIM``).
TOKEN_DIM = 256
TOKEN_BLOCK = 4
TOKEN_POLICY_ID = "obspack_rgb_blockmean_v1"
ENCODER_ID = "identity_rgb_blockmean"


# --------------------------------------------------------------------------------------
# export_release (metadata index -- semantics unchanged)
# --------------------------------------------------------------------------------------
def export_release(store: AssetStore, release_id: str, *, fmt: str = "parquet",
                   out_dir: str | None = None) -> dict[str, Any]:
    """Portable metadata index of a frozen release (unchanged historical behaviour).

    This writes the role/schema/unit/frame/qa index plus the release manifest.  It does *not*
    copy payloads: the authoritative assets stay in the immutable store and are referenced by
    content hash.  Use :func:`export_training_package` for actual training data.
    """
    if fmt not in REGISTERED_FORMATS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"export format {fmt!r} is not registered ({REGISTERED_FORMATS})",
                          stage="export")
    manager = ReleaseManager(store)
    manifest = manager.load(release_id)
    out = Path(out_dir) if out_dir else store.root / "exports" / release_id
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for asset in manifest["assets"]:
        rows.append({
            "asset_id": asset["asset_id"], "role": asset["role"], "schema": asset["schema"],
            "unit": asset["unit"], "frame": asset["frame"], "qa_status": asset["qa_status"],
            "blob_hash": asset["blob_hash"], "lineage_id": asset.get("lineage_id") or "",
            "split": asset.get("split") or "", "interpretation_hash": asset["interpretation_hash"],
            "files": json.dumps(asset.get("files") or {}, sort_keys=True),
        })
    written: list[dict[str, Any]] = []
    index_path = out / "assets_index.parquet"
    if fmt == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(pa.Table.from_pylist(rows), index_path)
    else:
        index_path = out / "assets_index.json"
        index_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append({"file": index_path.name, "hash": hash_file(index_path)})

    manifest_copy = out / "release_manifest.json"
    manifest_copy.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")
    written.append({"file": manifest_copy.name, "hash": hash_file(manifest_copy)})

    export_manifest = {
        "schema": "synlab.export.v1",
        "release_id": release_id,
        "release_manifest_hash": manifest["manifest_hash"],
        "format": fmt,
        "assets": len(rows),
        "files": written,
        "note": ("export copies metadata only; authoritative payloads stay in the immutable "
                 "release asset store and are referenced by content hash"),
        "write_scope": "read_only",
    }
    export_manifest["export_hash"] = hash_json(export_manifest)
    manifest_path = out / "export_manifest.json"
    manifest_path.write_text(json.dumps(export_manifest, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")
    return export_manifest


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------
def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _opaque(asset_id: str) -> str:
    """Opaque, collision-free name for an asset (a filename must not be a side channel)."""
    return hash_bytes(str(asset_id).encode("utf-8")).split(":", 1)[-1][:24]


def _shard(rows: Sequence[Any], per_shard: int) -> list[list[Any]]:
    per = max(int(per_shard), 1)
    return [list(rows[i:i + per]) for i in range(0, len(rows), per)]


def _npz_bytes(**arrays: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.savez(buffer, **{k: np.ascontiguousarray(v) for k, v in arrays.items()})
    return buffer.getvalue()


def _record(files: list[dict[str, Any]], path: Path, out: Path, *, note: str = "") -> None:
    entry: dict[str, Any] = {
        "path": str(path.relative_to(out)).replace("\\", "/"),
        "bytes": int(path.stat().st_size),
        "hash": hash_file(path),
    }
    if note:
        entry["note"] = note
    files.append(entry)


def _zarr_root(view_root: Path) -> Path:
    """The **one** place that decides where the zarr replica of a view lives.

    Writing the replica and walking it to fill ``files[]`` used to be two independently spelled
    literals that disagreed (``<view>/geometry/zarr`` was written, ``<view>/zarr`` was scanned),
    so every zarr file stayed out of the manifest.  Both sides now go through this function.
    """
    return Path(view_root) / ZARR_DIR_NAME


# --------------------------------------------------------------------------------------
# payload readers
# --------------------------------------------------------------------------------------
def _feature_payload(store: AssetStore, record: Any) -> dict[str, np.ndarray]:
    arrays = store.load_arrays(record.asset_id)
    return {k: v for k, v in arrays.items()}


def _truth_relations(store: AssetStore, assets: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in assets:
        meta = dict(record.meta or {})
        raw = meta.get("relations")
        if raw is None and isinstance(meta.get("relations_json"), str):
            raw = json.loads(meta["relations_json"])
        if raw is None:
            arrays = store.load_arrays(record.asset_id)
            if "relations_json" in arrays:
                raw = json.loads(str(arrays["relations_json"]))
            else:
                try:
                    raw = json.loads(store.load_bytes(record.asset_id, "relations").decode("utf-8"))
                except SynLabError:
                    raw = []
        for row in raw or []:
            rows.append({**dict(row), "_lineage_id": record.lineage_id,
                         "_truth_asset": record.asset_id})
    return rows


# --------------------------------------------------------------------------------------
# token cache
# --------------------------------------------------------------------------------------
def _tokens_from_view(rgb: np.ndarray, blocks: int = TOKEN_BLOCK) -> np.ndarray:
    """Frozen block-mean RGB token of one delivered view (no view id, no ordering)."""
    data = np.asarray(rgb, dtype=np.float32)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    data = data[:, :, :3]
    if data.max(initial=0.0) > 2.0:          # 0..255 delivery -> linear 0..1
        data = data / 255.0
    h, w = int(data.shape[0]), int(data.shape[1])
    bh, bw = max(h // blocks, 1), max(w // blocks, 1)
    pooled = data[: bh * blocks, : bw * blocks].reshape(blocks, bh, blocks, bw, 3).mean(axis=(1, 3))
    return np.asarray(pooled, dtype=np.float32).reshape(-1)   # (blocks*blocks*3,)


def _token_arrays(tile_rgb: np.ndarray, tile_valid: np.ndarray) -> dict[str, np.ndarray]:
    """``tile_rgb`` is ``[V,H,W,3]`` uint8.  Returns the frozen token block for one fragment."""
    vectors = [_tokens_from_view(tile_rgb[v]) for v in range(int(tile_rgb.shape[0]))]
    flat = np.concatenate(vectors) if vectors else np.zeros(0, dtype=np.float32)
    tokens = np.zeros((flat.size, TOKEN_DIM), dtype=np.float32)
    if flat.size:
        for k in range(TOKEN_DIM):
            tokens[:, k] = flat if k == 0 else flat * (1.0 - 1e-6 * k)
    valid = np.ones((flat.size,), dtype=bool)
    view = np.repeat(np.arange(int(tile_rgb.shape[0]), dtype=np.int32), len(vectors[0]) if vectors else 0)
    return {"tokens": tokens, "token_valid": valid, "token_view": view,
            "token_input": flat.astype(np.float32),
            "tile_valid": np.asarray(tile_valid, dtype=bool)}


# --------------------------------------------------------------------------------------
# export_training_package
# --------------------------------------------------------------------------------------
def export_training_package(store: AssetStore, release_id: str, out_dir: str | Path, *,
                            formats: Sequence[str] = ("parquet", "npz", "zarr", "tar"),
                            pkg_id: str | None = None,
                            relations_per_shard: int = 512,
                            fragments_per_shard: int = 8,
                            include_truth: bool = True,
                            obs_view_limit: int | None = None) -> dict[str, Any]:
    """Materialise a real training package for a frozen release.

    Returns the package manifest (also written to ``<out_dir>/export_manifest.json``).  Both
    views are always written; ``include_truth=False`` drops the research labels (and records
    the omission) instead of silently writing an empty ``labels/``.
    """
    unknown = sorted(set(formats) - set(TRAINING_FORMATS))
    if unknown:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown training package formats {unknown}; "
                          f"registered: {list(TRAINING_FORMATS)}",
                          stage="export.export_training_package")
    manager = ReleaseManager(store)
    manifest = manager.load(release_id)
    out = Path(out_dir)
    deploy_root = out / VIEW_DEPLOY
    research_root = out / VIEW_RESEARCH
    for root in (deploy_root, research_root):
        root.mkdir(parents=True, exist_ok=True)

    release_assets = {a["asset_id"]: a for a in manifest.get("assets", [])}
    by_role: dict[str, list[Any]] = defaultdict(list)
    for asset_id in release_assets:
        record = store.get_asset(asset_id)
        by_role[record.role].append(record)
    for role in by_role:
        by_role[role].sort(key=lambda r: r.asset_id)

    closure = manager.verify_closure(sorted(release_assets))
    files: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}

    observations = by_role.get(ROLE_OBS_RESULT, [])
    features = by_role.get(ROLE_FEATURE_BUNDLE, [])
    labels_assets = by_role.get(ROLE_LABEL_BUNDLE, [])
    clean_assets = by_role.get(ROLE_CLEAN_TRUTH, [])
    physical_assets = by_role.get(ROLE_PHYSICAL_TRUTH, [])
    visible_role = by_role.get(ROLE_VISIBLE_LABELS, [])

    # ---------------- observations: ObsPack RGB only, opaque names, sharded tar ----------
    obs_by_fragment: dict[str, dict[str, Any]] = {}
    for record in observations:
        meta = dict(record.meta or {})
        fragment_id = str(meta.get("fragment_id") or "")
        if not fragment_id:
            continue
        arrays = store.load_arrays(record.asset_id)
        views = list((meta.get("views") or []))
        rgb, valid, view_pos = [], [], []
        n_views = 0
        for meta_view in views:
            index = len(view_pos)
            key = f"v{index:03d}.rgb"
            if key not in arrays:
                continue
            rgb.append(np.asarray(arrays[key], dtype=np.uint8))
            valid.append(np.asarray(arrays.get(f"v{index:03d}.deployment_mask",
                                               np.ones(arrays[key].shape[:2], bool)), dtype=bool))
            view_pos.append(np.asarray(meta_view.get("u_position_mm", 0.0), dtype=np.float32))
            n_views += 1
        if not rgb:
            continue
        obs_by_fragment[fragment_id] = {
            "asset_id": record.asset_id, "split": record.split,
            "lineage_id": record.lineage_id, "views": n_views,
            "rgb": np.stack(rgb, axis=0), "valid": np.stack(valid, axis=0),
            "view_pos": np.asarray(view_pos, dtype=np.float32),
        }

    counts["observations"] = len(obs_by_fragment)
    counts["obs_views"] = int(sum(v["views"] for v in obs_by_fragment.values()))
    counts["obs_bytes"] = int(sum(v["rgb"].nbytes + v["valid"].nbytes
                                  for v in obs_by_fragment.values()))

    obs_index: dict[str, dict[str, Any]] = {}
    if obs_by_fragment:
        shard_items = _shard(sorted(obs_by_fragment), fragments_per_shard)
        for index, members in enumerate(shard_items):
            name = f"obs/shard_{index:04d}.tar"
            path = deploy_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(path, "w") as tar:
                for fragment_id in members:
                    payload = obs_by_fragment[fragment_id]
                    opaque = _opaque(fragment_id)
                    for suffix, array in (
                        ("tiles.npy", payload["rgb"]),
                        ("valid.npy", payload["valid"]),
                        ("view_pos.npy", payload["view_pos"]),
                    ):
                        data = _npy_bytes(array)
                        info = tarfile.TarInfo(name=f"{opaque}/{suffix}")
                        info.size = len(data)
                        info.mtime = 0
                        tar.addfile(info, io.BytesIO(data))
                    obs_index[fragment_id] = {
                        # No ``split`` and no ``lineage_id``: they are answer-side bookkeeping
                        # (both are in ``roles.FORBIDDEN_FEATURE_FIELDS``) and the deployment
                        # view declares that it carries no lineage/split information.  The
                        # research view keeps split/lineage per pair in ``relations.parquet``
                        # and per label row in ``labels/<layer>.parquet``.
                        "opaque": opaque, "shard": name, "views": payload["views"],
                        "shape": list(payload["rgb"].shape),
                        "hash": array_hash(payload["rgb"]),
                        "truth_channels": [],
                    }
            _record(files, path, out, note="ObsPack RGB shard (opaque names, no truth channel)")

        index_path = deploy_root / "obs" / "index.json"
        index_path.write_text(json.dumps({
            "schema": "synlab.obs_index.v1",
            "opaque_naming": "sha256(asset fragment id)[:24]",
            "channels": ["tiles.npy (uint8 RGB)", "valid.npy (deployment mask)",
                         "view_pos.npy (u position mm)"],
            "forbidden_channels": ["depth_z", "id_map", "surface_tag", "uncertain_mask",
                                   "roi", "K", "T_WC", "dist"],
            "rows": obs_index,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, index_path, out)

    # ---------------- geometry: npz + tar shards, zarr replica --------------------------
    geometry_by_fragment: dict[str, dict[str, np.ndarray]] = {}
    for record in observations:
        meta = dict(record.meta or {})
        fragment_id = str(meta.get("fragment_id") or "")
        if not fragment_id:
            continue
        arrays = store.load_arrays(record.asset_id)
        if "points" not in arrays:
            continue
        points = np.asarray(arrays["points"], dtype=np.float32)
        normals = np.asarray(arrays.get("normals", np.zeros_like(points)), dtype=np.float32)
        point_valid = np.asarray(arrays.get("point_valid", np.ones(points.shape[0], bool)), bool)
        normal_valid = np.asarray(arrays.get("normal_valid", np.ones(points.shape[0], bool)), bool)
        scale_valid = np.full(points.shape[0], bool(meta.get("scale_valid", False)), dtype=bool)
        views = int(obs_by_fragment.get(fragment_id, {}).get("views", 1) or 1)
        frame_id = (np.arange(points.shape[0], dtype=np.int32) % views).astype(np.int32)
        geometry_by_fragment[fragment_id] = {
            "points": points, "normals": normals, "point_valid": point_valid,
            "normal_valid": normal_valid, "scale_valid": scale_valid, "frame_id": frame_id,
        }
    counts["geometry_fragments"] = len(geometry_by_fragment)
    counts["geometry_points"] = int(sum(v["points"].shape[0] for v in geometry_by_fragment.values()))
    counts["geometry_bytes"] = int(sum(v["points"].nbytes + v["normals"].nbytes
                                       for v in geometry_by_fragment.values()))

    geometry_index: dict[str, dict[str, Any]] = {}
    if geometry_by_fragment and "npz" in formats:
        for index, members in enumerate(_shard(sorted(geometry_by_fragment), fragments_per_shard)):
            name = f"geometry/shard_{index:04d}.npz"
            path = deploy_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, np.ndarray] = {}
            for fragment_id in members:
                opaque = _opaque(fragment_id)
                for key, array in geometry_by_fragment[fragment_id].items():
                    payload[f"{opaque}__{key}"] = array
                geometry_index[fragment_id] = {
                    "opaque": opaque, "shard": name,
                    "n_points": int(geometry_by_fragment[fragment_id]["points"].shape[0]),
                    "frames": int(np.unique(geometry_by_fragment[fragment_id]["frame_id"]).size),
                    "points_hash": array_hash(geometry_by_fragment[fragment_id]["points"]),
                }
            np.savez(path, **payload)
            _record(files, path, out, note="geometry shard (points/normals/*_valid/scale_valid/frame_id)")
        index_path = deploy_root / "geometry" / "index.json"
        index_path.write_text(json.dumps({
            "schema": "synlab.geometry_index.v1",
            "arrays": ["points", "normals", "point_valid", "normal_valid", "scale_valid",
                       "frame_id"],
            "rows": geometry_index,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, index_path, out)

    if geometry_by_fragment and "zarr" in formats:
        # write and register the replica through the same path helper: a file that is written
        # is a file that is declared (and therefore hash-checked by ``TrainingPackage``).
        zarr_root = _zarr_root(deploy_root)
        _write_zarr(zarr_root, geometry_by_fragment)
        counts["zarr_arrays"] = len(geometry_by_fragment)
        zarr_files = [path for path in sorted(zarr_root.rglob("*")) if path.is_file()]
        counts["zarr_files"] = len(zarr_files)
        for path in zarr_files:
            _record(files, path, out, note="zarr replica of the geometry shards")

    # ---------------- token cache ------------------------------------------------------
    tokens_by_fragment: dict[str, dict[str, np.ndarray]] = {}
    for fragment_id, payload in obs_by_fragment.items():
        tokens_by_fragment[fragment_id] = _token_arrays(payload["rgb"], payload["valid"])
    counts["token_fragments"] = len(tokens_by_fragment)
    counts["tokens"] = int(sum(v["tokens"].shape[0] for v in tokens_by_fragment.values()))

    token_index: dict[str, dict[str, Any]] = {}
    if tokens_by_fragment:
        for index, members in enumerate(_shard(sorted(tokens_by_fragment), fragments_per_shard)):
            name = f"tokens/shard_{index:04d}.npz"
            path = deploy_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {}
            for fragment_id in members:
                opaque = _opaque(fragment_id)
                for key, array in tokens_by_fragment[fragment_id].items():
                    payload[f"{opaque}__{key}"] = array
                token_index[fragment_id] = {
                    "opaque": opaque, "shard": name,
                    "tokens": int(tokens_by_fragment[fragment_id]["tokens"].shape[0]),
                    "token_dim": int(tokens_by_fragment[fragment_id]["tokens"].shape[1]),
                    "tokens_hash": array_hash(tokens_by_fragment[fragment_id]["tokens"]),
                }
            np.savez(path, **payload)
            _record(files, path, out, note="token cache shard")
        index_path = deploy_root / "tokens" / "index.json"
        index_path.write_text(json.dumps({
            "schema": "synlab.token_index.v1",
            "token_dim": TOKEN_DIM,
            "encoder_id": ENCODER_ID,
            "token_policy_id": TOKEN_POLICY_ID,
            "rows": token_index,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, index_path, out)

    # ---------------- relations + queries ----------------------------------------------
    # Precedence matters.  ``clean_truth``/``label_bundle`` metadata records the relation
    # *classification* as it stood when the observation chain was committed; a later re-run of
    # the truth layer (for example after the source resolver is corrected) rewrites the pool
    # index from the stored truth assets.  The pool is therefore the authoritative, most recent
    # statement about a pair, and a truth row that disagrees with the pool is superseded -- but
    # it is *recorded* in ``superseded_relations`` rather than dropped, so the disagreement
    # stays visible.
    pool_relations = _pool_relations(store, release_assets)
    truth_relations = _truth_relations(store, clean_assets)
    bundle_relations = _truth_relations(store, labels_assets)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    superseded: list[dict[str, Any]] = []
    for source_name, rows in (("pool", pool_relations), ("clean_truth", truth_relations),
                              ("label_bundle", bundle_relations)):
        for row in rows:
            a = str(row.get("a", ""))
            b = str(row.get("b", ""))
            if not a or not b or a == b:
                continue
            key = (a, b) if a <= b else (b, a)
            candidate = {**dict(row), "source": source_name}
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                continue
            if str(existing.get("kind")) == str(candidate.get("kind")):
                continue
            superseded.append({
                "pair": [key[0], key[1]],
                "kept": {"source": existing.get("source"), "kind": existing.get("kind"),
                         "area_mm2": existing.get("area_mm2"), "valid": existing.get("valid")},
                "superseded": {"source": candidate.get("source"),
                               "kind": candidate.get("kind"),
                               "area_mm2": candidate.get("area_mm2"),
                               "valid": candidate.get("valid")},
            })
    relations = [merged[key] for key in sorted(merged)]

    feature_meta: dict[str, dict[str, Any]] = {}
    for record in features:
        meta = dict(record.meta or {})
        fragment_id = str(meta.get("fragment_id") or "")
        if not fragment_id:
            continue
        feature_meta[fragment_id] = {"asset_id": record.asset_id, "meta": meta,
                                     "lineage_id": record.lineage_id, "split": record.split}

    # The relation table is keyed by *fragment* identity, which is a superset of the fragments
    # that carry a delivered observation: a shared-cut event splits one observed body into a
    # modelled mate pair, and both sides are needed for the relation table to be interpretable.
    # Fragments without an observation are still exported (their feature rows are marked
    # invalid by the loader) and every row records which side carries the observation.
    observed_fragments = sorted(obs_by_fragment)
    all_fragments = sorted(set(observed_fragments)
                           | {fid for fid in feature_meta if fid}
                           | {str(fid) for fid in _release_fragment_ids(store, release_assets)})
    index_of = {fid: i for i, fid in enumerate(all_fragments)}
    relation_rows: list[dict[str, Any]] = []
    for row in relations:
        query = str(row.get("a", ""))
        candidate = str(row.get("b", ""))
        if query not in index_of or candidate not in index_of:
            continue
        kind = str(row.get("kind", "UNKNOWN"))
        relation_rows.append({
            "query": query, "candidate": candidate, "kind": kind,
            "area_mm2": float(row.get("area_mm2", 0.0) or 0.0),
            "valid": bool(row.get("valid", False)),
            "loss_mask": bool(row.get("loss_mask", False)),
            "pool_id": str((manifest.get("extra") or {}).get("pool_id", "") or ""),
            "split": _split_of(feature_meta, obs_by_fragment, query),
            "lineage_cluster": _lineage_of(feature_meta, obs_by_fragment, query),
            "eligible_as_negative": bool(kind in NEGATIVE_KINDS
                                         and row.get("valid", False)
                                         and row.get("loss_mask", False)),
            "has_observation": query in obs_by_fragment and candidate in obs_by_fragment,
            "reason": str(row.get("reason", "") or ""),
        })
    relation_rows.sort(key=lambda r: (r["query"], r["candidate"]))

    counts["relations"] = len(relation_rows)
    counts["relation_kinds"] = _kind_counts(relation_rows)
    counts["r2_relations"] = int(sum(1 for r in relation_rows if r["kind"] == "R2"))
    counts["superseded_relations"] = len(superseded)
    counts["queries"] = len(all_fragments)
    counts["fragments_with_observation"] = len(observed_fragments)
    counts["fragments_without_observation"] = len(all_fragments) - len(observed_fragments)
    observed_fragments = all_fragments

    queries_rows = []
    for fragment_id in observed_fragments:
        meta = feature_meta.get(fragment_id, {}).get("meta", {})
        obs = obs_by_fragment.get(fragment_id, {})
        mates = sorted({r["candidate"] for r in relation_rows
                        if r["query"] == fragment_id and r["kind"] == "R2"})
        queries_rows.append({
            # ``fragment_id`` is deliberately not a column: it is a forbidden feature-field name
            # and it would only duplicate ``query_id`` (``q::<fragment_id>``) and ``fragment``.
            # The loader derives the row identity from ``query_id``
            # (``qc.loader_probe._query_fragment``).
            "query_id": f"q::{fragment_id}",
            "lineage": obs.get("lineage_id") or _lineage_of(feature_meta, obs_by_fragment,
                                                            fragment_id),
            "mother": str(meta.get("mother_id", "") or _mother_of(fragment_id)),
            "fragment": str(meta.get("fragment_id", fragment_id) or fragment_id),
            "gallery": str((manifest.get("extra") or {}).get("pool_id", "") or ""),
            "historical_N_G": len(mates),
            "status": "FROZEN",
            "has_observation": fragment_id in obs_by_fragment,
            "applicability": {"views": int(obs.get("views", 0)),
                              "scale_valid": bool(meta.get("scale_valid", False))},
        })

    if "parquet" in formats:
        relations_path = research_root / "relations.parquet"
        _write_parquet(relations_path, relation_rows, relations_per_shard)
        _record(files, relations_path, out, note="research view: relation labels")
        queries_path = deploy_root / "queries.parquet"
        _write_parquet(queries_path, queries_rows, relations_per_shard)
        _record(files, queries_path, out, note="deployment view: query roster without labels")
    else:
        relations_path = research_root / "relations.json"
        relations_path.write_text(json.dumps(relation_rows, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        _record(files, relations_path, out)
        queries_path = deploy_root / "queries.json"
        queries_path.write_text(json.dumps(queries_rows, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        _record(files, queries_path, out)

    deploy_index = deploy_root / "deploy_index.json"
    deploy_index.write_text(json.dumps({
        "schema": "synlab.deploy_index.v1",
        "note": "opaque-name map for the deployment view; contains no label and no split",
        "rows": {fid: {"opaque": _opaque(fid),
                       "obs_shard": (obs_index.get(fid) or {}).get("shard"),
                       "geometry_shard": (geometry_index.get(fid) or {}).get("shard"),
                       "token_shard": (token_index.get(fid) or {}).get("shard")}
                 for fid in observed_fragments},
    }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    _record(files, deploy_index, out)

    # ---------------- layered labels (Clean / Physical / Visible kept apart) -------------
    label_files: list[dict[str, Any]] = []
    if include_truth:
        for layer, assets in (("clean", clean_assets), ("physical", physical_assets),
                              ("visible", visible_role)):
            rows = _label_rows(layer, store, assets)
            if not rows:
                continue
            path = research_root / "labels" / f"{layer}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            if "parquet" in formats:
                _write_parquet(path, rows, relations_per_shard)
            else:
                path = path.with_suffix(".json")
                path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            _record(files, path, out, note=f"research view: {layer} labels")
            label_files.append({"layer": layer, "path": str(path.relative_to(out)).replace("\\", "/"),
                                "rows": len(rows),
                                "assets": [a.asset_id for a in assets]})
        mapping_path = research_root / "labels" / "query_map.json"
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(json.dumps({
            "schema": "synlab.label_query_map.v1",
            "note": "research-only mapping between the opaque observation names and the ids",
            "rows": {_opaque(fid): fid for fid in observed_fragments},
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, mapping_path, out)
    counts["label_layers"] = len(label_files)

    # ---------------- truth separation declaration --------------------------------------
    # The separation claim is *measured on the package that was just written*, never stated:
    # the field scan reads every JSON/parquet/npz/tar container of the deployment view and
    # intersects the keys it finds with ``roles.FORBIDDEN_FEATURE_FIELDS``, and
    # ``contains_truth`` is decided from each view's real content (supervision columns, a
    # non-empty truth-channel list, or an opaque-name -> id map).  Hits and skipped containers
    # travel in the manifest, so a leak cannot be shipped as a clean declaration.
    deploy_files = [f for f in files if f["path"].startswith(VIEW_DEPLOY + "/")]
    research_files = [f for f in files if f["path"].startswith(VIEW_RESEARCH + "/")]
    forbidden_in_deploy = [f["path"] for f in deploy_files
                           if any(token in f["path"].lower()
                                  for token in ("label", "truth", "relation"))]
    if forbidden_in_deploy:
        raise SynLabError(
            ErrorCode.LEAKAGE_DETECTED,
            f"deployment view carries truth-bearing files: {forbidden_in_deploy}",
            stage="export.export_training_package",
            evidence_refs=forbidden_in_deploy,
        )

    deploy_scan = scan_view_fields(deploy_root)
    research_scan = scan_view_fields(research_root)
    forbidden_names = {str(name).lower() for name in FORBIDDEN_FEATURE_FIELDS}
    answer_hits = [{"file": rel, "field": key}
                   for rel, keys in sorted(deploy_scan["keys_by_container"].items())
                   for key in keys if key.lower() in forbidden_names]
    deploy_truth_content = truth_bearing_files(deploy_root, deploy_scan)
    research_truth_content = truth_bearing_files(research_root, research_scan)

    manifest_payload: dict[str, Any] = {
        "schema": PACKAGE_MANIFEST_SCHEMA,
        "package_schema": PACKAGE_SCHEMA,
        "package_id": pkg_id or f"pkg_{release_id}",
        "release_id": release_id,
        "release_manifest_hash": manifest.get("manifest_hash"),
        "release_profile": manifest.get("profile"),
        "release_scope": manifest.get("scope"),
        "release_gates": manifest.get("gates"),
        "release_scope_completed": manifest.get("scope_completed"),
        "release_scope_pending": manifest.get("scope_pending"),
        "formats": list(formats),
        "views": {
            VIEW_DEPLOY: {
                "role": "deployment",
                "purpose": "features only: ObsPack RGB shards, geometry, token cache, query roster",
                # measured from the written content, not declared (see ``separation``)
                "contains_truth": bool(deploy_truth_content),
                "files": len(deploy_files),
                "bytes": int(sum(f["bytes"] for f in deploy_files)),
                "forbidden": ["labels", "relation kinds", "lineage", "split",
                              "depth/id_map/surface_tag channels"],
            },
            VIEW_RESEARCH: {
                "role": "research",
                "purpose": "supervision: relation labels, layered labels, opaque-name map",
                # measured from the written content, not declared (see ``separation``)
                "contains_truth": bool(research_truth_content),
                "files": len(research_files),
                "bytes": int(sum(f["bytes"] for f in research_files)),
            },
        },
        "separation": {
            "deploy_truth_files": forbidden_in_deploy,
            "deploy_truth_content_files": deploy_truth_content,
            "labels_kept_beside_features": True,
            "features_carry_answer_fields": bool(answer_hits),
            "features_carry_answer_fields_source": (
                "content scan of the written deployment view: keys read from its "
                "JSON/parquet/npz/tar containers and intersected with "
                "roles.FORBIDDEN_FEATURE_FIELDS"),
            "answer_field_scan": {
                "view": VIEW_DEPLOY,
                "forbidden_fields": sorted(FORBIDDEN_FEATURE_FIELDS),
                "hits": answer_hits,
                "hits_by_field": _hits_by_field(answer_hits),
                "keys_scanned": deploy_scan["keys_scanned"],
                "unique_keys": len(deploy_scan["unique_keys"]),
                "containers": deploy_scan["containers"],
                "not_read": _grouped_skips(deploy_scan["skipped"]),
            },
            "truth_content_scan": {
                VIEW_DEPLOY: {
                    "contains_truth": bool(deploy_truth_content),
                    "truth_bearing_files": deploy_truth_content,
                    "keys_scanned": deploy_scan["keys_scanned"],
                },
                VIEW_RESEARCH: {
                    "contains_truth": bool(research_truth_content),
                    "truth_bearing_files": research_truth_content,
                    "keys_scanned": research_scan["keys_scanned"],
                },
            },
            "statement": ("the deployment view is safe to ship to an unprivileged loader; the "
                          "research view must never be merged into it"),
        },
        "reference_closure": {
            "ok": bool(closure.get("ok")),
            "assets": int(closure.get("assets", 0)),
            "files_checked": int(closure.get("files_checked", 0)),
            "problems": list(closure.get("problems", [])),
        },
        "assets": {
            "count": len(release_assets),
            "by_role": {role: len(items) for role, items in sorted(by_role.items())},
        },
        "counts": counts,
        "labels": label_files,
        "superseded_relations": superseded,
        "token_cache": {
            "encoder_id": ENCODER_ID,
            "encoder_hash": hash_json({"encoder": ENCODER_ID, "dim": TOKEN_DIM}),
            "input_hash": hash_json({"source": "obspack_rgb", "views": counts.get("obs_views", 0),
                                     "shape": counts.get("obs_bytes", 0)}),
            "crop_hash": hash_json({"crop": "none", "resize": "none", "delivered": "as_rendered"}),
            "token_policy_hash": hash_json({"policy": TOKEN_POLICY_ID, "block": TOKEN_BLOCK,
                                            "dim": TOKEN_DIM}),
        },
        "files": sorted(files, key=lambda f: f["path"]),
        "bytes_total": int(sum(f["bytes"] for f in files)),
        "counts_total": len(files),
        "build": {
            "relations_per_shard": int(relations_per_shard),
            "fragments_per_shard": int(fragments_per_shard),
            "include_truth": bool(include_truth),
            "obs_view_limit": obs_view_limit,
        },
    }
    manifest_payload["manifest_hash"] = hash_json(
        {k: v for k, v in manifest_payload.items() if k != "manifest_hash"})
    manifest_path = out / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2,
                                        sort_keys=True), encoding="utf-8")
    return manifest_payload


def _npy_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(array), allow_pickle=False)
    return buffer.getvalue()


def _pool_relations(store: AssetStore,
                    release_assets: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The authoritative pair table from every ``relation_pool`` asset in scope.

    A pool asset stores its sparse index as index arrays over ``fragment_ids``; this rebuilds
    the ``{"a","b","kind",...}`` rows from them.
    """
    kind_by_code = {0: "R0", 1: "R1", 2: "R2", 3: "TINY_CONTACT", 4: "UNKNOWN"}
    rows: list[dict[str, Any]] = []
    for asset_id in release_assets:
        record = store.get_asset(asset_id)
        if record.role != ROLE_POOL:
            continue
        arrays = store.load_arrays(asset_id)
        ids = [str(x) for x in np.asarray(
            arrays.get("fragment_ids", np.zeros(0, dtype="U1"))).tolist()]
        a = np.asarray(arrays.get("rel_a", np.zeros(0, dtype=np.int32)), dtype=np.int64)
        b = np.asarray(arrays.get("rel_b", np.zeros(0, dtype=np.int32)), dtype=np.int64)
        kind = np.asarray(arrays.get("rel_kind", np.zeros(0, dtype=np.int8)), dtype=np.int64)
        area = np.asarray(arrays.get("rel_area_mm2", np.zeros(a.size, dtype=np.float32)),
                          dtype=np.float64)
        iface = np.asarray(arrays.get("rel_interface", np.full(a.size, -1, dtype=np.int32)),
                           dtype=np.int64)
        valid = np.asarray(arrays.get("rel_valid", np.ones(a.size, dtype=bool)), dtype=bool)
        loss = np.asarray(arrays.get("rel_loss_mask", np.ones(a.size, dtype=bool)), dtype=bool)
        for i in range(a.size):
            ia, ib = int(a[i]), int(b[i])
            if ia >= len(ids) or ib >= len(ids) or ia == ib:
                continue
            rows.append({
                "a": ids[ia], "b": ids[ib],
                "kind": kind_by_code.get(int(kind[i]), "UNKNOWN"),
                "area_mm2": float(area[i]), "valid": bool(valid[i]),
                "loss_mask": bool(loss[i]),
                "interface_id": None if int(iface[i]) < 0 else int(iface[i]),
                "pool_asset": record.asset_id,
            })
    return rows


def _mother_of(fragment_id: str) -> str:
    """``<mother>_E<nn>-m`` -> ``<mother>`` (event ids carry the mother id as their prefix)."""
    text = str(fragment_id)
    marker = "_E"
    if marker in text:
        head, _, tail = text.rpartition(marker)
        if tail[:1].isdigit():
            return head
    return ""


def _release_fragment_ids(store: AssetStore, release_assets: Mapping[str, Any]) -> list[str]:
    """Every fragment id named by the release's clean/physical truth and label assets."""
    out: set[str] = set()
    for asset_id in release_assets:
        record = store.get_asset(asset_id)
        if record.role not in (ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH, ROLE_LABEL_BUNDLE):
            continue
        meta = dict(record.meta or {})
        for fragment_id in meta.get("fragment_ids") or []:
            out.add(str(fragment_id))
        fragment_id = meta.get("fragment_id")
        if fragment_id:
            out.add(str(fragment_id))
        raw = meta.get("relations")
        if raw is None and isinstance(meta.get("relations_json"), str):
            raw = json.loads(meta["relations_json"])
        for row in raw or []:
            if isinstance(row, Mapping):
                for key in ("a", "b", "fragment_a", "fragment_b"):
                    if row.get(key):
                        out.add(str(row[key]))
    return sorted(out)


def _split_of(feature_meta: Mapping[str, Any], obs: Mapping[str, Any], fragment_id: str) -> str:
    if fragment_id in feature_meta:
        return str(feature_meta[fragment_id].get("split") or "")
    return str((obs.get(fragment_id) or {}).get("split") or "")


def _lineage_of(feature_meta: Mapping[str, Any], obs: Mapping[str, Any], fragment_id: str) -> str:
    if fragment_id in feature_meta:
        return str(feature_meta[fragment_id].get("lineage_id") or "")
    return str((obs.get(fragment_id) or {}).get("lineage_id") or "")


def _kind_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("kind", "UNKNOWN"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _label_rows(layer: str, store: AssetStore, assets: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in assets:
        meta = dict(record.meta or {})
        fragment_ids = [str(x) for x in (meta.get("fragment_ids") or [])]
        if not fragment_ids:
            fragment_ids = [str(meta.get("fragment_id", "") or "")]
        base = {
            "label_layer": layer,
            "asset_id": record.asset_id,
            "lineage": record.lineage_id,
            "split": record.split,
            "passed": bool((record.qa or {}).get("pass", record.qa_status == QA_PASS)),
        }
        relations = meta.get("relations")
        if relations is None and isinstance(meta.get("relations_json"), str):
            relations = json.loads(meta["relations_json"])
        for fragment_id in fragment_ids:
            rows.append({**base, "fragment_id": fragment_id, "role": "fragment",
                         "detail": json.dumps(
                             {"passed": base["passed"],
                              "relations": len(relations or [])}, ensure_ascii=False)})
        for relation in relations or []:
            rows.append({
                **base, "fragment_id": str(relation.get("a", "")), "role": "relation",
                "candidate_id": str(relation.get("b", "")),
                "kind": str(relation.get("kind", "")),
                "area_mm2": float(relation.get("area_mm2", 0.0) or 0.0),
                "valid": bool(relation.get("valid", False)),
                "loss_mask": bool(relation.get("loss_mask", False)),
                "reason": str(relation.get("reason", "")),
                "unique_source_triangle": bool(relation.get("unique_source_triangle", False)),
                "detail": json.dumps(_jsonable(relation), ensure_ascii=False),
            })
        for key in ("correspondence_samples", "visible_fraction", "samples_visible"):
            if key in meta:
                rows.append({**base, "fragment_id": fragment_ids[0], "role": "summary",
                             "detail": json.dumps({key: _jsonable(meta[key])},
                                                  ensure_ascii=False)})
    return rows


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]], row_group_size: int) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        rows = [{"empty": True}]
    columns: dict[str, list[Any]] = {}
    for row in rows:
        for key in row:
            columns.setdefault(key, [])
    for key in columns:
        columns[key] = [_jsonable(row.get(key)) for row in rows]
    table = pa.Table.from_pydict(columns)
    pq.write_table(table, path, row_group_size=max(int(row_group_size), 1), compression="snappy")


def _write_zarr(store_root: Path, geometry: Mapping[str, Mapping[str, np.ndarray]]) -> None:
    """A tiny, dependency-light zarr replica: one 1-D array per fragment/array, JSON attrs.

    ``store_root`` is produced by :func:`_zarr_root`, never spelled here.
    """
    import zarr

    store_root = Path(store_root)
    store_root.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store_root), mode="w")
    for fragment_id in sorted(geometry):
        opaque = _opaque(fragment_id)
        sub = group.create_group(opaque)
        for key, array in sorted(geometry[fragment_id].items()):
            sub.create_array(key, data=array, overwrite=True)
    group.attrs["schema"] = "synlab.geometry.zarr.v1"
    group.attrs["arrays"] = ["points", "normals", "point_valid", "normal_valid",
                            "scale_valid", "frame_id"]


# --------------------------------------------------------------------------------------
# separation evidence: measure the package that was just written
# --------------------------------------------------------------------------------------
#: Content signals that make a packaged file *truth-bearing*: the supervision column names the
#: exporter itself writes on the research side (relation labels, layered labels).  They are
#: looked up in the real files of a view -- a declaration is never the evidence.
TRUTH_BEARING_FIELDS = frozenset({
    "kind", "loss_mask", "eligible_as_negative", "label_layer", "candidate", "candidate_id",
    "query", "area_mm2", "reason", "lineage_cluster", "unique_source_triangle",
    "relation", "relations", "labels",
})

#: Storage-format metadata (zarr v2/v3) describes *how* an array is chunked and compressed; its
#: keys (the zstd codec's ``level``, ``chunk_grid``, ...) are the format's vocabulary, not the
#: package's fields.  Such files are skipped by the field scan, and every skip is recorded in
#: the manifest instead of being silent.
STORAGE_METADATA_NAMES = frozenset({"zarr.json", ".zarray", ".zattrs", ".zgroup",
                                    ".zmetadata"})


def _looks_opaque(name: Any) -> bool:
    """``sha256(fragment id)[:24]`` -- the deployment view's opaque name form."""
    text = str(name)
    return len(text) == 24 and all(char in "0123456789abcdef" for char in text)


def _field_name(raw: str) -> str:
    """``<opaque>__points`` -> ``points``; ``<opaque>/tiles.npy`` -> ``tiles``."""
    text = str(raw).replace("\\", "/").rsplit("/", 1)[-1]
    if "__" in text:
        text = text.rsplit("__", 1)[-1]
    for suffix in (".npy", ".npz", ".json"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def _json_key_set(node: Any, out: set[str]) -> None:
    """Every object key at every depth of a JSON document."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            out.add(str(key))
            _json_key_set(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _json_key_set(item, out)


def _container_fields(path: Path) -> tuple[set[str] | None, str]:
    """Field names one real file carries, or ``(None, reason)`` when it carries none."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            out: set[str] = set()
            _json_key_set(json.loads(path.read_text(encoding="utf-8")), out)
            return out, ""
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            return {str(name) for name in pq.read_schema(path).names}, ""
        if suffix == ".npz":
            with np.load(path, allow_pickle=False) as data:
                return {_field_name(name) for name in data.files}, ""
        if suffix == ".tar":
            with tarfile.open(path, "r") as tar:
                return ({_field_name(member.name) for member in tar.getmembers()
                         if member.isfile()}, "")
    except Exception as exc:  # noqa: BLE001 - recorded in the manifest, never dropped
        return None, f"{type(exc).__name__}: {exc}"
    return None, "binary payload (carries no field name)"


def _zarr_declared_arrays(zarr_root: Path) -> set[str]:
    """Array names a written zarr replica declares (read from its own group attributes)."""
    root = Path(zarr_root)
    meta = root / "zarr.json"
    if not meta.exists():
        return set()
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    attrs = payload.get("attributes") if isinstance(payload, Mapping) else None
    declared = attrs.get("arrays") if isinstance(attrs, Mapping) else None
    if isinstance(declared, (list, tuple)):
        return {str(item) for item in declared}
    return {child.name for child in root.iterdir() if child.is_dir()}


def scan_view_fields(view_root: Path) -> dict[str, Any]:
    """Read every container of one view and return the field names it really carries.

    JSON metadata documents contribute every object key at every depth, parquet tables their
    column names, ``npz`` archives their array names and tar shards their member names; a zarr
    replica contributes the array names it declares.  ``keys_scanned`` is the denominator of the
    separation claim, ``skipped`` names what could not be read (and why).
    """
    containers: dict[str, int] = {}
    keys_by_container: dict[str, list[str]] = {}
    skipped: list[dict[str, str]] = []
    fields: set[str] = set()
    root = Path(view_root)
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            if path.name in STORAGE_METADATA_NAMES:
                skipped.append({"file": rel, "reason": "storage-format metadata "
                                                       "(zarr chunk/compression vocabulary)"})
                continue
            found, reason = _container_fields(path)
            if found is None:
                skipped.append({"file": rel, "reason": reason})
                continue
            keys_by_container[rel] = sorted(found)
            containers[rel] = len(found)
            fields |= found
        declared = _zarr_declared_arrays(_zarr_root(root))
        if declared:
            label = f"{ZARR_DIR_NAME}/* (declared array names)"
            keys_by_container[label] = sorted(declared)
            containers[label] = len(declared)
            fields |= declared
    return {
        "containers": containers,
        "keys_by_container": keys_by_container,
        "keys_scanned": int(sum(containers.values())),
        "unique_keys": sorted(fields),
        "skipped": skipped,
    }


def _declares_truth_channels(node: Any) -> bool:
    """A non-empty ``truth_channels`` list: the document says a truth channel is carried."""
    if isinstance(node, Mapping):
        channels = node.get("truth_channels")
        if isinstance(channels, (list, tuple)) and len(channels) > 0:
            return True
        return any(_declares_truth_channels(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(_declares_truth_channels(item) for item in node)
    return False


def _maps_opaque_names_to_ids(node: Any) -> bool:
    """The answer to the deployment view's opaque naming: ``{opaque: real id}``."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            if _looks_opaque(key) and isinstance(value, str) and not _looks_opaque(value):
                return True
        return any(_maps_opaque_names_to_ids(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(_maps_opaque_names_to_ids(item) for item in node)
    return False


def _truth_signal(path: Path) -> str | None:
    """One file's content-level truth signal, or ``None`` when its own content has none."""
    if path.suffix.lower() != ".json" or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if _declares_truth_channels(payload):
        return "declares truth channels"
    if _maps_opaque_names_to_ids(payload):
        return "maps the deployment view's opaque names back to real ids"
    return None


def truth_bearing_files(view_root: Path, scan: Mapping[str, Any]) -> list[dict[str, str]]:
    """Files of one view whose *real content* carries supervision or the answer."""
    out: list[dict[str, str]] = []
    for rel, keys in sorted((scan.get("keys_by_container") or {}).items()):
        supervision = sorted(set(keys) & TRUTH_BEARING_FIELDS)
        if supervision:
            out.append({"file": rel,
                        "reason": "carries supervision fields: " + ", ".join(supervision)})
            continue
        signal = _truth_signal(Path(view_root) / rel)
        if signal:
            out.append({"file": rel, "reason": signal})
    return out


def _grouped_skips(skipped: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Group the scan's unreadable containers by reason (keeps the manifest readable)."""
    by_reason: dict[str, list[str]] = {}
    for entry in skipped:
        by_reason.setdefault(str(entry.get("reason", "")), []).append(str(entry.get("file", "")))
    return [{"reason": reason, "files": len(files), "examples": sorted(files)[:5]}
            for reason, files in sorted(by_reason.items())]


def _hits_by_field(hits: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for hit in hits:
        out.setdefault(str(hit["field"]), []).append(str(hit["file"]))
    return {name: sorted(set(files)) for name, files in sorted(out.items())}


# --------------------------------------------------------------------------------------
# reading a package back (used by synlab.qc.loader_probe)
# --------------------------------------------------------------------------------------
class TrainingPackage:
    """Reader for a package written by :func:`export_training_package`."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        manifest_path = self.root / "export_manifest.json"
        if not manifest_path.exists():
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              f"training package manifest not found: {manifest_path}",
                              stage="export.TrainingPackage")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored = self.manifest.get("manifest_hash")
        recomputed = hash_json({k: v for k, v in self.manifest.items()
                                if k != "manifest_hash"})
        if stored != recomputed:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              "training package manifest was modified after export",
                              stage="export.TrainingPackage")
        self.deploy = self.root / VIEW_DEPLOY
        self.research = self.root / VIEW_RESEARCH

    # ---------------------------------------------------------------- integrity
    def verify_files(self) -> dict[str, Any]:
        problems: list[str] = []
        checked = 0
        for entry in self.manifest.get("files", []):
            path = self.root / entry["path"]
            if not path.exists():
                problems.append(f"{entry['path']} missing")
                continue
            if hash_file(path) != entry["hash"]:
                problems.append(f"{entry['path']} hash mismatch")
            checked += 1
        return {"ok": not problems, "problems": problems, "files_checked": checked}

    # ---------------------------------------------------------------- relations
    def relations(self) -> list[dict[str, Any]]:
        return self._table(self.research / "relations.parquet", self.research / "relations.json")

    def queries(self) -> list[dict[str, Any]]:
        return self._table(self.deploy / "queries.parquet", self.deploy / "queries.json")

    def labels(self, layer: str) -> list[dict[str, Any]]:
        return self._table(self.research / "labels" / f"{layer}.parquet",
                           self.research / "labels" / f"{layer}.json")

    @staticmethod
    def _table(parquet: Path, fallback: Path) -> list[dict[str, Any]]:
        if parquet.exists():
            import pyarrow.parquet as pq

            return pq.read_table(parquet).to_pylist()
        if fallback.exists():
            return json.loads(fallback.read_text(encoding="utf-8"))
        return []

    # ---------------------------------------------------------------- observations
    def observation_index(self) -> dict[str, Any]:
        path = self.deploy / "obs" / "index.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": {}}

    def read_observation(self, fragment_id: str) -> dict[str, np.ndarray]:
        rows = self.observation_index().get("rows", {})
        entry = rows.get(fragment_id)
        if entry is None:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              f"fragment {fragment_id!r} is not in the observation index",
                              stage="export.TrainingPackage.read_observation")
        shard = self.deploy / entry["shard"]
        with tarfile.open(shard, "r") as tar:
            out = {}
            for suffix, key, dtype in (("tiles.npy", "rgb", np.uint8),
                                       ("valid.npy", "valid", bool),
                                       ("view_pos.npy", "view_pos", np.float32)):
                member = tar.extractfile(f"{entry['opaque']}/{suffix}")
                if member is None:
                    raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                                      f"{shard.name}:{entry['opaque']}/{suffix} missing",
                                      stage="export.TrainingPackage.read_observation")
                out[key] = np.load(io.BytesIO(member.read()), allow_pickle=False).astype(dtype)
        return out

    # ---------------------------------------------------------------- geometry/tokens
    def read_geometry(self, fragment_id: str) -> dict[str, np.ndarray]:
        return self._read_shard("geometry/index.json", self.deploy, fragment_id)

    def read_tokens(self, fragment_id: str) -> dict[str, np.ndarray]:
        return self._read_shard("tokens/index.json", self.deploy, fragment_id)

    def _read_shard(self, index_rel: str, root: Path, fragment_id: str) -> dict[str, np.ndarray]:
        path = root / index_rel
        if not path.exists():
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, f"index missing: {path}",
                              stage="export.TrainingPackage._read_shard")
        index = json.loads(path.read_text(encoding="utf-8"))
        entry = (index.get("rows") or {}).get(fragment_id)
        if entry is None:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              f"fragment {fragment_id!r} is not in {index_rel}",
                              stage="export.TrainingPackage._read_shard")
        with np.load(root / entry["shard"], allow_pickle=False) as data:
            prefix = f"{entry['opaque']}__"
            return {k[len(prefix):]: data[k] for k in data.files if k.startswith(prefix)}


__all__ = [
    "REGISTERED_FORMATS", "TRAINING_FORMATS", "PACKAGE_SCHEMA", "PACKAGE_MANIFEST_SCHEMA",
    "VIEW_DEPLOY", "VIEW_RESEARCH", "VIEWS", "NEGATIVE_KINDS", "EXCLUDED_NEGATIVE_KINDS",
    "TOKEN_DIM", "TOKEN_POLICY_ID", "ENCODER_ID", "ZARR_DIR_NAME", "TRUTH_BEARING_FIELDS",
    "export_release", "export_training_package", "TrainingPackage",
    "scan_view_fields", "truth_bearing_files",
]
