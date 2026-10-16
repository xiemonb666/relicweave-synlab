"""Probe 05: FRACTURE-SPECIFIC evidence -- interface faces, areas, normals, pairing (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
DB = ROOT / "data" / "a12" / "metadata.sqlite"
ASSETS = ROOT / "data" / "a12" / "assets"
ORIGIN_MOTHER_SURFACE, ORIGIN_INTERFACE, ORIGIN_AMBIGUOUS = 0, 1, 2

L = []
w = L.append


def tri_area(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    a = v[f[:, 0]]
    b = v[f[:, 1]]
    c = v[f[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def main() -> None:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select asset_id, role, meta_json from assets where role in "
        "('fragment_mesh','physical_component','clean_truth','physical_truth','obs_result') "
        "order by role, asset_id").fetchall()
    con.close()

    # ---- 1. fragment_mesh interface census
    frags = [r for r in rows if r["role"] == "fragment_mesh"]
    w("=" * 100)
    w(f"# probe_05 FRACTURE census   fragment_mesh n={len(frags)}")
    w("")
    tot_faces = 0
    tot_iface = 0
    tot_amb = 0
    tot_area = 0.0
    tot_iface_area = 0.0
    per_asset = []
    iid_hist = collections.Counter()
    side_hist = collections.Counter()
    src_tri_missing = 0
    has_dev = 0
    for r in frags:
        p = ASSETS / r["asset_id"] / "arrays.npz"
        if not p.exists():
            continue
        with np.load(p, allow_pickle=False) as z:
            keys = set(z.files)
            v = z["mesh.vertices"]
            f = z["mesh.faces"]
            ok = z["mesh.face__origin_kind"] if "mesh.face__origin_kind" in keys else None
            iid = z["mesh.face__interface_id"] if "mesh.face__interface_id" in keys else None
            amb = z["mesh.face__ambiguous"] if "mesh.face__ambiguous" in keys else None
            side = z["mesh.face__side"] if "mesh.face__side" in keys else None
            st = z["mesh.face__source_tri"] if "mesh.face__source_tri" in keys else None
        area = tri_area(v, f)
        n = len(f)
        n_if = int(np.count_nonzero(ok == ORIGIN_INTERFACE))
        n_am = int(np.count_nonzero(ok == ORIGIN_AMBIGUOUS))
        a_if = float(area[ok == ORIGIN_INTERFACE].sum())
        tot_faces += n
        tot_iface += n_if
        tot_amb += n_am
        tot_area += float(area.sum())
        tot_iface_area += a_if
        if iid is not None:
            for x in np.unique(iid[ok == ORIGIN_INTERFACE]):
                iid_hist[int(x)] += 1
        if side is not None:
            for x in np.unique(side):
                side_hist[int(x)] += 1
        if st is not None and int(np.count_nonzero(st < 0)):
            src_tri_missing += 1
        per_asset.append((r["asset_id"], n, n_if, n_am, a_if, float(area.sum())))
    w(f"  assets scanned = {len(per_asset)}")
    w(f"  total faces              = {tot_faces}")
    w(f"  total faces origin=INTERFACE (k=1) = {tot_iface}  ({100.0*tot_iface/max(tot_faces,1):.2f}% of all faces)")
    w(f"  total faces origin=AMBIGUOUS (k=2) = {tot_amb}  ({100.0*tot_amb/max(tot_faces,1):.2f}%)")
    w(f"  total surface area  = {tot_area:.1f} mm^2 ; interface area = {tot_iface_area:.1f} mm^2 "
      f"({100.0*tot_iface_area/max(tot_area,1e-9):.2f}%)")
    w(f"  assets with any negative source_tri = {src_tri_missing}")
    w("")
    w(f"  interface_id value histogram (face counts per asset, INTERFACE faces only): {dict(sorted(iid_hist.items()))}")
    w(f"  face__side value histogram (present in how many assets): {dict(sorted(side_hist.items()))}")
    w("")
    w(f"  per-asset interface face fraction: min={min((x[2]/max(x[1],1)) for x in per_asset):.4f} "
      f"max={max((x[2]/max(x[1],1)) for x in per_asset):.4f}")
    areas_if = np.array([x[4] for x in per_asset])
    w(f"  per-asset interface area mm^2: min={areas_if.min():.3f} median={np.median(areas_if):.1f} "
      f"mean={areas_if.mean():.1f} max={areas_if.max():.1f}  (n={len(areas_if)})")
    faces_n = np.array([x[1] for x in per_asset])
    w(f"  per-asset face count: min={faces_n.min()} median={int(np.median(faces_n))} max={faces_n.max()}")
    w("")
    w("  first 10 assets (asset_id, faces, iface_faces, amby_faces, iface_area_mm2, total_area_mm2):")
    for x in per_asset[:10]:
        w(f"    {x[0]} {x[1]:6d} {x[2]:6d} {x[3]:5d} {x[4]:12.2f} {x[5]:14.2f}")

    # ---- 2. physical_component interface census
    comps = [r for r in rows if r["role"] == "physical_component"]
    w("")
    w("=" * 100)
    w(f"# physical_component n={len(comps)}")
    c_tot = c_if = 0
    c_area = c_ifarea = 0.0
    for r in comps:
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            keys = set(z.files)
            if "faces" in keys:
                v, f, ok = z["vertices"], z["faces"], z["face__origin_kind"]
            else:
                v, f, ok = z["payload.mesh.vertices"], z["payload.mesh.faces"], z["payload.mesh.face__origin_kind"]
        a = tri_area(v, f)
        c_tot += len(f)
        c_if += int(np.count_nonzero(ok == ORIGIN_INTERFACE))
        c_area += float(a.sum())
        c_ifarea += float(a[ok == ORIGIN_INTERFACE].sum())
    w(f"  components with mesh arrays = {sum(1 for r in comps)}")
    w(f"  total faces = {c_tot}; INTERFACE faces = {c_if} ({100.0*c_if/max(c_tot,1):.2f}%)")
    w(f"  total area = {c_area:.1f} mm^2; interface area = {c_ifarea:.1f} mm^2 "
      f"({100.0*c_ifarea/max(c_area,1e-9):.2f}%)")

    # ---- 3. clean_truth interface & pairing evidence
    cts = [r for r in rows if r["role"] == "clean_truth"]
    w("")
    w("=" * 100)
    w(f"# clean_truth n={len(cts)}  -- interface area / pairing / normals")
    iface_counts = []
    clip_area = []
    pair_common = []
    gap_p95 = []
    nrm_p95 = []
    per_asset_iface_sum = []
    rel_kinds = collections.Counter()
    n_rel = 0
    for r in cts:
        mj = json.loads(r["meta_json"])
        fq = mj.get("fracture_qa") or {}
        iface_counts.append(fq.get("interface_count"))
        clip_area.append(fq.get("interface_common_clip_area_mm2"))
        pair_common.append(fq.get("interface_pair_common_clip_area_mm2"))
        gap_p95.append(fq.get("gap_p95_mm_max"))
        nrm_p95.append(fq.get("normal_angle_p95_deg_max"))
        for rel in (mj.get("relations") or []):
            n_rel += 1
            rel_kinds[str(rel.get("kind"))] += 1
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            if "iface_area_mm2" in z.files:
                per_asset_iface_sum.append(float(np.sum(z["iface_area_mm2"])))

    def _nums(seq):
        return np.array([float(x) for x in seq if x is not None], dtype=float)

    ic = _nums(iface_counts)
    w(f"  fracture_qa.interface_count per asset (n={ic.size}): min={int(ic.min())} "
      f"median={int(np.median(ic))} max={int(ic.max())}  sum={int(ic.sum())}")
    w(f"  relation kinds across all clean_truth: {dict(rel_kinds)}  (total relations={n_rel})")
    pa = np.array(per_asset_iface_sum, dtype=float)
    if pa.size:
        w(f"  per-asset sum(iface_area_mm2) mm^2 (n={pa.size}): min={pa.min():.2f} "
          f"median={np.median(pa):.1f} max={pa.max():.1f} sum={pa.sum():.1f}")
    g = _nums(gap_p95)
    nn = _nums(nrm_p95)
    if g.size:
        w(f"  gap_p95_mm_max (n={g.size}): max={g.max():.3e} median={np.median(g):.3e}  (tolerance 0.02 mm)")
    if nn.size:
        w(f"  normal_angle_p95_deg_max (n={nn.size}): max={nn.max():.3e} median={np.median(nn):.3e}  (tolerance 2.0 deg)")
    ca = _nums(clip_area)
    pc = _nums(pair_common)
    if ca.size:
        w(f"  interface_common_clip_area_mm2 (n={ca.size}): median={np.median(ca):.1f} max={ca.max():.1f} "
          f"sum={ca.sum():.1f}  [absent on {len(clip_area)-ca.size} assets]")
    if pc.size:
        w(f"  interface_pair_common_clip_area_mm2 (n={pc.size}): median={np.median(pc):.1f} max={pc.max():.1f}")

    # ---- 4. obs_result: are interface / rim pixels present?
    obs = [r for r in rows if r["role"] == "obs_result"]
    w("")
    w("=" * 100)
    w(f"# obs_result n={len(obs)}  -- surface_tag value histogram (rim==2) and depth semantics")
    tag_hist = collections.Counter()
    tot_px = 0
    tot_rim = 0
    st_names = collections.Counter()
    dsets = collections.Counter()
    for r in obs:
        mj = json.loads(r["meta_json"])
        for k, v in (mj.get("meta", {}).get("surface_tag_names") or {}).items():
            st_names[f"{k}={v}"] += 1
        dsets[str(mj.get("meta", {}).get("data_semantics"))] += 1
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            for vname in ("v000",):
                if f"{vname}.surface_tag" in z.files:
                    st = z[f"{vname}.surface_tag"]
                    for val, c in zip(*np.unique(st, return_counts=True)):
                        tag_hist[int(val)] += int(c)
                    tot_px += int(st.size)
                    tot_rim += int(np.count_nonzero(st == 2))
    w(f"  surface_tag_names vocabulary seen: {dict(st_names)}")
    w(f"  data_semantics values: {dict(dsets)}")
    w(f"  v000 surface_tag pixel histogram over {len(obs)} obs_result (sum px={tot_px}):")
    for k, c in sorted(tag_hist.items()):
        w(f"      tag={k:4d}  px={c:12d}  ({100.0*c/max(tot_px,1):.3f}%)")
    w(f"  RIM (tag==2 == ORIGIN_INTERFACE) pixel fraction = {100.0*tot_rim/max(tot_px,1):.4f}%")

    txt = "\n".join(L)
    (OUT / "probe_05_fracture.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
