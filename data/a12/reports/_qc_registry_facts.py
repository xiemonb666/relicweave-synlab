"""Emit the per-target facts needed for docs/a12/dataset_registry.md (read-only)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPORTS = REPO / "data" / "a12" / "reports"
BLOCKING = {"FAIL", "MISSING", "UNREADABLE"}

rows = []
for path in sorted(REPORTS.glob("data_quality_*.json")):
    r = json.loads(path.read_text(encoding="utf-8"))
    t = r["target"]
    checks = {c["id"]: c for c in r["checks"]}
    blocking = [c for c in r["checks"] if c["required"] and c["status"] in BLOCKING]
    gen = checks["semantics.generation_uniform"]
    rows.append({
        "path": t["path"],
        "kind": t["kind"],
        "report": path.name,
        "verdict": r["verdict"],
        "trainable": r["trainable"],
        "counts": r.get("counts"),
        "relation_rows": r.get("relation_rows"),
        "relation_source": r.get("relation_source"),
        "generation": gen["status"],
        "generation_detail": gen["detail"],
        "blocking": [{"id": c["id"], "status": c["status"], "detail": c["detail"],
                      "denominator": c["denominator"], "hits": c["hits"]} for c in blocking],
        "unreadable_count": len(r.get("unreadable") or []),
        "provenance": {k: v for k, v in (r.get("provenance") or {}).items()
                       if k in ("git_head", "git_dirty", "git_dirty_file_count")},
    })

out = REPORTS / "_qc_registry_facts.json"
out.write_text(json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
print(f"wrote {out} ({len(rows)} targets)")
for row in rows:
    print("=" * 100)
    print(f"{row['path']} [{row['kind']}] -> {row['verdict']} trainable={row['trainable']}")
    c = row["counts"] or {}
    print(f"  assets={c.get('total')} PASS={c.get('QA_PASS')} PEND={c.get('QA_PENDING')} "
          f"FAIL={c.get('QA_FAIL')} relations={row['relation_rows']} "
          f"unreadable={row['unreadable_count']}")
    print(f"  generation: {row['generation']} -- {row['generation_detail'][:200]}")
    for b in row["blocking"]:
        print(f"    {b['status']:<9} {b['id']}  ({b['hits']}/{b['denominator']})")
        print(f"        {b['detail'][:250]}")
