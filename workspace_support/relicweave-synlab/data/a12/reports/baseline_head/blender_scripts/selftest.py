"""Blender capability self-test used by ``synlab.observe.blender.selftest``.

Run::

    & $env:BLENDER_BIN --background --factory-startup --python-exit-code 1 \
        --python blender_scripts/selftest.py

Prints one ``RWS_SELFTEST {json}`` line.  It checks what the render worker actually needs
(Cycles engine assignable, a background render producing finite scene-linear pixels); it
does not claim anything about the CPU/GPU performance.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import bpy
import numpy as np


def main() -> int:
    report: dict = {"status": "OK", "version": bpy.app.version_string,
                    "python": sys.version.split()[0],
                    "binary": bpy.app.binary_path}
    try:
        report["build_hash"] = (bpy.app.build_hash.decode()
                                if isinstance(bpy.app.build_hash, bytes)
                                else str(bpy.app.build_hash))
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        report["cycles_engine"] = scene.render.engine
        report["cycles_samples_default"] = int(scene.cycles.samples)
        report["cycles_device"] = str(scene.cycles.device)
        report["denoiser"] = str(getattr(scene.cycles, "denoiser", ""))
        report["denoiser_available"] = hasattr(scene.cycles, "use_denoising")
        report["passes"] = sorted(a for a in dir(bpy.context.view_layer)
                                  if a.startswith("use_pass_"))
        report["compositor_node_group"] = hasattr(scene, "compositing_node_group")
        report["shader_aov_node"] = hasattr(bpy.types, "ShaderNodeOutputAOV")
        report["engine_enum"] = sorted(
            i.identifier for i in
            bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items)

        # A real 16x12 background render: proves the integrator runs headless here.
        scene.render.resolution_x = 16
        scene.render.resolution_y = 12
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "32"
        scene.cycles.samples = 4
        scene.view_settings.view_transform = "Standard"
        tmp = tempfile.mkdtemp(prefix="rws_selftest_")
        scene.render.filepath = os.path.join(tmp, "selftest")
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        report["render_seconds"] = time.time() - t0
        path = os.path.join(tmp, "selftest.exr")
        report["render_output"] = os.path.exists(path)
        if report["render_output"]:
            img = bpy.data.images.load(path)
            buf = np.empty(len(img.pixels), dtype=np.float32)
            img.pixels.foreach_get(buf)
            report["render_finite"] = bool(np.isfinite(buf).all())
            report["render_channels"] = int(img.channels)
            bpy.data.images.remove(img)
    except Exception as exc:  # noqa: BLE001 - any failure is a capability failure
        report["status"] = "ERROR"
        report["error"] = f"{type(exc).__name__}: {exc}"

    print("RWS_SELFTEST " + json.dumps(report, default=str))
    return 0 if report["status"] == "OK" else 4


if __name__ == "__main__":
    sys.exit(main())
