"""Read-only GLB probe: attribute lists, normal stats, primitive/node layout.

Nothing here writes; it only parses the exported display GLBs and prints measurements.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import struct
import sys

COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
             5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path: pathlib.Path) -> dict:
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67, f"bad magic in {path}"
    offset = 12
    gltf = None
    binary = b""
    while offset < length:
        clen, ctype = struct.unpack_from("<II", raw, offset)
        chunk = raw[offset + 8: offset + 8 + clen]
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            binary = chunk
        offset += 8 + clen + ((4 - clen % 4) % 4 if clen % 4 else 0)
    return {"gltf": gltf, "bin": binary, "bytes": len(raw), "version": version}


def accessor_bytes(doc: dict, binary: bytes, index: int) -> bytes:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    fmt, size = COMPONENT[acc["componentType"]]
    n = NCOMP[acc["type"]]
    stride = view.get("byteStride") or size * n
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    out = bytearray()
    for i in range(acc["count"]):
        base = start + i * stride
        out += binary[base: base + size * n]
    return bytes(out)


def summarize(path: pathlib.Path) -> dict:
    import numpy as np

    d = read_glb(path)
    doc, binary = d["gltf"], d["bin"]
    prims = []
    for mesh_i, mesh in enumerate(doc.get("meshes", [])):
        for prim_i, prim in enumerate(mesh.get("primitives", [])):
            entry = {
                "mesh": mesh_i,
                "primitive": prim_i,
                "attributes": sorted(prim.get("attributes", {})),
                "mode": prim.get("mode", 4),
                "has_material": "material" in prim,
                "material": (doc.get("materials", [])[prim["material"]]
                             if "material" in prim else None),
            }
            pos_acc = doc["accessors"][prim["attributes"]["POSITION"]]
            entry["vertices"] = pos_acc["count"]
            if "indices" in prim:
                entry["triangles"] = doc["accessors"][prim["indices"]]["count"] // 3
            else:
                entry["triangles"] = pos_acc["count"] // 3
            if "NORMAL" in prim["attributes"]:
                normals = np.frombuffer(
                    accessor_bytes(doc, binary, prim["attributes"]["NORMAL"]), dtype="<f4")
                normals = normals.reshape(-1, 3).astype(np.float64)
                lengths = np.linalg.norm(normals, axis=1)
                entry["normal_norm"] = {
                    "min": float(lengths.min()), "max": float(lengths.max()),
                    "mean": float(lengths.mean()),
                    "max_abs_dev_from_1": float(np.abs(lengths - 1.0).max()),
                }
                # per-face normal agreement: compare vertex normals within each triangle
                pos = np.frombuffer(accessor_bytes(doc, binary, prim["attributes"]["POSITION"]),
                                    dtype="<f4").reshape(-1, 3).astype(np.float64)
                if "indices" in prim:
                    idx = np.frombuffer(accessor_bytes(doc, binary, prim["indices"]),
                                        dtype="<%s" % COMPONENT[
                                            doc["accessors"][prim["indices"]]["componentType"]][0])
                else:
                    idx = np.arange(len(pos))
                tri = idx.reshape(-1, 3)
                v0, v1, v2 = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
                fn = np.cross(v1 - v0, v2 - v1 if False else v2 - v0)
                ln = np.linalg.norm(fn, axis=1, keepdims=True)
                fn = fn / np.where(ln > 0, ln, 1.0)
                vn = normals[tri]  # (F,3,3)
                dots = np.einsum("fij,fj->fi", vn, fn)
                entry["vertex_normal_vs_face_normal_deg"] = {
                    "max_mean": float(np.degrees(np.arccos(np.clip(
                        dots.mean(axis=1), -1, 1))).max()),
                    "share_within_1deg": float(np.mean(dots > np.cos(np.radians(1.0)))),
                    "share_within_30deg": float(np.mean(dots > np.cos(np.radians(30.0)))),
                    "share_within_60deg": float(np.mean(dots > np.cos(np.radians(60.0)))),
                }
            prims.append(entry)
    return {
        "path": str(path),
        "bytes": d["bytes"],
        "glb_version": d["version"],
        "extensions_used": doc.get("extensionsUsed"),
        "node_names": [n.get("name") for n in doc.get("nodes", [])],
        "materials": [{"name": m.get("name"),
                       "baseColorFactor": m.get("pbrMetallicRoughness", {}).get("baseColorFactor"),
                       "metallic": m.get("pbrMetallicRoughness", {}).get("metallicFactor"),
                       "roughness": m.get("pbrMetallicRoughness", {}).get("roughnessFactor"),
                       "has_texture": "baseColorTexture" in m.get("pbrMetallicRoughness", {})}
                      for m in doc.get("materials", [])],
        "primitives": prims,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    rows = [summarize(pathlib.Path(p)) for p in args.paths]
    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in rows:
        print("=" * 100)
        print(row["path"], f"({row['bytes']} bytes)  nodes={row['node_names']}")
        for m in row["materials"]:
            print("   material:", m)
        for p in row["primitives"]:
            print(f"   prim m{p['mesh']}/p{p['primitive']}: attrs={p['attributes']} "
                  f"verts={p['vertices']} tris={p['triangles']} material={p['has_material']}")
            if "normal_norm" in p:
                print("      normal length:", {k: round(v, 8) for k, v in p["normal_norm"].items()})
                print("      vtx-vs-face deg:", {k: round(v, 6) for k, v in
                                                 p["vertex_normal_vs_face_normal_deg"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
