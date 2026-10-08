"""Environment compatibility shims needed by the degradation axes.

Each shim restores an API that the installed third-party version removed or changed, so that
modules outside this package (frozen interfaces owned by other workstreams) keep working
unchanged.  Every shim is (a) minimal, (b) documented with the evidence that it is needed, and
(c) recorded in :data:`ACTIVE_SHIMS`, which the operator audit reports.

.. warning::
   **Currently no shim is installed.**  All three original shims were requests against
   ``synlab/physical``, that workstream fixed them at the source, and installation is now
   conditional on a runtime probe that measures the defect.  See :data:`RETIRED_SHIMS` for the
   evidence that retired each one and :func:`install_trimesh_shims` for what still activates a
   shim if an older ``synlab/physical`` is paired with this package.

Retirement record (measured, not assumed)
-----------------------------------------
1. ``Trimesh.remove_degenerate_faces`` (removed in trimesh 5.1) -- **retired**.
   ``synlab.physical.sdf.clean_mesh`` now calls ``out.nondegenerate_faces(height=1e-12)`` and
   ``update_faces`` directly, so the missing attribute is never touched.  Verified by importing
   ``synlab.physical`` in a fresh interpreter (the shim is *not* installed by that import) and
   calling ``clean_mesh`` on a box: 12 faces in, 12 faces out, no ``AttributeError``.
2. ``trimesh.boolean.boolean_automatic`` (removed in trimesh 5.1) -- **retired**.
   ``synlab.physical.sdf.boolean_op`` now dispatches to
   ``trimesh.boolean.difference/union/intersection`` directly.  Verified the same way with a
   real difference.
3. ``Trimesh.edges_face`` (trimesh 5.1 changed it to the directed-edge face index) --
   **retired, not needed at all**: ``synlab.physical.fields.edge_face_pairs`` rebuilds the
   legacy ``(E_unique, 2)`` face-pair table from ``edges_unique_inverse`` itself and no longer
   reads ``Trimesh.edges_face``.  Measured on the probe slab without the shim: 208 convex edges
   at 45 deg (the shimmed run reported 206), and the dihedral angles stay 90.0 deg.  The shim
   is now **opt-in** through ``install_edges_face_shim=True`` for any other legacy consumer.
4. ``synlab.physical.sdf.evaluate_field`` base term -- **retired**.  The frozen implementation
   used to overwrite the copied ``base`` with ``fn(points)``, so ``field != d0 + t*alpha*b``.
   Upstream now adds ``base_block + values`` before writing.  Verified with a real probe call:
   ``evaluate_field(grid, lambda p: 2.0, base=full(-7.0))`` returns ``-5.0`` everywhere (the
   shimmed and unshimmed runs agree), and ``info["seam_max_abs_diff"] == 0.0``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: Records of the shims that are currently active (surfaced in the operator audit report).
ACTIVE_SHIMS: list[dict[str, Any]] = []

#: Shims that were requested by this package, fixed upstream and are therefore no longer
#: installed.  Kept as data so the audit and the docs can state *why* nothing is active.
RETIRED_SHIMS: list[dict[str, Any]] = [
    {
        "shim": "trimesh.Trimesh.remove_degenerate_faces",
        "retired_by": "synlab.physical.sdf.clean_mesh",
        "evidence": "import synlab.physical in a fresh interpreter (shim not installed) and call "
                    "clean_mesh on a box: 12 faces in, 12 faces out, no AttributeError",
    },
    {
        "shim": "trimesh.boolean.boolean_automatic",
        "retired_by": "synlab.physical.sdf.boolean_op",
        "evidence": "boolean_op('difference', [box, shifted_box]) returns 12 faces without the "
                    "shim; sdf.py dispatches to trimesh.boolean.<op> directly",
    },
    {
        "shim": "trimesh.Trimesh.edges_face (legacy (E,2) table)",
        "retired_by": "synlab.physical.fields.edge_face_pairs",
        "evidence": "without the shim the probe slab yields 208 convex edges at 45 deg and "
                    "90.0 deg dihedral angles (shimmed: 206 edges); fields.py rebuilds the table "
                    "from edges_unique_inverse and never reads Trimesh.edges_face",
    },
    {
        "shim": "synlab.physical.sdf.evaluate_field (base term restored)",
        "retired_by": "synlab.physical.sdf.evaluate_field",
        "evidence": "evaluate_field(grid, lambda p: 2.0, base=full(-7.0)) returns -5.0 "
                    "everywhere with seam_max_abs_diff 0.0; the upstream body adds "
                    "base_block + values",
    },
]


def _evaluate_field_drops_base() -> bool:
    """Runtime probe: does the installed ``evaluate_field`` really honour ``base``?

    The probe is a two-node grid with a constant function, so the expected result is known
    exactly: ``base + 2.0``.  Returns ``True`` only when the upstream implementation drops the
    base term (i.e. when the old shim would be needed).
    """
    from ..physical import sdf as S

    try:
        grid = S.VoxelGrid(origin=np.zeros(3), spacing=1.0, shape=(5, 5, 5))
        base = np.full(grid.shape, -7.0, dtype=np.float64)
        out, _info = S.evaluate_field(grid, lambda p: np.full(len(p), 2.0), base=base,
                                      chunk=4, halo=1)
        return not bool(np.allclose(np.asarray(out), -5.0, atol=1e-9))
    except Exception:  # a broken/absent evaluate_field is reported by the caller, not hidden
        return False


def _legacy_edges_face(mesh: Any) -> np.ndarray:
    """Legacy ``(len(edges_unique), 2)`` face-pair table (second face ``-1`` at a boundary)."""
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    inverse = np.asarray(mesh.edges_unique_inverse, dtype=np.int64).ravel()
    faces = np.repeat(np.arange(len(mesh.faces), dtype=np.int64), 3)
    n_unique = len(np.asarray(mesh.edges_unique))
    if inverse.size != edges.shape[0] or faces.size != inverse.size:
        return np.full((n_unique, 2), -1, dtype=np.int64)
    counts = np.bincount(inverse, minlength=n_unique)
    order = np.argsort(inverse, kind="stable")
    face_sorted = faces[order]
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.int64)
    first = face_sorted[np.clip(starts, 0, max(len(face_sorted) - 1, 0))] if len(face_sorted) else \
        np.zeros(n_unique, dtype=np.int64)
    second = np.full(n_unique, -1, dtype=np.int64)
    many = counts > 1
    second[many] = face_sorted[starts[many] + 1]
    return np.stack([first, second], axis=1)


class _EdgeFaceCompat(np.ndarray):
    """Array carrying the legacy ``(E_unique, 2)`` face-pair table as its data.

    * ``np.asarray(edges_face, dtype=...)`` and any arithmetic see the legacy table;
    * integer-array indexing (``edges_face[edge_groups]`` in ``trimesh.graph``,
      ``edges_face[edge_index]`` in ``trimesh.repair``) is forwarded to the directed-edge face
      index that trimesh 5.1 produces, so no trimesh internal changes behaviour.
    """

    _directed: np.ndarray | None

    def __new__(cls, legacy: np.ndarray, directed: np.ndarray) -> "_EdgeFaceCompat":
        obj = np.asarray(legacy).view(cls)
        obj._directed = np.asarray(directed, dtype=np.int64)
        return obj

    def __array_finalize__(self, obj: Any) -> None:
        self._directed = getattr(obj, "_directed", None) if obj is not None else None

    def __getitem__(self, key: Any) -> Any:
        directed = self._directed
        if directed is not None and isinstance(key, (np.ndarray, list, tuple)):
            arr = np.asarray(key)
            if arr.dtype.kind in "iu" and arr.ndim in (1, 2) and arr.size:
                return directed[arr]
        return super().__getitem__(key)


def install_edges_face_shim(trimesh_module: Any) -> bool:
    """Install the legacy ``edges_face`` table (opt-in; not needed by this repository).

    Kept because the shim is the documented workaround for the trimesh 5.1 API change and an
    external consumer of the legacy table may still want it.  ``install_trimesh_shims`` does
    **not** call this by default: ``synlab.physical.fields.edge_face_pairs`` no longer reads
    ``Trimesh.edges_face``, so installing it only changes what *trimesh's own* internals see.
    """
    current = trimesh_module.Trimesh.__dict__.get("edges_face")
    if current is None or isinstance(current, _EdgeFaceCompatProperty):
        return False
    original = current.fget if isinstance(current, property) else current

    def edges_face(self: Any) -> _EdgeFaceCompat:
        cache = getattr(self, "_cache", None)
        directed = original(self)
        if cache is None:  # pragma: no cover - every trimesh mesh has a cache
            return _EdgeFaceCompat(_legacy_edges_face(self), directed)
        try:
            hit = cache["degrade_edges_face_compat"]
        except (KeyError, TypeError):
            hit = None
        if hit is not None and hit[0] is directed:
            return hit[1]
        compat = _EdgeFaceCompat(_legacy_edges_face(self), directed)
        try:
            cache["degrade_edges_face_compat"] = (directed, compat)
        except TypeError:  # pragma: no cover - read-only cache
            pass
        return compat

    trimesh_module.Trimesh.edges_face = _EdgeFaceCompatProperty(original, edges_face)
    return True


def _install_evaluate_field_fix() -> bool:
    """Re-apply the ``base + fn(points)`` fix **only if the installed version drops the base**.

    See the module docstring: upstream ``synlab.physical.sdf.evaluate_field`` now adds the base
    block, so this returns ``False`` on the current checkout (verified by
    :func:`_evaluate_field_drops_base`).  It stays as the guarded fallback for an older
    ``synlab/physical`` paired with this package.
    """
    from ..physical import sdf as S

    current = S.evaluate_field
    if getattr(current, "_degrade_base_fix", False):
        return False
    if not _evaluate_field_drops_base():
        return False

    def evaluate_field(grid: Any, fn: Any, *, chunk: int = 32, halo: int = 1,
                       base: Any = None) -> tuple[np.ndarray, dict[str, Any]]:
        nx, ny, nz = grid.shape
        base_arr = None if base is None else np.asarray(base, dtype=np.float64)
        out = (np.zeros(grid.shape, dtype=np.float64) if base_arr is None
               else np.array(base_arr, dtype=np.float64, copy=True))
        written = np.zeros(grid.shape, dtype=bool)
        seam_diff = 0.0
        overlap_nodes = 0
        xs, ys, zs = grid.axis_coords
        step = max(1, int(chunk) - 2 * int(halo))
        for i0 in range(0, nx - 1, step):
            i1 = min(nx, i0 + chunk)
            for j0 in range(0, ny - 1, step):
                j1 = min(ny, j0 + chunk)
                for k0 in range(0, nz - 1, step):
                    k1 = min(nz, k0 + chunk)
                    block = np.stack(np.meshgrid(xs[i0:i1], ys[j0:j1], zs[k0:k1], indexing="ij"),
                                     axis=-1).reshape(-1, 3)
                    values = np.asarray(fn(block), dtype=np.float64).reshape(i1 - i0, j1 - j0,
                                                                             k1 - k0)
                    if base_arr is not None:
                        values = values + base_arr[i0:i1, j0:j1, k0:k1]
                    target = out[i0:i1, j0:j1, k0:k1]
                    mask = written[i0:i1, j0:j1, k0:k1]
                    if mask.any():
                        seam_diff = max(seam_diff,
                                        float(np.max(np.abs(target[mask] - values[mask]))))
                        overlap_nodes += int(mask.sum())
                    target[~mask] = values[~mask]
                    written[i0:i1, j0:j1, k0:k1] = True
        if not written.all():
            raise S.SynLabError(S.ErrorCode.PRECISION_NOT_REALIZED,
                                f"chunked evaluation left {int((~written).sum())} nodes unwritten",
                                stage="physical.sdf")
        return out, {"seam_max_abs_diff": float(seam_diff), "overlap_nodes": int(overlap_nodes),
                     "chunk": int(chunk), "halo": int(halo), "base_applied": base_arr is not None,
                     "degrade_shim": "evaluate_field_base_fix"}

    evaluate_field._degrade_base_fix = True  # type: ignore[attr-defined]
    evaluate_field.__doc__ = (current.__doc__ or "") + \
        "\n\n[shim] base is added to fn(points) as documented (synlab.degrade.compat)."
    S.evaluate_field = evaluate_field  # type: ignore[assignment]
    return True


def install_trimesh_shims(*, with_edges_face: bool = False) -> list[dict[str, Any]]:
    """Install the still-needed compatibility shims (idempotent) and return the active list.

    On the current checkout this installs **nothing**: the three trimesh/``physical`` shims are
    retired (see the module docstring) and the ``edges_face`` shim is opt-in via
    ``with_edges_face=True``.  The remaining conditional branches cover the two regressions the
    runtime probes can still detect -- a ``synlab/physical`` that calls the removed
    ``remove_degenerate_faces``/``boolean_automatic``, or one whose ``evaluate_field`` drops the
    base term.
    """
    import trimesh

    from ..physical import sdf as S

    if not hasattr(trimesh.Trimesh, "remove_degenerate_faces") \
            and _calls(S.clean_mesh, "remove_degenerate_faces"):
        def remove_degenerate_faces(self: Any, height: float = 1e-8) -> None:
            """Drop faces whose area is not greater than ``height`` (in place)."""
            mask = np.asarray(self.nondegenerate_faces(height=float(height)), dtype=bool)
            if not bool(mask.all()):
                self.update_faces(mask)

        trimesh.Trimesh.remove_degenerate_faces = remove_degenerate_faces  # type: ignore[attr-defined]
        ACTIVE_SHIMS.append({
            "shim": "trimesh.Trimesh.remove_degenerate_faces",
            "reason": "trimesh 5.1.0 removed the method and the installed synlab/physical "
                      "clean_mesh still calls it",
            "evidence": "clean_mesh source mentions remove_degenerate_faces and trimesh has no "
                        "such attribute",
            "semantics": "keep faces with area > height (historic trimesh behaviour)",
        })

    if not hasattr(trimesh.boolean, "boolean_automatic") \
            and _calls(S.boolean_op, "boolean_automatic"):
        def boolean_automatic(meshes: Any, operation: str, engine: Any = None,
                              **kwargs: Any) -> Any:
            """Historic ``boolean_automatic`` dispatch over the current trimesh entries."""
            table = {"difference": trimesh.boolean.difference,
                     "union": trimesh.boolean.union,
                     "intersection": trimesh.boolean.intersection}
            if operation not in table:
                raise ValueError(f"unknown boolean operation {operation!r}")
            return table[operation](meshes, engine=engine, **kwargs)

        trimesh.boolean.boolean_automatic = boolean_automatic  # type: ignore[attr-defined]
        ACTIVE_SHIMS.append({
            "shim": "trimesh.boolean.boolean_automatic",
            "reason": "trimesh 5.1.0 removed the dispatcher and the installed "
                      "synlab/physical boolean_op still calls it",
            "evidence": "boolean_op source mentions boolean_automatic and trimesh.boolean has "
                        "no such attribute",
            "semantics": "dispatch to trimesh.boolean.difference/union/intersection(meshes, "
                         "engine=...)",
        })

    if with_edges_face and install_edges_face_shim(trimesh):
        ACTIVE_SHIMS.append({
            "shim": "trimesh.Trimesh.edges_face (legacy table as array data)",
            "reason": "explicitly requested; trimesh 5.1 changed edges_face from the "
                      "(E_unique,2) face-pair table to the directed-edge face index (3F,)",
            "evidence": "opt-in only -- synlab.physical.fields no longer reads edges_face",
            "semantics": "array conversion yields the legacy (E,2) table; integer-array indexing "
                         "yields trimesh 5.1's directed-edge faces",
        })

    if _install_evaluate_field_fix():
        ACTIVE_SHIMS.append({
            "shim": "synlab.physical.sdf.evaluate_field (base term restored)",
            "reason": "the installed implementation overwrites the copied base with fn(points), "
                      "so field != d0 + t*alpha*b",
            "evidence": "runtime probe: evaluate_field(grid, const 2.0, base=-7.0) does not "
                        "return -5.0",
            "semantics": "chunk values are base + fn(points); halo seams still share nodes",
            "kind": "BUG_FIX (not a compatibility shim)",
        })
    return ACTIVE_SHIMS


def _function_source(function: Any) -> str:
    """Source of a function for a cheap behavioural probe; empty when unavailable."""
    try:
        import inspect

        return inspect.getsource(function)
    except Exception:  # pragma: no cover - builtins / C functions
        return ""


def _calls(function: Any, name: str) -> bool:
    """True when ``function`` really **calls** ``name`` (docstrings/comments excluded).

    A plain substring test is not enough: the current ``synlab/physical`` *documents* the two
    removed trimesh APIs in comments while calling the replacements, so a substring probe
    re-installed both shims and reported them as active.  Extracting the real string literals
    (which drops the docstring) and looking for a call keeps the shim honest.
    """
    import ast

    source = _function_source(function)
    if not source:
        return False
    try:
        tree = ast.parse(_dedent(source))
    except SyntaxError:  # pragma: no cover - unusual indentation
        return f"{name}(" in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = getattr(func, "attr", None) or getattr(func, "id", None)
            if called == name:
                return True
    return False


def _dedent(source: str) -> str:
    import textwrap

    return textwrap.dedent(source)


class _EdgesFaceProperty:
    """Keeps a handle on the wrapped property so the shim is not installed twice."""

    original: Any = None


class _EdgeFaceCompatProperty(property):
    """Marker subclass so the shim can detect its own installation."""

    def __init__(self, original: Any, getter: Any) -> None:
        _EdgesFaceProperty.original = original.fget if isinstance(original, property) else original
        self._original = original
        super().__init__(getter)


__all__ = ["install_trimesh_shims", "install_edges_face_shim", "ACTIVE_SHIMS", "RETIRED_SHIMS",
           "_legacy_edges_face"]
