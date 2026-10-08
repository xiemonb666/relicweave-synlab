import pathlib
p = pathlib.Path("synlab/fracture/implicit/backend.py")
s = p.read_text(encoding="utf-8")
# 1) draw ONE base seed from the caller rng, then give every (re)build of the field its own
#    deterministic stream: otherwise each outer attempt draws different Fourier phases and the
#    refinement loop compares two different surfaces (measured: 0.0103 / 0.0198 / 0.0640 mm).
s = s.replace("""    budget = float(error_budget_mm)
    if float(max_triangles) < 2 * triangle_budget:""",
"""    budget = float(error_budget_mm)
    #: every (re)build of the field uses its own deterministic stream derived from ONE draw of the
    #: caller's rng: a refinement loop that redraws the random phases compares different surfaces
    #: and can never converge (measured: 0.0103 / 0.0198 / 0.0640 mm error on the same geometry).
    base_seed = int(rng.integers(0, 2 ** 31 - 1))
    if float(max_triangles) < 2 * triangle_budget:""")
s = s.replace("""    field, field_info = build_implicit_field(
        basis, mesh, base_params, rng=rng,
        cross_section=(tris_uv, core_area, prepared["cross_info"]),
        delta_mm=delta_sampling, samples_per_wavelength=samples_per_wavelength,
        slope_target_p95_deg=slope_target, envelope_width_mm=envelope_width,
        raster_step_mm=opts.get("raster_step_mm"), slope_step_mm=opts.get("slope_step_mm"))
    timings["field_seconds"] = time.time() - stage""",
"""    field, field_info = build_implicit_field(
        basis, mesh, base_params, rng=np.random.default_rng(base_seed + 1),
        cross_section=(tris_uv, core_area, prepared["cross_info"]),
        delta_mm=delta_sampling, samples_per_wavelength=samples_per_wavelength,
        slope_target_p95_deg=slope_target, envelope_width_mm=envelope_width,
        raster_step_mm=opts.get("raster_step_mm"), slope_step_mm=opts.get("slope_step_mm"))
    timings["field_seconds"] = time.time() - stage""")
s = s.replace("""        field, field_info = build_implicit_field(
            basis, mesh, base_params, rng=rng,
            cross_section=(tris_uv, core_area, prepared["cross_info"]),
            delta_mm=delta_sampling, samples_per_wavelength=samples_per_wavelength,
            slope_target_p95_deg=slope_target, envelope_width_mm=envelope_width,
            raster_step_mm=opts.get("raster_step_mm"), slope_step_mm=opts.get("slope_step_mm"))
        timings["field_seconds"] = timings.get("field_seconds", 0.0) + (time.time() - stage)""",
"""        field, field_info = build_implicit_field(
            basis, mesh, base_params, rng=np.random.default_rng(base_seed + 1 + outer),
            cross_section=(tris_uv, core_area, prepared["cross_info"]),
            delta_mm=delta_sampling, samples_per_wavelength=samples_per_wavelength,
            slope_target_p95_deg=slope_target, envelope_width_mm=envelope_width,
            raster_step_mm=opts.get("raster_step_mm"), slope_step_mm=opts.get("slope_step_mm"))
        timings["field_seconds"] = timings.get("field_seconds", 0.0) + (time.time() - stage)""")
s = s.replace("""        envelope_width = float(min(4.0 * envelope_width, envelope_width * 1.4))""",
"""        envelope_width = float(min(4.0 * envelope_width, envelope_width * 1.5))""")
p.write_text(s, encoding="utf-8")
print("rng determinism patched")
