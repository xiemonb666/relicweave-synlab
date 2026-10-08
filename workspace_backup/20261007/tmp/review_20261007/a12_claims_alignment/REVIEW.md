# A12 claims alignment — metadata-only review

**Scope:** source/report reconciliation only. No tests, Blender, CAD, solver, rendering, Git, or production/document edits were performed. The JSON reads and counters completed in under one second per probe.

## Findings

### Degradation: 155/155 is a row-status denominator, not a fidelity result

`status.md:33` says 31 axes × 5 levels, 155/155 PASS; `status.md:81` separately says 22/31 axes lack declared-to-measured pairing and notes G01/G08 errors. The saved evidence explains these as different predicates:

- `precision_probe_07_degrade_audit.json` has 31 registered axes, 5 planned levels, 155 measurement rows, and 155 `status=PASS` rows. All are `realized=true`, `valid=true`, `calibration_status=UNCALIBRATED`; `independent_mothers=1`. Provenance is 115 `BUILTIN_PROBE_REAL_RENDER` rows and 40 `BUILTIN_PROBE_FIXTURE_ROUGH_INTERFACE` rows. Thus 155/155 is a one-source-set execution/validity result, not calibrated accuracy or 20-mother coverage.
- `precision_probe_09_degrade_error.json` also has 155 rows with PASS status, but only 36 rows have both a non-null planned and measured quantity: four nonzero levels on 9/31 axes. The other 22 axes have no actual paired row. Level 0 has 31/31 identity/hash-equal rows, but no measured quantity pair, as expected for the identity level.
- The distinction in wording matters: the report has declared pair-key mappings for 28/31 axes. Only three axes lack any pair definition (`P01`, `P05`, `P06`), while 22/31 have no non-null realized pair in the saved rows. The JSON field `unpaired_axes` lists the former three; it does not enumerate all 22 axes with no realized pair. So “22/31 无配对” is accurate only when defined as **no observed planned/measured value pair**, not “no pair schema exists.”
- G01 has measured values for all four nonzero levels; its relative absolute errors are 13.0577%, 12.2257%, 11.1199%, and 8.1413%. Its level-0 row is PASS/identity with `measured=null`. Across the 36 paired rows, 10 exceed 1% relative error; G08 is the maximum at 20.2074% (planned 1.4, measured 1.1170963).

This is not a contradiction between “155 PASS” and G01/G08 errors: the PASS status and the later paired-quantity comparison are different checks. It is a reporting ambiguity if the first PASS is read as dose accuracy. The saved report itself makes the predicate and limited sample explicit.

### Patterns: fixture geometry, true-mother audit status, and applied geometry need separate denominators

`patterns.md` contains an internal true-mother count mismatch: §4.2 (`patterns.md:141–143`) says `families_ok=14/16` and names two failed geometry checks (PAT14/PAT15); §5 (`patterns.md:191`) says 13/16 with three remaining items. The “three” count is not explained by the two named failures in §4.2. I cannot determine from the saved files which wording was intended to be authoritative.

The directly saved `data/a12/reports/pattern_audit.json` is a separate, later `pattern-merge` artifact (`evidence_min.py --step pattern-merge`, `committed=false`), not proof that the exact `pattern-audit --root data/a12` route mentioned in `patterns.md:188–199` ran. It reports 16 families and 16/16 family-level QA statuses, but its geometry details show **both** PAT14 and PAT15 as `GUARD_REJECTED` with `PRECISION_BUDGET_EXCEEDED`. Their per-family `pass=true` records that the guard refused an under-resolved operation correctly; it does not mean relief/engraving displacement was applied. Therefore the saved JSON’s 16/16 family-audit result is not 16/16 successful geometry application.

The source dimensions also identify distinct snapshots: the fixture described in `patterns.md:97` is 28,088 faces; the §4.2 true-mother run is 23,520 faces; `pattern_audit.json` records `mother_source=synlab.mothers.api.create_mother`, `mother_id=V01-M01-101`, and 6,624 faces (base chart 8,213.7 mm²). The saved report is a true-mother-source run by its recorded provenance, but it cannot be proven to use the exact same mesh snapshot as the §4.2 narrative. Its guard measurements are PAT14 `min_wavelength=6.9124 mm`, PAT15 `6.7517 mm`, both with `achieved_edge=6.2887 mm`; these differ from the §4.2 values. Filesystem mtimes are `patterns.md` 2026-10-01 17:14 UTC and `pattern_audit.json` 2026-10-02 03:59 UTC; this ordering is inventory evidence only and does not identify equivalent commands or inputs.

Fixture and true-mother geometry are also distinct outcomes. The document’s fixture section (`patterns.md:118–119`, `149`) reports actual PAT14/PAT15 displacement on the analytic fixture: 0.8 mm / +1701.5 mm³ and 0.5 mm / −443.2 mm³, with zero flipped faces and watertightness. The true-mother evidence instead describes resolution-budget refusals. Keep the fixture result as a 2/2 fixture result; do not use it to claim true-mother geometry applied. `patterns.md:193` already marks 20 independent mothers as PENDING.

The `geometry_applied=true` aggregate in the saved merge report must be read with the per-family statuses: both geometry-family operations are guard-rejected. Without the producer’s precise aggregate predicate, treat that aggregate as UNKNOWN for successful physical geometry realization.

## Minimal documentation repair proposal (not applied)

1. At `status.md:33`, keep 155/155 but label it “155/155 per-level status PASS (execution/validity; one independent mother; uncalibrated).”
2. At `status.md:81`, distinguish the denominators: “28/31 axes have pair-key definitions; 9/31 have any non-null planned/measured values (36/155 levels); 22/31 have no realized pair; P01/P05/P06 lack a pair definition.” Keep the G01 range and G08 20.2% attached to the comparison report, not to the 155 PASS predicate.
3. In `patterns.md`, replace the 13/16 vs 14/16 prose with an explicit “historical count unresolved” note until a run-specific canonical report is identified. Add separate rows for (a) analytic fixture geometry applied for PAT14/PAT15, (b) true-mother family-audit status, and (c) true-mother geometry realization/refusal. Cite `pattern_audit.json` as `pattern-merge` evidence (16/16 family-audit rows, PAT14/PAT15 guard-refused), and leave the canonical A05 CLI report PENDING unless that exact route is evidenced.

## Source pins

SHA-256 values and filesystem mtimes (mtime is inventory metadata, not a run receipt):

| Path | SHA-256 |
|---|---|
| `relicweave-synlab/docs/a12/status.md` | `3c5593d847b2638c28c409b1921c9075e823b1cc8d54a90544a52bb9ddc1f1d5` |
| `relicweave-synlab/docs/a12/patterns.md` | `ca0cb226a17c1ee9950955bc2fda40827ea694b8ae7a2a92348f328dddc05311` |
| `relicweave-synlab/data/a12/reports/precision_probe_07_degrade_audit.json` | `b38d7dd1cddeff2dfcc06173de44ac83eb583cab045c05d6f47aff102a9f39fb` |
| `relicweave-synlab/data/a12/reports/precision_probe_09_degrade_error.json` | `d964413f473caea5bb75ec7a7ca39c140dcd8ac38892e13ebe3247a40327987e` |
| `relicweave-synlab/data/a12/reports/pattern_audit.json` | `e52989f1fa25cfb47442094c3c36dccbccc8b59a10ca97c9cbf910d3071e7e71` |

No readiness status was upgraded; this review only narrows the meaning of recorded counts and identifies unresolved provenance/count conflicts.
