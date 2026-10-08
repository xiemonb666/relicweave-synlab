# Single-span inner base candidate review plan

Candidate: `beaker-single-inner-fairing-math-v1`, derived from the frozen v2 beaker case. Review the new case, wrapper source, plot source, design note, and `FROZEN_SHA256.txt` before authorizing any diagnostic run.

The only geometry edit is replacing the inner base's parent two-span fairing with one quintic Hermite span from the unchanged `(17.5,10) mm` root jet to the unchanged `(10,4.5) mm` floor jet. Its sole parameter width is fixed at `0.8`, the exact sum of the two removed widths. Outer geometry, shoulder-to-rim radial thickening, lip, dimensions, endpoint jets, and all other case values are inherited. The wrapper verifies the parent v2 source/case hashes, endpoint equality, width sum, and a structural diff proving no other parent fields changed.

The wrapper calls the reviewed frozen math module by explicit case argument; it does not edit or copy that parent source and does not use the parent's default case path. It adds exact rational Bernstein sign and derivative-control reports for the one inner base span. Same nonzero sign of the exact curvature numerator plus strictly negative radial derivative controls is required for an exact regular, monotone-radius, convex/no-inflection arc certificate. Its 1001-sample curvature target remains `>= 1.25 mm`. A failed exact certificate or finite target yields `PURE_MATH_DIAGNOSTIC_NEEDS_REVIEW`; no parameters or thresholds are changed.

After root accepts this frozen input set, one bounded run is proposed (maximum 120 seconds) using the configured VesselForge Python runtime:

```powershell
third_party/vesselforge-runtime/venv/Scripts/python.exe -B `
  vesselforge/experiments/smooth_surface_single_inner_fairing_20261005/single_inner_fairing_math.py `
  --output tmp/review_20261005/smooth_single_inner_fairing/frozen_run/math_diagnostics.json
```

The wrapper fixes sampling at 1001 curvature samples per span and 101 normal-ray samples per eligible outer span; callers cannot vary those counts. Capture argv/runtime, stdout/stderr, exit code, wall time, and frozen source/case hashes before and after. Retain exit code 2 and any UNKNOWN without retry or adjustment. If that run completes, invoke `plot_single_inner_fairing_section.py` once and save the PNG and sampled arrays in `frozen_run/plot`. The legend uses a separate panel outside the plotting axes, so it cannot cover the lip or section boundary; axes remain equal scale. The plot shows the mathematical section only, with the historical v1 UNKNOWN explicitly marked as not tested on this candidate.

The frozen scope excludes CAD/OCC/STEP, bowl or other family cases, optimization or parameter sweeps, and every edit to the parent coupled candidate. A 2D candidate ray distance is not a classifier-confirmed material interval or global/surface-normal wall thickness. Any future native classifier UNKNOWN investigation must keep tolerance fixed at `1e-7 mm` and inspect the trim/UV/face-orientation evidence and offsets on both sides; widening tolerance cannot promote UNKNOWN.
