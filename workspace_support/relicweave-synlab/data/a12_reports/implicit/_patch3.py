import pathlib, re
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
# 1) fine-block margin must cover the taper width
s = s.replace('''    boundary_fn = lambda u, v: (np.asarray(field.unmasked(u, v), dtype=np.float64),) * 2  # noqa: E731
    envelope, samples = build_footprint_envelope(
        tris_uv, exact_area_mm2=float(core_area), bbox=bbox, step_mm=step_raster, width_mm=width,
        boundary_values_fn=boundary_fn,
        extension_iterations=int(240))''', '''    envelope, samples = build_footprint_envelope(
        tris_uv, exact_area_mm2=float(core_area), bbox=bbox, step_mm=step_raster, width_mm=width)''')
# 2) default taper width: wider than before (it only damps the OUTSIDE of the footprint)
s = s.replace("else max(10.0 * float(delta_mm), 1.4))", "else max(8.0 * float(delta_mm), 1.0))")
p.write_text(s, encoding="utf-8")
print("patched build_implicit_field")
