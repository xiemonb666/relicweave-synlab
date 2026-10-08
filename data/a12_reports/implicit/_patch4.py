import pathlib
p = pathlib.Path("synlab/fracture/implicit/backend.py")
s = p.read_text(encoding="utf-8")
s = s.replace("envelope_width = max(10.0 * delta_sampling, 1.4)", "envelope_width = max(8.0 * delta_sampling, 1.0)")
# the fine block must cover the taper (the field is non-flat one taper-width outside the footprint)
s = s.replace("""                fine_u=(fine_u[0] - 4.0 * delta, fine_u[1] + 4.0 * delta),
                fine_v=(fine_v[0] - 4.0 * delta, fine_v[1] + 4.0 * delta),""",
"""                fine_u=(fine_u[0] - (envelope_width + 4.0 * delta),
                        fine_u[1] + (envelope_width + 4.0 * delta)),
                fine_v=(fine_v[0] - (envelope_width + 4.0 * delta),
                        fine_v[1] + (envelope_width + 4.0 * delta)),""")
p.write_text(s, encoding="utf-8")
print("ok")
