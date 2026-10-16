# VesselForge spherical bowl continuation — 2026-10-15

## Implemented API

The new independent module `vesselforge.spherical_bowl` adds an analytic concentric hemispherical shell without changing the legacy `VesselSpec` or `create_asset_package` path. Its default `BowlSpec` uses outer radius 12 mm, inner radius 8 mm, center `(0, 0, 12)` mm, and the lower half-space `z <= 12` mm. The opening is the annular rim at `z = 12` mm; the bottom tip is at `z = 0` mm. The analytic design separation is 4 mm.

The API provides:

- `BowlSpec`, `build_spherical_bowl_solid`, and `analytic_spherical_bowl_volume_mm3` for the native CAD solid and exact volume.
- `contains_material` and `segment_in_material` for boundary-inclusive point and full-segment shell membership. Segments require both original endpoints in the material; the closest point on the complete segment is checked against the inner sphere.
- `generate_solver_points` for centroid-selected lattice points and the explicitly approximate `accepted_count * h^3` volume estimate. It rejects candidate grids above 2,000,000 before allocating a meshgrid and rejects a grid with no cell centers.
- `create_spherical_bowl_asset_package` for a `forge.asset.v1` package, canonical STEP face semantics and lineage, triangle fields, and continuous paint evaluation from immutable rest-coordinate Z.

The paint recipe remains a deterministic procedural candidate with `geometry_relief_mm = 0` and `historical_style_validation = NOT_VALIDATED`. The package mechanics are the root-selected native-case values `rho = 2300 kg/m^3`, `E = 70 GPa`, `nu = 0.25`, and `Gc = 7.6 J/m^2`; they remain `UNVALIDATED_PROTOTYPE` placeholders with no specimen test or calibration. The source records the shape, both radii, and center in `manifest.provenance.spec` for downstream binding.

## Tests and generated packages

The focused suite is `vesselforge/tests/test_spherical_bowl.py`. It covers default dimensions and analytic volume, invalid specifications, one closed native solid, point and complete-segment predicates, translated solver-point coordinates, the pre-allocation candidate-count guard, empty-grid rejection, continuous translated-coordinate paint, rest-coordinate retention, and the existing asset validator. The recorded run completed with **11 passed**.

The case JSON files and bounded runner live in `vesselforge/experiments/continuation_20261015/spherical_bowl/`. Each run keeps the case bytes, actual argv, runner source, a byte-for-byte snapshot and hash inventory of the VesselForge Python source, logs, and execution receipt in a fresh `runs/` directory. The PowerShell launcher stops a run at 60 seconds. The resulting packages are in `vesselforge/data/continuation_20261015/spherical_bowl/`.

| Pattern | Package | Receipt | Wall time | Package size | `validate_asset` | Independent STEP-volume check |
|---|---|---|---:|---:|---|---|
| `three_bands` | `vesselforge/data/continuation_20261015/spherical_bowl/three_bands/` | `vesselforge/experiments/continuation_20261015/spherical_bowl/runs/three_bands_01/receipt.json` | 10.031 s | 4,228,636 bytes | contract and geometry PASS | PASS; relative error `1.93e-13` |
| `four_bands` | `vesselforge/data/continuation_20261015/spherical_bowl/four_bands/` | `vesselforge/experiments/continuation_20261015/spherical_bowl/runs/four_bands_01/receipt.json` | 10.844 s | 4,227,455 bytes | contract and geometry PASS | PASS; relative error `1.93e-13` |

Both runs used CadQuery 2.8.0 and OCP 7.9.3.1. Each package has one valid solid and one closed shell with three classified B-rep faces. The independent check read volume back from exported STEP and compared it to `2*pi/3*(Ro^3 - Ri^3) = 2546.7844445101255 mm^3`; the STEP volume was `2546.784444509635 mm^3`. Each run stayed below both the 60-second and 32-MiB limits. The source inventory SHA-256 was `9efc793c528a3388a3883538f59301e289f8022b872cd1515756fb55192911ee` for both runs, and each receipt records `source_unchanged_during_run: true`.

The package manifest SHA-256 values are `0b33ba3dc1bdd12c05b65f73c4c570ab6e4b566702dcb5b33958b426e756ee67` for `three_bands` and `2fc26967acb7eb9e635080a056d6e96d23f3635579d367be57fe4258214c897e` for `four_bands`.
