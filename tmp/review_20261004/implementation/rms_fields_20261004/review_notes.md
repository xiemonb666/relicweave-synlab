# A12 G01 RMS calibration core — 2026-10-04

## Frozen source and contract evidence

- `baseline/ops_geometry.py` is an exact SHA-256 copy of the pre-edit source: `7909CAF7943E1D82B37D56C288792D22B292C52D85654925A694B5AC37AE8569`.
- `baseline/axes.py` is an exact SHA-256 copy of the pre-edit G01 dispatcher source: `1255550FE50741C81C2C57CF1EA5B4701496E8B1E933949279E4F54D41CF0E87`.
- `baseline/test_effects.py` records the existing G01 effect assertion. The requested new module and test were absent before the work.
- `fixture_rms_calibration_20261004.json` freezes a six-sample, 5 mm RMS displacement field, a boolean mask, 10 mm target, and expected one-pass scale 2. Its SHA-256 is `D7747163C82EB8DE54051163124ADA41AAFE3C8276E18E2586E7674AD25E1D64`.

## G01 finding: proven and unknown

`ops_geometry.py:175-189` defines the existing RMS as uncentered scalar RMS, `sqrt(mean(delta ** 2))`, in millimetres. G01 first computes `base = coarse * weight` and scales that base RMS to `target_rms_mm`. `normals_of` normalizes the direction vectors and `depth_error` applies the scalar displacement along each normal.

`ops_geometry.py:191-203` then adds signed outliers after that initial scale: each selected outlier receives a random magnitude between `2 * target` and `5 * target`, with the frozen declared probability of 0.02. There is no final scale after those additions. The same function measures `realized_rms_mm` on the complete final `delta`; `axes.py:1603-1605` reports it as `applied_rms_mm`, beside the requested target. This proves the source of the target/actual mismatch: the target scales the pre-outlier field, while the reported applied value covers the post-outlier field.

The amount of mismatch in any run is not known from source alone. It depends on the frozen point count, sampled field, and the existing outlier RNG draws; some small fields may draw no outliers. No evidence here establishes real-phone noise calibration. G01's current implementation does not select an ROI mask, so future caller mask semantics need to remain explicit.

## Implementation and later integration point

`rms_fields.py` adds a deterministic utility that accepts an already-frozen scalar displacement field in mm, a same-shape boolean mask, and a target. It performs at most one scalar rescale; reports a fresh post-scale RMS, signed mean, absolute peak, requested and finite denominators; preserves raw field/hash and mask/hash; copies mask exterior unchanged; and never samples randomness. Selected missing values are kept and cause UNKNOWN for positive targets. Empty masks, invalid targets and positive-target zero fields reject or report UNKNOWN. A zero target sets finite selected displacement to zero, the identity displacement.

A future G01 integration point is `ops_geometry.depth_error`, after its fixed outlier draws have been added to `delta` and before `perturbed = points + delta[:, None] * normals`. Once accepted, pass the chosen full G01 displacement mask explicitly to `calibrate_rms_field`, replace `delta` with its returned calibrated field, and propagate its metadata. This utility alone does not modify G01 behavior.

Metadata labels the result as conditioned exact RMS and states that deterministic conditioning does not preserve a strict independent-Gaussian model. It explicitly leaves real-phone calibration unclaimed.

## Verification

One focused command was run from the SynLab project root:

` .venv\\Scripts\\python.exe -m pytest tests/a12/degrade/test_rms_fields_20261004.py `

Exit code: 0; stdout is preserved in `pytest.stdout.txt` (`8 passed in 0.19s`); stderr is preserved in `pytest.stderr.txt` (empty). Exact argv, cwd, and exit code are in `pytest.run.json`. Pre-edit baseline hashes and current after hashes are in `baseline_freeze.json` and `after_hashes.json`.
