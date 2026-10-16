# A12 registered design-space adapter — 2026-10-15

`synlab.mothers.design_space` exposes the parameter models already registered for V01–V24 and sends every build through `synlab.mothers.api.create_mother`. It adds no generator and defines no source-derived dimensions. The adapter gives each existing type a structured field catalog, deterministic recipe/override precedence, structured build provenance and an explicit same-seed mesh-effect probe.

All 24 registered entries remain `SYNTHETIC_CONTROL` / `PARAMETRIC_CANDIDATE`. Their parameter bounds are generator constraints, not measured object dimensions. This work establishes no daily-use match, archaeological reconstruction, manufacturing attribution, source profile, or material qualification. `source_dimensions` and `visual_style` are `null`; `generator_assumption` records only the existing registry family.

## Parameter catalog

Call `parameter_space(vessel_id)` to get each model's field name, declared type, unit, registered minimum/maximum, canonical default, source of that default, registry shape-parameter declaration, and evidence status. It also separates `common_parameters` from `type_specific_parameters`: common fields are inherited from the nearest shared Pydantic parameter base, while type-specific fields are declared on the vessel model. These are existing schema fields; a shared name does not make values interchangeable across vessel types. `registered_model_count` reports where a same-named field occurs elsewhere.

`shape_effect.registry_declared_shape_driver` mirrors the current registry's `shape_parameters` list. That list is metadata, not proof. `probe_parameter_effect(...)` explicitly builds a baseline and a one-field variant with the same seed, then compares the actual mesh hash, bounds, volume and face count. Pass `base_params` for conditional geometry controls, such as enabling V18 perforations before probing `hole_diameter_mm`.

## Build behavior

`build_designed_mother(vessel_id, material_id="M01", *, base_params=None, overrides=None, style_preset=None, seed=0)` resolves parameters in this order:

1. Existing canonical defaults from `mothers.api.default_params`.
2. The selected named recipe, if any.
3. Caller-supplied `base_params`.
4. Explicit caller `overrides`.

Both user mappings and the recipe are checked against that vessel's declared fields. Unknown fields and schema-invalid values raise `SynLabError`; infeasible combinations are passed to the existing builder and returned with the implicated parameter fields and the generator's diagnostic. Successful builds return requested values, canonical values, realized values and any observable coercion or generator repair. The same vessel, material, parameters and integer seed replay to the same geometry hash.

The four built-in recipe sets are convenient numeric recipes for examples. Names such as `narrow_mouth` or `long_spout` describe their parameter values only; they are not historical subtypes or style attributions. Other registered types expose their declared parameters but have no built-in recipe in this module.

## Measured examples

`experiments/continuation_20261015/design_space/run_examples.py` creates one default and two one-field variants each for V01 bowl, V04 cup, V06 jar and V09 ewer at seed `20261015`. Each change uses a field declared directly on that type's parameter model. The script stores actual bounds, volume, mesh hash, vertices and faces in `experiments/continuation_20261015/design_space/outputs/metrics.json` and `outputs/mesh_arrays/`. `render_previews.py` uses the VesselForge matplotlib runtime to create plain orthographic X–Z projections; they are geometric previews, not reference comparisons.

| Type | Variant | Changed field | Bounds min → max (mm) | Volume (mm³) | Geometry hash |
|---|---|---|---|---:|---|
| V01 | default | — | (-102.117, -100.836, 8.038) → (102.190, 100.398, 85.589) | 184,888.885 | `sha256:af65ff4f…35a61895` |
| V01 | deeper_profile | `depth_ratio=0.62` | (-102.230, -100.933, 10.318) → (102.304, 100.490, 125.723) | 246,925.149 | `sha256:dcd48ceb…08cf3117` |
| V01 | rim_flare | `rim_flare=0.35` | (-113.730, -112.288, 8.038) → (113.803, 111.854, 86.039) | 205,252.277 | `sha256:7f40b4a3…952f0b93` |
| V04 | default | — | (-94.763, -96.417, 1.219) → (145.290, 96.901, 124.260) | 227,908.850 | `sha256:584a9c7c…09e80813` |
| V04 | thicker_handle | `handle_thickness_mm=11` | (-94.763, -96.417, 1.219) → (147.267, 96.901, 125.910) | 238,066.918 | `sha256:ab85614d…de24180c` |
| V04 | without_handle | `with_handle=false` | (-94.763, -96.417, 1.219) → (98.555, 96.901, 99.046) | 221,026.336 | `sha256:99ea4b27…d1650f68` |
| V06 | default | — | (-96.085, -96.026, 3.019) → (96.529, 96.163, 184.328) | 421,953.158 | `sha256:c547bf2f…692af5ae` |
| V06 | higher_shoulder | `shoulder_position=0.78` | (-96.078, -96.004, 3.190) → (96.634, 96.176, 184.560) | 425,721.373 | `sha256:9b29acfa…99b8443a` |
| V06 | wider_mouth | `mouth_ratio=0.78` | (-96.217, -96.157, 3.250) → (96.663, 96.295, 184.152) | 422,694.209 | `sha256:e33128fd…32ad8408` |
| V09 | default | — | (-90.611, -91.415, 3.207) → (129.654, 92.028, 184.933) | 401,284.282 | `sha256:190f5f06…b7532bba` |
| V09 | longer_spout | `spout_length_mm=145` | (-90.611, -91.415, 3.207) → (174.731, 92.028, 198.406) | 406,812.384 | `sha256:587582bb…88293f17` |
| V09 | steeper_spout | `spout_angle_deg=55` | (-90.611, -91.415, 3.207) → (142.129, 92.028, 184.933) | 401,546.351 | `sha256:52e580c6…1cac77a` |

The complete hashes, vertex/face counts, canonical parameter sets and adjustment lists are in `outputs/metrics.json`. `run_shape_effect_audit.py` and `outputs/shape_effect_probes.json` preserve the same-seed metadata-mismatch probes summarized below.

![V01 bowl side projections](/C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/experiments/continuation_20261015/design_space/outputs/previews/V01_side.png)

![V04 cup side projections](/C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/experiments/continuation_20261015/design_space/outputs/previews/V04_side.png)

![V06 jar side projections](/C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/experiments/continuation_20261015/design_space/outputs/previews/V06_side.png)

![V09 ewer side projections](/C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/experiments/continuation_20261015/design_space/outputs/previews/V09_side.png)

## Existing shape-field discrepancies found

The adapter leaves existing API and group metadata unchanged. Fixed-seed probes show that several declared inputs do not agree with the existing `shape_parameters` declarations, and one model accepts fields its builder ignores. Results below use the same seed and compare constructed meshes:

| Vessel / field | `shape_parameters` lists it | Observed geometry change | Finding |
|---|---:|---:|---|
| V01 `warp_amplitude` | no | yes | Same 4,128-face topology; bounds differ under `0.02 → 0.0`. |
| V01 `warp_eccentricity_mm` | no | yes | Bounds and geometry hash differ under `0.8 → 0.0`. |
| V01 `warp_lobes` | no | yes | Geometry hash differs under `2 → 6`. |
| V04 `with_handle` | no | yes | `true → false` changes 5,486 to 3,456 faces and removes the handle from the bounds. |
| V18 `groove_width_mm` | no | yes | At the default nonzero groove depth, `6 → 14` changes mesh hash and face count. |
| V18 `hole_diameter_mm` | no | yes, conditional | With `aeration_holes=4`, `8 → 14` changes mesh hash. At zero holes it is dormant. |
| V23 `diameter_mm` | no | no | `190 → 280` leaves geometry hash, bounds and 4,624-face count identical. |
| V23 `wall_mm` | no | no | `4 → 8` leaves geometry hash, bounds and face count identical. |
| V23 `base_mm` | no | no | `6.5 → 12` leaves geometry hash, bounds and face count identical. |

V23's inherited `diameter_mm`, `wall_mm` and `base_mm` values are accepted by `FigurineParams`, but `build_figurine` does not consume them. The adapter records these as unverified until probed and does not pretend the fields drive geometry. The existing schema/registry owners should decide whether to remove these accepted no-op fields or implement their intended effects. The shared warp omissions, V04 handle toggle and V18 conditional dimensions should likewise be reviewed against the registry's shape-field contract.

## Focused verification

Run the focused tests with:

```powershell
relicweave-synlab\.venv\Scripts\python.exe -m pytest relicweave-synlab\tests\test_design_space.py -q
```

Regenerate measurements with the project virtual environment, metadata probes with the same runtime, and previews with `third_party/vesselforge-runtime/venv/Scripts/python.exe`. No physics, source comparison, training export or global status update is performed here.
