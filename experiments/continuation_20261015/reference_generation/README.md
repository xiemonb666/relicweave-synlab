# Reference-guided geometry + appearance integration

This offline experiment now builds three controlled family instances from `recipe.json` using
the existing VesselForge `FootedBowlDesign` CAD driver, then composes reference-guided material
and pattern appearance with the existing SynLab APIs. The geometry driver writes fresh
non-overwriting candidates under `vesselforge/.../reference_forms/outputs`; the appearance
bundles and canonical experiment recipe go under `outputs_v3_pbr/`. The loader reads each VF
`surface.npz` as authoritative geometry, verifies producer hashes and structural reports, and
assigns A12 face tags through exact triangle-to-native-face and native-face-to-section
lineage. Appearance composition does not repair, resample, or otherwise change source
vertices/faces.

The recipe generates three new daily `FootedBowlDesign` candidates: `daily_baseline_tokusa`,
`daily_deep_jun_plain` (increased height), and `daily_broad_foot_tokusa` (wider foot). They are
parametric design variants, not measured archaeological specimens. Each instance receives one
source-conditioned material/pattern pair from the existing APIs:

| Pair | Material recipe | Pattern recipe |
| --- | --- | --- |
| `daily_tokusa_celadon_proxy` | Aberdeen porcelain/celadon source-conditioned appearance | Hasami tokusa outer-wall stripes |
| `jun_plain_bluegrey_proxy` | Met Jun stoneware/glaze source-conditioned appearance | Met Jun plain outer-wall field |

Each mix is a new mixed-source design. The surface stays the exact VF candidate geometry;
pattern relief is rejected because this integration does not alter the mesh. Material and
pattern fields are recorded separately as well as the explicit appearance transfer. Optical
measurements, physical glaze thickness, chemistry, firing/mechanics, and the candidate
meridian's exact source-object fidelity remain unknown.

Run the three recipe-controlled instances from the `relicweave-synlab` directory:

```powershell
.\.venv\Scripts\python.exe experiments\continuation_20261015\reference_generation\run_generation.py
```

`--recipe` selects another JSON recipe and `--output` selects a new experiment directory.
Both experiment and CAD output directories refuse to overwrite existing data. The recipe
selects one footed-bowl family, the existing `daily` or `met` geometry preset, named
`FootedBowlDesign` overrides, source-conditioned material/pattern styles and controls, and
independent material and pattern seeds for each instance. The bundled recipe creates a daily
baseline with Hasami tokusa, a deeper Jun plain-glaze candidate, and a broad-foot tokusa
candidate. These are mixed-source design variants, not specimen clones.

Render four views of each saved result with the VesselForge runtime (VTK):

```powershell
..\third_party\vesselforge-runtime\venv\Scripts\python.exe experiments\continuation_20261015\reference_generation\render_previews.py --output experiments\continuation_20261015\reference_generation\outputs_v3_pbr --preview-revision finish_proxy
```

Each preview has a lit PBR-appearance perspective view plus orthographic side, top, and underside views. The side camera has no vertical tilt. Display normals are area-weighted on the original shared mesh vertices before UV display duplication; smoothing crosses source CAD faces only at C1 section joins. The exact inside-floor source lineage receives the original interior finish appearance, while the exterior underside remains bare. The body-inner chart excludes the floor, so no floor decoration UV is claimed. PBR roughness and IOR use per-region medians of the source-conditioned design fields; these are uncalibrated appearance choices, not physical measurements.
The continuous texture sampler checks selected samples against the original general-purpose
source chart and audits periodic texture and face-UV seams. Texture `s` is a finite-polyline
arclength approximation, not exact CAD arclength. Per-instance SHA-256 receipts cover the
canonical instance recipe, source geometry files, fields, and texture. The generated bundles
are research evidence only; native fracture and training export are not run.

The same recipe CLI accepts between one and eight instances. Alongside the existing buildable
reference-style recipes, it supports the explicitly separate
`met_50899_partial_dragon_panel` source-field route. That route records the already-fired-photo
mask provenance and finite mapping/spread controls and does not claim a PAT-family pattern.
The paired recipe and execution commands live in
`experiments/continuation_20261016/bluewhite_reference_generation/README.md`; its new output
directory is separate from `outputs_v3_pbr`.
