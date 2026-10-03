# Execution attempts and corrections

This file records failed setup/reporting attempts separately from the final cases. The four final runs are listed in each case's `execution.toml`; only the three requested full simulations and the one-step preflight are used for the reported results.

| Attempt | Runtime and exit | What happened | Correction |
| --- | --- | --- | --- |
| Direct one-step preflight without `JULIA_DEPOT_PATH` | 1.769 s, exit 1 | Julia could not load `StaticArrays`, which is installed in the bundled depot. No simulation step ran. | Set `JULIA_DEPOT_PATH=third_party/pgfrag-runtime/depot`. |
| Direct one-step preflight with the depot set | 26.646 s, exit 1 | Native `submit` completed and the point CSV was written, then Julia stopped at top-level soft-scope assignment of `max_abs_external`. The attempt did not produce a summary and is not treated as a passing preflight. | Marked the loop assignment `global`; the subsequent preflight completed with exit 0. |
| First PowerShell runner launch | 0.617 s, exit 1 | Windows PowerShell did not expose `ProcessStartInfo.ArgumentList`; Julia was not launched. | Switched to `ProcessStartInfo.Arguments` with explicit quoting and `EnvironmentVariables`. |
| First independent Python analysis | 0.5 s, exit 1 | The simulation execution manifests wrote PowerShell's `False` capitalization, which is not valid TOML. The native runs themselves had already exited 0. | Normalized only the boolean token to valid TOML `false`, preserved the original `argv`, exit and runtime fields, and added current archived log paths. Hashes before/after are recorded in `path_migration.toml`. |

The runner initially placed outputs in the mistaken `ShardForge\\SynLab` alias directory. All four actual case directories were moved to `ShardForge\\relicweave-synlab\\tmp\\review_20261004\\implementation\\native_contact_minimal`; `execution.toml` retains the exact original run `argv` and paths. Each `summary.toml` records both the original runtime output path and current archive path. `path_migration.toml` records the move and hashes.

No prior contact wrapper was retried. The old `pgfrag/experiments/native_contact_minimal/results/preflight` directory is retained as superseded evidence; see its README for scope and provenance.
