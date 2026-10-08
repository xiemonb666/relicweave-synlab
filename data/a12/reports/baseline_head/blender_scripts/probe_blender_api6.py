"""Sixth probe: can Blender read back its own EXR pass files? (loader diagnostics)

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/probe_blender_api6.py -- <dir>
"""

from __future__ import annotations

import json
import os
import sys

import bpy
import numpy as np


def probe(path: str) -> dict:
    rec: dict = {"path": path, "size_bytes": os.path.getsize(path)}
    try:
        img = bpy.data.images.load(path, check_existing=False)
    except Exception as exc:  # noqa: BLE001
        rec["load_error"] = f"{type(exc).__name__}: {exc}"
        return rec
    rec.update({"size": list(img.size), "channels": int(img.channels),
                "has_data": bool(img.has_data), "source": img.source,
                "filepath": img.filepath, "is_float": bool(img.is_float),
                "colorspace": img.colorspace_settings.name, "n_pixels": len(img.pixels)})
    if rec["n_pixels"] == 0:
        try:
            img.reload()
            rec["after_reload"] = {"size": list(img.size), "n_pixels": len(img.pixels)}
        except Exception as exc:  # noqa: BLE001
            rec["after_reload"] = f"{type(exc).__name__}: {exc}"
        try:
            img.colorspace_settings.name = "Non-Color"
            rec["after_noncolor"] = {"size": list(img.size), "n_pixels": len(img.pixels)}
        except Exception as exc:  # noqa: BLE001
            rec["after_noncolor"] = f"{type(exc).__name__}: {exc}"
        try:
            rec["views"] = [v.name if hasattr(v, "name") else str(v) for v in img.views]
            rec["render_slots"] = [s.name for s in img.render_slots]
        except Exception as exc:  # noqa: BLE001
            rec["views"] = f"{type(exc).__name__}: {exc}"
    else:
        buf = np.empty(rec["n_pixels"], dtype=np.float32)
        img.pixels.foreach_get(buf)
        arr = buf.reshape(img.size[1], img.size[0], int(img.channels))
        rec["stats"] = {"min": float(arr.min()), "max": float(arr.max()),
                        "center": arr[arr.shape[0] // 2, arr.shape[1] // 2].tolist(),
                        "row_top_mean": float(arr[-1].mean()), "row_bottom_mean": float(arr[0].mean())}
    bpy.data.images.remove(img)
    return rec


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out: dict = {"out": []}
    if not argv:
        print("usage: -- <dir-or-file>")
        return 2
    target = argv[0]
    paths = ([os.path.join(target, f) for f in sorted(os.listdir(target))
              if f.lower().endswith(".exr")] if os.path.isdir(target) else [target])
    for path in paths:
        out["out"].append(probe(path))

    # control: a single-layer EXR written by write_still in this same process
    scene = bpy.context.scene
    scene.render.resolution_x = 32
    scene.render.resolution_y = 24
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    ctrl = os.path.join(os.path.dirname(paths[0]), "control_writestill.exr")
    scene.render.filepath = ctrl[:-4]
    bpy.ops.render.render(write_still=True)
    out["control"] = probe(ctrl)
    print("PROBE6_JSON_BEGIN")
    print(json.dumps(out, indent=2, default=str))
    print("PROBE6_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
