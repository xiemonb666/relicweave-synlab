def inward_offset_guard(mesh: Any, offset_mm: np.ndarray, *, rounds: int = 22,
                        safety: float = 0.90, tol_mm: float = 1e-3) -> tuple[
        np.ndarray, dict[str, Any]]:
    """Truncate the depth field so that **every moved vertex is really inside** the source body.

    Two independent failure modes were measured on real bodies and both have to be handled.

    1. *Face-level piercing.*  The offset moves vertices along their own normals, but
       ``damaged ⊆ clean`` is a statement about the surface between them.  On the mother body
       ``LIN0000_V10_M11_PAT15`` (7936 faces, 3973 vertices, median wall 10.0 mm) every violating
       triangle at wear level 4 had three very different corner offsets (measured example
       ``1.5998 / 0.1084 / 1.5998`` mm on a 311 mm² sliver) whose *in-plane* components slid the
       face projection off the original triangle.  Handled by :func:`_inplane_cap_mm`.
    2. *Vertex-level sign.*  A body can be a shell whose cavities are enclosed, so "inward along
       the vertex normal" is not the same as "into the material".  Measured on the same body: the
       centroid of all vertices has ``signed_distance = -62.96`` mm (i.e. it sits in a cavity), and
       50 of 2645 moved vertices landed outside by up to 0.813 mm even though their local wall
       thickness was 8.2 mm — a ray-parity test and Open3D's occupancy query both agree they are
       outside, so this is real geometry, not numerical noise.  Handled by the per-vertex bisection
       below, which uses the **same** instrument as the audit
       (``trimesh.proximity.signed_distance``, positive = inside).

    The A09 tolerance (1e-3 mm) is not touched: the verdict is re-measured afterwards by
    :func:`synlab.physical.api.subset_outside_stats`.  Offsets only ever shrink, so every reported
    wear magnitude stays an upper bound.

    Rejected instruments (measured, kept as negative evidence): an Open3D ray test along the face
    normal (casting from any point of a closed mesh hits the body — 19/19 known-outside centroids
    returned a finite ``t_hit`` along both ``+n`` and ``-n``), and ``signed_distance`` on face
    *centroids only* (every centroid of a vertex-offset body is within ~1e-6 mm of the source
    surface by construction: 667 of 2645 moved centroids reported ``sd <= 0`` while the sampled
    surface had 8-12 real violations).
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = _area_weighted_vertex_normals(mesh)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    offset = np.clip(np.asarray(offset_mm, dtype=np.float64).reshape(-1), 0.0, None)
    declared_max = float(offset.max()) if offset.size else 0.0

    # ---- stage 1: the cheap closed-form in-plane cap
    caps = _inplane_cap_mm(mesh, normals, faces)
    per_vertex_cap = np.full(len(vertices), np.inf, dtype=np.float64)
    if caps.size:
        for corner in range(3):
            np.minimum.at(per_vertex_cap, faces[:, corner], caps[:, corner])
    finite_cap = np.isfinite(per_vertex_cap)
    capped = np.where(offset > 0, np.minimum(offset, float(safety) * per_vertex_cap), 0.0)
    capped = np.clip(np.nan_to_num(capped, nan=0.0, posinf=0.0), 0.0, None)

    report: dict[str, Any] = {
        "stage_1_instrument": "closed-form in-plane cap per face corner: "
                              "d * sqrt(1 - (n_vertex . n_face)^2) < safety * inradius(face), "
                              "per-vertex minimum over incident faces",
        "stage_2_instrument": "trimesh.proximity.signed_distance(mesh, moved vertex) > 0 "
                              "(exact float64; the instrument of subset_outside_stats), "
                              "per-vertex bisection",
        "safety_factor": float(safety), "tol_mm": float(tol_mm),
        "vertices_moved": int(np.count_nonzero(offset > 0)),
        "vertices_with_finite_cap": int(np.count_nonzero(finite_cap)),
        "vertices_capped": int(np.count_nonzero((offset > 0) & (capped < offset - 1e-15))),
        "declared_max_mm": declared_max,
        "max_cap_truncation_mm": float(np.max(offset - capped)) if offset.size else 0.0,
        "vertices_outside_before_stage2": 0, "vertices_outside_after": 0,
        "rounds": 0, "applied_max_mm": float(capped.max()) if capped.size else 0.0,
        "truncated_vertices": 0, "max_truncation_mm": 0.0,
    }
    moved_indices = np.flatnonzero(capped > 0)
    if moved_indices.size == 0:
        return capped, report

    # ---- stage 2: per-vertex bisection against the audit's own instrument
    lo_f = np.zeros(moved_indices.size, dtype=np.float64)      # last known good factor
    hi_f = np.ones(moved_indices.size, dtype=np.float64)       # first known bad factor
    best = capped[moved_indices].copy()

    def outside(values: np.ndarray, indices: np.ndarray) -> np.ndarray:
        points = vertices[indices] - normals[indices] * values[:, None]
        signed = np.asarray(trimesh.proximity.signed_distance(mesh, points), dtype=np.float64)
        return signed <= float(tol_mm) * 0.5

    current = capped[moved_indices].copy()
    bad = outside(current, moved_indices)
    report["vertices_outside_before_stage2"] = int(np.count_nonzero(bad))
    hi_f[bad] = 1.0
    for round_index in range(int(rounds)):
        if not bool(np.any(bad)):
            break
        mid = 0.5 * (lo_f + hi_f)
        trial = np.where(bad, capped[moved_indices] * mid, current)
        trial_bad = np.where(bad, outside(trial, moved_indices), False)
        ok = bad & ~trial_bad
        lo_f[ok] = mid[ok]
        best[ok] = trial[ok]
        bad = bad & trial_bad
        hi_f[bad] = mid[bad]
        current = np.where(ok, best, current)
        report["rounds"] = round_index + 1
    current = np.maximum(best, 0.0)
    current[lo_f > 0] = np.maximum(current[lo_f > 0], capped[moved_indices][lo_f > 0] * lo_f[lo_f > 0])
    still = outside(current, moved_indices)
    # a vertex that cannot be placed inside at any positive depth is pinned to the source point
    current[still] = 0.0
    report["vertices_outside_after"] = int(np.count_nonzero(outside(current, moved_indices)))
    report["vertices_pinned_to_source"] = int(np.count_nonzero(still))

    applied = np.zeros(len(vertices), dtype=np.float64)
    applied[moved_indices] = current
    report["applied_max_mm"] = float(applied.max()) if applied.size else 0.0
    report["truncated_vertices"] = int(np.count_nonzero(applied < offset - 1e-15))
    report["max_truncation_mm"] = float(np.max(offset - applied)) if offset.size else 0.0
    return applied, report


