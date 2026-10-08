import pathlib
p = pathlib.Path("synlab/fracture/implicit/assembler.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''    stage = time.time()
    patches = _pair_interfaces(''',
'''    _repair_mother_sources(fragments, mother_mesh)

    stage = time.time()
    patches = _pair_interfaces(''')
s = s.replace('''def _pair_interfaces(''',
'''def _repair_mother_sources(fragments: list[Any], mother_mesh: Any) -> dict[str, int]:
    """Give faces that *are* on the mother's surface but carry no source id their nearest triangle.

    ``fragment._majority_source`` breaks a three-way tie towards the smallest value, so a mother
    face that has two mother vertices and one sheet vertex (the first ring of wall triangles along
    the cut) votes ``-1`` and is counted as unmapped -- measured as source coverage 0.986 against
    the frozen 0.999 floor.  The origin of those faces is ``MOTHER_SURFACE`` and their distance to
    the mother is ~0, so the nearest mother triangle is their provenance, exactly as the frozen
    resolver defines it; nothing else is touched.
    """
    from trimesh.proximity import closest_point

    repaired: dict[str, int] = {}
    for fragment in fragments:
        origin = np.asarray(fragment.face_origin_kind)
        source = np.asarray(fragment.face_source_tri, dtype=np.int64).copy()
        need = (origin == ORIGIN_MOTHER_SURFACE) & (source < 0)
        if not bool(np.any(need)):
            continue
        centroids = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[need]
        _closest, _distance, tri = closest_point(mother_mesh, centroids)
        source[need] = np.asarray(tri, dtype=np.int64)
        fragment.face_source_tri = source.astype(np.int32)
        with_face_attrs(fragment.mesh, source_triangle=fragment.face_source_tri)
        fragment.meta["source_tri_per_face"] = source
        fragment.meta["source_repaired_faces"] = int(np.sum(need))
        repaired[fragment.fragment_id] = int(np.sum(need))
    return repaired


def _pair_interfaces(''')
p.write_text(s, encoding="utf-8")
print("mother-source repair added")
