"""Cycles render-throughput sweep across compute devices, inside ONE Blender process.

``probe_gpu_render.py`` measures one device per process, so process startup and the first-use
OptiX module compile are mixed into every number.  This harness builds the scene **once**,
then renders the same frame with each requested device and sample count, which isolates the
render itself and shows how the CPU/GPU gap scales with sample count.

Run::

    & $env:BLENDER_BIN --background --factory-startup --python-exit-code 1 \
        --python blender_scripts/bench_cycles_devices.py -- \
        --res 1024x768 --samples 1,8,32,128 --devices CPU,CUDA,OPTIX --repeat 2 --out out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import bpy


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

    # a box of the same dimensions as the project's 1024x768 realism probe, with labelled
    # faces so the scene is not a two-triangle best case
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


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1024x768")
    ap.add_argument("--samples", default="1,8,32,128")
    ap.add_argument("--devices", default="CPU,CUDA,OPTIX")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    w, h = (int(v) for v in args.res.lower().split("x"))
    samples = [int(v) for v in args.samples.split(",")]
    devices = [d.strip().upper() for d in args.devices.split(",")]
    build_scene(w, h)
    scene = bpy.context.scene
    tri_count = len(bpy.context.active_object.data.polygons)

    results = []
    for device in devices:
        info = select_device(device)
        scene.cycles.device = "GPU" if device != "CPU" else "CPU"
        info["cycles_device"] = scene.cycles.device
        for n in samples:
            scene.cycles.samples = n
            times = []
            for _ in range(args.repeat):
                t0 = time.perf_counter()
                bpy.ops.render.render(write_still=False)
                times.append(time.perf_counter() - t0)
            results.append({"device": device, "samples": n, "seconds": times,
                            "best_seconds": min(times), "device_info": info})
    out = {"resolution": [w, h], "faces": tri_count, "blender": bpy.app.version_string,
           "repeat": args.repeat, "results": results}
    print("RWS_DEVICE_SWEEP " + json.dumps(out))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
