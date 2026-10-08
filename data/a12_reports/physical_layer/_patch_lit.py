"""Patch v3: lambert sign convention + lit-ROI selection in the runner."""
from pathlib import Path

p = Path("synlab/observe/fracture_appearance.py")
t = p.read_text(encoding="utf-8")
pairs = [
    ("""            lambert_buf[ymin:ymax + 1, xmin:xmax + 1][better] = float(
                world_normals[f] @ l_unit)""",
     """            lambert_buf[ymin:ymax + 1, xmin:xmax + 1][better] = float(
                -(world_normals[f] @ l_unit))"""),
    ("""        lambert_buf[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = n_px @ l_unit""",
     """        lambert_buf[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = -(n_px @ l_unit)"""),
    ("""    ``unlit_fraction`` is the share of fracture pixels whose Lambert term is clipped at 0: there the
    shading is ``albedo * ambient`` and **no** normal perturbation can change the image at all.
    ``fully_lit_fraction`` is the same for the clip at 1.  This is the measurement that decides
    whether a view can show relief under the frozen single-light model.
    \"\"\"""",
     """    ``unlit_fraction`` is the share of fracture pixels whose Lambert term is clipped at 0: there the
    shading is ``albedo * ambient`` and **no** normal perturbation can change the image at all.
    ``fully_lit_fraction`` is the same for the clip at 1.  This is the measurement that decides
    whether a view can show relief under the frozen single-light model, and ``mean_raw_dot`` is the
    signed quantity ``-(n_world . light.direction)`` *before* the clip: it is negative when the
    fracture faces away from the light and the whole view is ambient-only.
    \"\"\""""),
]
for old, new in pairs:
    if old not in t:
        raise SystemExit("APP PATTERN NOT FOUND:\n" + old[:200])
    t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")

# ---------------------------------------------------------------- runner: lit ROI selection
r = Path("tests/a12/observe/_run_fracture_appearance.py")
s = r.read_text(encoding="utf-8")
helper = '''

def lit_score(roi, light) -> float:
    """``-(n_roi . light.direction)``: > 0 means the fracture faces the frozen light.

    The frozen model has ONE directional light and a normal-independent ambient term, and it clips
    the Lambert term at 0.  A fracture whose outward normal points away from that light renders as
    ``albedo * ambient`` over its whole area, and **no** normal perturbation can change a single
    code value there - so the appearance study must be run on a view that is lit, and which views
    are lit is a measurement, not a choice.
    """
    n = np.asarray(roi.normal, dtype=np.float64).reshape(3)
    n = n / max(float(np.linalg.norm(n)), 1e-30)
    return float(-(n @ np.asarray(light.direction, dtype=np.float64).reshape(3)))


def select_lit_specimen(*, config, light, rois_by_body):
    """Pick the (body, roi) with the largest lit score, and report every candidate measured."""
    best = None
    table = []
    for entry, target, body, rois in rois_by_body:
        for roi in rois:
            score = lit_score(roi, light)
            table.append({"vessel_id": body["vessel_id"], "material_id": body["material_id"],
                          "roi_id": roi.roi_id, "lit_score": score,
                          "n_faces": int(roi.n_faces), "area_mm2": float(roi.area_mm2)})
            if best is None or score > best[0]:
                best = (score, entry, target, body, roi)
    return best, sorted(table, key=lambda r: -r["lit_score"])
'''
anchor = "\ndef measure(res: dict) -> dict:"
if anchor not in s:
    raise SystemExit("RUNNER ANCHOR NOT FOUND")
s = s.replace(anchor, helper + anchor, 1)
r.write_text(s, encoding="utf-8")
print("patched")
