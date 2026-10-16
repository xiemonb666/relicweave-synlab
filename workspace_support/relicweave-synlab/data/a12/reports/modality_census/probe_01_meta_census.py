"""Probe 01: census every asset meta.json under data/a12/assets (READ ONLY)."""
from __future__ import annotations
import json, os, sys, collections
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
ASSETS = ROOT / "data" / "a12" / "assets"
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"

def main() -> None:
    dirs = sorted([d for d in ASSETS.iterdir() if d.is_dir()])
    n_dir = len(dirs)
    roles = collections.Counter()
    schemas = collections.Counter()
    units = collections.Counter()
    frames = collections.Counter()
    role_schema = collections.Counter()
    role_unit = collections.Counter()
    role_frame = collections.Counter()
    has_npz = 0
    npz_keys_by_role = collections.defaultdict(collections.Counter)
    npz_shapes_by_role = collections.defaultdict(collections.Counter)
    npz_dtypes_by_role = collections.defaultdict(collections.Counter)
    meta_top_keys_by_role = collections.defaultdict(collections.Counter)
    role_examples = collections.defaultdict(list)
    missing_meta = []
    bad = []
    status = collections.Counter()
    qa = collections.Counter()
    ancestor_roles = collections.Counter()

    import numpy as np

    for d in dirs:
        mp = d / "meta.json"
        npx = d / "arrays.npz"
        if not mp.exists():
            missing_meta.append(d.name)
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad.append((d.name, str(e)))
            continue
        role = m.get("role", "<none>")
        roles[role] += 1
        schemas[m.get("schema", "<none>")] += 1
        units[str(m.get("unit", "<none>"))] += 1
        frames[str(m.get("frame", "<none>"))] += 1
        role_schema[(role, m.get("schema", "<none>"))] += 1
        role_unit[(role, str(m.get("unit", "<none>")))] += 1
        role_frame[(role, str(m.get("frame", "<none>")))] += 1
        status[str(m.get("status", "<none>"))] += 1
        qa[str(m.get("qa_status", m.get("qa", "<none>")))] += 1
        for k in m.keys():
            meta_top_keys_by_role[role][k] += 1
        for a in (m.get("ancestors") or []):
            if isinstance(a, dict):
                ancestor_roles[a.get("role", "?")] += 1
        if len(role_examples[role]) < 3:
            role_examples[role].append(d.name)
        if npx.exists():
            has_npz += 1
            try:
                with np.load(npx, allow_pickle=False) as z:
                    for k in z.files:
                        npz_keys_by_role[role][k] += 1
                        npz_shapes_by_role[role][f"{k}:{tuple(z[k].shape)}"] += 1
                        npz_dtypes_by_role[role][f"{k}:{z[k].dtype}"] += 1
            except Exception as e:  # noqa: BLE001
                bad.append((d.name, f"npz:{e}"))

    lines = []
    w = lines.append
    w(f"# probe_01 meta census  (denominator: {n_dir} asset dirs under data/a12/assets)")
    w(f"assets_with_meta={n_dir - len(missing_meta)}, missing_meta={len(missing_meta)}, with_arrays_npz={has_npz}, bad={len(bad)}")
    w("")
    w("## role counts")
    for r, c in roles.most_common():
        w(f"  {r:32s} {c:6d}")
    w("")
    w("## schema counts")
    for s, c in schemas.most_common():
        w(f"  {s:32s} {c:6d}")
    w("")
    w("## unit counts")
    for s, c in units.most_common():
        w(f"  {s:24s} {c:6d}")
    w("")
    w("## frame counts")
    for s, c in frames.most_common():
        w(f"  {s:24s} {c:6d}")
    w("")
    w("## (role, schema) pairs")
    for (r, s), c in sorted(role_schema.items()):
        w(f"  {r:32s} {s:32s} {c:6d}")
    w("")
    w("## (role, unit, frame) triples")
    for (r, u), c in sorted(role_unit.items()):
        w(f"  {r:32s} unit={u:8s} {c:6d}")
    w("")
    for (r, f), c in sorted(role_frame.items()):
        w(f"  {r:32s} frame={f:14s} {c:6d}")
    w("")
    w("## status / qa_status")
    for s, c in status.most_common():
        w(f"  status {s:24s} {c:6d}")
    for s, c in qa.most_common():
        w(f"  qa     {s:24s} {c:6d}")
    w("")
    w("## ancestor role counts (references found across all metas)")
    for s, c in ancestor_roles.most_common():
        w(f"  {s:32s} {c:6d}")
    w("")
    w("## meta.json top-level keys per role")
    for r in sorted(meta_top_keys_by_role):
        w(f"  [{r}]")
        for k, c in meta_top_keys_by_role[r].most_common():
            w(f"      {k:34s} {c:6d}")
    w("")
    w("## arrays.npz keys per role  (count = #assets having that key)")
    for r in sorted(npz_keys_by_role):
        w(f"  [{r}]")
        for k, c in npz_keys_by_role[r].most_common():
            w(f"      {k:30s} {c:6d}")
    w("")
    w("## arrays.npz shapes per role (top 200)")
    n = 0
    for r in sorted(npz_shapes_by_role):
        w(f"  [{r}]")
        for k, c in npz_shapes_by_role[r].most_common(200):
            w(f"      {k:60s} {c:6d}")
            n += 1
            if n > 900:
                break
    w("")
    w("## arrays.npz dtypes per role")
    for r in sorted(npz_dtypes_by_role):
        w(f"  [{r}]")
        for k, c in npz_dtypes_by_role[r].most_common(80):
            w(f"      {k:60s} {c:6d}")
    w("")
    w("## example asset ids per role")
    for r in sorted(role_examples):
        w(f"  {r:32s} {role_examples[r]}")
    w("")
    if missing_meta:
        w(f"## dirs without meta.json ({len(missing_meta)}): {missing_meta[:40]}")
    if bad:
        w(f"## bad entries ({len(bad)}): {bad[:40]}")

    txt = "\n".join(lines)
    (OUT / "probe_01_meta_census.txt").write_text(txt, encoding="utf-8")
    print(txt[:6000])
    print(f"\n...wrote {OUT / 'probe_01_meta_census.txt'} ({len(txt)} chars)")

if __name__ == "__main__":
    main()
