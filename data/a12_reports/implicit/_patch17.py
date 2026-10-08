import pathlib
p = pathlib.Path("synlab/fracture/implicit/assembler.py")
s = p.read_text(encoding="utf-8")
s = s.replace("from ..booleans import boolean_difference, boolean_intersection, mesh_hash, tag_source",
              "from ..booleans import (\n    GRAZING_NORMAL_DOT,\n    boolean_difference,\n    boolean_intersection,\n    mesh_hash,\n    tag_source,\n)")
s = s.replace('''def _classify(side: Any, *, basis: Any, h_fn: Any, mother_mesh: Any,
              on_sheet_tol: float, on_mother_tol: float) -> dict[str, Any]:
    """Per-vertex origin/source record for one boolean side (analytic cutter distance)."""
    from trimesh.proximity import closest_point, signed_distance

    points = np.asarray(side.mesh.vertices, dtype=np.float64)
    d_sheet, _local = sheet_distance(basis, h_fn, points)
    d_mother = np.abs(np.asarray(signed_distance(mother_mesh, points), dtype=np.float64))
    _closest, _distance, mother_tri = closest_point(mother_mesh, points)
    mother_tri = np.asarray(mother_tri, dtype=np.int64)
    inside = np.asarray(signed_distance(mother_mesh, points), dtype=np.float64) > 0.0
    on_sheet = d_sheet <= float(on_sheet_tol)
    on_mother = (d_mother <= float(on_mother_tol)) & inside''',
'''def sheet_normal(basis: Any, h_fn: Any, local: np.ndarray, *, step_mm: float = 1.0e-3
                 ) -> np.ndarray:
    """World normal of the implicit sheet at the given local ``(u, v, w)`` points."""
    u = np.asarray(local[:, 0], dtype=np.float64)
    v = np.asarray(local[:, 1], dtype=np.float64)
    hu = (np.asarray(h_fn(u + step_mm, v), dtype=np.float64)
          - np.asarray(h_fn(u - step_mm, v), dtype=np.float64)) / (2.0 * step_mm)
    hv = (np.asarray(h_fn(u, v + step_mm), dtype=np.float64)
          - np.asarray(h_fn(u, v - step_mm), dtype=np.float64)) / (2.0 * step_mm)
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    normals = (-hu[:, None] * matrix[0][None, :] - hv[:, None] * matrix[1][None, :]
               + matrix[2][None, :])
    length = np.linalg.norm(normals, axis=1)
    return normals / np.maximum(length[:, None], 1.0e-12)


def _classify(side: Any, *, basis: Any, h_fn: Any, mother_mesh: Any,
              on_sheet_tol: float, on_mother_tol: float) -> dict[str, Any]:
    """Per-vertex origin/source record for one boolean side (analytic cutter distance).

    The on-sheet test is the frozen one -- distance **and** normal (anti)parallel to the sheet
    (``booleans.GRAZING_NORMAL_DOT``).  Distance alone would label the mother's own wall along the
    tangent line of the sheet as interface, and it would rob those faces of their mother-triangle
    provenance (measured: source coverage 0.986 against the 0.999 floor).
    """
    from trimesh.proximity import closest_point, signed_distance

    points = np.asarray(side.mesh.vertices, dtype=np.float64)
    d_sheet, local = sheet_distance(basis, h_fn, points)
    signed_mother = np.asarray(signed_distance(mother_mesh, points), dtype=np.float64)
    d_mother = np.abs(signed_mother)
    _closest, _distance, mother_tri = closest_point(mother_mesh, points)
    mother_tri = np.asarray(mother_tri, dtype=np.int64)
    inside = signed_mother > 0.0
    vertex_normals = np.asarray(side.mesh.vertex_normals, dtype=np.float64)
    normals_sheet = sheet_normal(basis, h_fn, local)
    aligned = np.abs(np.einsum("ij,ij->i", vertex_normals, normals_sheet)) >= GRAZING_NORMAL_DOT
    on_sheet = (d_sheet <= float(on_sheet_tol)) & aligned
    on_mother = (d_mother <= float(on_mother_tol)) & inside''')
s = s.replace('''        "vertex_sheet_distance_mm": d_sheet,
        "vertex_mother_distance_mm": d_mother,''',
'''        "vertex_sheet_distance_mm": d_sheet,
        "vertex_mother_distance_mm": d_mother,
        "vertex_sheet_aligned": aligned,
        "grazing_normal_dot": float(GRAZING_NORMAL_DOT),''')
p.write_text(s, encoding="utf-8")
print("frozen grazing rule wired in")
