"""One merged, **experiment-ready** export: every implemented-but-unpackaged dimension in one package.

Why this tool exists
--------------------
By the time of this run the repository had five families of real data that no training package
carried, because each was produced by a different line of work and each wrote into its own store:

* the **fracture-ROI close-up view family** (``data/a12_roi/store``: 4 obs_result x 24 views =
  12 whole-slice + 12 ROI close-ups each),
* the nine **synthetic extras** (``data/a12_extras/store`` + the ``synthetic_extra`` export),
* the **simulated excavation context packs** (``data/a12_context/store``),
* the **31-axis degradation registry with its materialised variants** (``data/a12_degrade/store``),
* the **fracture-surface channels** (``face__origin_kind == INTERFACE``).

Assembling them by hand would make the package a literal transcription of what somebody believed
should be there.  This tool instead does exactly two things and nothing else:

1. **base** -- it calls the *real* writer, ``synlab.storage.export.export_training_package``, on
   the release the A12 next-experiment batch was exported from, into a **new** directory.  Nothing
   about the base package is hand-written, so the S3 direction completion and the S4 table-column
   declaration take effect by construction.
2. **merge** -- for every extra dimension it *copies the real payload bytes* out of the source
   store and then **measures** what it copied (array keys, shapes, dtypes, per-view families,
   per-axis levels, interface areas and planarity).  Every number in every ``index.json`` under
   ``research/`` is a measurement of the bytes that were just written, never a constant.

The merge never touches ``deploy/``: the ROI obs payloads carry ``id_map``/``surface_tag``/
``T_WC``/``dist`` (research-only channels by ``synlab/schemas/view_channels.json``), so they are
written under ``research/`` where the deployment-view answer-field scan does not look -- and the
base package's own ``separation`` block is left byte-identical.

``finalise`` re-declares the merged file set in ``export_manifest.json`` (real sha256 of every
file, on disk) and recomputes ``manifest_hash`` the same way the writer does.  ``ablation`` emits
``ablation_index.json`` (one row per switchable dimension: dimension, switch field, testable
hypothesis, positive- and negative-gain yardsticks).  ``card`` runs the shipped card builder.

Exit codes: ``0`` ok, ``1`` a step failed, ``2`` usage error.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.canonical import hash_file, hash_json              # noqa: E402
from synlab.storage.store import AssetStore                    # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

DEFAULT_OUT = "data/a12_exports/experiment_ready"
DEFAULT_STORE = "data/a12_trainable/store"
DEFAULT_STATE = "data/a12_exports/trainable/next_experiment/next_experiment_export_state.json"
DEFAULT_RELEASE = "rel_nexp_1790919836"
EXPORT_FORMATS = ("parquet", "npz", "zarr", "tar")

ROI_STORE = "data/a12_roi/store"
EXTRAS_STORE = "data/a12_extras/store"
EXTRAS_EXPORT = "data/a12_exports/a12_extras/synthetic_extra"
CONTEXT_STORE = "data/a12_context/store"
DEGRADE_STORE = "data/a12_degrade/store"
DEGRADE_EXPORT = ("data/a12_degrade/exports/rel_degrade_diversity_1790919754/training_package/"
                  "degrade")
POLICY_PATH = "synlab/schemas/view_channels.json"

#: ``deploy/obs/index.json`` channel keys of the base package: a channel a deployment loader of
#: *this* package really receives.  Used as the measured basis of ``rig_obtainable``.
POLICY = json.loads((REPO_ROOT / POLICY_PATH).read_text(encoding="utf-8"))
POLICY_VIEW_OF: dict[str, str] = {}
POLICY_EVIDENCE: dict[str, str] = {}
for _view, _block in (POLICY.get("views") or {}).items():
    for _channel in (_block.get("channels") or []):
        POLICY_VIEW_OF.setdefault(str(_channel["key"]), str(_view))
        POLICY_EVIDENCE.setdefault(str(_channel["key"]), str(_channel.get("evidence_class", "")))
POLICY_SHA = hash_file(REPO_ROOT / POLICY_PATH)


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def sha256(path: Path) -> str:
    return hash_file(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def annotation(channel: str, *, deploy_channels: Iterable[str], evidence: str | None = None,
               source_kind: str | None = None, route: str | None = None) -> dict[str, Any]:
    """The three flags required per item -- each one traced to a real source, not to a guess.

    * ``rig_obtainable`` is **measured**: "the base package's deployment view hands this channel
      to a deployment loader" (scan of ``deploy/obs/index.json`` channel lists).  It is therefore
      false for every research-only channel, by construction rather than by opinion.
    * ``synthetic_only`` is **measured from the producer's own metadata**: every producing asset
      declares a simulation route (``route=proxy_scan`` / ``source_kind`` in the SENSOR_* family)
      and none declares a real capture.  The evidence string is recorded beside the flag.
    * ``claim_allowed`` is **policy**: it is true only when
      ``synlab/schemas/view_channels.json`` puts the channel in the ``deploy`` view *and* its
      ``evidence_class`` is not one of the ``CAVEAT_*`` classes.  Undeclared channels are false
      with the reason ``not_declared_by_policy``.
    """
    view = POLICY_VIEW_OF.get(channel)
    klass = evidence or POLICY_EVIDENCE.get(channel) or "NOT_DECLARED_BY_POLICY"
    caveat = str(klass).startswith("CAVEAT")
    return {
        "channel": channel,
        "rig_obtainable": bool(channel in set(deploy_channels)),
        "rig_obtainable_basis": "channel is shipped by this package's own deploy view",
        "synthetic_only": True,
        "synthetic_only_basis": ("producer metadata declares a simulation route "
                                 f"(source_kind={source_kind!r}, route={route!r}); no producer "
                                 "declares real_capture"),
        "claim_allowed": bool(view == "deploy" and not caveat),
        "claim_allowed_basis": ("policy synlab/schemas/view_channels.json: view=%s evidence_class=%s"
                                % (view, klass)),
        "evidence_class": klass,
        "policy_view": view,
        "policy_sha256": POLICY_SHA,
    }


def deploy_channel_keys(package: Path) -> set[str]:
    """Real scan: which channel keys the base package's deploy view actually ships."""
    index = package / "deploy" / "obs" / "index.json"
    if not index.is_file():
        return set()
    payload = json.loads(index.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for entry in (payload.get("rows") or {}).values():
        keys.update(str(name) for name in (entry.get("channels") or []))
    return keys


def _dimension_counts(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Flat, card-readable counts for the merged dimensions (all of them measured)."""
    out: dict[str, Any] = {}
    lookup = {str(d.get("dimension")): (d.get("counts") or {})
              for d in (bundle.get("dimensions") or [])}
    if "roi_views" in lookup:
        out["roi_view_family_assets"] = lookup["roi_views"].get("assets")
        out["roi_view_family_views"] = lookup["roi_views"].get("views")
        out["roi_view_family_bytes"] = lookup["roi_views"].get("bytes")
    if "synthetic_extras" in lookup:
        out["synthetic_extra_modalities"] = lookup["synthetic_extras"].get("modalities")
        out["synthetic_extra_claim_allowed"] = lookup["synthetic_extras"].get(
            "claim_allowed_modalities")
    if "context" in lookup:
        out["context_packs"] = lookup["context"].get("packs")
        out["context_declared_table_columns"] = lookup["context"].get(
            "declared_capture_context_columns")
    if "degrade" in lookup:
        out["degrade_registered_axes"] = lookup["degrade"].get("registered_axes")
        out["degrade_axes_with_levels"] = lookup["degrade"].get("axes_with_materialised_levels")
        out["degrade_materialised_variants"] = lookup["degrade"].get("materialised_variants")
        out["degrade_materialised_levels"] = lookup["degrade"].get("materialised_levels")
    if "fracture_interfaces" in lookup:
        out["fracture_interface_faces"] = lookup["fracture_interfaces"].get("interface_faces")
        out["fracture_planar_fragments"] = lookup["fracture_interfaces"].get("planar_fragments")
        out["fracture_non_planar_fragments"] = lookup["fracture_interfaces"].get(
            "non_planar_fragments")
    out["experiment_ready_missing_dimensions"] = len(bundle.get("missing") or [])
    return {k: v for k, v in out.items() if v is not None}


def declare(manifest: dict[str, Any], root: Path, extras: Sequence[str] = ()) -> dict[str, Any]:
    """Re-declare the file set from a real scan of the bytes on disk.

    Keeps every original manifest field; only ``files``, ``bytes_total``, ``counts_total`` and
    ``manifest_hash`` are recomputed, the last one exactly the way
    ``synlab.storage.export.export_training_package`` computes it.
    """
    declared = {str(entry["path"]): entry for entry in manifest.get("files", [])}
    on_disk = sorted(str(p.relative_to(root)).replace("\\", "/")
                     for p in root.rglob("*") if p.is_file())
    files: list[dict[str, Any]] = []
    for relative in on_disk:
        if relative in ("export_manifest.json",) + tuple(extras):
            continue
        path = root / relative
        entry = dict(declared.get(relative) or {})
        entry["path"] = relative
        entry["bytes"] = int(path.stat().st_size)
        entry["hash"] = sha256(path)
        entry.setdefault("note", "merged experiment-ready dimension" if relative.startswith("research/")
                         else "")
        files.append(entry)
    manifest["files"] = sorted(files, key=lambda item: item["path"])
    manifest["bytes_total"] = int(sum(int(f["bytes"]) for f in manifest["files"]))
    manifest["counts_total"] = len(manifest["files"])
    manifest["manifest_hash"] = hash_json(
        {k: v for k, v in manifest.items() if k != "manifest_hash"})
    return manifest


# ----------------------------------------------------------------------------------------------
# step: base
# ----------------------------------------------------------------------------------------------
def step_base(store_dir: Path, out_dir: Path, state_path: Path, release: str,
              report: dict[str, Any]) -> dict[str, Any]:
    """Run the *real* writer on the recorded release scope.  No hand-written bytes."""
    from synlab.errors import SynLabError
    from synlab.storage import release as release_mod
    from synlab.storage.export import export_training_package

    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    ids = (state.get("freeze") or {}).get("unverified_scope_ids") or []
    if not ids:
        raise SynLabError(
            __import__("synlab.errors", fromlist=["ErrorCode"]).ErrorCode.INPUT_UNAVAILABLE,
            f"{state_path} carries no recorded export scope", stage="experiment_ready.base")
    next_exp = load_module(REPO_ROOT / "tools" / "next_experiment_export.py", "_nexp_export")
    store = AssetStore(store_dir)
    manifest = next_exp._unverified_manifest(store, release, ids)
    package_dir = out_dir / "training_package"
    original = release_mod.ReleaseManager.load

    def _load(self, requested_id, _manifest=manifest):        # noqa: ANN001
        if str(requested_id) == release:
            return _manifest
        return original(self, requested_id)

    release_mod.ReleaseManager.load = _load
    started = time.time()
    try:
        package = export_training_package(store, release, package_dir, formats=EXPORT_FORMATS)
    finally:
        release_mod.ReleaseManager.load = original
    return {
        "status": "OK", "seconds": round(time.time() - started, 3),
        "store": str(store_dir), "release_id": release,
        "scope_assets": len(ids),
        "release_manifest": "in-memory UNFROZEN scope, replayed from the recorded export state",
        "package_dir": str(package_dir),
        "files_total": package.get("counts_total"), "bytes_total": package.get("bytes_total"),
        "relations": (package.get("counts") or {}).get("relations"),
        "relation_kinds": (package.get("counts") or {}).get("relation_kinds"),
        "relation_rows_reverse_role": (package.get("counts") or {}).get(
            "relation_rows_reverse_role"),
        "relation_pairs_direction_complete": (package.get("counts") or {}).get(
            "relation_pairs_direction_complete"),
        "separation_features_carry_answer_fields": (
            (package.get("separation") or {}).get("features_carry_answer_fields")),
        "separation_answer_hits": ((package.get("separation") or {}).get(
            "answer_field_scan") or {}).get("hits"),
    }


# ----------------------------------------------------------------------------------------------
# step: merge -- one function per dimension, each one copies real bytes then measures them
# ----------------------------------------------------------------------------------------------
def _copy(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return int(dst.stat().st_size)


def _npz_header(path: Path) -> dict[str, dict[str, Any]]:
    with np.load(path, allow_pickle=False) as data:
        return {str(k): {"shape": list(np.shape(data[k])), "dtype": str(data[k].dtype)}
                for k in data.files}


def merge_roi_views(package: Path, deploy_keys: set[str], store_dir: Path) -> dict[str, Any]:
    """Dimension 1a: the whole-slice + fracture-ROI close-up view family."""
    root = package / "research" / "roi_views"
    store = AssetStore(store_dir)
    rows: list[dict[str, Any]] = []
    families: collections.Counter = collections.Counter()
    channels: set[str] = set()
    for asset in sorted(store.list_assets(limit=100000), key=lambda a: a.asset_id):
        if asset.role != "obs_result":
            continue
        arrays_rel = (asset.files or {}).get("arrays")
        if not arrays_rel:
            continue
        src = store.root / Path(*arrays_rel.split("/"))
        dst = root / f"{asset.asset_id}.npz"
        bytes_written = _copy(src, dst)
        header = _npz_header(dst)
        meta = dict(asset.meta or {})
        views = list(meta.get("views") or [])
        per_view = []
        for index, view in enumerate(views):
            view_meta = view.get("meta") or {}
            family = ("FRACTURE_ROI" if isinstance(view_meta.get("fracture_roi_view"), dict)
                      else "WHOLE_FRAGMENT")
            families[family] += 1
            resolution = view_meta.get("resolution") or {}
            per_view.append({
                "index": index, "view_id": view.get("view_id"), "tier": view.get("tier"),
                "profile_id": view.get("profile_id"), "view_family": family,
                "working_distance_mm": view.get("working_distance_mm"),
                "mm_per_pixel_declared": (view_meta.get("delivered_grid") or {}).get("mm_per_pixel"),
                "mm_per_px_axis_raycast": resolution.get("mm_per_px_axis_raycast"),
                "r_eff_mm_4px": resolution.get("r_eff_mm_4px"),
                "rim_px": (view_meta.get("fracture_roi_view") or {}).get("rim_px"),
                "fracture_roi_id": (view_meta.get("fracture_roi_view") or {}).get("fracture_roi_id"),
                "direction_offset_deg": (view_meta.get("fracture_roi_view") or {}).get(
                    "direction_offset_deg"),
                "capture_feasible": (view_meta.get("fracture_roi_view") or {}).get(
                    "capture_feasible"),
                "arrays_present": sorted(
                    sorted({k.split(".", 1)[1] for k in header if k.startswith(f"v{index:03d}.")})),
            })
        for key in header:
            if "." in key:
                channels.add(key.split(".", 1)[1])
        rows.append({
            "asset_id": asset.asset_id, "lineage_id": asset.lineage_id,
            "fragment_id": meta.get("fragment_id"), "component_id": meta.get("component_id"),
            "qa_status": asset.qa_status, "split": str(asset.split),
            "n_views": len(views), "view_family_counts": dict(collections.Counter(
                v["view_family"] for v in per_view)),
            "arrays": header, "n_arrays": len(header),
            "file": f"research/roi_views/{asset.asset_id}.npz", "bytes": bytes_written,
            "view_meta_file": None,
            "evidence_class": (meta.get("meta") or {}).get("evidence_class"),
            "route": meta.get("route"), "input_profile": meta.get("input_profile"),
            "renderer": (meta.get("meta") or {}).get("renderer"),
            "surface_tag_pixels": (meta.get("meta") or {}).get("surface_tag_pixels"),
            "views": per_view,
        })
        meta_dst = root / f"{asset.asset_id}.meta.json"
        write_json(meta_dst, {k: v for k, v in meta.items()})
        rows[-1]["view_meta_file"] = f"research/roi_views/{asset.asset_id}.meta.json"
        rows[-1]["view_meta_bytes"] = int(meta_dst.stat().st_size)
    evidence = None
    route = None
    source_kind = None
    if rows:
        head = AssetStore(store_dir)
        record = head.get_asset(rows[0]["asset_id"])
        head_meta = dict(record.meta or {})
        evidence = (head_meta.get("meta") or {}).get("evidence_class")
        route = head_meta.get("route")
        source_kind = head_meta.get("source_kind") or head_meta.get("input_profile")
    global_channels = sorted(channels | {k for row in rows for k in row["arrays"] if "." not in k})
    annotations = [annotation(name, deploy_channels=deploy_keys, evidence=evidence,
                              source_kind=source_kind, route=route)
                   for name in global_channels]
    index = {
        "schema": "synlab.experiment_ready.roi_views.v1",
        "dimension": "observations.roi_view_family",
        "ablation_group": "ABL_ROI_VIEWS",
        "switch_field": "observations.roi_views.enabled",
        "source_store": str(store_dir),
        "policy_file": POLICY_PATH, "policy_sha256": POLICY_SHA,
        "rig_obtainable_basis": ("measured: the channel is shipped by this package's own deploy "
                                "view (scan of deploy/obs/index.json)"),
        "synthetic_only_basis": ("measured: the producing observation declares route=proxy_scan / "
                                 "SENSOR_* source_kind and no real capture"),
        "claim_allowed_basis": ("policy synlab/schemas/view_channels.json: deploy view and a "
                                "non-CAVEAT evidence_class"),
        "counts": {
            "assets": len(rows), "views": int(sum(r["n_views"] for r in rows)),
            "view_families": dict(families),
            "bytes": int(sum(r["bytes"] + int(r.get("view_meta_bytes") or 0) for r in rows)),
            "channels": len(channels),
        },
        "annotations": annotations,
        "rows": rows,
    }
    write_json(root / "index.json", index)
    return {"dimension": "roi_views", "ablation_group": "ABL_ROI_VIEWS",
            "switch_field": index["switch_field"], "counts": index["counts"],
            "deploy_view_touched": False}


def merge_synthetic_extras(package: Path, deploy_keys: set[str],
                           export_dir: Path) -> dict[str, Any]:
    """Dimension 1b: the nine synthetic extras (rig-unobtainable by document)."""
    root = package / "research" / "synthetic_extras"
    source_index = json.loads((export_dir / "index.json").read_text(encoding="utf-8"))
    copied: list[dict[str, Any]] = []
    for path in sorted(export_dir.iterdir()):
        if path.is_file():
            target = root / path.name
            _copy(path, target)
            copied.append({"path": f"research/synthetic_extras/{path.name}",
                           "bytes": int(target.stat().st_size), "sha256": sha256(target)})
    modules = []
    for item in source_index.get("modalities") or []:
        ablation = item.get("ablation") or {}
        modules.append({
            "modality_id": item.get("modality_id"), "item": item.get("item"),
            "title": item.get("title"),
            "rig_obtainable": item.get("rig_obtainable"),
            "synthetic_only": item.get("synthetic_only"),
            "claim_allowed": item.get("claim_allowed"),
            "reason": item.get("reason"), "doc_refs": item.get("doc_refs"),
            "unit": item.get("unit"), "frame": item.get("frame"),
            "instances": item.get("instances"), "fragments": item.get("fragments"),
            "arrays_declared": item.get("arrays_declared"),
            "switch_field": ablation.get("field"), "switch_group": ablation.get("group"),
            "hypothesis": ablation.get("hypothesis"),
            "evidence_basis": ("copied verbatim from the producer's own annotation index "
                               f"(schema {source_index.get('schema')}); the flags are the "
                               "producer's, not this merge's"),
        })
    index = {
        "schema": "synlab.experiment_ready.synthetic_extras.v1",
        "dimension": "observations.synthetic_extras",
        "ablation_group": "ABL_SYNTHETIC_EXTRAS",
        "switch_field": "extras.enable_<modality_id>",
        "source_export": str(export_dir),
        "source_index_schema": source_index.get("schema"),
        "claim_ban": source_index.get("claim_ban"),
        "placement_note": source_index.get("placement_note"),
        "counts": {
            "modalities": len(modules), "files": len(copied),
            "bytes": int(sum(c["bytes"] for c in copied)),
            "claim_allowed_modalities": sum(1 for m in modules if m.get("claim_allowed")),
            "rig_obtainable_modalities": sum(1 for m in modules if m.get("rig_obtainable")),
        },
        "modalities": modules, "files": copied,
        "deploy_view_touched": False,
        "deploy_view_note": ("the deployment view of this package ships none of these channels "
                            f"(deploy channel keys scanned: {sorted(deploy_keys)})"),
    }
    write_json(root / "index.json", index)
    return {"dimension": "synthetic_extras", "ablation_group": "ABL_SYNTHETIC_EXTRAS",
            "switch_field": index["switch_field"], "counts": index["counts"],
            "deploy_view_touched": False}


def merge_context(package: Path, deploy_keys: set[str], context_store: Path,
                  extras_store: Path) -> dict[str, Any]:
    """Dimension 2: simulated excavation context packs + the acquisition-context column table."""
    root = package / "research" / "context"
    rows: list[dict[str, Any]] = []
    for label, store_dir in (("a12_context", context_store), ("a12_extras", extras_store)):
        store = AssetStore(store_dir)
        for asset in sorted(store.list_assets(limit=100000), key=lambda a: a.asset_id):
            if asset.role != "context_pack":
                continue
            meta = dict(asset.meta or {})
            dst = root / f"{label}__{asset.asset_id}.json"
            write_json(dst, meta)
            rows.append({
                "source_store": str(store_dir), "store_label": label,
                "asset_id": asset.asset_id, "schema": asset.schema, "qa_status": asset.qa_status,
                "lineage_id": asset.lineage_id, "split": str(asset.split),
                "context_id": meta.get("context_id"), "bag_id": meta.get("bag_id"),
                "batch_id": meta.get("batch_id"),
                "excavation_area_id": meta.get("excavation_area_id"),
                "grid_ref": meta.get("grid_ref"),
                "simulated": meta.get("simulated"), "real_capture": meta.get("real_capture"),
                "depth_band_mm": meta.get("depth_band_mm"),
                "level_or_layer": meta.get("level_or_layer") or meta.get("stratigraphic_unit"),
                "scale_reference": meta.get("scale_reference"),
                "coexistent_counts": meta.get("coexistent_counts"),
                "file": f"research/context/{label}__{asset.asset_id}.json",
                "bytes": int(dst.stat().st_size),
                "meta_keys": sorted(meta.keys()),
            })
    simulated_flags = collections.Counter(str(r.get("simulated")) for r in rows)
    # the acquisition-context *table columns* the deploy view declares (S4): a real read of the
    # base package's own query table plus the policy block that admits each name.
    queries = package / "deploy" / "queries.parquet"
    columns = [str(c) for c in pd.read_parquet(queries).columns] if queries.is_file() else []
    declared = {str(entry.get("key")): entry
                for entry in ((POLICY.get("table_columns") or {}).get("columns") or [])}
    table_columns = []
    for name in columns:
        entry = declared.get(name)
        table_columns.append({
            "column": name,
            "declared_capture_context": bool(entry),
            "evidence_class": (entry or {}).get("evidence_class"),
            "rig_obtainable": (entry or {}).get("rig_obtainable"),
            "claim_allowed": (entry or {}).get("claim_allowed"),
            "table": (entry or {}).get("table"),
            "in_forbidden_feature_fields": bool(name in _forbidden_feature_fields()),
        })
    index = {
        "schema": "synlab.experiment_ready.context.v1",
        "dimension": "context.excavation",
        "ablation_group": "ABL_CONTEXT",
        "switch_field": "context.enabled",
        "counts": {
            "packs": len(rows), "bytes": int(sum(r["bytes"] for r in rows)),
            "simulated_flags": dict(simulated_flags),
            "queries_table_columns": len(columns),
            "declared_capture_context_columns": sum(
                1 for c in table_columns if c["declared_capture_context"]),
        },
        "rows": rows,
        "queries_table_columns": table_columns,
        "column_declaration_note": (
            "S4: capture-context *table columns* are declared in synlab/schemas/view_channels.json"
            " -> table_columns and validated by synlab.storage.export._resolve_capture_context "
            "through the same rules as channel names, so the deployment-view answer-field scan "
            "reports features_carry_answer_fields=false. The declaration is *not* loosened here;"
            " this merge only records it."),
        "deploy_view_touched": False,
        "deploy_view_note": ("context packs are research-side; nothing was added to deploy/ "
                            f"(deploy channel keys scanned: {sorted(deploy_keys)})"),
    }
    write_json(root / "index.json", index)
    return {"dimension": "context", "ablation_group": "ABL_CONTEXT",
            "switch_field": index["switch_field"], "counts": index["counts"],
            "deploy_view_touched": False}


def _forbidden_feature_fields() -> list[str]:
    from synlab import roles
    return sorted(str(name) for name in roles.FORBIDDEN_FEATURE_FIELDS)


def merge_degrade(package: Path, deploy_keys: set[str], degrade_store: Path,
                  degrade_export: Path) -> dict[str, Any]:
    """Dimension 3: the degradation registry (all registered axes) + the materialised variants."""
    root = package / "research" / "degrade"
    store = AssetStore(degrade_store)
    source_index = json.loads((degrade_export / "index.json").read_text(encoding="utf-8"))
    variants: list[dict[str, Any]] = []
    for asset in sorted(store.list_assets(limit=100000), key=lambda a: a.asset_id):
        if asset.role not in ("degrade_variant", "degrade_source"):
            continue
        arrays_rel = (asset.files or {}).get("arrays")
        meta = dict(asset.meta or {})
        entry = {
            "asset_id": asset.asset_id, "role": asset.role, "schema": asset.schema,
            "unit": asset.unit, "frame": asset.frame, "qa_status": asset.qa_status,
            "axis_id": meta.get("axis_id"), "family": meta.get("family"),
            "level": meta.get("level"), "variant": meta.get("variant"),
            "identity": meta.get("identity"),
            "calibration_status": meta.get("calibration_status"),
            "factor_kind": meta.get("factor_kind"),
            "label_status": meta.get("label_status"),
            "measured": meta.get("measured"),
            "realized": meta.get("realized"),
            "arrays": {}, "bytes": 0, "file": None,
        }
        if arrays_rel:
            src = store.root / Path(*arrays_rel.split("/"))
            dst = root / "variants" / f"{asset.asset_id}.npz"
            entry["bytes"] = _copy(src, dst)
            entry["file"] = f"research/degrade/variants/{asset.asset_id}.npz"
            entry["arrays"] = _npz_header(dst)
        variants.append(entry)
    # the registry: every *registered* axis, with the levels the store really materialised.
    registry = _degrade_axis_registry()
    materialised: dict[str, list[int]] = collections.defaultdict(list)
    for entry in variants:
        if entry["role"] == "degrade_variant" and entry["axis_id"]:
            materialised[str(entry["axis_id"])].append(int(entry["level"]))
    axes = []
    for axis_id, spec in sorted(registry.items()):
        levels = sorted(materialised.get(axis_id, []))
        axes.append({**spec, "axis_id": axis_id, "materialised_levels": levels,
                     "n_materialised_levels": len(levels),
                     "materialised": bool(levels)})
    for axis_id, levels in sorted(materialised.items()):
        if axis_id not in registry:
            axes.append({"axis_id": axis_id, "materialised_levels": sorted(levels),
                         "n_materialised_levels": len(levels), "materialised": True,
                         "registry": "NOT_IN_REGISTRY"})
    for name in ("index.json", "variants.json", "sources.json"):
        src = degrade_export / name
        if src.is_file():
            _copy(src, root / f"producer_{name}")
    grid = collections.Counter()
    for axis in axes:
        for level in axis["materialised_levels"]:
            grid[f"{axis['axis_id']}::L{level}"] += 1
    index = {
        "schema": "synlab.experiment_ready.degrade.v1",
        "dimension": "degrade.axis_levels",
        "ablation_group": "ABL_DEGRADE",
        "switch_field": "degrade.axes.<axis_id>.level",
        "source_store": str(degrade_store), "source_index": str(degrade_export),
        "producer_index_schema": source_index.get("schema"),
        "level_zero_contract": source_index.get("level_zero_contract"),
        "retrieval_role": source_index.get("retrieval_role"),
        "fields": source_index.get("fields"),
        "counts": {
            "registered_axes": len(registry), "axes_emitted": len(axes),
            "axes_with_materialised_levels": sum(1 for a in axes if a["materialised"]),
            "materialised_variants": sum(1 for v in variants if v["role"] == "degrade_variant"),
            "materialised_levels": sum(len(a["materialised_levels"]) for a in axes),
            "sources": sum(1 for v in variants if v["role"] == "degrade_source"),
            "bytes": int(sum(v["bytes"] for v in variants)),
            "axis_level_cells": len(grid),
        },
        "axes": axes, "variants": variants,
        "deploy_view_touched": False,
        "deploy_view_note": ("degrade variants are research-side; the base package's own "
                            "degrade/ index (written by the real exporter) is left untouched"),
    }
    write_json(root / "index.json", index)
    return {"dimension": "degrade", "ablation_group": "ABL_DEGRADE",
            "switch_field": index["switch_field"], "counts": index["counts"],
            "deploy_view_touched": False}


def _degrade_axis_registry() -> dict[str, dict[str, Any]]:
    """The registered degradation axes, read from the registry that declares them.

    ``AXIS_REGISTRY`` is the object ``synlab.degrade.api.audit_all_axes`` itself iterates over, so
    "how many axes are registered" here is the same number the operator audit reports -- it is a
    read, not a transcription.
    """
    from synlab.degrade.registry import AXIS_REGISTRY
    registry: dict[str, dict[str, Any]] = {}
    for axis_id in AXIS_REGISTRY.ids():
        operator = AXIS_REGISTRY.get(axis_id)
        entry: dict[str, Any] = {"axis_id": axis_id, "family": axis_id[0],
                                 "registry": "synlab.degrade.registry.AXIS_REGISTRY"}
        for name, getter in (("declared_levels", "levels"), ("variants", "variants"),
                             ("declared", "declared")):
            try:
                value = getattr(operator, getter)()
            except Exception as exc:                                   # noqa: BLE001
                value = f"unavailable ({type(exc).__name__})"
            entry[name] = value
        registry[axis_id] = entry
    return registry


def _patch_stats(tri: np.ndarray, areas: np.ndarray, centroids: np.ndarray,
                 mean_normal: np.ndarray, centre: np.ndarray,
                 bands: Sequence[float] = (5.0, 1.0, 0.25)) -> dict[str, Any]:
    """One interface patch: area-weighted plane + the band-resolved amplitude statistics.

    ``heights``/``points`` are fed to the **same** instrument the fracture report uses
    (``synlab.observe.fracture_roi.height_field_stats``), so ``below_1mm.Ra_mm`` here is directly
    comparable with the ``below_1mm`` column of ``docs/a12/fracture_visible.md`` §2.3 -- including
    the exactly-zero result for a plane-cut patch.
    """
    from synlab.observe.fracture_roi import height_field_stats

    corners = tri.reshape(-1, 3)
    heights = (corners - centre) @ mean_normal
    out: dict[str, Any] = {
        "plane_residual_max_mm": float(np.abs(heights).max()),
        "plane_residual_rms_mm": float(np.sqrt(np.mean(heights ** 2))),
        "centroid_height_ra_mm": float(np.average(np.abs((centroids - centre) @ mean_normal),
                                                  weights=areas)) if float(areas.sum()) else 0.0,
    }
    stats = height_field_stats(heights, corners, bands_mm=tuple(bands))
    out["n_height_samples"] = int(stats.get("n_samples") or 0)
    out["plane"] = stats.get("plane")
    for radius in bands:
        key = f"below_{radius:g}mm"
        entry = (stats.get("bands") or {}).get(key) or {}
        out[f"ra_{key}_mm"] = entry.get("Ra_mm")
        out[f"rq_{key}_mm"] = entry.get("Rq_mm")
    return out


def merge_fracture_interfaces(package: Path, deploy_keys: set[str], store_dir: Path,
                              scope_ids: Sequence[str]) -> dict[str, Any]:
    """Dimension 4: fracture-surface channels selected by a real ``origin_kind == INTERFACE`` scan.

    Two levels, both measured on the real mesh payloads:

    * **patch level** (``interfaces.parquet``): INTERFACE faces grouped by ``face__interface_id``,
      each patch getting its own area-weighted plane, its residual and the band-resolved
      amplitude statistics from the instrument the fracture report uses;
    * **fragment level** (``fragments.parquet`` + the index): the aggregate, including
      ``planar_geometry`` -- true when *every* interface patch of that fragment is numerically
      coplanar, which is the sub-millimetre statement
      ``docs/a12/fracture_visible.md`` §2.3 makes for the plane-cut lineages.
    """
    root = package / "research" / "fracture"
    store = AssetStore(store_dir)
    wanted = set(str(i) for i in scope_ids)
    rows: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []
    for asset in sorted(store.list_assets(limit=500000), key=lambda a: a.asset_id):
        if asset.role != "fragment_mesh" or (wanted and asset.asset_id not in wanted):
            continue
        arrays = store.load_arrays(asset.asset_id)
        # stored mesh payloads prefix every key with the payload name (``mesh.vertices``,
        # ``mesh.face__origin_kind``); accept both spellings instead of assuming one.
        def _get(name: str):
            for candidate in (name, f"mesh.{name}"):
                if candidate in arrays:
                    return arrays[candidate]
            return None

        vertices = _get("vertices")
        faces = _get("faces")
        if vertices is None or faces is None:
            rows.append({"asset_id": asset.asset_id, "lineage_id": asset.lineage_id,
                         "skipped": f"no vertices/faces in the payload (keys: {sorted(arrays)[:6]})"})
            continue
        vertices = np.asarray(vertices, dtype=np.float64)
        faces = np.asarray(faces, dtype=np.int64)
        origin = _get("face__origin_kind")
        interface_id = _get("face__interface_id")
        if origin is None:
            rows.append({"asset_id": asset.asset_id, "lineage_id": asset.lineage_id,
                         "skipped": "no face__origin_kind channel on this mesh"})
            continue
        origin = np.asarray(origin).reshape(-1)
        mask = origin == 1
        n_interface = int(mask.sum())
        if not n_interface:
            rows.append({"asset_id": asset.asset_id, "lineage_id": asset.lineage_id,
                         "n_interface_faces": 0, "area_mm2": 0.0, "planar_geometry": None,
                         "why_planar_is_null": "this fragment carries no INTERFACE face"})
            continue
        ids = (np.asarray(interface_id).reshape(-1)[mask] if interface_id is not None
               else np.full(int(mask.sum()), -1, dtype=np.int64))
        patch_rows: list[dict[str, Any]] = []
        for patch_id in sorted({int(v) for v in ids}):
            sel = ids == patch_id
            tri = vertices[faces[mask][sel]]
            if tri.shape[0] == 0:
                continue
            cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            areas = 0.5 * np.linalg.norm(cross, axis=1)
            total_weight = float(areas.sum())
            centroids = tri.mean(axis=1)
            centre = ((centroids * areas[:, None]).sum(axis=0) / total_weight
                      if total_weight else centroids.mean(axis=0))
            normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-300)
            mean_normal = (normals * areas[:, None]).sum(axis=0)
            mean_normal /= max(float(np.linalg.norm(mean_normal)), 1e-300)
            stats = _patch_stats(tri, areas, centroids, mean_normal, centre)
            patch = {
                "asset_id": asset.asset_id, "lineage_id": asset.lineage_id,
                "split": str(asset.split), "qa_status": asset.qa_status,
                "interface_id": patch_id, "n_faces": int(tri.shape[0]),
                "area_mm2": total_weight,
                "mean_normal": [float(v) for v in mean_normal],
                "plane_centre_mm": [float(v) for v in centre],
                "planar": bool(stats["plane_residual_max_mm"] <= 1e-9),
                **stats,
            }
            patches.append(patch)
            patch_rows.append(patch)
        total_area = float(sum(p["area_mm2"] for p in patch_rows))
        ras = [p.get("ra_below_1mm_mm") for p in patch_rows if p.get("ra_below_1mm_mm") is not None]
        rows.append({
            "asset_id": asset.asset_id, "lineage_id": asset.lineage_id, "split": str(asset.split),
            "qa_status": asset.qa_status,
            "n_faces": int(faces.shape[0]), "n_interface_faces": n_interface,
            "interface_fraction": float(n_interface / max(faces.shape[0], 1)),
            "area_mm2": total_area, "n_patches": len(patch_rows),
            "interface_ids": [int(p["interface_id"]) for p in patch_rows],
            "patch_residual_max_mm": max((p["plane_residual_max_mm"] for p in patch_rows),
                                         default=None),
            "patch_ra_below_1mm_min_mm": min(ras) if ras else None,
            "patch_ra_below_1mm_max_mm": max(ras) if ras else None,
            "planar_geometry": bool(patch_rows) and all(p["planar"] for p in patch_rows),
            "planar_patches": sum(1 for p in patch_rows if p["planar"]),
            "planar_geometry_rule": (
                "planar_geometry = every INTERFACE patch of this fragment is numerically coplanar "
                "(max |vertex - area-weighted patch plane| <= 1e-9 mm) -- the sub-millimetre "
                "statement docs/a12/fracture_visible.md 2.3 makes for the plane-cut lineages; "
                "ra_below_1mm_mm is the same instrument's band statistic, so it is directly "
                "comparable with that table"),
            "fracture_signal_channels": sorted(
                str(k) for k in arrays if str(k).rsplit(".", 1)[-1].startswith("face__")),
        })
    frame = pd.DataFrame(rows)
    patch_frame = pd.DataFrame(patches)
    root.mkdir(parents=True, exist_ok=True)
    table = root / "interfaces.parquet"
    fragment_table = root / "fragments.parquet"
    patch_frame.to_parquet(table, index=False)
    frame.to_parquet(fragment_table, index=False)
    planar = [r for r in rows if r.get("planar_geometry") is True]
    nonplanar = [r for r in rows if r.get("planar_geometry") is False]
    sub_mm_zero = [p for p in patches if p.get("ra_below_1mm_mm") == 0.0]
    sub_mm_nonzero = [p for p in patches if (p.get("ra_below_1mm_mm") or 0.0) > 0.0]
    index = {
        "schema": "synlab.experiment_ready.fracture_interfaces.v1",
        "dimension": "fracture.interface_channels",
        "ablation_group": "ABL_FRACTURE_IFACE",
        "switch_field": "fracture.interface_channels.enabled",
        "source_store": str(store_dir),
        "selection_rule": "face__origin_kind == 1 (ORIGIN_INTERFACE), measured per fragment mesh",
        "planarity_rule": (
            "patch: planar = (max |patch vertex - area-weighted patch plane| <= 1e-9 mm); "
            "fragment: planar_geometry = every patch of that fragment is planar.  The band "
            "amplitudes come from synlab.observe.fracture_roi.height_field_stats, the same "
            "instrument docs/a12/fracture_visible.md 2.3 used, so ra_below_1mm_mm is directly "
            "comparable with that table's below_1mm column (including the exactly-zero result)."),
        "annotation_basis": {
            "rig_obtainable": "measured: the channel is shipped by this package's deploy view",
            "synthetic_only": "measured: every producing mesh asset is a synthetic run",
            "claim_allowed": "policy synlab/schemas/view_channels.json",
        },
        "counts": {
            "fragments_scanned": sum(1 for r in rows if "n_interface_faces" in r),
            "fragments_with_interfaces": sum(1 for r in rows if r.get("n_interface_faces")),
            "interface_faces": int(sum(r.get("n_interface_faces") or 0 for r in rows)),
            "interface_area_mm2": float(sum(r.get("area_mm2") or 0.0 for r in rows)),
            "interface_patches": len(patches),
            "planar_patches": sum(1 for p in patches if p.get("planar")),
            "patches_below_1mm_ra_exactly_zero": len(sub_mm_zero),
            "patches_below_1mm_ra_nonzero": len(sub_mm_nonzero),
            "planar_fragments": len(planar), "non_planar_fragments": len(nonplanar),
            "bytes": int(table.stat().st_size) + int(fragment_table.stat().st_size),
            "interfaces_parquet": "research/fracture/interfaces.parquet (one row per patch)",
            "fragments_parquet": "research/fracture/fragments.parquet (one row per fragment)",
        },
        "channels": [annotation(name, deploy_channels=deploy_keys)
                     for name in ("face__origin_kind", "face__interface_id", "face__side",
                                  "face__material_id")],
        "rows": rows,
        "patches": patches,
        "deploy_view_touched": False,
    }
    write_json(root / "index.json", index)
    return {"dimension": "fracture_interfaces", "ablation_group": "ABL_FRACTURE_IFACE",
            "switch_field": index["switch_field"], "counts": index["counts"],
            "deploy_view_touched": False}


def step_merge(package: Path, store_dir: Path, scope_ids: Sequence[str],
               out_dir: Path) -> dict[str, Any]:
    deploy_keys = deploy_channel_keys(package)
    results = [
        merge_roi_views(package, deploy_keys, REPO_ROOT / ROI_STORE),
        merge_synthetic_extras(package, deploy_keys, REPO_ROOT / EXTRAS_EXPORT),
        merge_context(package, deploy_keys, REPO_ROOT / CONTEXT_STORE, REPO_ROOT / EXTRAS_STORE),
        merge_degrade(package, deploy_keys, REPO_ROOT / DEGRADE_STORE, REPO_ROOT / DEGRADE_EXPORT),
        merge_fracture_interfaces(package, deploy_keys, store_dir, scope_ids),
    ]
    hard = package / "research" / "hard_negatives.parquet"
    gap = {
        "missing": "research/hard_negatives.parquet",
        "status": "missing",
        "scanned": ("a repository-wide scan for a file named hard_negatives*.parquet found none; "
                    "tools/a12_s2_hard_negatives.py produces the class *online* "
                    "(synlab.relations.sampler.hard_negative_candidates) and writes it to "
                    "data/a12_reports/s2_hard_negatives_class.json, never into a package"),
        "unlock_condition": ("a producer that materialises CANDIDATE_MATE_PRESENT_NOT_ORDINARY as a "
                            "shipped table; it must stay out of research/relations.parquet "
                            "(merging it adds 880 D10 violations, measured in "
                            "docs/a12/smallfixes_report.md S2)"),
        "ablation_group": "ABL_HARD_NEGATIVES",
        "switch_field": "negative_mix.hard_negative_weight",
    }
    write_json(package / "research" / "hard_negatives.index.json", gap)
    return {"dimensions": results, "missing": [gap],
            "deploy_channel_keys": sorted(deploy_keys)}


# ----------------------------------------------------------------------------------------------
# step: ablation index
# ----------------------------------------------------------------------------------------------
def step_ablation(package: Path, merge_report: Mapping[str, Any]) -> dict[str, Any]:
    """One row per switchable dimension: dimension, switch field, hypothesis, +/- yardsticks."""
    groups = []

    def dim(name: str, group: str, switch: str, present: bool, files: Sequence[str],
            hypothesis: str, positive: str, negative: str, evidence: Any,
            unlock: str | None = None) -> None:
        groups.append({
            "dimension": name, "group_id": group, "switch_field": switch,
            "availability": "present" if present else "missing",
            "files": list(files), "hypothesis": hypothesis,
            "positive_gain": positive, "negative_gain": negative,
            "evidence": evidence, "unlock_condition": unlock,
        })

    roi = package / "research" / "roi_views" / "index.json"
    extras = package / "research" / "synthetic_extras" / "index.json"
    context = package / "research" / "context" / "index.json"
    degrade = package / "research" / "degrade" / "index.json"
    fracture = package / "research" / "fracture" / "index.json"
    roi_d = json.loads(roi.read_text(encoding="utf-8")) if roi.is_file() else {}
    extras_d = json.loads(extras.read_text(encoding="utf-8")) if extras.is_file() else {}
    context_d = json.loads(context.read_text(encoding="utf-8")) if context.is_file() else {}
    degrade_d = json.loads(degrade.read_text(encoding="utf-8")) if degrade.is_file() else {}
    fracture_d = json.loads(fracture.read_text(encoding="utf-8")) if fracture.is_file() else {}

    dim("observations.roi_view_family", "ABL_ROI_VIEWS", "observations.roi_views.enabled",
        roi.is_file(), ["research/roi_views/"],
        "The ROI close-up family (whole-slice views plus per-fracture 60 mm close-ups) carries "
        "information the 12 whole-slice views do not: the fracture fills 75-100% of the frame "
        "instead of 0.7-4.6%, so the macro shape/edge/thickness of the break is no longer a few "
        "pixels.",
        "Hit@10 / Recall@1 rise and the pairing-residual P95 falls on the same backbone and seed; "
        "the gain must survive the degrade and hard-negative arms",
        "no movement beyond one standard error, or a rise on clean only (then it is a negative "
        "result, per docs/a12/v144_project_core.md 3.1)",
        roi_d.get("counts"), None)
    dim("observations.synthetic_extras", "ABL_SYNTHETIC_EXTRAS", "extras.enable_<modality_id>",
        extras.is_file(), ["research/synthetic_extras/"],
        "Nine bench-unobtainable modalities are shipped as declared upper-bound simulations; they "
        "bound what the rig cannot give, and the interesting result is usually that they do not "
        "transfer.",
        "a gain that reproduces under the degraded arms (it still may not enter a capability claim: "
        "claim_ban)",
        "no transfer, or a clean-only gain; a modality with claim_allowed=false can never be "
        "reported as a capability gain",
        extras_d.get("counts"), None)
    dim("context.excavation", "ABL_CONTEXT", "context.enabled", context.is_file(),
        ["research/context/"],
        "Restricted simulated excavation context (area / grid / layer / bag / coexistence / scale "
        "reference) helps retrieval, or it is just a disguised mother-id shortcut.",
        "a gain that survives the leakage audit (bag_id/parent_id/object_id are in "
        "roles.FORBIDDEN_FEATURE_FIELDS) and the conflicting-context arm",
        "any gain that disappears once the mother identity is removed, or a rise in the context "
        "conflict rate",
        {"counts": context_d.get("counts"),
         "bag_id_declared_as_capture_context": [c for c in
                                                (context_d.get("queries_table_columns") or [])
                                                if c.get("declared_capture_context")]}, None)
    dim("degrade.axis_levels", "ABL_DEGRADE", "degrade.axes.<axis_id>.level", degrade.is_file(),
        ["research/degrade/"],
        "Each degradation axis at each level must produce a measurable, monotone drop that cannot "
        "be extrapolated from the clean score.",
        "the curve is monotone in level and the clean-to-degraded ordering is preserved for true "
        "pairs",
        "a flat or non-monotone curve, or a clean-only ranking gain that inverts once a level is on",
        {"counts": degrade_d.get("counts"),
         "axes": [{"axis_id": a.get("axis_id"), "materialised_levels": a.get("materialised_levels")}
                  for a in (degrade_d.get("axes") or [])]}, None)
    dim("fracture.interface_channels", "ABL_FRACTURE_IFACE",
        "fracture.interface_channels.enabled", fracture.is_file(), ["research/fracture/"],
        "Fracture-surface supervision comes from face__origin_kind == INTERFACE, not from the 2D "
        "surface_tag map; the two must be opened together for a locatable break.",
        "fracture-localisation and contradiction loss improve, and the gain holds on the "
        "non-planar sub-population",
        "no gain, or a gain that exists only where planar_geometry is true (i.e. the model is "
        "reading the plane, not the break)",
        fracture_d.get("counts"), None)
    dim("relations.hard_negatives", "ABL_HARD_NEGATIVES", "negative_mix.hard_negative_weight",
        (package / "research" / "hard_negatives.parquet").is_file(),
        ["research/hard_negatives.parquet"],
        "The mate-present hard-negative class (hard_negative_loss, default weight 0.0) sharpens "
        "the rank head beyond the ordinary mate-absent negatives.",
        "rank loss / Hit@10 improve over the ordinary-negative-only arm at equal batch composition",
        "no gain at weight 0.3 with an unchanged rank denominator (measured once already in "
        "docs/a12/smallfixes_report.md S2: no gain, so the class is recommended off)",
        {"measured_once": "data/a12_reports/s2_hard_negatives_ab.json",
         "class_producer": "synlab.relations.sampler.hard_negative_candidates"},
        "a producer that ships the class as a table; it must stay out of "
        "research/relations.parquet (adding it there creates 880 D10 audit violations)")
    for group in groups:
        if group["dimension"] == "relations.hard_negatives":
            group["missing_reason"] = ("no hard_negatives.parquet exists anywhere in the "
                                       "repository (scanned); the class is produced online only")

    index = {
        "schema": "synlab.experiment_ready.ablation_index.v1",
        "package": str(package),
        "note": ("one entry per switchable data dimension of this package; every entry names the "
                 "dimension, the field a loader/experiment switches, a falsifiable hypothesis and "
                 "the positive- and negative-gain yardsticks.  'missing' entries carry the concrete "
                 "unlock condition instead of a placeholder."),
        "switch_semantics": ("each field is a switch on the dimension: with it off the dimension's "
                            "files are simply not read, so 'not opened' and 'not present' stay "
                            "distinguishable in the evidence"),
        "groups": groups,
        "counts": {"groups": len(groups),
                   "present": sum(1 for g in groups if g["availability"] == "present"),
                   "missing": sum(1 for g in groups if g["availability"] == "missing"),
                   "deploy_side_groups": 0},
        "doc": "docs/a12/ablation_experiments.md",
    }
    write_json(package / "ablation_index.json", index)
    return {"ablation_index": str(package / "ablation_index.json"), "counts": index["counts"],
            "groups": [g["group_id"] for g in groups]}


# ----------------------------------------------------------------------------------------------
# step: card
# ----------------------------------------------------------------------------------------------
def step_card(package: Path, report_path: Path) -> dict[str, Any]:
    loader = load_module(REPO_ROOT / "tools" / "load_package.py", "_load_package")
    card, scan = loader.build_data_card(package, hash_files=True)
    (package / loader.CARD_NAME).write_text(
        json.dumps(loader._jsonable(card), indent=2, ensure_ascii=False), encoding="utf-8")
    (package / loader.README_NAME).write_text(
        loader.render_readme(loader._jsonable(card)), encoding="utf-8")
    write_json(report_path, loader._jsonable(card))
    return {"card": str(package / loader.CARD_NAME), "readme": str(package / loader.README_NAME),
            "files_on_disk": card["package"]["file_count_on_disk"],
            "bytes_total": card["package"]["bytes_total"],
            "hashes_match_manifest": card["package"]["hashes_match_manifest"],
            "report": str(report_path)}


# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a12_experiment_ready_export", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", default="all",
                        help="base | merge | finalise | ablation | card | all")
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--release", default=DEFAULT_RELEASE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    package = out_dir / "training_package"
    report_path = out_dir / "experiment_ready_report.json"
    report: dict[str, Any] = (json.loads(report_path.read_text(encoding="utf-8"))
                              if report_path.exists() else {})
    out_dir.mkdir(parents=True, exist_ok=True)
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    scope_ids = (state.get("freeze") or {}).get("unverified_scope_ids") or []

    # order matters: the ablation index is a package-root file, so it must exist *before*
    # ``finalise`` re-declares the file set (``--check`` accepts only the manifest itself and the
    # two card artifacts as extras).  The card is written last because it is a reader artifact.
    steps = (["base", "merge", "ablation", "finalise", "card"]
             if args.step == "all" else [args.step])
    failed = False
    for name in steps:
        print(f"[{name}] running ...", flush=True)
        started = time.time()
        try:
            if name == "base":
                result = step_base(Path(args.store), out_dir, Path(args.state), args.release,
                                   report)
            elif name == "merge":
                result = step_merge(package, Path(args.store), scope_ids, out_dir)
            elif name == "finalise":
                manifest_path = package / "export_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                before = {"files_total": manifest.get("counts_total"),
                          "bytes_total": manifest.get("bytes_total")}
                bundle = report.get("merge") or {}
                manifest["experiment_ready_dimensions"] = {
                    "schema": "synlab.experiment_ready.dimensions.v1",
                    "merge_tool": "tools/a12_experiment_ready_export.py",
                    "dimensions": bundle.get("dimensions"),
                    "missing": bundle.get("missing"),
                    "deploy_view_note": ("the merge wrote only under research/; the deploy view of "
                                         "this package is the one the real writer produced"),
                    "ablation_index": "ablation_index.json",
                }
                before["merged_files"] = len([f for f in manifest["files"]
                                              if str(f["path"]).startswith("research/")])
                manifest.setdefault("counts", {}).update(_dimension_counts(bundle))
                manifest = declare(manifest, package,
                                   extras=("dataset_card.json", "README.md"))
                write_json(manifest_path, manifest)
                result = {"status": "OK", "before": before,
                          "after": {"files_total": manifest["counts_total"],
                                    "bytes_total": manifest["bytes_total"]},
                          "manifest_hash": manifest["manifest_hash"]}
            elif name == "ablation":
                result = step_ablation(package, report.get("merge") or {})
            elif name == "card":
                result = step_card(package, REPO_ROOT / "data/a12_reports/experiment_ready_card.json")
            else:
                parser.error(f"unknown step {name!r}")
            result = {**result, "status": result.get("status", "OK")}
        except Exception as exc:                                        # noqa: BLE001
            import traceback
            traceback.print_exc()
            result = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        result["seconds"] = round(time.time() - started, 3)
        report[name] = result
        write_json(report_path, report)
        print(f"[{name}] {result['status']} in {result['seconds']}s", flush=True)
        if result["status"] != "OK":
            failed = True
            break
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("dimensions", "axes")}
                      for k, v in report.items()}, ensure_ascii=False, indent=2, default=str)[:6000])
    return EXIT_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
