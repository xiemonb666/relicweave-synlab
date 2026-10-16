"""Scratch: patch cut.py assembly to global grid coordinates."""
import pathlib
import re

path = pathlib.Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\fracture\cut.py")
text = path.read_text(encoding="utf-8")

# 1) cell_error must pass the dyadic span
old = """    def cell_error(i: int, j: int, level: int, mesh: bool = False):
        pts_ij, tris = tree.cell_triangles(i, j, level)
        u, v = _cell_uv(tree, level, pts_ij)"""
new = """    def cell_error(i: int, j: int, level: int, span: int) -> float:
        pts_ij, tris = tree.cell_triangles(i, j, level, span)
        u, v = _cell_uv(tree, level, span, pts_ij)"""
assert old in text
text = text.replace(old, new)

old = """            exact = height(samp[:, 0], samp[:, 1])
            local = float(np.max(np.abs(samp[:, 2] - exact)))
            if local > worst:
                worst, worst_tri = local, index
        if mesh:
            return worst, (pts_ij, tris, worst_tri)
        return worst"""
new = """            exact = height(samp[:, 0], samp[:, 1])
            worst = max(worst, float(np.max(np.abs(samp[:, 2] - exact))))
        return worst"""
assert old in text
text = text.replace(old, new)

old = """            cells_tested += 1
            if cell_error(i, j, level) > max_over:"""
new = """            cells_tested += 1
            if cell_error(i, j, level, leaf_span_for(level)) > max_over:"""
assert old in text
text = text.replace(old, new)

# 2) replace the whole assembly block
start = text.index("    # ---------------------------------------------------------------- assemble")
end = text.index("    verts = np.asarray(vertices, dtype=np.float64)")
assert start < end
head, rest = text[:start], text[end:]

assembly = '''    # ---------------------------------------------------------------- assemble
    key_level = max(leaf_level, tree.level + 1)
    top_index: dict[tuple[int, int], int] = {}
    bottom_index: dict[tuple[int, int], int] = {}
    vertices: list[tuple[float, float, float]] = []

    def top_vertex(level: int, gi: int, gj: int) -> int:
        key = (gi, gj)
        found = top_index.get(key)
        if found is None:
            u, v = _cell_uv(tree, level, key_level - level,
                            np.array([[gi, gj]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
            top_index[key] = found
        return found

    def bottom_vertex(gi: int, gj: int) -> int:
        key = (gi, gj)
        found = bottom_index.get(key)
        if found is None:
            found = len(vertices)
            vertices.append((u0 + gi * cap_hx, v0 + gj * cap_hy, float(w_min - depth_margin)))
            bottom_index[key] = found
        return found

    top_faces: list[tuple[int, int, int]] = []
    for i, j, level in leaves:
        pts_ij, tris = tree.cell_triangles(i, j, level, leaf_span_for(level))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pts_ij]
        for tri in tris:
            top_faces.append((int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]])))

    side_faces: list[tuple[int, int, int]] = []
    for (i, j, level, orient, lo, split) in sorted(boundary_preview):
        span = leaf_span_for(level)
        step = 1 << span
        half = 1 << (span - 1)
        base_i, base_j = i * step, j * step
        subs = [(0, 0), (0, half)] if split else [(0, 0)]
        if orient == "v":
            ii = base_i if lo else base_i + step
            for offset, _unused in subs:
                j0 = base_j + offset
                j1 = base_j + offset + half
                a = top_vertex(level, ii, j0)
                b = top_vertex(level, ii, j1)
                ba = bottom_vertex(ii >> span, j0 >> span)
                bb = bottom_vertex(ii >> span, j1 >> span)
                if lo:
                    side_faces.append((a, b, bb))
                    side_faces.append((a, bb, ba))
                else:
                    side_faces.append((b, a, ba))
                    side_faces.append((b, ba, bb))
        else:
            jj = base_j if lo else base_j + step
            for offset, _unused in subs:
                i0 = base_i + offset
                i1 = base_i + offset + half
                a = top_vertex(level, i0, jj)
                b = top_vertex(level, i1, jj)
                ba = bottom_vertex(i0 >> span, jj >> span)
                bb = bottom_vertex(i1 >> span, jj >> span)
                if lo:
                    side_faces.append((b, a, ba))
                    side_faces.append((b, ba, bb))
                else:
                    side_faces.append((a, b, bb))
                    side_faces.append((a, bb, ba))

    cap_faces: list[tuple[int, int, int]] = []
    cap_side = 1 << cap_level
    for ci in range(cap_side):
        for cj in range(cap_side):
            a = bottom_vertex(ci, cj)
            b = bottom_vertex(ci + 1, cj)
            c = bottom_vertex(ci + 1, cj + 1)
            d = bottom_vertex(ci, cj + 1)
            cap_faces.append((a, d, c))
            cap_faces.append((a, c, b))

'''
text = head + assembly + rest

# 3) the verification loop also needs the span
old = """    realized, top_checked = 0.0, 0
    for i, j, level in leaves:
        local, tris = cell_pointers[(i, j, level)]
        pts = verts[local]
        for tri in tris:"""
new = """    realized, top_checked = 0.0, 0
    for i, j, level in leaves:
        pts_ij, tris = tree.cell_triangles(i, j, level, leaf_span_for(level))
        pts = np.asarray([verts[top_index[(int(p[0]), int(p[1]))]] for p in pts_ij],
                         dtype=np.float64)
        for tri in tris:"""
assert old in text
text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("assembly patched")
