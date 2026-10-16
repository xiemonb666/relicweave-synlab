# Continuation status — 2026-10-16

> Development was paused by the user on 2026-10-16. This is the pre-pause
> engineering snapshot. Current handover, offline checks and delivery records
> are in [the dated handover](../../handover/20261016/START_HERE.md).
> Prepared native preflights and coupon campaigns remain unstarted.

Overall goal remains OPEN. The previous goal turn made concrete progress: new
CAD/mesh/appearance modules, imported source assets, executed tests and failure
diagnoses changed the implementation and the next actions. It was not a verified
wait or a status-only turn.

## Requirements retained

Daily and archaeological utensils must both be covered. Every family needs real
form references, meaningful content/layout for ornament, source-aware materials,
multiple common and dedicated controls, and appropriate process constraints.
Open resources can be reused, modified or replaced by new construction according
to quality. All imported resources require refinement review. Blue-and-white
appearance requires brush density and pigment spread, not merely a blue icon.
The original native-fracture and experimental/training-data objective is retained.

## Current authoritative evidence

- `vesselforge/src/vesselforge/revolved_profile.py` builds smooth closed CAD from
  source-role meridian segments. Daily Aberdeen v6 and Met 18.56.44 v2 candidates,
  and three independent family variants, have actual STEP, surface, section,
  lineage and structural reports. These are source-guided designs; unmeasured
  wall/foot/section details remain assumptions. Root viewed the candidate sheets.
- `vesselforge/src/vesselforge/reference_mesh.py` varies an actual open museum
  footed-bowl mesh, preserving input indices and attributes. Root review fixed a
  height control that unintentionally also scaled width. Eight focused tests
  passed; corrected run02 is retained. It uses the raw scan and is not an accepted
  refined/physical asset.
- The Apsida SHM 17946:0047 source is retained with CC BY-SA 4.0 attribution and
  hashes under `third_party/reference-assets/apsida-shm17946-0047`. Refinement v3
  removed disconnected islands, exact zero-area faces and an opposite-winding
  coincident triangle pair in separate derivatives. It still has seven pinched
  vertex links. Its final status is
  `FAIL_UNQUALIFIED_SCAN_USE_AS_VISUAL_REFERENCE_ONLY`. Closed indexed edges alone
  did not qualify it. Do not silently feed this derivative to solid simulation.
- `step_partition.py` produced a full-size v5 diagnostic: 56,139 positive T4,
  18,236 nodes, 541 conformal interface triangles, 0.6121% CAD volume error and
  independent closed-boundary audit PASS. It is v5, not the latest reviewed v6.
  All exterior source roles remain UNKNOWN through that STEP import. Direct STEP
  face-label propagation failed: Gmsh imported the solid but returned blank face
  names. A separate native-face-witness/OCC-history bridge passed the actual v6
  bowl imprint and center-cut probe. The strengthened v15 proof includes native,
  round-trip and imported face areas, per-source cut areas, coherent missing and
  coincident-but-distinct-ID negative controls. Root independently checked source
  curve area/volume quadrature and every recorded raw map: PASS in
  `experiments/continuation_20261016/root_witness_readback.{py,json}`. Reusable
  `face_witness.py` and production-mesher integration passed root's current
  37-test run. The passing v6 production mesh and its remaining limits are below.
- A12 `mothers/design_space.py` exposes existing per-family models and reports
  requested/resolved/realized controls. Existing parameter metadata mismatches
  and ignored V23 inherited controls are documented, not hidden.
- Reference material recipes reuse A12's material field engine. Reference-only
  semantic coating now retains glaze on original inner/outer/rim faces and exposes
  bare body on foot/base/new fracture surfaces. A signed integer shift bug kept
  the old pore noise below its threshold; unsigned kernel v2 fixes this for new
  reference profiles while old profiles retain their versioned behavior.
  The source-aware set now also includes an explicit Met 50899 pale/clear porcelain
  appearance proxy; no measured optical or mechanical constants are claimed.
  Mechanics remain UNKNOWN for these sources.
- Reference patterns currently build source-guided Hasami Tokusa and a plain Jun
  baseline. Hacilar geometry is research-only until its actual zones/motif can
  be represented. Root did not accept triangles as substitutes for chevrons.
- The Met 50899 public-domain dragon photo has a readable extracted partial
  cobalt appearance proxy. It is a fired-photo projection, not recovered initial
  pigment, calibrated UV, or a complete seamless original motif.
- `patterns/underglaze.py` has a conservative metric surface diffusion operator
  using SciPy sparse exponential action. The first sourced demo passed numerical
  mass checks but root rejected its excessive full-field defocus as finished
  blue-and-white realism. A bound/mobile appearance extension and finer edge
  study now pass 16 tests; the v2 dragon-head study retains a sharper core and
  controlled halo, with weighted mass drift at most 7.3e-16. Root viewed it as an
  appearance foundation. It is not yet a complete bowl ornament; a sourced,
  continuous-tone panel on the actual varying-radius bowl is the next slice.
  Thermal/chemical calibration is not established. The actual bowl panel module
  `patterns/bluewhite_panel.py` now has a final standalone v2 study inside A12:
  245,760 cells, 1.66e-16 within-grid mass drift, finite-polyline shear bound
  0.63665. Coarse/fine density RMS difference is about 0.0584; this is sensitivity
  evidence, not convergence. Source density hashes include schema, shape and dtype.
  Root independently ran 22 panel/material checks after the final module changes.
  The new source-field route is now integrated into the recipe CLI. Two bundles
  compare zero/default effective spread with identical geometry/material seeds.
  The final `bluewhite_v3` previews use explicit experiment-wide studio IBL and
  renderer-only `t=1-v` conversion for all outer PNG textures. An asymmetric
  four-color marker independently verifies image orientation. Root viewed the
  upright panel/closeup and accepts the technical composition, while the cropped
  photo remains an unfinished ornament proxy. The next refinement adds opt-in
  `source_resolved_stationary_v1`: stationary brush detail is sampled directly
  from the immutable full-resolution source; only the mobile fraction is sampled
  from the transport grid. Zero transport reproduces the unchanged continuous
  source. Legacy sampling remains default. The unchanged 240x1024 field grid and
  bounded 480x2048 texture have separate resolution roles. Root reviewed both new
  panel closeups, checked all receipt hashes and exact 27,304,078-byte output size,
  and reran 55 focused panel/generator/underglaze/material checks: PASS. The finite
  volume mass receipt is explicitly DISCRETE_GRID_MASS_ONLY; source-detail retention
  is not a continuous-source mass/convergence or finished-composition claim.
- `integrations/reference_generator.py` loads the actual VF mother unchanged and
  composes material/pattern fields. Six first bundles exist. Face-centroid preview
  caused triangular stripe artifacts; root required continuous texture evaluation
  instead of changing stroke width to hide the rendering error. A unified recipe
  CLI generated three new variants in `outputs_v3_pbr`. Shared-source-vertex
  normals, explicit sRGB PBR texture binding, an exact inside-floor finish binding,
  and true orthographic side/top/underside views fix the technical preview defects.
  Root viewed all three refined previews. The latest independent run of the
  generator, panel and reference-material files passed 34 focused tests before
  the source-resolution slice, followed by the 55-check run described above. This
  accepts the technical composition/preview slice, not specimen reconstruction,
  photorealism, firing chemistry or physical-material calibration.

Root independently ran 26 focused VF checks and 68 A12 design/material/pattern
checks at the earlier stable checkpoint, all passing. A subsequent independent
run of the 16 underglaze and 8 reference-generator checks passed. New work must
have its own current checks and visual review.

## Physics and data remain distinct

The earlier compression-corrected Akantu control has real native evolution,
independently audited numerical histories, two closed fragments and six A12 RGBD
research views. Its small thick hemisphere remains a numerical control. Its
acceptance cannot be transferred to the new geometry or materials. No new native
fracture run on a reviewed full-size realistic mother has completed yet.

An actual Akantu zero-step cost/stability preflight on the full-size v5 diagnostic
mesh passed (`pgfrag/experiments/continuation_20261016/reference_vessel_preflight/
run_attempt_02/native_preflight/run01`). Attempt 01 failed before initialization
because of physical-group names and remains retained. Attempt 02 changes only
the two physical-group name strings; node/element blocks, connectivity, tags and
ordering are identical. It uses its own frozen source geometry, not a toy manifest.

The native preflight has 18,634 nodes after insertion, 56,139 T4, 541 cohesive
facets and 1,623 quadrature points. With explicitly uncalibrated placeholder
properties its mass is 0.07478999938 kg and selected stable step is 2.22182723 ns
(22,504 steps for 50 microseconds). No solver evolution or damage was run.
Full-history storage is forecast as 5,574,228,400 bytes with node stride 50 or
45,024,046,192 bytes with stride 1; the configured 64 MiB cap prevents that
allocation. The storage review and bounded mesh optimizer probe are complete;
their outcomes are recorded below.

Root independently reread the actual initial arrays and verified input hashes,
positive T4 volumes, density-times-volume mass, paired cohesive rest coordinates,
quadrature areas, all-free DOFs, balanced force/torque and step arithmetic in
`experiments/continuation_20261016/root_preflight_math.{py,json}`. Its status is
`INDEPENDENT_ZERO_STEP_READBACK_PASS`. This validates initialization and arithmetic,
not realistic fracture. The diagnostic geometry is v5 rather than the reviewed
v6, exterior ancestry is still UNKNOWN, and constitutive parameters are cost
placeholders. The next production mesh must retain the v6 source-face identities.

A single 100 ns zero-load benchmark subsequently evolved that same v5 diagnostic
for 46 native steps with full nodal history. It completed in 18.758 s wrapper /
23.753 s outer wall time. All 47 frames were committed and the independent
readback passed 22 checks; motion, damage, work, energy and residuals stayed zero.
The initial delta_max remains the declared delta0, rather than zero. The full
experiment/data footprint is 148,756,872 bytes, below its 256 MiB budget. This is
a cost/numerical control, not fracture or an ETA for a loaded full trajectory.

The storage review found that current standard NPY memmaps are already reusable
and consumed directly by auditors/exporters. Uncompressed chunks add overhead
and reader changes without meaningful storage savings. Root chose to retain
lossless named NPY histories for the next experiment; no new storage framework
was introduced. All QP histories remain at every step. Node stride distinguishes
full-step from sampled nodal checks explicitly.

The corrected Gmsh optimizer probe preserved all 49 indexed boundary/interface
surface entities with `Mesh.Renumber=0`, but did not improve the minimum T4
altitude (0.0587216 mm). The earlier apparent 103 mm movement was confounded by
automatic node-tag renumbering; the original report is retained with a correction
pointer. Netgen's failed discrete-mesh attempt is not a candidate. Root chose not
to add an optimizer with no demonstrated gain to production.

The v6 witness-backed mesh run01 at 3 mm failed the unchanged 1% CAD-volume gate
(1.060% error, 15,009 T4). Run02 at 2.5 mm stopped before meshing because its
105,561-cell forecast exceeded the 100,000-cell cap. Run03 at 2.6 mm and run04 at
2 mm also failed (1.232% and 1.125% errors). Root's per-source-face divergence
audit found that the rim alone accounted for about 93% of run04's net volume
deficit; its mesh area was 22.24% below the source CAD area.

Run05 therefore uses global 2.2 mm and verified rim-role-local 0.5 mm sizing.
Its 86,624 positive T4 pass the unchanged volume gate with 0.240308% error;
44,182 exterior triangles retain all 16 source FIDs/roles and 356 interface
triangles each have two opposite-partition parents. Minimum/p1/median altitude
is 0.1038/0.2380/0.6131 mm. The explicit caller-specific forecast is 93,808 T4 /
1,536,950,272 bytes within 100,000 T4 / 2 GiB; this is a forecast, not measured
peak memory or an OS memory cap. The external watchdog completed in 16.34 s.

Root independently verified hashes, source-curve volume/areas, all source roles,
T4 determinants, exterior orientation, all interface parent incidences and MSH
serialization in `experiments/continuation_20261016/root_v6_run05_readback.*`.
The NPZ has 25,748 nodes including 169 unused nodes; the MSH contains exactly the
25,579 T4-referenced nodes. Original integer tags bind the two formats, all ordered
cell corners agree, and the maximum ASCII/binary coordinate round-trip error is
6.94e-18 m. An initial root assertion incorrectly required binary equality; its
failure/correction is retained separately. Source identity is not inferred from
this coordinate tolerance. Foot-fillet mesh area deviations of roughly -9.72%
and -8.70% remain reported. This accepts a geometry/ancestry diagnostic, not
whole-feature accuracy, real-object reconstruction or physical evolution.

One actual native zero-step initialization/cost preflight on this unchanged run05
MSH is assigned in new `reference_v6_preflight` folders. It may alias only the two
physical-group names, proving Nodes/Elements/tag/order identity. No new v6 solver
evolution, fracture or data qualification is authorized by the zero-step result.
The earlier v5 used global 1.5 mm and forecast factor 10; it is not a same-size
comparison to run05.

The realistic bulk-crack route also needs extrinsic insertion work. Astra's
read-only reconstruction explains the old coupon's first negative native
dissipation from its saved signed vector work, to <7e-21 J. It occurs after an
unresolved direction reversal/complete-opening jump, not immediately on insertion.
Root derived the nonzero-state tangent in `EXTRINSIC_EVENT_MATH.md`. The completed
offline audit finds that insertion C carries zero/stale duplicated-node mass;
after solve D each new component has 5e-6 kg while total mass remains 4e-5 kg.
Missing historical acceleration/effective-parameter/contact arrays prevent an
independent force-law reconstruction. A zero-step wheel capability preflight now
confirms public getters for the needed cohesive fields, nodal arrays and FE shape
maps; it exposes no public integration-weight/Jacobian getter. No evolution was
performed in that capability check. A fully instrumented h/h2/h4 coupon campaign
is being prepared for root review; h/8 remains a separate confirmation decision.
The current weak-seam wrapper cannot be
promoted to arbitrary stress-driven ceramic fracture by renaming its output.
An independent generic internal-facet/source-node ancestry helper is implemented.
Root's 25 focused tests pass, and a saved-case read-only audit maps the same eight
source facets through B/C/D and reversed cohesive row order. Its scope explicitly
depends on preserved native bulk row/local-corner ancestry; exact coordinates
cannot independently distinguish a reorder of coincident identical cells.
An A12/PG generic mother-binding audit is assigned next, with no new physical
fragment package implied by plumbing work.

All imported resources still require actual refinement and review before final
use. The fired-photo panel is an intermediate reference/proxy and has not been
accepted as a finished ornament asset. Retaining a source, performing a crop, or
passing numerical checks alone does not satisfy the user's requested fine finish.

The complete qualified physical-package count remains zero. This is not a claim
that all forms/materials/motifs are implemented or that the overall goal is done.

