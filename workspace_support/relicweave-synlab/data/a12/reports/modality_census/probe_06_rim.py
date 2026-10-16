"""Probe 06: does ANY route/view produce rim (surface_tag==2) pixels? + full tag histograms (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
DB = ROOT / "data" / "a12" / "metadata.sqlite"
ASSETS = ROOT / "data" / "a12" / "assets"

L = []
w = L.append


def main() -> None:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select asset_id, role, meta_json from assets where role in "
        "('obs_result','obs_view','obs_fused_geometry','feature_bundle','label_bundle') "
        "order by role, asset_id").fetchall()
    con.close()

    # ---- obs_result: per-route tag histogram over ALL views
    w("=" * 100)
    w("# obs_result -- surface_tag histogram over ALL views, per route")
    per_route = collections.defaultdict(lambda: collections.Counter())
    per_route_px = collections.Counter()
    routes = collections.Counter()
    renderer_kinds = collections.Counter()
    for r in rows:
        if r["role"] != "obs_result":
            continue
        mj = json.loads(r["meta_json"])
        route = str(mj.get("route"))
        routes[route] += 1
        renderer_kinds[str(mj.get("backend_report", {}).get("route"))] += 1
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            for k in z.files:
                if k.endswith(".surface_tag"):
                    st = z[k]
                    for val, c in zip(*np.unique(st, return_counts=True)):
                        per_route[route][int(val)] += int(c)
                    per_route_px[route] += int(st.size)
    w(f"  obs_result routes: {dict(routes)}")
    w(f"  backend_report.route: {dict(renderer_kinds)}")
    for route, h in sorted(per_route.items()):
        tot = per_route_px[route]
        w(f"  ROUTE {route}  total_px={tot}")
        for k in sorted(h):
            w(f"      tag={k:4d} px={h[k]:12d}  {100.0*h[k]/max(tot,1):8.4f}%")
    w("")
    for route, h in sorted(per_route.items()):
        w(f"  ROUTE {route}: rim(tag=2) pixels = {h.get(2, 0)}")

    # ---- obs_view
    w("")
    w("=" * 100)
    w("# obs_view -- which channels present, tag/roi/mask stats")
    ov = [r for r in rows if r["role"] == "obs_view"]
    summ = collections.Counter()
    for r in ov:
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            for k in z.files:
                base = k.split(".", 2)[-1]
                summ[base] += 1
    for k, c in summ.most_common(60):
        w(f"      {k:30s} in {c}/{len(ov)} obs_view assets")

    # ---- feature_bundle: global_rgb / label_bundle maps
    w("")
    w("=" * 100)
    w("# label_bundle -- surface_tag_map histogram (per-view) to check rim presence in labels")
    lh = collections.Counter()
    lpx = 0
    n_assets = 0
    for r in rows:
        if r["role"] != "label_bundle":
            continue
        n_assets += 1
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            for k in z.files:
                if k.startswith("label__surface_tag_map__"):
                    a = z[k]
                    for val, c in zip(*np.unique(a, return_counts=True)):
                        lh[int(val)] += int(c)
                    lpx += int(a.size)
    w(f"  label_bundle assets={n_assets} total px over all maps={lpx}")
    for k in sorted(lh):
        w(f"      tag={k:4d} px={lh[k]:12d}  {100.0*lh[k]/max(lpx,1):8.4f}%")

    # ---- research_id_map histogram (is id_map useful as ID channel?)
    w("")
    rid = collections.Counter()
    rpx = 0
    for r in rows:
        if r["role"] != "label_bundle":
            continue
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            for k in z.files:
                if k.startswith("label__research_id_map__"):
                    a = z[k]
                    u, c = np.unique(a, return_counts=True)
                    rid[int(u.min()) if u.size else 0] += 0
                    # record distinct label count per map
                    rid[f"n_distinct={u.size}"] += 1
                    rpx += int(a.size)
    w(f"  research_id_map total px={rpx}; distinct-value histogram: {dict(sorted(rid.items(), key=lambda x: str(x[0])))}")

    txt = "\n".join(L)
    (OUT / "probe_06_rim.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
