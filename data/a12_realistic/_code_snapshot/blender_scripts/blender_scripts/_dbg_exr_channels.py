"""Diagnostic: dump the four compositor EXR channels of one pass file.

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/_dbg_exr_channels.py -- <file.exr> [...]
"""

from __future__ import annotations

import json
import sys

import bpy
import numpy as np


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:]
    out = {}
    for path in argv:
        img = bpy.data.images.load(path, check_existing=False)
        img.colorspace_settings.name = "Non-Color"
        n = len(img.pixels)
        buf = np.empty(n, dtype=np.float32)
        img.pixels.foreach_get(buf)
        ch = int(img.channels)
        arr = buf.reshape(img.size[1], img.size[0], ch)
        rec = {"size": list(img.size), "channels": ch, "depth": int(img.depth),
               "is_float": bool(img.is_float)}
        for i in range(ch):
            plane = arr[:, :, i]
            rec[f"ch{i}"] = {"min": float(plane.min()), "max": float(plane.max()),
                             "mean": float(plane.mean()),
                             "unique_head": np.unique(np.round(plane, 3))[:8].tolist()}
        out[path.split("\\")[-1]] = rec
        bpy.data.images.remove(img)
    print("DBG_CH_JSON_BEGIN")
    print(json.dumps(out, indent=2, default=str))
    print("DBG_CH_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
