# RMS calibration core v2 review pack — 2026-10-04

The first implementation and its 8-PASS stdout/stderr/argv/exit receipt remain unchanged in the parent review directory and in `baseline_v1/`. `v2_freeze.json` records exact SHA-256 copies of the v1 module, v1 test and v1 receipt before this edit. Original source snapshots and fixture remain in `baseline/` and `fixture_rms_calibration_20261004.json`.

V2 changes:

- `_measure` uses peak-normalized RMS and mean, avoiding `x ** 2` overflow for finite high-magnitude values.
- The scale candidate is constructed by peak-normalizing the raw field and multiplying by target, avoiding a zero field when `target / raw_rms` underflows. The scalar factor is reported only if it is a finite positive float; otherwise the result is `UNKNOWN_SCALE_UNREPRESENTABLE`, with `scale_factor=None` and the raw field/hash retained.
- A positive target is `EXACT` only if independently measured actual RMS is positive and `np.isclose(actual_rms, target, rtol=64 * float64_epsilon, atol=0.0)` succeeds. Failed/nonrepresentable results do not claim `EXACT`.
- Floating field hash payloads are explicitly canonicalized to little-endian `<f8` before hashing.
- Added a high dynamic range regression: `1e200` samples retain a finite measured RMS despite square overflow; a `1e100` field with the smallest positive float target produces a nonzero measured candidate but is marked UNKNOWN because the scalar scale underflows and cannot be truthfully reported.

No v2 tests were run, per root instruction. The regression is awaiting review and an approved verification run.

V2 source SHA-256: `B080E04A6AE00D02C6B231C5FAEF8174E2E2EAA75554A19261DE40264489DC26`.

V2 test SHA-256: `A1DEE137774AE0DEE322DCADF26BB106F09A5E8DA073939E5270A90500A28277`.

Unified diff: `v2.diff` (source and test only). Full v2 hash manifest: `v2_after_hashes.json`.
