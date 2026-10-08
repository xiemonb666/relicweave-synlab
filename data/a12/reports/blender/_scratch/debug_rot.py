"""Scratch: isolate which rotation breaks the Blender/ray-cast correspondence."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render_1024_12 import cast_rays                              # noqa: E402
from synlab.observe.blender import BlenderBackendConfig           # noqa: E402
from synlab.observe.render import BACKEND_BLENDER, RenderSpec, build_scene  # noqa: E402
from synlab.observe.routes import ObsSpec, render_view            # noqa: E402
from synlab.schemas.runtime import ViewFrame                      # noqa: E402

SIZE = (1024, 768)
FX = 1200.0
CAM_Z = -400.0


def frame() -> ViewFrame:
    K = np.array([[FX, 0.0, (SIZE[0] - 1) / 2.0], [0.0, FX, (SIZE[1] - 1) / 2.0],
                  [0.0, 0.0, 1.0]])
    T_WC = np.eye(4)
    T_WC[2, 3] = CAM_Z
    return ViewFrame(view_id="rot", K=K, T_WC=T_WC, image_size=SIZE, profile_id="fx",
                     tier="GLOBAL", u_position_mm=0.0, working_distance_mm=abs(CAM_Z),
                     focus_setting="FIXED", source_kind="SENSOR_SIM",
                     camera_model="PINHOLE", dist=None)


def case(name: str, rotations: list[tuple[float, list[float]]]) -> dict:
    box = trimesh.creation.box(extents=(100.0, 100.0, 100.0))
    for deg, axis in rotations:
        box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(deg), axis))
    verts = np.asarray(box.vertices)
    faces = np.asarray(box.faces)
    scene = build_scene(box, surface_tag=np.zeros(faces.shape[0], dtype=np.int16),
                        face_id=np.arange(faces.shape[0]), name="rot")
    fr = frame()
    light = ObsSpec().resolved_light()
    cast = cast_rays(np.asarray(fr.K), np.asarray(fr.T_WC), verts, faces, SIZE, 8)
    zref = cast["z_mm"]
    sw = render_view(scene, fr, light=light, spec=RenderSpec(supersample=1),
                     focus_distance_mm=abs(CAM_Z), backend="SOFTWARE_RASTERIZER")
    bl = render_view(scene, fr, light=light, spec=RenderSpec(),
                     focus_distance_mm=abs(CAM_Z), backend=BACKEND_BLENDER,
                     blender_config=BlenderBackendConfig(samples=4, filter_width=1.5,
                                                        f_number=8.0, previews=False,
                                                        raycast_samples=100,
                                                        run_label=f"rot_{name}"))
    out = {"case": name}
    for tag, r in (("software", sw), ("blender", bl)):
        depth = np.asarray(r.depth_z, dtype=np.float64)[cast["y"], cast["x"]]
        both = np.isfinite(depth) & np.isfinite(zref)
        only_ray = ~np.isfinite(depth) & np.isfinite(zref)
        only_render = np.isfinite(depth) & ~np.isfinite(zref)
        delta = np.abs(depth[both] - zref[both]) if both.any() else np.zeros(0)
        out[tag] = {
            "hits": int(np.isfinite(zref).sum()),
            "both": int(both.sum()), "ray_only": int(only_ray.sum()),
            "render_only": int(only_render.sum()),
            "median_abs_mm": float(np.median(delta)) if delta.size else None,
            "max_abs_mm": float(delta.max()) if delta.size else None,
            "id_mismatch": int(np.sum(np.asarray(r.id_map)[cast["y"], cast["x"]][both]
                                      != cast["face"][both])),
        }
    print(out, flush=True)
    return out


def main() -> int:
    results = [
        case("identity", []),
        case("z45", [(45.0, [0, 0, 1])]),
        case("x20", [(20.0, [1, 0, 0])]),
        case("z45_x20", [(45.0, [0, 0, 1]), (20.0, [1, 0, 0])]),
    ]
    import json

    Path(__file__).with_name("debug_rot.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
