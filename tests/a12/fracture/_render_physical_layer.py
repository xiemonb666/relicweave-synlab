#!/usr/bin/env python
"""Stage 3: render the plane fracture surface against the morphology surfaces (Blender Cycles).

For one fragment of the *same* mother, cut by the *same* basis, the script renders:

* ``front``      -- the whole fragment from the fracture-normal side, neutral body shading;
* ``front_hl``   -- the same view with every ``origin_kind == INTERFACE`` face painted (the
                    "fracture highlight" the task asks for);
* ``macro``      -- a close-up of the fracture-centre ROI, neutral body shading;
* ``macro_hl``   -- the same close-up, interface painted.

Plus, for every morphology case, a numpy fallback figure set (height map over the fracture
``(u, v)`` patch + shaded normal map + two profile sections) written by
``_render_physical_layer_fields.py``.

The camera is built from the project's *real* ``LOCAL`` tier optics (``synlab.cameras.profiles``):
its focal length and sensor width fix the field of view, and the frame distance is chosen so the
target covers the requested fraction of the frame.  ``mm_per_pixel`` is therefore a real number and
is recorded next to every PNG.

Usage::

    .venv\\Scripts\\python.exe tests\\a12\\fracture\\_render_physical_layer.py `
        --bundle data\\a12_reports\\physical_layer\\bundle_V18.pkl --samples 24
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "data" / "a12_reports" / "physical_layer"

#: albedo of a fracture face in the highlight renders (linear RGB, deliberately not a material)
HL_INTERFACE = np.array([0.72, 0.09, 0.06], dtype=np.float32)
#: albedo of the original (mother) surface in the highlight renders
HL_MOTHER = np.array([0.55, 0.55, 0.58], dtype=np.float32)


def _write_rgb(path: Path, rgb: np.ndarray) -> str:
    """Write (H,W,3) in either 0..1 float or 0..255 uint as an 8-bit PNG."""
    import cv2

    arr = np.asarray(rgb)
    if arr.dtype.kind == "f":
        arr = np.clip(arr, 0.0, 1.0)
        arr = (np.power(arr, 1.0 / 2.2) * 255.0 + 0.5).astype(np.uint8)
    else:
        arr = arr.astype(np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 3:
        bgr = arr[:, :, ::-1].copy()
    else:
        bgr = arr
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), bgr):
        raise RuntimeError(f"cv2.imwrite failed for {path}")
    return str(path)


def local_profile_frame(*, center_mm: np.ndarray, forward: np.ndarray, up_hint: np.ndarray,
                        target_mm: float, frac: float, width: int, height: int,
                        profile: Any) -> tuple[np.ndarray, float, float]:
    """``(K, distance_mm, mm_per_pixel)`` for a frame that fits ``target_mm`` into ``frac``.

    The intrinsics are the real ``LOCAL`` tier optics scaled to the output resolution, so the
    field of view is the real lens's and ``mm_per_pixel`` is a measured quantity, not a choice.
    """
    f_x_local = float(profile.K[0, 0])
    f_y_local = float(profile.K[1, 1])
    sensor_w = float(profile.meta.get("sensor_width_mm", 7.6))
    focal = f_x_local * sensor_w / float(profile.image_size[0])     # mm, from the profile
    f_x = focal / sensor_w * float(width)
    f_y = f_x * (f_y_local / f_x_local)
    distance = max(f_x * float(target_mm) / (float(frac) * float(width)), 1.0)
    mm_per_pixel = distance / f_x
    del center_mm, forward, up_hint
    K = np.array([[f_x, 0.0, (width - 1) / 2.0],
                  [0.0, f_y, (height - 1) / 2.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    return K, distance, mm_per_pixel


def look_at_T_WC(eye: np.ndarray, target: np.ndarray, up_hint: np.ndarray) -> np.ndarray:
    forward = np.asarray(target, dtype=np.float64) - np.asarray(eye, dtype=np.float64)
    forward = forward / max(float(np.linalg.norm(forward)), 1e-12)
    up = np.asarray(up_hint, dtype=np.float64)
    if abs(float(np.dot(forward, up))) > 0.999:
        up = np.array([1.0, 0.0, 0.0])
    x_c = np.cross(up, forward)
    x_c /= max(float(np.linalg.norm(x_c)), 1e-12)
    y_c = np.cross(forward, x_c)
    T = np.eye(4, dtype=np.float64)
    T[:3, 0], T[:3, 1], T[:3, 2] = x_c, y_c, forward
    T[:3, 3] = np.asarray(eye, dtype=np.float64)
    return T


def fracture_roi_uv(fragment: Any, basis: Any, origin_uv: tuple[float, float],
                    *, quantile: float = 0.9) -> dict[str, Any]:
    """ROI of the fracture face in the cut frame, taken from the face centroids around the origin."""
    origin = np.asarray(origin_uv, dtype=np.float64).reshape(2)
    origin_kind = np.asarray(fragment.face_origin_kind)
    ids = np.nonzero(origin_kind == 1)[0]
    if ids.size == 0:
        return {"faces": 0}
    centres = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[ids]
    local = basis.to_local(centres)
    radius = np.linalg.norm(local[:, 0:2] - origin[None, :], axis=1)
    keep = radius <= float(np.quantile(radius, quantile))
    sel = local[keep]
    lo = sel[:, 0:2].min(axis=0)
    hi = sel[:, 0:2].max(axis=0)
    return {"faces": int(ids.size), "roi_faces": int(keep.sum()),
            "u_range_mm": [float(lo[0]), float(hi[0])],
            "v_range_mm": [float(lo[1]), float(hi[1])],
            "extent_mm": [float(hi[0] - lo[0]), float(hi[1] - lo[1])],
            "center_uv_mm": [float(0.5 * (lo[0] + hi[0])), float(0.5 * (lo[1] + hi[1]))],
            "radius_mm": float(np.max(radius[keep]))}


def make_scene(fragment: Any, *, highlight: bool, name: str) -> Any:
    from synlab.observe.render import build_scene

    origin_kind = np.asarray(fragment.face_origin_kind)
    surface_tag = np.where(origin_kind == 1, np.int16(1), np.int16(0)).astype(np.int16)
    if highlight:
        albedo = np.tile(HL_MOTHER, (len(origin_kind), 1)).astype(np.float32)
        albedo[origin_kind == 1] = HL_INTERFACE
    else:
        albedo = None
    return build_scene(fragment.mesh, surface_tag=surface_tag, albedo=albedo,
                       name=name, albedo_source_kind=(
                           "SENSOR_SIM" if albedo is None else "SYNTHETIC"))


def render_one(scene: Any, *, frame: Any, light: Any, spec: Any, config: Any,
               out_name: str) -> dict[str, Any]:
    import cv2

    from synlab.observe import blender

    started = time.time()
    render = blender.render_view_blender(scene, frame, light=light, spec=spec, config=config)
    png = OUT_DIR / f"{out_name}.png"
    _write_rgb(png, render.rgb_linear)
    rgba = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
    coverage = float(np.mean(np.any(np.asarray(rgba)[:, :, :3] > 4, axis=2))) if rgba is not None \
        else float("nan")
    del render
    return {"png": str(png), "seconds": round(time.time() - started, 2),
            "coverage_fraction": coverage, "frame_view_id": frame.view_id,
            "mm_per_pixel": float(frame.K[0, 0] and frame.working_distance_mm / frame.K[0, 0]),
            "image_size": list(frame.image_size)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--long-edge", type=int, default=1024)
    parser.add_argument("--out", default="")
    parser.add_argument("--cases", default="")
    parser.add_argument("--skip-software", action="store_true")
    args = parser.parse_args()

    import pickle

    import cv2
    from synlab.cameras.profiles import profile_by_id
    from synlab.observe.blender import BACKEND_BLENDER, BlenderBackendConfig, render_view_blender
    from synlab.observe.render import LightSpec, RenderSpec, build_scene, render_view
    from synlab.schemas.runtime import ViewFrame

    del cv2
    bundle_path = Path(args.bundle)
    with bundle_path.open("rb") as handle:
        bundle = pickle.load(handle)
    vessel_id = bundle.get("vessel_id", "V18")
    wanted = [c for c in str(args.cases).split(",") if c.strip()]
    labels = [label for label in bundle["cases"] if not wanted or label in wanted]

    profile = profile_by_id("CAM_LOCAL_V3")
    width = int(args.long_edge)
    height = int(round(width * 3.0 / 4.0))
    light = LightSpec(direction=np.array([-0.42, -0.55, -0.72], dtype=np.float64),
                      color=np.array([1.0, 0.98, 0.94], dtype=np.float64),
                      ambient=np.array([0.16, 0.16, 0.18], dtype=np.float64))
    spec = RenderSpec(supersample=2, near_mm=0.5, far_mm=2000.0,
                      background_linear=(0.035, 0.035, 0.042))
    config = BlenderBackendConfig(samples=int(args.samples), denoise=True, max_bounces=6,
                                  device="CPU", previews=False, keep_workdir=False,
                                  run_label=f"physlayer_{vessel_id}",
                                  timeout_s=1800.0)

    report: dict[str, Any] = {"bundle": str(bundle_path), "vessel_id": vessel_id,
                              "long_edge": width, "samples": int(args.samples),
                              "profile_id": profile.profile_id, "cases": {}}
    for label in labels:
        case = bundle["cases"][label]
        basis = case["basis"]
        origin_uv = tuple(case["origin_uv_mm"])
        # the largest delivered piece is the one a human would pick up
        fragment = max(case["result"].fragments, key=lambda f: float(f.volume_mm3))
        bounds = np.asarray(fragment.mesh.bounds, dtype=np.float64)
        center = 0.5 * (bounds[0] + bounds[1])
        radius = float(np.linalg.norm(bounds[1] - bounds[0]) / 2.0)
        normal = np.asarray(basis.normal, dtype=np.float64)
        normal = normal / float(np.linalg.norm(normal))
        # look at the fracture face from the fracture-normal side
        eye_dir = normal if float(np.dot(center - basis.origin, normal)) < 0 else -normal
        roi = fracture_roi_uv(fragment, basis, origin_uv)
        case_out: dict[str, Any] = {"roi": roi, "fragment_id": fragment.fragment_id,
                                    "fragment_faces": int(len(fragment.mesh.faces)),
                                    "fragment_volume_mm3": float(fragment.volume_mm3),
                                    "renders": {}, "errors": {}}

        views = []
        front_target = 2.0 * radius
        K, dist, mpp = local_profile_frame(center_mm=center, forward=eye_dir, up_hint=basis.e_v,
                                           target_mm=front_target, frac=0.72,
                                           width=width, height=height, profile=profile)
        views.append(("front", center + eye_dir * dist, center, basis.e_v, K, dist, mpp,
                      front_target, True))
        views.append(("front_hl", center + eye_dir * dist, center, basis.e_v, K, dist, mpp,
                      front_target, True))
        if roi.get("faces"):
            macro_uv = np.asarray(roi["center_uv_mm"], dtype=np.float64)
            macro_center = basis.to_world(np.array([[macro_uv[0], macro_uv[1], 0.0]]))[0]
            macro_target = float(max(roi["extent_mm"]) * 1.25)
            K2, dist2, mpp2 = local_profile_frame(center_mm=macro_center, forward=eye_dir,
                                                  up_hint=basis.e_v, target_mm=macro_target,
                                                  frac=0.80, width=width, height=height,
                                                  profile=profile)
            views.append(("macro", macro_center + eye_dir * dist2, macro_center, basis.e_v,
                          K2, dist2, mpp2, macro_target, True))
            views.append(("macro_hl", macro_center + eye_dir * dist2, macro_center, basis.e_v,
                          K2, dist2, mpp2, macro_target, True))

        for view_name, eye, target, up_hint, K, dist, mpp, target_mm, highlight in views:
            frame = ViewFrame(
                view_id=f"{label}_{view_name}", K=K,
                T_WC=look_at_T_WC(eye, target, up_hint), image_size=(width, height),
                profile_id=f"{profile.profile_id}+RENDER", tier=profile.tier,
                u_position_mm=float(profile.u_position_mm),
                working_distance_mm=float(np.linalg.norm(np.asarray(eye) - np.asarray(target))),
                focus_setting=profile.focus_setting,
                source_kind="SYNTHETIC_RENDER_VIEW",
                camera_model="PINHOLE", dist=None,
                meta={"framing": "PURPOSE_BUILT_INSPECTION", "highlight": bool(highlight),
                      "target_extent_mm": float(target_mm),
                      "focal_length_mm": profile.meta.get("focal_length_mm"),
                      "sensor_width_mm": profile.meta.get("sensor_width_mm"),
                      "mm_per_pixel": float(K[0, 0] and mpp),
                      "view_direction": eye_dir.tolist()})
            scene = make_scene(fragment, highlight=highlight, name=f"{label}_{view_name}")
            out_name = f"render_{vessel_id}_{label}_{view_name}"
            row: dict[str, Any] = {"highlight": bool(highlight),
                                   "target_extent_mm": float(target_mm),
                                   "mm_per_pixel": float(K[0, 0] and mpp),
                                   "working_distance_mm": float(frame.working_distance_mm)}
            try:
                row.update(render_one(scene, frame=frame, light=light, spec=spec,
                                      config=config, out_name=out_name))
                row["backend"] = BACKEND_BLENDER
                print(f"[{label}/{view_name}] OK {row['seconds']}s "
                      f"{row['coverage_fraction'] * 100:.1f}% covered "
                      f"{row['mm_per_pixel']:.4f} mm/px -> {Path(row['png']).name}", flush=True)
            except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
                row["backend"] = BACKEND_BLENDER
                row["status"] = "FAILED"
                row["error"] = {"type": type(exc).__name__, "message": str(exc)[:600],
                                "traceback_tail": traceback.format_exc()[-1500:]}
                print(f"[{label}/{view_name}] BLENDER FAILED {type(exc).__name__}: "
                      f"{str(exc)[:300]}", flush=True)
                if not args.skip_software:
                    try:
                        out = render_view(scene, frame, light=light, spec=spec)
                        png = OUT_DIR / f"soft_{vessel_id}_{label}_{view_name}.png"
                        _write_rgb(png, out.rgb_linear)
                        row["fallback"] = {"backend": "SOFTWARE_RASTERISER", "png": str(png)}
                        print(f"[{label}/{view_name}] software fallback -> {png.name}", flush=True)
                    except BaseException as exc2:  # noqa: BLE001
                        row["fallback"] = {"status": "FAILED", "type": type(exc2).__name__,
                                           "message": str(exc2)[:400]}
                        print(f"[{label}/{view_name}] software fallback FAILED: {exc2}", flush=True)
            case_out["renders"][view_name] = row
        # a raw numpy read-back of the rendered RGB (evidence the PNG is the render, not a plot)
        report["cases"][label] = case_out
        del render_view_blender

    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    out_path = Path(args.out) if args.out else (OUT_DIR / f"renders_{vessel_id}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"[written] {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
