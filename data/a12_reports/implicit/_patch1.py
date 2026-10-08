import re, pathlib
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
old_start = s.index("def measure_field_slope(")
old_end = s.index("def calibrate_slope(")
new = '''def measure_field_slope(h_fn: Any, *, bounds: tuple[float, float, float, float],
                        mask_fn: Any, step_mm: float, max_points: int = 600_000
                        ) -> dict[str, Any]:
    """P50/P95/max slope and curvature of the realized surface over the footprint.

    The curvature is the mixed second-derivative bound ``|h_uu| + 2|h_uv| + |h_vv|`` that the
    interpolation budget uses (``error <= C * cell^2 / 8``), measured on a raster finer than the
    sheet spacing so that a cell-sized feature cannot hide between samples.
    """
    u0, u1, v0, v1 = (float(x) for x in bounds)
    step = float(step_mm)
    while ((u1 - u0) / step + 2.0) * ((v1 - v0) / step + 2.0) > float(max_points):
        step *= 1.25
    gu = np.arange(u0, u1 + 0.5 * step, step)
    gv = np.arange(v0, v1 + 0.5 * step, step)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    inside = np.asarray(mask_fn(GU, GV), dtype=bool)
    if int(inside.sum()) < 64:
        return {"samples": int(inside.sum()), "note": "too few samples inside the footprint"}
    h = np.asarray(h_fn(GU, GV), dtype=np.float64)
    dv_axis, du_axis = np.gradient(h, step)
    slope = np.hypot(du_axis, dv_axis)[inside]
    angles = np.degrees(np.arctan(slope))
    ddu = np.gradient(du_axis, step, axis=0)
    ddv = np.gradient(dv_axis, step, axis=1)
    duv = np.gradient(du_axis, step, axis=1)
    curv = (np.abs(ddu) + 2.0 * np.abs(duv) + np.abs(ddv))[inside]
    return {
        "samples": int(slope.size), "step_mm": float(step),
        "slope_p50": float(np.percentile(slope, 50)),
        "slope_p95": float(np.percentile(slope, 95)),
        "slope_max": float(slope.max()),
        "angle_p50_deg": float(np.percentile(angles, 50)),
        "angle_p95_deg": float(np.percentile(angles, 95)),
        "angle_max_deg": float(angles.max()),
        "height_rms_mm": float(np.sqrt(np.mean((h[inside] - float(np.mean(h[inside]))) ** 2))),
        "height_peak_to_valley_mm": float(np.ptp(h[inside])),
        "curvature_p50_per_mm": float(np.percentile(curv, 50)),
        "curvature_p99_per_mm": float(np.percentile(curv, 99)),
        "curvature_max_per_mm": float(curv.max()),
    }


'''
p.write_text(s[:old_start] + new + s[old_end:], encoding="utf-8")
print("patched", len(new))
