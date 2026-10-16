"""Step-wise evidence runner: one process per audit, every report written immediately.

The host kills heavy Python processes without a traceback, so this script is designed to be
driven **one step at a time**, each in its own interpreter::

    python tools/evidence_min.py --step registry
    python tools/evidence_min.py --step pattern-batch --batch-size 4 --batch-index 0
    python tools/evidence_min.py --step pattern-merge
    python tools/evidence_min.py --step axes-batch    --batch-size 5 --batch-index 0
    python tools/evidence_min.py --step axes-merge
    python tools/evidence_min.py --step observe
    python tools/evidence_min.py --step pixel-contract
    python tools/evidence_min.py --step scale
    python tools/evidence_min.py --step resource-profile --run-id probe_recovery
    python tools/evidence_min.py --step loader-probe
    python tools/evidence_min.py --step leakage --run-id probe_recovery
    python tools/evidence_min.py --step api-ui
    python tools/evidence_min.py --step health
    python tools/evidence_min.py --step all          # in-process fallback, same steps

Every step writes its report to ``<data-root>/reports/<name>.json`` before it returns, so a
killed later step never destroys earlier evidence.  A capability that is absent is written as
``NOT_RUN`` with the concrete reason; nothing is replaced by a placeholder value.

Exit codes: ``0`` the step wrote its report (whatever the measured ``ok`` is), ``3`` the step
could not be completed (report written with ``status=NOT_RUN``) or the arguments were wrong.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Report files consumed by ``synlab.qc.acceptance`` and the delta document.
REPORTS = (
    "registry_summary", "pattern_audit", "operator_audit", "channel_audit", "spurious_audit",
    "camera_profile_audit", "pixel_contract", "scale_report", "resource_profile",
    "loader_probe", "leakage_negative_control", "api_ui_evidence", "store_health",
)

PARTS_DIRNAME = "_parts"


# ---------------------------------------------------------------------------- plumbing
def write_report(store_root: Path, name: str, payload: dict[str, Any]) -> Path:
    path = store_root / "reports" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    return path


def part_path(store_root: Path, name: str, index: int) -> Path:
    path = store_root / "reports" / PARTS_DIRNAME / f"{name}.part{index:02d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_parts(store_root: Path, name: str) -> list[tuple[Path, dict[str, Any]]]:
    files = sorted((store_root / "reports" / PARTS_DIRNAME).glob(f"{name}.part*.json"))
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        out.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def chunks(items: Sequence[Any], size: int) -> list[list[Any]]:
    size = max(1, int(size))
    return [list(items[i:i + size]) for i in range(0, len(items), size)]


def store_for(store_root: Path) -> Any:
    from synlab.storage.store import AssetStore

    return AssetStore(store_root)


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return jsonable(value.item())
        if isinstance(value, np.ndarray):
            return jsonable(value.tolist())
    except Exception:  # noqa: BLE001 - numpy is optional for pure-json steps
        pass
    return value


def run_step(name: str, fn: Callable[[], dict[str, Any]], store_root: Path,
             *, report_name: str | None = None) -> dict[str, Any]:
    """Run one step, persist its report, print a one-line honest summary."""
    started = time.perf_counter()
    try:
        payload = jsonable(fn() or {})
        payload.setdefault("ok", False)
    except Exception as exc:  # noqa: BLE001 - evidence collection must never crash silently
        payload = {"ok": False, "status": "NOT_RUN",
                   "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-1500:]}
    payload["step"] = name
    payload["seconds"] = round(time.perf_counter() - started, 2)
    payload["command"] = " ".join([Path(sys.executable).name, "tools/evidence_min.py", "--step", name])
    if payload.get("status") is None:
        payload["status"] = "PASS" if payload.get("ok") else "FAIL"
    written = None
    if report_name:
        written = str(write_report(store_root, report_name, payload))
    payload["report_path"] = written
    print(f"[{name}] ok={payload.get('ok')} status={payload.get('status')} "
          f"sec={payload['seconds']} report={written} "
          f"{str(payload.get('error', ''))[:160]}", flush=True)
    return payload


# ---------------------------------------------------------------------------- steps
def step_registry(store_root: Path) -> dict[str, Any]:
    from synlab.registry import REGISTRY, load_all

    reports = load_all()
    summary = REGISTRY.summary()
    return {"ok": bool(summary), "modules": reports,
            "counts": {k: v["count"] for k, v in summary.items()},
            "by_status": {k: v["by_status"] for k, v in summary.items()}}


def step_pattern_batch(store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    from synlab.patterns.audit_all import FAMILY_MODELS, audit_all_patterns

    store = store_for(store_root)
    families = sorted(FAMILY_MODELS)
    batch = chunks(families, args.batch_size)[args.batch_index]
    report = audit_all_patterns(store, families=batch, n_pairs=int(args.pattern_pairs),
                               commit=False)
    path = part_path(store_root, "pattern_audit", args.batch_index)
    path.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2, sort_keys=True,
                               default=str), encoding="utf-8")
    return {"ok": bool(report.get("families")), "status": report.get("status"),
            "families": batch, "batch_index": args.batch_index,
            "families_ok": report.get("families_ok"), "max_seam_error": report.get("max_seam_error"),
            "mother_source": report.get("mother_source"), "part": str(path),
            "batch_ok": report.get("ok"), "batch_failures": report.get("failures"),
            "seconds_in_audit": report.get("seconds")}


def step_pattern_merge(store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Merge the per-batch family reports with the module's own aggregation rules."""
    from synlab.patterns.audit_all import (
        FAMILY_MODELS,
        SEAM_TOL,
        _APPEARANCE_GEOMETRY_MODES,  # noqa: PLC2701 - the aggregation must match the module
    )

    parts = load_parts(store_root, "pattern_audit")
    if not parts:
        raise RuntimeError("no pattern_audit parts found; run --step pattern-batch first")
    reports: dict[str, Any] = {}
    tiers: dict[str, Any] = {}
    mother_sources: set[str] = set()
    mother_ids: set[str] = set()
    mother_faces: set[int] = set()
    duplicates: list[str] = []
    for path, payload in parts:
        for family, entry in (payload.get("families") or {}).items():
            if family in reports:
                duplicates.append(family)
            reports[family] = entry
        tiers.update(payload.get("tier_probe") or {})
        if payload.get("mother_source"):
            mother_sources.add(str(payload["mother_source"]))
        if payload.get("mother_id"):
            mother_ids.add(str(payload["mother_id"]))
        if payload.get("mother_faces") is not None:
            mother_faces.add(int(payload["mother_faces"]))
    if duplicates:
        raise RuntimeError(f"family reported by more than one batch: {sorted(set(duplicates))}")

    family_ids = sorted(reports)
    missing = sorted(set(FAMILY_MODELS) - set(reports))

    seam_values = [e["seam"]["chart_space_max_abs_color_error"] for e in reports.values()
                   if isinstance(e.get("seam"), dict)
                   and e["seam"].get("chart_space_max_abs_color_error") is not None]
    max_seam_error = float(max(seam_values)) if seam_values else float("nan")
    world_values = [e["seam"].get("world_space_pass") for e in reports.values()
                    if isinstance(e.get("seam"), dict)]
    deterministic = bool(reports) and all(bool(e.get("deterministic")) for e in reports.values())
    inheritance_ok = bool(reports) and all(bool(e.get("inheritance_pass")) for e in reports.values())

    geometric: dict[str, bool] = {}
    appearance_untouched: dict[str, bool] = {}
    for family, entry in reports.items():
        geometry = dict(entry.get("geometry") or {})
        mode = str(geometry.get("mode", (entry.get("height_policy") or {}).get("mode", "none")))
        if mode in _APPEARANCE_GEOMETRY_MODES:
            appearance_untouched[family] = bool(geometry.get("hash_unchanged"))
        else:
            geometric[family] = bool(geometry.get("pass"))
    geometry_applied = bool(geometric) and all(geometric.values())
    appearance_ok = all(appearance_untouched.values())
    tiers_ok = all(v.get("all_distinct") for v in tiers.values()) if tiers else None
    hashes = [e.get("recipe_hash") for e in reports.values() if e.get("recipe_hash")]
    hashes_unique = len(set(hashes)) == len(hashes)

    failures: list[str] = []
    for family, entry in reports.items():
        if not entry.get("ok"):
            failures.append(f"{family}: {entry.get('status')} "
                            f"{'; '.join(entry.get('failures') or []) or entry.get('error', '')}")
    if missing:
        failures.append(f"families never audited: {missing}")
    if len(family_ids) != len(FAMILY_MODELS):
        failures.append(f"only {len(family_ids)} of {len(FAMILY_MODELS)} families were audited")
    if not (max_seam_error <= SEAM_TOL):
        failures.append(f"max seam colour error {max_seam_error:.3e} above {SEAM_TOL:g}")
    if not deterministic:
        failures.append("determinism check failed")
    if not inheritance_ok:
        failures.append("source inheritance check failed")
    if not geometry_applied:
        failures.append("a geometric family did not change the mother geometry")
    if not appearance_ok:
        failures.append("an appearance-only family changed the mother geometry")
    if not hashes_unique:
        failures.append("recipe hashes are not unique across families (fixed tile?)")
    if tiers and not tiers_ok:
        failures.append("complexity tiers did not change the frozen coefficients")

    ok = not failures
    return {
        "ok": bool(ok), "status": "QA_PASSED" if ok else "QA_FAILED",
        "check": "A05 pattern families (plan 9.3 / 9.6)",
        "families": reports, "family_ids": family_ids, "n_families": len(family_ids),
        "families_ok": sum(1 for e in reports.values() if e.get("ok")),
        "max_seam_error": max_seam_error, "seam_tolerance": SEAM_TOL,
        "max_seam_error_world_space_ok": all(bool(v) for v in world_values) if world_values else None,
        "deterministic": deterministic, "inheritance_ok": inheritance_ok,
        "geometry_applied": geometry_applied, "geometry_families": geometric,
        "appearance_geometry_untouched": appearance_untouched,
        "complexity_tiers_all_distinct": tiers_ok, "tier_probe": tiers,
        "recipe_hashes_unique": hashes_unique,
        "mother_source": ("; ".join(sorted(mother_sources)) or None),
        "mother_id": (sorted(mother_ids)[0] if len(mother_ids) == 1 else sorted(mother_ids)),
        "mother_faces": (sorted(mother_faces)[0] if len(mother_faces) == 1
                         else sorted(mother_faces) or None),
        "committed": False, "n_pairs": int(args.pattern_pairs), "seed": 20260101,
        "batched": True,
        "batch_size": int(args.batch_size), "n_batches": len(parts),
        "batch_files": [str(p) for p, _ in parts],
        "aggregation": ("merged from per-batch audit_all_patterns(families=...) runs; per-family "
                        "entries are the module's unmodified output and the aggregate rules are "
                        "the module's own (seam tolerance, determinism, inheritance, geometry, "
                        "unique recipe hashes, complexity tiers)"),
        "notes": [f"mother_source={src}" for src in sorted(mother_sources)],
        "failures": failures,
        "evidence": {"report": "data/a12/reports/pattern_audit.json", "acceptance": "A05",
                     "recipe_role": "pattern_recipe"},
    }


def step_axes_batch(store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    from synlab.degrade.api import audit_all_axes
    from synlab.degrade.registry import AXIS_REGISTRY

    store = store_for(store_root)
    axes = list(AXIS_REGISTRY.ids())
    batch = chunks(axes, args.batch_size)[args.batch_index]
    path = part_path(store_root, "operator_audit", args.batch_index)
    try:
        report = audit_all_axes(store, axes=batch, levels=[0, 1, 2, 3, 4])
        jsonable_report = jsonable(report)
    except Exception as exc:  # noqa: BLE001 - a crashed axis is recorded, never a hole
        code = getattr(exc, "code", None)
        code_text = getattr(code, "value", None) or (str(code) if code is not None else "")
        # The module maps an inapplicable input to NA (``NA_NOT_APPLICABLE``); when that code
        # escapes ``audit_all_axes`` before the per-level handler sees it, keep the module's
        # own semantics instead of inventing a verdict.
        status = "NA" if code_text in ("NA_NOT_APPLICABLE", "DEPENDENCY_CAPABILITY_MISSING") \
            else "NOT_RUN"
        entry = {"status": status, "independent_mothers": 0, "levels": {},
                 "error": f"audit_all_axes raised {type(exc).__name__}: {exc}",
                 "error_code": code_text,
                 "measured_by": "exception during audit_all_axes",
                 "traceback": traceback.format_exc()[-1200:]}
        if status == "NA":
            entry["na_reason"] = str(exc)
        jsonable_report = {
            "ok": False, "identity_ok": False, "levels": [0, 1, 2, 3, 4],
            "measurements": [], "source_provenance": [], "crash":
                f"{type(exc).__name__}: {exc}", "crash_code": code_text,
            "traceback": traceback.format_exc()[-1200:],
            "axes": {axis: dict(entry) for axis in batch},
        }
    report = jsonable_report
    # ``audit_all_axes`` always returns **all** registered ids, filling the axes it was not
    # asked for with MISSING; record which ids this process really measured so the merge can
    # tell "not requested here" from "declared but not implemented".
    report["_batch_axes"] = list(batch)
    report["_batch_index"] = int(args.batch_index)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    axes_status = {a: (v or {}).get("status") for a, v in (report.get("axes") or {}).items()
                   if a in batch}
    return {"ok": bool(axes_status) and None not in axes_status.values(),
            "status": "MEASURED" if not report.get("crash") else (
                next(iter(set(axes_status.values())), None) or "NOT_RUN"),
            "axes": batch, "batch_index": args.batch_index,
            "axes_status": axes_status,
            "axes_pass": sorted(a for a, s in axes_status.items() if s == "PASS"),
            "axes_fail": sorted(a for a, s in axes_status.items() if s == "FAIL"),
            "axes_na": sorted(a for a, s in axes_status.items() if s == "NA"),
            "axes_missing": sorted(a for a, s in axes_status.items() if s == "MISSING"),
            "axes_not_run": sorted(a for a, s in axes_status.items() if s == "NOT_RUN"),
            "crash": report.get("crash"), "crash_code": report.get("crash_code"),
            "batch_ok": report.get("ok"), "identity_ok": report.get("identity_ok"),
            "denominators": report.get("denominators"), "part": str(path)}


def step_axes_merge(store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Merge the per-batch axis reports with the module's own aggregation rules."""
    from synlab.degrade.registry import AXIS_REGISTRY

    parts = load_parts(store_root, "operator_audit")
    if not parts:
        raise RuntimeError("no operator_audit parts found; run --step axes-batch first")
    reports: dict[str, Any] = {}
    measurements: list[dict[str, Any]] = []
    duplicates: list[str] = []
    provenance: set[str] = set()
    axis_registry: list[dict[str, Any]] = []
    contract: dict[str, Any] = {}
    limits: dict[str, Any] = {}
    levels: list[int] = []
    for path, payload in parts:
        batch_axes = payload.get("_batch_axes")
        if batch_axes is None:  # legacy part: keep every axis the module actually measured
            batch_axes = [a for a, v in (payload.get("axes") or {}).items()
                          if (v or {}).get("levels") or (v or {}).get("status") != "MISSING"]
        for axis_id in batch_axes:
            entry = (payload.get("axes") or {}).get(axis_id)
            if entry is None:
                continue
            if axis_id in reports:
                duplicates.append(axis_id)
            reports[axis_id] = entry
        measurements.extend(payload.get("measurements") or [])
        provenance.update(payload.get("source_provenance") or [])
        axis_registry = payload.get("axis_registry") or axis_registry
        contract = payload.get("contract") or contract
        limits = payload.get("limits") or limits
        levels = payload.get("levels") or levels
    if duplicates:
        raise RuntimeError(f"axis reported by more than one batch: {sorted(set(duplicates))}")

    missing = list(AXIS_REGISTRY.missing())
    never_measured = sorted(set(AXIS_REGISTRY.ids()) - set(reports))
    for axis_id in never_measured:
        reports[axis_id] = {"status": "MISSING", "independent_mothers": 0, "levels": {},
                            "error": "axis was not measured by any batch of this run"}
    for axis_id in missing:
        reports.setdefault(axis_id, {"status": "MISSING", "independent_mothers": 0, "levels": {},
                                     "error": "axis declared in the schema but not implemented"})

    evaluated = [r for r in reports.values() if r.get("status") != "MISSING"]
    with_identity = [r for r in evaluated if "0" in (r.get("levels") or {})]
    identity_ok = bool(with_identity) and all(
        bool(r["levels"]["0"].get("identity")) and bool(r["levels"]["0"].get("bytes_unchanged", True))
        for r in with_identity)
    positive = [r for r in evaluated
                if r.get("status") == "PASS" and r.get("independent_mothers", 0) > 0]
    failing = sorted(a for a, r in reports.items() if r.get("status") == "FAIL")
    ok = bool(not missing and identity_ok and len(positive) >= 1)
    all_axes_pass = bool(not missing and not failing and identity_ok
                         and len(positive) == len(evaluated) and evaluated)
    denominators = {
        "axes_registered": len(AXIS_REGISTRY.ids()),
        "axes_audited": len(evaluated),
        "axes_pass": len([r for r in evaluated if r.get("status") == "PASS"]),
        "axes_na": len([r for r in evaluated if r.get("status") == "NA"]),
        "axes_fail": len([r for r in evaluated if r.get("status") == "FAIL"]),
        "axes_missing": len([r for r in reports.values() if r.get("status") == "MISSING"]),
        "levels_planned": int(sum(len(r.get("levels", {})) for r in reports.values())),
        "levels_passed": int(sum(1 for r in reports.values() for e in r.get("levels", {}).values()
                                 if e.get("status") == "PASS")),
        "levels_na": int(sum(1 for r in reports.values() for e in r.get("levels", {}).values()
                             if e.get("status") == "NA")),
        "levels_failed": int(sum(1 for r in reports.values() for e in r.get("levels", {}).values()
                                 if e.get("status") == "FAIL")),
    }
    crashed = sorted(
        ({"axis": axis, "status": r.get("status"), "error": r.get("error"),
          "error_code": r.get("error_code")}
         for axis, r in reports.items()
         if r.get("measured_by") == "exception during audit_all_axes"),
        key=lambda e: e["axis"])
    parquet: dict[str, Any] | None = None
    try:
        from synlab.degrade.api import write_operator_measurements

        parquet = write_operator_measurements(measurements, store=store_for(store_root))
    except Exception as exc:  # noqa: BLE001 - the parquet copy is evidence, not the report
        parquet = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": ok, "identity_ok": identity_ok, "all_axes_pass": all_axes_pass,
        "status": "PASS" if ok else "FAIL",
        "failing_axes": failing, "levels": levels, "axes": reports,
        "denominators": denominators, "measurements": measurements,
        "axis_registry": axis_registry, "source_provenance": sorted(provenance),
        "contract": contract, "limits": limits,
        "axes_raised_in_module": crashed,
        "batched": True, "batch_size": int(args.batch_size), "n_batches": len(parts),
        "batch_files": [str(p) for p, _ in parts],
        "measurements_parquet": parquet,
        "aggregation": ("merged from per-batch audit_all_axes(axes=..., levels=[0,1,2,3,4]) runs; "
                        "every axis keeps all five levels from one process so the paired basis is "
                        "preserved; aggregate rules are the module's own"),
    }


def step_observe(store_root: Path) -> dict[str, Any]:
    from synlab.observe.audit import audit_camera_profiles, audit_channels, audit_spurious

    store = store_for(store_root)
    channels = jsonable(audit_channels(store))
    written = {"channel_audit": str(write_report(store_root, "channel_audit", channels))}
    spurious = jsonable(audit_spurious(store))
    written["spurious_audit"] = str(write_report(store_root, "spurious_audit", spurious))
    cameras = jsonable(audit_camera_profiles(store))
    written["camera_profile_audit"] = str(write_report(store_root, "camera_profile_audit", cameras))
    metrics = (channels.get("metrics") or {})
    return {"ok": bool(channels.get("ok") and spurious.get("ok") and cameras.get("ok")),
            "status": "PASS" if (channels.get("ok") and spurious.get("ok")
                                 and cameras.get("ok")) else "FAIL",
            "reports": written,
            "depth_median_abs_error_mm": metrics.get("depth_median_abs_error_mm"),
            "integer_label_dtype": metrics.get("integer_label_dtype"),
            "fractional_labels": metrics.get("fractional_labels"),
            "spurious_ok": spurious.get("ok"),
            "spurious_variants": {k: v.get("status") for k, v in
                                  ((spurious.get("metrics") or {}).get("variants") or {}).items()},
            "camera_engineering_ok": cameras.get("engineering_ok"),
            "camera_calibration_ok": cameras.get("calibration_ok")}


def step_pixel_contract(store_root: Path) -> dict[str, Any]:
    store = store_for(store_root)
    try:
        from synlab.cameras.audit import audit_pixel_contract
    except Exception as exc:  # noqa: BLE001 - the module is allowed to be absent
        return {"ok": False, "status": "NOT_RUN",
                "error": f"{type(exc).__name__}: {exc}",
                "note": ("synlab.cameras.audit (pixel/display contract suite) does not exist in "
                         "this checkout, so A25 has no measurement source; nothing was inferred "
                         "from configuration"),
                "required_module": "synlab.cameras.audit",
                "required_call": "audit_pixel_contract(store)",
                "acceptance": "A25"}
    report = jsonable(audit_pixel_contract(store))
    report.setdefault("status", "PASS" if report.get("ok") else "FAIL")
    return report


def _asset_inventory(store: Any) -> dict[str, int]:
    roles: dict[str, int] = {}
    for asset in store.list_assets(limit=1000000):
        roles[asset.role] = roles.get(asset.role, 0) + 1
    return dict(sorted(roles.items()))


def step_scale(store_root: Path) -> dict[str, Any]:
    store = store_for(store_root)
    fragments = store.list_assets(role="fragment_mesh", limit=1000000)
    mothers = store.list_assets(role="mother_mesh", limit=1000000)
    lineages = {a.lineage_id for a in mothers if a.lineage_id}
    splits: dict[str, int] = {}
    for asset in fragments:
        key = asset.split or "unknown"
        splits[key] = splits.get(key, 0) + 1
    inventory = _asset_inventory(store)
    return {
        "ok": bool(fragments),
        "status": "PASS" if fragments else "PENDING",
        "accepted_fragments": len(fragments),
        "accepted_max": len(fragments),
        "independent_mothers": len(lineages),
        "per_split_fragments": splits,
        "assets_by_role": inventory,
        "total_assets": sum(inventory.values()),
        "note": ("accepted counts are read from committed fragment assets; the L2/L3 targets "
                 "(480 mothers / 1e5 fragments) stay PENDING until those runs exist"),
    }


def step_resource_profile(store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    from synlab.errors import SynLabError
    from synlab.qc.profile import profile_run

    store = store_for(store_root)
    run_id = args.run_id
    if not run_id:
        return {"ok": False, "status": "NOT_RUN",
                "error": "no --run-id given and no run with committed jobs was selected",
                "acceptance": "A21"}
    try:
        report = jsonable(profile_run(store, run_id))
    except SynLabError as exc:
        return {"ok": False, "status": "NOT_RUN", "run_id": run_id,
                "error": f"{exc.code}: {exc.message}",
                "note": "the run carries no jobs to profile; nothing was estimated by hand"}
    report["status"] = "PASS" if report.get("ok") else "FAIL"
    report["assets_by_role"] = _asset_inventory(store)
    return report


def step_loader_probe(store_root: Path) -> dict[str, Any]:
    """Really try to build a training batch from committed assets and record the outcome."""
    store = store_for(store_root)
    inventory = _asset_inventory(store)
    attempts: list[dict[str, Any]] = []
    loaded: dict[str, Any] = {}

    def attempt(name: str, fn: Callable[[], dict[str, Any]]) -> None:
        started = time.perf_counter()
        try:
            detail = fn()
            attempts.append({"name": name, "ok": True, "detail": jsonable(detail)})
        except Exception as exc:  # noqa: BLE001 - a refused load is the evidence
            attempts.append({"name": name, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}",
                             "error_code": str(getattr(exc, "code", "")),
                             "traceback": traceback.format_exc()[-600:]})
        attempts[-1]["seconds"] = round(time.perf_counter() - started, 3)

    def load_pool() -> dict[str, Any]:
        from synlab.relations.api import load_pool

        assets = store.list_assets(role="relation_pool", limit=10)
        if not assets:
            raise FileNotFoundError("store has no relation_pool asset")
        pool = load_pool(store, assets[0].asset_id)
        return {"pool_id": pool.pool_id, "lineup": len(pool.lineup)}

    def load_stored_arrays() -> dict[str, Any]:
        assets = store.list_assets(role="feature_bundle", limit=10)
        if not assets:
            raise FileNotFoundError("store has no feature_bundle asset")
        asset = assets[0]
        arrays = store.load_arrays(asset.asset_id)
        loaded["asset_id"] = asset.asset_id
        loaded["schema"] = asset.schema
        loaded["arrays"] = arrays
        return {"asset_id": asset.asset_id, "schema": asset.schema, "role": asset.role,
                "split": asset.split,
                "array_keys": sorted(arrays),
                "shapes": {k: list(getattr(v, "shape", ())) for k, v in sorted(arrays.items())}}

    def build_batch() -> dict[str, Any]:
        from synlab.training.adapter import FeatureBundle
        from synlab.training.batch import build_training_batch, negative_audit

        if not loaded.get("arrays"):
            raise RuntimeError("no stored arrays were loaded; attempt 'load_stored_arrays' failed")
        payload = {str(loaded["asset_id"]): dict(loaded["arrays"])}
        bundle = FeatureBundle.from_dict(payload).check_shapes()
        batch = build_training_batch(bundle, labels=None, block_r2_contamination=True)
        return {"queries": int(batch.n_queries), "candidates": int(batch.n_candidates),
                "audit": jsonable(negative_audit(batch))}

    def iterable_sampler() -> dict[str, Any]:
        from synlab.training.sampler import ShardedIterableDataset, bucket_of

        if not loaded.get("arrays"):
            raise RuntimeError("no stored arrays were loaded; attempt 'load_stored_arrays' failed")
        pool_assets = store.list_assets(role="relation_pool", limit=1)
        if not pool_assets:
            raise FileNotFoundError(
                "ShardedIterableDataset needs a frozen relation_pool (cursor replay unit)")
        dataset = ShardedIterableDataset(pool_assets[0].asset_id)  # type: ignore[call-arg]
        return {"bucket_of_1": bucket_of(1), "dataset": type(dataset).__name__}

    attempt("relations.load_pool", load_pool)
    attempt("store.load_arrays(feature_bundle)", load_stored_arrays)
    attempt("training.adapter.FeatureBundle.from_dict", build_batch)
    attempt("training.sampler.ShardedIterableDataset", iterable_sampler)

    ok = all(a["ok"] for a in attempts)
    blocking = [a for a in attempts if not a["ok"]]
    return {
        "ok": bool(ok), "status": "PASS" if ok else "NOT_RUN",
        "attempts": attempts,
        "store_array_load_ok": attempts[1]["ok"],
        "assets_by_role": inventory,
        "blocking_attempt": blocking[0]["name"] if blocking else None,
        "note": ("a training batch needs a committed feature_bundle in the adapted payload form "
                 "(and, for supervised rows, a frozen relation_pool). This store carries "
                 "observation assets committed under the feature role and no relation_pool, so "
                 "the loaders refuse instead of synthesising a batch; the refusals are the "
                 "measured result."),
        "acceptance": "loader_probe (not an A-item on its own; feeds A15/A16/A35 prerequisites)",
    }


def step_leakage(store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    from synlab.qc.leakage import run_negative_control

    store = store_for(store_root)
    report = jsonable(run_negative_control(store, args.run_id))
    report.setdefault("status", "PASS" if report.get("ok") else "FAIL")
    report["run_id"] = args.run_id
    return report


def step_api_ui(store_root: Path) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from synlab.api import create_app

    app = create_app(store_root, role="researcher")
    client = TestClient(app)
    calls: dict[str, Any] = {}
    try:
        for label, path in (("capabilities", "/api/synlab/capabilities"),
                            ("registry_vessel", "/api/synlab/registry/vessel"),
                            ("assets", "/api/synlab/assets")):
            response = client.get(path, params={"limit": 5} if label == "assets" else None)
            body: Any
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                body = None
            calls[label] = {
                "path": path, "status_code": response.status_code,
                "ok": response.status_code < 500,
                "items": (len(body.get("items", []))
                          if isinstance(body, dict) and isinstance(body.get("items"), list)
                          else None),
                "keys": sorted(body)[:12] if isinstance(body, dict) else None,
            }
    finally:
        client.close()
    frontend_dist = ROOT / "frontend" / "dist"
    frontend_index = frontend_dist / "index.html"
    frontend_doc = ROOT / "docs" / "a12" / "api_ui.md"
    api_ok = all(v["ok"] for v in calls.values())
    metrics = {
        "capabilities_status": calls["capabilities"]["status_code"],
        "registry_status": calls["registry_vessel"]["status_code"],
        "assets_status": calls["assets"]["status_code"],
        "assets_page_items": calls["assets"]["items"],
        "frontend_build_present": frontend_dist.exists(),
        "frontend_index_present": frontend_index.exists(),
        "frontend_doc_present": frontend_doc.exists(),
        "routes": {k: v["path"] for k, v in calls.items()},
    }
    return {"ok": bool(api_ok and frontend_index.exists()), "status":
            "PASS" if (api_ok and frontend_index.exists()) else ("FAIL" if not api_ok else "PENDING"),
            "metrics": metrics, "calls": calls,
            "note": ("status codes and page sizes are real HTTP responses from create_app(role="
                     "'researcher'); the frontend build artefact must exist for a PASS")}


def step_fixtures(store_root: Path) -> dict[str, Any]:
    """Diagnostics metric/statistic fixtures (hand-computed values, no dataset needed)."""
    from synlab.diagnostics.fixtures import run_fixtures

    report = jsonable(run_fixtures())
    metrics = jsonable(report.get("metrics") or {"ok": False})
    stats = jsonable(report.get("stats") or {"ok": False})
    # ``metric_fixture.json`` keeps the module's whole report so the harness can read both
    # ``report["ok"]`` (A18) and ``report["metrics"][<hand-computed flag>]`` (A30).
    full = dict(report)
    full["note"] = ("full run_fixtures() report: 'metrics' carries the A30 hand-computed "
                    "flags, 'stats' the statistics fixtures (also written to stat_fixture.json)")
    written = {"metric_fixture": str(write_report(store_root, "metric_fixture", full)),
               "stat_fixture": str(write_report(store_root, "stat_fixture", stats))}
    return {"ok": bool(metrics.get("ok")) and bool(stats.get("ok")),
            "status": "PASS" if (metrics.get("ok") and stats.get("ok")) else "FAIL",
            "reports": written,
            "metrics_passed": metrics.get("checks_passed"), "metrics_total": metrics.get("checks_total"),
            "stats_passed": stats.get("checks_passed"), "stats_total": stats.get("checks_total"),
            "clopper_pearson_ok": stats.get("clopper_pearson_ok"),
            "bootstrap_unit": stats.get("bootstrap_unit")}


def step_health(store_root: Path) -> dict[str, Any]:
    from synlab.storage.store import health_check

    return jsonable(health_check(str(store_root)))


def step_cli_dry(store_root: Path) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    commands = (
        ("validate", ["-m", "synlab.cli", "validate", "--config", "configs/a12/sandbox.yaml",
                      "--json"]),
        ("validate_pool", ["-m", "synlab.cli", "validate", "--config", "configs/a12/pool_dev.yaml",
                           "--json"]),
        ("budget", ["-m", "synlab.cli", "budget", "--config", "configs/a12/sandbox.yaml", "--json"]),
        ("doctor", ["-m", "synlab.cli", "doctor", "--json"]),
    )
    for name, argv in commands:
        proc = subprocess.run([sys.executable, *argv], cwd=str(ROOT), capture_output=True,
                              text=True, timeout=900, check=False)
        runs[name] = {"exit": proc.returncode, "argv": argv,
                      "stdout_tail": (proc.stdout or "")[-2000:],
                      "stderr_tail": (proc.stderr or "")[-600:]}
    return {"ok": all(v["exit"] == 0 for v in runs.values()),
            "status": "PASS" if all(v["exit"] == 0 for v in runs.values()) else "FAIL",
            "cli": runs}


STEP_TABLE: dict[str, str] = {
    "registry": "registry_summary",
    "pattern-batch": "pattern_audit (part)",
    "pattern-merge": "pattern_audit",
    "axes-batch": "operator_audit (part)",
    "axes-merge": "operator_audit",
    "observe": "channel_audit + spurious_audit + camera_profile_audit",
    "pixel-contract": "pixel_contract",
    "fixtures": "metric_fixture + stat_fixture",
    "scale": "scale_report",
    "resource-profile": "resource_profile",
    "loader-probe": "loader_probe",
    "leakage": "leakage_negative_control",
    "api-ui": "api_ui_evidence",
    "health": "store_health",
    "cli-dry": "cli_dry_runs",
}


def dispatch(step: str, store_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    if step == "registry":
        return run_step("registry", lambda: step_registry(store_root), store_root,
                        report_name="registry_summary")
    if step == "pattern-batch":
        return run_step("pattern-batch", lambda: step_pattern_batch(store_root, args), store_root)
    if step == "pattern-merge":
        return run_step("pattern-merge", lambda: step_pattern_merge(store_root, args), store_root,
                        report_name="pattern_audit")
    if step == "axes-batch":
        return run_step("axes-batch", lambda: step_axes_batch(store_root, args), store_root)
    if step == "axes-merge":
        return run_step("axes-merge", lambda: step_axes_merge(store_root, args), store_root,
                        report_name="operator_audit")
    if step == "observe":
        return run_step("observe", lambda: step_observe(store_root), store_root)
    if step == "pixel-contract":
        return run_step("pixel-contract", lambda: step_pixel_contract(store_root), store_root,
                        report_name="pixel_contract")
    if step == "fixtures":
        return run_step("fixtures", lambda: step_fixtures(store_root), store_root)
    if step == "scale":
        return run_step("scale", lambda: step_scale(store_root), store_root,
                        report_name="scale_report")
    if step == "resource-profile":
        return run_step("resource-profile", lambda: step_resource_profile(store_root, args),
                        store_root, report_name="resource_profile")
    if step == "loader-probe":
        return run_step("loader-probe", lambda: step_loader_probe(store_root), store_root,
                        report_name="loader_probe")
    if step == "leakage":
        return run_step("leakage", lambda: step_leakage(store_root, args), store_root,
                        report_name="leakage_negative_control")
    if step == "api-ui":
        return run_step("api-ui", lambda: step_api_ui(store_root), store_root,
                        report_name="api_ui_evidence")
    if step == "health":
        return run_step("health", lambda: step_health(store_root), store_root,
                        report_name="store_health")
    if step == "cli-dry":
        return run_step("cli-dry", lambda: step_cli_dry(store_root), store_root,
                        report_name="cli_dry_runs")
    raise SystemExit(f"unknown step {step!r}; known: {', '.join(sorted(STEP_TABLE))}")


def run_all(store_root: Path, args: argparse.Namespace) -> int:
    """In-process fallback: identical steps, one report each, in a single interpreter."""
    results: dict[str, Any] = {}
    for step in ("registry", "pattern-batch", "pattern-merge", "axes-batch", "axes-merge",
                 "observe", "pixel-contract", "scale", "loader-probe", "leakage", "api-ui",
                 "health"):
        if step in ("pattern-batch", "pattern-merge", "axes-batch", "axes-merge"):
            n = max(1, args.n_batches)
            for index in range(n):
                args.batch_index = index
                payload = dispatch(step, store_root, args)
                results[f"{step}:{index}"] = {"ok": payload.get("ok"),
                                              "status": payload.get("status")}
            continue
        payload = dispatch(step, store_root, args)
        results[step] = {"ok": payload.get("ok"), "status": payload.get("status")}
    write_report(store_root, "evidence_min_summary", {"ok": True, "steps": results})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="data/a12")
    parser.add_argument("--profile", default="SANDBOX_CORE")
    parser.add_argument("--step", default="all", choices=("all", *sorted(STEP_TABLE)))
    parser.add_argument("--batch-index", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--n-batches", type=int, default=4)
    parser.add_argument("--pattern-pairs", type=int, default=150)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    store_root = Path(args.data_root)
    if not store_root.is_absolute():
        store_root = ROOT / store_root
    store_root.mkdir(parents=True, exist_ok=True)

    if args.step == "all":
        return run_all(store_root, args)
    payload = dispatch(args.step, store_root, args)
    return 0 if (payload.get("report_path") or payload.get("part") or payload.get("reports")) else 3


if __name__ == "__main__":
    raise SystemExit(main())
