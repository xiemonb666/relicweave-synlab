import pathlib
p = pathlib.Path("synlab/fracture/implicit/backend.py")
s = p.read_text(encoding="utf-8")
s = s.replace("""    world = _sheet_to_world(basis, sheet)
    stage = time.time()
    vertices, faces, closure = close_sheet(world, sheet.faces, bottom_w=bottom_w)
    timings["closure_seconds"] = timings.get("closure_seconds", 0.0) + (time.time() - stage)""",
"""    # The closure happens in the *cut basis* frame: the flat bottom is ``w = bottom_w`` there, not
    # a horizontal plane in world coordinates.  Extruding along world z instead (the first revision)
    # cut a near-vertical plane's mother with a horizontal slab, which produced a third fragment and
    # a 0.14 mm conjugate gap -- measured, then fixed here.
    local_top = np.column_stack([sheet.uv, sheet.heights])
    stage = time.time()
    local_vertices, faces, closure = close_sheet(local_top, sheet.faces, bottom_w=bottom_w)
    vertices = _local_to_world(basis, local_vertices)
    timings["closure_seconds"] = timings.get("closure_seconds", 0.0) + (time.time() - stage)""")
s = s.replace('''def _sheet_to_world(basis: Any, sheet: Any) -> np.ndarray:
    """``(u, v, h)`` lattice -> world mm using the cut basis (same frame as the plane cutter)."""
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    local = np.column_stack([sheet.uv, sheet.heights])
    return local @ matrix + np.asarray(basis.origin, dtype=np.float64)[None, :]''',
'''def _local_to_world(basis: Any, local: np.ndarray) -> np.ndarray:
    """``(u, v, w)`` in the cut basis -> world mm (the frame the plane cutter also works in)."""
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    return (np.asarray(local, dtype=np.float64) @ matrix
            + np.asarray(basis.origin, dtype=np.float64)[None, :])''')
p.write_text(s, encoding="utf-8")
print("closure now happens in the cut basis frame")
