"""Independent, read-only run05 geometry/serialization/source-area acceptance."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vesselforge/src"))
from vesselforge.revolved_profile import MeridianSegment


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    run = ROOT / "vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05"
    folder = run / "partition_output"
    source = ROOT / "vesselforge/experiments/continuation_20261015/reference_forms/outputs/daily_aberdeen_108x53_v6_final/geometry"
    receipt = json.loads((run / "audit_receipt.json").read_text())
    result = json.loads((folder / "result.json").read_text())
    assert sha(folder / "result.json") == receipt["result_sha256"]
    for name, rec in result["files"].items():
        assert (folder / name).stat().st_size == rec["bytes"]
        assert sha(folder / name) == rec["sha256"]
    for name in ("section.json", "face_lineage.json", "solid.step"):
        assert sha(source / name) == receipt["input_hashes"][name]
    with np.load(folder / "mesh.npz", allow_pickle=False) as z:
        a = {key: z[key] for key in z.files}
    x, t = a["nodes_m"], a["tets"]
    assert x.shape == (25748, 3) and t.shape == (86624, 4)
    assert np.isfinite(x).all() and t.min() >= 0 and t.max() < len(x)
    p = x[t]
    volumes = np.einsum("ij,ij->i", p[:, 1]-p[:, 0],
                        np.cross(p[:, 2]-p[:, 0], p[:, 3]-p[:, 0])) / 6
    assert (volumes > 0).all()
    np.testing.assert_allclose(volumes, a["volume_m3"], rtol=2e-14, atol=1e-25)

    # Source IDs, rather than row positions, bind two independently serialized formats.
    lines = (folder / "mesh.msh").read_text().splitlines()
    ni, ei = lines.index("$Nodes"), lines.index("$Elements")
    nn, ne = int(lines[ni+1]), int(lines[ei+1])
    native_node_records = [line.split() for line in lines[ni+2:ni+2+nn]]
    msh_tags = np.array([int(row[0]) for row in native_node_records])
    msh_xyz = np.array([[float(v) for v in row[1:]] for row in native_node_records])
    npz_by_tag = {int(tag): row for row, tag in enumerate(a["original_node_tags"])}
    assert len(npz_by_tag) == len(x) and len(set(msh_tags)) == len(msh_tags)
    msh_to_npz = np.array([npz_by_tag[int(tag)] for tag in msh_tags])
    coordinate_delta = np.abs(msh_xyz-x[msh_to_npz])
    # Gmsh ASCII uses fewer decimal digits than the binary NPZ. Source IDs
    # establish identity; this check only verifies serialization accuracy.
    np.testing.assert_allclose(msh_xyz, x[msh_to_npz], rtol=8e-16, atol=1e-30)
    tet_by_tag = {int(tag): row for row, tag in enumerate(a["original_cell_tags"])}
    seen_tets, msh_triangles = set(), []
    for line in lines[ei+2:ei+2+ne]:
        fields = [int(v) for v in line.split()]
        tag, kind, nmeta = fields[:3]
        corners = fields[3+nmeta:]
        if kind == 4:
            row = tet_by_tag[tag]
            np.testing.assert_array_equal(corners, a["original_node_tags"][t[row]])
            seen_tets.add(row)
        elif kind == 2:
            msh_triangles.append(tuple(sorted(npz_by_tag[v] for v in corners)))
    assert len(seen_tets) == len(t)
    used = np.unique(t)
    assert set(msh_to_npz) == set(used) and nn == 25579
    unused = np.setdiff1d(np.arange(len(x)), used)
    assert len(unused) == 169

    # Independent face incidence, parent IDs, interface completeness and outward winding.
    local_faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    faces = np.sort(t[:, local_faces].reshape(-1, 3), axis=1)
    unique, inverse, counts = np.unique(faces, axis=0, return_inverse=True, return_counts=True)
    assert counts.max() == 2
    face_id = {tuple(face): i for i, face in enumerate(unique)}
    parent_lists = [[] for _ in unique]
    for flat, face in enumerate(inverse):
        parent_lists[int(face)].append(flat // 4)
    exterior = a["exterior_triangles"]
    interface = a["interface_triangles"]
    exterior_keys = {tuple(sorted(face)) for face in exterior}
    interface_keys = {tuple(sorted(face)) for face in interface}
    assert len(exterior_keys) == 44182 and len(interface_keys) == 356
    assert exterior_keys == {tuple(face) for face in unique[counts == 1]}
    cross_partition = set()
    for face, parents in zip(unique, parent_lists):
        if len(parents) == 2 and a["source_partition_volume"][parents[0]] != a["source_partition_volume"][parents[1]]:
            cross_partition.add(tuple(face))
    assert interface_keys == cross_partition
    for face, parents in zip(interface, a["interface_parents"]):
        assert set(map(int, parents)) == set(parent_lists[face_id[tuple(sorted(face))]])
        assert len(set(a["source_partition_volume"][parents])) == 2
    assert set(msh_triangles) == exterior_keys | interface_keys
    tri = x[exterior]
    normals = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    parent = np.array([parent_lists[face_id[tuple(sorted(face))]][0] for face in exterior])
    assert (np.einsum("ij,ij->i", normals, x[t[parent]].mean(axis=1)-tri.mean(axis=1)) < 0).all()
    surface_volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()/6)
    assert abs(surface_volume-volumes.sum()) < 1e-17
    area = np.linalg.norm(normals, axis=1)/2
    heights = []
    for face in local_faces:
        q = p[:, face]
        face_area = np.linalg.norm(np.cross(q[:, 1]-q[:, 0], q[:, 2]-q[:, 0]), axis=1)/2
        heights.append(3*volumes/face_area)
    minimum_height = np.min(heights, axis=0)

    section = json.loads((source / "section.json").read_text())
    lineage = json.loads((source / "face_lineage.json").read_text())["faces"]
    xi, wi = np.polynomial.legendre.leggauss(128)
    tt, ww = (xi+1)/2, wi/2
    cad_area, cad_volume = [], []
    for rec in section["segments"]:
        curve = MeridianSegment(role=rec["role"], kind=rec["curve"],
                                points=tuple(tuple(v) for v in rec["points_rz_mm"]))
        cp = np.array([curve.point(float(v)) for v in tt])
        cd = np.array([curve.derivative(float(v)) for v in tt])
        cad_area.append(2*np.pi*np.sum(ww*cp[:, 0]*np.linalg.norm(cd, axis=1))*1e-6)
        cad_volume.append(2*np.pi/3*np.sum(ww*cp[:, 0]*(cp[:, 1]*cd[:, 0]-cp[:, 0]*cd[:, 1]))*1e-9)
    cad_area, cad_volume = np.asarray(cad_area), np.asarray(cad_volume)
    fid_rows = []
    assert a["exterior_ancestry_exact"].all()
    for key, rec in lineage.items():
        fid = f"original-brep-face-{int(key):03d}"
        mask = a["exterior_source_face_ids"] == fid
        assert mask.any() and (a["exterior_roles"][mask] == rec["role"]).all()
        ca = float(cad_area[rec["source_segment_indices"]].sum())
        fid_rows.append({"fid": fid, "role": rec["role"], "triangle_count": int(mask.sum()),
                         "source_area_m2": ca, "mesh_area_m2": float(area[mask].sum()),
                         "relative_area_error": float(area[mask].sum()/ca-1)})
    assert len(set(a["exterior_source_face_ids"])) == len(lineage) == 16
    volume_error = abs(volumes.sum()/cad_volume.sum()-1)
    assert volume_error < .01
    output = {
        "status": "ROOT_INDEPENDENT_V6_RUN05_GEOMETRY_READBACK_PASS",
        "source_section_sha256": sha(source / "section.json"),
        "source_lineage_sha256": sha(source / "face_lineage.json"),
        "msh_sha256": sha(folder / "mesh.msh"), "npz_sha256": sha(folder / "mesh.npz"),
        "audit_receipt_sha256": sha(run / "audit_receipt.json"),
        "npz_nodes": len(x), "msh_nodes": nn, "unused_npz_nodes": len(unused),
        "unused_npz_original_node_tags": a["original_node_tags"][unused].tolist(),
        "serialization_scope": "MSH contains exactly T4-referenced NPZ nodes; correspondence is verified by original tags and exact ordered cell corners. ASCII coordinates use a declared 8e-16 relative / 1e-30 m absolute round-trip tolerance, not exact binary equality.",
        "msh_npz_coordinate_max_absolute_error_m": float(coordinate_delta.max()),
        "msh_npz_coordinate_roundtrip_rtol": 8e-16,
        "msh_npz_coordinate_roundtrip_atol_m": 1e-30,
        "tetrahedra": len(t), "exterior_triangles": len(exterior), "interface_triangles": len(interface),
        "source_quadrature_volume_m3": float(cad_volume.sum()), "mesh_volume_m3": float(volumes.sum()),
        "mesh_surface_volume_m3": surface_volume, "cad_mesh_relative_volume_error": float(volume_error),
        "min_p1_median_altitude_m": np.quantile(minimum_height, [0, .01, .5]).tolist(),
        "per_fid_area": fid_rows,
        "scope": "Geometry/serialization/source mapping acceptance only. Foot fillet area errors remain visible. No source-shape fidelity, calibrated material, evolution, fracture or training qualification."
    }
    with Path(__file__).with_suffix(".json").open("x", encoding="utf-8") as stream:
        json.dump(output, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: val for key, val in output.items() if key not in ("per_fid_area", "unused_npz_original_node_tags")}, indent=2))


if __name__ == "__main__":
    main()
