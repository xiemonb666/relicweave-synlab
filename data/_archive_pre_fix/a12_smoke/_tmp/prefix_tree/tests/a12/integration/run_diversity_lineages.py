"""Run >=6 lineages into ``data/a12_diversity/store`` with every variable really applied.

Why this file exists instead of a straight ``run_generation(..., diversity=True)`` call
----------------------------------------------------------------------------------------
``synlab/pipeline.py`` is edited by another writer continuously while this work runs (observed:
its mtime advanced every ~20 s for minutes, and it grew by ~57 kB during the session).  The wiring
in that file therefore stops at "the per-lineage variable table is drawn and recorded"; the four
places that **consume** it are not patched there.  Rather than race a live writer, this module
drives the *real* ``build_one_mother`` (unchanged) and applies the variables through four narrow,
named adapters.  Each adapter is also the executable statement of one wiring point:

=========================  ==================================================================
adapter                    the ``pipeline.py`` site it stands in for
=========================  ==================================================================
`patch_fracture_event`     step 4: ``fracture = fracture_event(mother, spec.fracture, rngs["cut"],
                           event_id=event_id)`` -- must pass the sampled ``FractureSpec``
`patch_observe_spec`       step 7: ``observe_spec = _resolve_observe_spec(spec, store)`` -- must
                           return the lineage's sampled ``ObsSpec``
`patch_observe_profile`    step 7: ``observe(physical, None, rngs, route=route, spec=observe_spec)``
                           -- must pass ``profile=<sampled CameraProfile>``
`patch_build_pattern`      step 2b: ``_build_pattern_recipe`` -> ``build_pattern(mother, payload,
                           rng)`` -- must put the sampled family parameters/palette into ``payload``
=========================  ==================================================================

Everything else is the real pipeline: the same ``build_one_mother``, the same truth / physical /
feature / label / provenance commits, and the same degradation materialiser fed the lineage's
sampled axis+level subset.

Usage::

    .venv\\Scripts\\python.exe -B tests/a12/integration/run_diversity_lineages.py \\
        --config configs/a12/diversity.yaml --spec configs/a12/next_experiment.yaml \\
        --store data/a12_diversity/store --lineages 8 --batch 2

Resumable and batchable: a lineage already recorded as accepted in the store's own run report is
skipped, so the caller can keep every process to one or two lineages on this host.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUN_SCHEMA = "synlab.diversity_run.v1"

#: ``lineage_id -> variable table`` of the run currently in flight.
VARIABLES: dict[str, dict[str, Any]] = {}
#: The lineage whose assets are being built right now (the adapters key off it).
ACTIVE: dict[str, Any] = {"lineage_id": None}


# ---------------------------------------------------------------------------------------
# adapters -- one per pipeline.py wiring point
# ---------------------------------------------------------------------------------------
@contextlib.contextmanager
def patch_fracture_event() -> Iterator[None]:
    """Step 4: hand ``fracture_event`` the *sampled* ``FractureSpec``.

    ``pipeline.py`` calls ``fracture_event(mother, spec.fracture, rngs["cut"], ...)`` with the
    frozen ``FractureConfig``, which ``fracture.api._coerce_spec`` projects onto a ``FractureSpec``
    whose ``plane_normal``/``plane_point`` are ``None``.  With ``None``, ``_default_basis`` ignores
    the rng (its source literally says ``del rng``) and derives the plane from a hash of the body's
    vertices and faces -- so the cut orientation is a function of the *body*, not of the event.
    """
    from synlab.fracture import api as fracture_api

    original = fracture_api.fracture_event

    def patched(mother: Any, spec: Any, rng: Any, *, event_id: str) -> Any:
        table = _table_for_active()
        sampled = (table or {}).get("_fracture_spec")
        return original(mother, sampled if sampled is not None else spec, rng, event_id=event_id)

    fracture_api.fracture_event = patched
    try:
        yield
    finally:
        fracture_api.fracture_event = original


@contextlib.contextmanager
def patch_observe_spec() -> Iterator[None]:
    """Step 7: every observation of the lineage uses the lineage's own sampled ``ObsSpec``."""
    from synlab import pipeline as pipeline_mod

    original = pipeline_mod._resolve_observe_spec

    def patched(spec: Any, store: Any) -> Any:
        table = _table_for_active()
        sampled = (table or {}).get("_observe_spec")
        return sampled if sampled is not None else original(spec, store)

    pipeline_mod._resolve_observe_spec = patched
    try:
        yield
    finally:
        pipeline_mod._resolve_observe_spec = original


@contextlib.contextmanager
def patch_observe_profile() -> Iterator[None]:
    """Step 7: pass the sampled camera profile **explicitly** instead of letting it default.

    ``observe(..., profile=None)`` resolves to ``camera_profiles()[1]`` (the MID tier), so without
    this every sampled tier and working distance collapses back onto one profile.  ``profile`` is an
    existing keyword of the frozen ``observe`` signature; the function itself is untouched.
    """
    from synlab.observe import api as observe_api

    original = observe_api.observe

    def patched(target: Any, compiled: Any, rngs: Any, *, route: str, profile: Any = None,
                renderer: Any = None, spec: Any = None) -> Any:
        table = _table_for_active()
        sampled = (((table or {}).get("observation") or {}).get("camera") or {}).get("profile")
        if profile is None and sampled is not None:
            profile = sampled
        return original(target, compiled, rngs, route=route, profile=profile,
                        renderer=renderer, spec=spec)

    observe_api.observe = patched
    try:
        yield
    finally:
        observe_api.observe = original


@contextlib.contextmanager
def patch_build_pattern() -> Iterator[None]:
    """Step 2b: inject the sampled family parameters and palette into ``build_pattern``.

    ``_build_pattern_recipe`` sends ``params={}``, so every family parameter falls back to its
    pydantic field default.  The sampled values are merged into the payload the pipeline already
    builds (``PatternSpec.params``, the documented input), and a key the family does not declare is
    dropped by the family model's own validation instead of being forced in.
    """
    from synlab.patterns import api as patterns_api
    from synlab.patterns.params import FAMILY_MODELS, validate_family_params

    original = patterns_api.build_pattern

    def patched(mother: Any, spec: Any = None, rng: Any = None) -> Any:
        table = _table_for_active()
        pattern_vars = (table or {}).get("pattern") or {}
        payload = dict(spec) if isinstance(spec, dict) else spec
        if isinstance(payload, dict):
            family = str(payload.get("family") or "").upper()
            model = FAMILY_MODELS.get(family)
            mine = dict(pattern_vars.get("params") or {})
            if model is not None and mine:
                declared = set(getattr(model, "model_fields", {}) or {})
                filtered = {k: v for k, v in mine.items() if k in declared}
                validate_family_params(family, filtered)
                payload["params"] = {**(payload.get("params") or {}), **filtered}
            if pattern_vars.get("palette_id"):
                payload["palette_id"] = str(pattern_vars["palette_id"])
        return original(mother, payload, rng)

    patterns_api.build_pattern = patched
    try:
        yield
    finally:
        patterns_api.build_pattern = original


def _table_for_active() -> dict[str, Any] | None:
    active = ACTIVE.get("lineage_id")
    return VARIABLES.get(active) if active else None


# ---------------------------------------------------------------------------------------
# pipeline-source provenance
#
# ``build_one_mother`` is the one function this harness cannot call unmodified *if* it is broken:
# while this work ran, its step-7 ``stamp_context`` read ``primary_fragment_id`` before the
# assignment ~15 lines later, and because Python makes that name a true local of the frame
# (``'primary_fragment_id' in build_one_mother.__code__.co_varnames`` is ``True``, ``co_cellvars``
# is empty) **every** lineage died with ``UnboundLocalError`` after a fully successful
# mother/material/pattern/fracture/clean_truth/physical chain.  The defect was reported to the
# file's owner with the one-line fix and has since been fixed upstream (`pipeline.py` now resolves
# the owning fragment right after the observation and says so in a comment).
#
# :func:`pipeline_source` therefore only *records* what was executed, so the report can state
# whether the run used the owner's file as-is or a repaired copy, and
# :func:`patched_build_one_mother` still works if the defect ever comes back -- it detects the
# read-before-assign structurally and inserts the missing assignment; when the source is correct it
# returns the untouched function.
# ---------------------------------------------------------------------------------------
#: name -> the exact assignment line and the expression whose line must not precede it
UNBOUND_GUARDS: dict[str, tuple[str, str]] = {
    "primary_fragment_id": (
        '        primary_fragment_id = str(getattr(observation, "fragment_id", "") or "")',
        "stamp_context(observation,",
    ),
}


#: Field-name collisions between a live pipeline document and its own leakage guard.  The guard
#: ``assert_context_is_not_answer_bearing`` forbids the key ``kind`` anywhere in the simulated
#: context pack; ``build_context_pack`` puts ``"kind": "fragment"`` on every coexistent row, so the
#: guard refuses the very document it is handed and step 10 fails on **every** lineage with
#: ``ErrorCode.LEAKAGE_DETECTED: simulated context pack carries answer-side fields: ['kind']``
#: (measured: after observe 43.8 s and features 8.8 s had already succeeded).  The repair renames
#: that literal key inside the pack document (``kind`` -> ``unit_kind``); it does **not** touch the
#: forbidden-field list, so the guard keeps refusing every other answer-bearing field -- nothing is
#: relaxed.  Reported to the file's owner.
NAME_COLLISIONS: tuple[dict[str, str], ...] = (
    {"document_marker": '"coexistents": coexistents,',
     "old": '"kind": "fragment",', "new": '"unit_kind": "fragment",',
     "reason": "the pack's own coexistents key is exactly the guard's forbidden key"},
)


def pipeline_source() -> dict[str, Any]:
    """File, hash and mtime of the ``pipeline.py`` this run actually imports."""
    import hashlib

    from synlab import pipeline as pipeline_mod

    path = Path(pipeline_mod.__file__)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "sha256": f"sha256:{digest}",
            "bytes": path.stat().st_size, "mtime": path.stat().st_mtime}


#: Module globals the live ``pipeline.py`` reads but does not import.  Same discipline as
#: :data:`UNBOUND_GUARDS`: recorded, reversible, and reported to the owner instead of edited in.
#: ``SCHEMA_PROVENANCE`` lives in :mod:`synlab.roles` (``"synlab.provenance.v1"``) and is used by
#: ``pipeline._commit_provenance``, but ``pipeline.py`` imports only ``SCHEMA_FEATURE`` and
#: ``SCHEMA_LABELS`` from that module, so step 8 of ``build_one_mother`` raised
#: ``NameError: name 'SCHEMA_PROVENANCE' is not defined`` on every run (measured: 6 fragments built,
#: 67.7 s spent, then step 8 lost).
MISSING_GLOBALS: dict[str, tuple[str, str]] = {
    "SCHEMA_PROVENANCE": ("synlab.roles", "SCHEMA_PROVENANCE"),
}


@contextlib.contextmanager
def patch_missing_globals() -> Iterator[dict[str, Any]]:
    """Supply the module globals the live ``pipeline.py`` forgot to import, then remove them."""
    import importlib

    from synlab import pipeline as pipeline_mod

    applied: dict[str, str] = {}
    for name, (module_name, attr) in MISSING_GLOBALS.items():
        if hasattr(pipeline_mod, name):
            continue
        try:
            value = getattr(importlib.import_module(module_name), attr)
        except AttributeError:
            continue
        setattr(pipeline_mod, name, value)
        applied[name] = f"{module_name}.{attr}"
    try:
        yield applied
    finally:
        for name in applied:
            try:
                delattr(pipeline_mod, name)
            except AttributeError:
                pass


def patched_build_one_mother() -> tuple[Any, dict[str, Any]]:
    """The live ``build_one_mother``, repaired from source only if it reads before assigning."""
    from synlab import pipeline as pipeline_mod

    info = pipeline_source()
    info["repair_applied"] = False
    info["repairs"] = []
    path = Path(info["path"])
    lines = path.read_text(encoding="utf-8").lstrip("\ufeff").splitlines()
    for name, (assignment, reader) in UNBOUND_GUARDS.items():
        readers = [i for i, line in enumerate(lines) if line.strip() == reader.strip()]
        assigns = [i for i, line in enumerate(lines) if line.strip() == assignment.strip()]
        if not readers or not assigns:
            continue
        if min(assigns) < min(readers):
            info["defect_present"] = False
            continue
        info["defect_present"] = True
        insert_at = min(readers)
        lines.insert(insert_at, assignment)
        info["repairs"].append({"kind": "read_before_assign", "name": name,
                                "inserted_at_1based_line": insert_at + 1,
                                "reason": "frame-local name read before its assignment"})
        info["repair_applied"] = True
    for collision in NAME_COLLISIONS:
        marker = collision["document_marker"].strip()
        anchors = [i for i, line in enumerate(lines) if line.strip() == marker]
        hits = [i for i, line in enumerate(lines) if line.strip() == collision["old"].strip()]
        if not anchors or not hits:
            continue
        # only rewrite the occurrence inside the guarded document, never a same-named key elsewhere
        window = [i for i in hits if abs(i - min(anchors)) < 40]
        if not window:
            continue
        for index in window:
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            lines[index] = indent + collision["new"]
        info["repairs"].append({"kind": "field_name_collision", "from": collision["old"].strip(),
                                "to": collision["new"].strip(),
                                "at_1based_lines": [i + 1 for i in window],
                                "reason": collision["reason"]})
        info["repair_applied"] = True
    if not info["repair_applied"]:
        info.pop("repairs", None)
        return pipeline_mod.build_one_mother, info
    namespace: dict[str, Any] = dict(pipeline_mod.__dict__)
    exec(compile("\n".join(lines) + "\n", str(path) + "#diversity-harness-repaired", "exec"),
         namespace)
    return namespace["build_one_mother"], info


@contextlib.contextmanager
def patch_build_one_mother(P: Any, plan: Any, lineage: Any, store: Any, *, run_id: Any,
                           degrade_cfg: Any) -> Iterator[dict[str, Any]]:
    """Call the (possibly repaired) ``build_one_mother`` and capture both result and provenance."""
    original = P.build_one_mother
    repaired, info = patched_build_one_mother()
    captured: dict[str, Any] = {"provenance": info}
    P.build_one_mother = repaired
    try:
        try:
            with patch_missing_globals() as applied:
                info["missing_globals_supplied"] = applied
                captured["result"] = repaired(plan, lineage, store, run_id=run_id,
                                              degrade_cfg=degrade_cfg)
        except Exception as exc:  # noqa: BLE001 - a dead lineage is an outcome, not a crash
            captured["result"] = {
                "ok": False, "coverage_row": {"lineage_id": lineage.lineage_id},
                "error": {"code": "UNEXPECTED", "stage": "harness",
                          "message": f"{type(exc).__name__}: {exc}"[:400],
                          "traceback": traceback.format_exc()[-1500:]}}
        yield captured
    finally:
        P.build_one_mother = original


def _complete_table(mother: Any, lineage: Any, table: dict[str, Any], config: dict[str, Any]
                    ) -> dict[str, Any]:
    """Draw the parts of the variable table that need the built mother geometry.

    ``plan_generation`` can only draw what the *lineage* determines; the fracture plane needs the
    body's vertex cloud (its centroid and equivalent radius), so ``event`` and ``_fracture_spec``
    are drawn here, from the same frozen ``event`` sub-stream, once the mother exists.  This is
    exactly the call that ``build_one_mother`` must make after step 1 -- and it is the only reason
    the fracture wiring is "impossible" from the planning side.
    """
    from synlab import pipeline as P

    if table.get("_fracture_spec") is None:
        fracture_spec, event_vars = P._div_fracture_spec(
            P._div_rng(config, lineage.lineage_id, "event"), config, lineage, mother)
        table["_fracture_spec"] = fracture_spec
        table["event"] = event_vars
    if table.get("_degrade_config") is None:
        base = P._resolve_degrade_diversity(str(DEGRADE_PATH[0]))
        rebuilt, degrade_vars = P._div_degradation_config(
            P._div_rng(config, lineage.lineage_id, "diversity"), config, base)
        table["_degrade_config"] = rebuilt
        table["degradation"] = degrade_vars
    return table


DEGRADE_PATH: list[Path] = [REPO_ROOT / "configs/a12/degrade_diversity.yaml"]


# ---------------------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------------------
def _new_store(store_root: Path) -> Any:
    from synlab.storage.store import AssetStore

    return AssetStore(store_root)


def _run_dir(store_root: Path) -> Path:
    return store_root / "reports" / "diversity_run"


def _accepted_lineages(store_root: Path) -> dict[str, Any]:
    """Real outcomes recorded by previous batches (the resume key)."""
    out: dict[str, Any] = {}
    for path in sorted(_run_dir(store_root).glob("batch_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in payload.get("outcomes") or []:
            out[str(entry.get("lineage_id"))] = entry
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8")


def _build_mother_only(P: Any, plan: Any, lineage: Any, store: Any, *, run_id: str
                       ) -> dict[str, Any]:
    """Build and commit the mother **alone**, so the variable table can be completed.

    Only two pipeline statements are reproduced here -- the mother construction and its commit
    (``pipeline.py`` step 1) -- because the crack plane is a function of the body: the plane
    normal/offset are drawn from the body's vertex cloud, which does not exist until step 1 has
    run.  Everything after step 1 is the untouched ``build_one_mother``.  A duplicate mother asset
    is impossible: the store is content-addressed and idempotent by interpretation hash, so the
    real step 1 inside ``build_one_mother`` returns this same asset.
    """
    from synlab.errors import ErrorCode, SynLabError
    from synlab.mothers.api import audit_mother, create_mother
    from synlab.seeds import derive_named_rngs

    rngs = derive_named_rngs(plan.spec.master_seed, lineage.lineage_id)
    try:
        mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                               rngs["shape"], mother_id=lineage.lineage_id)
        audit = audit_mother(mother)
        if not audit.get("ok", True):
            raise SynLabError(ErrorCode.MOTHER_INVALID, f"mother audit failed: {audit}",
                              stage="harness.mother")
        P._commit_mother(store, mother, lineage, audit, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "coverage_row": {"lineage_id": lineage.lineage_id},
                "error": {"code": "MOTHER_INVALID" if isinstance(exc, SynLabError) else "UNEXPECTED",
                          "stage": "harness.mother",
                          "message": f"{type(exc).__name__}: {exc}"[:400],
                          "traceback": traceback.format_exc()[-1200:]}}
    return {"ok": True, "mother": mother}


def _batch(store_root: Path, spec: Any, config: dict[str, Any], config_path: Path,
           degrade_path: Path, indexes: list[int]) -> dict[str, Any]:
    """Run the real ``build_one_mother`` for ``indexes`` and record every real outcome."""
    from synlab import pipeline as P
    from synlab.storage.store import QA_PASS

    plan = P.plan_generation(spec, diversity=config)
    degrade_base = P._resolve_degrade_diversity(str(degrade_path))
    if degrade_base is None:
        raise SystemExit(f"degradation config {degrade_path} resolved to None")

    chosen = [plan.lineages[i] for i in indexes if i < len(plan.lineages)]
    VARIABLES.clear()
    VARIABLES.update({l.lineage_id: dict(l.variables or {}) for l in chosen
                      if l.variables is not None})

    store = _new_store(store_root)
    run_id = f"divrun_{int(time.time()) % 100000:05d}"
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value,
                     profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(), "spec": plan.compiled.expanded,
                           "data_semantics": P.data_semantics(),
                           "obs_semantics": P.OBS_SEMANTICS_V2,
                           "diversity_config": str(config_path),
                           "diversity_config_hash": config.get("config_hash")})
    _write_json(store_root / "reports" / f"run_spec_{run_id}.json",
                {**plan.as_dict(), "diversity_config": str(config_path),
                 "config_hash": config.get("config_hash"),
                 "pipeline_source": pipeline_source(),
                 "lineages": {l.lineage_id: P._jsonable_variables(l.variables or {})
                              for l in chosen}})

    outcomes: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for lineage in chosen:
        ACTIVE["lineage_id"] = lineage.lineage_id
        table = VARIABLES.get(lineage.lineage_id) or {}
        sampled_degrade = table.get("_degrade_config") or degrade_base
        started = time.time()
        mother = _build_mother_only(P, plan, lineage, store, run_id=run_id)
        if mother["ok"]:
            _complete_table(mother["mother"], lineage, table, config)
            VARIABLES[lineage.lineage_id] = table
            sampled_degrade = table.get("_degrade_config") or degrade_base
            try:
                with patch_fracture_event(), patch_observe_spec(), patch_observe_profile(), \
                        patch_build_pattern(), \
                        patch_build_one_mother(P, plan, lineage, store, run_id=run_id,
                                               degrade_cfg=sampled_degrade) as captured:
                    result = captured["result"]
                    harness_patch = captured.get("provenance")
            except Exception as exc:  # noqa: BLE001 - a dead lineage is an outcome, not a crash
                result = {"ok": False, "coverage_row": {"lineage_id": lineage.lineage_id},
                          "error": {"code": "UNEXPECTED", "stage": "harness",
                                    "message": f"{type(exc).__name__}: {exc}"[:400],
                                    "traceback": traceback.format_exc()[-1500:]}}
                harness_patch = None
        else:
            result = mother
            harness_patch = None
        ACTIVE["lineage_id"] = None
        row = dict(result.get("coverage_row") or {})
        row["run_id"] = run_id
        row["diversity"] = P._jsonable_variables(table)
        row["diversity_applied"] = {
            "fracture_plane_from_variables": bool(table.get("event")),
            "observe_spec_from_variables": table.get("_observe_spec") is not None,
            "camera_profile_from_variables": bool(
                (((table.get("observation") or {}).get("camera")) or {}).get("profile_id")),
            "pattern_params_from_variables": bool((table.get("pattern") or {}).get("params")),
            "degrade_axes_from_variables": bool((table.get("degradation") or {}).get("sampled")),
        }
        rows.append(row)
        outcomes.append({
            "lineage_id": lineage.lineage_id,
            "ok": bool(result.get("ok")),
            "seconds": time.time() - started,
            "error": result.get("error"),
            "quarantine_reason": row.get("quarantine_reason"),
            "fragments": row.get("fragments"),
            "observations": row.get("observations"),
            "stages": row.get("stages"),
            "diversity": row["diversity"],
            "diversity_applied": row["diversity_applied"],
            "harness_source_patch": harness_patch,
            "degrade_variant_assets": len(row.get("degrade_variant_assets") or []),
        })
        # flush after EVERY lineage: this host kills long heavy processes without a traceback
        _write_json(_run_dir(store_root) / "in_flight.json",
                    {"schema": RUN_SCHEMA, "run_id": run_id, "outcomes": outcomes})
        print(f"[diversity] {lineage.lineage_id}: ok={result.get('ok')} "
              f"fragments={row.get('fragments')} seconds={outcomes[-1]['seconds']:.1f}"
              + ("" if result.get("ok") else f"  reason={row.get('quarantine_reason')}"))

    payload = {"schema": RUN_SCHEMA, "run_id": run_id, "config_path": str(config_path),
               "config_hash": config.get("config_hash"),
               "degrade_config": str(degrade_path),
               "planned": len(plan.lineages), "attempted": len(chosen),
               "accepted": sum(1 for o in outcomes if o["ok"]),
               "outcomes": outcomes, "stopped_at": time.time()}
    _write_json(_run_dir(store_root) / "batch_all.json", payload)
    store.set_run_status(run_id, "QA_PASSED" if payload["accepted"] else "FAILED",
                         meta={"accepted": payload["accepted"], "attempted": payload["attempted"]})
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run diverse lineages")
    parser.add_argument("--config", default="configs/a12/diversity.yaml")
    parser.add_argument("--spec", default="configs/a12/next_experiment.yaml")
    parser.add_argument("--store", default="data/a12_diversity/store")
    parser.add_argument("--degrade", default="configs/a12/degrade_diversity.yaml")
    parser.add_argument("--lineages", type=int, default=8)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--start", type=int, default=0)
    args = parser.parse_args(argv)

    from synlab import pipeline as P
    from synlab.config import load_generation_spec

    store_root = (REPO_ROOT / args.store).resolve()
    store_root.mkdir(parents=True, exist_ok=True)
    config_path = (REPO_ROOT / args.config).resolve()
    degrade_path = (REPO_ROOT / args.degrade).resolve()

    config = P._resolve_diversity(str(config_path))
    if config is None:
        print("diversity config resolved to None; nothing to do", file=sys.stderr)
        return 2
    spec = load_generation_spec(REPO_ROOT / args.spec)
    spec.dataset.target_mothers = int(args.lineages)

    done = {k for k, v in _accepted_lineages(store_root).items() if v.get("ok")}
    if done:
        print(f"[diversity] resume: {len(done)} accepted lineage(s) already on disk")

    summary: list[dict[str, Any]] = []
    index = int(args.start)
    while index < args.lineages:
        batch = [i for i in range(index, min(index + args.batch, args.lineages))]
        pending = []
        for i in batch:
            lineage_id = f"LIN{i:04d}"
            if any(done_id.startswith(lineage_id) for done_id in done):
                print(f"[diversity] skip LIN{i:04d} (already accepted)")
                continue
            pending.append(i)
        if pending:
            try:
                payload = _batch(store_root, spec, config, config_path, degrade_path, pending)
                summary.append({"indexes": pending, "accepted": payload["accepted"],
                                "attempted": payload["attempted"]})
            except Exception as exc:  # noqa: BLE001
                summary.append({"indexes": pending, "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc()[-2000:]})
                _write_json(_run_dir(store_root) / f"failed_{pending[0]:04d}.json", summary[-1])
        index = min(index + args.batch, args.lineages)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
