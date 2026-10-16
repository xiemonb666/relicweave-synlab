import pathlib
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
s = s.replace("""    pad = 12.0 * step_raster""",
"""    #: the raster must contain the whole taper (plus a margin): a taper clipped by the raster edge
    #: leaves the mask at ~0.8 on the edge, i.e. a step of 0.8 * relief in the middle of the sheet
    #: (measured: 0.147 mm of interpolation error, and it grew with the taper width).
    pad = float(width) + 12.0 * step_raster""")
p.write_text(s, encoding="utf-8")
print("ok")
