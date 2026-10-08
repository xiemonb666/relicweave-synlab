"""Probe 16: verify contract-vocabulary mismatches + meta nesting + truth_incomplete (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections, sys
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
sys.path.insert(0, str(ROOT))

L = []
w = L.append


def main() -> None:
    import synlab.roles as R
    declared_schemas = {v for k, v in vars(R).items() if k.startswith("SCHEMA_")}
    declared_units = {v for k, v in vars(R).items() if k.startswith("UNIT_")}
    declared_frames = {v for k, v in vars(R).items() if k.startswith("FRAME_")}
    declared_roles = {v for k, v in vars(R).items() if k.startswith("ROLE_")}

    w("# probe_16 contract-vocabulary mismatches (READ ONLY)")
    w(f"  roles.py SCHEMA_* ({len(declared_schemas)}): {sorted(declared_schemas)}")
    w(f"  roles.py UNIT_*   ({len(declared_units)}): {sorted(declared_units)}")
    w(f"  roles.py FRAME_*  ({len(declared_frames)}): {sorted(declared_frames)}")
    w(f"  roles.py ROLE_*   ({len(declared_roles)})")
    w("")

    for rel in ("data/a12/metadata.sqlite", "data/a12_demo/store/metadata.sqlite"):
        db = ROOT / rel
        if not db.exists():
            w(f"  {rel}: MISSING")
            continue
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        sch = {r[0] for r in con.execute("select distinct schema from assets")}
        un = {r[0] for r in con.execute("select distinct unit from assets")}
        fr = {r[0] for r in con.execute("select distinct frame from assets")}
        rol = {r[0] for r in con.execute("select distinct role from assets")}
        w(f"## {rel}")
        w(f"  roles on assets ({len(rol)}): {sorted(rol)}")
        w(f"  roles NOT declared in roles.py: {sorted(rol - declared_roles)}")
        w(f"  schemas on assets ({len(sch)}) NOT declared in roles.py: {sorted(sch - declared_schemas)}")
        w(f"  units on assets ({len(un)}) NOT declared in roles.py:   {sorted(un - declared_units)}")
        w(f"  frames on assets ({len(fr)}) NOT declared in roles.py:  {sorted(fr - declared_frames)}")
        # declared but unused
        w(f"  declared schemas with NO asset here: {sorted(declared_schemas - sch)}")
        w("")
        if rel == "data/a12/metadata.sqlite":
            w("## meta nesting trap: which roles wrap payload under a top-level 'meta' key?")
            nest, total = collections.Counter(), collections.Counter()
            for r in con.execute("select role, meta_json from assets"):
                mj = json.loads(r["meta_json"] or "{}")
                total[r["role"]] += 1
                if isinstance(mj.get("meta"), dict):
                    nest[r["role"]] += 1
            for role in sorted(total):
                flag = "  <-- NESTED" if nest[role] else ""
                w(f"    {role:26s} nested-meta {nest[role]:4d} / {total[role]:4d}{flag}")
            w("")
            w("## visible_labels: truth_incomplete vs qa_status")
            for r in con.execute(
                    "select qa_status, json_extract(meta_json, '$.truth_incomplete') ti, "
                    "count(*) c from assets where role='visible_labels' group by 1,2"):
                w(f"    qa={r['qa_status']:10s} truth_incomplete={str(r['ti']):6s} count={r['c']}")
            w("")
            w("## history.association_kind per truth role")
            for role in ("clean_truth", "physical_truth", "visible_labels", "label_bundle"):
                vals = collections.Counter()
                for r in con.execute("select meta_json from assets where role=?", (role,)):
                    mj = json.loads(r["meta_json"] or "{}")
                    vals[str((mj.get("history") or {}).get("association_kind"))] += 1
                w(f"    {role:16s} {dict(vals)}")
            w("")
            w("## synlab.obs.v1 covers which (unit, frame)?  -- one schema id, two units")
            for r in con.execute(
                    "select schema, unit, count(*) c from assets group by 1,2 order by 1,2"):
                star = "  <-- px/mm split" if r["schema"] == "synlab.obs.v1" else ""
                w(f"    {r['schema']:26s} unit={r['unit']:8s} {r['c']:4d}{star}")
        con.close()
        w("")

    txt = "\n".join(L)
    (OUT / "probe_16_contract_mismatch.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
