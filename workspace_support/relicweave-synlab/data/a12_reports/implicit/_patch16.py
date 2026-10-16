import pathlib
p = pathlib.Path("synlab/fracture/implicit/assembler.py")
s = p.read_text(encoding="utf-8")
s = s.replace("""def _pair_points(triangles: np.ndarray, order: int = 3) -> np.ndarray:""",
"""def _canonical(triangles: np.ndarray) -> np.ndarray:
    \"\"\"Order each triangle's three vertices canonically, so two coincident triangles sample alike.

    The two sides of a shared cut carry the same clipped triangle, but their vertex *order* differs
    (the boolean is free to rotate or reflect a face).  Sampling the raw order therefore compares
    different points of the same triangle -- measured as a 0.14 mm "gap" -- while sampling the
    canonical order compares the same points, which is what a conjugate measurement means.
    \"\"\"
    tri = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    if tri.shape[0] == 0:
        return tri
    key = tri[:, :, 0] * 1.0e6 + tri[:, :, 1] * 1.0e3 + tri[:, :, 2]
    order = np.argsort(key, axis=1, kind="stable")
    return np.take_along_axis(tri, order[:, :, None], axis=1)


def _pair_points(triangles: np.ndarray, order: int = 3) -> np.ndarray:""")
s = s.replace("""        samples_a = _pair_points(tri_a, order=3)
        samples_b = _pair_points(tri_b, order=3)""",
"""        samples_a = _pair_points(_canonical(tri_a), order=3)
        samples_b = _pair_points(_canonical(tri_b), order=3)""")
p.write_text(s, encoding="utf-8")
print("canonical pairing applied")
