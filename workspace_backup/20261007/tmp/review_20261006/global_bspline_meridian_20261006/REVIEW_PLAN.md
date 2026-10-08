# Global B-spline meridian source review

This is a source freeze for the exact minimum-jerk candidate driver. No basis extraction, Hessian assembly, KKT solve, control net, curve sample, curvature certificate, offset, PNG, or CAD operation has been run.

## Review files

- `vesselforge/experiments/global_bspline_meridian_20261006/bspline_constraint_source.py`
- `vesselforge/experiments/global_bspline_meridian_20261006/bspline_minimum_jerk_driver.py`
- `vesselforge/experiments/global_bspline_meridian_20261006/fixed_cases.json`
- `vesselforge/experiments/global_bspline_meridian_20261006/DESIGN_PROPOSAL.md`
- `tmp/review_20261006/global_bspline_meridian_20261006/REVIEW_PLAN.md`

The adjacent `FREEZE_MANIFEST.json` pins this set; the manifest is reported out-of-band and does not hash itself.

## Root review questions

1. Confirm the global degree-5 clamped vector, unit rational weights, eleven controls, and simple internal knots. The driver verifies equality of exact endpoint jets through order four at every extracted-span join; no internal second derivative is forced to zero.
2. Confirm only axis-bottom, apex, and outer-mouth coordinates are exact interpolants. The old outer foot-turn heights 6/5.5 mm and old intermediate stations are free; base thickness is a later inner-floor datum.
3. Review the exact minimum-jerk Hessian scale `3600/h^5`, derived from the degree-2 Bernstein Gram integral of the third forward differences, plus the exact 16×16 `r` and 15×15 `z` KKT systems per family. The driver requires full equality-row rank and exact zero residuals and refuses ridge/pseudoinverse fallback. Three distinct fixed values annihilate the global quadratic nullspace in each coordinate, so the fairness Hessian is positive definite on the equality nullspace.
4. Review exact Boehm insertion and the degree-24 polynomial `P_R=S^3−R²D²`. The driver screens all six spans against both radius targets while base-target region assignment remains unknown. Nonnegative Bernstein coefficients plus a regularity proof certify a span; mixed signs remain UNKNOWN except a negative endpoint value, which is an actual point counterexample.
5. A mixed-sign derivative-pole or out-of-bounds control pole does not establish curve failure; those rows must say NOT_CERTIFIED. Strict inequalities, zero endpoint tangents, and negative endpoint `P_R` are exact point checks.
6. Preserve the offset distinction: signed local condition `1−3κ>0`; `|3κ|<1` is conservative sufficient, not necessary. Global reach, self-intersection, and wall thickness remain UNKNOWN.
7. Mouth datums remain 90/120 mm and clear openings 108/46 mm. Accepted candidate total crest targets are 92/122 mm, but this body-only driver constructs no lip and does not verify total height.

## If a later bounded check is approved

Only after explicit root READY, one bounded call may parse both cases, extract six exact Bezier spans, solve the four exact Fraction KKT systems, check the nine equalities and four strict inequalities per case, and report exact hull/monotonicity/regularity/join checks plus `P_R` coefficient screens. It must not optimize beyond the declared minimum-jerk objective, add knots, tune targets, or reinterpret conservative certificates as failures. Output goes only beneath `vesselforge/tmp/review_20261006/global_bspline_meridian_20261006/minimum_jerk_candidate`, with 10-second and 8-MiB caps.

The proposed one-shot argv, from the ShardForge workspace root, is:

```powershell
& 'C:\Users\xiemo\Desktop\ShardForge\third_party\vesselforge-runtime\venv\Scripts\python.exe' -B -c "from vesselforge.experiments.global_bspline_meridian_20261006.bspline_minimum_jerk_driver import run_fixed_minimum_jerk_source_plan; run_fixed_minimum_jerk_source_plan(root_ready=True)"
```

The invoking harness must enforce a 10-second wall limit and capture bounded stdout/stderr, exit code, and elapsed time. The driver itself refuses an existing output folder and rejects JSON larger than 8 MiB. Record pre/post SHA-256 for the pinned source and case inputs; the run should not change them. Exit 0 means exact arithmetic and report serialization completed, not that the vessel geometry passed every screen. Only `minimum_jerk_exact_result.json` is produced by this call. A later root-authorized render-only step may draw the saved exact control net and extracted spans without solving or changing controls; no PNG is part of this source freeze.

No CAD, STEP, mesh, material section, inner curve, lip bridge, production source, catalog, or legacy experiment is in scope.
