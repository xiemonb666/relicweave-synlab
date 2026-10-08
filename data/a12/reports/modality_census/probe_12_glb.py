"""Probe 12: parse the REAL GLB binaries in data/a12_demo/store -- primitives, materials,
accessors (normals/UV), scene nodes (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, struct, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
STORE = ROOT / "data" / "a12_demo" / "store"


def read_glb_json(p: Path) -> dict | None:
    data = p.read_bytes()
    if data[:4] != b"glTF":
        return None
    ver, total = struct.unpack_from("<II", data, 4)
    off = 12
    while off < min(total, len(data)):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        if ctype == 0x4E4F534A:  # JSON
            return json.loads(data[off:off + clen].decode("utf-8"))
        off += clen
    return None


def main() -> None:
    con = sqlite3.connect(f"file:{(STORE/'metadata.sqlite').as_posix()}?mode=ro&immutable=1",
                          uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select asset_id, meta_json, files_json, qa_status from assets "
        "where role='display_lod_glb'").fetchall()
    con.close()
    L = []
    w = L.append
    w(f"# probe_12 GLB binaries in {STORE}   n(display_lod_glb assets)={len(rows)}")
    w("")
    mat_names = collections.Counter()
    prim_counts = collections.Counter()
    attr_sets = collections.Counter()
    node_counts = collections.Counter()
    tex_counts = collections.Counter()
    has_uv = 0
    has_normal = 0
    n_parsed = 0
    n_missing = 0
    split_ok = 0
    n_split = 0
    tri_tot = 0
    per_asset = []
    for r in rows:
        fj = json.loads(r["files_json"] or "{}")
        rel = fj.get("glb")
        p = STORE / rel if rel else None
        if p is None or not p.exists():
            n_missing += 1
            continue
        g = read_glb_json(p)
        if g is None:
            n_missing += 1
            continue
        n_parsed += 1
        mj = json.loads(r["meta_json"] or "{}")
        mats = [m.get("name") for m in (g.get("materials") or [])]
        for m in mats:
            mat_names[str(m)] += 1
        prims = []
        for mesh in (g.get("meshes") or []):
            for pr in (mesh.get("primitives") or []):
                prims.append(pr)
        prim_counts[len(prims)] += 1
        for pr in prims:
            attr_sets[tuple(sorted((pr.get("attributes") or {}).keys()))] += 1
            if "NORMAL" in (pr.get("attributes") or {}):
                has_normal += 1
            if "TEXCOORD_0" in (pr.get("attributes") or {}):
                has_uv += 1
        node_counts[len(g.get("nodes") or [])] += 1
        tex_counts[len(g.get("textures") or [])] += 1
        tri = 0
        for pr in prims:
            acc = g["accessors"][pr["indices"]]
            tri += int(acc["count"]) // 3
        tri_tot += tri
        prim_mats = sorted({g["materials"][pr["material"]].get("name") for pr in prims
                            if "material" in pr})
        is_split = set(prim_mats) >= {"synlab_display_new_fracture_surface",
                                      "synlab_display_original_surface"}
        if "surface_groups" in mj:
            n_split += 1
            if is_split:
                split_ok += 1
        per_asset.append((r["asset_id"], mj.get("label"), len(prims), tri, prim_mats,
                          len(g.get("nodes") or []), len(g.get("textures") or [])))
    w(f"  GLB files parsed = {n_parsed}; missing/unparseable = {n_missing}")
    w(f"  total triangles across all GLB = {tri_tot}")
    w("")
    w(f"  material names used: {dict(mat_names)}")
    w(f"  primitives per GLB: {dict(prim_counts)}")
    w(f"  scene node counts per GLB: {dict(node_counts)}")
    w(f"  texture counts per GLB: {dict(tex_counts)}")
    w(f"  primitives carrying NORMAL = {has_normal}; carrying TEXCOORD_0 (UV) = {has_uv}")
    w(f"  attribute sets: {dict(attr_sets)}")
    w(f"  assets whose meta declares `surface_groups` = {n_split}; of those, GLB really has "
      f"BOTH fracture/mother primitives = {split_ok}")
    w("")
    w("  first 14 assets: asset_id, label, n_primitives, triangles, primitive material names, "
      "n_nodes, n_textures")
    for x in per_asset[:14]:
        w(f"    {x[0]} {str(x[1])[:58]:58s} prims={x[2]} tri={x[3]:6d} nodes={x[5]} tex={x[6]} "
          f"mats={x[4]}")

    txt = "\n".join(L)
    (OUT / "probe_12_glb.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
