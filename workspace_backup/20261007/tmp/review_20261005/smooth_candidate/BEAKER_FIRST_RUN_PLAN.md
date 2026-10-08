# Smooth candidate — first local run

**State: review package only. No CadQuery/OCP import, CAD construction, STEP export, tessellation, or image render has been run.** Wait for the main agent to review this source and explicitly approve the one-case CAD run.

## Frozen inputs and source

- Candidate source: `vesselforge/experiments/smooth_surface_route_20261004/route_source_draft.py`.
- Fixed input remains exactly the two-case `fixed_cases.json` with `beaker` and `bowl`; no station data or family scope changed.
- Original source snapshot: `route_source_draft.original.py`, SHA-256 `C8A686A6844926880C63C43174CFFBD4278DDE3DC9214638508417DD9295CE11`.
- Candidate source SHA-256: `359DC041B521799C39A08ED1F2A680A192EECC234FD8E47845511CAE58048D8E`.
- Fixed-case snapshot: `fixed_cases.original.json`, SHA-256 `9AFDFC764C28FC73932598B38A1A36DB56642864F620B0C67E2382AD5DAEF74F`.
- The candidate source hash is expected to differ because the all-hit refusal policy and explicit STEP bounds policy are recorded in this revision. `run_fixed_case` records source and fixed-case hashes in its report.

## Meridian continuity scope

The exact quintic endpoint-jet comparison covers every sequential non-axis section join: outside underside → outside base blend; base blend → first outer side span; all outer side station joins; outer side → rounded lip; rounded lip → reversed inner side; all reversed inner side station joins; and inner side → inner floor. The inner-floor → axis-closure join is excluded, and the closing axis-closure → outside-underside join is not in the sequential comparison. This is the section-curve C2 data check used before revolution; it is not a separate native face-continuity measurement.

## All-hit and bounding-box policy

Each selected normal ray retains the original OCC hit parameters. Exact floating-point duplicates may be removed as duplicate face reports. Distinct hits connected by adjacent gaps at or below `1e-5 mm` make the ray `UNKNOWN`; the report retains the raw values, the group members, and the full group span, and no group mean is used as a cut. Non-finite, negative, beyond-query-limit, or too-close hits cannot become interval boundaries. Each interval must be wider than `1e-6 mm` before its midpoint is classified, and every interval must classify as strict `IN` or `OUT`.

The ray coverage is limited to sampled revolution-face UV cell centers below the nominal rim with radius at least `1e-6 mm` and outward radial-normal dot greater than `0.25`. Planar floors, the rounded lip, axis samples, and revolved-face samples with radial-normal dot at or below `0.25` are excluded. The sample does not claim complete wall coverage or a global minimum normal thickness.

For STEP bounds, the experiment calls `OCP.BRepBndLib.AddOptimal_s(shape, box, False, False)` on the native and reloaded shapes. This excludes triangulation and shape-tolerance expansion. The existing `0.01 mm` per-bound and `0.01 mm³` volume tolerances stay unchanged.

## Single-case command after approval

Run only the beaker fixture, with a fresh output directory:

```powershell
$vfPy = '.\third_party\vesselforge-runtime\venv\Scripts\python.exe'
& $vfPy .\vesselforge\experiments\smooth_surface_route_20261004\route_source_draft.py `
  --family beaker `
  --output .\tmp\review_20261005\smooth_candidate\run_beaker `
  --step-roundtrip
```

The run should produce one JSON report, one native-solid/actual-section PNG, and the optional STEP round-trip file under that new directory. Do not run the bowl fixture unless the beaker report and real-surface image pass review. No batch command is part of this plan.

The pure checks are in `hit_audit_pure_checks.py`; they test raw-hit retention, exact duplicate removal, near-hit refusal for `0`, `0.75*tolerance`, `1.5*tolerance`, invalid hits, and strict-interior interval width without importing CadQuery/OCP.
