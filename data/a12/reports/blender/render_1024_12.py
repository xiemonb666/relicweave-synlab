"""12-view / long-edge-1024 px Blender imaging measurement (V1.44 G14.1 evidence).

This is the harness behind ``docs/a12/blender_route_wiring.md``.  It drives the **real**
observation route (``synlab.observe.routes``) with either the Blender Cycles backend or the
software rasteriser and records, per view and in total:

* wall time and the worker's own measured pass times,
* delivered sizes and the size of every file the worker wrote,
* ``id_map`` dtype / integrality / visible class count,
* ``depth_z`` statistics and an **independent** ray-cast comparison against the scene
  geometry (Moller-Trumbore, computed here, not by the renderer),
* ``uncertain_mask`` coverage,
* depth-derived per-pixel normals, for the Blender-vs-software comparison,
* the fused observation cloud statistics.

Usage (from the repository root)::

    .venv\\Scripts\\python.exe data/a12/reports/blender/render_1024_12.py --stage probe
    .venv\\Scripts\\python.exe data/a12/reports/blender/render_1024_12.py --stage blender
    .venv\\Scripts\\python.exe data/a12/reports/blender/render_1024_12.py --stage software
    .venv\\Scripts\\python.exe data/a12/reports/blender/render_1024_12.py --stage compare
    .venv\\Scripts\\python.exe data/a12/reports/blender/render_1024_12.py --stage fixture
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.api import camera_profiles                      # noqa: E402
from synlab.mothers.api import create_mother, default_params        # noqa: E402
from synlab.observe import routes as rt                             # noqa: E402
from synlab.observe.blender import BlenderBackendConfig             # noqa: E402
from synlab.observe.render import BACKEND_BLENDER, RenderSpec       # noqa: E402
from synlab.observe.routes import ObsSpec                           # noqa: E402
from synlab.seeds import make_rng                                   # noqa: E402
from synlab.errors import SynLabError                               # noqa: E402

OUT_ROOT = Path(__file__).resolve().parent / "1024_12"

#: The production-equivalent declared mark-out.  ``synlab.observe.render`` and the Blender
#: worker use the **same** CoC formula, but it is expressed in *pixel* focal-length units; the
#: rasteriser always evaluates it at f/1 while the worker is told the declared f-number, so
#: the two thresholds differ by exactly that f-number.  On top of that the pipeline passes
#: ``0.75 px * f_number`` (an f/1 convention correction), which on a profile whose declared
#: depth of field is 300-700 mm still marks the whole object: at 1024 px the formula returns
#: ~39 px for a surface at the near DOF edge.  This harness instead *calibrates the threshold
#: to the declared DOF*, i.e. a pixel is marked for defocus exactly when it lies outside the
#: profile's declared ``depth_of_field_mm`` - the declared optics, not a convention artifact.
DECLARED_COC_PX = 0.75
F_NUMBER = 8.0


def coc_px(z_mm: float, focus_mm: float, f_number: float, f_px: float) -> float:
    """The renderer's own CoC formula (``synlab.observe.render.circle_of_confusion_px``)."""
    denom = max(float(z_mm), 1e-6)
    return abs(f_px ** 2 / (f_number * denom) * (float(z_mm) - focus_mm)
               / max(focus_mm, 1e-6))


def dof_calibrated_threshold(*, focus_mm: float, f_number: float, f_px: float,
                             dof_mm: tuple[float, float]) -> dict[str, float]:
    """Thresholds that make "defocus uncertain" mean "outside the declared DOF"."""
    near, far = float(dof_mm[0]), float(dof_mm[1])
    worker = max(coc_px(near, focus_mm, f_number, f_px),
                 coc_px(far, focus_mm, f_number, f_px))
    return {"worker_threshold_px": worker,
            "rasterizer_threshold_px": worker * float(f_number),
            "coc_at_near_dof_px": coc_px(near, focus_mm, f_number, f_px),
            "coc_at_far_dof_px": coc_px(far, focus_mm, f_number, f_px),
            "f_number": float(f_number), "f_px": float(f_px),
            "focus_mm": float(focus_mm), "dof_mm": [near, far]}



def rng_for(module: str, seed: int = 20261001):
    return make_rng(seed, "blender_route_wiring", module)


# --------------------------------------------------------------------------------------
# independent geometry verification (no renderer involved)
# --------------------------------------------------------------------------------------
def cast_rays(K: np.ndarray, T_WC: np.ndarray, vertices: np.ndarray, faces: np.ndarray,
              size: tuple[int, int], stride: int) -> dict[str, np.ndarray]:
    """Vectorised pixel-centre ray cast over a strided grid of a ``(W, H)`` frame.

    Returns the sampled pixel coordinates, the camera-frame z of the hit (the quantity the
    renderer's depth pass reports, computed here by Moller-Trumbore) and the hit face index.
    A ray that misses every face gets ``z = NaN``.
    """
    width, height = int(size[0]), int(size[1])
    st = max(int(stride), 1)
    ys, xs = np.mgrid[st // 2:height:st, st // 2:width:st]
    ys = ys.ravel()
    xs = xs.ravel()
    uv = np.stack([xs.astype(np.float64) + 0.5, ys.astype(np.float64) + 0.5], axis=1)
    d_cam = np.stack([(uv[:, 0] - K[0, 2]) / K[0, 0],
                      (uv[:, 1] - K[1, 2]) / K[1, 1],
                      np.ones(uv.shape[0])], axis=1)
    R = np.asarray(T_WC, dtype=np.float64)[:3, :3]
    C = np.asarray(T_WC, dtype=np.float64)[:3, 3]
    d_world = d_cam @ R.T                       # NOT normalised: t is the camera z
    v0 = np.asarray(vertices, dtype=np.float64)[np.asarray(faces)[:, 0]]
    e1 = np.asarray(vertices, dtype=np.float64)[np.asarray(faces)[:, 1]] - v0
    e2 = np.asarray(vertices, dtype=np.float64)[np.asarray(faces)[:, 2]] - v0
    n_rays = d_world.shape[0]
    best_t = np.full(n_rays, np.inf, dtype=np.float64)
    best_f = np.full(n_rays, -1, dtype=np.int64)
    eps = 1e-12
    chunk = max(int(600_000 // max(n_rays, 1)), 8)
    for start in range(0, e1.shape[0], chunk):
        stop = min(start + chunk, e1.shape[0])
        e1c, e2c, v0c = e1[start:stop], e2[start:stop], v0[start:stop]
        pvec = np.cross(d_world[:, None, :], e2c[None, :, :])          # (nR, m, 3)
        det = np.einsum("fk,nfk->nf", e1c, pvec)                       # (nR, m)
        ok = np.abs(det) > eps
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tvec = C[None, :] - v0c                                        # (m, 3)
        u = np.einsum("fk,nfk->nf", tvec, pvec) * inv
        ok &= (u >= -1e-9) & (u <= 1.0 + 1e-9)
        qvec = np.cross(tvec[None, :, :], e1c[None, :, :])             # (nR, m, 3)
        v = np.einsum("nk,nfk->nf", d_world, qvec) * inv
        ok &= (v >= -1e-9) & (u + v <= 1.0 + 1e-9)
        t = np.einsum("fk,nfk->nf", e2c, qvec) * inv
        ok &= t > 1e-6
        t = np.where(ok, t, np.inf)
        local = np.argmin(t, axis=1)
        local_t = t[np.arange(n_rays), local]
        better = local_t < best_t
        best_t = np.where(better, local_t, best_t)
        best_f = np.where(better, start + local, best_f)
    z = np.where(np.isfinite(best_t), best_t, np.nan)
    return {"y": ys, "x": xs, "z_mm": z, "face": best_f}


def pose_mesh(vertices: np.ndarray, T_WO: np.ndarray | None) -> np.ndarray:
    verts = np.asarray(vertices, dtype=np.float64)
    if T_WO is None:
        return verts
    T = np.asarray(T_WO, dtype=np.float64)
    return verts @ T[:3, :3].T + T[:3, 3][None, :]


def depth_reference_check(render, frame, vertices: np.ndarray, faces: np.ndarray,
                          object_pose: np.ndarray | None, *, stride: int,
                          flat_tol_mm: float = 0.05) -> dict:
    """Compare the delivered depth pass with the independent ray cast.

    Three subsets are reported separately, because they answer different questions:

    ``all pairs``      every sampled pixel where both agree a surface is there;
    ``interior``       pixels the renderer does not flag as mixed/defocused;
    ``locally flat``   interior pixels whose 3x3 rendered-depth range is below
                       ``flat_tol_mm`` - the subset where a pixel-centre ray and the
                       rendered pass must agree to float32 if the depth channel is sound.
                       A slanted/grazing pixel has a per-pixel depth gradient of many mm, so
                       a sub-pixel sampling difference there is *expected*, and the measured
                       correlation between the local depth range and the error is reported.
    """
    import warnings

    cast = cast_rays(np.asarray(frame.K, dtype=np.float64),
                     np.asarray(frame.T_WC, dtype=np.float64),
                     pose_mesh(vertices, object_pose), faces,
                     tuple(int(v) for v in frame.image_size), stride)
    depth = np.asarray(render.depth_z, dtype=np.float64)
    uncertain = np.asarray(render.uncertain_mask, dtype=bool)
    ys, xs = cast["y"], cast["x"]
    rendered = depth[ys, xs]
    zref = cast["z_mm"]
    both = np.isfinite(rendered) & np.isfinite(zref)
    ray_only = ~np.isfinite(rendered) & np.isfinite(zref)
    render_only = np.isfinite(rendered) & ~np.isfinite(zref)
    interior = both & ~uncertain[ys, xs]
    delta = np.abs(rendered - zref)
    height, width = depth.shape
    pad = np.pad(depth, 1, constant_values=np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        windows = np.stack([pad[dy:dy + height, dx:dx + width]
                            for dy in range(3) for dx in range(3)])
        local_range = np.nanmax(windows, axis=0) - np.nanmin(windows, axis=0)
    grad = local_range[ys, xs]
    flat = interior & np.isfinite(grad) & (grad < float(flat_tol_mm))
    out = {
        "stride_px": int(stride),
        "n_rays": int(ys.size),
        "n_both_hit": int(both.sum()),
        "n_ray_only_hit": int(ray_only.sum()),
        "n_render_only_hit": int(render_only.sum()),
        "n_interior": int(interior.sum()),
        "n_locally_flat": int(flat.sum()),
        "flat_tolerance_mm": float(flat_tol_mm),
        "silhouette_disagreement_fraction": float((ray_only.sum() + render_only.sum())
                                                  / max(ys.size, 1)),
        "interior_max_abs_error_mm": (float(delta[interior].max())
                                      if interior.any() else None),
        "interior_mean_abs_error_mm": (float(delta[interior].mean())
                                       if interior.any() else None),
        "interior_p99_abs_error_mm": (float(np.percentile(delta[interior], 99))
                                      if interior.any() else None),
        "flat_max_abs_error_mm": float(delta[flat].max()) if flat.any() else None,
        "flat_mean_abs_error_mm": float(delta[flat].mean()) if flat.any() else None,
        "all_pairs_max_abs_error_mm": float(delta[both].max()) if both.any() else None,
        "all_pairs_p99_9_abs_error_mm": (float(np.percentile(delta[both], 99.9))
                                         if both.any() else None),
        "all_pairs_median_abs_error_mm": (float(np.median(delta[both]))
                                          if both.any() else None),
        "depth_discontinuity_pairs_gt_5mm": int(np.count_nonzero(delta[both] > 5.0)),
        "tolerance_mm": 0.01,
    }
    if interior.sum() > 2:
        g = grad[interior]
        d = delta[interior]
        keep = np.isfinite(g) & np.isfinite(d)
        if keep.sum() > 2 and float(np.std(g[keep])) > 0 and float(np.std(d[keep])) > 0:
            out["corr_error_vs_local_depth_range"] = float(np.corrcoef(g[keep], d[keep])[0, 1])
        out["median_local_depth_range_mm"] = float(np.median(g[keep])) if keep.any() else None
        # a 3x3 window spans 2 px, so the implied pixel-phase offset of the disagreement is
        # delta / (local_range / 2); it must stay well below one pixel for a sound channel
        span = np.where(g[keep] > 1e-9, g[keep] / 2.0, np.nan)
        implied = d[keep] / span
        implied = implied[np.isfinite(implied)]
        if implied.size:
            out["implied_pixel_offset_median_px"] = float(np.median(implied))
            out["implied_pixel_offset_p95_px"] = float(np.percentile(implied, 95))
        tol = np.maximum(0.1 * g[keep], 0.05)
        out["subpixel_consistent_fraction"] = float(np.mean(d[keep] <= tol))
    return out


# --------------------------------------------------------------------------------------
# depth-derived normals (per-pixel, camera frame) for the cross-backend comparison
# --------------------------------------------------------------------------------------
def depth_normals(depth_z: np.ndarray, K: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Camera-frame normals from the depth map by central differences (valid mask)."""
    depth = np.asarray(depth_z, dtype=np.float64)
    h, w = depth.shape
    ys, xs = np.mgrid[0:h, 0:w]
    valid = np.isfinite(depth) & (depth > 0)

    def backproject(dy: int, dx: int):
        yy = np.clip(ys + dy, 0, h - 1)
        xx = np.clip(xs + dx, 0, w - 1)
        d = depth[yy, xx]
        ok = valid & np.isfinite(d) & (d > 0) & (yy == ys + dy) & (xx == xs + dx)
        x = (xs + dx - K[0, 2]) / K[0, 0] * d
        y = (ys + dy - K[1, 2]) / K[1, 1] * d
        return np.stack([x, y, d], axis=-1), ok

    px, okx = backproject(0, 1)
    mx, okmx = backproject(0, -1)
    py, oky = backproject(1, 0)
    my, okmy = backproject(-1, 0)
    du = px - mx
    dv = py - my
    n = np.cross(du, dv)
    norm = np.linalg.norm(n, axis=-1)
    ok = valid & okx & okmx & oky & okmy & (norm > 1e-12)
    n = np.where(ok[..., None], n / np.maximum(norm, 1e-12)[..., None], np.nan)
    # orient towards the camera (the visible surface faces the camera centre by construction)
    flip = n[..., 2] > 0
    n = np.where((flip & ok)[..., None], -n, n)
    return n.astype(np.float64), ok


def normal_agreement(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> dict:
    if not mask.any():
        return {"n": 0}
    dot = np.einsum("ijk,ijk->ij", a, b)
    ang = np.degrees(np.arccos(np.clip(np.abs(dot), -1.0, 1.0)))
    sel = ang[mask]
    return {"n": int(sel.size), "mean_deg": float(sel.mean()),
            "median_deg": float(np.median(sel)), "p95_deg": float(np.percentile(sel, 95)),
            "max_deg": float(sel.max()),
            "fraction_over_5_deg": float((sel > 5.0).mean())}


# --------------------------------------------------------------------------------------
# scenes
# --------------------------------------------------------------------------------------
def mother_target(vessel_id: str = "V01"):
    mother = create_mother(vessel_id, "M01", default_params(vessel_id),
                           rng_for(f"mother_{vessel_id}"), mother_id=f"{vessel_id}-1024")
    return mother, rt.resolve_target(mother, None)


def pinhole_twin(profile):
    """Declared distortion-free twin of a profile (same optics, ideal pinhole).

    ``PINHOLE`` means *zero* coefficients, not five zeros: ``cameras.distort`` rejects a
    PINHOLE model that carries a coefficient vector.
    """
    return replace(profile, dist=np.zeros(0, dtype=np.float64),
                   meta={**profile.meta, "camera_model": "PINHOLE"})


def obs_spec(*, views: int, long_edge: int, renderer: str, policy: str,
             samples: int, workdir: str | None, supersample: int,
             profile, coc: dict[str, float]) -> ObsSpec:
    height = max(int(round(long_edge * 3.0 / 4.0)), 8)
    cfg = None
    if renderer == "blender":
        cfg = BlenderBackendConfig(samples=int(samples), filter_width=1.5, denoise=False,
                                   max_bounces=4, seed=20261001,
                                   coc_px_threshold=float(coc["worker_threshold_px"]),
                                   f_number=float(coc["f_number"]),
                                   raycast_samples=1500, distortion_policy="error",
                                   keep_workdir=True, previews=False, run_label="a12_1024")
        if workdir:
            cfg = replace(cfg, work_root=workdir)
    return ObsSpec(view_count=int(views), delivered_size=(int(long_edge), height),
                   max_render_pixels=int(long_edge) * height,
                   render_spec=RenderSpec(
                       supersample=int(supersample),
                       coc_px_threshold=float(coc["rasterizer_threshold_px"])),
                   master_seed=20261001, lineage_id="blender_route_wiring",
                   renderer=renderer, distortion_policy=policy, blender_config=cfg)


# --------------------------------------------------------------------------------------
# instrumented render
# --------------------------------------------------------------------------------------
def make_recorder(records_path: Path, target, *, stride: int, stage: str):
    """Wrap ``rt.render_view`` so each finished view is appended to a JSONL file.

    The per-view depth map and its depth-derived normals are saved next to the records, so
    the Blender/software comparison runs on exactly the arrays that were rendered.
    """
    original = rt.render_view
    vertices = np.asarray(target.mesh.vertices, dtype=np.float64)
    faces = np.asarray(target.mesh.faces, dtype=np.int64)

    def wrapper(scene, frame, **kwargs):
        t0 = time.perf_counter()
        render = original(scene, frame, **kwargs)
        wall = time.perf_counter() - t0
        record: dict[str, object] = {
            "view_id": frame.view_id,
            "backend": render.backend,
            "wall_seconds": wall,
            "worker_seconds": render.meta.get("worker_wall_seconds"),
            "worker_elapsed_seconds": render.meta.get("elapsed_seconds"),
            "render_seconds": render.meta.get("render_seconds"),
            "samples_requested": render.meta.get("samples_requested"),
            "samples_used": render.meta.get("samples_used"),
            "resolution": list(np.asarray(render.rgb_linear).shape[:2][::-1]),
            "product_bytes": int(sum(int(v.get("bytes", 0))
                                     for v in (render.meta.get("outputs") or {}).values())),
            "output_files": len(render.meta.get("outputs") or {}),
            "manifest_path": render.meta.get("manifest_path"),
        }
        depth = np.asarray(render.depth_z, dtype=np.float64)
        valid = np.isfinite(depth)
        record["depth"] = {
            "valid_fraction": float(valid.mean()),
            "min_mm": float(depth[valid].min()) if valid.any() else None,
            "median_mm": float(np.median(depth[valid])) if valid.any() else None,
            "max_mm": float(depth[valid].max()) if valid.any() else None,
        }
        id_map = np.asarray(render.id_map)
        visible = id_map >= 0
        classes = np.unique(id_map[visible]) if visible.any() else np.zeros(0)
        record["id"] = {
            "dtype": str(id_map.dtype),
            "is_integer_dtype": bool(np.issubdtype(id_map.dtype, np.integer)),
            "all_integral": bool(np.all(id_map == np.rint(id_map))),
            "visible_classes": int(classes.size),
            "visible_max_label": int(classes.max()) if classes.size else None,
            "background_is_minus_one": bool(np.all(id_map[~visible] == -1)),
            "labels_within_face_count": bool(classes.size == 0
                                             or int(classes.max()) < int(faces.shape[0])),
            "visible_fraction": float(visible.mean()),
        }
        uncertain = np.asarray(render.uncertain_mask, dtype=bool)
        record["uncertain"] = {
            "fraction_of_frame": float(uncertain.mean()),
            "fraction_of_object": float(uncertain[visible].mean()) if visible.any() else None,
            "components": _uncertain_components(render),
        }
        record["statistics_meta"] = {
            k: render.meta.get(k) for k in
            ("surface_visible_fraction", "uncertain_fraction", "id_classes_visible",
             "occluded_fraction", "target_visible_fraction", "depth_z_aa_std_mm")
        }
        record["checks"] = _compact_checks(render.meta.get("checks") or {})
        try:
            record["depth_vs_raycast"] = depth_reference_check(
                render, frame, vertices, faces, kwargs.get("object_pose"), stride=stride)
        except Exception as exc:  # noqa: BLE001 - the check must not hide the render
            record["depth_vs_raycast"] = {"error": f"{type(exc).__name__}: {exc}"}
        normals, nmask = depth_normals(depth, np.asarray(frame.K, dtype=np.float64))
        record["normal_coverage"] = float(nmask.mean())
        np.save(OUT_ROOT / f"normals_{stage}_{frame.view_id}.npy",
                np.where(nmask[..., None], normals, np.nan).astype(np.float32))
        np.save(OUT_ROOT / f"depth_{stage}_{frame.view_id}.npy",
                np.asarray(render.depth_z, dtype=np.float32))
        with records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        print(f"[view] {frame.view_id} {render.backend} wall={wall:.1f}s "
              f"worker={render.meta.get('worker_wall_seconds')}", flush=True)
        return render

    return original, wrapper


def selftest() -> dict:
    """Validate the *measurement* code against analytic geometry (no renderer involved)."""
    import trimesh

    size = (256, 192)
    box_mm, cam_z, fx = 100.0, -400.0, 400.0
    box = trimesh.creation.box(extents=(box_mm, box_mm, box_mm))
    K = np.array([[fx, 0.0, (size[0] - 1) / 2.0], [0.0, fx, (size[1] - 1) / 2.0],
                  [0.0, 0.0, 1.0]])
    T_WC = np.eye(4)
    T_WC[2, 3] = cam_z
    cast = cast_rays(K, T_WC, np.asarray(box.vertices), np.asarray(box.faces), size, 1)
    front_mm = abs(cam_z) - box_mm / 2.0                     # 350 mm
    z = cast["z_mm"]
    hit = np.isfinite(z)
    front = hit & (np.abs(z - front_mm) < 1e-6)
    # analytic silhouette: the front face is 100 mm wide at 350 mm with fx = 400 px
    width_px = box_mm * fx / front_mm
    xs = cast["x"][front]
    out = {
        "stage": "selftest",
        "analytic_front_mm": front_mm,
        "rays": int(z.size),
        "hit_fraction": float(hit.mean()),
        "front_pixels": int(front.sum()),
        "max_abs_error_front_mm": float(np.abs(z[front] - front_mm).max()),
        "analytic_width_px": width_px,
        "measured_width_px": (float(xs.max() - xs.min() + 1) if xs.size else 0.0),
        "min_z_mm": float(z[hit].min()) if hit.any() else None,
    }
    depth = np.full((size[1], size[0]), np.nan)
    depth[cast["y"], cast["x"]] = z
    normals, mask = depth_normals(depth, K)
    front_mask = (np.abs(depth - front_mm) < 1e-6) & mask
    n_front = normals[front_mask]
    out["front_normal_mean"] = (np.nanmean(n_front, axis=0).tolist()
                                if n_front.size else None)
    out["front_normal_max_angle_deg"] = (
        float(np.degrees(np.arccos(np.clip(np.nanmax(np.abs(n_front[:, 2])), -1, 1))))
        if n_front.size else None)
    (OUT_ROOT / "selftest.json").write_text(json.dumps(out, indent=2, sort_keys=True),
                                            encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True), flush=True)
    return out


def _uncertain_components(render) -> dict | None:
    """The worker's own per-rule counts for ``uncertain_mask`` (``channels.json``)."""
    out_dir = render.meta.get("output_dir")
    if not out_dir:
        return None
    path = Path(str(out_dir)) / "channels.json"
    if not path.is_file():
        return None
    try:
        channels = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = channels.get("uncertain_mask") or {}
    return {"components": entry.get("components"),
            "coc_threshold_px": entry.get("coc_threshold_px"),
            "f_number": entry.get("f_number"),
            "depth_edge_tol_mm": entry.get("depth_edge_tol_mm")}


def _compact_checks(checks: dict) -> dict:
    out: dict[str, object] = {}
    for key in ("camera_model", "raycast_vs_exact_pass", "exact_pass_integrality",
                "aa_pass_fractional", "rgb_background_linearity"):
        if key in checks:
            out[key] = checks[key]
    pas = checks.get("pass_aa_behaviour") or {}
    out["pass_aa_behaviour"] = {k: pas.get(k) for k in
                               ("shader_aov_pass_filtered", "z_pass_filtered",
                                "object_index_pass_filtered", "material_index_pass_usable")}
    return out


# --------------------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------------------
def run_stage(kind: str, *, views: int, long_edge: int, samples: int, vessel: str,
              supersample: int, stride: int, stage_name: str | None = None,
              profile_index: int = 1) -> dict:
    stage_name = stage_name or kind
    records_path = OUT_ROOT / f"{stage_name}_views.jsonl"
    if records_path.exists():
        records_path.unlink()
    mother, target = mother_target(vessel)
    profile = camera_profiles()[int(profile_index)]
    render_height = max(int(round(long_edge * 3.0 / 4.0)), 8)
    scale = min(1.0, (float(long_edge) * render_height
                      / float(profile.image_size[0] * profile.image_size[1])) ** 0.5)
    f_px = float(profile.K[0, 0]) * scale
    coc = dof_calibrated_threshold(focus_mm=float(profile.working_distance_mm),
                                   f_number=float(profile.f_number), f_px=f_px,
                                   dof_mm=tuple(profile.depth_of_field_mm))
    summary: dict[str, object] = {
        "stage": stage_name, "kind": kind, "views": int(views), "long_edge": int(long_edge),
        "vessel_id": vessel, "n_faces": int(target.n_faces),
        "profile_id": profile.profile_id, "profile_image_size": list(profile.image_size),
        "profile_camera_model": profile.meta.get("camera_model"),
        "profile_dist": np.asarray(profile.dist).tolist(),
        "profile_dof_mm": list(profile.depth_of_field_mm),
        "profile_working_distance_mm": float(profile.working_distance_mm),
        "coc_policy": coc,
        "blender_binary": rt.blender_binary(), "records": str(records_path),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if kind == "blender":
        # the requirement run: real profile, Blender, undistorted pinhole delivery
        spec = obs_spec(views=views, long_edge=long_edge, renderer="blender",
                        policy=rt.DISTORTION_POLICY_UNDISTORT, samples=samples,
                        workdir=None, supersample=supersample, profile=profile, coc=coc)
        run_profile = profile
    elif kind == "software":
        # the comparison run: the declared pinhole twin, same frames, software rasteriser
        spec = obs_spec(views=views, long_edge=long_edge, renderer="auto",
                        policy=rt.DISTORTION_POLICY_ERROR, samples=samples,
                        workdir=None, supersample=supersample, profile=profile, coc=coc)
        run_profile = pinhole_twin(profile)
        summary["profile_id"] = run_profile.profile_id + "+PINHOLE_TWIN"
    else:  # pragma: no cover - guarded by argparse
        raise SystemExit(f"unknown stage kind {kind!r}")
    summary["obs_spec"] = {
        "view_count": spec.view_count, "delivered_size": list(spec.delivered_size),
        "max_render_pixels": spec.max_render_pixels, "renderer": spec.renderer,
        "distortion_policy": spec.distortion_policy,
        "render_spec": {"supersample": spec.render_spec.supersample,
                        "coc_px_threshold": spec.render_spec.coc_px_threshold},
        "blender_samples": samples if kind == "blender" else None,
        "blender_coc_threshold_px": (spec.blender_config.coc_px_threshold
                                     if spec.blender_config is not None else None),
        "mm_per_pixel": float(profile.working_distance_mm / f_px),
    }
    original, wrapper = make_recorder(records_path, target, stride=stride, stage=stage_name)
    rt.render_view = wrapper
    t0 = time.perf_counter()
    try:
        # the same rng substream for both stages: the 12 frames must be identical, i.e. the
        # comparison isolates the renderer and not the view geometry
        obs, bundles = rt.route_ideal_visible(
            target, run_profile, spec, rng_for("render_1024"))
        summary["route_seconds"] = time.perf_counter() - t0
        summary["ok"] = True
        summary["observation"] = {
            "renderer": obs.meta.get("renderer"),
            "renderer_requested": obs.meta.get("renderer_requested"),
            "renderer_class": obs.meta.get("renderer_class"),
            "n_views": len(obs.views),
            "delivered_sizes": sorted({tuple(int(v) for v in np.asarray(v.rgb).shape[:2][::-1])
                                       for v in obs.views}),
            "n_points": int(np.asarray(obs.points).shape[0]),
            "normal_valid_fraction": float(np.asarray(obs.normal_valid).mean())
            if np.asarray(obs.normal_valid).size else None,
            "quality": obs.quality,
            "meta_renderer": obs.meta.get("renderer"),
            "meta_renderer_requested": obs.meta.get("renderer_requested"),
            "meta_renderer_backend": obs.meta.get("renderer_backend"),
            "meta_renderer_class": obs.meta.get("renderer_class"),
            "meta_distortion_policy": obs.meta.get("distortion_policy"),
            "backend_report": {k: obs.backend_report.get(k) for k in
                               ("route", "renderer_backend", "renderer_requested",
                                "renderer_class", "distortion_policy",
                                "depth_source", "voxel_mm", "backprojection_stride",
                                "render_mm_per_pixel", "delivered_mm_per_pixel")},
            "view_backends": [v.meta.get("render_backend") for v in obs.views],
            "view_frames": [{"view_id": v.view_id,
                             "K00": float(np.asarray(v.frame.K)[0, 0]),
                             "image_size": list(v.frame.image_size),
                             "camera_model": v.frame.camera_model,
                             "dist_none": v.frame.dist is None,
                             "tier": v.frame.tier,
                             "T_WC": np.asarray(v.frame.T_WC).tolist()}
                            for v in obs.views],
            "per_view_id_classes": [int(np.unique(v.id_map[v.id_map >= 0]).size)
                                    for v in obs.views],
            "per_view_uncertain_fraction": [float(np.mean(v.uncertain_mask))
                                            for v in obs.views],
            "per_view_depth_valid_fraction": [float(np.mean(np.isfinite(v.depth_z)))
                                              for v in obs.views],
            "per_view_roi_fraction": [float(np.mean(v.roi)) if v.roi is not None else None
                                      for v in obs.views],
            "per_view_deployment_mask_fraction": [float(np.mean(v.deployment_mask))
                                                  for v in obs.views],
        }
        np.save(OUT_ROOT / f"{stage_name}_points.npy",
                np.asarray(obs.points, dtype=np.float32))
    except SynLabError as exc:
        summary["ok"] = False
        summary["error"] = {"code": str(exc.code), "stage": exc.stage,
                            "message": exc.message[:600],
                            "measurements": exc.measurements}
    except Exception as exc:  # noqa: BLE001 - record, never fake
        summary["ok"] = False
        summary["error"] = {"code": "UNEXPECTED", "message": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc()[-1500:]}
        summary["route_seconds"] = time.perf_counter() - t0
    finally:
        rt.render_view = original
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()
               if line.strip()] if records_path.exists() else []
    summary["n_view_records"] = len(records)
    summary["per_view_wall_seconds"] = [r["wall_seconds"] for r in records]
    summary["total_view_wall_seconds"] = float(sum(r["wall_seconds"] for r in records))
    summary["total_product_bytes"] = int(sum(r["product_bytes"] for r in records))
    (OUT_ROOT / f"{stage_name}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "observation"},
                     indent=2, sort_keys=True, default=str)[:4000], flush=True)
    return summary


def probe(*, long_edge: int, samples: int, vessel: str, stride: int,
          profile_index: int = 1) -> dict:
    """One-view timing probe at the production resolution."""
    return run_stage("blender", views=1, long_edge=long_edge, samples=samples, vessel=vessel,
                     supersample=1, stride=stride, stage_name="probe",
                     profile_index=profile_index)


def phase_search(render, frame, vertices, faces, *, phases=((0.5, 0.5), (0.0, 0.0),
                                                            (1.0, 1.0), (0.5, 0.0),
                                                            (0.0, 0.5))) -> list[dict]:
    """Which sampling phase of the pixel grid reproduces the delivered depth pass?

    On a planar slanted face the camera z is linear in the pixel coordinate, so the phase
    that minimises ``|render - ray(phase)|`` is the phase the renderer actually sampled.
    ``(0.5, 0.5)`` is the project's declared OpenCV pixel-centre convention.
    """
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    K0 = np.asarray(frame.K, dtype=np.float64)
    depth = np.asarray(render.depth_z, dtype=np.float64)
    rows: list[dict] = []
    for phase in phases:
        K = K0.copy()
        # a ray through the point (x + phase) in the original K is the ray through
        # (x + 0.5) in a frame whose principal point is shifted by (0.5 - phase)
        K[0, 2] += 0.5 - float(phase[0])
        K[1, 2] += 0.5 - float(phase[1])
        cast = cast_rays(K, np.asarray(frame.T_WC, dtype=np.float64), vertices, faces,
                         (width, height), 1)
        face_grid = np.full((height, width), -1, dtype=np.int64)
        face_grid[cast["y"], cast["x"]] = cast["face"]
        same = np.ones_like(face_grid, dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                same &= (np.roll(np.roll(face_grid, -dy, axis=0), -dx, axis=1) == face_grid)
        sel = (same & (face_grid >= 0))[cast["y"], cast["x"]] \
            & np.isfinite(cast["z_mm"]) & np.isfinite(depth[cast["y"], cast["x"]])
        if not sel.any():
            continue
        delta = np.abs(depth[cast["y"], cast["x"]][sel] - cast["z_mm"][sel])
        rows.append({"phase_px": [float(phase[0]), float(phase[1])],
                     "n": int(sel.sum()), "median_mm": float(np.median(delta)),
                     "mean_mm": float(delta.mean()), "max_mm": float(delta.max())})
    rows.sort(key=lambda r: r["mean_mm"])
    return rows


def fixture_per_face(render, frame, vertices, faces, *, margin_px: int = 1) -> dict:
    """Delta statistics restricted to the *interior* of each planar face.

    The reference is the exact pixel-centre ray cast: on a planar triangle the camera-frame
    z of the pixel-centre hit is the analytically correct value for that pixel, so any
    deviation is a renderer property (screen-space interpolation, filtering, ...), not a
    sub-pixel sampling ambiguity.  A pixel counts as face interior when its whole 3x3
    neighbourhood hits the very same triangle.
    """
    cast = cast_rays(np.asarray(frame.K, dtype=np.float64),
                     np.asarray(frame.T_WC, dtype=np.float64),
                     np.asarray(vertices, dtype=np.float64), np.asarray(faces),
                     tuple(int(v) for v in frame.image_size), 1)
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    face_grid = np.full((height, width), -1, dtype=np.int64)
    z_grid = np.full((height, width), np.nan, dtype=np.float64)
    face_grid[cast["y"], cast["x"]] = cast["face"]
    z_grid[cast["y"], cast["x"]] = cast["z_mm"]
    depth = np.asarray(render.depth_z, dtype=np.float64)
    same = np.ones((height, width), dtype=bool)
    for dy in range(-margin_px, margin_px + 1):
        for dx in range(-margin_px, margin_px + 1):
            shifted = np.roll(np.roll(face_grid, -dy, axis=0), -dx, axis=1)
            same &= (shifted == face_grid)
    interior = same & (face_grid >= 0) & np.isfinite(z_grid) & np.isfinite(depth)
    delta = np.abs(depth - z_grid)
    per_face: list[dict] = []
    for face_id in np.unique(face_grid[interior]):
        sel = interior & (face_grid == int(face_id))
        per_face.append({"face": int(face_id), "pixels": int(sel.sum()),
                         "max_abs_error_mm": float(delta[sel].max()),
                         "mean_abs_error_mm": float(delta[sel].mean()),
                         "p99_abs_error_mm": float(np.percentile(delta[sel], 99))})
    per_face.sort(key=lambda e: -e["pixels"])
    return {"interior_pixels_total": int(interior.sum()),
            "max_abs_error_mm": float(delta[interior].max()) if interior.any() else None,
            "mean_abs_error_mm": float(delta[interior].mean()) if interior.any() else None,
            "per_face_top": per_face[:6],
            "faces_covered": len(per_face)}


def fixture(*, samples: int, samples_sw: int = 1, tilt: bool = False,
            out_name: str = "fixture.json") -> dict:
    """Analytic box fixture at 1024 px: depth vs an exactly known plane distance.

    ``tilt=True`` rotates the box (45 deg about Z, 20 deg about X) so that the visible
    triangles are *slanted*: a planar face is still analytically exact, but a renderer that
    interpolates z linearly in screen space (instead of 1/z) must now deviate, while a
    ray-traced Z pass cannot.
    """
    import trimesh

    from synlab.observe.render import build_scene
    from synlab.schemas.runtime import ViewFrame

    size = (1024, 768)
    box_mm = 100.0
    cam_z = -400.0
    fx = 1200.0
    box = trimesh.creation.box(extents=(box_mm, box_mm, box_mm))
    if tilt:
        box.apply_transform(trimesh.transformations.rotation_matrix(
            np.deg2rad(45.0), [0.0, 0.0, 1.0]))
        box.apply_transform(trimesh.transformations.rotation_matrix(
            np.deg2rad(20.0), [1.0, 0.0, 0.0]))
    faces = np.asarray(box.faces)
    scene = build_scene(box, surface_tag=np.zeros(faces.shape[0], dtype=np.int16),
                        face_id=np.arange(faces.shape[0]), name="fixture_box")
    K = np.array([[fx, 0.0, (size[0] - 1) / 2.0],
                  [0.0, fx, (size[1] - 1) / 2.0], [0.0, 0.0, 1.0]])
    frame = ViewFrame(view_id="fixture_box_1024", K=K,
                      T_WC=np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                                     [0.0, 0.0, 1.0, cam_z], [0.0, 0.0, 0.0, 1.0]]),
                      image_size=size, profile_id="fixture", tier="GLOBAL",
                      u_position_mm=0.0, working_distance_mm=abs(cam_z),
                      focus_setting="FIXED", source_kind="SENSOR_SIM",
                      camera_model="PINHOLE", dist=None)
    light = rt.ObsSpec().resolved_light()
    #: The Blender adapter only writes the imported object's ``matrix_world`` when an object
    #: pose is supplied; with ``object_pose=None`` Blender's PLY importer keeps its own axis
    #: rotation (measured: 180 deg about Z for the declared ``forward=NEGATIVE_Y``).  Every
    #: observation route passes the turntable pose, so it is not affected - but this fixture
    #: must pass an explicit identity pose to compare the two backends on the same geometry.
    identity_pose = np.eye(4)
    out: dict[str, object] = {"stage": "fixture", "tilt": bool(tilt), "size": list(size),
                              "fx": fx, "box_mm": box_mm, "object_pose": "identity",
                              "analytic_front_mm": abs(cam_z) - box_mm / 2.0,
                              "analytic_half_width_px": box_mm * fx / (abs(cam_z) - box_mm / 2.0)
                              / 2.0}
    results: dict[str, object] = {}
    for name, backend, cfg in (("blender", BACKEND_BLENDER,
                                BlenderBackendConfig(samples=int(samples), filter_width=1.5,
                                                     f_number=8.0, coc_px_threshold=0.75,
                                                     raycast_samples=600, previews=False,
                                                     run_label="fixture_1024")),
                               ("software", rt.BACKEND_SOFTWARE, None)):
        t0 = time.perf_counter()
        render = rt.render_view(scene, frame, light=light,
                                spec=RenderSpec(supersample=int(samples_sw),
                                                coc_px_threshold=0.75 * 8.0),
                                object_pose=identity_pose,
                                focus_distance_mm=frame.working_distance_mm,
                                backend=backend, blender_config=cfg)
        seconds = time.perf_counter() - t0
        depth = np.asarray(render.depth_z, dtype=np.float64)
        geom = np.isfinite(depth)
        front = geom & (np.abs(depth - out["analytic_front_mm"]) < 1.0)
        ys, xs = np.nonzero(front)
        width_px = float(xs.max() - xs.min() + 1) if xs.size else 0.0
        height_px = float(ys.max() - ys.min() + 1) if ys.size else 0.0
        results[name] = {
            "seconds": seconds,
            "backend": render.backend,
            "samples_used": render.meta.get("samples_used"),
            "depth_front_max_abs_error_mm": (float(np.abs(depth[front]
                                                          - out["analytic_front_mm"]).max())
                                             if front.any() else None),
            "depth_front_rms_error_mm": (float(np.sqrt(np.mean((depth[front]
                                                                 - out["analytic_front_mm"])
                                                                ** 2)))
                                         if front.any() else None),
            "front_pixels": int(front.sum()),
            "front_width_px": width_px, "front_height_px": height_px,
            "front_width_error_px": width_px - 2.0 * out["analytic_half_width_px"],
            "id_classes_visible": int(np.unique(render.id_map[geom]).size),
            "uncertain_fraction": float(np.mean(render.uncertain_mask)),
            "depth_vs_raycast": depth_reference_check(
                render, frame, np.asarray(box.vertices), faces, identity_pose, stride=4),
            "depth_vs_raycast_per_face": fixture_per_face(
                render, frame, np.asarray(box.vertices), faces),
            "phase_search": phase_search(render, frame, np.asarray(box.vertices), faces),
        }
    out["backends"] = results
    data = np.asarray(box.vertices)
    out["analytic_checks"] = {
        "front_plane_distance_mm": out["analytic_front_mm"],
        "cube_bbox_mm": [float(v) for v in (data.max(axis=0) - data.min(axis=0))],
    }
    (OUT_ROOT / out_name).write_text(json.dumps(out, indent=2, sort_keys=True),
                                     encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True)[:6000], flush=True)
    return out


def _coc_band(depth_path: Path, *, focus_mm: float, f_px: float, f_number: float,
              threshold_px: float) -> dict | None:
    """Fraction of object pixels inside a ``coc <= threshold`` focus band (from depth only)."""
    if not depth_path.exists():
        return None
    depth = np.load(depth_path).astype(np.float64)
    valid = np.isfinite(depth) & (depth > 0)
    if not valid.any():
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        coc = np.abs(f_px ** 2 / (f_number * depth) * (depth - focus_mm) / focus_mm)
    inside = valid & (coc <= float(threshold_px))
    z = depth[valid]
    return {"object_pixels": int(valid.sum()),
            "inside_focus_band_fraction": float(inside.sum() / valid.sum()),
            "z_p05_mm": float(np.percentile(z, 5)), "z_p95_mm": float(np.percentile(z, 95)),
            "threshold_px": float(threshold_px), "f_number": float(f_number)}


def compare() -> dict:
    """Per-view + cloud comparison of the Blender and software stages."""
    blender_records = _load_records("blender")
    software_records = _load_records("software")
    blender_summary = json.loads((OUT_ROOT / "blender.json").read_text(encoding="utf-8"))
    software_summary = json.loads((OUT_ROOT / "software.json").read_text(encoding="utf-8"))
    out: dict[str, object] = {"stage": "compare",
                              "blender": _stage_totals(blender_records, blender_summary),
                              "software": _stage_totals(software_records, software_summary)}
    by_view_b = {r["view_id"]: r for r in blender_records}
    by_view_s = {r["view_id"]: r for r in software_records}
    frames_b = {f["view_id"]: f for f in
                blender_summary.get("observation", {}).get("view_frames", [])}
    frames_s = {f["view_id"]: f for f in
                software_summary.get("observation", {}).get("view_frames", [])}
    per_view: list[dict[str, object]] = []
    for view_id in sorted(set(by_view_b) & set(by_view_s)):
        b, s = by_view_b[view_id], by_view_s[view_id]
        fb, fs = frames_b.get(view_id), frames_s.get(view_id)
        entry = {
            "view_id": view_id,
            "blender_wall_seconds": b["wall_seconds"],
            "software_wall_seconds": s["wall_seconds"],
            "blender_depth_median_mm": b["depth"]["median_mm"],
            "software_depth_median_mm": s["depth"]["median_mm"],
            "blender_id_classes": b["id"]["visible_classes"],
            "software_id_classes": s["id"]["visible_classes"],
            "blender_uncertain_fraction": b["uncertain"]["fraction_of_frame"],
            "software_uncertain_fraction": s["uncertain"]["fraction_of_frame"],
            "blender_visible_fraction": b["id"]["visible_fraction"],
            "software_visible_fraction": s["id"]["visible_fraction"],
            "blender_depth_vs_raycast_interior_max_mm":
                (b["depth_vs_raycast"] or {}).get("interior_max_abs_error_mm"),
            "software_depth_vs_raycast_interior_max_mm":
                (s["depth_vs_raycast"] or {}).get("interior_max_abs_error_mm"),
            "same_frame": bool(fb and fs and fb["K00"] == fs["K00"]
                               and fb["image_size"] == fs["image_size"]
                               and np.allclose(np.asarray(fb["T_WC"], dtype=np.float64),
                                               np.asarray(fs["T_WC"], dtype=np.float64))),
        }
        per_view.append(entry)
    out["per_view"] = per_view
    view_ids = [e["view_id"] for e in per_view]
    out["depth_agreement"] = _depth_agreement(view_ids)
    out["normal_agreement"] = _normal_agreement(view_ids)
    out["cloud"] = _cloud_agreement()
    # -- mask coverage under the two declared CoC conventions, from the depth maps alone
    blender_summary = json.loads((OUT_ROOT / "blender.json").read_text(encoding="utf-8"))
    coc = blender_summary.get("coc_policy", {})
    focus = float(coc.get("focus_mm", 0.0))
    f_px = float(coc.get("f_px", 0.0))
    f_number = float(coc.get("f_number", 1.0))
    out["focus_band"] = {
        "dof_calibrated_threshold_px": coc.get("worker_threshold_px"),
        "pipeline_convention_threshold_px": DECLARED_COC_PX,
        "dof_mm": coc.get("dof_mm"),
        "focus_mm": focus,
        "blender_pipeline_convention": [
            _coc_band(OUT_ROOT / f"depth_blender_{v}.npy", focus_mm=focus, f_px=f_px,
                      f_number=f_number, threshold_px=float(DECLARED_COC_PX))
            for v in view_ids],
        "blender_dof_calibrated": [
            _coc_band(OUT_ROOT / f"depth_blender_{v}.npy", focus_mm=focus, f_px=f_px,
                      f_number=f_number,
                      threshold_px=float(coc.get("worker_threshold_px") or DECLARED_COC_PX))
            for v in view_ids],
    }
    out["all_frames_identical"] = bool(per_view) and all(e["same_frame"] for e in per_view)
    (OUT_ROOT / "compare.json").write_text(json.dumps(out, indent=2, sort_keys=True,
                                                      default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True, default=str)[:6000], flush=True)
    return out


def _load_records(stage: str) -> list[dict]:
    path = OUT_ROOT / f"{stage}_views.jsonl"
    if not path.exists():
        raise SystemExit(f"missing {path}; run --stage {stage} first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _stage_totals(records: list[dict], summary: dict) -> dict:
    obs = summary.get("observation", {})
    return {
        "n_views": len(records),
        "renderer": obs.get("renderer"),
        "delivered_sizes": obs.get("delivered_sizes"),
        "total_view_wall_seconds": float(sum(r["wall_seconds"] for r in records)),
        "per_view_wall_seconds": [r["wall_seconds"] for r in records],
        "mean_view_wall_seconds": (float(np.mean([r["wall_seconds"] for r in records]))
                                   if records else None),
        "min_max_view_wall_seconds": ([float(np.min([r["wall_seconds"] for r in records])),
                                       float(np.max([r["wall_seconds"] for r in records]))]
                                      if records else None),
        "total_product_bytes": int(sum(r["product_bytes"] for r in records)),
        "mean_product_bytes": (int(np.mean([r["product_bytes"] for r in records]))
                               if records else None),
        "samples_used": sorted({r["samples_used"] for r in records}),
        "resolution": sorted({tuple(r["resolution"]) for r in records}),
        "id_is_integer_dtype": all(r["id"]["is_integer_dtype"] for r in records),
        "id_all_integral": all(r["id"]["all_integral"] for r in records),
        "id_classes_visible": [r["id"]["visible_classes"] for r in records],
        "id_background_is_minus_one": all(r["id"]["background_is_minus_one"]
                                          for r in records),
        "id_labels_within_face_count": all(r["id"]["labels_within_face_count"]
                                           for r in records),
        "uncertain_fraction_of_frame": [r["uncertain"]["fraction_of_frame"]
                                        for r in records],
        "depth_vs_raycast_interior_max_mm": [
            (r["depth_vs_raycast"] or {}).get("interior_max_abs_error_mm")
            for r in records],
        "exact_pass_non_integral_px": [
            ((r.get("checks") or {}).get("exact_pass_integrality") or {}).get(
                "face_id_non_integral") for r in records],
        "route_seconds": summary.get("route_seconds"),
        "n_points": obs.get("n_points"),
        "normal_valid_fraction": obs.get("normal_valid_fraction"),
        "per_view_roi_fraction": obs.get("per_view_roi_fraction"),
        "per_view_deployment_mask_fraction": obs.get("per_view_deployment_mask_fraction"),
        "quality_keys": sorted((obs.get("quality") or {}).keys()),
        "quality": obs.get("quality"),
        "ok": summary.get("ok"),
        "error": summary.get("error"),
    }


def _depth_agreement(view_ids: list[str]) -> dict:
    """Blender vs software depth on exactly the same pixels (per view)."""
    out: list[dict] = []
    for view_id in view_ids:
        b_path = OUT_ROOT / f"depth_blender_{view_id}.npy"
        s_path = OUT_ROOT / f"depth_software_{view_id}.npy"
        if not (b_path.exists() and s_path.exists()):
            continue
        b = np.load(b_path)
        s = np.load(s_path)
        if b.shape != s.shape:
            out.append({"view_id": view_id, "error": f"shape {b.shape} vs {s.shape}"})
            continue
        both = np.isfinite(b) & np.isfinite(s)
        if not both.any():
            continue
        delta = np.abs(b[both].astype(np.float64) - s[both].astype(np.float64))
        out.append({"view_id": view_id, "n_pixels": int(both.sum()),
                    "mean_abs_mm": float(delta.mean()),
                    "median_abs_mm": float(np.median(delta)),
                    "p99_abs_mm": float(np.percentile(delta, 99)),
                    "max_abs_mm": float(delta.max()),
                    "fraction_within_0p05mm": float((delta <= 0.05).mean()),
                    "fraction_within_0p5mm": float((delta <= 0.5).mean()),
                    "fraction_over_5mm": float((delta > 5.0).mean()),
                    "background_disagreement_px": int(np.count_nonzero(
                        np.isfinite(b) != np.isfinite(s))),
                    "background_disagreement_fraction": float(np.mean(
                        np.isfinite(b) != np.isfinite(s)))})
    ok = [e for e in out if "max_abs_mm" in e]
    return {"per_view": out,
            "max_abs_mm": max((e["max_abs_mm"] for e in ok), default=None),
            "mean_abs_mm": float(np.mean([e["mean_abs_mm"] for e in ok])) if ok else None,
            "max_background_disagreement_fraction": (
                max((e["background_disagreement_fraction"] for e in ok), default=None))}


def _normal_agreement(view_ids: list[str]) -> dict:
    out: list[dict] = []
    for view_id in view_ids:
        a_path = OUT_ROOT / f"normals_blender_{view_id}.npy"
        b_path = OUT_ROOT / f"normals_software_{view_id}.npy"
        if not (a_path.exists() and b_path.exists()):
            continue
        a = np.load(a_path).astype(np.float64)
        b = np.load(b_path).astype(np.float64)
        valid = np.isfinite(a).all(axis=-1) & np.isfinite(b).all(axis=-1)
        out.append({"view_id": view_id, **normal_agreement(a, b, valid)})
    ok = [e for e in out if e.get("n")]
    return {"per_view": out,
            "mean_deg": float(np.mean([e["mean_deg"] for e in ok])) if ok else None,
            "median_deg": float(np.median([e["median_deg"] for e in ok])) if ok else None,
            "max_deg": max((e["max_deg"] for e in ok), default=None)}


def _cloud_agreement() -> dict:
    b_path = OUT_ROOT / "blender_points.npy"
    s_path = OUT_ROOT / "software_points.npy"
    if not (b_path.exists() and s_path.exists()):
        return {"available": False}
    from scipy.spatial import cKDTree

    b = np.load(b_path).astype(np.float64)
    s = np.load(s_path).astype(np.float64)
    rng = np.random.default_rng(0)
    n = min(20_000, b.shape[0], s.shape[0])
    if n == 0:
        return {"available": False}
    bi = b[rng.choice(b.shape[0], n, replace=False)]
    si = s[rng.choice(s.shape[0], n, replace=False)]
    dist_bs, _ = cKDTree(s).query(bi)
    dist_sb, _ = cKDTree(b).query(si)
    return {"available": True, "n_points_blender": int(b.shape[0]),
            "n_points_software": int(s.shape[0]), "n_sampled": int(n),
            "blender_to_software_mm": {"median": float(np.median(dist_bs)),
                                       "p95": float(np.percentile(dist_bs, 95)),
                                       "max": float(dist_bs.max())},
            "software_to_blender_mm": {"median": float(np.median(dist_sb)),
                                       "p95": float(np.percentile(dist_sb, 95)),
                                       "max": float(dist_sb.max())}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="probe",
                        choices=("selftest", "probe", "blender", "software", "compare",
                                 "fixture"))
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--long-edge", type=int, default=1024)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--supersample", type=int, default=1)
    parser.add_argument("--raycast-stride", type=int, default=16)
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--profile-index", type=int, default=1,
                        help="index into camera_profiles(); 1 = the profile the batch "
                             "pipeline resolves by default (observe(profile=None))")
    parser.add_argument("--tilt", action="store_true",
                        help="fixture stage: use the 45/20 deg rotated (slanted) box")
    args = parser.parse_args(argv)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if args.stage == "selftest":
        selftest()
    elif args.stage == "probe":
        probe(long_edge=args.long_edge, samples=args.samples, vessel=args.vessel,
              stride=args.raycast_stride, profile_index=args.profile_index)
    elif args.stage == "blender":
        run_stage("blender", views=args.views, long_edge=args.long_edge,
                  samples=args.samples, vessel=args.vessel, supersample=args.supersample,
                  stride=args.raycast_stride, profile_index=args.profile_index)
    elif args.stage == "software":
        run_stage("software", views=args.views, long_edge=args.long_edge,
                  samples=args.samples, vessel=args.vessel, supersample=args.supersample,
                  stride=args.raycast_stride, profile_index=args.profile_index)
    elif args.stage == "compare":
        compare()
    else:
        fixture(samples=args.samples, tilt=bool(args.tilt),
                out_name="fixture_tilted.json" if args.tilt else "fixture.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
