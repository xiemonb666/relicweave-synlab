"""Minimal Cycles device-selection test: does setting compute_device_type + cycles.device
actually render on the GPU?

Run::

    & $env:BLENDER_BIN --background --factory-startup --python-exit-code 1 \
        --python blender_scripts/probe_gpu_render.py -- OPTIX|CUDA|CPU

Prints ``RWS_GPU_TEST {json}``.  Renders a fixed 256x192, 32-sample sphere twice and reports
wall time, so a "GPU" that silently falls back to CPU is visible as a missing speed-up.
"""

from __future__ import annotations

import json
import sys
import time

import bpy


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y = 256, 192
    scene.render.resolution_percentage = 100
    scene.cycles.samples = 32
    scene.cycles.use_adaptive_sampling = True
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    sphere = bpy.context.active_object
    light_data = bpy.data.lights.new("l", type="SUN")
    light_data.energy = 5.0
    sun = bpy.data.objects.new("l", light_data)
    sun.rotation_euler = (0.6, 0.2, 0.3)
    scene.collection.objects.link(sun)
    cam_data = bpy.data.cameras.new("c")
    cam = bpy.data.objects.new("c", cam_data)
    cam.location = (0.0, -5.0, 0.0)
    cam.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene, sphere


def select_device(requested: str) -> dict:
    """Return a report of what was actually selected."""
    report: dict = {"requested": requested}
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.get_devices()
    except Exception as exc:  # noqa: BLE001
        report["get_devices_error"] = f"{type(exc).__name__}: {exc}"
    if requested == "CPU":
        report["compute_device_type_set"] = None
        report["enabled_devices"] = []
        return report
    try:
        prefs.compute_device_type = requested
    except Exception as exc:  # noqa: BLE001
        report["set_error"] = f"{type(exc).__name__}: {exc}"
    report["compute_device_type_after_set"] = prefs.compute_device_type
    enabled = []
    for dev in prefs.devices:
        dev.use = (dev.type == requested)
        if dev.use:
            enabled.append(dev.name)
    report["enabled_devices"] = enabled
    return report


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    requested = (argv[0] if argv else "OPTIX").upper()
    scene, sphere = build_scene()
    device_report = select_device(requested)
    scene.cycles.device = "GPU" if requested in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL") \
        else "CPU"
    device_report["cycles_device"] = scene.cycles.device

    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=False)
    dt = time.perf_counter() - t0
    result = {"requested": requested, "device_report": device_report,
              "render_seconds": dt, "resolution": [256, 192], "samples": 32,
              "blender": bpy.app.version_string}
    print("RWS_GPU_TEST " + json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
