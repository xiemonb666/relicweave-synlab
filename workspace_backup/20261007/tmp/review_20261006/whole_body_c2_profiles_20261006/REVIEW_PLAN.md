# Whole-body C3 source review and bounded-check plan

This is a source/design-only freeze candidate. No curve math, profile samples, PNG, CAD, OCC, STEP, or solver run has been executed. The future driver has a fail-closed `root_ready=True` gate and fixed output paths; execution still requires a separate explicit root READY after source review.

## Frozen review set

- `vesselforge/experiments/whole_body_c2_profiles_20261006/profile_design.py`
- `vesselforge/experiments/whole_body_c2_profiles_20261006/fixed_cases.json`
- `vesselforge/experiments/whole_body_c2_profiles_20261006/DESIGN_PROPOSAL.md`
- `vesselforge/experiments/whole_body_c2_profiles_20261006/CONTROL_HULL_DESIGN.md`
- `vesselforge/experiments/whole_body_c2_profiles_20261006/diagnostic_driver_source_only.py`
- `tmp/review_20261006/whole_body_c2_profiles_20261006/REVIEW_PLAN.md`

The SHA-256 pins for this exact set are recorded in the adjacent `FREEZE_MANIFEST.json`. The manifest itself is not self-pinned.

## Required source review

1. Confirm fixed bowl/jar stations, apexes `(60, 77.4)` and `(54, 62)`, mouth datums, semantic span set, and positive parameter lengths.
2. Review the exact degree-seven endpoint position/d1/d2/d3 pole formulas and shared-jet comparison. The parameter `s` is measured in mm but is not arc length; `d1` is dimensionless, `d2` is `1/mm`, and `d3` is `1/mm²`.
3. Confirm the arbitrary-parameter identities `κ = det(C′, C″)/|C′|³`, `C″ = v′T + κv²N`, `N′ = −κC′`, and `C_t′ = (1−tκ)C′`.
4. Check exact pole hulls and strict derivative projections. For curvature, the source-only driver uses exact rational Bernstein coefficients on four fixed parameter subintervals; any loose or nonpositive bound must remain UNKNOWN/FAIL, without subdivision or parameter adjustment.
5. Confirm wall semantics: the catalog’s 3 mm is radial in source; proposed 3 mm Euclidean normal offset is limited to listed outer side-wall spans. The inner profile is not constructed, and global minimum wall/nonintersection remains UNKNOWN.
6. Keep the height roles explicit: catalog 90/120 mm are mouth/body datums; candidate rim-crest bounding heights are 92/122 mm.

## One bounded future run, only after root READY

- Exactly 16 outer spans, eight per family; eight fixed `t=i/7` parameters per span (128 total).
- Exactly 16 normal-offset point probes (eight per family), each explicitly pointwise and not a wall certificate.
- Total fixed evaluations: 144, below the ceiling of 256. Four exact Bernstein interval pieces per span are algebraic bounds, not additional samples.
- Write one two-panel, equal-scale RZ PNG and one JSON diagnostic under `tmp/review_20261006/whole_body_c2_profiles_20261006/fixed_outer_trial/`; do not overwrite an existing trial.
- No inner spans, inner offset curve, CAD/OCC, STEP, solver, extra family, adaptive sampling, retuning, or retry.

The image is a plot of the mathematical source profile only. It is not CAD, a real-vessel image, or evidence of global wall thickness or vessel qualification.
