"""One-shot patch of the runner: float-DN difference metrics and measure(res) refactor."""
from pathlib import Path

p = Path("tests/a12/observe/_run_fracture_appearance.py")
t = p.read_text(encoding="utf-8")

pairs = [
    # measure() takes the whole result dict so the float channel travels with it
    ('''def measure(dn: np.ndarray, mask: np.ndarray, render) -> dict:
    out = {"dn": fa.dn_statistics(dn, mask),
           "facet": fa.facet_metrics(dn, render.id_map, mask),
           "direction": fa.directional_index(dn, mask),
           "grain": fa.grain_pixel_statistics(dn, mask)}
    return out''',
     '''def measure(res: dict) -> dict:
    """Delivered-image statistics of one appearance render.

    Both readings of the same render are reported: ``dn`` is the quantised delivered image (the
    code values a reader sees) and ``dn_float`` is the pre-quantisation DN of the chain's linear
    output, which is the channel a sub-code-value shading signal has to be measured in.
    """
    dn, mask, render = res["dn"], res["mask"], res["render"]
    out = {"dn": fa.dn_statistics(dn, mask),
           "dn_float": fa.dn_statistics(res["dn_float"], mask),
           "dn_delivered_shipped_gain": fa.dn_statistics(res["dn_delivered"], mask),
           "facet": fa.facet_metrics(dn, render.id_map, mask),
           "direction": fa.directional_index(dn, mask),
           "grain": fa.grain_pixel_statistics(dn, mask)}
    return out'''),
    ('''            "albedo_mean": albedo, "relief_off": measure(off["dn"], off["mask"], off["render"]),''',
     '''            "albedo_mean": albedo, "relief_off": measure(off),'''),
    ('''            diff = fa.difference_dn_statistics(on["dn"], off["dn"], on["mask"])
            diff_delivered = fa.difference_dn_statistics(on["dn_delivered"], off["dn_delivered"],
                                                         on["mask"])
            entry = {"ra_target_mm": float(amp), "ra_realized_mm": scaled.realized_ra_mm,
                     "difference": diff, "difference_delivered": diff_delivered,
                     "relief_on": measure(on["dn"], on["mask"], on["render"]),''',
     '''            diff = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], on["mask"])
            changed = fa.difference_dn_statistics(on["dn"], off["dn"], on["mask"])
            diff_delivered = fa.difference_dn_statistics(on["dn_delivered"], off["dn_delivered"],
                                                         on["mask"])
            entry = {"ra_target_mm": float(amp), "ra_realized_mm": scaled.realized_ra_mm,
                     "difference": diff, "changed_code_values": changed,
                     "difference_delivered": diff_delivered,
                     "relief_on": measure(on),'''),
    ('''                   "difference_shading": fa.difference_dn_statistics(a["dn"], b["dn"], a["mask"]),
                   "difference_delivered": fa.difference_dn_statistics(
                       a["dn_delivered"], b["dn_delivered"], a["mask"]),''',
     '''                   "difference_shading": fa.difference_dn_statistics(
                       a["dn_float"], b["dn_float"], a["mask"]),
                   "difference_shading_quantised": fa.difference_dn_statistics(
                       a["dn"], b["dn"], a["mask"]),
                   "difference_delivered": fa.difference_dn_statistics(
                       a["dn_delivered"], b["dn_delivered"], a["mask"]),'''),
    ('''            "measured": measure(res["dn"], res["mask"], res["render"]),''',
     '''            "measured": measure(res),'''),
    ('''            "relief_on": measure(res["dn"], res["mask"], res["render"]),
            "relief_on_without_transmission_weight": measure(res_nw["dn"], res_nw["mask"],
                                                             res_nw["render"]),
            "relief_off": measure(off["dn"], off["mask"], off["render"]),
            "difference_relief_on_minus_off": fa.difference_dn_statistics(res["dn"], off["dn"],
                                                                         res["mask"]),''',
     '''            "relief_on": measure(res),
            "relief_on_without_transmission_weight": measure(res_nw),
            "relief_off": measure(off),
            "difference_relief_on_minus_off": fa.difference_dn_statistics(
                res["dn_float"], off["dn_float"], res["mask"]),
            "changed_code_values_relief_on_minus_off": fa.difference_dn_statistics(
                res["dn"], off["dn"], res["mask"]),'''),
    ('''        "difference": fa.difference_dn_statistics(a["dn"], b["dn"], mask),
        "dn_with_strip": fa.dn_statistics(a["dn"], mask),
        "dn_without_strip": fa.dn_statistics(b["dn"], mask),''',
     '''        "difference": fa.difference_dn_statistics(a["dn_float"], b["dn_float"], mask),
        "changed_code_values": fa.difference_dn_statistics(a["dn"], b["dn"], mask),
        "dn_with_strip": fa.dn_statistics(a["dn"], mask),
        "dn_without_strip": fa.dn_statistics(b["dn"], mask),'''),
    ('''        diff = fa.difference_dn_statistics(on["dn"], off["dn"], on["mask"])''',
     '''        diff = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], on["mask"])'''),
    ('''        common = [f"V10/M11 iface6_c000  mm/px={measured_mm_px:.5f}  L={int(long_edge)}px",''',
     '''        common = [f"{body['vessel_id']}/{body['material_id']} {roi.roi_id}"
                  f"  mm/px={measured_mm_px:.5f}  L={int(long_edge)}px",'''),
]
for old, new in pairs:
    if old not in t:
        raise SystemExit("PATTERN NOT FOUND:\n" + old[:200])
    t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("patched", len(pairs), "blocks")
