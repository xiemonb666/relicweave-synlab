# Peridynamics.jl runtime spike — 2026-10-03

## Status

**Historical status at the time of the first probe:** blocked before solver execution. The original upstream package import was stopped by Windows Application Control when it loaded an unsigned native dependency. This historical observation is retained below; it is superseded by the bounded headless fork follow-up.

## Installation evidence

- Official portable Julia: 1.10.12, x86_64-w64-mingw32.
- Archive: `third_party/pgfrag-runtime/julia-1.10.12-win64.zip` (183,434,216 bytes).
- Official SHA-256: `88177b1089a01f5254454ecbda888542d6038aba4d017a4bf8bc860322d7f9de`; the downloaded archive hash matched the Julia checksum file.
- Isolated Julia depot: `third_party/pgfrag-runtime/depot`.
- Isolated environment: `third_party/pgfrag-runtime/peridynamics-env`; Manifest reports Julia 1.10.12. Peridynamics.jl 0.5.4 installed successfully with automatic precompile disabled; install command returned exit code 0.
- Runtime attempt: Julia `--project=.` from the isolated environment with `JULIA_NUM_THREADS=2` and `using Peridynamics`.

## Failure evidence

`using Peridynamics` loads `WriteVTK`, which initializes `XML2_jll`. The OS rejected:

`third_party/pgfrag-runtime/depot/artifacts/74c0258ad6f614c0a10e61f6bbb6e85798cc1057/bin/libxml2-16.dll`

with: “An Application Control policy has blocked this file.” `Get-AuthenticodeSignature` reports `NotSigned`. Retrying with `--compiled-modules=no` reproduced the same denial. This is an operating-system application-control restriction, not evidence of an API or numerical failure. I did not alter file trust markings or attempt to bypass the policy.

## Historical conclusion / next decision at the first probe

The v0.5.4 API/source audit remains useful, but actual solver feasibility and performance are unverified. Do not describe the PD backend as running or the prototype as producing physical damage. A next attempt requires an execution route permitted by local Application Control (or a different approved backend/runtime). PeriLab may encounter the same restriction if its Julia dependencies load unsigned native libraries. No simulation parameters, calibration claims, or solver output are available.

## Follow-up — bounded headless source fork and actual tensile spike

The WSL and Docker execution paths were unavailable without changing system permissions, so they were left untouched. Under the authorized headless-fork scope, a local v0.5.4 source snapshot was copied out of the Julia package depot into `pgfrag/vendor/Peridynamics.jl`; no trust markings, App Control policy, or global package depot were changed. The fork removes only VTK/LightXML input/output: `WriteVTK`, VTK reader/export APIs, the VTK-only `BodyChunk.cells`/`get_cells` fields, and path-based output options. It reports backend id `peridynamics_jl_headless_0_5_4` and explicitly rejects VTK APIs. The mechanics, bond-system, contact, damage, and time-solver sources are intended to remain upstream-identical; a file-hash comparison report is still required before claiming that invariant is verified.

The fork imports and initializes under Julia 1.10.12 with one thread (`Peridynamics 0.5.4+pgfrag.1`, MPI rank 0). An actual CPU `BBMaterial` / `CriticalStretch` tensile job completed. v4 outputs and a machine-readable audit are in [series_v4](spike/series_v4/) and [series_v4_analysis](spike/series_v4_analysis/); the earlier main-reviewed [series_v3](spike/series_v3/) snapshot has not been overwritten. The updated fixture extracts native `BondSystem` endpoints plus both directed `storage.bond_active` states, asserts reciprocal agreement, emits canonical global point pairs, and builds connected components from intact horizon bonds. It also calls the upstream `export_field(:strain_energy_density, ...)`; loaded cases now have finite nonzero strain-energy output rather than default zero storage.

At `dx=1 mm`, horizon `3 mm`, nominal box request `6×6×16 mm`, `rho=1000 kg/m³`, `E=1 MPa`, `nu=0.25`, and `Gc=1 J/m²` (all mechanics values are `UNVALIDATED_PROTOTYPE`), the no-load case completed with zero damage and zero broken pairs. At equal 50-step duration, 0.1 m/s yielded max damage `0.1351` and 220 broken undirected pairs; 0.5 m/s yielded max damage `0.9286` and 2,504 broken pairs. High-load snapshots at 5/10/20/35/50 steps yielded 400/960/2,000/2,476/2,504 broken pairs. The final 50-step intact-bond graph splits into component sizes `[36, 504, 36]`; the two 36-point components are exactly the imposed bottom and top velocity boundary layers, not a ceramic fragment-size result.

The same `dx=1 mm` high-load run with half the timestep uses 100 steps and ends at the same measured physical time (`0.000961387912597604 s`) as the 50-step baseline. It yields max damage `0.8929`, 2,456 broken pairs, and the same three graph components. This is a numerical timestep-sensitivity check, not a convergence or physical-validation pass. The upstream strain-energy density routine is evaluated, but total-energy conservation is `UNKNOWN` because the driven boundaries do external work and this spike has no complete ledger.

The attempted `dx=1.5 mm` control is **not a like-for-like spatial-resolution comparison**. Although `uniform_box` was asked for the same nominal dimensions and the run held the `3 mm` horizon and physical duration fixed, the resulting reference point-center spans are `4.5×4.5×13.5 mm` versus `5×5×15 mm` at `dx=1 mm`; assigned point-volume sums are 540 versus 576 mm³. The missing 1 mm in the coarse z support confounds the damage difference. Its max damage `0.7143` and 472 broken pairs are recorded observations only; do not infer mesh convergence or attribute the difference to spacing alone.

The images [point-state contact sheet](spike/series_v4/bar_point_state_preview.png) and [50-step detail](spike/series_v4/bar_high_load_50_detail.png) plot a reference-y point slice with damage, intact-bond components, and z displacement. They show discrete solver state, not reconstructed crack faces or fracture roughness. No material microstructure, calibrated ceramic law, explicit R2/contact truth, or realistic vessel fragmentation is established by this bar. The old original upstream import failure remains a valid runtime-history note; the headless import and actual run supersede the prior “no solver output” status.

## Current next steps

Build the independent Python SDK/CLI and versioned Asset/Job/Result contract around the tested subprocess boundary, with path/hash/mesh/unit validation, point/step/thread/time limits, process timeout/cancellation, real exit status, and explicit unsupported/unknown capabilities. Use the native OSB material adapter for materials with supported general `nu`; retain BB as a compatibility/reference backend and reject its unsupported Poisson ratios rather than coercing them. Native multibody contact is the next small fixture after the initial package skeleton. Geometry-to-fragment surface reconstruction, physical calibration, high-density vessel runs, GPU execution, and A12 integration remain unimplemented or unverified.
