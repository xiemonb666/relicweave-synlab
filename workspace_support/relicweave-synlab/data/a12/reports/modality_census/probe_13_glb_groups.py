"""Probe 13: GLB material-group combos + texture/UV bake details + LOD completeness (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, struct, collections
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
STORE = ROOT / "data" / "a12_demo" / "store"


def read_glb(p: Path) -> dict | None:
    data = p.read_bytes()
    if data[:4] != b"glTF":
        return None
    off = 12
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        if ctype == 0x4E4F534A:
            return json.loads(data[off:off + clen].decode("utf-8"))
        off += clen
    return None


def main() -> None:
    con = sqlite3.connect(f"file:{(STORE/'metadata.sqlite').as_posix()}?mode=ro&immutable=1",
                          uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select asset_id, meta_json, files_json, unit, frame "
                       "from assets where role='display_lod_glb'").fetchall()
    con.close()
    L = []
    w = L.append
    w(f"# probe_13 GLB group combinations / UV bake / LOD completeness  (n={len(rows)})")
    w("")
    unit_frame = collections.Counter()
    combo = collections.Counter()
    lod_keys = collections.Counter()
    lod_L0 = collections.Counter()
    lod_L1 = collections.Counter()
    lod_L2 = collections.Counter()
    notes = collections.Counter()
    bake_assets = 0
    uv_assets = 0
    normals_meta = 0
    raster_assets = 0
    KINDS = collections.Counter()
    for r in rows:
        mj = json.loads(r["meta_json"] or "{}")
        unit_frame[(r["unit"], r["frame"])] += 1
        if mj.get("label"):
            KINDS[str(mj["label"]).split(":")[0] + ":" +
                  (str(mj["label"]).split(":")[1] if ":" in str(mj["label"]) else "")] += 1
        fj = json.loads(r["files_json"] or "{}")
        p = STORE / fj["glb"]
        g = read_glb(p)
        mats = tuple(sorted({str(g["materials"][pr["material"]].get("name"))
                              if "material" in pr else "<no-material>"
                              for mesh in g.get("meshes", []) for pr in mesh.get("primitives", [])}))
        combo[mats] += 1
        lv = mj.get("lod_levels") or {}
        lod_keys[tuple(sorted(lv))] += 1
        for k in ("L0", "L1", "L2"):
            if k in lv:
                (lod_L0 if k == "L0" else lod_L1 if k == "L1" else lod_L2)[
                    "present"] += 1
            else:
                (lod_L0 if k == "L0" else lod_L1 if k == "L1" else lod_L2)["absent"] += 1
        for n in (mj.get("lod_notes") or []):
            if "skipped" in n:
                notes[n.split(":")[0] + " : " + n.split(":", 1)[1][:60]] += 1
            elif "measured only" in n:
                notes["L1/L2 measured only (not exported as scene nodes)"] += 1
            else:
                notes[n[:70]] += 1
        if "bake" in mj:
            bake_assets += 1
        if "uv" in mj:
            uv_assets += 1
        if "normals" in mj:
            normals_meta += 1
        if "raster_asset" in mj:
            raster_assets += 1
    w(f"  (unit, frame) of display_lod_glb = {dict(unit_frame)}")
    w("")
    w("  MATERIAL-GROUP COMBINATIONS actually present in the GLB binaries:")
    for k, v in combo.most_common():
        w(f"      {v:4d}  {list(k)}")
    w("")
    w(f"  LOD level keys present: {dict(lod_keys)}")
    w(f"  L0 presence: {dict(lod_L0)}   L1: {dict(lod_L1)}   L2: {dict(lod_L2)}")
    w("")
    w("  lod_notes histogram:")
    for k, v in notes.most_common(30):
        w(f"      {v:4d}  {k}")
    w("")
    w(f"  assets with a texture 'bake' block = {bake_assets}")
    w(f"  assets with a 'uv' block          = {uv_assets}")
    w(f"  assets with a 'normals' block     = {normals_meta}")
    w(f"  assets with 'raster_asset'        = {raster_assets}")
    w(f"  asset kinds (label prefix): {dict(KINDS)}")
    txt = "\n".join(L)
    (OUT / "probe_13_glb_groups.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
