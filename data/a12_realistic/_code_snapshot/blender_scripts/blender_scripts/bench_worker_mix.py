"""Decisive measurement: the worker's real 6-render pass mix, CPU vs GPU, in ONE process.

End-to-end CPU-vs-GPU numbers from separate 12-view runs disagreed by 2x because parallel
agents on this host contend for the CPU.  This harness removes that variable: it builds the
scene once, then for each device renders the exact pass mix one view costs
(``32, 32, 32, 1, 1, 1`` samples: RGB + two anti-aliased geometry packs + the three
one-sample exact geometry passes) and reports every individual render time.

Because ``render_worker`` is launched once **per view**, the first render of each block is a
cold render: any one-time device initialisation lands there.  That is what decides whether the
GPU's warm throughput survives into the real pipeline.

Run::

    & $env:BLENDER_BIN --background --factory-startup --python-exit-code 1 \
        --python blender_scripts/bench_worker_mix.py -- --devices CPU,CUDA,OPTIX --out out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import bpy

#: one view = RGB(32 spp) + AA geometry pack a/b (32 spp) + 3 exact passes (1 spp)
WORKER_MIX = (32, 32, 32, 1, 1, 1)
WORKER_MIX_LABELS = ("rgb", "geometry_aa_a", "geometry_aa_b",
                     "geometry_exact_a", "geometry_exact_b", "geometry_targetonly")


def build_scene(width: int, height: int) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.cycles.max_bounces = 4
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = False
    scene.view_settings.view_transform = "Standard"

    bpy.ops.mesh.primitive_cube_add(size=1.0)
    box = bpy.context.active_object
    box.scale = (30.0, 21.0, 13.0)
    bpy.ops.object.modifier_add(type="SUBSURF")
    box.modifiers[-1].levels = 2
    box.modifiers[-1].render_levels = 2
    bpy.ops.object.modifier_apply(modifier=box.modifiers[-1].name)

    light_data = bpy.data.lights.new("sun", type="SUN")
    light_data.energy = 3.141592653589793
    sun = bpy.data.objects.new("sun", light_data)
    sun.rotation_euler = (0.9, 0.2, 0.4)
    scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("cam", cam_data)
    cam.location = (0.0, -160.0, 0.0)
    cam.rotation_euler = (1.5707963267948966, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.02, 0.025, 1.0)


def select_device(requested: str) -> dict:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    report: dict = {"requested": requested}
    try:
        prefs.get_devices()
    except Exception as exc:  # noqa: BLE001
        report["get_devices_error"] = f"{type(exc).__name__}: {exc}"
    if requested == "CPU":
        report["enabled"] = []
        return report
    try:
        prefs.compute_device_type = requested
    except Exception as exc:  # noqa: BLE001
        report["set_error"] = f"{type(exc).__name__}: {exc}"
        return report
    report["readback"] = str(prefs.compute_device_type)
    enabled = []
    for dev in prefs.devices:
        dev.use = (dev.type == requested)
        if dev.use:
            enabled.append(dev.name)
    report["enabled"] = enabled
    return report


def apply_device(requested: str) -> dict:
    """Set ``cycles.device`` + the matching Cycles backend/device for ``requested``."""
    scene = bpy.context.scene
    if requested == "CPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        try:
            prefs.compute_device_type = "NONE"
        except Exception:  # noqa: BLE001
            pass
        scene.cycles.device = "CPU"
        return {"requested": "CPU", "cycles_device": "CPU", "enabled": []}
    info = select_device(requested)
    scene.cycles.device = "GPU"
    info["cycles_device"] = "GPU"
    return info


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1024x768")
    ap.add_argument("--devices", default="CPU,CUDA,OPTIX")
    ap.add_argument("--views", type=int, default=3,
                    help="how many simulated views to render per device")
    #: HYBRID routes the multi-sample passes to the GPU and the one-sample exact geometry
    #: passes to the CPU, which is where the GPU loses badly (a fixed ~0.4 s per GPU render
    #: call against ~0.07 s on the CPU).
    ap.add_argument("--hybrid-gpu", default="CUDA",
                    help="backend used for the multi-sample passes in HYBRID mode")
    ap.add_argument("--hybrid-threshold", type=int, default=2,
                    help="passes with samples >= this go to the GPU in HYBRID mode")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    w, h = (int(v) for v in args.res.lower().split("x"))
    devices = [d.strip().upper() for d in args.devices.split(",")]
    build_scene(w, h)
    scene = bpy.context.scene
    faces = len(bpy.context.active_object.data.polygons)

    results = []
    for device in devices:
        hybrid = device == "HYBRID"
        if hybrid:
            apply_device("CPU")
            info = {"requested": "HYBRID", "gpu_backend": args.hybrid_gpu,
                    "threshold_samples": args.hybrid_threshold,
                    "routing": "samples >= threshold -> GPU, else CPU"}
        else:
            info = apply_device(device)
        view_rows = []
        for _ in range(args.views):
            renders = []
            current = None
            for label, spp in zip(WORKER_MIX_LABELS, WORKER_MIX):
                want = device
                if hybrid:
                    want = args.hybrid_gpu if spp >= args.hybrid_threshold else "CPU"
                if want != current:
                    apply_device(want)
                    current = want
                scene.cycles.samples = spp
                t0 = time.perf_counter()
                bpy.ops.render.render(write_still=False)
                renders.append({"pass": label, "samples": spp, "device": want,
                                "seconds": time.perf_counter() - t0})
            view_rows.append({"renders": renders,
                              "view_seconds": sum(r["seconds"] for r in renders),
                              "first_render_seconds": renders[0]["seconds"]})
        results.append({
            "device": device, "device_info": info, "views": view_rows,
            "view_seconds": [v["view_seconds"] for v in view_rows],
            "cold_view_seconds": view_rows[0]["view_seconds"],
            "warm_view_seconds": min(v["view_seconds"] for v in view_rows[1:])
            if len(view_rows) > 1 else view_rows[0]["view_seconds"],
        })

    out = {"resolution": [w, h], "faces": faces, "blender": bpy.app.version_string,
           "worker_mix": list(WORKER_MIX), "worker_mix_labels": list(WORKER_MIX_LABELS),
           "views_per_device": args.views, "results": results}
    print("RWS_WORKER_MIX " + json.dumps(out))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
