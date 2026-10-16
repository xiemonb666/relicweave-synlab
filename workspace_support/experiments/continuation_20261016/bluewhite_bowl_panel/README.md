# Sourced blue-white panel on the VF bowl candidate

Run from the workspace root:

```powershell
& '.\relicweave-synlab\.venv\Scripts\python.exe' '.\experiments\continuation_20261016\bluewhite_bowl_panel\run_bluewhite_bowl_panel.py'
```

The experiment uses the actual `outer_wall` `profile_rzs` from
`daily_aberdeen_108x53_v6_final` and the retained continuous Met 50899 cobalt-chroma
mask. It maps one finite 45 × 26 mm image panel to the bowl's sampled outer meridian,
using the physical arc coordinate `X = r(s) * wrapped(theta - theta0)`. The photo top
maps toward lower `s`, which is the first profile sample at the outer rim for this chart.
The generic chart payload's zero third column is therefore recorded and recomputed from
the finite `(r,z)` polyline.

The zero-spread field and the `m=0.25`, `K_s=0.02 mm²`, `K_theta=0.08 mm²` comparison
are appearance controls. The mask is an already-fired-photo proxy that retains tonal
variation, projection, lighting, glaze, and source-vase curvature; added spread is a
stylized transformation with a double-spread risk. The bowl and vase-derived panel form
a new synthetic design, not a historical bowl decoration. The candidate meridian is a
finite-polyline size-reference geometry, not an exact CAD reconstruction or scan.

`outputs_v1/receipt.json` records source and geometry hashes, panel mapping and shear,
halo, grid sensitivity, mass residuals, and interpretation limits. The coarse and fine
NPZ archives contain the sampled loading, bound/mobile/total fields, geometry axes,
cell areas, and linear-RGB appearance. PNG previews show the unwrapped zero-spread and
spread comparison plus a physical-mm density cross-section.
