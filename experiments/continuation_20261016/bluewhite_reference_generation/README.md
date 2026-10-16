# Sourced blue-and-white panel on one reusable footed-bowl mother

This two-instance recipe exercises the reusable `reference_generation/run_generation.py`
CLI on fresh `FootedBowlDesign` candidates. Both candidates use the same daily geometry
parameters, the same source-conditioned Met 50899 porcelain appearance profile, and the same
material and pattern seed values. Their canonical mesh-array hashes match.
The first instance sets effective spread duration to zero; the second uses the panel module's
default spread controls. All other panel mapping, source, and color controls are the same.

`met_50899_partial_dragon_panel` is a distinct source-field route. It samples the retained
continuous mask from the Met's Public Domain O2 photograph of object 50899 / accession
29.149.50, recorded as a late 18th-century Chinese porcelain vase painted in underglaze cobalt
blue. The extracted mask is a blue-excess chroma proxy from an already-fired photograph. The
Met record names a dragon; this recipe does not infer symbolic meaning, anatomy hidden behind
the vessel, the unseen wrap, or pre-firing brush placement. See
`docs/a12/BLUEWHITE_MOTIF_SOURCES_20261015.json` for the source record and extraction
limitations. The mask's expected SHA-256 is checked before image decoding.

The finite panel defaults to 45 × 26 mm, centered at half of the source outer-meridian chart's
finite-polyline arclength and `theta=pi`. That theta is the `-X` meridian for the registered
`[r*cos(theta), r*sin(theta)]` coordinate convention. The preview's separate panel views use
the source-profile-derived outward normal at the saved panel center and check it against nearby
native outer-face normals; they do not change panel placement or scale. The full four-view
side, top, 3D, and underside preview remains. The panel is not tiled. The field module records
`K_s=0.02 mm²`, `K_theta=0.08 mm²`, effective duration, mobile fraction, grid, finite-width
checks, mass checks, and its numerical solver receipt. `n_s=240`, `n_theta=1024`, and a 2 mm
boundary halo are the default field settings.

The sampled density changes outer-wall source-conditioned material albedo by
`exp(-tau_rgb * density)`. Material roughness and IOR stay as supplied by the material profile.
The compatibility check uses the profile's classified substrate material class. The Met's
named cobalt decoration remains source evidence for the image; another compatible ceramic
profile does not need a separate historical cobalt-decoration fact. The field module's
standalone normalized `linear_rgb` diagnostic is retained in `bluewhite_panel_fields.npz`;
the on-bowl albedo is stored separately in the geometry and continuous-texture bundles.
The exact exterior underside, foot, inside wall/floor, rim, and future fracture interface do
not receive this pigment field. The outer-wall face values and continuous UV texture both
sample the same `s/theta` field. Geometry vertices, triangles, source-face IDs, material
mechanics, and fracture data are not changed by this appearance adapter. This is a research
appearance proxy, not a recovered firing process, optical calibration, physical glaze layer,
specimen reproduction, or production claim.

From the `relicweave-synlab` directory, build the candidates and replayable evidence bundles:

```powershell
.\.venv\Scripts\python.exe experiments\continuation_20261015\reference_generation\run_generation.py `
  --recipe experiments\continuation_20261016\bluewhite_reference_generation\recipe.json `
  --output experiments\continuation_20261016\bluewhite_reference_generation\outputs_v2
```

Render actual geometry in a lit four-view PBR appearance preview with VesselForge's VTK runtime:

```powershell
..\third_party\vesselforge-runtime\venv\Scripts\python.exe `
  experiments\continuation_20261015\reference_generation\render_previews.py `
  --output experiments\continuation_20261016\bluewhite_reference_generation\outputs_v2 `
  --preview-revision bluewhite_v3 `
  --lighting studio_ibl
```

`--lighting` is shared across every material and instance in one preview run. `legacy` is the
default to replay historical four-scene-light renders; this demo explicitly selects
`studio_ibl`, a neutral linear-RGB map with 0.6 base fill, 1.05 softboxes, a 64 × 32 grid, no
direct scene lights, and VTK's sRGB render-window mode.

The v3 preview adds two profile-normal views and a separate material-color swatch rendered
through VTK's actual PBR base-color texture path. It also writes
`texture_origin_probe_bluewhite_v3.png`, a two-panel asymmetric red/green over blue/yellow marker
rendered through VTK's same PNG/PBR path. The marker shows that raw `v=s/L` displays the PNG
bottom row at the rim, while the renderer-only `t=1-v` conversion restores PNG row 0 at the rim.
Saved chart UV and field arrays retain their original meaning; this conversion applies to every
outer-chart PNG texture at the renderer boundary. Probe corner measurements and scene settings
are recorded in `preview_manifest_bluewhite_v3.json` and the bundle receipts.

The swatch's median source material albedo is `[0.951, 0.941, 0.901]` linear RGB; its rendered
center crop measured `[210, 210, 210]` sRGB8. This is uncalibrated presentation lighting and a
renderer diagnostic, not an optical or colorimetric measurement. The previous v2 images remain
as an audit artifact; their artwork view was vertically inverted and v3 is the corrected preview.

The run writes each panel's `bluewhite_panel_fields.npz` and numerical
`bluewhite_panel_receipt.json`, face and continuous-texture density arrays, canonical recipe,
source/geometry hashes, replay comparison, and a bundle SHA-256 receipt. All output paths are
new and non-overwriting. The bundles are research data only; native fracture, A12 observation,
and training export are not run here.

The candidate bundles are in `outputs_v2/`; the earlier `outputs_v1/` bundle remains unchanged.
The v3 preview images are added to those bundles without replacing v2. Both instances have
geometry-array SHA-256
`7714b224dfc866d119cc1e42c664bf31c3ba6a05584630bad1c19b2f68195729`; before/after appearance
hashes agree for each. Bitwise replay passed for both instances. The retained fired-photo mask
SHA-256 is `bc166ca1adf15907f8049f39e81a8cfe75486818e231a2d4b998c49797782da5`. Total-density
mass drift was 0 for the no-spread case and `3.32e-16` for default spread. The field NPZ files
are byte-identical between v1 and v2. V3 four-view previews, panel-normal views, and PBR swatches
are saved beside each bundle as `preview_bluewhite_v3_4view.png`,
`preview_bluewhite_v3_panel_detail.png`, and `preview_bluewhite_v3_material_swatch.png`.
