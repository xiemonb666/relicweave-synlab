# Native cohesive fragment observations (2026-10-15)

This is a research-only observation/export adapter for the native closed-fragment packet at
`pgfrag/data/continuation_20261015/native_cohesive_fragments_v5`. It consumes the complete
`pgfrag.native_cohesive_fragments.v1` packet returned by
`pgfrag.src.pgfrag.cohesive_fragments.extract_cohesive_fragments`; it does not infer fragments
from source-volume labels or alter the source solver output.

The adapter lives in
[`native_cohesive.py`](../../../relicweave-synlab/synlab/integrations/native_cohesive.py).
`validate_native_cohesive_fragments()` verifies the packet inventory, byte counts and SHA-256
records; exact native arrays and extractor JSON; positive rest/current T4 volumes; complete
tetrahedron and node ownership; density-weighted mass coverage; native failed-interface pairs
and facet failure evidence; and each component's oriented, closed boundary edge incidence. It
also rebuilds each component boundary from T4 face incidence and rejects surfaces that do not
equal that independently derived oriented boundary. Raw native cohesive connectivity, damage,
traction vectors, and openings are checked against the extractor's node ancestry and QP evidence.
The QP failure decision is recomputed from raw damage and the Euclidean norm of each raw traction
vector, then checked against every declared QP flag, facet row, and boundary pair. For the bowl
source it also checks outer/inner/rim appearance-region codes against the source rest geometry.
If a case declares positive `interface.penalty_Pa_m`, state must include finite raw
`cohesive_contact_traction_Pa`; QP traction gates are recomputed from the norm of the sum of raw
cohesive and contact vectors. This establishes native topology and data integrity, not calibrated
material behavior.

`export_native_cohesive_dataset()` makes software RGB-D observations with the existing NumPy
rasterizer and imaging chain. Every view receives an independently sampled proper sensor frame;
visible depth pixels are back-projected to camera-frame XYZ and randomly permuted per view. The
source recipe's exact `world_xyz_rest_mm; band centers use global Z` map is kept unchanged and
sampled continuously at raster barycentric coordinates. Paint is applied only to outer region 1;
inner region 2, rim region 3, and failed-crack region 255 retain the source preview fallback
colors. The software observations are idealized proxies: RGB capture noise is disabled, XYZ is
back-projected from the synthetic depth image, and no physical camera rig has been validated.
Control status is inherited from the source packet when present and otherwise remains
`NOT_REVIEWED`. A caller-supplied review must name the exact frozen-case SHA; it is recorded in the
dataset manifest and cannot override a status already declared by the source packet. It does not
change the adapter's physical or calibration qualification.

The feature NPZ has a strict observable-only allowlist: `rgb_u8`, `depth_m`,
`point_xyz_sensor_m`, `normal_sensor`, `normal_valid`, and `view_point_offsets`. Native IDs,
ancestry, face/component labels, rest/current coordinates, velocity, and the sensor transforms
and point-to-triangle alignment are kept in `offline_targets.npz` and the byte-exact packet under
`offline_truth/source_packet/`. Native velocity stays available in native-frame
`point_velocity_mps`; a second offline target, `point_velocity_sensor_mps`, applies the same
view's rotation to the vector. Current/rest point positions are in `NATIVE_SOURCE_WORLD_METRES`;
sensor XYZ is in camera coordinates. The dataset loader verifies both output hashes, vector-frame
rotation, and that each anonymous sensor point aligns to its offline target and source face.

All fragments and views come from one source case and one simulation event. The manifest groups
them by the frozen case and run receipt, sets `split=UNASSIGNED_RESEARCH`, and requires all views
and fragments from that source group to stay together. No train/validation/test split or
training/performance pass was run.

## Actual v5 export

Source validation returned `SOURCE_VERIFIED_RESEARCH_ONLY` with 1,317 native nodes, 4,342 T4s,
2 closed components, 2,208 boundary triangles, and 316 failed cohesive-side faces (158 paired
failed facets). Rest volume was `2.5398821979027247e-6 m^3`; density was `2,300 kg/m^3`; the
recomputed mass was `0.005841729055176267 kg`. Both components had zero boundary edges with bad
incidence or orientation.

The actual research dataset is
[`native_cohesive_v5_dataset`](../../../relicweave-synlab/data/continuation_20261015/native_cohesive_v5_dataset).
It contains 6 views (3 per component), 8,217 visible point samples, and 4,342 source tetrahedra.
The loader reopened it successfully; its status is `RESEARCH_ONLY_UNCALIBRATED`. The offline
truth directory contains all 10 files registered in the source packet manifest, in addition to
the feature/target arrays and dataset manifest.

This exact source case has a separately reviewed bonded-control failure. The source interface
penalty was `0 Pa/m`; its loading-window RMS relative deviation was `2.99%`, exceeding the `2%`
gate, and its post-pulse relative deviation was `308%`. The dataset manifest records
`physical_control_status=FAILED_TRANSIENT_BONDED_COMPLIANCE`, bound to frozen-case SHA
`69bac6f740c7ee03ae08021288afff63e3ef110dbd8f7f12202e5e2c69dc4dde`. Zero contact penalty as a
possible cause remains under review. This source-specific failure does not alter the generic
adapter's status rules or imply a failure conclusion for future source packets. This v5 case has
zero penalty and predates the optional contact-traction array; a future positive-penalty packet
must provide it and pass the recomputed vector-sum gate.

Qualification is explicitly `physical_pass=false`, `pretrain_eligible=false`,
`deployment_eligible=false`, `rig_obtainable=false`, and `production_a12_complete=false`.
Material calibration, mesh sensitivity, homogeneous fracture-path validation, and contact
validation remain outstanding. Relation labels were not generated. The preinserted weak seam,
uncalibrated material, and failed bonded control do not establish a physical fracture-path or
production A12 pass. All 158 paired facets passed the independently recomputed raw-vector/QP
failure criteria (474 of 474 QP samples); this confirms packet consistency for the recorded run,
not physical calibration or contact compliance.

## Actual v6 export

The separate `contact_weak_v1` packet is at
`pgfrag/data/continuation_20261015/native_cohesive_fragments_v6`. Its source manifest SHA-256 is
`c643d8bada69c1ea8132f8a97cc74301f04c3c1231182de95332315c40da280d`; its frozen-case SHA-256 is
`390d4775a88ddc5c2a17c132fb394ecc9cefb5ac956886e2b0b00ff855e6bc6c`, and its run-receipt SHA-256
is `c1162285546963f5c7631531cc2530e61427d7ab46a5ffdb156a148a93f8cdb2`. Native source validation
recomputed 158 failed paired facets across 474/474 quadrature samples, verified 2 closed components
and full mass coverage, and validated the raw `(158, 3, 3)` contact-traction array. The case declares
`penalty_Pa_m=1e15`; the recorded final contact traction is zero.

The inherited status is `PASSED_NARROW_ELASTIC_COMPLIANCE`. The included, hash-registered
same-mesh transient control comparison reports `0.716%` loading-window RMS, `1.324%` full-window
RMS, and `0.382%` difference at peak load, each below its declared `2%` diagnostic gate. These are
transient compliance measurements against the recorded same-mesh control. The root reports that
two native time-step runs completed; time convergence remains unestablished pending comparative
review. The independent contact and native arithmetic audits remain pending.

The actual dataset is
[`native_cohesive_v6_dataset`](../../../relicweave-synlab/data/continuation_20261015/native_cohesive_v6_dataset).
It uses seed `20261015`, 3 views per component, and 96 by 96 RGB-D frames. The loader reopened it
successfully: 6 views, 8,216 observed points, 4,342 T4s, and the raw contact-traction state remains
offline in targets. Its dataset manifest SHA-256 is
`7da1501c60f08fb40646f66a9ac8f680d978fc9a37068ac254ddba97f7c73a25`. The source group is
`native-cohesive-390d4775a88ddc5c2a17c132fb394ecc9cefb5ac956886e2b0b00ff855e6bc6c`, with
`split=UNASSIGNED_RESEARCH`; all views from the same case and run stay grouped.

The dataset remains `RESEARCH_ONLY_UNCALIBRATED` with `physical_pass=false`,
`pretrain_eligible=false`, `deployment_eligible=false`, and `production_a12_complete=false`.
Material calibration, mesh sensitivity, time convergence, homogeneous fracture-path validation,
and independent contact validation are not established. This narrow transient-control result
does not promote v6 to a blanket physical pass or alter v5's separately recorded
`FAILED_TRANSIENT_BONDED_COMPLIANCE` result. Run details and the loader smoke record are saved in
[`native_cohesive_v6_run_summary.json`](../../../relicweave-synlab/data/continuation_20261015/native_cohesive_v6_run_summary.json)
and
[`native_cohesive_v6_loader_smoke.json`](../../../relicweave-synlab/data/continuation_20261015/native_cohesive_v6_loader_smoke.json).

## Verification

Run from `relicweave-synlab` with its project environment:

```powershell
.venv\Scripts\python.exe -m pytest tests/a12/integrations/test_native_cohesive.py -q
```

The tests use hand-calculable 6 mm tetrahedra to check closed oriented edges, volume and mass;
they exercise depth-buffer occlusion in a real software render, verify sensory/offline field
separation and random view alignment, check a manual 90-degree vector rotation, and reject both
source-packet and exported-file hash corruption. They also verify that caller-supplied control
review metadata is bound to the exact source case and that unreviewed fixture packets stay
`NOT_REVIEWED`, and positive contact penalty requires and validates raw contact traction. Current
result: **7 passed**. The v5 and v6 source validation, export, and dataset loaders were also run
with the same environment.
