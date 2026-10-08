from __future__ import annotations
import hashlib, json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import trimesh

ROOT = Path.cwd().resolve()
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLBACKEND", "Agg")
started = time.perf_counter()
files = [
    "docs/a12/engineering_policy.md",
    "docs/a12/evidence/20261004/copies/validity/pytest-routing-v2.log",
    "tests/a12/operators/test_narrowband.py",
    "tests/a12/degrade/test_axis_routing_audit.py",
    "synlab/degrade/physical_narrowband.py",
    "synlab/degrade/narrowband.py",
    "synlab/physical/sdf.py",
    "synlab/physical/operators.py",
    "synlab/physical/api.py",
    "synlab/degrade/registry.py",
    "synlab/degrade/axes.py",
]
hashes = {}
for rel in files:
    p = ROOT / rel
    if p.is_file():
        hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()

def topology(m):
    v = np.asarray(m.vertices, dtype=np.float64)
    f = np.asarray(m.faces, dtype=np.int64)
    if f.size:
        tri = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=0), axis=1)
        uniq, counts = np.unique(tri, axis=0, return_counts=True)
        boundary = uniq[counts == 1]
        nonmanifold = uniq[counts > 2]
        try:
            degenerate = int((~m.nondegenerate_faces(height=1e-12)).sum())
        except Exception:
            degenerate = None
    else:
        boundary = np.empty((0, 2), dtype=np.int64)
        nonmanifold = np.empty((0, 2), dtype=np.int64)
        degenerate = 0
    try:
        signed_volume = float(m.volume)
    except Exception:
        signed_volume = None
    try:
        watertight = bool(m.is_watertight)
        winding = bool(m.is_winding_consistent)
        is_volume = bool(m.is_volume)
    except Exception:
        watertight = winding = is_volume = None
    return {
        "vertices": int(len(v)), "faces": int(len(f)),
        "boundary_edges": int(len(boundary)), "nonmanifold_edges": int(len(nonmanifold)),
        "degenerate_faces": degenerate,
        "watertight": watertight, "winding_consistent": winding, "is_volume": is_volume,
        "signed_volume_mm3": signed_volume,
        "bounds_mm": [[float(x) for x in row] for row in m.bounds] if len(v) else None,
    }

def boundary_data(m):
    f = np.asarray(m.faces, dtype=np.int64)
    verts = np.asarray(m.vertices, dtype=np.float64)
    pairs = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=0), axis=1)
    edges, counts = np.unique(pairs, axis=0, return_counts=True)
    bedges = edges[counts == 1]
    rows = []
    for i, edge in enumerate(bedges):
        p0, p1 = verts[edge]
        mid = 0.5 * (p0 + p1)
        rows.append({
            "edge_index_sorted": i,
            "vertex_indices": [int(edge[0]), int(edge[1])],
            "p0_mm": [float(x) for x in p0],
            "p1_mm": [float(x) for x in p1],
            "midpoint_mm": [float(x) for x in mid],
            "length_mm": float(np.linalg.norm(p1 - p0)),
        })
    degree = {}
    for a, b in bedges:
        degree[int(a)] = degree.get(int(a), 0) + 1
        degree[int(b)] = degree.get(int(b), 0) + 1
    return {
        "edges": rows,
        "vertex_degrees": {str(k): int(v) for k, v in sorted(degree.items())},
        "boundary_components": int(len(rows) and _edge_components(bedges)),
        "length_total_mm": float(sum(x["length_mm"] for x in rows)),
        "all_endpoint_coordinates_mm": verts[np.unique(bedges)].tolist() if len(bedges) else [],
    }

def _edge_components(edges):
    adj = {}
    for a, b in edges:
        a, b = int(a), int(b)
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    remaining = set(adj)
    n = 0
    while remaining:
        n += 1
        stack = [remaining.pop()]
        while stack:
            for nxt in adj[stack.pop()]:
                if nxt in remaining:
                    remaining.remove(nxt)
                    stack.append(nxt)
    return n

def cleanup_trace(m):
    # Diagnostic shadow of physical.sdf.clean_mesh's explicit stages. This operates on a copy,
    # and actual clean_mesh still runs after this trace.
    c = m.copy()
    stages = [{"stage": "clean_input", **topology(c)}]
    c.merge_vertices()
    stages.append({"stage": "after_merge_vertices", **topology(c)})
    mask = c.nondegenerate_faces(height=1e-12)
    removed = int(len(c.faces) - int(mask.sum()))
    c.update_faces(mask)
    stages.append({"stage": "after_degenerate_face_filter", "faces_removed": removed,
                   **topology(c)})
    c.remove_unreferenced_vertices()
    stages.append({"stage": "after_remove_unreferenced_vertices", **topology(c)})
    return stages

events = []
repair_events = []
current = {"axis": None, "site": "degrade_runtime"}
orig_intersection = trimesh.boolean.intersection
orig_clean_mesh = None
orig_component_split = None
orig_fix_winding = trimesh.repair.fix_winding
orig_fix_inversion = trimesh.repair.fix_inversion
orig_offset_body = None

def native_intersection_capture(meshes, *args, **kwargs):
    out = orig_intersection(meshes, *args, **kwargs)
    try:
        if isinstance(out, trimesh.Trimesh):
            events.append({"axis": current["axis"], "stage": "manifold_boolean_native_return",
                           **topology(out), "boundary": boundary_data(out)})
        else:
            events.append({"axis": current["axis"], "stage": "manifold_boolean_native_return",
                           "return_type": type(out).__name__,
                           "items": [topology(x) for x in out] if isinstance(out, (list, tuple)) else None})
    except Exception as exc:
        events.append({"axis": current["axis"], "stage": "manifold_boolean_native_return",
                       "capture_error": f"{type(exc).__name__}: {exc}"})
    return out

def traced_fix(name, original):
    def wrapped(mesh, *args, **kwargs):
        row = {"axis": current["axis"], "site": current["site"], "operation": name,
               "before": topology(mesh)}
        result = original(mesh, *args, **kwargs)
        row["after"] = topology(mesh)
        repair_events.append(row)
        return result
    return wrapped

trimesh.boolean.intersection = native_intersection_capture
trimesh.repair.fix_winding = traced_fix("fix_winding", orig_fix_winding)
trimesh.repair.fix_inversion = traced_fix("fix_inversion", orig_fix_inversion)

from synlab.degrade import api as degrade_api
from synlab.degrade import narrowband as NB
from synlab.degrade import physical_narrowband as PNB
from synlab.degrade.axes import physical_fragment
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.physical import sdf as S

orig_clean_mesh = S.clean_mesh
orig_component_split = S.component_split
orig_offset_body = NB._offset_body

def traced_clean(mesh):
    old_site = current["site"]
    current["site"] = "physical.sdf.clean_mesh"
    row = {"axis": current["axis"], "stage": "clean_mesh_call",
           "shadow_stages": cleanup_trace(mesh)}
    result = orig_clean_mesh(mesh)
    row["actual_output"] = topology(result)
    row["actual_output_boundary"] = boundary_data(result)
    events.append(row)
    current["site"] = old_site
    return result

def traced_component_split(mesh, *args, **kwargs):
    parts = orig_component_split(mesh, *args, **kwargs)
    events.append({"axis": current["axis"], "stage": "component_split_return",
                   "input": topology(mesh), "parts": [topology(p) for p in parts],
                   "part_count": int(len(parts))})
    return parts

def traced_offset(mesh, depth):
    old_site = current["site"]
    current["site"] = "narrowband._offset_body"
    result = orig_offset_body(mesh, depth)
    events.append({"axis": current["axis"], "stage": "offset_body_after_repair",
                   "depth_positive_vertices": int(np.count_nonzero(np.asarray(depth) > 0)),
                   **topology(result), "boundary": boundary_data(result)})
    current["site"] = old_site
    return result

S.clean_mesh = traced_clean
S.component_split = traced_component_split
NB._offset_body = traced_offset

def build_output(axis_id, lineage):
    source = probe[ "P" ]
    fragment = physical_fragment(source)
    operator = AXIS_REGISTRY.get(axis_id)
    variant = operator.default_variant
    context = degrade_api._context_for(source, axis_id=axis_id, lineage_id=lineage,
                                       master_seed=int((source.meta or {}).get(
                                           "master_seed", degrade_api.DEFAULT_MASTER_SEED)))
    context["variant"] = variant
    basis = operator.sample_basis(context, degrade_api._default_rng(context, axis_id, variant),
                                  variant)
    level = 1
    planned = operator.params_for(level, variant)
    output = operator._apply(source, level, planned, basis, variant)
    result = output.get("physical_result")
    mesh = output.get("mesh")
    return source, fragment, basis, output, result, mesh

try:
    from synlab.degrade.api import probe_sources
    probe = probe_sources()
    source_mesh = physical_fragment(probe["P"]).mesh
    source_report = topology(source_mesh)
    case_results = []
    meshes_for_plot = {}
    for axis_id, lineage in (("P02", "lin_p02"), ("P03", "lin_p03")):
        current["axis"] = axis_id
        current["site"] = "degrade_runtime"
        before = len(events)
        source, fragment, basis, output, physical_result, final_mesh = build_output(axis_id, lineage)
        diag = {
            "axis_id": axis_id,
            "lineage_id": lineage,
            "variant": physical_result.meta.get("variant"),
            "level": int(physical_result.meta.get("level")),
            "basis_id": basis.basis_id,
            "source_provenance": (probe["P"].meta or {}).get("provenance"),
            "source": source_report,
            "source_boundary": boundary_data(source_mesh),
            "physical_qa_realized": bool(physical_result.qa.get("realized")),
            "physical_qa_status": physical_result.qa.get("status"),
            "physical_qa_failure_codes": physical_result.qa.get("failure_codes"),
            "postassembly": physical_result.qa.get("postassembly"),
            "measured": physical_result.meta.get("measured"),
            "narrowband_details": (physical_result.meta.get("details") or {}).get("narrowband"),
            "final_component": topology(final_mesh),
            "final_boundary": boundary_data(final_mesh),
            "diagnostic_events": events[before:],
        }
        case_results.append(diag)
        meshes_for_plot[axis_id] = (final_mesh, diag["final_boundary"])

    # Calculate the P07 test's actual spacing decision only; no global SDF grid is built.
    p07 = AXIS_REGISTRY.get("P07")
    p07_variant = p07.default_variant
    p07_context = degrade_api._context_for(probe["P"], axis_id="P07",
                                           lineage_id="lin_s12",
                                           master_seed=int((probe["P"].meta or {}).get(
                                               "master_seed", degrade_api.DEFAULT_MASTER_SEED)))
    p07_context["variant"] = p07_variant
    p07_basis = p07.sample_basis(p07_context,
                                 degrade_api._default_rng(p07_context, "P07", p07_variant),
                                 p07_variant)
    p07_fragment = physical_fragment(probe["P"])
    p07_recipe = p07.recipe(level=1, variant=p07_variant,
                             params=p07.params_for(1, p07_variant), basis=p07_basis,
                             fragment=p07_fragment, source=probe["P"])
    grid_spec = dict(p07_recipe.grid or {})
    grid_spec["max_nodes"] = 60_000
    thickness = S.ray_thickness(p07_fragment.mesh, n_samples=160,
                                seed=int(p07_basis.payload.get("seed", 0)) % 997)
    extent = np.asarray(p07_fragment.mesh.bounds[1]) - np.asarray(p07_fragment.mesh.bounds[0])
    choice = S.choose_spacing(
        min_wall_thickness_mm=max(float(thickness["p05_mm"]), 1e-3),
        shortest_structure_mm=float(p07_recipe.meta.get("shortest_structure_mm", 0.0) or 0.0)
                               or float(np.min(extent)),
        requested_mm=grid_spec.get("spacing_mm"),
        max_nodes=int(grid_spec["max_nodes"]),
        bbox_mm=tuple(float(x) for x in extent),
        explicit_mm=grid_spec.get("damage_spacing_mm"),
    )
    spacing = float(choice["spacing_mm"])
    pad = float(grid_spec.get("pad_mm", max(1.0, 2.0 * spacing)))
    actual_shape = np.ceil((extent + 2.0 * pad) / spacing).astype(int) + 1
    p07_budget = {
        "fixture_provenance": (probe["P"].meta or {}).get("provenance"),
        "bbox_extent_mm": [float(x) for x in extent],
        "p05_ray_thickness_mm": float(thickness["p05_mm"]),
        "ray_thickness": thickness,
        "recipe_grid": p07_recipe.grid,
        "test_override_max_nodes": 60_000,
        "choice": choice,
        "builder_pad_mm": pad,
        "builder_shape_with_pad": [int(x) for x in actual_shape],
        "builder_nodes_with_pad": int(np.prod(actual_shape)),
        "budget_loop_estimator_nodes": int(np.prod(np.ceil(extent / spacing) + 3)),
        "reported_estimator_nodes": S.spacing_budget_report(
            choice, bbox_mm=tuple(float(x) for x in extent))["estimated_nodes"],
        "interpretation": (
            "The existing 60,000-node assertion is only justified if this specific fixture's "
            "choice exceeds that budget. The recorded decision below is computed from the exact "
            "SdfContext formula and no SDF field/grid was built."
        ),
    }

    report = {
        "schema": "a12_narrowband_routing_diagnosis_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(ROOT),
        "diagnostic_script": str(Path(__file__).resolve()),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "task_scope": "read-only diagnosis; no production/test edits; no Git; no original artifacts modified",
        "source_hashes_sha256": hashes,
        "probe_source": {
            "provenance": (probe["P"].meta or {}).get("provenance"),
            "mesh": source_report,
            "boundary": boundary_data(source_mesh),
        },
        "p02_p03_cases": case_results,
        "p07_budget_formula": p07_budget,
        "repair_events": repair_events,
        "elapsed_seconds": float(time.perf_counter() - started),
    }

    (OUT / "diagnosis.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    # Actual final-component mesh vertex projection with every open boundary edge highlighted.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    fig, axs = plt.subplots(2, 2, figsize=(12.8, 9.0), constrained_layout=True)
    projections = [(0, 1, "X", "Y"), (0, 2, "X", "Z")]
    for row, axis_id in enumerate(("P02", "P03")):
        mesh, bd = meshes_for_plot[axis_id]
        v = np.asarray(mesh.vertices, dtype=np.float64)
        f = np.asarray(mesh.faces, dtype=np.int64)
        edges = bd["edges"]
        for col, (u, w, ux, wy) in enumerate(projections):
            ax = axs[row, col]
            ax.scatter(v[:, u], v[:, w], s=1.7, c="#89939e", alpha=0.42, linewidths=0,
                       label="final component mesh vertices")
            segs = [([e["p0_mm"][u], e["p0_mm"][w]],
                     [e["p1_mm"][u], e["p1_mm"][w]]) for e in edges]
            if segs:
                ax.add_collection(LineCollection(segs, colors="#d7191c", linewidths=2.2,
                                                 label="open boundary edges"))
                ends = np.asarray([p for e in edges for p in (e["p0_mm"], e["p1_mm"])])
                ax.scatter(ends[:, u], ends[:, w], s=16, c="#d7191c", marker="o",
                           label="boundary endpoints", zorder=4)
                allv = v[:, [u, w]]
                lo = np.min(ends[:, [u, w]], axis=0)
                hi = np.max(ends[:, [u, w]], axis=0)
                extentp = np.ptp(allv, axis=0)
                margin = max(0.5, 0.04 * float(np.max(extentp)))
                ax.set_xlim(float(lo[0] - margin), float(hi[0] + margin))
                ax.set_ylim(float(lo[1] - margin), float(hi[1] + margin))
            ax.set_xlabel(f"{ux} (mm)")
            ax.set_ylabel(f"{wy} (mm)")
            ax.set_aspect("equal", adjustable="box")
            ax.grid(True, alpha=0.25)
            if col == 0:
                ax.set_title(f"{axis_id}: XY projection")
            else:
                ax.set_title(f"{axis_id}: XZ projection")
            ax.text(0.02, 0.98,
                    f"open edges={len(edges)}; watertight={mesh.is_watertight}",
                    transform=ax.transAxes, va="top", ha="left",
                    bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#888"})
    handles, labels = axs[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="outside lower center", ncol=3)
    fig.suptitle("Actual narrow-band output mesh boundaries (probe fixture; all coordinates mm)\n"
                 "Highlighted edges are topology failures, not physical cracks or cut surfaces")
    fig.savefig(OUT / "actual_mesh_boundary_projections.png", dpi=180)
    plt.close(fig)
    print(json.dumps({
        "output_json": str(OUT / "diagnosis.json"),
        "output_png": str(OUT / "actual_mesh_boundary_projections.png"),
        "elapsed_seconds": report["elapsed_seconds"],
        "python_executable": sys.executable,
        "p02": {"boundary_edges": case_results[0]["final_component"]["boundary_edges"],
                "boundary": case_results[0]["final_boundary"]},
        "p03": {"boundary_edges": case_results[1]["final_component"]["boundary_edges"],
                "boundary": case_results[1]["final_boundary"]},
        "p07_budget": p07_budget,
    }, indent=2))
finally:
    trimesh.boolean.intersection = orig_intersection
    trimesh.repair.fix_winding = orig_fix_winding
    trimesh.repair.fix_inversion = orig_fix_inversion
    S.clean_mesh = orig_clean_mesh
    S.component_split = orig_component_split
    NB._offset_body = orig_offset_body
