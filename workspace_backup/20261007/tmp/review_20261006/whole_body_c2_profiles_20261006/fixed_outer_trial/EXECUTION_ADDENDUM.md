# Execution addendum

The saved point probe on `jar / outer_apex_to_shoulder` at `t=1/4` reports signed curvature `0.11222216144789537 mm⁻¹`. This exceeds the fixed body/shoulder target `1/9 = 0.111111… mm⁻¹`, so this span has a **`POINT_COUNTEREXAMPLE_TARGET`** for the minimum-radius-at-least-9-mm requirement. The finite sample is sufficient to refute that pointwise curvature target; the prior full-span upper-bound status remains `UNKNOWN_BOUND_TOO_LOOSE_OR_TARGET_NOT_PROVED` and is not rewritten.

At this same point the sampled 3-mm offset tangent factor is `0.6633335156563138 > 0`, which is point evidence only. It does not establish full-span offset regularity, an inner curve, global nonintersection, or minimum wall thickness. The original diagnostic JSON, curves, fixed inputs, and source remain unchanged; no rerun was performed.

Source result: `outer_math_diagnostic.json`, SHA-256 `eb60138fc559d5a06ab2b4febf82fdc6654e6bbeab84f05f847c65934ffbbd4f`.
