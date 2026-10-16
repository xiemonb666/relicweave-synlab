"""One-shot atomic patch for synlab/fracture/cut.py (level/lattice corrections)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

PATH = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\fracture\cut.py")
src = PATH.read_text(encoding="utf-8")
orig = src
applied: list[str] = []


def rep(old: str, new: str, tag: str) -> None:
    global src
    if new in src and old not in src:
        applied.append(f"{tag}: already")
        return
    if old not in src:
        print(f"!! MISS {tag}", file=sys.stderr)
        return
    src = src.replace(old, new, 1)
    applied.append(f"{tag}: patched")


# ------------------------------------------------------------------ constructor
rep(
    """        #: dyadic level of the root grid.  ``root_level``/``side``/``hx``/``hy`` describe the
        #: grid the stored cell indices live on and never change, so a level-``l`` cell always
        #: measures ``hx / 2 ** l``.
        self.root_level = int(root_level)
        #: how many times the whole grid has been re-rooted by :meth:`refine_all_to`.  Cells
        #: keep their indices across a re-rooting, so the *true* dyadic level of a stored
        #: cell is ``grid_level + level`` — only the key lattice needs that number.
        self.grid_level = 0
        self.side = 1 << self.root_level""",
    """        #: absolute dyadic level of the root grid.  A stored cell ``(i, j, level)`` covers
        #: ``side >> level`` slots of that same root grid, so its true dyadic level is
        #: ``root_level + level`` and its edge is ``hx / 2 ** level``.
        self.root_level = int(root_level)
        self.side = 1 << self.root_level""",
    "constructor",
)
rep(
    """        #: how many times the whole grid has been re-rooted by :meth:`refine_all_to`.  Cells
        #: keep their indices across a re-rooting, so the *true* dyadic level of a stored
        #: cell is ``grid_level + level`` — only the key lattice needs that number.
        self.grid_level = 0
""",
    "",
    "constructor-grid-level",
)

# ------------------------------------------------------------------ cell_size docstring
rep(
    """        ``hx``/``hy`` are the root grid's cell size and ``side`` its resolution; a cell at
        ``level`` is ``2 ** level`` times smaller.  ``root_level`` is only the dyadic level of
        that root grid: it is *not* used here, because using it would silently rescale every
        cell the moment the grid is refined and the shared key lattice would stop matching
        the cell lattices.
        \"\"\"""",
    """        ``hx``/``hy`` are the root grid's cell size and ``side`` its resolution; a stored
        cell at ``level`` is ``2 ** level`` times smaller.  ``root_level`` is only the dyadic
        level of that root grid and is deliberately *not* used here: using it would silently
        rescale every cell the moment the grid is refined, and the shared key lattice would
        stop matching the cell lattices.
        \"\"\"""",
    "cell_size-doc",
)

# ------------------------------------------------------------------ absolute_level + key_span
rep(
    """    #: absolute dyadic level of a relative ``level`` cell (re-rootings + subdivisions)
    def absolute_level(self, level: int) -> int:
        return self.grid_level + int(level)

    def key_span(self, level: int, key_level: int) -> int:
        \"\"\"Halvings between a stored cell's own indexes and the shared key grid.

        A cell's local index unit is ``cell_size(level) / 2 ** span`` and one single key grid
        is shared by every generation exactly when that unit is the same for them all.  With
        ``cell_size(level) = hx / 2 ** level`` and ``hx = extent / side`` this means
        ``span = key_level - level``: the key grid is measured on the *stored* index grid, so
        neither ``root_level`` nor the re-rooting counter may enter here.
        \"\"\"
        span = int(key_level) - int(level)
        if span < 1:
            raise SynLabError(
                ErrorCode.PRECISION_NOT_REALIZED,
                f"cell level {level} reaches the key level {key_level}: no headroom left to "
                f"share vertices between generations",
                stage="fracture.cut.key_span",
                measurements={"level": int(level), "key_level": int(key_level),
                              "side": int(self.side)},
            )
        return span""",
    """    #: absolute dyadic level of a stored ``level`` cell (root grid level + subdivisions)
    def absolute_level(self, level: int) -> int:
        return self.root_level + int(level)

    def key_span(self, level: int, key_level: int) -> int:
        \"\"\"Halvings between a stored cell's own indexes and the shared key grid.

        A cell's local index unit is ``cell_size(level) / 2 ** span``; ``key_level`` is the
        *absolute* dyadic level of the key grid, so one shared key lattice follows from
        ``span = key_level - (root_level + level)``.  Dropping the root level here (or using a
        refinement counter instead) silently misaligns shared vertices between generations.
        \"\"\"
        span = int(key_level) - self.absolute_level(level)
        if span < 1:
            raise SynLabError(
                ErrorCode.PRECISION_NOT_REALIZED,
                f"cell level {level} reaches the key level {key_level}: no headroom left to "
                f"share vertices between generations",
                stage="fracture.cut.key_span",
                measurements={"level": int(level), "key_level": int(key_level),
                              "root_level": int(self.root_level)},
            )
        return span""",
    "key_span",
)

# ------------------------------------------------------------------ refine_uniform_to
rep(
    """    def refine_all_to(self, target_level: int) -> None:
        \"\"\"Refine every current leaf until the tree is uniform at relative ``target_level``.

        Refining the whole tree once moves every stored cell exactly one level deeper, so
        ``grid_level`` advances and the whole index set is relabelled by ``level - 1``.  Stored
        levels therefore always stay relative to the *current* root grid (``cell_size`` stays
        exact), while ``absolute_level`` still reports the true dyadic level.  A loop that
        only marked cells never terminated; one that advances a counter without relabelling
        silently makes every cell ``2 ** k`` too large.
        \"\"\"
        level_cap = self.grid_level + 30
        while self.grid_level < target_level:
            if self.grid_level >= level_cap:  # pragma: no cover - defensive
                raise SynLabError(
                    ErrorCode.PRECISION_BUDGET_EXCEEDED,
                    f"quadtree seeding did not advance past level {self.grid_level}",
                    stage="fracture.cut.refine_all_to",
                    measurements={"grid_level": int(self.grid_level),
                                  "target_level": int(target_level)},
                )
            for i, j, level in self.leaves():
                self.refined.add((i, j, level))
            if self.refined:
                self.refined = {(i // 2, j // 2, level - 1) for i, j, level in self.refined}
            self.grid_level += 1""",
    """    def refine_uniform_to(self, absolute_level: int) -> None:
        \"\"\"Refine every current leaf until the tree is uniform at ``absolute_level``.

        Refining the whole tree once moves every stored cell exactly one level deeper and
        doubles the resolution, so the stored indices are relabelled by ``(i, j, level) ->
        (i // 2, j // 2, level - 1)``.  That keeps a stored cell's edge exactly ``hx / 2 **
        level`` while its *absolute* dyadic level is ``root_level + level``.  A loop that only
        marked cells never terminated; one that advances a counter without relabelling makes
        every cell ``2 ** k`` too large.
        \"\"\"
        level_cap = self.root_level + 40
        while self.root_level < int(absolute_level):
            if self.root_level >= level_cap:  # pragma: no cover - defensive
                raise SynLabError(
                    ErrorCode.PRECISION_BUDGET_EXCEEDED,
                    f"quadtree seeding did not advance past absolute level {self.root_level}",
                    stage="fracture.cut.refine_uniform_to",
                    measurements={"root_level": int(self.root_level),
                                  "target_level": int(absolute_level)},
                )
            for i, j, level in self.leaves():
                self.refined.add((i, j, level))
            if self.refined:
                self.refined = {(i // 2, j // 2, level - 1) for i, j, level in self.refined}
            self.root_level += 1""",
    "refine_uniform_to",
)

# ------------------------------------------------------------------ sampling floor
rep(
    """_EPS = 1.0e-12
_MIN_FRAME_MARGIN_CELLS = 1""",
    """_EPS = 1.0e-12
#: Minimum samples per shortest wavelength for the shared surface (plan 10.1: "0.2 mm
#: wavelength needs about 0.025 mm spacing", i.e. eight points per wavelength).  A linear
#: interpolant cannot resolve a sinusoid that a cell spans several times, so this is a
#: necessary condition on its own, independent of the curvature bound.
POINTS_PER_WAVELENGTH = 8.0
_MIN_FRAME_MARGIN_CELLS = 1""",
    "points-per-wavelength",
)

# ------------------------------------------------------------------ _cell_uv
rep(
    """def _cell_uv(tree: _Quadtree, level: int, span: int,
             grid_ij: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    \"\"\"Map global dyadic integer coordinates to world (u, v).

    ``span`` is the number of halvings between the cell's own index grid and the *key* grid
    (see :meth:`_Quadtree.key_span`): a key unit is ``cell_size(level) / 2 ** span`` wide and
    is the same world length for every cell generation, which is what lets one vertex be
    identified by one integer pair no matter which leaf created it.
    \"\"\"
    hx, hy = tree.cell_size(level)
    step_u = hx / float(1 << span)
    step_v = hy / float(1 << span)
    return tree.u0 + grid_ij[:, 0] * step_u, tree.v0 + grid_ij[:, 1] * step_v""",
    """def _cell_uv(tree: _Quadtree, level: int, span: int,
             grid_ij: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    \"\"\"Map global key-grid indices to world ``(u, v)``.

    ``grid_ij`` rows come from :meth:`_Quadtree.cell_triangles`, which already scales a cell's
    local indices by ``2 ** span`` and adds its origin, so a key unit is the same world length
    for every generation and two cells share a pair exactly when they share a world point.
    \"\"\"
    key_level = tree.root_level + int(level) + int(span)
    step_u = tree.hx / float(1 << key_level)
    step_v = tree.hy / float(1 << key_level)
    return tree.u0 + grid_ij[:, 0] * step_u, tree.v0 + grid_ij[:, 1] * step_v""",
    "_cell_uv",
)

# ------------------------------------------------------------------ seeding call site
rep(
    """        # The seed takes the finer of the two; the verified fixed point below still has to
        # confirm every single cell against the analytic h.  ``start_level`` is expressed on
        # the tree's *absolute* dyadic scale and mapped onto the stored grid by
        # ``refine_all_to``.""",
    """        # The seed takes the finer of the two; the verified fixed point below still has to
        # confirm every single cell against the analytic h.  ``start_level`` is an *absolute*
        # dyadic level and ``refine_uniform_to`` maps it onto the stored grid.""",
    "seed-doc",
)
rep("    tree.refine_all_to(start_level)", "    tree.refine_uniform_to(start_level)", "seed-call")
rep(
    """    #: deepest generation allowed, counted on the *stored* (relative) level grid.
    max_level = (start_level - tree.grid_level) + 12
    #: dyadic reference level for the global vertex key table, measured on the stored level
    #: grid: one vertex is then identified by one integer pair no matter which leaf created it.
    key_level = max_level""",
    """    #: deepest generation allowed, on the tree's *absolute* dyadic scale so the cap does not
    #: depend on how many re-rootings the seed performed.
    max_level = max(start_level - tree.root_level, 0) + 12
    #: absolute dyadic level of the shared vertex key lattice: one vertex is identified by one
    #: integer pair there, no matter which leaf created it.
    key_level = tree.absolute_level(max_level)""",
    "key-level",
)
rep('        "grid_level": int(tree.grid_level),', '        "root_level_after_seed": int(tree.root_level),', "report-grid")

# ------------------------------------------------------------------ top_vertex
rep(
    """        Cell-local indices are meaningless across generations: a level-``l`` cell's index
        unit is smaller than a coarse cell's, so the pair is scaled onto the shared key grid
        before it is used as an identity.  Without this a coarse cell and a refined neighbour
        would create two vertices for the same world point.
        \"\"\"
        shift = leaf_span_for(level)
        key = (int(gi) << shift, int(gj) << shift)
        found = top_index.get(key)
        if found is None:
            u, v = _cell_uv(tree, level, shift, np.array([[int(gi), int(gj)]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
            top_index[key] = found
        return found""",
    """        ``cell_triangles`` already returns **global key-grid indices**, so a vertex is
        identified by that pair alone: neighbouring cells and parent/child pairs produce the
        same pair for a shared world point at every refinement pattern, which is what keeps the
        solid watertight without T-junction bookkeeping.  Shifting a *local* index here instead
        would weld vertices from cells that merely have equal local indices.
        \"\"\"
        del level
        key = (int(gi), int(gj))
        found = top_index.get(key)
        if found is None:
            step_u = tree.hx / float(1 << key_level)
            step_v = tree.hy / float(1 << key_level)
            u = tree.u0 + key[0] * step_u
            v = tree.v0 + key[1] * step_v
            found = len(vertices)
            vertices.append((float(u), float(v), float(height(np.array([u]), np.array([v]))[0])))
            top_index[key] = found
        return found""",
    "top_vertex",
)

PATH.write_text(src, encoding="utf-8")
print("\n".join(applied))
print("changed" if src != orig else "NO CHANGE")
import ast  # noqa: E402

ast.parse(src)
print("syntax OK")
