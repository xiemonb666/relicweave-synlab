"""Fracture-surface signal: end-to-end runner into a NEW library (``data/a12_iface/store``).

Nothing here writes to ``data/a12`` except ``data/a12/reports/``; the library is the new
``data/a12_iface/store`` named by the task.  The generation chain is the *frozen* pipeline
(``synlab.pipeline.build_one_mother``: mother -> pattern/material -> fracture -> clean truth ->
physical damage -> observation -> features/labels/provenance -> store) with the stock
``configs/a12/sandbox.yaml``; only the store root is chosen here, so the measurement is of the
shipped code path and not of a private re-implementation.

Modes
-----
``--mode run``      run ``--only`` (default 2) lineages, then measure every hop.
``--mode measure``  measure an existing store (no generation).
``--mode before``   independently re-measure the *pre-fix* store ``data/a12``: the surface_tag
                    histogram of every committed ``obs_result`` (read-only, one asset at a time).

Every measured number is written to ``--report`` as JSON; the console prints a short table.

Exit codes: 0 report written, 3 a step raised, 4 the config failed to compile.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

REPORT_SCHEMA = "synlab.fracture_surface_signal.v1"
RIM_TAG = 2


def _wall(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _wall(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wall(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"__ndarray__": {"dtype": str(value.dtype), "shape": list(value.shape)}}
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


def histogram(values: np.ndarray) -> dict[str, int]:
    arr = np.asarray(values).reshape(-1)
    if arr.size == 0:
        return {}
    unique, counts = np.unique(arr, return_counts=True)
    return {str(int(k)): int(v) for k, v in zip(unique, counts)}


def _merge_counts(blocks) -> dict[str, int]:
    out: dict[str, int] = {}
    for block in blocks:
        for key, value in (block or {}).items():
            out[str(key)] = out.get(str(key), 0) + int(value)
    return out


def _merge_floats(blocks) -> dict[str, float]:
    out: dict[str, float] = {}
    for block in blocks:
        for key, value in (block or {}).items():
            out[str(key)] = out.get(str(key), 0.0) + float(value)
    return out


# --------------------------------------------------------------------------------------
# read-only store access (never creates a database, never writes)
# --------------------------------------------------------------------------------------
def store_rows(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for row in con.execute("select asset_id, role, schema, files_json, meta_json, qa_json, "
                           "lineage_id, qa_status from assets"):
        entry = dict(row)
        entry["files"] = json.loads(entry.pop("files_json") or "{}")
        entry["meta"] = json.loads(entry.pop("meta_json") or "{}")
        entry["qa"] = json.loads(entry.pop("qa_json") or "{}")
        out.append(entry)
    con.close()
    return out


def load_arrays(root: Path, row: dict, prefix: str | None = None) -> dict:
    rel = row["files"].get("arrays")
    if not rel:
        return {}
    with np.load(root / rel, allow_pickle=False) as data:
        out = {k: data[k] for k in data.files}
    if prefix is None:
        return out
    head = f"{prefix}."
    selected = {k[len(head):]: v for k, v in out.items() if k.startswith(head)}
    return selected or out


def only_keys(root: Path, row: dict, wanted: tuple[str, ...]) -> dict:
    """Read a subset of one asset's arrays without materialising the whole payload."""
    rel = row["files"].get("arrays")
    if not rel:
        return {}
    out = {}
    with np.load(root / rel, allow_pickle=False) as data:
        for key in data.files:
            if any(token in key for token in wanted):
                out[key] = data[key]
    return out


# --------------------------------------------------------------------------------------
# per-hop measurements
# --------------------------------------------------------------------------------------
def measure_physical(root: Path, rows: list[dict]) -> dict[str, Any]:
    """Hop 1: the committed ``physical_component`` / ``physical_result`` assets."""
    out: dict[str, Any] = {}
    for row in rows:
        if row["role"] not in ("physical_component", "physical_result"):
            continue
        arrays = load_arrays(root, row)
        entry: dict[str, Any] = {
            "asset_id": row["asset_id"], "role": row["role"], "lineage_id": row["lineage_id"],
            "array_keys": sorted(arrays),
            "face_channel_keys": sorted(k for k in arrays if k.startswith("face__")),
        }
        origin = arrays.get("face__origin_kind")
        iface = arrays.get("face__interface_id")
        if origin is not None:
            entry["origin_kind_histogram"] = histogram(origin)
            entry["faces"] = int(np.asarray(origin).size)
            entry["interface_faces"] = int(np.count_nonzero(np.asarray(origin) == 1))
        if iface is not None:
            entry["interface_id_histogram"] = histogram(iface)
        # ``metadata.sqlite.assets.meta_json`` holds the *inner* role metadata (the ``meta.json``
        # file wraps it under a top-level ``meta`` key), so the provenance block sits directly
        # under the row meta for both roles
        entry["face_provenance_meta"] = _wall((row["meta"] or {}).get("face_provenance"))
        entry["face_channel_arrays_declared"] = (row["meta"] or {}).get("face_channel_arrays")
        entry["qa_face_provenance"] = _wall((row["qa"] or {}).get("face_provenance"))
        out[row["asset_id"]] = entry
    return out


def measure_observation(root: Path, rows: list[dict]) -> dict[str, Any]:
    """Hop 2: the committed ``obs_result`` frames (delivered ``surface_tag`` per view)."""
    out: dict[str, Any] = {}
    for row in rows:
        if row["role"] != "obs_result":
            continue
        meta = row["meta"]
        inner = dict(meta.get("meta") or {})
        assets = only_keys(root, row, ("surface_tag", "id_map"))
        per_view: dict[str, Any] = {}
        totals: dict[str, int] = {}
        total_pixels = 0
        rim_pixels = 0
        object_pixels = 0
        n_views = len(meta.get("views") or [])
        for index in range(n_views):
            key = f"v{index:03d}.surface_tag"
            if key not in assets:
                continue
            tag = np.asarray(assets[key])
            hist = histogram(tag)
            for k, v in hist.items():
                totals[k] = totals.get(k, 0) + int(v)
            pixels = int(tag.size)
            total_pixels += pixels
            rim = int(hist.get(str(RIM_TAG), 0))
            rim_pixels += rim
            # a tagged pixel is a rendered object pixel; -1 is background
            object_here = pixels - int(hist.get("-1", 0))
            object_pixels += object_here
            per_view[f"v{index:03d}"] = {
                "pixels": pixels, "histogram": hist, "rim_pixels": rim,
                "object_pixels": int(object_here),
                "rim_fraction_of_view": (rim / pixels) if pixels else 0.0,
                "rim_fraction_of_object": (rim / object_here) if object_here else 0.0}
        out[row["asset_id"]] = {
            "asset_id": row["asset_id"], "lineage_id": row["lineage_id"],
            "fragment_id": meta.get("fragment_id"), "route": meta.get("route"),
            "target_meta": _wall((inner.get("target_meta") or {})),
            "surface_tag_source": inner.get("surface_tag_source"),
            "surface_tag_pixels_meta": _wall(inner.get("surface_tag_pixels")),
            "views": per_view,
            "pixels_total": int(total_pixels),
            "object_pixels": int(object_pixels),
            "histogram": totals,
            "rim_pixels": int(rim_pixels),
            "rim_fraction": (float(rim_pixels) / total_pixels) if total_pixels else 0.0,
            "rim_fraction_of_object": (float(rim_pixels) / object_pixels)
            if object_pixels else 0.0,
        }
    return out


def measure_truth(root: Path, rows: list[dict]) -> dict[str, Any]:
    """Hop 3: the three truth layers, with the ``iface_*`` fields each one carries."""
    out: dict[str, Any] = {}
    for row in rows:
        if row["role"] not in ("clean_truth", "physical_truth", "visible_labels"):
            continue
        arrays = load_arrays(root, row)
        meta = row["meta"]
        iface_keys = sorted(k for k in arrays if k.startswith("iface_"))
        entry: dict[str, Any] = {
            "asset_id": row["asset_id"], "role": row["role"], "lineage_id": row["lineage_id"],
            "array_keys": sorted(arrays), "iface_array_keys": iface_keys,
            "corr_array_keys": sorted(k for k in arrays if k.startswith("corr_")),
            "iface_meta_keys": sorted(k for k in meta if k.startswith("iface")),
            "qa_iface": {k: _wall(v) for k, v in (row["qa"] or {}).items()
                         if k.startswith("iface")},
        }
        ids = arrays.get("iface_id")
        if ids is not None:
            entry["iface_id_count"] = int(np.asarray(ids).size)
            entry["iface_ids"] = [int(x) for x in np.asarray(ids).reshape(-1)][:40]
        for key in ("iface_new_faces", "iface_new_area_mm2", "iface_area_mm2",
                    "iface_visible_samples", "iface_corr_samples"):
            if key in arrays:
                values = np.asarray(arrays[key])
                entry[key] = {"values": [float(x) for x in values.reshape(-1)][:40],
                              "total": float(np.sum(values))}
        for key in ("iface_new_faces_total", "iface_new_area_total_mm2",
                    "iface_origin_kind_faces", "iface_rim_pixels", "iface_rim_visible",
                    "iface_rim_pixels_per_view", "iface_visible_samples_by_id"):
            if key in meta:
                entry[key] = _wall(meta[key])
        entry["interface_count_meta"] = meta.get("interface_count")
        entry["truth_hash"] = meta.get("truth_hash")
        out[row["asset_id"]] = entry
    return out


def measure_lineage(root: Path, rows: list[dict], lineage_id: str) -> dict[str, Any]:
    mine = [r for r in rows if str(r["lineage_id"]) == lineage_id]
    physical = measure_physical(root, mine)
    observation = measure_observation(root, mine)
    truth = measure_truth(root, mine)
    components = [v for v in physical.values() if v["role"] == "physical_component"]
    # a lineage can own several committed components (re-runs / several damaged bodies); every one
    # is reported, and the summary sums the ones that really carry the face provenance block
    tagged = [v for v in components
              if isinstance(v.get("face_provenance_meta"), dict)
              and v["face_provenance_meta"].get("component")]
    faces = int(sum(int(v.get("faces", 0) or 0) for v in tagged))
    interface_faces = int(sum(int(v.get("interface_faces", 0) or 0) for v in tagged))
    class_faces: dict[str, int] = {}
    class_area: dict[str, float] = {}
    for entry in tagged:
        own = entry["face_provenance_meta"]["component"]
        for key, value in (own.get("classes") or {}).items():
            class_faces[str(key)] = class_faces.get(str(key), 0) + int(value)
        for key, value in (own.get("class_area_mm2") or {}).items():
            class_area[str(key)] = class_area.get(str(key), 0.0) + float(value)
    total_area = float(sum(class_area.values()))
    rim_pixels = sum(int(v["rim_pixels"]) for v in observation.values())
    pixels = sum(int(v["pixels_total"]) for v in observation.values())
    object_pixels = sum(int(v.get("object_pixels", 0)) for v in observation.values())
    return {
        "lineage_id": lineage_id,
        "assets": {r["asset_id"]: r["role"] for r in mine},
        "physical": physical,
        "observation": observation,
        "truth": truth,
        "summary": {
            "physical_components": len(components),
            "physical_components_with_face_provenance": len(tagged),
            "physical_faces": faces,
            "physical_class_faces": class_faces,
            "physical_class_area_mm2": class_area,
            "physical_class_area_fraction": {k: (v / total_area if total_area else 0.0)
                                             for k, v in class_area.items()},
            "physical_area_mm2": total_area,
            "physical_interface_faces": interface_faces,
            "physical_interface_face_fraction": (interface_faces / faces) if faces else 0.0,
            "observation_pixels": pixels,
            "observation_object_pixels": object_pixels,
            "observation_rim_pixels": rim_pixels,
            "observation_rim_fraction": (rim_pixels / pixels) if pixels else 0.0,
            "observation_rim_fraction_of_object": (rim_pixels / object_pixels)
            if object_pixels else 0.0,
            "rim_visible": bool(rim_pixels > 0),
        },
    }


# --------------------------------------------------------------------------------------
# pre-fix measurement (independent, read-only, on the shipped library data/a12)
# --------------------------------------------------------------------------------------
def measure_before(root: Path) -> dict[str, Any]:
    rows = store_rows(root / "metadata.sqlite")
    out: dict[str, Any] = {"root": str(root), "observations": {}, "totals": {}}
    totals: dict[str, int] = {}
    pixels = 0
    rim = 0
    for row in rows:
        if row["role"] != "obs_result":
            continue
        meta = row["meta"]
        n_views = len(meta.get("views") or [])
        assets = only_keys(root, row, ("surface_tag",))
        entry: dict[str, Any] = {"views": {}, "histogram": {}}
        for index in range(n_views):
            key = f"v{index:03d}.surface_tag"
            if key not in assets:
                continue
            hist = histogram(np.asarray(assets[key]))
            pixels += int(np.asarray(assets[key]).size)
            rim += int(hist.get(str(RIM_TAG), 0))
            for k, v in hist.items():
                totals[k] = totals.get(k, 0) + int(v)
            entry["views"][f"v{index:03d}"] = {
                "pixels": int(np.asarray(assets[key]).size),
                "rim_pixels": int(hist.get(str(RIM_TAG), 0))}
        entry["histogram"] = histogram(np.concatenate(
            [np.asarray(assets[k]).reshape(-1) for k in assets])) if assets else {}
        out["observations"][row["asset_id"]] = entry
        del assets
    out["totals"] = {"pixels": int(pixels), "histogram": totals, "rim_pixels": int(rim),
                     "observations": len(out["observations"])}
    # the physical components of the same library: the pre-fix origin_kind channel.  Two payload
    # layouts exist in the shipped store (flat ``face__*`` and nested ``mesh.face__*``); both are
    # counted, and the layout is reported so no component is silently skipped.
    before_origin: dict[str, int] = {}
    components = 0
    layouts: dict[str, int] = {}
    for row in rows:
        if row["role"] != "physical_component":
            continue
        arrays = only_keys(root, row, ("face__origin_kind",))
        key = next((k for k in arrays if k.endswith("face__origin_kind")), None)
        origin = None if key is None else arrays[key]
        if origin is None:
            layouts["missing"] = layouts.get("missing", 0) + 1
            continue
        components += 1
        layout = "flat" if key == "face__origin_kind" else key.rsplit(".", 1)[0]
        layouts[layout] = layouts.get(layout, 0) + 1
        for k, v in histogram(origin).items():
            before_origin[k] = before_origin.get(k, 0) + int(v)
    out["physical_component_origin_kind"] = before_origin
    out["physical_components"] = components
    out["physical_component_layouts"] = layouts
    out["physical_component_interface_faces"] = int(before_origin.get("1", 0))
    return out


# --------------------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------------------
def run_lineages(args: argparse.Namespace) -> dict[str, Any]:
    from synlab.config import load_generation_spec
    from synlab.pipeline import build_one_mother, plan_generation
    from synlab.registry import load_all
    from synlab.storage.store import AssetStore

    legacy: dict[str, Any] = {}
    if getattr(args, "legacy_target", False):
        legacy = _install_legacy_target()
    restored = {} if getattr(args, "no_shim", False) else missing_pipeline_names()
    load_all()
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    store = AssetStore(Path(args.root))
    wanted = {int(x) for x in str(args.only).split(",") if str(x).strip()}
    lineages = [l for l in plan.lineages if l.mother_index in wanted]
    if not lineages:
        raise SystemExit(f"no lineage matches --only {args.only}")
    run_id = args.run_id or f"run_iface_{plan.job_id.split('_', 1)[-1][:10]}"
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value,
                     profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(),
                           "batch_driver": "tests/a12/observe/run_iface_lineage.py"})
    out: dict[str, Any] = {"run_id": run_id, "root": str(store.root), "lineages": {},
                           "pipeline_names_restored": _wall(restored),
                           "legacy_target_control": _wall(legacy)}
    for lineage in lineages:
        t0 = time.time()
        entry: dict[str, Any] = {"lineage_id": lineage.lineage_id,
                                 "mother_index": int(lineage.mother_index)}
        try:
            outcome = build_one_mother(plan, lineage, store, run_id=run_id,
                                       total_lineages=len(lineages))
            row = dict(outcome.get("coverage_row") or {})
            entry.update({
                "ok": bool(outcome.get("ok")),
                "seconds": round(time.time() - t0, 2),
                "fragments": row.get("fragments"),
                "observations": row.get("observation_assets"),
                "r2_pairs": row.get("r2_pairs"),
                "physical_audit_status": row.get("physical_audit_status"),
                "stages": _wall(row.get("stages") or {}),
                "obs_endpoint_failures": _wall(row.get("obs_endpoint_failures") or {}),
                "error": outcome.get("error"),
            })
        except Exception as exc:  # noqa: BLE001 - one lineage's failure is a measured outcome
            entry.update({"ok": False, "seconds": round(time.time() - t0, 2),
                          "error": f"{type(exc).__name__}: {exc}",
                          "traceback": traceback.format_exc()[-2000:]})
        out["lineages"][lineage.lineage_id] = entry
        print(f"[run] {lineage.lineage_id} ok={entry.get('ok')} {entry.get('seconds')}s",
              flush=True)
        _write(args, {"run": out})
    store.set_run_status(run_id, "QA_PASSED" if any(
        v.get("ok") for v in out["lineages"].values()) else "FAILED")
    return out


def missing_pipeline_names() -> dict[str, Any]:
    """Restore constant *bindings* a concurrent writer left out of ``synlab.pipeline``.

    ``synlab/pipeline.py`` is outside this task's write scope and is being edited by another
    writer; at the time of this run it references ``SCHEMA_PROVENANCE`` without importing it
    (``NameError`` at ``pipeline.py:2483``), which aborts every lineage *after* the observation
    stage.  This helper only re-binds the missing name to its value in ``synlab.roles`` (a pure
    constant, no behaviour), records what it did, and does nothing when the module is complete.
    """
    import synlab.pipeline as pipeline
    from synlab import roles

    restored: dict[str, Any] = {}
    for name in ("SCHEMA_PROVENANCE", "SCHEMA_COVERAGE", "SCHEMA_LABELS", "SCHEMA_CONTEXT"):
        if not hasattr(pipeline, name) and hasattr(roles, name):
            setattr(pipeline, name, getattr(roles, name))
            restored[name] = getattr(roles, name)
    return restored


def _install_legacy_target() -> dict[str, Any]:
    """A/B control: restore the *pre-fix* behaviour of ``resolve_target``.

    The control answers exactly one question - "does this run fail because the target now carries
    a real provenance instead of an all-zero tag map?" - by catching the structured refusal and
    re-resolving with ``allow_unlabeled=True``, which reproduces the old silent all-zero map.
    Nothing else is patched.
    """
    from synlab.errors import SynLabError
    from synlab.observe import routes as rt

    original = rt.resolve_target
    seen = {"fallbacks": 0, "sources": []}

    def wrapper(obj, fragment_id=None, **kwargs):
        try:
            target = original(obj, fragment_id, **kwargs)
        except SynLabError:
            target = original(obj, fragment_id, allow_unlabeled=True)
            seen["fallbacks"] += 1
        seen["sources"].append(str((target.meta or {}).get("surface_tag_source")))
        return target

    rt.resolve_target = wrapper  # type: ignore[assignment]
    return seen


def run_observations(args: argparse.Namespace) -> dict[str, Any]:
    """Complete hops 2-3 of every lineage that already has a committed damaged component.

    This drives the **frozen** observation and truth APIs (``observe`` /
    ``commit_observation`` / ``update_visibility_truth`` / ``commit_truth``) on the committed
    ``physical_component`` instead of re-running the whole generation chain.  It exists because the
    full pipeline run is heavy and this host gives OpenCV allocation failures under memory
    pressure (see ``_probe_g01_crash.py``); the step performed is exactly pipeline step 7-8, and the
    store keeps both assets.
    """
    from synlab.config import load_generation_spec
    from synlab.observe.api import commit_observation, observe
    from synlab.observe.routes import resolve_target
    from synlab.pipeline import OBS_ROLE_PHYSICAL_TARGET, _resolve_observe_spec, _stamp_obs_semantics
    from synlab.registry import load_all
    from synlab.roles import ROLE_OBS_RESULT, ROLE_PHYSICAL_COMPONENT, ROLE_PHYSICAL_TRUTH
    from synlab.seeds import make_rng
    from synlab.storage.mesh_io import arrays_to_mesh
    from synlab.storage.store import AssetStore
    from synlab.truth.api import commit_truth, load_truth, update_visibility_truth

    load_all()
    store = AssetStore(Path(args.root))
    gen_spec = load_generation_spec(args.config)
    obs_spec = _resolve_observe_spec(gen_spec, store)
    run_id = args.run_id or "run_iface_observe"
    try:
        store.get_run(run_id)
    except Exception:  # noqa: BLE001 - an unknown run id is simply created below
        store.create_run(run_id, "observe-only", scope=gen_spec.data_scope.value,
                         profile=gen_spec.release_profile.value,
                         meta={"batch_driver": "tests/a12/observe/run_iface_lineage.py"})
    wanted = {x.strip() for x in str(args.only).split(",") if x.strip()}
    lineages = sorted({str(r.lineage_id) for r in
                       store.list_assets(role=ROLE_PHYSICAL_COMPONENT)})
    if wanted:
        def _index(lineage_id: str) -> str:
            head = lineage_id.split("_")[0]
            digits = "".join(ch for ch in head if ch.isdigit())
            return str(int(digits)) if digits else head

        lineages = [x for x in lineages if _index(x) in wanted]
    out: dict[str, Any] = {"run_id": run_id, "obs_spec": {
        "views": int(obs_spec.view_count), "delivered_size": list(obs_spec.delivered_size),
        "max_render_pixels": int(obs_spec.max_render_pixels)}, "lineages": {}}
    for lineage in lineages:
        entry: dict[str, Any] = {"lineage_id": lineage}
        t0 = time.time()
        components = [r for r in store.list_assets(role=ROLE_PHYSICAL_COMPONENT)
                      if str(r.lineage_id) == lineage]
        # the component that really carries the face provenance block
        chosen = None
        for record in components:
            meta = dict(record.meta or {})
            if (meta.get("face_provenance") or {}).get("attached"):
                chosen = record
        if chosen is None:
            entry["error"] = "no physical_component with attached face provenance"
            out["lineages"][lineage] = entry
            continue
        arrays = store.load_arrays(chosen.asset_id)
        selected = ({k: v for k, v in arrays.items()
                     if k in ("vertices", "faces") or k.startswith("face__")}
                    or {k.split(".", 1)[1]: v for k, v in arrays.items()
                        if k.startswith("mesh.")})
        mesh, attrs = arrays_to_mesh(selected)
        ancestor = str((chosen.meta or {}).get("ancestor") or "")
        target = resolve_target({"mesh": mesh, "fragment_id": ancestor}, None)
        entry["surface_tag_source"] = target.meta.get("surface_tag_source")
        entry["target_tag_histogram"] = target.meta.get("surface_tag_face_histogram")
        try:
            observation = observe({"mesh": mesh, "fragment_id": ancestor}, None,
                                  make_rng(gen_spec.master_seed, lineage, "camera"),
                                  route="proxy_scan", spec=obs_spec)
            _stamp_obs_semantics(observation, role=OBS_ROLE_PHYSICAL_TARGET,
                                 damage_state="DAMAGED", geometry_asset_id=chosen.asset_id)
            obs_record = commit_observation(store, observation, lineage_id=lineage,
                                            split=str(chosen.split or "train"),
                                            ancestry=[chosen.asset_id], run_id=run_id)
            truth_records = [r for r in store.list_assets(role=ROLE_PHYSICAL_TRUTH)
                             if str(r.lineage_id) == lineage]
            visible_record = None
            if truth_records:
                physical_truth = load_truth(store, truth_records[-1].asset_id,
                                            role=ROLE_PHYSICAL_TRUTH)
                visible = update_visibility_truth(physical_truth, observation)
                visible_record = commit_truth(store, visible, role="visible_labels",
                                              lineage_id=lineage,
                                              split=str(chosen.split or "train"),
                                              ancestry=[obs_record.asset_id],
                                              run_id=run_id)
            entry.update({
                "ok": True, "component_asset": chosen.asset_id,
                "observation_asset": obs_record.asset_id,
                "visible_labels_asset": (None if visible_record is None
                                         else visible_record.asset_id),
                "rim_pixels": int((observation.meta.get("surface_tag_pixels") or {}
                                   ).get("rim_pixels", 0)),
                "iface_rim_pixels": int((visible.qa.get("iface_rim_pixels", 0)
                                         if visible_record is not None else 0)),
                "seconds": round(time.time() - t0, 2),
            })
        except Exception as exc:  # noqa: BLE001 - one lineage's failure is a measured outcome
            entry.update({"ok": False, "seconds": round(time.time() - t0, 2),
                          "error": f"{type(exc).__name__}: {exc}",
                          "traceback": traceback.format_exc()[-1500:]})
        out["lineages"][lineage] = entry
        print(f"[observe] {lineage} ok={entry.get('ok')} rim={entry.get('rim_pixels')} "
              f"{entry.get('seconds')}s", flush=True)
        _write(args, {"observe_only": out})
    return out


# --------------------------------------------------------------------------------------
# report plumbing
# --------------------------------------------------------------------------------------
def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"schema": REPORT_SCHEMA}


def _write(args: argparse.Namespace, patch: dict[str, Any]) -> None:
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _load(path)
    document["schema"] = REPORT_SCHEMA
    document.update(_wall(patch))
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    tmp.replace(path)


def measure_store(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    rows = store_rows(root / "metadata.sqlite")
    lineages = sorted({str(r["lineage_id"]) for r in rows
                       if r["role"] == "physical_component"})
    measured = {lineage: measure_lineage(root, rows, lineage) for lineage in lineages}
    summary = {
        "root": str(root),
        "lineages": len(measured),
        "physical_components_with_face_provenance": sum(
            v["summary"]["physical_components_with_face_provenance"] for v in measured.values()),
        "physical_faces": sum(v["summary"]["physical_faces"] for v in measured.values()),
        "physical_interface_faces": sum(v["summary"]["physical_interface_faces"]
                                        for v in measured.values()),
        "physical_class_faces": _merge_counts(v["summary"]["physical_class_faces"]
                                              for v in measured.values()),
        "physical_class_area_mm2": _merge_floats(v["summary"]["physical_class_area_mm2"]
                                                 for v in measured.values()),
        "observation_pixels": sum(v["summary"]["observation_pixels"] for v in measured.values()),
        "observation_object_pixels": sum(v["summary"]["observation_object_pixels"]
                                         for v in measured.values()),
        "observation_rim_pixels": sum(v["summary"]["observation_rim_pixels"]
                                      for v in measured.values()),
        "observations": sum(len(v["observation"]) for v in measured.values()),
        "per_lineage": {k: v["summary"] for k, v in measured.items()},
    }
    summary["observation_rim_fraction"] = (
        summary["observation_rim_pixels"] / summary["observation_pixels"]
        if summary["observation_pixels"] else 0.0)
    summary["observation_rim_fraction_of_object"] = (
        summary["observation_rim_pixels"] / summary["observation_object_pixels"]
        if summary["observation_object_pixels"] else 0.0)
    summary["physical_interface_face_fraction"] = (
        summary["physical_interface_faces"] / summary["physical_faces"]
        if summary["physical_faces"] else 0.0)
    return {"measured": measured, "summary": summary}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "configs" / "a12" / "sandbox.yaml"))
    ap.add_argument("--root", default=str(ROOT / "data" / "a12_iface" / "store"))
    ap.add_argument("--before-root", default=str(ROOT / "data" / "a12"))
    ap.add_argument("--report",
                    default=str(ROOT / "data" / "a12" / "reports"
                                / "fracture_surface_signal" / "end_to_end.json"))
    ap.add_argument("--mode", choices=("run", "measure", "before", "observe-only"), default="run")
    ap.add_argument("--only", default="0,1")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--legacy-target", action="store_true",
                    help="A/B control: emulate the pre-fix all-zero tag map (see "
                         "_install_legacy_target)")
    ap.add_argument("--no-measure", action="store_true", help="run only, skip the measurement")
    ap.add_argument("--no-shim", action="store_true",
                    help="do not restore constant bindings a concurrent writer left out of "
                         "synlab.pipeline (see missing_pipeline_names)")
    args = ap.parse_args(argv)
    try:
        if args.mode == "run":
            run = run_lineages(args)
            _write(args, {"run": _wall(run)})
            if args.no_measure:
                print(json.dumps(_wall(run), ensure_ascii=False, indent=1)[:4000], flush=True)
                return 0
            measured = measure_store(args)
            _write(args, measured)
            print(json.dumps(measured["summary"], ensure_ascii=False, indent=1), flush=True)
        elif args.mode == "measure":
            measured = measure_store(args)
            _write(args, measured)
            print(json.dumps(measured["summary"], ensure_ascii=False, indent=1), flush=True)
        elif args.mode == "observe-only":
            observed = run_observations(args)
            _write(args, {"observe_only": _wall(observed)})
            print(json.dumps(_wall(observed), ensure_ascii=False, indent=1)[:3000], flush=True)
        else:
            before = measure_before(Path(args.before_root))
            _write(args, {"before": _wall(before)})
            print(json.dumps(_wall(before["totals"]), ensure_ascii=False, indent=1), flush=True)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
