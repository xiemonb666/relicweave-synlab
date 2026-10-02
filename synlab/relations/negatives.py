"""Store side of the relation-negative library: commit, pool, export, batch, verification.

What this module produces
-------------------------
``synlab.relations.multi_event`` builds a **real** mutually exclusive event library (several
fracture events per mother) and classifies every fragment pair.  This module turns that
measurement into the artifacts a loader actually consumes:

1. :func:`commit_library` -- one ``label_bundle`` per fragment (its own rows, so a negative can
   always be traced back to its event/lineage), one ``clean_truth`` per event (the measured
   within-event verdicts), the real ``fragment_mesh`` of every fragment, and optionally real
   ``obs_result`` + ``feature_bundle`` assets from :func:`observe_library`.
2. :func:`freeze_library_release` -- closure-verified release over those assets.  The release
   gates are those ``qc.gates.evaluate_gates`` actually returns for the run; **no gate is
   relaxed, overridden or claimed PASS without evidence**.  Because a relation-only companion
   store cannot satisfy a whole profile's required gates, the gate policy is recorded in the
   manifest and the release is not presented as profile-complete.
3. :func:`batch_rows_from_relations` / :func:`build_batch_from_package` -- a real
   :class:`synlab.training.batch.TrainingBatch` built from an **exported** training package
   with ``n_negatives > 0`` and per-row provenance.
4. :func:`audit_negative_sample` -- an independent recheck of sampled negatives against the raw
   event ledger (not against the classification it is checking).
5. :func:`discrimination_auc` -- the minimal relation discrimination experiment: a real legal
   observable score per pair, AUC, and a mother-clustered bootstrap interval.

Known integration gap (not worked around silently)
--------------------------------------------------
``synlab.training.batch.build_training_batch(pool=...)`` calls
``pool.neighbours(query)`` to decide whether a candidate is *historical R2*, but the frozen
:class:`synlab.qc.loader_probe.ExportedRelationPool` returns its **confirmed R1/R0** set from
``neighbours()`` and its R2 mates from ``mates()``.  Every real negative is therefore flagged
``is_history_r2`` and the batch builder raises ``LEAKAGE_DETECTED``.  ``qc/**`` is outside this
task's write scope, so :func:`build_training_batch_for_package` wires the same real labels
through the documented ``labels=`` form (``{"R2": ..., "R1": ..., "R0": ..., "confirmed": ...}``)
-- the identical rule set, with ``neighbours`` taken from ``pool.mates()`` -- and
:func:`build_batch_from_package` reports both outcomes instead of hiding either.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FRAME_WORLD,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_POOL,
    ROLE_ROSTER,
    SCHEMA_FEATURE,
    SCHEMA_FRAGMENT,
    SCHEMA_TRUTH_CLEAN,
    UNIT_MM,
)
from ..schemas.runtime import (
    RELATION_R0,
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
    CleanTruth,
    RelationEdge,
)
from ..storage.export import (
    EXCLUDED_NEGATIVE_KINDS,
    NEGATIVE_KINDS,
    TOKEN_DIM,
    TrainingPackage,
)
from ..storage.store import QA_PASS, AssetStore
from .multi_event import (
    MULTI_EVENT_VERSION,
    ROLE_UNRESOLVED,
    classify_library,
    library_fragments,
    library_hash,
    relation_histogram,
)

NEGATIVES_VERSION = "relations.negatives.v1"

#: ``a12.obs.v1`` array keys that are committed as arrays (mirrors
#: ``synlab.observe.features``/``pipeline._FEATURE_ARRAY_KEYS`` but is spelled here so the
#: feature bundle is written in the exact layout ``relations.gallery._feature_payload`` reads).
FEATURE_ARRAY_KEYS: tuple[str, ...] = (
    "global_rgb", "global_valid", "pixel_valid", "local_tokens", "token_valid", "token_view",
    "token_pixel", "token_modality", "token_source", "token_retrieval", "points", "point_valid",
    "normals", "normal_valid", "quality", "quality_valid", "presence", "presence_valid",
    "view_tokens", "roi_weight", "token_index", "roi_area_px",
)
FEATURE_SCALAR_KEYS: tuple[str, ...] = ("tokens_total", "scale_valid", "obs_version",
                                        "quality_tier")


# --------------------------------------------------------------------------------------
# 1. committing the library
# --------------------------------------------------------------------------------------
def _rows_of(rows: Sequence[Mapping[str, Any]], field: str, value: str
             ) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row.get("a")) == value or str(row.get("b")) == value]


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The relation row as it is written into a truth asset (no private bookkeeping)."""
    return {"a": str(row["a"]), "b": str(row["b"]), "kind": str(row["kind"]),
            "area_mm2": float(row.get("area_mm2", 0.0)), "valid": bool(row.get("valid", False)),
            "loss_mask": bool(row.get("loss_mask", False)),
            "interface_id": row.get("interface_id"), "reason": str(row.get("reason", "")),
            "decidability": str(row.get("decidability", "")),
            "evidence": row.get("evidence") or {}}


def commit_library(store: AssetStore, library: Mapping[str, Any], *,
                   run_id: str | None = None, mesh_dir: str | Path | None = None,
                   rows: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Persist the library: one label/truth asset per fragment and event (+ real meshes).

    Every fragment gets its **own** ``label_bundle`` carrying exactly the rows that mention it;
    ``synlab.relations.gallery.collect_fragments`` therefore attributes each fragment to its own
    event/mother/lineage instead of inheriting a neighbour's identity, and every negative stays
    traceable to the event that produced it.
    """
    relations = list(rows if rows is not None else classify_library(library))
    fragments = library_fragments(library)
    content_hash = library_hash(library)
    directory = Path(mesh_dir) if mesh_dir is not None else None
    committed: dict[str, Any] = {"schema": "synlab.relations.library_commit.v1",
                                 "version": NEGATIVES_VERSION,
                                 "library_hash": content_hash, "run_id": run_id,
                                 "label_bundles": {}, "clean_truth": {}, "fragment_mesh": {},
                                 "fragments": sorted(fragments), "relations": len(relations),
                                 "histogram": relation_histogram(relations)}
    for fragment_id, info in sorted(fragments.items()):
        own = [_public_row(row) for row in _rows_of(relations, "fragment_id", fragment_id)]
        incomplete = bool(info.get("truth_status") != "COMPUTED")
        history = {
            "event_id": info["event_id"],
            "historical_R2": [str(row["b"]) for row in own
                              if str(row["kind"]) == RELATION_R2 and str(row["a"]) == fragment_id]
                             + [str(row["a"]) for row in own
                                if str(row["kind"]) == RELATION_R2 and str(row["b"]) == fragment_id],
            "mate_present": any(str(row["kind"]) == RELATION_R2 for row in own),
            "association_kind": ("UNKNOWN_MAPPING" if incomplete else "EXACT_SURVIVOR"),
        }
        meta = {
            "fragment_id": fragment_id, "mother_id": info["mother_id"],
            "event_id": info["event_id"], "lineage_id": info["lineage_id"],
            "component_id": f"{fragment_id}::component",
            "observation_id": f"obs::{fragment_id}",
            "is_tiny": bool(info["is_tiny"]), "quality_tier": 0,
            "truth_incomplete": incomplete,
            "truth_status": str(info.get("truth_status", "COMPUTED")),
            "relation_count": len(own),
            "r2_count": sum(1 for row in own if str(row["kind"]) == RELATION_R2),
            "library_hash": content_hash, "library_version": MULTI_EVENT_VERSION,
            "event_seed_ref": str(info.get("event_seed_ref", "")),
            "history": history,
        }
        if run_id is not None:
            meta["run_id"] = str(run_id)
        record = store.commit_asset(
            role=ROLE_LABEL_BUNDLE, schema="synlab.labels.v1", unit="1", frame="W_mm",
            payload={"relations_json": json.dumps(own, ensure_ascii=False, sort_keys=True)},
            meta=meta, qa={"ok": True, "layer": "library", "library_hash": content_hash},
            qa_status=QA_PASS, lineage_id=info["lineage_id"], split=info["split"])
        committed["label_bundles"][fragment_id] = record.asset_id

        if directory is None:
            continue
        mesh_path = directory / f"mesh_{fragment_id}.npz"
        if not mesh_path.exists():
            continue
        payload = np.load(mesh_path)
        import trimesh

        mesh = trimesh.Trimesh(vertices=np.asarray(payload["vertices"]),
                               faces=np.asarray(payload["faces"]), process=False)
        from ..storage.mesh_io import with_face_attrs

        with_face_attrs(mesh,
                        origin_kind=np.asarray(payload["origin_kind"], dtype=np.uint8),
                        source_triangle=np.asarray(payload["source_triangle"], dtype=np.int32),
                        interface_id=np.asarray(payload["interface_id"], dtype=np.int32),
                        side=np.asarray(payload["side"], dtype=np.int8))
        mesh_meta = {"fragment_id": fragment_id, "event_id": info["event_id"],
                     "backend": "plane_shared_cut", "component_id": 0,
                     "is_tiny": bool(info["is_tiny"]),
                     "volume_mm3": float(info.get("volume_mm3", 0.0)),
                     "library_hash": content_hash}
        if run_id is not None:
            mesh_meta["run_id"] = str(run_id)
        mesh_record = store.commit_asset(
            role=ROLE_FRAGMENT_MESH, schema=SCHEMA_FRAGMENT, unit=UNIT_MM, frame=FRAME_WORLD,
            payload={"mesh": mesh}, meta=mesh_meta,
            qa={"ok": True, "library_hash": content_hash}, qa_status=QA_PASS,
            ancestry=[record.asset_id], lineage_id=info["lineage_id"], split=info["split"])
        committed["fragment_mesh"][fragment_id] = mesh_record.asset_id

    for mother in library.get("mothers") or []:
        mother_row = mother["mother"]
        for event in mother.get("events", []):
            if not event.get("ok") or event.get("truth_status") != "COMPUTED":
                continue
            event_rows = [_public_row(row) for row in event.get("relations", [])]
            edges = {}
            for row in event_rows:
                a, b = str(row["a"]), str(row["b"])
                key = (a, b) if a <= b else (b, a)
                edges[key] = RelationEdge(fragment_a=key[0], fragment_b=key[1],
                                          kind=str(row["kind"]),
                                          interface_id=row.get("interface_id"),
                                          area_mm2=float(row["area_mm2"]),
                                          valid=bool(row["valid"]), reason=str(row["reason"]),
                                          loss_mask=bool(row["loss_mask"]))
            truth = CleanTruth(
                mother_id=str(mother_row["lineage_id"]), event_id=str(event["event_id"]),
                version=1, relations=edges, interfaces=[], correspondence=[],
                event_tree={"event_id": str(event["event_id"]),
                            "backend": str(event.get("fracture_spec", {}).get("backend", "")),
                            "library_hash": content_hash,
                            "plane": event.get("plane")},
                qa={"pass": bool(event.get("clean_qa", {}).get("ok", True)),
                    "library_hash": content_hash, "multi_event": True,
                    "r2_area_threshold_mm2": event.get("r2_area_threshold_mm2"),
                    "tiny_area_threshold_mm2": event.get("tiny_area_threshold_mm2"),
                    "source": "relations.multi_event.run_event_library"},
                meta={"mother_id": str(mother_row["lineage_id"]),
                      "event_id": str(event["event_id"]),
                      "fragment_ids": [str(f) for f in event.get("fragment_ids", [])],
                      "library_hash": content_hash,
                      "fracture_qa": {k: v for k, v in (event.get("clean_qa") or {}).items()}})
            from ..truth.api import commit_truth

            record = commit_truth(store, truth, role=ROLE_CLEAN_TRUTH,
                                  lineage_id=str(mother_row["lineage_id"]),
                                  split=str(mother_row["split"]), run_id=run_id)
            committed["clean_truth"][str(event["event_id"])] = record.asset_id
    return committed


# --------------------------------------------------------------------------------------
# 2. real observations + feature bundles for a subset of the library
# --------------------------------------------------------------------------------------
def observe_library(plan: Any, store: AssetStore, *, fracture_config: Any,
                    events: Sequence[str], run_id: str | None = None,
                    route: str = "proxy_scan", view_count: int = 12,
                    renderer: str = "software_rasterizer") -> dict[str, Any]:
    """Observe selected events of the library for real and commit features in the legal layout.

    The fracture is re-run deterministically (same seeds, same event ids), then each **clean**
    fragment is observed through the frozen ``synlab.observe`` route.  Clean (undamaged) bodies
    are a legitimate observation tier -- plan 18.5 asks for at least 20% clean observations --
    and are declared as such in every asset; nothing here claims a damaged state.

    The committed ``feature_bundle`` uses the array names ``relations.gallery._feature_payload``
    actually reads (``points``/``normals``/``point_valid``/``normal_valid``/``quality``/...).
    ``synlab.pipeline`` writes ``point_cloud__xyz`` instead, which is why ``attach_features``
    attaches nothing for pipeline-produced bundles; that divergence is reported, not hidden.
    """
    from ..fracture.api import audit_fracture, fracture_event
    from ..fracture.spec import BACKEND_PLANE, FractureSpec
    from ..mothers.api import create_mother
    from ..observe.api import commit_observation, observe
    from ..observe.features import adapt_observed_features
    from ..observe.routes import ObsSpec
    from ..seeds import derive_named_rngs, make_rng
    from ..truth.api import finalize_clean_truth

    wanted = {str(e) for e in events}
    report: dict[str, Any] = {"schema": "synlab.relations.observe_library.v1",
                              "version": NEGATIVES_VERSION, "route": route,
                              "renderer": renderer, "run_id": run_id, "events": [],
                              "observations": {}, "features": {}, "ok": False}
    for mother_plan in plan.mothers:
        plan_events = [e for e in plan.events_of(mother_plan.mother_index)
                       if e.event_id in wanted]
        if not plan_events:
            continue
        rngs = derive_named_rngs(plan.master_seed, mother_plan.lineage_id)
        mother = create_mother(mother_plan.vessel_id, mother_plan.material_id,
                               mother_plan.params, rngs["shape"],
                               mother_id=mother_plan.mother_id)
        for event_plan in plan_events:
            entry: dict[str, Any] = {"event_id": event_plan.event_id, "fragments": [],
                                     "ok": False}
            report["events"].append(entry)
            started = time.perf_counter()
            if event_plan.role == ROLE_UNRESOLVED:
                entry["error"] = ("unresolved event: its fragments carry no relation evidence, "
                                  "so no observation is produced for them")
                continue
            try:
                rng = make_rng(plan.master_seed, mother_plan.lineage_id, "cut", event_plan.event_id)
                spec = FractureSpec(
                    backend=BACKEND_PLANE,
                    error_budget_mm=float(getattr(fracture_config,
                                                  "shared_surface_max_error_mm", 0.01)))
                fracture = fracture_event(mother, spec, rng, event_id=event_plan.event_id)
                audit_fracture(fracture, mother)
                finalize_clean_truth(mother, fracture)
                obs_spec = ObsSpec(master_seed=int(plan.master_seed),
                                   lineage_id=mother_plan.lineage_id, route=route,
                                   view_count=int(view_count), renderer=renderer)
            except Exception as exc:  # noqa: BLE001 - a failure is an outcome
                entry["error"] = f"{type(exc).__name__}: {exc}"
                entry["seconds"] = time.perf_counter() - started
                continue
            contract = {"schema": SCHEMA_FEATURE, "token_budget": TOKEN_DIM}
            for fragment in fracture.fragments:
                fragment_id = str(fragment.fragment_id)
                item: dict[str, Any] = {"fragment_id": fragment_id, "ok": False}
                entry["fragments"].append(item)
                t0 = time.perf_counter()
                try:
                    observation = observe(fragment, None, rngs, route=route,
                                          spec=obs_spec)
                    obs_record = commit_observation(
                        store, observation, lineage_id=mother_plan.lineage_id,
                        split=mother_plan.split, run_id=run_id)
                    bundles = adapt_observed_features(observation, contract)
                    arrays, meta_payload = feature_arrays_in_legal_layout(store,
                                                                          obs_record.asset_id,
                                                                          bundles)
                    if arrays is None:
                        item.update({"ok": False, "error": "adapt_observed_features produced no "
                                                           "usable payload for this fragment",
                                     "seconds": time.perf_counter() - t0})
                        report["observations"][fragment_id] = obs_record.asset_id
                        continue
                    meta = dict(meta_payload)
                    meta.update({"fragment_id": fragment_id, "schema": SCHEMA_FEATURE,
                                 "mother_id": mother_plan.lineage_id,
                                 "lineage_id": mother_plan.lineage_id,
                                 "event_id": event_plan.event_id,
                                 "observation_id": obs_record.asset_id,
                                 "observation_tier": "CLEAN_UNDAMAGED",
                                 "library_hash": library_hash({"plan": plan.as_dict()})})
                    if run_id is not None:
                        meta["run_id"] = str(run_id)
                    feature_record = store.commit_asset(
                        role=ROLE_FEATURE_BUNDLE, schema=SCHEMA_FEATURE, unit=UNIT_MM,
                        frame="S_mm", payload=arrays, meta=meta,
                        qa={"ok": True, "whitelist_checked": True,
                            "array_layout": "relations.gallery._feature_payload"},
                        qa_status=QA_PASS, ancestry=[obs_record.asset_id],
                        lineage_id=mother_plan.lineage_id, split=mother_plan.split)
                    item.update({"ok": True, "observation": obs_record.asset_id,
                                 "feature_bundle": feature_record.asset_id,
                                 "tokens_total": int(np.asarray(meta.get("tokens_total", 0))),
                                 "points": int(np.asarray(arrays.get("points",
                                                                    np.zeros((0, 3)))).shape[0]),
                                 "seconds": time.perf_counter() - t0})
                    report["observations"][fragment_id] = obs_record.asset_id
                    report["features"][fragment_id] = feature_record.asset_id
                except Exception as exc:  # noqa: BLE001
                    item.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                 "seconds": time.perf_counter() - t0})
            entry["ok"] = all(f.get("ok") for f in entry["fragments"]) and bool(entry["fragments"])
            entry["seconds"] = time.perf_counter() - started
    report["ok"] = bool(report["features"])
    report["observed_fragments"] = sorted(report["features"])
    report["failed_fragments"] = sorted(
        f["fragment_id"] for e in report["events"] for f in e["fragments"] if not f.get("ok"))
    return report


def feature_arrays_in_legal_layout(store: AssetStore, observation_asset_id: str,
                                   bundles: Mapping[str, Any]
                                   ) -> tuple[dict[str, np.ndarray] | None, dict[str, Any]]:
    """Flatten one ``adapt_observed_features`` bundle into the layout the reader expects.

    The nested groups are flattened with the frozen ``pipeline._flatten_features`` (so the
    ``point_cloud__xyz``-style names stay available for every existing consumer) and the
    delivered RGB/mask block is added with ``pipeline._observation_feature_block``.  On top of
    that the **aliases** ``points`` / ``normals`` / ``point_valid`` / ``normal_valid`` /
    ``quality`` / ``quality_valid`` are written, because those are the exact names
    ``relations.gallery._feature_payload`` reads back.  ``pipeline`` writes only the
    ``group__key`` names, which is why ``attach_features`` attaches nothing for pipeline-produced
    bundles -- the divergence is reported in ``docs/a12/relation_negatives.md``, not hidden.
    """
    from ..pipeline import _flatten_features, _observation_feature_block

    features = bundles.get("features") if isinstance(bundles, Mapping) else None
    if not isinstance(features, Mapping) or not features:
        return None, {}
    arrays, meta = _flatten_features(dict(features))
    encoded = _observation_feature_block(store, observation_asset_id)
    if encoded:
        arrays.update(encoded["arrays"])
        meta.update(encoded["meta"])
    aliases = {
        "points": "point_cloud__xyz", "point_valid": "point_cloud__valid",
        "normals": "normal_field__normals", "normal_valid": "normal_field__valid",
        "quality": "quality__values", "quality_valid": "quality__valid",
    }
    for target, source in aliases.items():
        if source in arrays and target not in arrays:
            arrays[target] = np.asarray(arrays[source])
    if "points" not in arrays or "global_rgb" not in arrays:
        return None, meta
    meta.setdefault("array_layout", "relations.gallery._feature_payload")
    return {str(k): np.asarray(v) for k, v in arrays.items()}, dict(meta)


# --------------------------------------------------------------------------------------
# 3. release freeze (measured gates, no profile claim)
# --------------------------------------------------------------------------------------
def freeze_library_release(store: AssetStore, *, release_id: str, run_id: str,
                           scope: str = "SYNTHETIC_RELATION_LIBRARY",
                           evidence_dirs: Sequence[str] = ("data/a12",),
                           extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Freeze a closure-verified release of one library run.

    The gate dictionary is whatever ``synlab.qc.gates.evaluate_gates`` measures for this run
    (with the declared additional evidence roots).  A profile's *required* gates are never
    relaxed: when they are not all PASS the release is written with
    ``required_gates = []`` and an explicit ``gate_policy`` stating that no profile is claimed,
    instead of stamping PASS values it did not measure.
    """
    from ..qc import gates as gates_mod
    from ..storage.release import PROFILE_GATES, ReleaseManager

    manager = ReleaseManager(store)
    run = store.get_run(run_id)
    assets = [a for a in store.list_assets(limit=500000)
              if (a.meta or {}).get("run_id") == run_id]
    keep = [a for a in assets if a.qa_status == QA_PASS]
    excluded = [{"asset_id": a.asset_id, "role": a.role, "qa_status": a.qa_status}
                for a in assets if a.qa_status != QA_PASS]
    if not keep:
        return {"status": "FAILED", "frozen": False,
                "error": {"code": "STOP_QA", "message": "the run has no QA_PASS asset"}}
    dirs = [d for d in evidence_dirs if Path(d).exists()]
    gates, _gate_assets, profile = gates_mod.evaluate_gates(store, run_id, evidence_dirs=dirs)
    evidence = gates_mod.gate_evidence(store, run_id, evidence_dirs=dirs)
    closure = manager.verify_closure([a.asset_id for a in keep])
    if not closure["ok"]:
        return {"status": "FAILED", "frozen": False, "closure": closure, "gates": gates,
                "error": {"code": "ASSET_HASH_MISMATCH",
                          "message": "reference closure does not verify",
                          "measurements": {"problems": closure["problems"][:8]}}}
    roles: dict[str, int] = {}
    for asset in keep:
        roles[asset.role] = roles.get(asset.role, 0) + 1
    splits: dict[str, int] = {}
    for asset in keep:
        splits[str(asset.split)] = splits.get(str(asset.split), 0) + 1
    coverage = {"run_id": run_id, "roles": roles, "splits": splits, "assets": len(keep),
                "store_profile": str(run.get("profile"))}
    blocking = sorted(g for g in PROFILE_GATES.get(profile, []) if gates.get(g) != "PASS")
    payload = dict(extra or {})
    payload.setdefault("gate_policy",
                       "gates are the measured verdicts of synlab.qc.gates.evaluate_gates for "
                       "this run; no profile is claimed and no gate was relaxed, overridden or "
                       "downgraded. A relation-only companion store cannot satisfy the full "
                       "profile gate set, and the pending gates are listed rather than filled.")
    payload.setdefault("store_profile_required_gates", PROFILE_GATES.get(profile, []))
    payload.setdefault("store_profile_blocking_gates", blocking)
    payload.setdefault("evidence_reports", evidence)
    payload.setdefault("excluded_assets", excluded[:200])
    started = time.time()
    manifest = {
        "schema": "synlab.release.v1", "release_id": release_id, "profile": profile,
        "scope": scope, "frozen_at": started, "gates": gates, "required_gates": [],
        "gate_policy": payload["gate_policy"],
        "scope_completed": [], "scope_pending": sorted(gates),
        "coverage": coverage,
        "assets": [{"asset_id": a.asset_id, **a.as_dict()} for a in sorted(
            keep, key=lambda r: r.asset_id)],
        "closure": {"ok": closure["ok"], "files_checked": closure["files_checked"]},
        "extra": _jsonable(payload),
    }
    manifest["manifest_hash"] = hash_json({k: v for k, v in manifest.items()
                                           if k not in ("frozen_at", "manifest_hash")})
    directory = store.root / "releases" / release_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    if path.exists():
        raise SynLabError(ErrorCode.STOP_QA,
                          f"release {release_id} already frozen (immutable)",
                          stage="relations.negatives.freeze_library_release")
    path.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    loaded = manager.load(release_id)
    return {"status": "OK", "frozen": True, "release_id": release_id,
            "manifest_hash": loaded["manifest_hash"], "manifest_path": str(path),
            "assets": len(keep), "assets_by_role": roles, "coverage": coverage,
            "gates": gates, "store_profile": profile,
            "store_profile_required_gates": PROFILE_GATES.get(profile, []),
            "store_profile_blocking_gates": blocking,
            "closure": manifest["closure"], "gate_policy": payload["gate_policy"],
            "excluded_asset_count": len(excluded)}


# --------------------------------------------------------------------------------------
# 4. a real training batch out of an exported package
# --------------------------------------------------------------------------------------
def batch_rows_from_relations(relations: Sequence[Mapping[str, Any]],
                              fragment_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Split the exported pair table into positives / legal negatives / excluded (plan 18.2).

    The rule is the frozen one (``storage.export`` + ``qc.loader_probe``): a **valid** ``R2``
    row is a positive, an ``R1``/``R0`` row that is ``valid`` *and* ``loss_mask``-ed is a legal
    negative, and everything else (``TINY_CONTACT``, ``UNKNOWN``, invalid or masked rows) is
    excluded -- an ``UNKNOWN`` pair is never turned into a negative.
    """
    known = {str(f) for f in fragment_ids}
    positives: dict[str, list[str]] = {}
    negatives: dict[str, list[str]] = {}
    excluded: dict[str, list[str]] = {}
    for row in relations:
        query = str(row.get("query", ""))
        candidate = str(row.get("candidate", ""))
        if not query or not candidate or query == candidate:
            continue
        if query not in known or candidate not in known:
            continue
        kind = str(row.get("kind", RELATION_UNKNOWN))
        valid = bool(row.get("valid", False))
        masked = bool(row.get("loss_mask", False))
        if kind == RELATION_R2 and valid:
            positives.setdefault(query, []).append(candidate)
        elif kind in NEGATIVE_KINDS and valid and masked:
            negatives.setdefault(query, []).append(candidate)
        else:
            excluded.setdefault(query, []).append(candidate)
    rows: list[dict[str, Any]] = []
    for query in sorted(set(positives) | set(negatives) | set(excluded)):
        rows.append({
            "query": query,
            "positives": sorted(dict.fromkeys(positives.get(query, []))),
            "negatives": sorted(dict.fromkeys(negatives.get(query, []))),
            "excluded": sorted(dict.fromkeys(excluded.get(query, []))),
            "r1_fallback": not any(
                str(r.get("kind")) == RELATION_R1 and str(r.get("query")) == query
                and bool(r.get("valid")) and bool(r.get("loss_mask")) for r in relations),
            "sample_key": f"negatives::{query}",
        })
    return rows


def _relation_lookup(relations: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for row in relations:
        a, b = str(row.get("query", "")), str(row.get("candidate", ""))
        if not a or not b:
            continue
        out[(a, b)] = dict(row)
        out.setdefault((b, a), dict(row))
    return out


def _r2_mates(relations: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for row in relations:
        if str(row.get("kind")) != RELATION_R2 or not bool(row.get("valid", False)):
            continue
        a, b = str(row.get("query", "")), str(row.get("candidate", ""))
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


def build_training_batch_for_package(package_dir: str | Path, *,
                                     max_fragments: int | None = None,
                                     token_budget: int | None = None) -> dict[str, Any]:
    """Build a real ``TrainingBatch`` from an exported package, with negatives and provenance.

    Features are read through the frozen ``qc.loader_probe.load_features`` (real ObsPack shards
    when the package carries them, an explicit *absent* payload otherwise -- never a zero-filled
    fake observation).  Labels go through the documented ``labels=`` form of
    ``training.batch.build_training_batch`` so that ``neighbours`` is the real R2 mate set; see
    the module docstring for why the ``pool=`` form cannot be used unchanged.
    """
    from ..qc.loader_probe import ExportedRelationPool, load_features
    from ..training.adapter import FeatureBundle
    from ..training.batch import build_training_batch, negative_audit

    package = TrainingPackage(package_dir)
    verify = package.verify_files()
    relations = list(package.relations())
    queries = list(package.queries())
    fragment_ids = [str(row.get("query_id", "")).split("::", 1)[-1] for row in queries]
    fragment_ids = [f for f in dict.fromkeys(fragment_ids) if f]
    if max_fragments:
        fragment_ids = fragment_ids[: int(max_fragments)]
    for candidate in sorted({str(r.get("candidate", "")) for r in relations if r.get("candidate")}):
        if candidate not in fragment_ids:
            fragment_ids.append(candidate)
    if not fragment_ids:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          "the package carries no fragment to build a batch from",
                          stage="relations.negatives.build_training_batch_for_package")
    payloads = load_features(package, fragment_ids, token_budget=token_budget)
    bundle = FeatureBundle.from_dict(payloads, token_budget=token_budget).check_shapes()
    pool = ExportedRelationPool(relations, pool_id="exported_relation_library")
    rows = batch_rows_from_relations(relations, fragment_ids)
    lookup = _relation_lookup(relations)
    mates = _r2_mates(relations)
    labels = {"R2": {q: sorted(mates.get(q, set())) for q in fragment_ids},
              "R1": {}, "R0": {}, "TINY_CONTACT": {}, "UNKNOWN": {}, "confirmed": {}}
    for row in relations:
        a, b = str(row.get("query", "")), str(row.get("candidate", ""))
        kind = str(row.get("kind", RELATION_UNKNOWN))
        if kind in (RELATION_R1, RELATION_R0, RELATION_TINY, RELATION_UNKNOWN):
            labels.setdefault(kind, {}).setdefault(a, []).append(b)
        labels["confirmed"][(a, b)] = bool(row.get("valid", False))
    r2_only_neighbours = {fid: sorted(mates.get(fid, set())) for fid in fragment_ids}
    batch = build_training_batch(bundle, labels=labels, rows=rows)
    audit = negative_audit(batch)
    exposure = batch.exposure()
    return {
        "schema": "synlab.relations.batch_from_package.v1", "version": NEGATIVES_VERSION,
        "package_dir": str(package_dir), "files_ok": bool(verify["ok"]),
        "files_checked": int(verify["files_checked"]),
        "relations": len(relations), "queries": len(queries),
        "relation_kinds": _kind_counts(relations),
        "batch": {"n_queries": int(batch.n_queries), "n_candidates": int(batch.n_candidates),
                  "positives": int(batch.pos_mask.sum()), "negatives": int(batch.neg_mask.sum()),
                  "excluded": int(batch.excluded_mask.sum()),
                  "effective_queries": int(batch.effective_query_count())},
        "negative_audit": audit, "exposure": _jsonable(exposure),
        "pool_mates_used_for_R2": r2_only_neighbours,
        "rows": rows, "labels_confirmed": sum(1 for v in labels["confirmed"].values() if v),
        "batch_object": batch, "pool_object": pool,
        "frozen_probe_pool_route": _probe_pool_route(bundle, pool, rows),
    }


def _probe_pool_route(bundle: Any, pool: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the frozen ``pool=`` route does with the very same real rows (reported, not hidden)."""
    from ..training.batch import build_training_batch

    try:
        batch = build_training_batch(bundle, pool=pool, rows=rows)
        return {"ok": True, "negatives": int(batch.neg_mask.sum())}
    except Exception as exc:  # noqa: BLE001 - the failure is the measurement
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "code": str(getattr(getattr(exc, "code", None), "value", "")),
                "note": ("qc.loader_probe.ExportedRelationPool.neighbours() returns the "
                         "confirmed R1/R0 set while build_training_batch reads it as the "
                         "historical R2 set; every real negative is therefore flagged "
                         "is_history_r2 and refused. qc/** is outside this task's write scope.")}


def _kind_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get("kind", RELATION_UNKNOWN))
        out[key] = out.get(key, 0) + 1
    return out


def build_batch_from_package(package_dir: str | Path, *, out_path: str | Path | None = None,
                             max_fragments: int | None = None,
                             token_budget: int | None = None) -> dict[str, Any]:
    """:func:`build_training_batch_for_package` without the live objects, written to disk."""
    result = build_training_batch_for_package(package_dir, max_fragments=max_fragments,
                                             token_budget=token_budget)
    result.pop("batch_object", None)
    result.pop("pool_object", None)
    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
        result["report_path"] = str(path)
    return result


# --------------------------------------------------------------------------------------
# 5. independent recheck of sampled negatives
# --------------------------------------------------------------------------------------
def audit_negative_sample(library: Mapping[str, Any], relations: Sequence[Mapping[str, Any]], *,
                          sample_size: int = 50, seed: int = 20261002,
                          kinds: Sequence[str] = (RELATION_R0, RELATION_R1)) -> dict[str, Any]:
    """Re-derive the verdict of sampled negatives from the **raw event ledger**.

    The check never reads the classification it is verifying.  For every sampled negative
    ``(q, c)`` it rebuilds the fact set from the measured library:

    * ``different mother``   -> must be ``R0``;
    * ``same event``         -> must **not** be a shared interface patch, and must not be the
      event's own ``R2``;
    * ``same mother, other event`` -> must be ``R1``/``UNKNOWN`` and no interface patch of any
      event may connect the two fragments (a shared real fracture surface would appear there).

    Any disagreement is a mismatch and is reported with its evidence.
    """
    fragments = library_fragments(library)
    patches: list[dict[str, Any]] = []
    r2_pairs: set[tuple[str, str]] = set()
    for mother in library.get("mothers") or []:
        for event in mother.get("events", []):
            if not event.get("ok"):
                continue
            for patch in event.get("interfaces", []):
                patches.append({"event_id": str(event["event_id"]),
                                "a": str(patch.get("fragment_a", "")),
                                "b": str(patch.get("fragment_b", "")),
                                "kind": str(patch.get("patch_kind", "")),
                                "area_mm2": float(patch.get("common_clip_area_mm2", 0.0) or 0.0)})
            for row in event.get("relations", []):
                a, b = str(row["a"]), str(row["b"])
                key = (a, b) if a <= b else (b, a)
                if str(row["kind"]) == RELATION_R2:
                    r2_pairs.add(key)
    rng = np.random.default_rng(int(seed))
    candidates = [row for row in relations if str(row.get("kind")) in set(kinds)]
    candidates.sort(key=lambda row: (str(row.get("a")), str(row.get("b"))))
    if not candidates:
        return {"ok": False, "sampled": 0, "mismatches": [],
                "reason": "no negative row exists to sample", "method": "raw_event_ledger"}
    take = min(int(sample_size), len(candidates))
    order = rng.permutation(len(candidates))[:take]
    checked: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for index in sorted(int(i) for i in order):
        row = candidates[index]
        a, b = str(row["a"]), str(row["b"])
        kind = str(row["kind"])
        info_a, info_b = fragments.get(a), fragments.get(b)
        if info_a is None or info_b is None:
            mismatches.append({"a": a, "b": b, "verdict": "fragment_not_in_library"})
            continue
        key = (a, b) if a <= b else (b, a)
        shared = [p for p in patches
                  if {p["a"], p["b"]} == {a, b}]
        foreign = [p for p in patches
                   if len({p["a"], p["b"]} & {a, b}) == 1
                   and (info_a["event_id"] in (p["event_id"],) or
                        info_b["event_id"] in (p["event_id"],))]
        same_mother = info_a["mother_id"] == info_b["mother_id"]
        same_event = info_a["event_id"] == info_b["event_id"]
        if not same_mother:
            expected = RELATION_R0
            basis = "different physical mother"
        elif same_event:
            expected = RELATION_R1 if key not in r2_pairs else RELATION_R2
            basis = "same event"
        else:
            expected = RELATION_R1
            basis = "same mother, mutually exclusive events"
        ok = (kind == expected) and not shared and key not in r2_pairs
        entry = {"a": a, "b": b, "labelled": kind, "re_derived": expected,
                 "same_mother": same_mother, "same_event": same_event,
                 "shared_patch": shared, "is_measured_R2": key in r2_pairs,
                 "basis": basis, "event_a": info_a["event_id"],
                 "event_b": info_b["event_id"], "lineage_a": info_a["lineage_id"],
                 "lineage_b": info_b["lineage_id"], "ok": ok}
        checked.append(entry)
        if not ok:
            mismatches.append(entry)
    return {
        "ok": not mismatches, "method": "raw_event_ledger",
        "description": ("each sampled negative is re-derived from the measured library "
                        "(mother identity, event identity, and the interface-patch list of "
                        "every event), never from the classification under test"),
        "sample_size": int(sample_size), "sampled": len(checked),
        "population": len(candidates), "seed": int(seed), "kinds": list(kinds),
        "mismatches": mismatches, "mismatch_rate": (len(mismatches) / len(checked)
                                                    if checked else None),
        "by_kind": {k: sum(1 for row in checked if row["labelled"] == k) for k in kinds},
        "checked": checked,
        "foreign_patch_note": ("a patch that names exactly one of the two fragments belongs to "
                               "another pair of the same event; it is listed for traceability"),
        "foreign_patch_examples": ([] if not checked else
                                   [p for p in patches
                                    if len({p["a"], p["b"]} & {checked[0]["a"],
                                                                checked[0]["b"]}) == 1][:2]),
    }


# --------------------------------------------------------------------------------------
# 6. minimal discrimination experiment on real legal features
# --------------------------------------------------------------------------------------
def _auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Rank AUC with ties counted half (Mann-Whitney U / (n_pos * n_neg))."""
    pos = scores[labels]
    neg = scores[~labels]
    if pos.size == 0 or neg.size == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(order.size, dtype=np.float64)
    ranks[order] = np.arange(1, order.size + 1, dtype=np.float64)
    # average ranks for ties
    values = np.concatenate([pos, neg])
    sorted_values = values[order]
    start = 0
    for index in range(1, sorted_values.size + 1):
        if index == sorted_values.size or sorted_values[index] != sorted_values[start]:
            if index - start > 1:
                ranks[order[start:index]] = ranks[order[start:index]].mean()
            start = index
    rank_pos = ranks[: pos.size].sum()
    return float((rank_pos - pos.size * (pos.size + 1) / 2.0) / (pos.size * neg.size))


def discrimination_auc(pool: Any, relations: Sequence[Mapping[str, Any]], *,
                       positive_kinds: Sequence[str] = (RELATION_R2,),
                       bootstrap: int = 2000, seed: int = 20261002) -> dict[str, Any]:
    """Minimal relation discrimination on **real legal observables** with a clustered interval.

    Every fragment is encoded with :func:`synlab.relations.sampler.legal_retrieval_vector` (the
    module's own legal, observable-only retrieval vector; a payload that cannot form one is
    reported unavailable, never zero-filled).  Each labelled pair is scored by cosine similarity
    and the AUC of "true adjacency vs everything else" is reported with a **mother-clustered**
    bootstrap interval (the unit is the independent mother, plan 19.4) plus the raw counts, so
    the reader can see how small the sample is.
    """
    from .sampler import legal_retrieval_vector

    features = getattr(pool, "features", {}) or {}
    vectors: dict[str, np.ndarray] = {}
    unavailable: list[str] = []
    for fid, payload in features.items():
        vector = legal_retrieval_vector(payload)
        if vector is None:
            unavailable.append(str(fid))
        else:
            vectors[str(fid)] = np.asarray(vector, dtype=np.float64)
    lookup = _relation_lookup(relations)
    mother_of = dict(getattr(pool, "mother_of", {}) or {})
    pairs: list[dict[str, Any]] = []
    for row in relations:
        a, b = str(row.get("query", "")), str(row.get("candidate", ""))
        if a == b or a not in vectors or b not in vectors:
            continue
        kind = str(row.get("kind", RELATION_UNKNOWN))
        if not bool(row.get("valid", False)):
            continue
        score = float(np.dot(vectors[a], vectors[b]))
        pairs.append({"a": a, "b": b, "kind": kind, "score": score,
                      "positive": kind in set(positive_kinds),
                      "mother_a": mother_of.get(a, ""), "mother_b": mother_of.get(b, "")})
    if not pairs:
        return {"ok": False, "status": "NOT_RUN", "reason": "no pair has two encodable fragments",
                "unavailable_fragments": sorted(unavailable), "features_available": len(vectors)}
    scores = np.asarray([p["score"] for p in pairs], dtype=np.float64)
    labels = np.asarray([p["positive"] for p in pairs], dtype=bool)
    auc = _auc(scores, labels)
    # mother-clustered bootstrap: resample mothers with replacement, keep all their pairs
    clusters: dict[str, list[int]] = {}
    for index, pair in enumerate(pairs):
        key = f"{pair['mother_a']}|{pair['mother_b']}"
        clusters.setdefault(key, []).append(index)
    keys = sorted(clusters)
    rng = np.random.default_rng(int(seed))
    draws: list[float] = []
    degenerate = 0
    if len(keys) >= 2:
        for _ in range(int(bootstrap)):
            picked = rng.choice(len(keys), size=len(keys), replace=True)
            index = np.concatenate([clusters[keys[int(i)]] for i in picked])
            value = _auc(scores[index], labels[index])
            if value is None:
                degenerate += 1
                continue
            draws.append(value)
    interval = None
    if draws:
        interval = {"low": float(np.percentile(draws, 2.5)),
                    "high": float(np.percentile(draws, 97.5)),
                    "replicates": len(draws), "degenerate_draws": degenerate,
                    "unit": "mother_pair_cluster", "confidence": 0.95}
    positives = [p for p in pairs if p["positive"]]
    negatives = [p for p in pairs if not p["positive"]]
    accuracy = None
    if positives and negatives:
        threshold = float(np.median(scores))
        accuracy = float(np.mean((scores >= threshold) == labels))
    return {
        "ok": auc is not None, "status": "MEASURED" if auc is not None else "NOT_ESTABLISHED",
        "scorer": "relations.sampler.legal_retrieval_vector (cosine)",
        "feature_dim": int(next(iter(vectors.values())).size),
        "fragments_with_features": len(vectors),
        "fragments_without_features": len(unavailable),
        "unavailable_fragments": sorted(unavailable),
        "pairs": len(pairs), "positives": len(positives), "negatives": len(negatives),
        "positive_kinds": list(positive_kinds),
        "negative_kinds": sorted({p["kind"] for p in negatives}),
        "clusters": len(keys), "clusters_note": "independent mother pairs (plan 19.4 unit)",
        "auc": auc, "accuracy_at_median_threshold": accuracy,
        "auc_interval": interval, "bootstrap_requested": int(bootstrap),
        "sample_note": (f"AUC over {len(pairs)} real labelled pairs from {len(vectors)} "
                        f"observed fragments in {len(keys)} mother-pair clusters; the interval "
                        f"is a mother-clustered percentile bootstrap and is wide by construction"),
        "per_pair": pairs,
    }


# --------------------------------------------------------------------------------------
# 7. summary
# --------------------------------------------------------------------------------------
def library_summary(library: Mapping[str, Any],
                    relations: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    rows = list(relations if relations is not None else classify_library(library))
    fragments = library_fragments(library)
    by_kind: dict[str, list[str]] = {}
    for row in rows:
        by_kind.setdefault(str(row["kind"]), []).append(f"{row['a']}|{row['b']}")
    mothers = [m["mother"] for m in library.get("mothers") or []]
    events = [e for m in library.get("mothers") or [] for e in m.get("events", [])]
    return {
        "ok": bool(library.get("ok")), "library_hash": library_hash(library),
        "version": MULTI_EVENT_VERSION,
        "mothers": len(mothers), "events": len(events),
        "events_ok": sum(1 for e in events if e.get("ok")),
        "fragments": len(fragments), "pairs": len(rows),
        "histogram": relation_histogram(rows),
        "counts_by_kind": {kind: len(items) for kind, items in sorted(by_kind.items())},
        "examples_by_kind": {kind: items[:4] for kind, items in sorted(by_kind.items())},
        "distractor_lineages": sorted({m["lineage_id"] for m in mothers
                                       if str(m["split"]) == "gallery_distractor"}),
        "training_lineages": sorted({m["lineage_id"] for m in mothers
                                     if str(m["split"]) != "gallery_distractor"}),
        "splits": sorted({str(m["split"]) for m in mothers}),
        "unresolved_fragments": sorted(f for f, info in fragments.items()
                                       if info.get("truth_status") != "COMPUTED"),
        "exclusion": library.get("exclusion"),
        "event_roles": sorted({str(e["plan"]["role"]) for e in events if e.get("ok")}),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "NEGATIVES_VERSION", "FEATURE_ARRAY_KEYS", "FEATURE_SCALAR_KEYS", "commit_library",
    "observe_library", "feature_arrays_in_legal_layout", "freeze_library_release",
    "batch_rows_from_relations",
    "build_training_batch_for_package", "build_batch_from_package", "audit_negative_sample",
    "discrimination_auc", "library_summary",
    "NEGATIVE_KINDS", "EXCLUDED_NEGATIVE_KINDS", "ROLE_POOL", "ROLE_ROSTER",
]
