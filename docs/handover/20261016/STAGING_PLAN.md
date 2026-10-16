# GitHub delivery staging plan — 2026-10-16

Development is paused. This handover covers delivery preparation for three independent Git repositories: `vesselforge`, `pgfrag`, and `relicweave-synlab`. Each repository keeps its own branch, history, staging area, and eventual GitHub push. The staging utility performs no development work, commit, push, or deletion.

The current [`STAGING_PLAN.json`](STAGING_PLAN.json) is a **pre-release snapshot** captured while the workspace-support archive was still being assembled. The root agent will refresh the inventory after that archive completes and review the new report immediately before staging. The JSON records every non-ignored untracked candidate with its size and selection reason, tracked changes, exclusions, source-suffix coverage, and any large tracked-file warnings. Its counts below are point-in-time values, not final staging totals.

## Staging rules

- The utility discovers new files with `git ls-files --others --exclude-standard -z` in each repository. It does not force-add ignored files. In particular, the ignored A12 source paths under workspace `tmp`/`data` and the workspace root remain in the separate A12 archive handled by the main agent.
- Every existing tracked change, including deletions and pre-staged tracked content, is included in `git add -u -- .` when `--stage` is explicitly supplied. New, non-ignored project code, configuration, docs, tests, and fixtures under 10 MiB are selected, including JSON configuration and small evidence files.
- New raw `.npy`, `.f64le`, and `.i32le` arrays and new `.dll`, `.exe`, `.whl`, `.pyd`, and `.so` dependency binaries are excluded. Runtime/dependency directories named `_temp_matplotlib`, `.mplconfig`, `.venv`, `__pycache__`, `node_modules`, `.pytest_cache`, `sdk`, `depot`, or `extract` are excluded wherever they occur in a path.
- Generated evidence over 10 MiB is excluded. Large JSON evidence is excluded by the same rule. Source text over 10 MiB remains selected and raises a blocking review error; the utility will not stage while that error remains. Tracked files over 95 MiB remain included and are listed as warnings.
- Path-based staging uses NUL-delimited `:(literal)` pathspecs. The utility never commits or pushes.

PGFrag's large local raw data remains on disk. At this snapshot, 178 new raw array files totaling 6,192,398,944 bytes are excluded from staging, while 13 small manifests under `data/` are selected by the ordinary rules. Runtime-directory exclusions are 2,136 PGFrag paths: 2,131 under `_temp_matplotlib` and five under `.mplconfig`; VesselForge and RelicWeave have none. These are staging decisions only; the utility does not remove or rewrite local data.

## Review and execution

From the `ShardForge` workspace root, run a read-only plan and save its full output:

```powershell
$pythonExe = ".\third_party\vesselforge-runtime\venv\Scripts\python.exe"
& $pythonExe .\relicweave-synlab\tools\handover\prepare_delivery_stage.py --workspace . --output-json .\relicweave-synlab\docs\handover\20261016\STAGING_PLAN.json | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Dry-plan failed with exit code $LASTEXITCODE" }
```

Review the JSON totals and every listed path/reason. Confirm the PGFrag raw arrays are excluded while their small manifests remain selected, and check all exclusions against the runtime/dependency and size rules. The report includes a zero uncovered-source count for the required `.py`, `.jl`, `.ps1`, `.sh`, `.toml`, `.yaml`, `.yml`, and `.json` suffixes; ignored files are outside this coverage by design and are never force-added. Stop if the report contains an error or any unmerged index entries.

After review, stage each repository without writing the report again:

```powershell
$pythonExe = ".\third_party\vesselforge-runtime\venv\Scripts\python.exe"
$stageReport = Join-Path $env:TEMP "ShardForge-stage-result.json"
& $pythonExe .\relicweave-synlab\tools\handover\prepare_delivery_stage.py --workspace . --stage --output-json $stageReport | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Staging plan was blocked or failed with exit code $LASTEXITCODE" }
"Full stage result: $stageReport"
```

The tool verifies that every planned tracked change and selected new file appears in its index. Review `git status` in all three repositories after staging. The root agent owns the later commit and push steps, and will handle each repository independently.

## Validation recorded for this snapshot

The read-only AST pass parsed 341 newly untracked Python files outside vendor and cache directories and found no parse failures. This is a syntax check only; it does not run tests, generators, solvers, or other project functionality. The JSON report records every runtime exclusion by path and reason. No tracked changed file over 95 MiB or source-text-over-10-MiB staging error was present at the recorded scan.
