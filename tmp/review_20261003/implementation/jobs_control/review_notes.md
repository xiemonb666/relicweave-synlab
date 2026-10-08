# A12 jobs control repair evidence

Date: 2026-10-03

## Scope and result

- `synlab/api/routers/jobs.py`: gated job creation and pause/resume/cancel/retry; GET-by-ID now uses `_job_or_404`; run status transitions for pause/resume/cancel check source status and optional revision and write the status, incremented revision, and `run.status` event in one `BEGIN IMMEDIATE` transaction. Retry refuses cancelled/unknown terminal runs; retry on a paused run may queue work but says it must be resumed before claim.
- `synlab/jobs/scheduler.py`: ready selection joins the run table and permits only `PENDING`, `ACCEPTED`, and `RUNNING`; claim repeats the run check under its existing `BEGIN IMMEDIATE` before changing job state, lease, attempt, fencing, or events. Missing and all other run statuses fail closed. Retry requeue/new-attempt writes also check run eligibility inside their scheduler write transaction, closing the cancel/retry race. `requeue` now accepts the message already passed by the API route.
- `synlab/jobs/state.py`: adds only `RETRYABLE → CANCELLED`, matching the cancel route's existing candidate handling; CANCELLED remains terminal.
- `tests/a12/jobs_control/test_run_claim_gates.py`: focused tests for run status, no-side-effect rejects, workspace/role isolation, cancellation ordering, stale revision refusal, safe-point completion, output-reference preservation, and retry.

The `runs` schema has no status enum/check. `create_run` initializes `PENDING`; `/jobs` changes it to `ACCEPTED`; controls use `PAUSED`, `RUNNING`, and `CANCELLED`. Other observed writers use `QA_PASSED`/`FAILED`; these are not claimable. `PENDING` remains claimable because existing foundation state-machine, dependency, and recovery probes create runs and claim from that initial state.

## Validation

Command:

```powershell
.venv\Scripts\python.exe tmp\review_20261002\data\run_pytest_no_tmpdir.py tests\a12\jobs_control\test_run_claim_gates.py tests\a12\foundation\test_core.py -k "run_claim_gates or scheduler_state_machine or dependency_gating or retry_keeps or recovery_probe or resume_run"
```

Result: **22 passed, 13 deselected**. The selected existing foundation checks cover scheduler fencing, dependency gating, retry seed preservation, recovery fencing, and resume reporting. The new tests use only small temporary stores and do not start workers or synthesis batches.

The complete existing API jobs/budget test file was also run, including its small `freeze_spec` worker fixture: **12 passed, 1 skipped**. The capability-gate case skips when every probed capability is importable.

Exact logs: [`targeted_jobs_control_20261003.log`](targeted_jobs_control_20261003.log), SHA-256 `41d72c6d604bb2b0334fdf95afe6e1bc06373548b8fa4931500c2734828aa59f`; and [`existing_jobs_api_20261003.log`](existing_jobs_api_20261003.log), SHA-256 `8014c5d11a344e5a7f2e84538a0f69887fb69db264f11e7965840a639a295d47`. `py_compile` passed for the two production files, state file, and new test file; `git diff --check` reported no whitespace errors.

## Boundaries still open

- `PENDING` is a legitimate scheduler initial state. `/jobs` currently creates the run and its DAG jobs through separate transactions before setting `ACCEPTED`; a worker could claim a job while the DAG is still being inserted. This known enqueue atomicity window is not addressed here.
- `recover_expired` may return an in-flight job from a now-cancelled run to `PENDING`, but ready/claim gating prevents it from being started again. Recovery-state normalization itself is unchanged.
- Status event revision is now the run revision written by these three controls. Other callers of `AssetStore.set_run_status` still emit a fixed event revision of `1`; they remain outside this repair. The current SSE path orders/reconnects by monotonic `event_seq` and does not sort mixed job/run events by `revision`.
