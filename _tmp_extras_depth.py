"""Scratch: why do the ray cast and the z-buffer disagree on dense depth?"""
from __future__ import annotations

import sys

import numpy as np
import trimesh

sys.stdout.reconfigure(encoding="utf-8")

import synlab.observe.synthetic_extras as se
from synlab.observe.routes import ObsSpec, resolve_target

m = trimesh.creation.box(extents=(120.0, 100.0, 40.0))
n = len(m.faces)
m.metadata["face_attr_arrays"] = {
    "origin_kind": np.full(n, 1, dtype=np.uint8),
    "interface_id": np.where(np.arange(n) % 3 == 0, 0, -1).astype(np.int32),
}
t = resolve_target({"mesh": m, "fragment_id": "F001", "component_id": "C001"})
p = se.resolve_profile("MID")
size = se._extras_size(p, 48)
fr = se._turntable_frame(view_id="v", profile=p, size=size,
                        center=se._bbox_center(t.bbox))
spec = ObsSpec()

cast, ok = se._cast_all_pixels(t, fr)
print("cast ok:", ok, "finite:", int(np.isfinite(cast).sum()), "of", cast.size)
print("cast range:", np.nanmin(cast), np.nanmax(cast))

from synlab.observe.render import RenderSpec, render_view, BACKEND_SOFTWARE
out = render_view(se._scene_for(t), fr, light=spec.resolved_light(),
                  spec=RenderSpec(**{**spec.render_spec.__dict__, "supersample": 1}),
                  backend=BACKEND_SOFTWARE)
zbuf = np.asarray(out.depth_z, dtype=np.float64)
print("zbuf finite:", int(np.isfinite(zbuf).sum()))
both = np.isfinite(cast) & np.isfinite(zbuf)
delta = np.abs(cast[both] - zbuf[both])
print("both:", int(both.sum()), "delta max", float(delta.max()),
      "median", float(np.median(delta)), "p99", float(np.percentile(delta, 99)))
ys, xs = np.nonzero(both & (np.abs(cast - np.where(np.isfinite(zbuf), zbuf, 0)) > 1.0))
print("big-delta pixels:", len(ys))
for k in range(min(8, len(ys))):
    y, x = int(ys[k]), int(xs[k])
    print(f"  ({x},{y}) cast={cast[y, x]:.3f} zbuf={zbuf[y, x]:.3f} id={out.id_map[y, x]}")
print("only-cast:", int((np.isfinite(cast) & ~np.isfinite(zbuf)).sum()),
      "only-zbuf:", int((~np.isfinite(cast) & np.isfinite(zbuf)).sum()))
print("near_mm", spec.render_spec.near_mm, "far_mm", spec.render_spec.far_mm)
