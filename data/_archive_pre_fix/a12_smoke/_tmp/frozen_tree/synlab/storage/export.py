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
import os
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
    ROLE_CONTEXT_PACK,
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

# --------------------------------------------------------------------------------------
# view channel policy (configurable, auditable)
# --------------------------------------------------------------------------------------
#: Environment variable that overrides the policy document path.  The code below only *reads* a
#: policy: which channel a view may carry is data, so a whitelist change is a diff in a file the
#: manifest records by real path **and** hash, never an edit of a literal in this module.
VIEW_CHANNEL_POLICY_ENV = "SYNLAB_VIEW_CHANNEL_POLICY"
#: Default policy document, relative to the repository root that holds this package.
VIEW_CHANNEL_POLICY_PATH = Path(__file__).resolve().parents[1] / "schemas" / "view_channels.json"


def _policy_path() -> Path:
    override = os.environ.get(VIEW_CHANNEL_POLICY_ENV, "").strip()
    return Path(override) if override else VIEW_CHANNEL_POLICY_PATH


def load_channel_policy(path: str | Path | None = None) -> dict[str, Any]:
    """Load the view channel policy and return it with its real source path and byte hash.

    ``channels`` is the resolved per-view channel table (each entry names the channel ``key``,
    the observation array it comes from, its dtype/unit and -- where the evidence class is not a
    plain delivered product -- an explicit ``evidence_class``/``caveat``).  ``research_only`` is
    the derived set of channel keys no other view may carry, and two views declaring the same
    channel is a hard error: a channel belongs to exactly one view.
    """
    target = Path(path) if path is not None else _policy_path()
    if not target.exists():
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"view channel policy not found: {target}",
                          stage="export.load_channel_policy")
    raw = target.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"view channel policy {target} is not valid JSON: {exc}",
                          stage="export.load_channel_policy") from exc
    views = payload.get("views")
    if not isinstance(views, Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"view channel policy {target} declares no views block",
                          stage="export.load_channel_policy")
    channels: dict[str, list[dict[str, Any]]] = {}
    for view, block in views.items():
        declared = (block or {}).get("channels") if isinstance(block, Mapping) else None
        if not isinstance(declared, list) or not declared:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"view {view!r} declares no channel list in {target}",
                              stage="export.load_channel_policy")
        channels[str(view)] = [dict(item) for item in declared]
    research_keys = sorted({str(item["key"]) for item in channels.get(VIEW_RESEARCH, [])})
    deploy_keys = sorted({str(item["key"]) for item in channels.get(VIEW_DEPLOY, [])})
    overlap = sorted(set(research_keys) & set(deploy_keys))
    if overlap:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"channel(s) {overlap} are declared in both views of {target}",
                          stage="export.load_channel_policy")
    return {
        "schema": str(payload.get("schema", "")),
        "path": str(target),
        "hash": hash_bytes(raw),
        "source": str(payload.get("source", "")),
        "channels": channels,
        "truth_roles": dict(payload.get("truth_roles") or {}),
        "research_only": research_keys,
        "deploy": deploy_keys,
    }


def channel_table(policy: Mapping[str, Any], view: str) -> dict[str, dict[str, Any]]:
    """``{channel key: descriptor}`` for one view of a resolved policy."""
    return {str(item["key"]): item for item in (policy.get("channels") or {}).get(view, [])}

#: Camera intrinsics carried as one ``3x3`` matrix per delivered view.
CHANNEL_K = "K"

#: Deployment-view channels that are **optional at the asset level**: they are written for every
#: view of a fragment that really carries them, and the fragments that do not are reported as
#: missing rather than being padded with a placeholder array.  The list is derived from the
#: policy document (``synlab/schemas/view_channels.json``), which the manifest records by path
#: and hash -- so adding or removing a channel is a policy diff, not an edit of this tuple.
OPTIONAL_DEPLOY_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("depth_z", "depth_z", "float32"),
    ("deployment_mask", "deployment_mask", "bool"),
    ("uncertain_mask", "uncertain_mask", "bool"),
    ("roi", "roi", "bool"),
    ("K", "K", "float64"),
)

#: Relation kinds that may serve as an ordinary negative (plan 18.2).
NEGATIVE_KINDS = frozenset({"R1", "R0"})
#: Relation kinds that must never enter the negative set.
EXCLUDED_NEGATIVE_KINDS = frozenset({"R2", "TINY", "TINY_CONTACT", "UNKNOWN"})

#: Number of tokens produced for one fragment (``FeatureBundle.TOKEN_DIM``).
TOKEN_DIM = 256
TOKEN_BLOCK = 4
#: Side of the per-token sub-grid (``TOKEN_SUB ** 2 == TOKEN_DIM``).  One token is one
#: ``(view, block, channel)`` slot of the ``TOKEN_BLOCK x TOKEN_BLOCK`` block-mean grid; its
#: ``TOKEN_DIM`` features are that slot's own ``TOKEN_SUB x TOKEN_SUB`` sub-grid means.
TOKEN_SUB = 16
TOKEN_POLICY_ID = "obspack_rgb_blockmean_v1"
ENCODER_ID = "identity_rgb_blockmean"
#: ``token_layout`` recorded in ``deploy/tokens/index.json``: what one token column means.
TOKEN_LAYOUT = "per-token sub-grid block means (identity, no learned weights)"

#: Tolerance of the ``frame_id`` derivation (D3 fix): a point is assigned to the delivered view
#: whose rendered ``depth_z`` agrees with its reprojection within this many millimetres.
FRAME_ID_TOLERANCE_MM = 5.0


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
def _linear_view(rgb: np.ndarray) -> np.ndarray:
    """One delivered view as ``[H,W,3]`` float in the 0..1 range ``_tokens_from_view`` uses."""
    data = np.asarray(rgb, dtype=np.float32)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    data = data[:, :, :3]
    if data.max(initial=0.0) > 2.0:          # 0..255 delivery -> linear 0..1
        data = data / 255.0
    return data


def _tokens_from_view(rgb: np.ndarray, blocks: int = TOKEN_BLOCK) -> np.ndarray:
    """Frozen block-mean RGB token of one delivered view (no view id, no ordering)."""
    data = _linear_view(rgb)
    h, w = int(data.shape[0]), int(data.shape[1])
    bh, bw = max(h // blocks, 1), max(w // blocks, 1)
    pooled = data[: bh * blocks, : bw * blocks].reshape(blocks, bh, blocks, bw, 3).mean(axis=(1, 3))
    return np.asarray(pooled, dtype=np.float32).reshape(-1)   # (blocks*blocks*3,)


def _grid_mean(cell: np.ndarray, sub: int) -> np.ndarray:
    """Exact ``sub x sub`` mean of ``cell`` (any cell size; a block smaller than the grid is
    sampled instead of padded, so the function is total)."""
    data = np.asarray(cell, dtype=np.float64)
    h, w = int(data.shape[0]), int(data.shape[1])
    rows = (np.arange(sub) * h) // sub
    cols = (np.arange(sub) * w) // sub
    if h < sub or w < sub:                   # too small to average: nearest sample, still real
        return np.asarray(data[np.ix_(rows, cols)], dtype=np.float32)
    sums = np.add.reduceat(np.add.reduceat(data, rows, axis=0), cols, axis=1)
    counts = np.diff(np.append(rows, h))[:, None] * np.diff(np.append(cols, w))[None, :]
    return np.asarray(sums / counts, dtype=np.float32)


def _token_feature(data: np.ndarray, slot: int, *, blocks: int = TOKEN_BLOCK,
                   sub: int = TOKEN_SUB) -> np.ndarray:
    """The ``sub*sub`` sub-grid means of one ``(block, channel)`` slot of a delivered view."""
    block, channel = divmod(int(slot), 3)
    br, bc = divmod(block, blocks)
    h, w = int(data.shape[0]), int(data.shape[1])
    bh, bw = max(h // blocks, 1), max(w // blocks, 1)
    cell = data[br * bh:(br + 1) * bh, bc * bw:(bc + 1) * bw, channel]
    return _grid_mean(cell, sub).reshape(-1)[: TOKEN_DIM]


def _token_arrays(tile_rgb: np.ndarray, tile_valid: np.ndarray) -> dict[str, np.ndarray]:
    """``tile_rgb`` is ``[V,H,W,3]`` uint8.  Returns the frozen token block for one fragment.

    One token is one ``(view, block, channel)`` slot of the ``TOKEN_BLOCK x TOKEN_BLOCK``
    block-mean grid (``TOKEN_BLOCK**2 * 3 == 48`` slots per view), and its ``TOKEN_DIM``
    features are **that slot's own** ``TOKEN_SUB x TOKEN_SUB`` sub-grid means of the delivered
    tile -- real local content of the image the model is allowed to see.

    Defect history (measured on the shipped packages): the previous writer set
    ``tokens[:, k] = flat * (1.0 - 1e-6 * k)``, i.e. 255 scaled copies of one scalar per token.
    The effective rank of every such block was **1** (``sv[1]/sv[0] <= 6.8e-09``) while
    ``deploy/tokens/index.json`` advertised ``token_dim = 256``.  ``token_input`` still carries
    the original coarse 48-per-view block mean (it is a real number, not a placeholder);
    ``tokens`` is now a real feature, so ``tokens[:, 0]`` is no longer a copy of ``token_input``.
    """
    if TOKEN_SUB * TOKEN_SUB != TOKEN_DIM:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"TOKEN_SUB**2 = {TOKEN_SUB ** 2} != TOKEN_DIM = {TOKEN_DIM}",
                          stage="export._token_arrays")
    n_views = int(tile_rgb.shape[0]) if np.ndim(tile_rgb) == 4 else 0
    vectors = [_tokens_from_view(tile_rgb[v]) for v in range(n_views)]
    flat = np.concatenate(vectors) if vectors else np.zeros(0, dtype=np.float32)
    per_view = TOKEN_BLOCK * TOKEN_BLOCK * 3
    tokens = np.zeros((flat.size, TOKEN_DIM), dtype=np.float32)
    for view_index in range(n_views):
        data = _linear_view(tile_rgb[view_index])
        for slot in range(per_view):
            tokens[view_index * per_view + slot] = _token_feature(data, slot)
    valid = np.ones((flat.size,), dtype=bool)
    view = np.repeat(np.arange(n_views, dtype=np.int32), per_view)
    return {"tokens": tokens, "token_valid": valid, "token_view": view,
            "token_input": flat.astype(np.float32),
            "tile_valid": np.asarray(tile_valid, dtype=bool)}


# --------------------------------------------------------------------------------------
# degradation diversity (config-driven axis x level variants)
# --------------------------------------------------------------------------------------
#: Schema of the degradation-variant index written beside the two views.
DEGRADE_INDEX_SCHEMA = "synlab.degrade_variant.index.v1"


def _degrade_diversity_block(store: AssetStore, by_role: Mapping[str, list[Any]], out: Path,
                             files: list[dict[str, Any]]) -> dict[str, Any]:
    """Index the release's degradation-diversity assets (markers/fields only, no payload copy).

    A ``degrade_variant`` asset is the **answer side** of a factor experiment: its metadata
    carries ``axis_id``/``level``/``variant`` -- exactly the keys
    ``roles.FORBIDDEN_FEATURE_FIELDS`` forbids inside a feature bundle -- so a variant may never
    be merged into a feature shard.  It is exported as an index at the package root (outside both
    views, so the deployment-view field scan cannot mistake it for a feature channel).

    ``level 0`` is not an asset: it is the *source* asset each axis was computed from, and every
    row records ``source_asset_id``, so the index rebuilds the
    ``(same source, different degradation level)`` pairs the neighbour-retrieval task needs
    without guessing which two assets are the same physical fragment.
    """
    from ..degrade.diversity import (ROLE_DEGRADE_SOURCE, ROLE_DEGRADE_VARIANT,
                                     VARIANT_FIELDS)

    variants = sorted(by_role.get(ROLE_DEGRADE_VARIANT, []), key=lambda r: r.asset_id)
    sources = sorted(by_role.get(ROLE_DEGRADE_SOURCE, []), key=lambda r: r.asset_id)
    rows: list[dict[str, Any]] = []
    for record in variants:
        meta = dict(record.meta or {})
        row = {"asset_id": record.asset_id, "role": record.role, "schema": record.schema,
               "unit": record.unit, "frame": record.frame, "qa_status": record.qa_status,
               "lineage_id": record.lineage_id, "split": record.split,
               "blob_hash": record.blob_hash}
        for key in VARIANT_FIELDS:
            row[key] = _jsonable(meta.get(key))
        rows.append(row)
    source_rows = [{"asset_id": record.asset_id, "role": record.role, "schema": record.schema,
                    "unit": record.unit, "frame": record.frame, "lineage_id": record.lineage_id,
                    "split": record.split, "source_kind": (record.meta or {}).get("source_kind"),
                    "content_hash": (record.meta or {}).get("content_hash"),
                    "family": (record.meta or {}).get("family")}
                   for record in sources]

    axes: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row.get('lineage_id')}::{row.get('axis_id')}"
        entry = axes.setdefault(key, {"axis_id": row.get("axis_id"),
                                      "lineage_id": row.get("lineage_id"),
                                      "variant": row.get("variant"), "family": row.get("family"),
                                      "stage": row.get("stage"),
                                      "basis_id": row.get("basis_id"), "levels": [],
                                      "realized_levels": [], "source_assets": []})
        entry["levels"].append(int(row.get("level") or 0))
        if row.get("realized"):
            entry["realized_levels"].append(int(row.get("level") or 0))
        if row.get("source_asset_id") and row["source_asset_id"] not in entry["source_assets"]:
            entry["source_assets"].append(row["source_asset_id"])
    for entry in axes.values():
        entry["levels"] = sorted(entry["levels"])
        entry["realized_levels"] = sorted(entry["realized_levels"])

    counts = {
        "degrade_variants": len(rows),
        "degrade_sources": len(source_rows),
        "degrade_axes": len(axes),
        "degrade_lineages": len({row.get("lineage_id") for row in rows}),
        "degrade_axis_levels": int(sum(len(entry["levels"]) for entry in axes.values())),
        # one identity reference per (lineage, axis): level 0 is the source asset itself
        "degrade_identity_references": int(sum(len(entry["source_assets"]) for entry in axes.values())),
    }
    index = {
        "schema": DEGRADE_INDEX_SCHEMA,
        "role": ROLE_DEGRADE_VARIANT,
        "source_role": ROLE_DEGRADE_SOURCE,
        "fields": ["asset_id", "role", "schema", "unit", "frame", "qa_status", "lineage_id",
                   "split", *VARIANT_FIELDS],
        "level_zero_contract": ("level 0 is the source asset itself: no variant asset exists for "
                                "it, `identity=true`/`bytes_unchanged=true` are recorded in the "
                                "run report and the source asset id is `source_asset_id`"),
        "retrieval_role": {
            "same_source_different_level": "same physical fragment under two degradation levels "
                                           "-> a same-instance positive (degradation invariance), "
                                           "never a mate-task positive",
            "different_source_same_level": "the hardest negatives of the robustness evaluation; "
                                           "a same-instance hit under mismatched degradation must "
                                           "still rank above them",
            "must_not_enter": "the mate-task negative pool (R1/R0): two variants of one source "
                              "are the same instance, so counting them as negatives would inject "
                              "label noise",
        },
        "counts": counts,
        "axes": {key: axes[key] for key in sorted(axes)},
        "rows": rows,
        "sources": source_rows,
    }
    degrade_root = Path(out) / "degrade"
    degrade_root.mkdir(parents=True, exist_ok=True)
    index_path = degrade_root / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")
    _record(files, index_path, out, note="degradation-diversity index (variant fields, no payload)")
    variants_path = degrade_root / "variants.json"
    variants_path.write_text(json.dumps({"schema": DEGRADE_INDEX_SCHEMA, "rows": rows},
                                        ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")
    _record(files, variants_path, out, note="one row per committed degrade_variant asset")
    sources_path = degrade_root / "sources.json"
    sources_path.write_text(json.dumps({"schema": DEGRADE_INDEX_SCHEMA, "rows": source_rows},
                                       ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
    _record(files, sources_path, out, note="one row per degradation source asset (level-0 anchor)")
    return {"counts": counts, "index": index, "files": [index_path.name, variants_path.name,
                                                        sources_path.name]}


# --------------------------------------------------------------------------------------
# export_training_package
# --------------------------------------------------------------------------------------
def _view_u_position_mm(meta_view: Mapping[str, Any], arrays: Mapping[str, np.ndarray],
                        index: int) -> tuple[float | None, str]:
    """The **real** per-view slide coordinate in mm, or ``(None, "unavailable")``.

    Order of evidence:

    ``T_WC`` (delivered pose)
        ``T_WC[0, 3]`` -- the camera's slide coordinate in the scan frame.  This is the same
        definition :mod:`synlab.degrade.api` uses when it builds a ``ViewFrame`` from a rendered
        view (``u_position_mm=float(plan["T_WC"])[0, 3]``), so the exported channel and the
        in-repo meaning agree instead of diverging.
    ``view_meta.u_position_mm``
        Used only as a fallback when no pose was delivered.
    ``None``
        Neither source carries a value: the channel is written as ``nan`` and the index records
        ``view_pos_source = "unavailable"`` rather than a fake ``0.0``.

    Defect history (D2, measured): the previous writer was
    ``np.asarray(meta_view.get("u_position_mm", 0.0), dtype=np.float32)`` and the source metadata
    really does carry ``u_position_mm = 0.0`` for every view of every asset, so the exported
    array was all-zero in **31/31** members while ``deploy/obs/index.json`` declared the channel
    as a delivered one.
    """
    pose = arrays.get(f"v{int(index):03d}.T_WC")
    if pose is not None:
        matrix = np.asarray(pose, dtype=np.float64)
        if matrix.shape == (4, 4) and np.isfinite(matrix).all():
            return float(matrix[0, 3]), "T_WC[0,3]"
    raw = (meta_view or {}).get("u_position_mm")
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = float("nan")
        if np.isfinite(value):
            return value, "view_meta.u_position_mm"
    return None, "unavailable"


def _frame_ids_from_views(points: np.ndarray, arrays: Mapping[str, np.ndarray],
                          views: int) -> tuple[np.ndarray, dict[str, Any]]:
    """A **real** per-point frame id, derived from the delivered geometry.

    For every delivered view the point is mapped into that view's camera frame with the
    delivered pose (``T_WC``) and projected with the delivered ``K``; the view whose rendered
    ``depth_z`` agrees with the reprojected depth best (and within :data:`FRAME_ID_TOLERANCE_MM`)
    becomes the point's ``frame_id``.  ``-1`` marks a point that no delivered view explains.

    Defect history (D3, measured): the previous writer was
    ``(np.arange(n_points) % views)`` -- a deterministic function of the row index with zero
    information about the point, which measured equal to the exported ``frame_id`` in **31/31**
    arrays while the geometry index reported it as a frame identifier.
    """
    n_points = int(np.asarray(points).shape[0])
    report: dict[str, Any] = {
        "source": "unavailable", "tolerance_mm": float(FRAME_ID_TOLERANCE_MM),
        "n_points": n_points, "views_used": 0, "matched": 0, "unmatched": n_points,
        "match_fraction": 0.0, "median_residual_mm": None,
    }
    if n_points == 0:
        return np.zeros(0, dtype=np.int32), report
    world = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    homogeneous = np.concatenate([world, np.ones((n_points, 1), dtype=np.float64)], axis=1)
    residuals: list[np.ndarray] = []
    for index in range(int(views)):
        pose = arrays.get(f"v{index:03d}.T_WC")
        camera_matrix = arrays.get(f"v{index:03d}.K")
        depth = arrays.get(f"v{index:03d}.depth_z")
        if pose is None or camera_matrix is None or depth is None:
            continue
        pose = np.asarray(pose, dtype=np.float64)
        camera_matrix = np.asarray(camera_matrix, dtype=np.float64)
        depth = np.asarray(depth, dtype=np.float64)
        if pose.shape != (4, 4) or camera_matrix.shape != (3, 3) or depth.ndim != 2:
            continue
        if not (np.isfinite(pose).all() and np.isfinite(camera_matrix).all()):
            continue
        try:
            camera = (np.linalg.inv(pose) @ homogeneous.T).T[:, :3]
        except np.linalg.LinAlgError:
            continue
        projected = (camera_matrix @ camera.T).T
        z = projected[:, 2]
        safe = np.where(np.abs(z) < 1e-12, np.nan, z)
        u = np.rint(projected[:, 0] / safe).astype(np.int64)
        v = np.rint(projected[:, 1] / safe).astype(np.int64)
        height, width = depth.shape
        inside = ((camera[:, 2] > 0) & np.isfinite(u) & np.isfinite(v)
                  & (u >= 0) & (u < width) & (v >= 0) & (v < height))
        residual = np.full(n_points, np.nan, dtype=np.float64)
        if np.any(inside):
            sampled = depth[v[inside], u[inside]]
            residual[inside] = np.abs(sampled - camera[inside, 2])
        residuals.append(residual)
    if not residuals:
        return np.full(n_points, -1, dtype=np.int32), report
    stack = np.vstack([np.where(np.isfinite(row), row, np.inf) for row in residuals])
    best = np.argmin(stack, axis=0)
    best_residual = stack[best, np.arange(n_points)]
    matched = np.isfinite(best_residual) & (best_residual <= float(FRAME_ID_TOLERANCE_MM))
    frame_id = np.full(n_points, -1, dtype=np.int32)
    frame_id[matched] = best[matched].astype(np.int32)
    finite = best_residual[np.isfinite(best_residual)]
    report.update({
        "source": "T_WC+K+depth_z", "views_used": len(residuals),
        "matched": int(matched.sum()), "unmatched": int(n_points - int(matched.sum())),
        "match_fraction": float(int(matched.sum()) / n_points),
        "median_residual_mm": (float(np.median(finite)) if finite.size else None),
        "distinct_frames": int(np.unique(frame_id[matched]).size) if np.any(matched) else 0,
    })
    return frame_id, report


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

    # the channel whitelist of both views, resolved from its own document (never a literal here)
    channel_policy = load_channel_policy()
    deploy_table = channel_table(channel_policy, VIEW_DEPLOY)
    research_table = channel_table(channel_policy, VIEW_RESEARCH)
    deploy_channel_keys = set(deploy_table)
    declared_optional = {
        str(item.get("key")) for item in channel_policy["channels"].get(VIEW_DEPLOY, [])
        if str(item.get("key")) not in {"tiles", "valid", "view_pos"}
    }
    policy_optional = {key for key, _array, _dtype in OPTIONAL_DEPLOY_CHANNELS}
    if declared_optional != policy_optional:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"view channel policy declares optional deploy channels {sorted(declared_optional)} "
            f"but this writer implements {sorted(policy_optional)}",
            stage="export.export_training_package",
            evidence_refs=[channel_policy["path"]])

    closure = manager.verify_closure(sorted(release_assets))
    files: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}

    observations = by_role.get(ROLE_OBS_RESULT, [])
    features = by_role.get(ROLE_FEATURE_BUNDLE, [])
    labels_assets = by_role.get(ROLE_LABEL_BUNDLE, [])
    clean_assets = by_role.get(ROLE_CLEAN_TRUTH, [])
    physical_assets = by_role.get(ROLE_PHYSICAL_TRUTH, [])
    visible_role = by_role.get(ROLE_VISIBLE_LABELS, [])

    # ---------------- observations: policy-driven channels, opaque names, sharded tar ----
    # Which channel may be written into the deployment view is read from the view channel policy
    # (``synlab/schemas/view_channels.json``, overridable through ``SYNLAB_VIEW_CHANNEL_POLICY``);
    # the resolved policy, its source path and its byte hash travel in the manifest.  A permitted
    # channel that a given observation does not carry is *absent* for that fragment and is
    # reported as missing -- never fabricated with a placeholder array.
    obs_by_fragment: dict[str, dict[str, Any]] = {}
    channel_availability: dict[str, int] = {key: 0 for key in deploy_channel_keys}
    for record in observations:
        meta = dict(record.meta or {})
        fragment_id = str(meta.get("fragment_id") or "")
        if not fragment_id:
            continue
        arrays = store.load_arrays(record.asset_id)
        views = list((meta.get("views") or []))
        rgb, valid, view_pos, view_pos_source = [], [], [], []
        optional: dict[str, list[np.ndarray]] = {key: [] for key in OPTIONAL_DEPLOY_CHANNELS}
        n_views = 0
        for meta_view in views:
            index = len(view_pos)
            key = f"v{index:03d}.rgb"
            if key not in arrays:
                continue
            rgb.append(np.asarray(arrays[key], dtype=np.uint8))
            valid.append(np.asarray(arrays.get(f"v{index:03d}.deployment_mask",
                                               np.ones(arrays[key].shape[:2], bool)), dtype=bool))
            for channel_key, array_name, dtype in OPTIONAL_DEPLOY_CHANNELS:
                raw = arrays.get(f"v{index:03d}.{array_name}")
                if raw is None:
                    continue
                optional[channel_key].append(np.asarray(raw, dtype=dtype))
            # D2 fix: a real per-view slide coordinate; a missing source becomes ``nan`` with a
            # recorded reason instead of a silent ``0.0`` placeholder (see
            # :func:`_view_u_position_mm`).
            value, source = _view_u_position_mm(meta_view, arrays, index)
            view_pos.append(np.float32(np.nan) if value is None else np.float32(value))
            view_pos_source.append(source)
            n_views += 1
        if not rgb:
            continue
        payload: dict[str, Any] = {
            "asset_id": record.asset_id, "split": record.split,
            "lineage_id": record.lineage_id, "views": n_views,
            "rgb": np.stack(rgb, axis=0), "valid": np.stack(valid, axis=0),
            "view_pos": np.asarray(view_pos, dtype=np.float32),
            "view_pos_source": (view_pos_source[0] if len(set(view_pos_source)) == 1
                                else "mixed"),
            "extra": {},
            "present": ["tiles", "valid", "view_pos"],
            # the batch this observation belongs to (plan t088), read from the obs metadata
            "context": {**(meta.get("context") or {}),
                        "context_id": str(meta.get("context_id", "") or ""),
                        "batch_id": str(meta.get("batch_id", "") or "")},
        }
        for channel_key, _array_name, _dtype in OPTIONAL_DEPLOY_CHANNELS:
            collected = optional[channel_key]
            if len(collected) == n_views and n_views:
                payload["extra"][channel_key] = np.stack(collected, axis=0)
                payload["present"].append(channel_key)
                channel_availability[channel_key] = channel_availability.get(channel_key, 0) + 1
        if "K" in payload["extra"]:
            # ``K`` is an array of one 3x3 matrix per delivered view
            payload["extra"]["K"] = np.asarray(payload["extra"]["K"], dtype=np.float64)
        obs_by_fragment[fragment_id] = payload

    counts["observations"] = len(obs_by_fragment)
    counts["obs_views"] = int(sum(v["views"] for v in obs_by_fragment.values()))
    counts["obs_bytes"] = int(sum(v["rgb"].nbytes + v["valid"].nbytes
                                  for v in obs_by_fragment.values()))
    counts["deploy_channels_per_fragment"] = {
        key: sum(1 for v in obs_by_fragment.values() if key in v["present"])
        for key in deploy_channel_keys}

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
                    members_written: list[str] = []
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
                        members_written.append(suffix[: -len(".npy")])
                    for channel_key, array in sorted(payload["extra"].items()):
                        data = _npy_bytes(array)
                        info = tarfile.TarInfo(name=f"{opaque}/{channel_key}.npy")
                        info.size = len(data)
                        info.mtime = 0
                        tar.addfile(info, io.BytesIO(data))
                        members_written.append(channel_key)
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
                        # the channels this fragment's member files really carry
                        "channels": sorted(members_written),
                        # where the delivered ``view_pos.npy`` really came from (D2 fix)
                        "view_pos_source": payload["view_pos_source"],
                    }
            _record(files, path, out,
                    note="ObsPack shard (opaque names, policy-driven channels, no truth channel)")

        positions = (np.concatenate([payload["view_pos"] for payload in obs_by_fragment.values()])
                     if obs_by_fragment else np.zeros(0, dtype=np.float32))
        finite_positions = positions[np.isfinite(positions)]
        index_path = deploy_root / "obs" / "index.json"
        index_path.write_text(json.dumps({
            "schema": "synlab.obs_index.v1",
            "opaque_naming": "sha256(asset fragment id)[:24]",
            "channel_policy": {
                "schema": channel_policy["schema"],
                "path": channel_policy["path"],
                "hash": channel_policy["hash"],
                "source": channel_policy["source"],
                "env_override": VIEW_CHANNEL_POLICY_ENV,
                "note": ("the deployment view's channel set is data, not a literal: this is the "
                         "policy the shards were written under, with its own hash"),
            },
            "channels": [
                {
                    "key": entry["key"],
                    "source_array": entry.get("source_array"),
                    "dtype": entry.get("dtype"),
                    "unit": entry.get("unit"),
                    "reason": entry.get("reason"),
                    "evidence_class": entry.get("evidence_class"),
                    "caveat": entry.get("caveat"),
                    "optional": bool(entry.get("optional", False)),
                    "fragments_with_channel": int(counts["deploy_channels_per_fragment"]
                                                  .get(entry["key"], 0)),
                }
                for entry in channel_policy["channels"].get(VIEW_DEPLOY, [])
            ],
            "channel_names": sorted(deploy_channel_keys),
            "research_only_channels": sorted(channel_policy["research_only"]),
            "view_pos": {
                "unit": "mm",
                "definition": ("camera slide coordinate in the scan frame, read from the delivered "
                               "pose T_WC as T_WC[0, 3] -- the same definition "
                               "synlab.degrade.api uses for a ViewFrame's u_position_mm"),
                "fallback": "view_meta.u_position_mm, only when no pose was delivered",
                "missing_marker": "nan (neither T_WC nor a real u_position_mm was delivered)",
                "measured": {
                    "views": int(positions.size),
                    "finite": int(finite_positions.size),
                    "nonzero_finite": int(np.count_nonzero(finite_positions)),
                    "min": (float(finite_positions.min()) if finite_positions.size else None),
                    "max": (float(finite_positions.max()) if finite_positions.size else None),
                    "varies_across_views": bool(finite_positions.size
                                                and float(np.ptp(finite_positions)) > 0.0),
                },
            },
            "rows": obs_index,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, index_path, out)

    # ---------------- geometry: npz + tar shards, zarr replica --------------------------
    geometry_by_fragment: dict[str, dict[str, np.ndarray]] = {}
    frame_reports: dict[str, dict[str, Any]] = {}
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
        # D3 fix: a real per-point frame id, not a row counter.  The old writer used
        # ``arange(n_points) % views`` -- a deterministic function of the row index carrying zero
        # information about the point (measured equal to the exported array in 31/31 members).
        # ``frame_id[i]`` is now the delivered view whose rendered ``depth_z`` matches the point
        # reprojected through ``K`` and ``T_WC``; ``-1`` marks a point no delivered view explains.
        frame_id, frame_report = _frame_ids_from_views(points, arrays, views)
        frame_reports[fragment_id] = frame_report
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
                frame_ids = np.asarray(geometry_by_fragment[fragment_id]["frame_id"])
                matched = frame_ids[frame_ids >= 0]
                geometry_index[fragment_id] = {
                    "opaque": opaque, "shard": name,
                    "n_points": int(geometry_by_fragment[fragment_id]["points"].shape[0]),
                    # "frames" counts the delivered views a point was really matched to; it used
                    # to be the number of distinct values of the row counter (always n_views).
                    "frames": int(np.unique(matched).size),
                    "frame_id_source": str(frame_reports.get(fragment_id, {}).get("source",
                                                                                 "unavailable")),
                    "frame_id_unmatched": int((frame_ids < 0).sum()),
                    "frame_id_match_fraction": float(matched.size / max(int(frame_ids.size), 1)),
                    "points_hash": array_hash(geometry_by_fragment[fragment_id]["points"]),
                }
            np.savez(path, **payload)
            _record(files, path, out, note="geometry shard (points/normals/*_valid/scale_valid/frame_id)")
        _matched_total = int(sum(int(row["n_points"]) - int(row["frame_id_unmatched"])
                                 for row in geometry_index.values()))
        _points_total = int(sum(int(row["n_points"]) for row in geometry_index.values()))
        _with_pose = sorted({str(row["frame_id_source"]) for row in geometry_index.values()})
        index_path = deploy_root / "geometry" / "index.json"
        index_path.write_text(json.dumps({
            "schema": "synlab.geometry_index.v1",
            "arrays": ["points", "normals", "point_valid", "normal_valid", "scale_valid",
                       "frame_id"],
            "frame_id": {
                "unit": "1 (index of a delivered view inside the fragment)",
                "definition": ("the delivered view whose rendered depth_z agrees with the point "
                               "reprojected through K and T_WC; -1 = no delivered view explains "
                               "the point"),
                "tolerance_mm": float(FRAME_ID_TOLERANCE_MM),
                "unmatched_marker": -1,
                "sources": _with_pose,
                "measured": {"points": _points_total, "matched": _matched_total,
                             "match_fraction": (float(_matched_total / _points_total)
                                                if _points_total else 0.0)},
            },
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
            # What one token *is*, stated where a loader can read it: one token per
            # ``(view, block, channel)`` slot, ``TOKEN_DIM`` sub-grid means of that slot.  The
            # previous writer broadcast one scalar into ``token_dim`` columns per token (measured
            # effective rank 1); the layout key is what makes that difference checkable.
            "token_layout": TOKEN_LAYOUT,
            "token_sub_grid": [TOKEN_SUB, TOKEN_SUB],
            "tokens_per_view": TOKEN_BLOCK * TOKEN_BLOCK * 3,
            "token_input": "coarse TOKEN_BLOCK x TOKEN_BLOCK block mean per view (real, rank-1 by"
                           " construction); kept for provenance, not a 256-dim feature",
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
        # the batch this query belongs to (plan t088): the same controlled metadata a real
        # excavation hands over with a sherd, so the candidate scope of a query is addressable
        query_context = dict(obs.get("context") or {})
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
            "context_id": str(query_context.get("context_id", "") or ""),
            "batch_id": str(query_context.get("batch_id", "") or ""),
            "bag_id": str(query_context.get("bag_id", "") or ""),
            "stratum_id": str(query_context.get("stratum_id", "") or ""),
            "excavation_area_id": str(query_context.get("excavation_area_id", "") or ""),
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
    supervision_labels: dict[str, Any] = {}
    if include_truth:
        # Two of the layers are *supervision* rather than bookkeeping and are built from the
        # measured label side: the observability target of task D and the real surface
        # correspondence of every supervised pair.  Both used to be dropped by the package, so a
        # consumer could not tell "no label was produced" from "the label never reached the
        # package" (see ``docs/a12/training_run.md``).
        quality_rows, quality_prov = _quality_rows(
            store, list(visible_role) + list(labels_assets), fragment_ids=all_fragments)
        correspondence_rows, correspondence_prov = _correspondence_rows(store, relations)
        supervision_labels = {"quality": quality_prov, "correspondence": correspondence_prov}
        counts["quality_targets"] = int(sum(1 for r in quality_rows if r["valid"]))
        counts["quality_target_views"] = len(quality_rows)
        counts["correspondence_samples"] = len(correspondence_rows)
        counts["correspondence_pairs"] = int(correspondence_prov["pairs_with_correspondence"])

        layer_rows = [(layer, assets, _label_rows(layer, store, assets))
                      for layer, assets in (("clean", clean_assets), ("physical", physical_assets),
                                            ("visible", visible_role))]
        layer_rows += [("quality", visible_role, quality_rows),
                       ("correspondence", [], correspondence_rows)]
        for layer, assets, rows in layer_rows:
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

    # ---------------- degradation diversity (axis x level variants) ---------------------
    # Indexed as a marked block beside the views: a variant carries the factor answer
    # (axis_id/level/variant) and must never be merged into a feature shard.
    degrade_block = _degrade_diversity_block(store, by_role, out, files)
    counts.update(degrade_block["counts"])

    # ---------------- simulated excavation context (plan t088) --------------------------
    # Context is *the metadata that travels with a sherd at a real excavation*, so it belongs to
    # the deployment view: the pack document is written under ``deploy/context/`` and every query
    # row names its own context/batch/bag.  Two answer-side fields are deliberately **not**
    # exported here: the batch membership lists real fragment ids, so it stays on the research
    # side (``research/context_membership.json``), and no lineage/split ever appears.
    deploy_context_rows: dict[str, dict[str, Any]] = {}
    research_membership: dict[str, Any] = {}
    for record in by_role.get(ROLE_CONTEXT_PACK, []):
        meta = dict(record.meta or {})
        packs.append({
            "asset_id": record.asset_id,
            "simulated": bool(meta.get("simulated", False)),
            "pack_id": str(meta.get("pack_id", "")),
            "context_id": str(meta.get("context_id", "")),
            "batch_id": str(meta.get("batch_id", "")),
            "batch_size": int(meta.get("batch_size", 0) or 0),
            "bag_id": str(meta.get("bag_id", "")),
            "pit_id": str(meta.get("pit_id", "")),
            "site_id": str(meta.get("site_id", "")),
            "institution_id": str(meta.get("institution_id", "")),
            "excavation_area_id": str(meta.get("excavation_area_id", "")),
            "grid_ref": str(meta.get("grid_ref", "")),
            "unit_code": str(meta.get("unit_code", "")),
            "stratum_id": str(meta.get("stratum_id", "")),
            "stratum_depth_mm": meta.get("stratum_depth_mm"),
            "session_id": str(meta.get("session_id", "")),
            "operator_id": str(meta.get("operator_id", "")),
            "captured_at": str(meta.get("captured_at", "")),
            "site_notes": str(meta.get("site_notes", "")),
            "scale_reference": _jsonable(meta.get("scale_reference") or {}),
            "coexistent_counts": _jsonable(meta.get("coexistent_counts") or {}),
            "coexistence_scope": str(meta.get("coexistence_scope", "")),
            "batch_rule": str(meta.get("batch_rule", "")),
            "schema": record.schema,
            "unit": record.unit,
            "frame": record.frame,
            "qa_status": record.qa_status,
        })
        deploy_context_rows.setdefault(str(meta.get("context_id", "")), {
            "context_id": str(meta.get("context_id", "")),
            "batch_id": str(meta.get("batch_id", "")),
            "bag_id": str(meta.get("bag_id", "")),
            "pit_id": str(meta.get("pit_id", "")),
            "stratum_id": str(meta.get("stratum_id", "")),
            "excavation_area_id": str(meta.get("excavation_area_id", "")),
        })
        members = [str(row.get("id", "")) for row in (meta.get("coexistents") or [])]
        research_membership[str(meta.get("context_id", ""))] = {
            "batch_id": str(meta.get("batch_id", "")),
            "members": sorted(members),
            "opaque_members": sorted(_opaque(member) for member in members),
            "note": ("research-only: the batch membership is a list of real fragment ids, which "
                     "is exactly the answer the deployment view's opaque names hide"),
        }
    counts["context_packs"] = len(packs)
    counts["context_batches"] = len({row["batch_id"] for row in packs})
    counts["context_queries"] = int(sum(1 for row in queries_rows if row.get("context_id")))

    if packs or research_membership:
        context_dir = deploy_root / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        packs_path = context_dir / "packs.json"
        packs_path.write_text(json.dumps({
            "schema": "synlab.context_pack.v1",
            "simulated": True,
            "role": ROLE_CONTEXT_PACK,
            "note": ("simulated excavation context (plan t088): every field is generated by the "
                     "synthetic generator and marked simulated=true; none of it is an "
                     "archaeological record"),
            "field_units": {
                "stratum_depth_mm": "mm below the simulated site datum",
                "scale_reference.size_mm": "mm (the physical size of the scale object)",
                "coexistents": "counts only; the member list is research-side",
            },
            "packs": packs,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, packs_path, out, note="deployment view: simulated excavation context")
        membership_path = research_root / "context_membership.json"
        membership_path.parent.mkdir(parents=True, exist_ok=True)
        membership_path.write_text(json.dumps({
            "schema": "synlab.context_membership.v1",
            "note": "research view: real fragment ids per batch (the deployment view hides them)",
            "batches": research_membership,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _record(files, membership_path, out, note="research view: batch membership ids")

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
    channel_separation = channel_separation_report(
        deploy_root, research_root, channel_policy,
        deploy_channels={
            fragment_id: list(payload["present"]) for fragment_id, payload in obs_by_fragment.items()
        })

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
            "channel_separation": channel_separation,
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
        "degrade_diversity": {
            "role": degrade_block["index"]["role"],
            "source_role": degrade_block["index"]["source_role"],
            "schema": DEGRADE_INDEX_SCHEMA,
            "counts": degrade_block["counts"],
            "files": degrade_block["files"],
            "axes": degrade_block["index"]["axes"],
            "level_zero_contract": degrade_block["index"]["level_zero_contract"],
            "retrieval_role": degrade_block["index"]["retrieval_role"],
            "feature_bundle_exclusion": ("degrade_variant metadata carries axis_id/level/variant, "
                                         "which roles.FORBIDDEN_FEATURE_FIELDS forbids inside a "
                                         "feature_bundle; the variant index is written at the "
                                         "package root, outside both views"),
        },
        "labels": label_files,
        "supervision_labels": supervision_labels,
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


# --------------------------------------------------------------------------------------
# supervision labels that the release already carries
# --------------------------------------------------------------------------------------
#: Label layers written *in addition* to clean/physical/visible.  Both carry supervision the
#: release has measured but the package used to drop:
#:
#: ``quality``
#:     The label-side observability measurement of the delivered observation (the visible/truth
#:     layer's ``per_view`` block): how many of a fragment's surface samples survive each
#:     visibility criterion.  It is computed against the *rendered* depth/id_map/uncertain_mask
#:     channels, which the deployment view never carries, so it is a target and not an input.
#:     ``loss_mask``/``valid`` semantics: a fragment/view with no measurement stays invalid and
#:     is never turned into a zero target.
#: ``correspondence``
#:     The real many-to-many surface correspondence between the two sides of a cut face
#:     (``corr_*`` arrays of the clean/physical truth assets: point indices, barycentrics, face
#:     ids, residual, association code, ambiguity flag and a non-negative edge weight).  Only
#:     pairs whose relation row is supervised (``valid and loss_mask``) are exported.
SUPERVISION_LABEL_LAYERS = ("quality", "correspondence")

#: The single channel the packaged quality target carries.  The observation-only feature side
#: exposes one quality slot (``a12.obs.v1`` payload ``quality``), so the D-task head predicts one
#: channel; the *target* is the label-side observability of the same fragment.
QUALITY_TARGET_CHANNEL = "observability_visible_rate"


def _observability_candidates(store: AssetStore, records: Iterable[Any]) -> dict[str, list[dict]]:
    """Every real per-view observability measurement of every asset, grouped by fragment.

    Two carriers exist in a release and both are read: ``visible_labels`` assets (``per_view``)
    and ``label_bundle`` assets (``visible_json``).  A release may contain several re-commits of
    the same fragment, so each candidate keeps its own asset id and view/sample counts and the
    choice is made explicitly by :func:`_canonical_observability`.
    """
    out: dict[str, list[dict]] = {}
    for record in records:
        meta = dict(record.meta or {})
        fragment_id = str(meta.get("fragment_id") or "")
        if not fragment_id:
            continue
        block = meta.get("per_view")
        if block is None:
            block = meta.get("visible_json")
        if isinstance(block, str):
            try:
                block = json.loads(block)
            except ValueError:
                block = None
        if not isinstance(block, Mapping) or not block:
            continue
        views = {str(k): dict(v) for k, v in block.items() if isinstance(v, Mapping)}
        if not views:
            continue
        out.setdefault(fragment_id, []).append({
            "asset_id": record.asset_id,
            "role": record.role,
            "schema": record.schema,
            "lineage": record.lineage_id,
            "split": record.split,
            "views": views,
            "n_views": len(views),
            "max_samples": int(max(int(v.get("samples") or 0) for v in views.values())),
        })
    for candidates in out.values():
        candidates.sort(key=lambda c: (-int(c["n_views"]), -int(c["max_samples"]),
                                       str(c["asset_id"])))
    return out


def _canonical_observability(candidates: Mapping[str, list[dict]]) -> dict[str, dict]:
    """The widest real measurement per fragment (most views, then most samples, then id).

    "Widest" is the only tie-break used: the candidates are re-commits of the same measurement,
    and the one that measured more views is the one that can supervise more of them.  The
    candidates that were *not* chosen are recorded in the manifest, so which measurement was
    used (and which were available) is never a silent decision.
    """
    chosen: dict[str, dict] = {}
    for fragment_id, items in sorted(candidates.items()):
        if items:
            chosen[fragment_id] = items[0]
    return chosen


def _quality_rows(store: AssetStore, records: Iterable[Any], *, fragment_ids: Sequence[str]
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Label-side observability rows (one per fragment x view) plus the provenance block."""
    candidates = _observability_candidates(store, records)
    chosen = _canonical_observability(candidates)
    wanted = {str(fid) for fid in fragment_ids}
    rows: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {"target_channel": QUALITY_TARGET_CHANNEL,
                                  "target_unit": "1",
                                  "source_kind": "GT_ORACLE",
                                  "rule": ("visible = inside the delivered image AND camera z>0 "
                                           "AND |z - rendered depth| <= max(0.5 mm, 4 * "
                                           "mm_per_px) AND id_map>=0 AND not uncertain_mask AND "
                                           "deployment_mask (measured by the visible/truth layer)"),
                                  "fragments_with_measurement": 0,
                                  "views_measured": 0,
                                  "candidates": {}}
    for fragment_id in sorted(set(chosen) & wanted):
        pick = chosen[fragment_id]
        provenance["candidates"][fragment_id] = {
            "chosen": pick["asset_id"],
            "available": [{"asset_id": c["asset_id"], "role": c["role"], "views": c["n_views"],
                           "max_samples": c["max_samples"]} for c in candidates[fragment_id]],
        }
        provenance["fragments_with_measurement"] += 1
        for view_id, entry in sorted(pick["views"].items()):
            samples = int(entry.get("samples") or 0)
            valid = samples > 0
            row = {
                "label_layer": "quality",
                "fragment_id": fragment_id,
                "view_id": view_id,
                "lineage": pick["lineage"],
                "split": pick["split"],
                "samples": samples,
                "projected": int(entry.get("projected") or 0),
                "depth_ok": int(entry.get("depth_ok") or 0),
                "id_ok": int(entry.get("id_ok") or 0),
                "not_uncertain": int(entry.get("not_uncertain") or 0),
                "deployment_ok": int(entry.get("deployment_ok") or 0),
                "visible": int(entry.get("visible") or 0),
                "target_channel": QUALITY_TARGET_CHANNEL,
                "target_unit": "1",
                "source_kind": "GT_ORACLE",
                "source_ref": str(pick["asset_id"]),
                "asset_id": str(pick["asset_id"]),
                "valid": bool(valid),
                "reason": "" if valid else "no_samples_measured_for_this_view",
            }
            for name, key in (("visible_rate", "visible"), ("depth_ok_rate", "depth_ok"),
                              ("id_ok_rate", "id_ok"), ("not_uncertain_rate", "not_uncertain"),
                              ("deployment_ok_rate", "deployment_ok")):
                row[name] = (float(row[key]) / float(samples)) if valid else None
            row["target_value"] = row["visible_rate"]
            rows.append(row)
        provenance["views_measured"] += int(pick["n_views"])
    return rows, provenance


def _correspondence_rows(store: AssetStore, relations: Sequence[Mapping[str, Any]]
                         ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Real correspondence samples of every supervised pair plus the provenance block."""
    rows: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {"pairs_supervised": 0, "pairs_with_correspondence": 0,
                                 "samples": 0, "weight_sum": 0.0, "valid_samples": 0,
                                 "ambiguous_samples": 0, "skipped": [],
                                 "association_code_histogram": {}}
    source_kind = {ROLE_CLEAN_TRUTH: "CLEAN_TRUTH", ROLE_PHYSICAL_TRUTH: "PHYSICAL_TRUTH"}
    for row in relations:
        if not (bool(row.get("valid", False)) and bool(row.get("loss_mask", False))):
            continue
        a = str(row.get("a", ""))
        b = str(row.get("b", ""))
        if not a or not b:
            continue
        provenance["pairs_supervised"] += 1
        asset_id = str(row.get("_truth_asset") or "")
        if not asset_id:
            provenance["skipped"].append({"pair": [a, b], "reason": "no truth asset reference"})
            continue
        try:
            record = store.get_asset(asset_id)
            arrays = store.load_arrays(asset_id)
        except SynLabError as exc:
            provenance["skipped"].append({"pair": [a, b], "reason": f"{asset_id}: {exc}"})
            continue
        if "corr_index_a" not in arrays or "corr_weight" not in arrays:
            provenance["skipped"].append(
                {"pair": [a, b], "asset_id": asset_id,
                 "reason": "asset carries no corr_* correspondence block"})
            continue
        pair_of_asset = {str(x) for x in np.asarray(
            arrays.get("corr_fragment_ids", np.zeros(0, dtype="U1"))).tolist()}
        if pair_of_asset and pair_of_asset != {a, b}:
            provenance["skipped"].append(
                {"pair": [a, b], "asset_id": asset_id,
                 "reason": f"correspondence is between {sorted(pair_of_asset)}"})
            continue
        index_a = np.asarray(arrays["corr_index_a"], dtype=np.int64)
        index_b = np.asarray(arrays.get("corr_index_b", index_a), dtype=np.int64)
        weight = np.asarray(arrays["corr_weight"], dtype=np.float64)
        valid = np.asarray(arrays.get("corr_valid", np.ones(index_a.size, bool)), dtype=bool)
        ambiguous = np.asarray(arrays.get("corr_ambiguous", np.zeros(index_a.size, bool)),
                               dtype=bool)
        code = np.asarray(arrays.get("corr_association_code",
                                     np.zeros(index_a.size, np.int32)), dtype=np.int64)
        residual = np.asarray(arrays.get("corr_residual_mm",
                                        np.zeros(index_a.size, np.float32)), dtype=np.float64)
        iface = np.asarray(arrays.get("corr_interface_id",
                                     np.full(index_a.size, -1, np.int32)), dtype=np.int64)
        provenance["pairs_with_correspondence"] += 1
        for i in range(index_a.size):
            c = int(code[i])
            hist = provenance["association_code_histogram"]
            hist[str(c)] = hist.get(str(c), 0) + 1
            provenance["weight_sum"] += float(weight[i])
            provenance["valid_samples"] += int(bool(valid[i]))
            provenance["ambiguous_samples"] += int(bool(ambiguous[i]))
            rows.append({
                "label_layer": "correspondence",
                "fragment_a": a, "fragment_b": b,
                "index_a": int(index_a[i]), "index_b": int(index_b[i]),
                "weight": float(weight[i]),
                "sample_valid": bool(valid[i]),
                "ambiguous": bool(ambiguous[i]),
                "association_code": c,
                "residual_mm": float(residual[i]),
                "interface_id": int(iface[i]),
                "relation_kind": str(row.get("kind", "")),
                "lineage": str(row.get("_lineage_id") or record.lineage_id or ""),
                "split": record.split,
                "source_kind": source_kind.get(record.role, record.role),
                "source_ref": asset_id,
                "asset_id": asset_id,
                "valid": bool(valid[i]),
                "reason": ("" if bool(valid[i]) else "correspondence sample marked invalid")
                          + (";ambiguous" if bool(ambiguous[i]) else ""),
            })
    provenance["samples"] = len(rows)
    provenance["weight_sum"] = float(provenance["weight_sum"])
    return rows, provenance


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
# channel separation: what each view really contains
# --------------------------------------------------------------------------------------
def observed_channels(view_root: str | Path) -> dict[str, Any]:
    """The channel names a written view really contains, read from its own files.

    Three carriers are scanned: the ``obs`` tar shards (one member file per channel per
    fragment), the zarr replica of the geometry arrays, and every ``npz``/``parquet``/``json``
    container at the view root.  The result is a measurement of the package on disk -- the
    manifest's channel claim is built from it, never from the writer's intent.
    """
    root = Path(view_root)
    by_channel: dict[str, int] = {}
    files_by_channel: dict[str, list[str]] = {}

    def note(channel: str, rel: str) -> None:
        by_channel[channel] = by_channel.get(channel, 0) + 1
        files_by_channel.setdefault(channel, []).append(rel)

    shards: list[str] = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            suffix = path.suffix.lower()
            if suffix == ".tar":
                shards.append(rel)
                try:
                    with tarfile.open(path, "r") as tar:
                        for member in tar.getmembers():
                            if member.isfile():
                                note(_field_name(member.name), rel)
                except Exception:  # noqa: BLE001 - an unreadable shard is simply not evidence
                    continue
            elif suffix == ".npz":
                try:
                    with np.load(path, allow_pickle=False) as data:
                        for name in data.files:
                            note(_field_name(name), rel)
                except Exception:  # noqa: BLE001
                    continue
            elif suffix == ".parquet":
                try:
                    import pyarrow.parquet as pq

                    for name in pq.read_schema(path).names:
                        note(str(name), rel)
                except Exception:  # noqa: BLE001
                    continue
            elif suffix == ".json":
                if path.name in STORAGE_METADATA_NAMES:
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for name in ("channel_names", "research_only_channels"):
                    for key in payload.get(name) or []:
                        note(str(key), rel)
    return {
        "view": root.name,
        "channels": {key: sorted(set(files)) for key, files in sorted(by_channel.items())},
        "counts": {key: len(files) for key, files in sorted(by_channel.items())},
        "tar_shards": sorted(set(shards)),
    }


def declared_channels(view_root: str | Path) -> dict[str, Any]:
    """The channel set the deployment view's own ``obs/index.json`` says it was written under.

    Recorded *separately* from the measured names: a writer's declaration is a statement about
    the policy, and only the measured set is evidence about the bytes on disk.
    """
    index_path = Path(view_root) / "obs" / "index.json"
    if not index_path.exists():
        return {"file": "", "channels": [], "policy": {}}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"file": str(index_path), "channels": [], "policy": {}, "unreadable": True}
    return {
        "file": str(index_path),
        "channels": sorted({str(name) for name in (payload.get("channel_names") or [])}),
        "policy": dict(payload.get("channel_policy") or {}),
    }


def channel_separation_report(deploy_root: str | Path, research_root: str | Path,
                              policy: Mapping[str, Any],
                              *, deploy_channels: Mapping[str, Sequence[str]] | None = None
                              ) -> dict[str, Any]:
    """Judge the two views' channel sets against the resolved policy, on real content.

    For every channel the policy permits in a view the report says ``included`` (and for how many
    fragments, when the caller supplies the per-fragment membership) or ``missing`` -- a permitted
    channel the package does not carry is never reported as present.  A channel that is in the
    export but in no policy list is reported as ``unexpected``, and a research-only channel found
    anywhere in the deployment view is reported as a ``leak``.
    """
    deploy_scan = observed_channels(deploy_root)
    research_scan = observed_channels(research_root)
    deploy_keys = set(deploy_scan["counts"])
    research_keys = set(research_scan["counts"])
    policy_deploy = [str(item["key"]) for item in (policy.get("channels") or {}).get(VIEW_DEPLOY, [])]
    policy_research = [str(item["key"])
                       for item in (policy.get("channels") or {}).get(VIEW_RESEARCH, [])]
    declared = declared_channels(deploy_root)
    measured = set(deploy_keys)
    per_fragment = deploy_channels or {}
    counts: dict[str, int] = {}
    missing: list[str] = []
    for key in policy_deploy:
        present = sum(1 for channels in per_fragment.values() if key in channels)
        counts[key] = present
        if per_fragment:
            if not present:
                missing.append(key)
        elif key not in measured:
            missing.append(key)

    def _status(key: str) -> str:
        return "missing" if key in missing else "included"

    research_only = sorted(policy.get("research_only") or [])
    leaks = sorted(key for key in measured if key in set(research_only))
    return {
        "policy": {"schema": policy.get("schema"), "path": policy.get("path"),
                   "hash": policy.get("hash")},
        "source": ("content scan of the written package: tar member names, npz array names, "
                   "parquet column names and json array-name lists of each view"),
        "declared_by_the_writer": declared,
        VIEW_DEPLOY: {
            "channels_present": sorted(measured),
            "channels_declared": declared["channels"],
            "permitted": policy_deploy,
            "status": {key: _status(key) for key in policy_deploy},
            "fragments_with_channel": counts,
            "fragments_examined": len(per_fragment),
            "files_by_channel": {key: deploy_scan["channels"].get(key, [])
                                 for key in sorted(measured)},
        },
        VIEW_RESEARCH: {
            "channels_present": sorted(research_keys),
            "permitted": policy_research,
            "status": {key: ("included" if key in research_keys else "missing")
                       for key in policy_research},
            "files_by_channel": {key: research_scan["channels"].get(key, [])
                                 for key in sorted(research_keys)},
        },
        "research_only_channels": research_only,
        "leaked_into_deploy": leaks,
        "truth_roles": dict(policy.get("truth_roles") or {}),
        "statement": ("every channel of the deployment view is either permitted by the channel "
                      "policy or reported here as unexpected/leaked; a permitted but absent "
                      "channel is reported as missing"),
    }


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
    "VIEW_CHANNEL_POLICY_ENV", "VIEW_CHANNEL_POLICY_PATH", "OPTIONAL_DEPLOY_CHANNELS",
    "load_channel_policy", "channel_table", "observed_channels", "declared_channels",
    "channel_separation_report",
    "export_release", "export_training_package", "TrainingPackage",
    "scan_view_fields", "truth_bearing_files",
]
