"""Probe 09: axis registry introspection + level-0 identity + materialised levels (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections, sys
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
sys.path.insert(0, str(ROOT))

L = []
w = L.append


def main() -> None:
    from synlab.degrade.registry import AXIS_REGISTRY
    reg = AXIS_REGISTRY
    ops = getattr(reg, "_ops", None) or getattr(reg, "_registry", None)
    w("# probe_09 degradation axis registry")
    w(f"  registry attrs: {[a for a in dir(reg) if not a.startswith('__')]}")
    ids = None
    for attr in ("axis_ids", "ids", "keys", "all_ids"):
        v = getattr(reg, attr, None)
        if callable(v):
            try:
                ids = list(v())
                break
            except Exception:
                pass
        elif v is not None:
            ids = list(v)
            break
    if ids is None and isinstance(ops, dict):
        ids = sorted(ops)
    w(f"  n axes resolved = {len(ids) if ids else 'unknown'}  ids={ids}")
    w("")
    w(f"  {'axis':6s} {'stage':18s} {'kind':16s} {'default_variant':24s} levels/params")
    rows = []
    for aid in (ids or []):
        op = reg.get(aid)
        stage = getattr(op, "STAGE", "?")
        kind = getattr(op, "FACTOR_KIND", getattr(op, "KIND", "?"))
        dv = getattr(op, "default_variant", "?")
        variants = op.variants() if hasattr(op, "variants") else None
        lv = getattr(op, "LEVELS", None)
        extra = f"variants={variants} levels={lv}"
        w(f"  {aid:6s} {stage:18s} {str(kind):16s} {str(dv):24s} {extra}")
        rows.append((aid, stage, str(kind), str(dv), variants, lv))
    w("")
    stage_hist = collections.Counter(r[1] for r in rows)
    w(f"  stage histogram ({len(rows)} axes): {dict(stage_hist)}")
    w("")
    # summary_table
    try:
        from synlab.degrade.registry import summary_table
        st = summary_table()
        w("  summary_table():")
        w("  " + json.dumps(st, ensure_ascii=False, default=str)[:6000])
    except Exception as e:  # noqa: BLE001
        w(f"  summary_table unavailable: {e}")
    w("")

    # ---- materialised: degrade_measurement / obs_view assets carrying axis_id+level
    dbs = sorted(ROOT.joinpath("data").rglob("metadata.sqlite"))
    mat = collections.Counter()
    variants = collections.Counter()
    kinds = collections.Counter()
    origins = collections.Counter()
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
            con.row_factory = sqlite3.Row
            tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            if "assets" not in tabs:
                con.close()
                continue
            rs = con.execute("select role, meta_json from assets").fetchall()
            con.close()
        except Exception:  # noqa: BLE001
            continue
        for r in rs:
            mj = json.loads(r["meta_json"] or "{}")
            ax = mj.get("axis_id")
            if ax is None:
                continue
            mat[(str(ax), int(mj.get("level", -1)), str(r["role"]))] += 1
            variants[(str(ax), str(mj.get("variant")))] += 1
            kinds[str(mj.get("factor_kind"))] += 1
            origins[str(mj.get("origin_role"))] += 1
    w("## MATERIALISED (axis_id, level, role) counts across ALL stores")
    for k in sorted(mat):
        w(f"  axis={k[0]:5s} level={k[1]:<3d} role={k[2]:22s} count={mat[k]}")
    w("")
    w(f"## axes with >=1 materialised level: {sorted({k[0] for k in mat})}")
    w(f"## n distinct axes materialised = {len({k[0] for k in mat})} / {len(rows)}")
    w(f"## factor_kind histogram: {dict(kinds)}")
    w(f"## origin_role histogram: {dict(origins)}")
    w("")
    w("## (axis, variant) pairs materialised")
    for k in sorted(variants):
        w(f"  {k[0]:5s} {k[1]:34s} {variants[k]}")

    txt = "\n".join(L)
    (OUT / "probe_09_axes.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
