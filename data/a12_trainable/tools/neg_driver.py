"""Relation-negative track of the A12 *trainable* dataset.

Why a second track is required
------------------------------
``synlab.pipeline.plan_generation`` gives every lineage exactly **one** event
(``event_ids=[f"{lineage_id}_E01"]``) and ``build_one_mother`` runs exactly one ``fracture_event``.
Every pair inside such a lineage is therefore *same-event*, and ``pipeline._commit_labels`` records
those pairs with ``valid=false, loss_mask=false`` and the reason
``"no_direct_fracture_surface (same event, mutually exclusive)"``.  The gallery keeps ``R0``
implicit and never materialises it, so an ordinary run cannot put a legal negative into an exported
relation table by construction.  Measured on the pre-existing package
``data/a12_exports/next_experiment/training_package``: 150 relation rows = {R1: 117, R2: 33}, and
all 117 R1 rows are ``valid=false / loss_mask=false``.

This driver therefore runs the second, real route that ``synlab.relations`` already provides:
``multi_event.plan_event_library`` plans >= 3 mutually exclusive events per mother;
``multi_event._run_one_mother`` runs each of them for real; ``negatives.commit_library`` writes a
``label_bundle`` per fragment carrying that fragment's own measured rows (including the legal
``R0``/``R1`` ones) and a ``clean_truth`` per event; ``negatives.observe_library`` renders each
fragment for real and commits ``obs_result`` + ``feature_bundle`` so **both** ends of every pair can
be encoded.

Kill safety
-----------
One fracture event per process, cached at ``work/event_<m>_<e>.json``.  A host kill costs one event,
never a mother: ``assemble`` rebuilds a mother's record from whatever is cached.  Nothing is ever
carried in memory between modes.

Mother indices are taken from the **tail** of the frozen plan so that the identifiers cannot collide
with the lineages the ordinary single-event track produces (a shared fragment id would mean two
different geometries claiming the same name).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA = "synlab.a12.trainable.neg_driver.v1"

#: Minimum number of fracture events that must have really run for a mother's record to be usable.
#:
#: ``plan_event_library`` plans >= 3 events, but a mother is still a valid relation lineage when
#: only **two** of them produced a measured event: two events are already enough for the cross-event
#: pairs that carry the legal ``R0``/``R1`` negatives (plan 11.1: "R1 requires a second event of the
#: same mother"), and the measured count travels in ``events_ok``, so a 2-event record can never be
#: read as a 3-event one.  Requiring 3 discarded mothers whose third event failed the fracture
#: audit for a reason that has nothing to do with the relation evidence.
MIN_EVENTS_USABLE = 2


def _paths(base: Path) -> dict[str, Path]:
    return {"base": base, "work": base / "work", "meshes": base / "meshes",
            "plan": base / "library_plan.json", "library": base / "library.json",
            "reports": base / "reports"}


def _import_hooks() -> dict:
    from synlab.fracture.api import audit_fracture, fracture_event
    from synlab.fracture.spec import BACKEND_PLANE, FractureSpec
    from synlab.mothers.api import create_mother
    from synlab.truth.api import finalize_clean_truth
    return {"create_mother": create_mother, "fracture_event": fracture_event,
            "audit_fracture": audit_fracture, "finalize_clean_truth": finalize_clean_truth,
            "fracture_spec_cls": FractureSpec, "plane_backend": BACKEND_PLANE}


def build_plan(config: str, indices: list[int]):
    """Event-library plan over the given mother indices of the frozen generation plan."""
    from synlab.config import load_generation_spec
    from synlab.pipeline import plan_generation
    from synlab.registry import load_all
    from synlab.relations.multi_event import plan_event_library

    load_all()
    lineage_plan = plan_generation(load_generation_spec(config))
    wanted = set(indices)
    mothers = []
    for lineage in lineage_plan.lineages:
        if int(lineage.mother_index) not in wanted:
            continue
        mothers.append({"lineage_id": lineage.lineage_id, "split": lineage.split,
                        "vessel_id": lineage.vessel_id, "material_id": lineage.material_id,
                        "pattern_id": lineage.pattern_id,
                        "layer_combo_id": lineage.layer_combo_id, "params": dict(lineage.params),
                        "mother_index": int(lineage.mother_index)})
    missing = sorted(wanted - {m["mother_index"] for m in mothers})
    if missing:
        raise SystemExit(f"mother indices not in the plan: {missing}")
    return plan_event_library(mothers, n_events=3, master_seed=int(lineage_plan.spec.master_seed))


def mode_plan(args) -> int:
    p = _paths(Path(args.base))
    indices = [int(x) for x in args.indices.split(",") if x.strip()]
    plan = build_plan(args.config, indices)
    p["base"].mkdir(parents=True, exist_ok=True)
    p["plan"].write_text(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(json.dumps({"mothers": len(plan.mothers), "events": len(plan.events),
                      "indices": indices, "path": str(p["plan"])}, ensure_ascii=False))
    return 0


def mode_step(args) -> int:
    from synlab.relations.multi_event import LibraryPlan, _run_one_mother
    from synlab.schemas.spec import FractureConfig

    p = _paths(Path(args.base))
    p["work"].mkdir(parents=True, exist_ok=True)
    p["meshes"].mkdir(parents=True, exist_ok=True)
    plan = build_plan(args.config, [int(x) for x in args.indices.split(",") if x.strip()])
    mother_index, event_index = int(args.mother), int(args.event)
    mother_plan = next(m for m in plan.mothers if m.mother_index == mother_index)
    event_plan = plan.events_of(mother_index)[event_index]
    sub = LibraryPlan(master_seed=plan.master_seed, mothers=[mother_plan], events=[event_plan])
    record = _run_one_mother(mother_plan, sub, fracture_config=FractureConfig(),
                             mesh_dir=p["meshes"], micro_events=True, **_import_hooks())
    event = record["events"][0]
    payload = {"mother_index": mother_index, "event_index": event_index,
               "mother": record["mother"], "event": event, "seconds": record["seconds"],
               "ran_at": time.time()}
    (p["work"] / f"event_{mother_index}_{event_index}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = {"mother_index": mother_index, "event_index": event_index,
               "event_id": event.get("event_id"), "ok": bool(event.get("ok")),
               "role": (event.get("plan") or {}).get("role"),
               "truth_status": event.get("truth_status"),
               "histogram": event.get("relation_histogram"),
               "fragments": [f.get("fragment_id") for f in event.get("fragments", [])],
               "seconds": round(float(record["seconds"]), 3),
               "last_error": str(event.get("last_error"))[:300] if event.get("last_error") else None}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary["ok"] else 1


def assemble(args) -> dict:
    from synlab.relations.multi_event import verify_event_exclusion

    p = _paths(Path(args.base))
    plan_payload = json.loads(p["plan"].read_text(encoding="utf-8"))
    mothers = []
    for mother_plan in plan_payload["mothers"]:
        index = int(mother_plan["mother_index"])
        events, mother_row, seconds = [], None, 0.0
        mother_events = [e for e in plan_payload["events"]
                         if int(e["mother_index"]) == index]
        for event_index, _event_plan in enumerate(mother_events):
            path = p["work"] / f"event_{index}_{event_index}.json"
            if not path.exists():
                continue
            cached = json.loads(path.read_text(encoding="utf-8"))
            mother_row = mother_row or cached["mother"]
            events.append(cached["event"])
            seconds += float(cached.get("seconds") or 0.0)
        if not events:
            continue
        usable = [e for e in events if e.get("ok")]
        mothers.append({"mother": mother_row, "events": events,
                        "ok": (len(usable) >= MIN_EVENTS_USABLE
                               and len({e["event_id"] for e in usable}) == len(usable)),
                        "events_ok": len(usable), "events_planned": len(events),
                        "events_usable_threshold": MIN_EVENTS_USABLE, "seconds": seconds})
    library = {"schema": "synlab.relations.event_library.v1",
               "version": plan_payload["version"], "master_seed": plan_payload["master_seed"],
               "plan": plan_payload, "mothers": mothers}
    library["exclusion"] = verify_event_exclusion(library)
    library["ok"] = bool(mothers) and all(m["ok"] for m in mothers) and library["exclusion"]["ok"]
    library["events_ok"] = sum(m["events_ok"] for m in mothers)
    p["library"].write_text(json.dumps(library, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
    summary = {"mothers_cached": len(mothers), "mothers_ok": sum(1 for m in mothers if m["ok"]),
               "events_ok": library["events_ok"],
               "exclusion_ok": bool(library["exclusion"].get("ok")),
               "exclusion_problems": len(library["exclusion"].get("problems") or []),
               "library_ok": library["ok"], "path": str(p["library"])}
    (p["reports"]).mkdir(parents=True, exist_ok=True)
    (p["reports"] / "assemble.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return library


def mode_assemble(args) -> int:
    library = assemble(args)
    return 0 if library["mothers"] else 1


def demote_unverified_event_pairs(library: Mapping[str, Any],
                                  rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Refuse to call a pair a *legal negative* when the event exclusion could not be verified.

    ``multi_event.verify_event_exclusion`` reports, per pair of events of the same mother, either a
    proof that they are distinct or a ``plane_unmeasured`` / ``distinct_plane`` /
    ``no_shared_patch`` / ``distinct_mesh`` problem.  A cross-event pair whose events are not
    proven distinct has no measured basis for ``R0``/``R1``: the two events might have cut one and
    the same surface, in which case the pair is not a negative at all.

    Such rows are **demoted in place** (``valid=False``, ``loss_mask=False``, with the check name
    written into ``reason``) instead of being dropped, so the demotion itself is auditable and the
    row count is unchanged.  Nothing is ever promoted.
    """
    exclusion = library.get("exclusion") or {}
    bad_pairs = {frozenset((str(p.get("events", ["", ""])[0]), str(p.get("events", ["", ""])[1]))):
                 str(p.get("check")) for p in (exclusion.get("problems") or [])}
    demoted: list[dict] = []
    for row in rows:
        key = frozenset((str(row.get("event_a", "")), str(row.get("event_b", ""))))
        check = bad_pairs.get(key)
        if check is None:
            continue
        row["valid"] = False
        row["loss_mask"] = False
        row["reason"] = f"event_exclusion_unverified:{check}"
        row["decidability"] = "UNVERIFIED"
        demoted.append({"a": row.get("a"), "b": row.get("b"), "kind": row.get("kind"),
                        "check": check})
    return rows, demoted


def mode_commit(args) -> int:
    from synlab.relations.multi_event import classify_library
    from synlab.relations.negatives import commit_library
    from synlab.storage.store import AssetStore

    p = _paths(Path(args.base))
    library = json.loads(p["library"].read_text(encoding="utf-8"))
    store = AssetStore(Path(args.store))
    store.create_run(args.run_id, "relneg", scope="SYNTHETIC", profile=None,
                     meta={"negatives": "synlab.relations.negatives.commit_library",
                           "library_hash": library.get("library_hash")})
    rows = classify_library(library)
    demoted: list[dict] = []
    if args.demote_unverified:
        rows, demoted = demote_unverified_event_pairs(library, rows)
    committed = commit_library(store, library, run_id=args.run_id, mesh_dir=p["meshes"],
                               rows=rows)
    committed.pop("label_bundles", None)
    committed.pop("clean_truth", None)
    committed.pop("fragment_mesh", None)
    committed["rows_demoted_event_exclusion_unverified"] = demoted
    committed["rows_demoted_count"] = len(demoted)
    committed["library_exclusion_ok"] = bool((library.get("exclusion") or {}).get("ok"))
    (p["reports"]).mkdir(parents=True, exist_ok=True)
    (p["reports"] / "commit.json").write_text(
        json.dumps(committed, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in committed.items()
                      if k != "rows_demoted_event_exclusion_unverified"},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if committed.get("relations") else 1


def _install_obsspec_route_shim() -> str:
    """Make ``negatives.observe_library`` callable without editing ``synlab/**``.

    Measured defect (2026-10-02, ``synlab/relations/negatives.py`` L356-358)::

        obs_spec = ObsSpec(master_seed=..., lineage_id=..., route=route,
                           view_count=int(view_count), renderer=renderer)

    but ``synlab.observe.routes.ObsSpec`` has no ``route`` field (measured signature: ``view_count,
    delivered_size, max_render_pixels, tiers, render_spec, imaging, light, route_params, workdir,
    freeze_label_files, master_seed, lineage_id, frame_id, renderer, distortion_policy,
    blender_config``).  Every call therefore died with
    ``TypeError: ObsSpec.__init__() got an unexpected keyword argument 'route'`` and produced zero
    observations, after the geometry correspondence check had already passed.

    ``observe_library`` imports ``ObsSpec`` *inside* the function body, so a subclass installed on
    the module attribute before the call is what it constructs.  The shim accepts ``route`` and
    **drops it**: the route is not an ``ObsSpec`` field, it is passed separately to
    ``observe(fragment, None, rngs, route=route, spec=obs_spec)`` by the very same function, so no
    information is lost and no other argument is touched.  ``synlab/**`` is outside this task's
    write scope; the owning work stream should make the same one-line change in place.
    """
    from synlab.observe import routes as routes_mod

    current = routes_mod.ObsSpec
    if getattr(current, "_trainable_route_shim", False):
        return "already_installed"

    class _ObsSpecRouteCompat(current):  # type: ignore[misc, valid-type]
        _trainable_route_shim = True

        def __init__(self, *positional, route=None, **kwargs):  # noqa: ANN002, ANN003
            super().__init__(*positional, **kwargs)

    _ObsSpecRouteCompat.__name__ = "ObsSpec"
    _ObsSpecRouteCompat.__qualname__ = "ObsSpec"
    routes_mod.ObsSpec = _ObsSpecRouteCompat
    return "installed"


def mode_observe(args) -> int:
    from synlab.relations.negatives import observe_library
    from synlab.schemas.spec import FractureConfig
    from synlab.storage.store import AssetStore

    _install_obsspec_route_shim()
    p = _paths(Path(args.base))
    library = json.loads(p["library"].read_text(encoding="utf-8"))
    plan = build_plan(args.config, [int(x) for x in args.indices.split(",") if x.strip()])
    store = AssetStore(Path(args.store))
    wanted_mothers = {int(x) for x in args.mothers.split(",") if x.strip()}
    # Only request events the library actually recorded as ok with a computed truth.  An event
    # whose fracture audit failed has no measured labels, and re-running it would silently fall
    # back to ``fracture_api_default_basis`` (a *different* body), committing observations for a
    # geometry no label was ever measured on.  Measured on LIN0101: E03 had failed in the library
    # and the un-filtered call observed it under ``fracture_api_default_basis``.
    recorded_ok = {str(e["event_id"]) for m in library.get("mothers", [])
                   for e in m.get("events", [])
                   if e.get("ok") and str(e.get("truth_status")) == "COMPUTED"}
    events = [str(e["event_id"]) for e in library["plan"]["events"]
              if int(e["mother_index"]) in wanted_mothers
              and (e.get("role") or "") != "unresolved"
              and str(e["event_id"]) in recorded_ok]
    started = time.time()
    report = observe_library(plan, store, fracture_config=FractureConfig(), events=events,
                             run_id=args.run_id, library=library,
                             route=args.route, view_count=int(args.views),
                             renderer=args.renderer)
    report["wall_seconds"] = round(time.time() - started, 3)
    report["requested_events"] = events
    report["requested_mothers"] = sorted(wanted_mothers)
    report["tag"] = args.tag
    (p["reports"]).mkdir(parents=True, exist_ok=True)
    out = p["reports"] / f"observe_{args.tag}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"tag": args.tag, "ok": report.get("ok"),
                      "observed_fragments": len(report.get("observed_fragments") or []),
                      "failed_fragments": report.get("failed_fragments"),
                      "wall_seconds": report["wall_seconds"], "path": str(out)},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("ok") else 1


def mode_summary(args) -> int:
    p = _paths(Path(args.base))
    if not p["library"].exists():
        print("no library yet")
        return 1
    library = json.loads(p["library"].read_text(encoding="utf-8"))
    from synlab.relations.multi_event import classify_library, relation_histogram

    rows = classify_library(library)
    hist = relation_histogram(rows)
    # ``classify_library`` rows are the public ``{a, b, kind, valid, loss_mask, lineage_a, ...}``
    # form (they are what ``commit_library`` writes into ``relations_json``), so the lineage comes
    # from ``lineage_a`` -- not from a ``fragment_id`` key, which these rows do not carry.
    per_mother = []
    for mother in library["mothers"]:
        lineage = mother["mother"]["lineage_id"]
        own = [r for r in rows if str(r.get("lineage_a", "")) == lineage]
        per_mother.append({
            "lineage_id": lineage, "ok": mother["ok"], "events_ok": mother["events_ok"],
            "relations": len(own), "histogram": relation_histogram(own),
            "eligible_negatives": sum(1 for r in own if str(r.get("kind")) in ("R1", "R0")
                                      and r.get("valid") and r.get("loss_mask")),
            "valid_R2": sum(1 for r in own if str(r.get("kind")) == "R2" and r.get("valid"))})
    summary = {"mothers": len(library["mothers"]),
               "mothers_ok": sum(1 for m in library["mothers"] if m["ok"]),
               "relations": len(rows), "histogram": hist, "per_mother": per_mother,
               "eligible_negatives_total": sum(1 for r in rows
                                               if str(r.get("kind")) in ("R1", "R0")
                                               and r.get("valid") and r.get("loss_mask")),
               "valid_R2_total": sum(1 for r in rows if str(r.get("kind")) == "R2"
                                     and r.get("valid")),
               "exclusion_ok": bool((library.get("exclusion") or {}).get("ok"))}
    (p["reports"]).mkdir(parents=True, exist_ok=True)
    (p["reports"] / "library_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="neg_driver")
    parser.add_argument("mode", choices=["plan", "step", "assemble", "commit", "observe",
                                         "summary"])
    parser.add_argument("--config", default="configs/a12/next_experiment.yaml")
    parser.add_argument("--base", default="data/a12_trainable/negatives")
    parser.add_argument("--store", default="data/a12_trainable/store")
    parser.add_argument("--indices", default="")
    parser.add_argument("--mothers", default="")
    parser.add_argument("--mother", type=int, default=-1)
    parser.add_argument("--event", type=int, default=-1)
    parser.add_argument("--run-id", default="run_trainable_relneg")
    parser.add_argument("--tag", default="batch")
    parser.add_argument("--route", default="proxy_scan")
    parser.add_argument("--renderer", default="auto")
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--config-sha256", default=None)
    parser.add_argument("--demote-unverified", action="store_true",
                        help="commit mode: demote every cross-event pair whose events the "
                             "exclusion verifier could not prove distinct to "
                             "valid=false/loss_mask=false instead of counting it as a legal "
                             "negative")
    args = parser.parse_args(argv)
    if args.config_sha256:
        import hashlib
        digest = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
        if digest != args.config_sha256:
            raise SystemExit(f"config hash mismatch: {digest} != {args.config_sha256}")
    modes = {"plan": mode_plan, "step": mode_step, "assemble": mode_assemble,
             "commit": mode_commit, "observe": mode_observe, "summary": mode_summary}
    return modes[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
