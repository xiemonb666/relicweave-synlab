"""Patch v2: record the per-pixel frozen Lambert term (is the fracture lit at all?)."""
from pathlib import Path

p = Path("synlab/observe/fracture_appearance.py")
t = p.read_text(encoding="utf-8")

pairs = [
    ("""            import os as _os
            if _os.environ.get("SYNLAB_FA_DEBUG"):
                _tilt = np.abs(gu[:, None] * tu + gv[:, None] * tv).max()
                print(f"[FA] face={f} rows={n_px.shape[0]} "
                      f"|gu|max={float(np.abs(gu).max()):.5f} |gv|max={float(np.abs(gv).max()):.5f} "
                      f"tilt_max={float(_tilt):.5f} |tu|min={float(np.linalg.norm(tu, axis=1).min()):.4f} "
                      f"scale={relief_field.amplitude_scale * float(appearance.amplitude_scale):.5f}",
                      flush=True)
            n_px = n_px - gu[:, None] * tu - gv[:, None] * tv
""",
     """            n_px = n_px - gu[:, None] * tu - gv[:, None] * tv
"""),
    ("""    rgba = np.zeros((height, width, 3), dtype=np.float32)
    faces = scene.faces
""",
     """    rgba = np.zeros((height, width, 3), dtype=np.float32)
    #: The frozen Lambert term of the pixel that won the z-buffer.  It is recorded because the
    #: normal channel can only deliver contrast where this term is strictly between 0 and 1: the
    #: frozen model clips it, so an unlit (or fully lit) surface has *no* normal response at all.
    lambert_buf = np.full((height, width), np.nan, dtype=np.float64)
    l_unit = np.asarray(light.direction, dtype=np.float64)
    faces = scene.faces
"""),
    ("""    if faces.shape[0] == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba}
""",
     """    if faces.shape[0] == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba,
                "lambert": lambert_buf}
"""),
    ("""    order = np.nonzero(visible)[0]
    if order.size == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba}
""",
     """    order = np.nonzero(visible)[0]
    if order.size == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba,
                "lambert": lambert_buf}
"""),
    ("""            shaded = shade_world_normals(normals_world=world_normals[f][None, :],
                                         albedo=albedo_px[f][None, :], light=light)[0]
            rgba[ymin:ymax + 1, xmin:xmax + 1][better] = shaded.astype(np.float32)
            continue
""",
     """            shaded = shade_world_normals(normals_world=world_normals[f][None, :],
                                         albedo=albedo_px[f][None, :], light=light)[0]
            rgba[ymin:ymax + 1, xmin:xmax + 1][better] = shaded.astype(np.float32)
            lambert_buf[ymin:ymax + 1, xmin:xmax + 1][better] = float(
                world_normals[f] @ l_unit)
            continue
"""),
    ("""        rgba[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = shaded.astype(np.float32)
    return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba}
""",
     """        rgba[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = shaded.astype(np.float32)
        lambert_buf[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = n_px @ l_unit
    return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba, "lambert": lambert_buf}
"""),
    ("""            "schema": APPEARANCE_SCHEMA, "spec": appearance.as_dict(),""",
     """            "schema": APPEARANCE_SCHEMA, "spec": appearance.as_dict(),
            "lambert": _lambert_report(buffers.get("lambert"), tag_map),"""),
]
for old, new in pairs:
    if old not in t:
        raise SystemExit("PATTERN NOT FOUND:\n" + old[:200])
    t = t.replace(old, new, 1)

helper = '''

def _lambert_report(lambert: Any, tag_map: np.ndarray) -> dict[str, Any]:
    """Statistics of the frozen Lambert term on the fracture (rim) pixels of one render.

    ``unlit_fraction`` is the share of fracture pixels whose Lambert term is clipped at 0: there the
    shading is ``albedo * ambient`` and **no** normal perturbation can change the image at all.
    ``fully_lit_fraction`` is the same for the clip at 1.  This is the measurement that decides
    whether a view can show relief under the frozen single-light model.
    """
    if lambert is None:
        return {"status": "NOT_RECORDED"}
    lam = np.asarray(lambert, dtype=np.float64)
    rim = np.asarray(tag_map) == 2
    valid = rim & np.isfinite(lam)
    if not valid.any():
        return {"status": "NO_RIM_PIXELS", "n_px": 0}
    v = lam[valid]
    return {
        "status": "OK", "n_px": int(v.size), "mean_raw_dot": float(v.mean()),
        "unlit_fraction": float(np.mean(v <= 0.0)),
        "fully_lit_fraction": float(np.mean(v >= 1.0)),
        "lit_fraction": float(np.mean((v > 0.02) & (v < 0.98))),
        "p05_raw_dot": float(np.percentile(v, 5)), "p95_raw_dot": float(np.percentile(v, 95)),
        "definition": ("raw = -(n_world . light.direction); the frozen shading clips it to [0, 1]. "
                       "unlit_fraction = share of fracture pixels with no normal response at all"),
    }

'''
anchor = "def _scaled_frame(frame: ViewFrame, factor: int) -> ViewFrame:"
if anchor not in t:
    raise SystemExit("ANCHOR NOT FOUND")
t = t.replace(anchor, helper.lstrip("\n") + "\n" + anchor, 1)
p.write_text(t, encoding="utf-8")
print("patched")
