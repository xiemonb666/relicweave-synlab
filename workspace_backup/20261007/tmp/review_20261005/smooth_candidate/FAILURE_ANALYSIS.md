# Frozen beaker run — failure analysis and next bounded design

## Run record

The single authorized beaker run used source SHA-256 `359DC041B521799C39A08ED1F2A680A192EECC234FD8E47845511CAE58048D8E` and fixed-case SHA-256 `9AFDFC764C28FC73932598B38A1A36DB56642864F620B0C67E2382AD5DAEF74F`. Pre-run and post-run hashes match. It ran with Python 3.12.14, CadQuery 2.8.0, and OCP 7.9.3.1 in 64.291 seconds. The Python process returned exit code 2 because local normal-ray evidence had one unknown. `stdout.txt` contains the CLI result; `stderr.txt` is empty. `run_metadata.json` records the exact argv, hashes, paths, and wall time.

## What passed and what did not

- Native B-rep: valid, exactly one valid solid and one closed shell, zero open shells; volume `61539.517793837906 mm³`. The section wire and face are valid, closed, and positive-area.
- Meridian data: all 13 recorded non-axis endpoint-jet joins pass. The 14 sampled non-axis spans have finite sample speeds and curvature values.
- Normal rays: 1840 selected side/base-transition probes yielded 1839 measured intervals and one `UNKNOWN`. The one unknown occurs before intersection, so it has no hit list or material-interval classification. The local normal-ray gate therefore fails and the process returns 2.
- Finite measured ray values range from `1.0216371371 mm` to `6.8864494474 mm`, with mean `2.5930461631 mm`. The radial setting is `2.5 mm`; these quantities remain separate, and the global minimum normal wall remains `UNKNOWN`.
- STEP: pass. Reloaded shape is valid with one closed shell and one solid. Volume delta is `-2.73576e-9 mm³`; all six geometry-only bbox deltas are `0 mm`. `AddOptimal_s(..., False, False)` was used and the `0.01 mm`/`0.01 mm³` limits were unchanged.

The actual native solid and half-space cut image is [beaker_native_body_and_section.png](run_beaker/beaker_native_body_and_section.png); the full report is [beaker_candidate_report.json](run_beaker/beaker_candidate_report.json). The image shows an open vessel, actual native section, and a visibly tight lower turn. This visual observation is separate from the local normal-ray failure.

## The single unknown

The report places it at face 3, `u=5.6941366846315`, `v=0.075`, with point `(13.5650305912, -9.0638636637, 4.5317384473) mm`. Face 3 has 320 UV cell centers inside trim; 16 were excluded by radial-normal dot `<= 0.25`; 304 were eligible, of which 303 measured. The failed cell is azimuth index 14 and meridian index 1 of that grid. Source selection had already accepted its trim state, so it was not rejected as outside the face trim.

Pure reconstruction from the frozen fixed Bezier data locates the point on `outer_side:0` at `t=0.075`, within `7.4e-15 mm` in `(r,z)`. The expected outward profile normal is `(0.2597769027, -0.9656686599)`; revolving it at the reported azimuth gives the saved native normal with dot product `1.0` and angle `0°`. This rules out a sampled-point mismatch and provides no evidence of reversed face orientation.

The remaining evidence is the classifier result: both the surface point and the outward offset classify as `TopAbs_IN`. The offset is `1e-4 mm` along the correctly oriented normal, while the solid-classifier tolerance is `1e-7 mm`. Since this ray fails before the all-hit query, the failure is not caused by hit clustering, interval selection, or material-interval classification. The report does not store per-face B-rep tolerances or an independent distance-to-boundary result, so the saved evidence cannot distinguish a local solid-classifier/boundary precision issue from an unexpected local solid classification. Do not change the classifier tolerance or count the ray as measured without a separate approved diagnostic.

The local curve is also unusually tight. At this point `outer_side:0` has sampled curvature radius `0.864106 mm`; the neighboring `outer_base_blend` minimum is `0.906052 mm`. The rounded lip reaches `0.915527 mm`. These are finite samples, not whole-span bounds. They explain the sharp lower turn and show why passing C2 endpoint tests alone is insufficient as a shape-quality criterion.

The pure reconstruction used for this finding is [analyze_beaker_unknown.py](analyze_beaker_unknown.py). It imports only the source's Python curve definitions and reads the saved report and JSON fixture; it does not import CadQuery/OCP or create CAD.

## Next smoother base and lip design

Treat the outside base blend, the first lower-wall span, and their shared endpoint jets as one fairing problem. Add a lower-wall transition station between `(16, 4.5)` and `(27, 20)` and choose its position, tangent, second derivative, and parameter widths to reduce the high curvature ramp. Keep the underside endpoint jet tied to the outside-floor line and keep one shared root jet on both sides of the base-blend/side join. Preserve monotone Bernstein control polygons and exact C2 checks. Set a separate curvature-radius design target before fitting; do not derive a normal-thickness claim from that target.

Give the lip a stated rounding parameter and fit its quintic bridge against a curvature bound. Its radial endpoint gap must continue to match the declared rim wall setting, while its endpoint tangents and second derivatives remain shared with the outer and reversed inner side endpoints. The current `8 mm` tangent scale and zero second derivatives produce a sampled minimum radius below `1 mm`; preserve the closed material section and test alternative curvature-controlled jets as a new fixed candidate, not by changing this frozen input.

Before any new CAD run, compare the candidate section curves and dense analytic curvature samples, run the exact fixed-case monotonicity preflight, and show the revised section profile for review. A later one-point classifier diagnostic may keep the existing `1e-7 mm` tolerance and record face trim state, native surface point, normal orientation, and solid-classifier states at signed offsets along both normal directions. Do not widen the tolerance or silently remove the sample.

## Local normal coverage path

The current report is a finite probe record, not complete wall coverage. For an authorized follow-up, save a status row for every UV cell center (`outside_trim`, `above_rim`, `near_axis`, `radial_normal_dot_cutoff`, `normal_unknown`, `hit_unknown`, `interval_unknown`, or `measured`) and require the count identity `eligible = measured + unknown`. Around this location, add a denser deterministic UV neighborhood while retaining the same normal and hit refusal rules; preserve all raw hits, strict material intervals, and per-sample distance values. Report the sampled region and exclusions beside its min/max/mean, and keep global minimum normal thickness `UNKNOWN`.
