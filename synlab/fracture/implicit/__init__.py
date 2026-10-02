"""Implicit-field (SDF) fracture backend: a displaced implicit sheet shared by both halves.

This package replaces the *quadtree + exact CSG + conformal triangulation* route of
:mod:`synlab.fracture.cut` (``build_closed_cutter``) with an implicit-field construction that has
**no T-junctions by construction**:

``synlab/fracture/cut.py`` triangulates an adaptively refined quadtree one cell at a time.  Two
neighbouring leaves of different generations meet at a hanging vertex, and the assembler has to
patch the resulting T-junction with side quads; measured on the real bodies that leaves thousands
of edges with a face count != 2 (``CUTTER_NOT_CLOSED``), see ``docs/a12/fracture_realism.md``
section 10.  The Lead's decision (recorded in ``docs/a12/fracture_implicit.md``) is to stop
investing there.

Construction (main path, :mod:`synlab.fracture.implicit.sheet`):

1. the *same* cut basis as the plane backend (:func:`synlab.fracture.cut.build_basis`), so a
   ``plane_shared_cut`` and an ``implicit_sheet_cut`` event on one mother differ in exactly one
   thing: the shape of the shared surface;
2. the fracture surface is the **graph** ``w = h(u, v)`` of a physically driven height field
   (:class:`~synlab.fracture.morphology.MorphologyHeightField`, parameters from
   :func:`synlab.fracture.morphology.derive_morphology_parameters`), band-limited and slope
   calibrated by this package;
3. ``h`` vanishes *exactly* on the material cross-section outline (the patch boundary ring), so
   the sheet meets the flat plane along that ring and the two halves close on it;
4. the sheet is triangulated on a **tensor-product grid** (``u`` and ``v`` coordinate arrays with
   local spacing), which is a conforming triangulation at any grading: every quad owns four
   lattice corners, neighbours share full edges, and a hanging vertex cannot exist;
5. the closed cutter body is assembled from that one sheet: flat bottom at ``w_min - margin`` and
   one side quad per silhouette edge.  Both sides of the event consume the *same* instance
   (``synlab.fracture.event.run_shared_cut``), so conjugacy is constructive.

Fallback path (:mod:`synlab.fracture.implicit.narrowband`): a true 3-D narrow-band signed
distance field + marching cubes, for sheets that are not a graph over ``(u, v)`` (overhangs).

Nothing in this package modifies ``cut.py`` / ``event.py`` / ``fragment.py`` / ``booleans.py``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "BACKEND_IMPLICIT", "SWITCH_ENV", "IMPLICIT_META_KEY", "GATED",
    "register", "implicit_backend_enabled", "implicit_options",
    "build_implicit_cutter", "run_implicit_event", "backend_status",
]

#: backend id registered in the global registry (``synlab.registry``).
BACKEND_IMPLICIT = "implicit_sheet_cut"
#: opt-in switch, mirroring :data:`synlab.fracture.api.MORPHOLOGY_SWITCH_ENV` (off by default).
SWITCH_ENV = "SYNLAB_FRACTURE_IMPLICIT"
#: key under which the frozen parameter/realization record is published on meta.
IMPLICIT_META_KEY = "fracture_implicit"
#: registered but gated off by default: it is NOT in ``api.BUILT_BACKENDS``.
GATED = True

_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def register() -> str:
    """Register the backend in the global registry (called from one line in ``api.py``).

    Kept deliberately tiny: importing this function must not import gmsh, torch or anything
    heavy, because :mod:`synlab.fracture.api` imports it at module import time.
    """
    from ...registry import STATUS_SPECIFIED, REGISTRY, RegistryEntry

    entry = RegistryEntry(
        id=BACKEND_IMPLICIT, kind="fracture_backend",
        name="隐式场薄片断口（SDF sheet）", version="1.0",
        module=__name__, status=STATUS_SPECIFIED,
        applicable={"shell": True, "solid": True},
        notes="implicit-field fracture surface: one displaced sheet w = h(u,v) with h == 0 on the "
              "material cross-section ring, triangulated on a conforming tensor grid (no quadtree, "
              "no T-junction), closed by a flat bottom + side quads and shared by both sides of "
              "the event.  Gated OFF by default (SYNLAB_FRACTURE_IMPLICIT=1 or "
              "spec.meta['implicit']); it is NOT in api.BUILT_BACKENDS.  Entry point: "
              "synlab.fracture.implicit.run_implicit_event "
              "(builder: synlab.fracture.implicit.build_implicit_cutter).",
        meta={"builder_name": "build_implicit_cutter",
              "switch_env": SWITCH_ENV, "gated": True,
              "fallback": "synlab.fracture.implicit.narrowband"},
    )
    if REGISTRY.has("fracture_backend", BACKEND_IMPLICIT):
        return BACKEND_IMPLICIT
    REGISTRY.register(entry)
    return BACKEND_IMPLICIT


def backend_status() -> dict[str, Any]:
    """Honest capability record (import path, gate, entry points, whether gmsh is present)."""
    from ...registry import REGISTRY

    registered = REGISTRY.has("fracture_backend", BACKEND_IMPLICIT)
    try:  # pragma: no cover - depends on the host
        import gmsh  # noqa: F401

        gmsh_version = str(getattr(gmsh, "__version__", "?"))
        del gmsh
    except Exception as exc:  # noqa: BLE001
        gmsh_version = f"MISSING ({type(exc).__name__})"
    return {
        "backend": BACKEND_IMPLICIT, "registered": bool(registered), "gated": True,
        "switch_env": SWITCH_ENV, "in_built_backends": False,
        "builder": "synlab.fracture.implicit.build_implicit_cutter",
        "runner": "synlab.fracture.implicit.run_implicit_event",
        "fallback": "synlab.fracture.implicit.narrowband.build_narrowband_cutter",
        "gmsh": gmsh_version,
    }


def implicit_backend_enabled(spec: Any = None) -> bool:
    """Is the implicit backend switched on for this call?  (env var or ``spec.meta``)"""
    import os
    from collections.abc import Mapping

    if str(os.environ.get(SWITCH_ENV, "")).strip().lower() in _TRUTHY:
        return True
    meta = getattr(spec, "meta", None)
    if isinstance(meta, Mapping):
        if bool(meta.get("implicit_backend")):
            return True
        if isinstance(meta.get("implicit"), Mapping):
            return True
    return False


def implicit_options(spec: Any) -> tuple[Any, dict[str, Any]]:
    """``(material_profile, options)`` carried by ``spec.meta`` for this backend."""
    from collections.abc import Mapping

    meta = getattr(spec, "meta", None)
    meta = dict(meta) if isinstance(meta, Mapping) else {}
    options = meta.get("implicit")
    return meta.get("material_profile"), (dict(options) if isinstance(options, Mapping) else {})


def _gate(spec: Any, *, stage: str) -> None:
    """Refuse to run unless the backend was explicitly switched on (never a silent plane)."""
    from ...errors import ErrorCode, SynLabError

    if implicit_backend_enabled(spec):
        return
    raise SynLabError(
        ErrorCode.OPERATOR_NOT_REALIZED,
        f"backend {BACKEND_IMPLICIT!r} is implemented but GATED OFF by default so that no existing "
        f"caller changes cost or QA numbers; opt in with {SWITCH_ENV}=1 or "
        f"spec.meta['implicit']/spec.meta['implicit_backend']",
        stage=stage, measurements={"switch_env": SWITCH_ENV, "gated": True},
    )


def __getattr__(name: str) -> Any:  # pragma: no cover - lazy re-exports
    """Lazy re-export of the heavy entry points (importing gmsh/scipy is not free)."""
    if name == "build_implicit_cutter":
        from .backend import build_implicit_cutter

        return build_implicit_cutter
    if name == "run_implicit_event":
        from .backend import run_implicit_event

        return run_implicit_event
    raise AttributeError(name)
