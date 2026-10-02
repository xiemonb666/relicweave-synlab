"""S12 driver: declare-vs-route audit over **all 31 degradation axes**.

Task context (``docs/a12/smallfixes_report.md`` §S11): P03 declared a narrow-band surface operator
(``degrade/axes.py: NARROWBAND = True``) while the production route
(``synlab/pipeline.py`` → ``physical.api.apply_damage`` → ``physical.operators.run_damage``) ran a
global voxel level set, so the delivered body carried the extraction drift of a grid it never
declared.  S11 fixed P03 and did not re-measure P02/P04.  This driver generalises that audit:

``--step table``
    Every one of the 31 axes, every level 1..4, on the real probe bundles: the *declared* backend
    (``degrade/axes.py``: ``NARROWBAND``, ``STAGE``, ``GRID``) against the backend that **actually
    executed**, captured by instrumenting both routes
    (``physical.operators.run_damage`` and ``degrade.axes._PhysicalAxis.physical_result``).  A row
    is ``AGREE`` only when the executed function is the one the axis declares.

``--step fix``
    Per P axis, on a real archived body (default ``data/a12_degrade/store``): the *declared* route
    against the legacy global-SDF route, with ``roi_external_drift_mm`` / p95 / p99,
    ``lost_volume_mm3``, watertight + boundary edges, faces and the audit ``failure_codes``.

``--step drift_versions``
    Backward-compatibility proof for the new quantiles: the shipped ``_roi_external_drift``
    implementation (loaded from git ``HEAD``) and the new
    ``physical.operators._roi_external_drift_stats`` are run on the same body and grid, and must
    agree bit for bit on the max.

``--step budget``
    The ``choose_spacing`` node budget: requested vs realised spacing and nodes, on the real body,
    including the exact "0.95 requested → 1.14 realised" case from S11, plus the
    budget → spacing → drift curve (global backend, where spacing still decides geometry).

Usage::

    .venv\\Scripts\\python.exe tests\\a12\\degrade\\_probe_axis_routing_audit.py --step all \\
        --out data/a12_reports/s12_axis_routing_audit.json
"""

from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.degrade.registry import AXIS_REGISTRY  # noqa: E402
from synlab.schemas.spec import AXIS_IDS as ALL_AXIS_IDS  # noqa: E402

DEFAULT_STORE = "data/a12_degrade/store"
DEFAULT_CONFIG = "configs/a12/sandbox.yaml"
RECIPE_OF_AXIS = {"P02": "P02_round_edge_mid", "P03": "P03_depth_light",
                  "P04": "P04_chip_mid"}
DEFAULT_LINEAGE = "LIN0000_V02_M01_PAT02"


# ======================================================================================
# instruments
# ======================================================================================
def _boundary_edges(mesh: Any) -> int:
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    if len(edges) == 0:
        return 0
    order = np.lexsort(edges.T)
    edges = edges[order]
    same = np.all(edges[1:] == edges[:-1], axis=1)
    starts = np.concatenate([[True], ~same])
    counts = np.bincount(np.cumsum(starts) - 1)
    return int(np.count_nonzero(counts == 1))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class _RouteSpy:
    """Records which implementation actually ran, per axis and call.

    Both routes are patched at module level: ``physical.operators.run_damage`` (the production
    route) and ``degrade.axes._PhysicalAxis.physical_result`` (the operator-audit route).  The spy
    records the *function* that was entered, so "declared narrowband" can be checked against
    "executed ``degrade.physical_narrowband.run_narrowband_damage``" instead of against a flag.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._undo: list[Any] = []

    def __enter__(self) -> "_RouteSpy":
        from synlab.degrade import axes as A
        from synlab.physical import operators as O

        original_run_damage = O.run_damage
        original_selected = O.selected_backend
        original_physical_result = A._PhysicalAxis.physical_result
        spy = self

        def run_damage(mesh: Any, recipe: Any, *, fragment: Any = None) -> Any:
            outcome = original_run_damage(mesh, recipe, fragment=fragment)
            self.records.append({
                "route": "physical.operators.run_damage", "axis_id": recipe.axis_id,
                "level": int(recipe.level), "backend": O.selected_backend(recipe),
                "executed": str(((outcome.details or {}).get("damage_backend")) or ""),
                "declared_narrowband": O.declared_narrowband_axis(recipe.axis_id),
            })
            return outcome

        def physical_result(self_axis: Any, recipe: Any, fragment: Any, clean_truth: Any) -> Any:
            outcome = original_physical_result(self_axis, recipe, fragment, clean_truth)
            self.records.append({
                "route": "degrade.axes._PhysicalAxis.physical_result",
                "axis_id": recipe.axis_id, "level": int(recipe.level),
                "backend": "narrowband" if self_axis.NARROWBAND else "global_sdf",
                "executed": ("degrade.physical_narrowband.run_narrowband_damage"
                             if self_axis.NARROWBAND else "physical.operators."
                             + _handler_name(recipe.axis_id)),
                "declared_narrowband": bool(self_axis.NARROWBAND),
            })
            return outcome

        def _apply(self_axis: Any, source: Any, level: int, params: Any, basis: Any,
                   variant: str) -> Any:
            cls_name = type(self_axis).__name__
            spy.records.append({
                "route": "degrade.axes._apply",
                "axis_id": getattr(self_axis, "AXIS_ID", "?"), "level": int(level),
                "backend": f"degrade.axes.{cls_name}",
                "executed": f"degrade.axes.{cls_name}._apply",
                "declared_narrowband": bool(getattr(self_axis, "NARROWBAND", False)),
            })
            return original_apply(self_axis, source, level, params, basis, variant)

        # Every concrete axis class gets its *own* ``_apply`` wrapped, whichever class defines it
        # (I/G/X define theirs directly, so patching only the base would miss them), and the
        # wrappers are installed on the classes rather than the instances so the spy sees exactly
        # what the framework would have called.
        wrapped: list[tuple[Any, Any]] = []
        seen: set[int] = set()
        keep_alive: list[Any] = []
        for axis_id in ALL_AXIS_IDS:
            cls = type(AXIS_REGISTRY.get(axis_id))
            keep_alive.append(cls)
            if id(cls) in seen:
                continue
            seen.add(id(cls))
            impl = cls.__dict__.get("_apply")
            if impl is None:
                impl = getattr(cls, "_apply")
                holder = next(base for base in cls.__mro__ if "_apply" in base.__dict__)
            else:
                holder = cls
            if holder.__name__ in ROUTING_ONLY_APPLY:
                # the P family's ``_apply`` is a routing obligation, not a backend: wrapping it
                # would produce a record that looks like an implementation claim
                continue
            setattr(holder, "_apply", _make_apply_wrapper(impl, spy))
            wrapped.append((holder, "_apply", impl))
        O.run_damage = run_damage
        O.selected_backend = original_selected
        A._PhysicalAxis.physical_result = physical_result
        self._undo = [(O, "run_damage", original_run_damage),
                      (A._PhysicalAxis, "physical_result", original_physical_result),
                      *wrapped]
        return self

    def __exit__(self, *exc: Any) -> None:
        for holder, name, value in self._undo:
            setattr(holder, name, value)

    def take(self) -> list[dict[str, Any]]:
        out, self.records = self.records, []
        return out


def _handler_name(axis_id: str) -> str:
    from synlab.physical.operators import GEOMETRY_DISPATCH

    handler = GEOMETRY_DISPATCH.get(axis_id)
    return getattr(handler, "__name__", "?")


def _make_apply_wrapper(original: Any, spy: Any) -> Any:
    """Wrap one concrete ``_apply`` so the spy records the class that actually ran."""

    def wrapper(self_axis: Any, source: Any, level: int, params: Any, basis: Any,
                variant: str) -> Any:
        cls_name = type(self_axis).__name__
        spy.records.append({
            "route": "degrade.axes._apply",
            "axis_id": getattr(self_axis, "AXIS_ID", "?"), "level": int(level),
            "backend": f"degrade.axes.{cls_name}",
            "executed": f"degrade.axes.{cls_name}._apply",
            "declared_narrowband": bool(getattr(self_axis, "NARROWBAND", False)),
        })
        return original(self_axis, source, level, params, basis, variant)

    wrapper.__name__ = getattr(original, "__name__", "_apply")
    wrapper.__qualname__ = getattr(original, "__qualname__", "_apply")
    return wrapper


def declared_implementation(axis_id: str, *, declared_narrowband: bool) -> str:
    """The function the axis's declaration says must run.

    * narrow-band P axes -> ``degrade.physical_narrowband.run_narrowband_damage``
    * other P axes      -> their handler in ``physical.operators`` (the global voxel level set)
    * I / G / X axes    -> their own ``degrade.axes.<Class>._apply`` (one implementation each)
    """
    family = axis_id[0]
    if family != "P":
        return f"degrade.axes.{axis_id}._apply"
    if declared_narrowband:
        return "degrade.physical_narrowband.run_narrowband_damage"
    return f"physical.operators.{_handler_name(axis_id)}"


#: ``_apply`` as defined by these base classes only *routes*; the geometry backend is decided one
#: level deeper (``_PhysicalAxis.physical_result`` / ``physical.operators.run_damage``).  Concrete
#: axis classes define their own ``_apply``, and for I/G/X that method *is* the implementation.
ROUTING_ONLY_APPLY = ("_BaseAxis", "_PhysicalAxis")


def _is_concrete_record(record: dict[str, Any]) -> bool:
    if record.get("route") != "degrade.axes._apply":
        return True
    executed = str(record.get("executed", ""))
    return not any(executed == f"degrade.axes.{name}._apply" for name in ROUTING_ONLY_APPLY)


# ======================================================================================
# setup helpers
# ======================================================================================
def load_store_body(store_root: str | Path, *, fragment_id: str | None = None
                    ) -> tuple[Any, Any, str]:
    from synlab.roles import ROLE_FRAGMENT_MESH
    from synlab.storage.store import AssetStore

    store = AssetStore(store_root)
    assets = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=100000)
    if not assets:
        raise SystemExit(f"no fragment_mesh asset in {store_root}")
    wanted = [a for a in assets if not fragment_id or str(a.meta.get("fragment_id")) == fragment_id]
    if not wanted:
        wanted = assets
    best = max(wanted, key=lambda r: float(abs(store.load_mesh(r.asset_id, "mesh").volume)))
    return store, store.load_mesh(best.asset_id, "mesh"), str(best.meta.get("fragment_id"))


def build_recipe(config: str | Path, recipe_id: str, lineage_id: str, mesh: Any, name: str) -> Any:
    from synlab.config import load_generation_spec
    from synlab.pipeline import _load_damage_recipe

    spec = load_generation_spec(config)
    fragment = SimpleNamespace(mesh=mesh, fragment_id=name, volume_mm3=float(abs(mesh.volume)),
                               is_tiny=False, meta={"material_id": ""})
    recipe = _load_damage_recipe(recipe_id, spec, fragment=fragment, master_seed=spec.master_seed,
                                 lineage_id=lineage_id)
    return fragment, recipe


def recipe_with(recipe: Any, **grid: Any) -> Any:
    merged = dict(recipe.grid or {})
    merged.update({k: v for k, v in grid.items() if v is not None})
    return replace(recipe, grid=merged)


# ======================================================================================
# step: table (31 axes)
# ======================================================================================
def step_table(*, levels: Sequence[int] = (1, 2, 3, 4)) -> dict[str, Any]:
    from synlab.degrade.api import apply_axis, probe_sources
    from synlab.schemas.spec import AXIS_IDS

    sources = probe_sources()
    rows: list[dict[str, Any]] = []
    for axis_id in AXIS_IDS:
        operator = AXIS_REGISTRY.get(axis_id)
        family = axis_id[0]
        source = sources[family]
        declared_nb = bool(getattr(operator, "NARROWBAND", False))
        declared_backend = ("narrowband" if declared_nb
                            else "global_sdf_level_set" if family == "P"
                            else f"degrade.axes.{type(operator).__name__}")
        level_rows: list[dict[str, Any]] = []
        for level in levels:
            row: dict[str, Any] = {"level": int(level), "degrade": {}}
            with _RouteSpy() as spy:
                try:
                    _ref, measurement = apply_axis(axis_id, level, source, None,
                                                   lineage_id=f"lin_{axis_id}_s12")
                    measured = dict(measurement.measured or {})
                    row["degrade"] = {
                        "realized": bool(measurement.realized),
                        "failure_code": measurement.failure_code,
                        "drift_mm": measured.get("roi_external_drift_mm"),
                        "drift_p95_mm": measured.get("roi_external_drift_p95_mm"),
                        "lost_volume_mm3": measured.get("lost_volume_mm3"),
                        "watertight": measured.get("watertight"),
                        "grid_spacing_mm": measured.get("grid_spacing_mm"),
                        "grid_budget_limited": measured.get("grid_budget_limited"),
                        "grid_request_honoured": measured.get("grid_request_honoured"),
                    }
                except Exception as exc:  # noqa: BLE001 - a refusal is an outcome
                    row["degrade"] = {"error": f"{type(exc).__name__}: {exc}",
                                      "code": getattr(getattr(exc, "code", None), "value", None)}
                row["routes"] = spy.take()
                row["degrade"]["executed"] = sorted({
                    str(r.get("executed")) for r in row["routes"]
                    if r.get("route", "").startswith("degrade")})
            level_rows.append(row)
        executed = sorted({str(r.get("executed")) for row in level_rows
                           for r in row["routes"] if r.get("route", "").startswith("degrade")})
        expected = declared_implementation(axis_id, declared_narrowband=declared_nb)
        # ``degrade.axes._BaseAxis._apply`` / ``_PhysicalAxis._apply`` are the axes' entry points,
        # not claims about which geometry backend ran: for the P family they delegate to
        # ``_PhysicalAxis.physical_result`` (or ``run_damage``), so they are recorded as the routing
        # chain and the *concrete* implementations decide agreement.
        concrete = [r for row in level_rows for r in row["routes"]
                    if r.get("route", "").startswith("degrade") and _is_concrete_record(r)]
        routing = sorted({str(r.get("executed")) for row in level_rows for r in row["routes"]
                          if r.get("route") == "degrade.axes._apply"})
        agrees = [str(r.get("executed", "")).startswith(expected) for r in concrete]
        rows.append({
            "axis_id": axis_id, "family": family, "stage": operator.STAGE,
            "declared_backend": declared_backend,
            "declared_narrowband": declared_nb,
            "declared_implementation": expected,
            "routing_entry_points": routing,
            "declared_spacing_rule": getattr(operator, "SPACING_FROM", None),
            "declared_grid": _jsonable(getattr(operator, "GRID", {}) or {}),
            "executed_backends": executed,
            "agree": ("AGREE" if agrees and all(agrees) else
                      "DISAGREE" if agrees else "NOT_EXECUTED"),
            "levels": level_rows,
        })
    return {"levels": [int(v) for v in levels], "rows": rows}


# ======================================================================================
# step: fix (per-axis before/after)
# ======================================================================================
def _body_view(result: Any, clean: Any) -> dict[str, Any]:
    from synlab.physical import sdf as S

    representative = next((c for c in result.components if c.is_representative),
                          result.components[0] if result.components else None)
    body = representative.mesh if representative is not None else None
    if body is None:
        return {"available": False}
    out: dict[str, Any] = {
        "available": True, "n_faces": int(len(body.faces)), "n_vertices": int(len(body.vertices)),
        "volume_mm3": float(abs(body.volume)), "area_mm2": float(body.area),
        "watertight": bool(body.is_watertight), "boundary_edges": _boundary_edges(body),
        "winding_consistent": bool(body.is_winding_consistent),
        "bodies": int(len(S.component_split(body))),
        "lost_volume_mm3": float(abs(clean.volume) - abs(body.volume)),
        "lost_volume_ratio": float(1.0 - abs(body.volume) / max(abs(clean.volume), 1e-12)),
    }
    return out


def _run_physical(mesh: Any, fragment: Any, recipe: Any) -> dict[str, Any]:
    from synlab.physical.api import apply_damage, audit_physical
    from synlab.physical.operators import selected_backend

    started = time.perf_counter()
    entry: dict[str, Any] = {"requested_backend": selected_backend(recipe),
                             "recipe_grid": _jsonable(recipe.grid)}
    with _RouteSpy() as spy:
        try:
            result = apply_damage(None, fragment, recipe, rng=None)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["code"] = getattr(getattr(exc, "code", None), "value", None)
            entry["routes"] = spy.take()
            entry["seconds"] = time.perf_counter() - started
            return entry
        entry["routes"] = spy.take()
    entry["seconds"] = time.perf_counter() - started
    details = dict((result.meta or {}).get("details") or {})
    measured = {k: float(v) for k, v in ((result.meta or {}).get("measured") or {}).items()
                if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)}
    audit = audit_physical(result, mesh)
    entry.update({
        "damage_backend": details.get("damage_backend"),
        "backend_selection": _jsonable(details.get("backend_selection")),
        "spacing_budget": _jsonable(details.get("spacing_budget")),
        "narrowband_grid": _jsonable(((details.get("narrowband") or {}).get("grid"))),
        "measured": {
            "roi_external_drift_mm": measured.get("roi_external_drift_mm"),
            "roi_external_drift_p50_mm": measured.get("roi_external_drift_p50_mm"),
            "roi_external_drift_p95_mm": measured.get("roi_external_drift_p95_mm"),
            "roi_external_drift_p99_mm": measured.get("roi_external_drift_p99_mm"),
            "roi_external_drift_moved_samples": measured.get("roi_external_drift_moved_samples"),
            "lost_volume_mm3": measured.get("lost_volume_mm3"),
            "grid_spacing_mm": measured.get("grid_spacing_mm"),
            "grid_nodes": measured.get("grid_nodes"),
            "watertight": measured.get("watertight"),
            "components": measured.get("components"),
            "applied_depth_mm": measured.get("applied_depth_mm"),
            "achieved_contact_loss": measured.get("achieved_contact_loss"),
            "measured_max_recession_mm": measured.get("measured_max_recession_mm"),
        },
        "body": _body_view(result, mesh),
        "audit": {"status": audit.get("status"),
                  "failure_codes": list(audit.get("failure_codes") or []),
                  "roi_external_drift_check": _jsonable(
                      (audit.get("checks") or {}).get("roi_external_drift"))},
    })
    del result
    gc.collect()
    return entry


def step_fix(*, store_root: str, config: str, lineage_id: str, level: int,
             fragment_id: str | None) -> dict[str, Any]:
    _store, mesh, frag_id = load_store_body(store_root, fragment_id=fragment_id)
    out: dict[str, Any] = {"fragment_id": frag_id,
                           "body": {"volume_mm3": float(abs(mesh.volume)),
                                    "n_faces": int(len(mesh.faces)),
                                    "watertight": bool(mesh.is_watertight)},
                           "axes": {}}
    for axis_id, recipe_id in RECIPE_OF_AXIS.items():
        try:
            fragment, recipe = build_recipe(config, recipe_id, lineage_id, mesh, frag_id)
        except Exception as exc:  # noqa: BLE001
            out["axes"][axis_id] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        if int(recipe.level) != int(level):
            recipe = replace(recipe, level=int(level))
        declared = _run_physical(mesh, fragment, recipe)
        legacy = _run_physical(mesh, fragment, recipe_with(recipe, damage_backend="global_sdf"))
        narrow = _run_physical(mesh, fragment, recipe_with(recipe, damage_backend="narrowband"))
        out["axes"][axis_id] = {
            "recipe_id": recipe_id, "level": int(level),
            "params": _jsonable(recipe.params), "roi": _jsonable(recipe.roi),
            "declared_route": declared, "legacy_global_sdf_route": legacy,
            "forced_narrowband_route": narrow,
        }
        print(f".. fix {axis_id} done", file=sys.stderr)
        gc.collect()
    return out


# ======================================================================================
# step: drift_versions (backward compatibility)
# ======================================================================================
def _head_roi_external_drift_source() -> str:
    """The shipped ``_roi_external_drift`` body, read from git HEAD."""
    rel = "synlab/physical/operators.py"
    text = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, check=True,
                          encoding="utf-8", errors="replace").stdout
    start = text.index("def _roi_external_drift(")
    end = text.index("\n# ------", start)
    return text[start:end]


def step_drift_versions(*, store_root: str, config: str, lineage_id: str, level: int,
                        fragment_id: str | None) -> dict[str, Any]:
    from synlab.physical import sdf as S
    from synlab.physical.operators import (DRIFT_QUANTILES, SdfContext,
                                           _roi_external_drift_stats)

    _store, mesh, frag_id = load_store_body(store_root, fragment_id=fragment_id)
    fragment, recipe = build_recipe(config, RECIPE_OF_AXIS["P03"], lineage_id, mesh, frag_id)
    recipe = recipe_with(replace(recipe, level=int(level)), damage_backend="global_sdf")
    ctx = SdfContext(mesh, recipe, fragment=fragment)

    namespace: dict[str, Any] = {"np": np, "trimesh": __import__("trimesh"), "S": S}
    exec(compile(_head_roi_external_drift_source(), "<git:HEAD:operators.py>", "exec"), namespace)
    head_fn = namespace["_roi_external_drift"]

    # the body the shipped implementation was measured on: the delivered global-SDF result
    delivered = _run_physical(mesh, fragment, recipe)
    from synlab.physical.api import apply_damage

    result = apply_damage(None, fragment, recipe, rng=None)
    body = next((c for c in result.components if c.is_representative),
                result.components[0]).mesh
    halo = float(recipe.params.get("depth_mm", 0.05)) * 2.0 + 3.0 * ctx.spacing + 1.0
    head_value = float(head_fn(body, ctx, halo_mm=halo))
    stats = _roi_external_drift_stats(body, ctx, halo_mm=halo)
    return {
        "fragment_id": frag_id, "level": int(level), "halo_mm": halo,
        "spacing_mm": float(ctx.spacing),
        "spacing_basis": str(ctx.spacing_info.get("basis")),
        "quantiles": list(DRIFT_QUANTILES),
        "head_roi_external_drift_mm": head_value,
        "new_max_mm": float(stats["max_mm"]),
        "bitwise_identical": bool(head_value == float(stats["max_mm"])),
        "p50_mm": float(stats["p50_mm"]), "p95_mm": float(stats["p95_mm"]),
        "p99_mm": float(stats["p99_mm"]),
        "samples": float(stats["samples"]), "moved_samples": float(stats["moved_samples"]),
        "delivered_global_body": delivered.get("body"),
    }


# ======================================================================================
# step: budget (choose_spacing requested vs realised)
# ======================================================================================
def step_budget(*, store_root: str, config: str, lineage_id: str, level: int,
                fragment_id: str | None, budgets: Sequence[int],
                declared_spacings: Sequence[float], backend: str) -> dict[str, Any]:
    from synlab.physical import sdf as S
    from synlab.physical.operators import SdfContext, selected_backend

    _store, mesh, frag_id = load_store_body(store_root, fragment_id=fragment_id)
    fragment, base = build_recipe(config, RECIPE_OF_AXIS["P03"], lineage_id, mesh, frag_id)
    base = replace(base, level=int(level))
    extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
    out: dict[str, Any] = {"fragment_id": frag_id, "level": int(level),
                           "bbox_mm": [float(v) for v in extent],
                           "backend": backend,
                           "budget_curve": [], "declared_spacing_curve": []}
    for max_nodes in budgets:
        recipe = recipe_with(base, max_nodes=int(max_nodes), damage_backend=backend)
        ctx = SdfContext(mesh, recipe, fragment=fragment)
        entry = {
            "max_nodes": int(max_nodes),
            "requested_mm": ctx.spacing_info.get("requested_spacing_mm"),
            "spacing_mm": float(ctx.spacing),
            "basis": str(ctx.spacing_info.get("basis")),
            "relaxation_steps": int(ctx.spacing_info.get("relaxation_steps", 0)),
            "relaxation_factor": float(ctx.spacing_info.get("relaxation_factor", 1.0)),
            "budget_limited": bool(ctx.spacing_info.get("budget_limited", False)),
            "grid_shape": list(ctx.grid.shape), "grid_nodes": int(ctx.grid.n_nodes),
            "realised": _jsonable(ctx.spacing_info.get("realised")),
        }
        del ctx
        gc.collect()
        run = _run_physical(mesh, fragment, recipe)
        entry["drift_mm"] = (run.get("measured") or {}).get("roi_external_drift_mm")
        entry["drift_p95_mm"] = (run.get("measured") or {}).get("roi_external_drift_p95_mm")
        entry["drift_p99_mm"] = (run.get("measured") or {}).get("roi_external_drift_p99_mm")
        entry["lost_volume_mm3"] = (run.get("measured") or {}).get("lost_volume_mm3")
        entry["n_faces"] = (run.get("body") or {}).get("n_faces")
        entry["watertight"] = (run.get("body") or {}).get("watertight")
        entry["boundary_edges"] = (run.get("body") or {}).get("boundary_edges")
        entry["audit_status"] = (run.get("audit") or {}).get("status")
        entry["failure_codes"] = (run.get("audit") or {}).get("failure_codes")
        out["budget_curve"].append(entry)
        print(f".. budget {max_nodes} done", file=sys.stderr)
        gc.collect()
    for spacing in declared_spacings:
        recipe = recipe_with(base, damage_spacing_mm=float(spacing), damage_backend=backend)
        ctx = SdfContext(mesh, recipe, fragment=fragment)
        entry = {
            "declared_mm": float(spacing),
            "requested_mm": ctx.spacing_info.get("requested_spacing_mm"),
            "spacing_mm": float(ctx.spacing),
            "basis": str(ctx.spacing_info.get("basis")),
            "budget_limited": bool(ctx.spacing_info.get("budget_limited", False)),
            "grid_shape": list(ctx.grid.shape), "grid_nodes": int(ctx.grid.n_nodes),
            "realised": _jsonable(ctx.spacing_info.get("realised")),
        }
        del ctx
        gc.collect()
        run = _run_physical(mesh, fragment, recipe)
        entry["drift_mm"] = (run.get("measured") or {}).get("roi_external_drift_mm")
        entry["drift_p95_mm"] = (run.get("measured") or {}).get("roi_external_drift_p95_mm")
        entry["drift_p99_mm"] = (run.get("measured") or {}).get("roi_external_drift_p99_mm")
        entry["lost_volume_mm3"] = (run.get("measured") or {}).get("lost_volume_mm3")
        entry["n_faces"] = (run.get("body") or {}).get("n_faces")
        entry["watertight"] = (run.get("body") or {}).get("watertight")
        entry["boundary_edges"] = (run.get("body") or {}).get("boundary_edges")
        entry["audit_status"] = (run.get("audit") or {}).get("status")
        entry["failure_codes"] = (run.get("audit") or {}).get("failure_codes")
        out["declared_spacing_curve"].append(entry)
        print(f".. declared spacing {spacing} done", file=sys.stderr)
        gc.collect()
    # the S11 "requested 0.95 -> realised 1.14" case, reproduced from the rule itself
    out["s11_case"] = _s11_requested_vs_realised(store_root, mesh, fragment, base)
    out["rule_probe"] = [
        {"requested_mm": req, "chosen": S.choose_spacing(
            min_wall_thickness_mm=0.6, shortest_structure_mm=float(np.min(extent)),
            requested_mm=req, max_nodes=600_000, bbox_mm=tuple(float(v) for v in extent))}
        for req in (None, 0.5701, 0.95018, 1.1402, 2.2804)]
    return out


def _s11_requested_vs_realised(store_root: str, mesh: Any, fragment: Any, base: Any) -> dict[str, Any]:
    """What the axis *requests* (``min_wall_thickness/6``) vs what the budget allows."""
    from synlab.physical import sdf as S

    thickness = S.ray_thickness(mesh, n_samples=160, seed=int(base.basis.get("seed", 0)) % 997)
    extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
    requested = float(thickness["p05_mm"]) / 6.0
    choice = S.choose_spacing(min_wall_thickness_mm=max(float(thickness["p05_mm"]), 1e-3),
                              shortest_structure_mm=float(np.min(extent)), requested_mm=None,
                              max_nodes=int((base.grid or {}).get("max_nodes", 600_000)),
                              bbox_mm=tuple(float(v) for v in extent))
    return {"measured_thickness": _jsonable(thickness),
            "axis_request_mm": requested,
            "chosen": _jsonable(choice),
            "requested_over_realised": float(choice["spacing_mm"] / max(requested, 1e-12)),
            "note": "P03 (like P01/P02/P04/P07/P08) declares SPACING_FROM = None, so the axis "
                    "hands the decision to choose_spacing: min(min_wall_thickness/6, "
                    "shortest_structure/4) then the node budget. The 'request' is what the "
                    "resolution rule asks for before the budget; the budget is what decides."}


# ======================================================================================
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a12_s12_axis_routing")
    parser.add_argument("--step", default="all",
                        choices=("table", "fix", "drift_versions", "budget", "all"))
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--lineage", default=DEFAULT_LINEAGE)
    parser.add_argument("--fragment", default=None)
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--budgets", default="600000,2000000,8000000")
    parser.add_argument("--declared-spacings", default="1.1402,0.95018,0.5701,0.25")
    parser.add_argument("--budget-backend", default="global_sdf")
    parser.add_argument("--out", default="data/a12_reports/s12_axis_routing_audit.json")
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"schema": "synlab.a12.s12.axis_routing.v1", "step": args.step,
                              "store": args.store, "config": args.config, "level": args.level}
    try:
        if args.step in ("table", "all"):
            report["table"] = step_table()
        if args.step in ("fix", "all"):
            report["fix"] = step_fix(store_root=args.store, config=args.config,
                                     lineage_id=args.lineage, level=args.level,
                                     fragment_id=args.fragment)
        if args.step in ("drift_versions", "all"):
            report["drift_versions"] = step_drift_versions(
                store_root=args.store, config=args.config, lineage_id=args.lineage,
                level=args.level, fragment_id=args.fragment)
        if args.step in ("budget", "all"):
            report["budget"] = step_budget(
                store_root=args.store, config=args.config, lineage_id=args.lineage,
                level=args.level, fragment_id=args.fragment,
                budgets=[int(v) for v in args.budgets.split(",") if v],
                declared_spacings=[float(v) for v in args.declared_spacings.split(",") if v],
                backend=args.budget_backend)
        report["ok"] = True
    except BaseException as exc:  # noqa: BLE001 - a crash is an outcome
        report["ok"] = False
        report["escaped_exception"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-4000:]
    out_path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2,
                                   sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2, default=str))
    print(f"wrote {out_path}")
    return 0 if report.get("ok") else 1


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": report.get("ok"), "step": report.get("step")}
    if "escaped_exception" in report:
        out["escaped_exception"] = report["escaped_exception"]
        out["traceback"] = report.get("traceback")
        return out
    table = report.get("table")
    if table:
        rows = table["rows"]
        out["table"] = {
            "axes": len(rows),
            "agree": sum(1 for r in rows if r["agree"] == "AGREE"),
            "disagree": [r["axis_id"] for r in rows if r["agree"] != "AGREE"],
            "executed_backends": {r["axis_id"]: r["executed_backends"] for r in rows},
            "declared_implementations": {r["axis_id"]: r["declared_implementation"]
                                         for r in rows},
        }
    fix = report.get("fix")
    if fix:
        out["fix"] = {}
        for axis, row in fix["axes"].items():
            if "declared_route" not in row:
                out["fix"][axis] = {"error": row.get("error")}
                continue
            out["fix"][axis] = {
                "declared_backend": (row["declared_route"] or {}).get("damage_backend"),
                "legacy_backend": (row["legacy_global_sdf_route"] or {}).get("damage_backend"),
                "declared_drift_mm": ((row["declared_route"] or {}).get("measured") or {}).get(
                    "roi_external_drift_mm"),
                "declared_drift_p95_mm": ((row["declared_route"] or {}).get("measured") or {}).get(
                    "roi_external_drift_p95_mm"),
                "legacy_drift_mm": ((row["legacy_global_sdf_route"] or {}).get("measured") or {}).get(
                    "roi_external_drift_mm"),
                "legacy_drift_p95_mm": ((row["legacy_global_sdf_route"] or {}).get("measured")
                                        or {}).get("roi_external_drift_p95_mm"),
                "legacy_failure_codes": ((row["legacy_global_sdf_route"] or {}).get("audit")
                                         or {}).get("failure_codes"),
                "declared_failure_codes": ((row["declared_route"] or {}).get("audit")
                                           or {}).get("failure_codes"),
                "legacy_watertight": ((row["legacy_global_sdf_route"] or {}).get("body")
                                      or {}).get("watertight"),
                "legacy_boundary_edges": ((row["legacy_global_sdf_route"] or {}).get("body")
                                          or {}).get("boundary_edges"),
                "declared_watertight": ((row["declared_route"] or {}).get("body")
                                        or {}).get("watertight"),
                "declared_boundary_edges": ((row["declared_route"] or {}).get("body")
                                            or {}).get("boundary_edges"),
            }
    dv = report.get("drift_versions")
    if dv:
        out["drift_versions"] = {k: dv[k] for k in ("head_roi_external_drift_mm", "new_max_mm",
                                                    "bitwise_identical", "p50_mm", "p95_mm",
                                                    "p99_mm", "moved_samples")}
    budget = report.get("budget")
    if budget:
        out["budget_curve"] = [{k: row.get(k) for k in
                                ("max_nodes", "requested_mm", "spacing_mm", "basis",
                                 "grid_nodes", "drift_mm", "drift_p95_mm", "drift_p99_mm",
                                 "lost_volume_mm3", "n_faces", "watertight", "boundary_edges",
                                 "audit_status")} for row in budget["budget_curve"]]
        out["declared_spacing_curve"] = [{k: row.get(k) for k in
                                          ("declared_mm", "spacing_mm", "grid_nodes", "drift_mm",
                                           "drift_p95_mm", "drift_p99_mm", "lost_volume_mm3",
                                           "n_faces", "watertight", "boundary_edges",
                                           "audit_status")}
                                         for row in budget["declared_spacing_curve"]]
        out["s11_case"] = {"axis_request_mm": budget["s11_case"]["axis_request_mm"],
                           "chosen": budget["s11_case"]["chosen"],
                           "requested_over_realised": budget["s11_case"]["requested_over_realised"]}
        out["rule_probe"] = budget["rule_probe"]
    return out


if __name__ == "__main__":
    raise SystemExit(main())
