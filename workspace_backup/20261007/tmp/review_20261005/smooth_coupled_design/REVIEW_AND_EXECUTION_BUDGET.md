# Frozen candidate review and execution budget

Accuracy corrections in the current source freeze: normal-ray rows no longer carry a blanket `2.5 mm` paired-gap value. The report states that the base has no declared radial pairing and that the shoulder-to-rim side gap changes from `2.5 mm` to `3.5 mm`; radial gaps are not normal thickness. A `null` sampled curvature minimum can count as infinite radius only when every sample is finite and the derivative speed is non-degenerate. Any invalid sample now fails the corresponding finite curvature target.

Candidate: `beaker-coupled-fairing-math-v2`, one fixed beaker RZ section. Review the source and case hashes in `FROZEN_SHA256.txt` before authorizing the single final diagnostic and plot.

The exact lip feasibility proof applies because the fixed lip has a regular convex one-turn half-turn, opposite vertical endpoint tangents, continuous zero endpoint curvature, and a `3.5 mm` horizontal endpoint gap. At the prior `2.5 mm` gap, `Rmin >= 1.25 mm` was strictly impossible under those assumptions. The local thickening changes only the mouth transition; it does not assert that `3.5 mm` is stylistically or materially correct. Style and material remain unknown.

The frozen design target is a finite-sample curvature radius of at least `1.25 mm` on the outer/inner base fairings, the first two lower-body spans, and the lip. The prior pre-freeze exploration measured the inner base fairing's second span near `0.743 mm`, so the present candidate likely remains `PURE_MATH_DIAGNOSTIC_NEEDS_REVIEW`. Keep that outcome and its exit code; do not change parameters or thresholds after the run. Exact C2 and control-polygon checks are separate from this finite curvature target.

After root acceptance of these frozen inputs, execute once from the repository root using the configured runtime:

```powershell
third_party/vesselforge-runtime/venv/Scripts/python.exe -B `
  vesselforge/experiments/smooth_surface_coupled_design_20261005/coupled_profile_math.py `
  --output tmp/review_20261005/smooth_coupled_design/frozen_run/math_diagnostics.json `
  --curvature-samples-per-span 1001 `
  --ray-samples-per-span 101
```

Budget: one process, 30 seconds. Capture start/end time, elapsed wall time, command, exit code, stdout/stderr, and SHA-256 of source and case immediately before and after. A nonzero expected status is preserved as a result, not retried. Do not run CAD/OCC/STEP, do not run the bowl, and do not optimize or alter case/source after freeze.

If and only if that one run finishes, invoke `plot_coupled_section.py` once with its report and output directory `tmp/review_20261005/smooth_coupled_design/frozen_run/plot`. The plot uses the sampled analytic RZ curves at equal scale, plus the minimum finite sampled 2D candidate inner-boundary ray and the explicitly historical v1 classifier UNKNOWN. The plot and arrays are not CAD geometry. Record hashes for the report, plot arrays, and PNG. Keep outputs in the new `frozen_run` directory; never overwrite the exploratory JSON or the old v1 run.

Interpretation limits for root review:

- A sampled curvature radius is not a whole-span bound.
- Radial gaps are not normal wall thickness.
- The 2D ray search excludes near-axis points and samples with outward radial normal dot `<= 0.25`; it is not a native material-interval or global-minimum proof.
- Any unknown ray remains UNKNOWN. The historical v1 native classifier point is not a v2 failure location.
- `110 mm` is the rim endpoint elevation; the lip rises to `112.1875 mm` and the control-hull upper bound is `112.8 mm`.
- Physical/style qualification, native validity, closed-shell validity, global self-intersection, native bounding box, material thickness, and global minimum normal wall remain unknown.

If a future separately authorized native classifier probe is performed, keep classifier tolerance at `1e-7 mm`; record face identity, UV parameters, trim state, and orientation, then classify the surface point and offsets on both sides at `1e-4`, `1e-3`, and `1e-2 mm`. Do not widen tolerance to turn UNKNOWN into IN or OUT.
