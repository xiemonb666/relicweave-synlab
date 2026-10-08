def _face_prism_violations(mesh: Any, normals: np.ndarray, offset: np.ndarray,
                           faces: np.ndarray) -> np.ndarray:
    """Faces whose moved corners leave the face's own prism, by a closed-form 2-D test.

    For one face with corners ``v_k`` and unit normal ``n``, the moved corners are
    ``v_k - n_k d_k``.  If the **projection** of every moved corner onto the face plane stays
    inside the original triangle, no point of the moved triangle can pierce the original face: the
    triangle only slides inward through its own prism.  That is a sufficient condition for
    ``damaged ⊆ clean`` restricted to that face, and it is evaluated here in closed form (a
    barycentric sign test) rather than by point sampling, so the verdict does not depend on a
    sampling seed.

    Returns the boolean per-face mask (``True`` = the face's prism is left).
    """
    if len(faces) == 0:
        return np.zeros(0, dtype=bool)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    triangles = vertices[faces]                                        # (F, 3, 3)
    edge1 = triangles[:, 1] - triangles[:, 0]
    edge2 = triangles[:, 2] - triangles[:, 0]
    raw = np.cross(edge1, edge2)
    norm = np.linalg.norm(raw, axis=1, keepdims=True)
    norm[norm < 1e-12] = 1.0
    unit = raw / norm
    moved = triangles - normals[faces] * offset[faces][:, :, None]     # (F, 3, 3)
    e1 = edge1 / np.maximum(np.linalg.norm(edge1, axis=1, keepdims=True), 1e-12)
    e2 = np.cross(unit, e1)
    rel = moved - triangles[:, 0][:, None, :]
    a = np.einsum("fkc,fc->fk", rel, e1)
    b = np.einsum("fkc,fc->fk", rel, e2)
    zero = np.zeros(len(faces))
    A = np.stack([zero, zero], axis=1)
    B = np.stack([np.linalg.norm(edge1, axis=1), zero], axis=1)
    C = np.stack([np.einsum("fc,fc->f", edge2, e1), np.einsum("fc,fc->f", edge2, e2)], axis=1)

    def sign(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
        return ((q[:, 0] - p[:, 0]) * (r[:, 1] - p[:, 1])
                - (q[:, 1] - p[:, 1]) * (r[:, 0] - p[:, 0]))

    bad = np.zeros(len(faces), dtype=bool)
    for k in range(3):
        point = np.stack([a[:, k], b[:, k]], axis=1)
        d1 = sign(A, B, point)
        d2 = sign(B, C, point)
        d3 = sign(C, A, point)
        has_neg = (d1 < -1e-12) | (d2 < -1e-12) | (d3 < -1e-12)
        has_pos = (d1 > 1e-12) | (d2 > 1e-12) | (d3 > 1e-12)
        bad |= has_neg & has_pos
    return bad


def inward_offset_guard(mesh: Any, offset_mm: np.ndarray, *, max_rounds: int = 24,
                        min_rounds: int = 2) -> tuple[np.ndarray, dict[str, Any]]:
    """Shrink the offset of any vertex whose **faces** would leave their own prism.

    Why the guard has to look at faces, not only vertices
    ----------------------------------------------------
    The offset moves *vertices* along their own normals, but ``damaged ⊆ clean`` is a statement
    about the *surface between* them.  A vertex can be strictly inside while being a corner of a
    triangle that still reaches the original surface: measured on the real mother body
    ``LIN0000_V10_M11_PAT15`` (7936 faces, 3973 vertices, median wall 10.0 mm) at wear level 4,
    the violating triangles of the shipped ``subset_outside_stats`` sample (8-12 of 1200 samples,
    up to 0.456 mm outside) all had three very different vertex offsets — measured example
    ``1.5998 / 0.1084 / 1.5998`` mm on a 311 mm² sliver.  The interior of such a triangle stays
    where the original face was while the moved corners cut across it in plane, so a vertex-only
    guard reports zero violations while the subset check still fails.

    Instrument
    ----------
    :func:`_face_prism_violations`: a closed-form 2-D containment test per face.  A
    ``trimesh.proximity.signed_distance`` version was tried first and is the wrong instrument
    here — every face centroid of a vertex-offset body sits within ~1e-6 mm of the source surface
    by construction (measured: 667 of 2645 moved centroids reported ``sd <= 0`` while the *sampled*
    surface had only 8 real violations), so it fires on numerical noise instead of on protrusion.
    An Open3D ray test was also tried and discarded on measured grounds: casting along the face
    normal from any point of a closed mesh hits the body (measured: 19/19 known-outside centroids
    returned a finite ``t_hit`` along both ``+n`` and ``-n``), so it carries no inside/outside
    information.

    The A09 tolerance is untouched: the verdict is re-measured afterwards by
    :func:`synlab.physical.api.subset_outside_stats` at 1e-3 mm.  Offsets only ever shrink, so
    every reported wear magnitude stays an upper bound.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = _area_weighted_vertex_normals(mesh)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    offset = np.clip(np.asarray(offset_mm, dtype=np.float64).reshape(-1), 0.0, None)
    active = np.flatnonzero(offset[faces].max(axis=1) > 0) if len(faces) else np.zeros(
        0, dtype=np.int64)
    report: dict[str, Any] = {
        "instrument": "closed-form 2-D prism containment test per face "
                      "(projection of every moved corner into the original triangle)",
        "method": "halve all three vertex offsets of a violating face, repeat",
        "rounds": 0, "vertices_moved": int(np.count_nonzero(offset > 0)),
        "faces_checked": int(len(active)), "faces_violating_before": 0,
        "faces_violating_after": 0, "vertices_shrunk": 0, "max_shrink_mm": 0.0,
        "min_rounds": int(min_rounds),
    }
    if active.size == 0:
        return offset, report
    current = offset.copy()
    for round_index in range(int(max_rounds)):
        bad = _face_prism_violations(mesh, normals, current, faces[active])
        if round_index == 0:
            report["faces_violating_before"] = int(np.count_nonzero(bad))
        if round_index >= int(min_rounds) and not bool(np.any(bad)):
            report["faces_violating_after"] = 0
            report["rounds"] = round_index
            break
        if bool(np.any(bad)):
            culprits = np.unique(faces[active][bad])
            current[culprits] = 0.5 * current[culprits]
        report["rounds"] = round_index + 1
        if round_index == int(max_rounds) - 1:
            report["faces_violating_after"] = int(np.count_nonzero(bad))
    shrunk_values = current < offset - 1e-12
    report["vertices_shrunk"] = int(np.count_nonzero(shrunk_values))
    report["max_shrink_mm"] = float(np.max(offset[shrunk_values] - current[shrunk_values])) if bool(
        np.any(shrunk_values)) else 0.0
    return current, report


