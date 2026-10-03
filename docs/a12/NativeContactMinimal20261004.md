# Native contact minimal probe — 2026-10-04

## Result

The native `submit(Job(ms, VelocityVerlet(...)); quiet=true)` path passed a real one-step preflight and each of the three requested cases completed once with exit code 0 in under 120 seconds. The baseline contact case changed the motion relative to the no-contact control, conserved total momentum to floating-point precision, and reversed the two-body center-relative velocity by the final state. At the endpoint the nearest points were still inside the native contact radius, so this is a rebound that is still within the penalty-contact range, not a fully separated state.

The run is a `POINT_CONTACT_NUMERICAL_PROTOTYPE`. It does not establish CAD surface contact, instrument geometry fidelity, or real fracture behavior.

## Setup and execution

Each body used eight corner points on a 2 mm lattice, each with volume `(2 mm)^3 = 8 mm^3`. Including half a point spacing at each boundary, the points represent a nominal 4 mm cube. The two centers began at `z=+2.25 mm` and `z=-2.25 mm`, so their nominal cell-envelope gap was 0.5 mm and the nearest point-center distance was 2.5 mm. Both bodies used bond-based material with `nu=0.25`, `rho=1000 kg/m^3`, `E=1e6 Pa`, `Gc=1 J/m^2`, and `no_failure!`; each body mass was `64e-6 kg`. There were no boundary conditions or external forces. Initial z velocities were `-0.2 m/s` for body A and `+0.2 m/s` for body B.

Native `calc_stable_timestep(bound_dh, 1.0)` returned `4.550099081502372e-5 s`; the `1.0` is the multiplier passed to that native bound calculation. The baseline used 240 steps at half the returned bound (`dt=2.275049540751186e-5 s`); the half-step case used 480 steps at `dt=1.137524770375593e-5 s`. Their measured solver-dt-to-bound ratios were `0.5` and `0.25`, respectively. Both ended at `0.005460118897802846 s`. The no-contact control used 240 steps at baseline `dt`. Contact cases used native radius `2 mm` and penalty factor `1e6`.

| Case | Steps | `dt` (s) | Runtime (s) | Final nearest point distance (mm) | Final center-relative z velocity A−B (m/s) | Nominal 4 mm cell-envelope overlap at end (mm) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Contact baseline | 240 | 2.275049540751186e-5 | 26.983 | 1.409837 | +0.247812 | 0.590437 |
| Contact half-dt | 480 | 1.137524770375593e-5 | 31.736 | 1.409837 | +0.247809 | 0.590435 |
| No-contact control | 240 | 2.275049540751186e-5 | 31.529 | 0.315952 | -0.400000 | 1.684048 |

The initial center-relative velocity was `-0.4 m/s`. Both contact cases ended with a positive relative velocity while retaining the initial center order, consistent with a rebound. Their nearest points remained within the 2 mm contact radius at the endpoint. The no-contact control kept approaching and its nominal point-cell envelopes overlapped further; nearest point centers remained 0.316 mm apart and the centers had not crossed. These overlap values describe this discrete point-cell setup, not measured CAD surface penetration.

## Independent checks

The exported CSVs contain all 16 points, native IDs 1–8 for each body, rest and final positions, initial and final velocities, mass, final native `b_int` in N/m³, and per-point active/broken bond flags. Each body had 48 directed bonds, all active; no point was omitted as an isolate. Maximum exported external-force density was zero in all cases.

Independent Python parsing found:

- The free-control final positions matched uniform motion within `1.11e-17 m`, and velocities within `3.95e-15 m/s`.
- Contact baseline body momentum changes were `+2.0729983363928722e-5 kg·m/s` for A and `-2.0729983363928722e-5 kg·m/s` for B in z. The half-dt changes agreed to the displayed precision. Maximum total momentum-change norm across cases was `3.42e-24 kg·m/s`.
- Baseline and half-dt final states differed by at most `2.78e-9 m` in point position and `7.29e-5 m/s` in point velocity. This is only a timestep sensitivity comparison; it is not presented as a convergence result.
- The contact baseline differed from control by up to `0.547 mm` in final point position and `0.324 m/s` in final point velocity.

The output has no per-step contact-force or contact-energy history. Time-integrated contact impulse and contact energy are therefore unknown; body `delta-P` is not a direct contact impulse integral.

## Provenance and artifacts

The result folders include Julia argv, exit code, runtime, stdout/stderr, per-point CSV, TOML summary, and source hashes. A path correction moved the four actual run folders from a mistaken `ShardForge\\SynLab` alias into the `relicweave-synlab` repository. The archived `execution.toml` preserves the exact original argv, exit, and runtime values, including the original output argument; archived log paths and current artifact paths are recorded separately. See [`path_migration.toml`](../../tmp/review_20261004/implementation/native_contact_minimal/path_migration.toml).

The initial and final point positions are shown in an x–z projection in millimetres; y coordinates are collapsed in this view:

![Initial and final native point positions in millimetres](../../tmp/review_20261004/implementation/native_contact_minimal/native_contact_minimal_points_xz.png)

The native implementation and upstream unit test were inspected read-only: [`short_range_force_contact.jl`](../../../pgfrag/src/pgfrag/resources/julia/vendor/Peridynamics.jl/src/physics/short_range_force_contact.jl) and [`test_short_range_force_contact.jl`](../../../pgfrag/vendor/Peridynamics.jl/test/unit/physics/test_short_range_force_contact.jl). The test confirms a one-step two-body contact-force path and the source applies force density to point pairs whose distance is below the specified radius.

Detailed per-case data and independent calculations are in [`native_contact_minimal/`](../../tmp/review_20261004/implementation/native_contact_minimal/), including [`independent_analysis.json`](../../tmp/review_20261004/implementation/native_contact_minimal/independent_analysis.json) and [`execution_attempts.md`](../../tmp/review_20261004/implementation/native_contact_minimal/execution_attempts.md). The earlier repository-local one-step output remains at `pgfrag/experiments/native_contact_minimal/results/preflight/` and is marked superseded in its README.
