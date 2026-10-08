"""Read-only census of a real store: runs, per-role run_id/QA coverage, gate inputs.

Usage:  python data/a12_exports/_scratch/census_gates.py <store_root> [<store_root> ...]
Writes JSON to stdout; nothing is modified.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def census(root: Path) -> dict:
    db = root / "metadata.sqlite"
    out: dict = {"store_root": str(root), "db": str(db), "db_exists": db.exists()}
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    con.row_factory = sqlite3.Row
    runs = [dict(r) for r in con.execute(
        "SELECT run_id, status, scope, profile, created_at, json_extract(meta_json,'$.accepted') AS accepted,"
        " json_extract(meta_json,'$.attempted') AS attempted FROM runs ORDER BY created_at")]
    for r in runs:
        r.pop("created_at", None)
    out["runs"] = runs
    rows = list(con.execute("SELECT role, qa_status, meta_json, lineage_id FROM assets"))
    by_role: dict[str, Counter] = {}
    for r in rows:
        meta = json.loads(r["meta_json"] or "{}")
        rid = meta.get("run_id")
        key = "run_id" if rid else "none"
        by_role.setdefault(r["role"], Counter())[key] += 1
        by_role[r["role"]][f"qa:{r['qa_status']}"] += 1
    out["assets_total"] = len(rows)
    out["by_role"] = {k: dict(v) for k, v in sorted(by_role.items())}
    out["roles_total"] = len(by_role)
    # meta key survey per interesting role
    keys: dict[str, Counter] = {}
    for r in rows:
        if r["role"] in ("mother_mesh", "pattern_recipe", "material_profile", "physical_component",
                         "physical_result", "provenance", "clean_truth", "relation_pool",
                         "query_roster", "obs_result"):
            meta = json.loads(r["meta_json"] or "{}")
            for k in meta:
                keys.setdefault(r["role"], Counter())[k] += 1
    out["meta_keys"] = {k: dict(v) for k, v in sorted(keys.items())}
    con.close()
    rep = root / "reports"
    out["reports"] = sorted(p.name for p in rep.glob("*.json")) if rep.exists() else []
    for name in ("coverage", "operator_audit", "pattern_audit", "acceptance_summary",
                 "recovery_probe", "loader_probe", "resource_profile", "mvs_subset",
                 "api_ui_evidence", "l2_scale", "scale_report", "research_evidence",
                 "coverage_rows"):
        p = rep / f"{name}.json"
        if not p.exists():
            out[f"report::{name}"] = None
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out[f"report::{name}"] = f"unreadable: {exc}"
            continue
        if isinstance(payload, dict):
            summary = {k: v for k, v in payload.items()
                       if k in ("ok", "run_id", "status", "complete", "counts", "accepted",
                                "accepted_max", "fracture_backend", "vessels", "materials",
                                "patterns", "layer_combos", "axes", "all_axes_pass",
                                "axes_registered", "axes_audited", "axes_pass", "axes_fail",
                                "axes_missing")}
            if name == "acceptance_summary":
                items = payload.get("items") or {}
                summary = {"items": {k: (v or {}).get("status") for k, v in sorted(items.items())}}
                summary["counts"] = payload.get("counts")
            out[f"report::{name}"] = summary
        else:
            out[f"report::{name}"] = f"<{type(payload).__name__} len={len(payload)}>"
    # axis registry
    from synlab.degrade.registry import AXIS_REGISTRY  # noqa: PLC0415
    out["axes_registered"] = AXIS_REGISTRY.ids()
    return out


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or [REPO / "data" / "a12"]
    payload = [census(r) for r in roots]
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
