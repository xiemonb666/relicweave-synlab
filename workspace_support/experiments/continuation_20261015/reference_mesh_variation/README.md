# Controlled variations of Apsida SHM 17946:0047

This experiment applies a reusable, smooth radial deformation to the actual
indexed triangle mesh for the Apsida footed bowl. It keeps the source vertex
order and every face index. All 389 edge-connected components remain in the
derived meshes, including the 388 smaller fragments. The original vertex RGB
values are copied unchanged to each derived archive. Source UV coordinates and
normals remain available in the retained, hash-identified OBJ; render normals
are recomputed for each changed surface.

The OBJ declares no coordinate units. The output uses an explicit candidate
calibration of 1 raw unit = 1 m (1000 mm/raw unit), inferred from the catalog
height of 119 mm and the raw Z span of 0.119432. This gives a base output height
of 119.432 mm. The catalog rim and base measurements do not match this candidate
exactly, so it remains a scale hypothesis. The frame uses the audit's
least-squares top-rim center in X/Y, the raw Z midpoint, and candidate Z-up
axis. These assumptions are written into every receipt.

The local controls explore narrow log-radius changes: belly fullness +0.055,
upper body +0.035 with mouth +0.045, and foot width +0.055. The base has all
variation controls at zero. Each view sheet uses the same parallel camera and
physical scale for all four variants.

| Variant | Controls | Views and receipt |
| --- | --- | --- |
| Base anchor | No local deformation | [plain views](run01/base_anchor/views.png), [source color views](run01/base_anchor/source_color_views.png), [receipt](run01/base_anchor/receipt.json) |
| Fuller belly | `belly_fullness = 0.055` | [plain views](run01/fuller_belly/views.png), [source color views](run01/fuller_belly/source_color_views.png), [receipt](run01/fuller_belly/receipt.json) |
| Broader upper body and rim | `upperbody_width = 0.035`, `mouth_width = 0.045` | [plain views](run01/broader_upper_and_rim/views.png), [source color views](run01/broader_upper_and_rim/source_color_views.png), [receipt](run01/broader_upper_and_rim/receipt.json) |
| Broader foot | `foot_width = 0.055` | [plain views](run01/broader_foot/views.png), [source color views](run01/broader_foot/source_color_views.png), [receipt](run01/broader_foot/receipt.json) |

`run01/experiment.json` records source and derived hashes, license attribution,
unit and frame evidence, inherited component diagnostics, bounds, and sampled
Jacobian metrics. Pointwise Jacobian samples do not certify values between
vertices, triangle self-intersection, or wall thickness. This scan remains a
surface-only source; the deformer does not repair, fill, smooth, decimate,
remesh, or remove any data.

To reproduce the outputs from the repository root, run:

```powershell
.\third_party\vesselforge-runtime\venv\Scripts\python.exe .\experiments\continuation_20261015\reference_mesh_variation\generate_variations.py
```

The source model is attributed to Medelhavsmuseet, SHM 17946:0047, via Apsida /
Digital Heritage Research Lab under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Any redistributed adaptations must retain that attribution and license.
