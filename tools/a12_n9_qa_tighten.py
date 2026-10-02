#!/usr/bin/env python
"""N9: version the QA tightening that puts ``roi_external_drift`` into ``failure_codes``.

Three steps, all read-only with respect to the produced artifacts (nothing is rewritten, no
manifest is edited):

``--step reproduce``
    The before/after on real recorded audits.  ``data/a12_reports/s11_p03_drift.json`` is the
    global-SDF P03 result (``roi_external_drift_mm = 0.35424330830574036``,
    ``checks.roi_external_drift.pass = false``, ``status = PASS``, ``failure_codes = []``);
    ``data/a12_reports/s11_p03_narrowband_routed.json`` is the same body on the narrowband path
    (``0.00034815253457054496``, ``pass = true``).  The policy must flip the first and leave the
    second alone.  ``--rerun`` additionally re-runs the P03 global-SDF pipeline first and applies
    the policy to the **fresh** audit (``data/a12_reports/n9_rerun_global_sdf.json``).

``--step scan``
    Every produced artifact that carries the drift check: report JSONs, store ``assets/*/meta.json``
    and store databases (``assets.qa_json``).  Each record gets its v1 and v2 verdict; the flips
    are written to ``data/a12_reports/n9_qa_v2_flips.json`` together with the "pre-fix generation"
    label (``superseded_by_qa_policy:a12.qa.v2``).  The old artifacts are **not** modified: the
    registry is the label, exactly like the ``_archive_pre_fix`` convention.

``--step version``
    The policy's own record (version, change, reason, evidence) as JSON, for the report.

Usage::

    python tools/a12_n9_qa_tighten.py --step all --out data/a12_reports/n9_qa_v2.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_GLOBAL = "data/a12_reports/s11_p03_drift.json"
DEFAULT_NARROWBAND = "data/a12_reports/s11_p03_narrowband_routed.json"
DEFAULT_RERUN = "data/a12_reports/n9_rerun_global_sdf.json"
DEFAULT_ROOTS = ("data",)
#: a produced artifact larger than this is reported as skipped instead of being parsed
MAX_JSON_BYTES = 400_000_000


# --------------------------------------------------------------------------------------
# finding audits inside real artifacts
# --------------------------------------------------------------------------------------
def walk_audits(value: Any, *, path: str = "$") -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Yield every audit-shaped mapping inside a parsed JSON document, with its path."""
    from synlab.qc.qa_policy import DRIFT_CHECK, looks_like_audit

    if isinstance(value, Mapping):
        if looks_like_audit(value) and isinstance((value.get("checks") or {}).get(DRIFT_CHECK),
                                                 Mapping):
            yield path, value
        for key, item in value.items():
            yield from walk_audits(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if index > 5000:
                break
            yield from walk_audits(item, path=f"{path}[{index}]")


def scan_json(path: Path, *, root: Path) -> list[dict[str, Any]]:
    from synlab.qc.qa_policy import audit_verdict

    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            return [{"artifact": str(path), "kind": "skipped_too_large",
                     "bytes": path.stat().st_size}]
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - an unreadable artifact is reported, never guessed
        return [{"artifact": str(path), "kind": "unreadable", "error": f"{type(exc).__name__}: {exc}"}]
    out: list[dict[str, Any]] = []
    for json_path, audit in walk_audits(payload):
        out.append(_record(f"json:{json_path}", str(path), root, audit))
    return out


def scan_sqlite(path: Path, *, root: Path) -> list[dict[str, Any]]:
    from synlab.qc.qa_policy import audit_verdict

    out: list[dict[str, Any]] = []
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT asset_id, role, qa_status, qa_json FROM assets").fetchall()
        con.close()
    except Exception as exc:  # noqa: BLE001
        return [{"artifact": str(path), "kind": "sqlite_unreadable",
                 "error": f"{type(exc).__name__}: {exc}"}]
    for row in rows:
        blob = row["qa_json"] or "{}"
        if "roi_external_drift" not in blob:
            continue
        try:
            qa = json.loads(blob)
        except Exception:  # noqa: BLE001
            continue
        records = list(walk_audits(qa, path="$.qa"))
        if not records:
            # the QA block may carry the check at the top level rather than as a full audit
            records = [("$.qa", {"checks": {"roi_external_drift": (qa.get("checks") or {}).get(
                "roi_external_drift", qa.get("roi_external_drift"))},
                "failure_codes": list(qa.get("failure_codes") or []),
                "status": str(row["qa_status"] or "")})]
        for json_path, audit in records:
            record = _record(f"sqlite:{row['asset_id']}:{json_path}", str(path), root, audit,
                             extra={"asset_id": row["asset_id"], "role": row["role"],
                                    "store_qa_status": str(row["qa_status"] or "")})
            out.append(record)
    return out


def _record(location: str, artifact: str, root: Path, audit: Mapping[str, Any], *,
            extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from synlab.qc.qa_policy import audit_verdict

    verdict = audit_verdict(audit)
    try:
        relative = str(Path(artifact).resolve().relative_to(root.resolve()))
    except Exception:  # noqa: BLE001
        relative = artifact
    return {"artifact": artifact, "root": str(root), "relative": relative, "location": location,
            "label": (f"superseded_by_qa_policy:{verdict['qa_policy_before']}"
                      if verdict["flips"] else "current"),
            **verdict, **(dict(extra or {}))}


def scan_roots(roots: Iterable[str | Path]) -> dict[str, Any]:
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    counters = {"json_files": 0, "sqlite_files": 0, "skipped": 0, "unreadable": 0}
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            records.append({"artifact": str(root_path), "kind": "root_missing"})
            continue
        for path in sorted(root_path.rglob("*.json")):
            counters["json_files"] += 1
            found = scan_json(path, root=root_path)
            counters["skipped"] += sum(1 for item in found if item.get("kind") == "skipped_too_large")
            counters["unreadable"] += sum(1 for item in found if item.get("kind") == "unreadable")
            records.extend(item for item in found if "status_before" in item)
        for path in sorted(root_path.rglob("*.sqlite")):
            counters["sqlite_files"] += 1
            found = scan_sqlite(path, root=root_path)
            counters["unreadable"] += sum(1 for item in found if item.get("kind") == "sqlite_unreadable")
            records.extend(item for item in found if "status_before" in item)
    flips = [item for item in records if item["flips"]]
    by_kind: dict[str, int] = {}
    by_root: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for item in records:
        kind = str(item["location"]).split(":", 1)[0]
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_root[item["root"]] = by_root.get(item["root"], 0) + 1
        key = f"{item['status_before']}->{item['status_after']}"
        statuses[key] = statuses.get(key, 0) + 1
    archives = [item for item in flips if "_archive_pre_fix" in item["artifact"]]
    return {
        "schema": "synlab.a12.n9_qa_v2.scan.v1",
        "roots": [str(root) for root in roots],
        "counters": {**counters, "records_with_drift_check": len(records),
                     "flips": len(flips), "flips_in_archive": len(archives)},
        "by_location_kind": dict(sorted(by_kind.items())),
        "by_root": dict(sorted(by_root.items())),
        "status_transitions": dict(sorted(statuses.items())),
        "flips": flips,
        "unchanged": [item for item in records if not item["flips"]],
        "wall_seconds": time.perf_counter() - started,
    }


def annotations(scan: Mapping[str, Any]) -> dict[str, str]:
    """The "pre-fix generation" label registry (nothing on disk is rewritten)."""
    out: dict[str, str] = {}
    for item in scan.get("flips", []):
        out[f"{item['artifact']}#{item['location']}"] = (
            f"{item['label']} (measured drift {item['drift_mm']} mm > "
            f"{item['threshold_mm']} mm; v1 verdict {item['status_before']})")
    return out


# --------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------
def version_step() -> dict[str, Any]:
    from synlab.qc.qa_policy import (DRIFT_FAILURE_CODE, QA_POLICY_HISTORY, QA_POLICY_VERSION,
                                     DRIFT_MAX_MM_DEFAULT)

    return {
        "schema": "synlab.a12.n9_qa_v2.version.v1",
        "qa_policy_version": QA_POLICY_VERSION,
        "failure_code_added": DRIFT_FAILURE_CODE,
        "threshold_mm_default": DRIFT_MAX_MM_DEFAULT,
        "history": [dict(item) for item in QA_POLICY_HISTORY],
        "change_scope": ("synlab/qc/qa_policy.py (new policy layer); the frozen producer "
                         "synlab/physical/api.py is unchanged and out of this task's write scope"),
        "guarantees": ["adds failure codes only", "never upgrades a status",
                       "never re-measures", "idempotent"],
    }


def _verdicts(path: str | Path) -> dict[str, Any]:
    from synlab.qc.qa_policy import apply_qa_policy, audit_verdict

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    audits = list(walk_audits(payload))
    if not audits:
        return {"path": str(path), "found": False}
    json_path, audit = audits[0]
    return {"path": str(path), "found": True, "audit_path": json_path,
            "before": {key: audit.get(key) for key in ("status", "failure_codes")},
            "verdict": audit_verdict(audit),
            "after": {key: apply_qa_policy(audit).get(key)
                      for key in ("status", "failure_codes", "qa_policy")}}


def reproduce_step(*, global_path: str | Path, narrowband_path: str | Path,
                   rerun_path: str | Path | None = None) -> dict[str, Any]:
    from synlab.qc.qa_policy import QA_POLICY_VERSION, apply_qa_policy

    out: dict[str, Any] = {
        "schema": "synlab.a12.n9_qa_v2.reproduce.v1",
        "qa_policy_version": QA_POLICY_VERSION,
        "global_sdf": _verdicts(global_path),
        "narrowband": _verdicts(narrowband_path),
        "rerun": _verdicts(rerun_path) if rerun_path and Path(rerun_path).exists() else
                 {"path": str(rerun_path or ""), "found": False},
    }
    global_ok = bool(out["global_sdf"].get("verdict", {}).get("flips"))
    narrowband_ok = not out["narrowband"].get("verdict", {}).get("flips", True)
    out["ok"] = bool(global_ok and narrowband_ok)
    out["expectation"] = ("the recorded 0.354 mm global-SDF audit flips PASS -> FAIL with "
                          "ROI_EXTERNAL_DRIFT_EXCEEDED; the 0.000348 mm narrowband audit stays "
                          "PASS")
    out["conclusion"] = (
        "the frozen producer already measured the drift and already computed pass=false; the v2 "
        "policy turns that recorded verdict into a failure code.  Nothing is re-measured and no "
        "threshold is changed (R5).")
    return out


def category_of(artifact: str) -> str:
    """Which produced-generation an artifact belongs to (the flip list's own vocabulary)."""
    path = str(Path(artifact)).replace("\\", "/")
    if "_archive_pre_fix" in path:
        return "archive_pre_fix"
    if "a12_exports" in path:
        return "exported_package"
    if "/assets/asset_" in path or path.endswith("metadata.sqlite"):
        return "store_asset"
    if "a12_reports" in path:
        return "report"
    return "other"


def annotate_scan(scan: Mapping[str, Any]) -> dict[str, Any]:
    """Add the per-category flip table (records **and** distinct artifacts) to a scan.

    A store asset's ``meta.json`` carries its QA block twice (``$.meta.qa`` and ``$.qa``), so the
    record count is not the artifact count; both are reported rather than one being called the
    other.
    """
    flips = list(scan.get("flips") or [])
    records = list(flips) + list(scan.get("unchanged") or [])
    out: dict[str, Any] = {
        "by_category": {},
        "flip_artifacts_distinct": len({item["artifact"] for item in flips}),
        "records_with_drift_check": len(records),
        "note": ("a store asset meta.json carries its QA block twice ($.meta.qa and $.qa), so "
                 "record counts exceed artifact counts; both are given"),
    }
    for category in ("exported_package", "store_asset", "report", "other", "archive_pre_fix"):
        selected = [item for item in flips if category_of(item["artifact"]) == category]
        all_records = [item for item in records if category_of(item["artifact"]) == category]
        out["by_category"][category] = {
            "flip_records": len(selected),
            "flip_artifacts": len({item["artifact"] for item in selected}),
            "records_with_drift_check": len(all_records),
            "already_fail": sum(1 for item in all_records if item["status_before"] == "FAIL"),
            "stayed_pass": sum(1 for item in all_records
                               if item["status_before"] == "PASS" and not item["flips"]),
            "drift_mm_min": min((item["drift_mm"] for item in selected), default=None),
            "drift_mm_max": max((item["drift_mm"] for item in selected), default=None),
            "roles": {role: count for role, count in sorted(
                __import__("collections").Counter(
                    str(item.get("role")) for item in selected if item.get("role")).items())},
        }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", default="all", choices=("version", "reproduce", "scan", "all"))
    parser.add_argument("--global-audit", default=DEFAULT_GLOBAL)
    parser.add_argument("--narrowband-audit", default=DEFAULT_NARROWBAND)
    parser.add_argument("--rerun", default=DEFAULT_RERUN)
    parser.add_argument("--root", action="append", default=None)
    parser.add_argument("--out", default="data/a12_reports/n9_qa_v2.json")
    parser.add_argument("--flips-out", default="data/a12_reports/n9_qa_v2_flips.json")
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {"schema": "synlab.a12.n9_qa_v2.run.v1", "step": args.step}
    ok = True
    if args.step in ("version", "all"):
        payload["version"] = version_step()
    if args.step in ("reproduce", "all"):
        payload["reproduce"] = reproduce_step(global_path=args.global_audit,
                                             narrowband_path=args.narrowband_audit,
                                             rerun_path=args.rerun)
        ok = bool(ok and payload["reproduce"]["ok"])
    if args.step in ("scan", "all"):
        scan = scan_roots(args.root or DEFAULT_ROOTS)
        scan["annotations"] = annotations(scan)
        scan.update(annotate_scan(scan))
        payload["scan"] = {key: value for key, value in scan.items()
                           if key not in ("flips", "unchanged")}
        payload["scan"]["flip_count"] = len(scan["flips"])
        flips_path = Path(args.flips_out)
        flips_path.parent.mkdir(parents=True, exist_ok=True)
        flips_path.write_text(json.dumps(
            {"schema": "synlab.a12.n9_qa_v2.flips.v1",
             "qa_policy_version": payload.get("version", {}).get("qa_policy_version", ""),
             "note": ("the label registry of the pre-fix generation: these artifacts keep their "
                      "bytes and their manifests; their QA verdict is superseded by the versioned "
                      "policy"),
             "counts": {key: value for key, value in scan.items()
                        if key in ("counters", "by_location_kind", "by_root", "status_transitions",
                                   "by_category", "flip_artifacts_distinct")},
             "flips": scan["flips"], "annotations": scan["annotations"]},
            ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
        payload["scan"]["flips_path"] = str(flips_path)
        payload["scan"]["flips"] = scan["flips"][:20]

    payload["ok"] = ok
    payload["status"] = "PASS" if ok else "FAIL"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                   default=str), encoding="utf-8")

    if "version" in payload:
        print(f"QA policy: {payload['version']['qa_policy_version']} "
              f"(adds {payload['version']['failure_code_added']})")
    if "reproduce" in payload:
        rep = payload["reproduce"]
        for key in ("global_sdf", "narrowband", "rerun"):
            item = rep.get(key, {})
            if not item.get("found"):
                print(f"  {key}: not present")
                continue
            verdict = item["verdict"]
            print(f"  {key}: drift={verdict['drift_mm']} mm pass={verdict['drift_pass']} "
                  f"{verdict['status_before']} -> {verdict['status_after']} "
                  f"added={verdict['added_failure_codes']}")
    if "scan" in payload:
        scan = payload["scan"]
        print(f"  scan: records={scan['counters']['records_with_drift_check']} "
              f"flips={scan['counters']['flips']} "
              f"(archive {scan['counters']['flips_in_archive']}) "
              f"by_root={scan['by_root']} transitions={scan['status_transitions']}")
        for category, item in scan["by_category"].items():
            print(f"    {category:>17}: flip_records={item['flip_records']:>4} "
                  f"flip_artifacts={item['flip_artifacts']:>4} "
                  f"already_fail={item['already_fail']:>4} "
                  f"stayed_pass={item['stayed_pass']:>2} "
                  f"drift[{item['drift_mm_min']}, {item['drift_mm_max']}]")
    print(f"status={payload['status']} out={out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
