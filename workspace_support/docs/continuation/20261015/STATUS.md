# Continuation status — 2026-10-15

**Overall status: OPEN.** This snapshot records the work completed under the
2026-10-15 continuation plan. It preserves prior failures and evidence limits;
no full physical qualification is established here. The qualified complete
physical-package count remains **0**.

## User correction: real-world forms across the entire catalogue

The user explicitly requires both everyday utensils and archaeological vessels,
and requires every existing and future type to remain consistent with the real
world. The small thick hemispherical specimen below is now retained only as a
numerical control. Its successful CAD, physics and observation checks do not
make it a representative real bowl. The earlier fixed handled specimen and
unreferenced A12 procedural archetypes need the same review; this is not a
bowl-only cosmetic change.

The catalogue-wide requirements are in
[REAL_WORLD_REQUIREMENTS.md](REAL_WORLD_REQUIREMENTS.md), with the concrete
source gaps in [REALITY_GAP_INVENTORY.md](REALITY_GAP_INVENTORY.md). Primary
everyday and archaeological references are being recorded separately and a
reusable smooth meridian/section CAD builder is being implemented. Reference
dimensions, visual interpretation and assumed internal construction remain
distinct. Source photographs or a metadata tag alone cannot certify a complete
profile, wall thickness, historical reconstruction or material properties.

Before the next main-corps fracture run, the corrected geometry must be checked
in side, top, bottom and section views against its actual references. New
full-size geometry must retain realistic proportions and thickness while solver
resolution/resources are adapted; it must not be shrunk into another thick toy.
No new real-world-form acceptance has been established yet.

## Latest compression-corrected numerical control

The former penalty=0 control failure recorded below remains valid for that
case. It was diagnosed from actual paired native nodes, not just an `opening`
field. A separate frozen case now supplies prebreak compression stiffness
`Kn=1e15 Pa/m`. Its matched elastic-seam/perfect-bond control has pulse-window
response RMS difference `0.7160%`, full-window difference `1.3240%`, and
peak-load difference `0.3818%`, below the declared 2% criterion. See
`pgfrag/experiments/cohesive_vessel_20261015/contact_control_comparison_v1.json`.

The corrected baseline and half-dt native runs completed 3,244 and 6,488 steps
at the same 50 microsecond duration. Both have independent
`AUDIT_ARITHMETIC_PASS` reports under
`pgfrag/experiments/cohesive_vessel_20261015/outaudit/` in
`contact_weak_v1_run02_contactaware` and
`contact_weak_halfdt_v1_run01_contactaware`. The half-dt authoritative Windows
copy is `cohesive_contact_weak_halfdt_v1_readback02`; its 23 payloads were
verified against the completed source receipt. The first readback, made before
the producer completed, lacks completion files and is retained as incomplete.

`native_cohesive_fragments_v6` contains two closed native components, complete
4,342-tet volume/mass coverage, 158 paired failed facets and zero final residual
contact traction. Its A12 research export `native_cohesive_v6_dataset` loads
successfully with six ideal RGBD views and 8,216 visible points. Numerical
identities and the narrow compliance control passed; real-world shape,
calibrated material, homogeneous crack path, mesh/orientation convergence and
production PRETRAIN qualification have not. The specimen therefore remains a
control and is not the main realistic-vessel dataset.

## VesselForge geometry

Two actual `forge.asset.v1` CAD packages are present at
`vesselforge/data/continuation_20261015/spherical_bowl/{three_bands,four_bands}`.
Each is a closed concentric lower-hemisphere shell with `Ro = 12 mm`,
`Ri = 8 mm`, center `(0, 0, 12 mm)`, one solid, and three classified B-rep
faces. Their exported STEP volumes are `2546.784444509635 mm^3`, within a
relative error of `1.93e-13` of the analytic `2546.7844445101255 mm^3`.
The independent root calculation at
`experiments/continuation_20261015/root_geometry_math.json` verified both
package payload digests and the closed triangle meshes (102,038 vertices,
204,072 faces, Euler characteristic 2, every edge used twice with opposite
orientation). Their signed mesh volume is `2546.599439422196 mm^3`, a relative
error of `7.2643e-5` against the analytic volume.

The complete two-pattern preview is
`vesselforge/experiments/continuation_20261015/spherical_bowl/visualization/spherical_bowl_two_patterns.png`.
With the user's Smart App Control setting change, a normal OCP/CadQuery import
succeeded (OCP 7.9.3.1, CadQuery 2.8.0); no policy workaround or analytic-only
replacement was used. The bands and the mechanics remain experimental: paint is
procedural, relief is zero, historical style is unvalidated, and the material
values are `UNVALIDATED_PROTOTYPE` placeholders.

## Native PG-Frag bowl results

Four new source-pinned native results are present: zero-load `run_attempt_03`,
`alpha100/run_attempt_01`, `alpha300/run_attempt_01`, and
`alpha300_halfdt/run_attempt_01`. Each completed run contains 2,516 points,
70,648 retained pairs, and 24 initial cavity-crossing pair exclusions. The zero
case and `alpha100` and half-dt `alpha300` cases have independent audits with
`PASS`. The `alpha300` audit attempt is saved as `INPUT_ERROR` because its
requested figure-rendering dependency could not be imported; that case has no
independent audit pass in this record.

The cases use free release from a prescribed initial velocity field, with no
impact, drop, contact, external grip, or precrack. The 400-step baseline has
`dt = 6.4072827964e-8 s`; the 800-step alpha300 sensitivity case halves that to
`3.2036413982e-8 s` at the same duration. In the half-dt audit, the final total
mechanical energy is `2.1761%` above its initial value. Under the auditor's
peak-total-energy normalization, the maximum absolute drift is `2.1298%`.
That comparison does not establish time convergence. The audit also finds 58
active-bond graph components, including isolates; this is not a count of
fragments. Its largest component retains `0.0053544 kg` of the total
`0.0057868 kg` discrete mass.

The first two zero attempts remain in the run directory as failed evidence:
attempt 01 lacked `StaticArrays` in its isolated Julia depot; attempt 02 lacked a
`parameter_setup_type` method for the adapter. Attempt 03 is the successful run.
The half-dt run used `224,748,773 B` peak materialized output and `96,031,574 B`
persistent output under the `268,435,456 B` cap. The initial 128 MiB plan had
been raised to 256 MiB before the first native solve to preserve the full
same-duration half-dt history; this was an I/O allocation change only. Details
and per-run accounting are in
[`pgfrag/docs/continuation/20261015/BOWL_DYNAMICS.md`](../../../pgfrag/docs/continuation/20261015/BOWL_DYNAMICS.md).

These are approximate centroid-lattice diagnostics. They do not establish
calibrated ceramic response, physical crack surfaces, experimentally verified
fragments, mesh or time convergence, contact, or material qualification. The
discrete break-energy ledger is not a `Gc * area` measurement.

## Bowl tetrahedral partition

`vesselforge/experiments/continuation_20261015/bowl_tetra/run02/mesh/result.json`
records a geometry-only conforming tetrahedral partition: 1,212 nodes, 4,342
tetrahedra, and 158 interface triangles. Each interface triangle has two
distinct volume parents. The tetrahedral volume relative error is `0.2710%`;
centroids pass the material-membership check. The inserted plane is geometry
input, not a damage event or a post-fracture fragment partition. The partition
is now used by the bounded native cohesive vessel experiment below.

## Native cohesive vessel result and controls

The frozen `weak_seam_v4` and `weak_seam_halfdt_v2` runs both completed on the
same 1,212-node / 4,342-T4 bowl mesh, with 158 prescribed x=0 interface facets
(474 cohesive quadrature points) after insertion. The native model has 1,317
nodes, all DOFs free, and retains every native QP and nodal state at every
solver step. Independent audits for both runs report
`AUDIT_ARITHMETIC_PASS` with all-step/all-node coverage and exact frozen input
hashes. Their qualification remains `NOT_PHYSICAL_QUALIFIED`: the seam is
prescribed, the material is uncalibrated, and arithmetic identity checks do
not validate physical ceramic behavior.

| Run | Steps / dt | First all-QP failure | Final native dissipation |
| --- | --- | --- | --- |
| `cohesive_weak_seam_v4` | 3,244 / `1.54130702836e-8 s` | `11.12824 us` | `9.54567210e-4 J` |
| `cohesive_weak_seam_halfdt_v2` | 6,488 / `7.70653514180e-9 s` | `11.12053 us` | `9.54704673e-4 J` |

The measured discrete interface area is `1.2562331510e-4 m^2`, so `Gc*A_h` is
`9.5473719477e-4 J`. Final dissipation differs from this scale by `-0.0178%`
and `-0.00341%`, respectively. The two-level fixed-mesh comparison reports a
final mass-weighted displacement difference of `1.47e-9 m` and a relative
mass-weighted velocity difference of `0.1475%`. This is a sensitivity result,
not asymptotic time convergence; mesh/orientation sensitivity remains open.

The v5 native fragment packet derives two closed components from all 4,342
native T4s after all 158 prescribed interface facets fail. Both components
cover their full rest/current volume and mass, have source-exterior ancestry,
and share no native nodes. The packet now carries native cohesive connectivity
and QP damage, traction, and opening fields; the earlier v4 packet is preserved.
The closed topology is an engineering result for this prescribed seam, not
physical crack-path qualification. The existing v4 PNG is only a preview of
the older penalty-zero result and does not depict the pending compression
contact implementation. A research-only v5 observation package has appeared
in A12, but its bridge review is pending and its manifest still says
`physical_pass=false`, `pretrain_eligible=false`, and
`production_a12_complete=false`.

The key transient bonded-control gate currently fails. Against the matching
perfect-bond bulk diagnostic, the nonsoft 100 N cohesive control differs by
only `0.0131%` at the peak-load instant, but its pulse-window response RMS
difference is `2.9908%` against a declared `2%` gate; the full-window RMS
difference is `308.34%`. The same nonsoft case has a sampled minimum current
normal gap of `-5.202 um`; `weak_seam_v4` reaches `-0.420 um`. These cases have
no compression/contact branch. The separate 100 N weak-seam low control has
maximum damage `0.003897`, so it is not an undamaged elastic control; the 1 N
elastic control and zero-load control remain distinct cases. A new
`Kn=1e15` compression/contact case is being implemented but has no run result
or receipt in this snapshot and is not counted as passing.

The native run, fragment packet, independent audits, control failures, and
research-data caveats are recorded in
[`pgfrag/docs/continuation/20261015/NATIVE_COHESIVE_VESSEL.md`](../../../pgfrag/docs/continuation/20261015/NATIVE_COHESIVE_VESSEL.md).

## Free cohesive coupling spike

The bounded intrinsic cohesive patch now has one recorded successful native
run. Frozen source is under
`pgfrag/experiments/free_cohesive_patch_20261015/frozen_run03/`; the saved run
status, lineage, initial state, and independent analysis are under
`pgfrag/experiments/free_cohesive_patch_20261015/coupled_readback_run02/`.
It completed 10,000 steps and saved 10,001 states. All 15 declared independent
analysis gates passed, including source integrity, the reviewed total
bulk-plus-cohesive stability bound, free-DOF contract, paired parent-facet
lineage, all 24 quadrature-point histories, and signed interface-work closure.

The eight paired facets have positive area totaling `4e-6 m^2`. The final
independent signed work is `3.0410667858528943e-5 J`; native dissipated plus
reversible energy is `3.0410667858528932e-5 J`, with maximum history residual
`1.02e-20 J`. The reference `Gc * A` is `3.04e-5 J`. The full-debond-plus-hold
rule first registers at history index 4,130. This is a result for the frozen
preinserted planar-interface toy, not vessel material calibration, crack-path
qualification, fragment qualification, or a shard-training sample. See
[`pgfrag/docs/continuation/20261015/FREE_COHESIVE_PATCH.md`](../../../pgfrag/docs/continuation/20261015/FREE_COHESIVE_PATCH.md).

## A12 evidence and mask repair

`relicweave-synlab/data/continuation_20261015/native_alpha100_dataset/` contains
a six-state research-only point-snapshot dataset from the native alpha100
result. It samples states `0, 80, 160, 240, 320, 400` from 401 source states,
with 2,516 points and 70,648 bonds. The public research feature view contains
positions only, independently permuted and transformed per state; physics
targets remain offline. Its manifest says `NO_SHARDS`, `pretrain_eligible=false`,
`deployment_eligible=false`, and physical-fragment and validation status
`UNKNOWN`. `native_alpha100_loader_smoke.json` reports finite arrays and
`pretrain_eligible=false`.

The relation-AUC loss-mask repair is implemented and its two targeted suites
record **19 passed** in
`relicweave-synlab/docs/continuation/20261015/RELATION_MASK_FIX.md`. This is a
software-contract fix; it does not retroactively rerun historical metric jobs
or establish any new physical dataset qualification.

## Remaining goal

The constrained weak-seam path has now produced native separation, closed
tet-derived components, and a research-only software-observation package. The
overall vessel goal remains open because the matched transient bonded-compliance
gate fails and the current seam/contact model is not physically qualified.
Compression/contact and energy behavior, mesh/orientation and time-step
sensitivity, homogeneous crack-path validation, material calibration, and
physical-fragment qualification remain outstanding. The A12 bridge and
production export also remain under review. No complete physical package or
measured ceramic prediction is claimed by this continuation; qualified physical
package count remains **0**.
