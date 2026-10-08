# Native BREP persistence candidate

**State:** `BREP_CANDIDATE` / `NOT_PROMOTED`

This experiment tests one native OpenCascade BREP round trip for the previously accepted H56/W41, 4 mm wall profile. It does not change the VesselForge production schema, API, generator, or `forge.asset.v1` behavior. STEP remains the canonical production asset format; this directory contains no `solid.step`.

## Geometry and persistence

The source is the same pair of exact degree-5 Bezier spans converted to B-splines, joined with C2 continuity, and offset inward by 4 mm with OCC's planar offset. The unchanged source profile passed its C2 join check and the 2,001-sample-per-span curvature check: minimum sampled radius 5.941661 mm against the 5 mm wall-plus-margin threshold.

Before persistence, OCC reported one valid solid with one shell, volume 26,998.301999424355 mm³, and a 41 × 41 × 56 mm bounding box. The only body persistence operation was `Shape.exportBrep` once followed by `Shape.importBrep` once. The imported solid retained one valid solid and shell; volume delta was 2.55e-11 mm³ and all six bounding-box bounds were unchanged. The BREP SHA-256 is `eb2fbf11776b291b1ca7a7d12d19d448ff03ed0a01717f88d5ec808434852e1f`.

The earlier STEP round trip remains failed evidence: its importer returned two shells, zero solids, and 8,671.448342 mm³. This BREP candidate does not claim STEP or cross-machine persistence support.

## Mesh and solid checks

The first mesh used 0.05 mm absolute linear deflection and 0.08 rad angular deflection. Its 10,217 nodes and 20,430 faces were watertight. In 602 deterministic samples, the maximum trimmed-face distance was 0.115315794 mm and p95 was 0.018486547 mm. The maximum came from an edge midpoint at `(-11.608900893, -9.376768122, 35.567023604)` mm on native BREP face 5.

One remesh of the same reimported BREP used 0.02 mm absolute linear deflection while keeping angular deflection at 0.08 rad. It produced 13,244 nodes and 26,484 faces, within the 200,000-face and 120-second budget (body plus section: 45,272 faces, 2.375 seconds). Its 602 samples had maximum distance 0.040084606 mm, p95 0.014721735 mm, and zero unknown samples. The worst sample was a triangle centroid at `(0.767308222, 15.257633082, 30.884973456)` mm on native BREP face 6; its trimmed-surface projection was classified `IN`.

Distances use the VesselForge deterministic edge-midpoint and triangle-centroid sample set. Triangle lineage maps each sample to the native BREP face that produced it. OCC projects each point to the face's supporting surface, checks periodic UV copies, and uses `BRepClass_FaceClassifier` to keep only trimmed-domain `IN` or `ON` projections. If no valid face projection exists, exact point-to-trim-edge distances are measured with `BRepExtrema_DistShapeShape`. This is finite sampled evidence, not a full Hausdorff bound.

The 336 outward normal rays measured 4.000000 mm sidewall thickness within floating-point precision; planar floor separation measured 4.000000 mm. The actual `y >= 0` half-space cut remained one valid solid with 0.499999844 retained volume fraction. Its section face on `y=0` was valid, positive-area, and had one wire. Actual-solid probes found floor material at z=2 mm inside, cavity at z=4.5 and z=28 mm outside, and the sampled wall band inside. Body and section meshes are watertight with positive signed volume.

## Candidate decision

This body-only result is experimental evidence for native BREP persistence. The image is rendered from the reimported BREP tessellation and its actual half-space cut at [native_brep_and_half_section.png](renders/native_brep_and_half_section.png). Detailed measurements and checks are in [brep_candidate_report.json](brep_candidate_report.json); command lines and exit codes are in the run receipts and logs. The SHA-256 manifest covers source inputs and generated deliverables.

The candidate is not promoted. It has no handle, fusion, or fillet. The kernel-native file is a candidate artifact only; production still requires canonical STEP and the existing strict asset contract.
