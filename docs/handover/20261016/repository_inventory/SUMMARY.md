# Repository Inventory Summary

Generated: 2026-10-16T10:28:13+00:00
Workspace: `C:\Users\xiemo\Desktop\ShardForge`

This is a read-only inventory for `vesselforge`, `pgfrag`, and `relicweave-synlab`. The script used `git ls-files -z`, `git ls-files --modified -z`, and `git ls-files --others --exclude-standard -z`; it also walked all of `pgfrag/data/` and `pgfrag/experiments/bowl_independent_audit_20261015/_temp_matplotlib/` so ignored histories and runtime cache files are represented. It does not stage, commit, push, or edit repository files.

It hashed 7,279 of 16,608 inventoried files using SHA-256 with at most 2 workers and 8 MiB read blocks. The classification threshold is 10 MiB. All tracked files marked modified/staged and visible untracked files were hashed; every file in PG `data/` and every excluded file over the threshold was hashed. The named `_temp_matplotlib/` tree was inventoried as a runtime cache. Unchanged tracked files outside those rules show `sha256: null` with `hash_status: unchanged_tracked_not_hashed`.

## Repository state

| Repository | Branch | HEAD | Tracked | Modified tracked | Staged | Visible untracked | Extra walked | Inventoried | Candidate | Local only | Review required | Total bytes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| vesselforge | `backup/forge-work-20261003` | `73116cf40bd8620e3142667dccd644cc16c47aac` | 822 | 1 | 0 | 1,311 | 0 | 2,133 | 1,551 | 89 | 493 | 154,770,945 |
| pgfrag | `backup/forge-work-20261003` | `21aa69dd131031944a3139b482abf6a0069da023` | 2,616 | 1 | 0 | 4,368 | 1,257 | 8,241 | 2,834 | 5,238 | 169 | 7,104,196,251 |
| relicweave-synlab | `backup/forge-work-20261003` | `9f1b4d5e53745d16d92ed2635b541aca859bf7d9` | 5,905 | 7 | 0 | 329 | 0 | 6,234 | 5,920 | 153 | 161 | 274,463,063 |

Across all repositories: 10,305 candidate files (319,392,096 bytes), 5,480 local-only files (6,918,896,780 bytes), and 823 review-required files (295,141,383 bytes).

## Classification guidance

- Candidate files include project code, configuration, documentation, and small textual evidence. Project-owned frozen inputs under `data/` with suffixes `.py`, `.jl`, `.toml`, `.dat`, or `.msh` are explicitly preserved as candidates; third-party `vendor/` and runtime/cache trees remain local-only.
- Raw `.npy` and `.f64le` histories, NPZ archives over 10 MiB, and generated JSON/CSV/NPZ over 10 MiB under data/experiment/result paths are recommended local-only. Hashes are streamed, so the large PG datasets do not need to be loaded into memory.
- `.dll`, `.exe`, and `.whl` are classified as dependency release artifacts. Runtime caches, virtual environments, `__pycache__`, `site-packages`, vendor trees, build output, and `_temp_matplotlib` are excluded from project code candidates.
- Photo, image, and geometry resources plus small NPZ fixtures are marked `review_required`; root must decide whether each is needed and verify any license/provenance before upload.
- Paths under repository roots were inventoried from tracked and visible untracked Git paths, with the two PG-specific full walks listed above. Other ignored paths outside those walks are not enumerated.
- This report is only a recommendation manifest. It does not stage files; final staging remains with the root agent.

## Suggested local-only patterns

Review/apply only after checking project-specific inputs: `**/__pycache__/`, `**/.venv/`, `**/venv/`, `**/site-packages/`, `**/node_modules/`, `**/vendor/`, `**/third_party/`, `**/_temp_matplotlib/`, `**/.pytest_cache/`, `**/.mypy_cache/`, `**/.ruff_cache/`, `**/.mplconfig/`, `**/build/`, `**/dist/`, `**/*.npy`, `**/*.f64le`, generated `**/*.npz`, generated `**/*.json` over 10 MiB, generated `**/*.csv` over 10 MiB, `**/*.dll`, `**/*.exe`, and `**/*.whl`. Keep the data-directory `.py`/`.jl`/`.toml`/`.dat`/`.msh` frozen inputs visible for root review.

## Credential scan

The source/config scan reports only file path, detector rule, and line number. It never writes matched content to either manifest or the console. It checked 7,021 of 8,467 eligible files and read 134,217,729 bytes; it skipped 28 files over 2 MiB, 1,418 files after the 128 MiB total scan budget, 7 lines over 64 KiB, 5 binary files, and 0 files with read errors. Runtime/vendor paths are excluded.

| Path | Rule | Line |
|---|---|---:|
| `vesselforge/docs/reviews/20261007/global_wall_distance_certificate/capture_once.py` | `credential_assignment_quoted` | 12 |
| `vesselforge/docs/reviews/20261007/monotone_normal_strip/decision/capture_supervisor.py` | `credential_assignment_quoted` | 15 |
| `vesselforge/docs/reviews/20261007/monotone_normal_strip/decision/capture_supervisor_02_after_scope_fix.py` | `credential_assignment_quoted` | 15 |
| `vesselforge/docs/reviews/20261007/monotone_normal_strip_decision/capture_supervisor.py` | `credential_assignment_quoted` | 15 |
| `vesselforge/docs/reviews/20261007/monotone_normal_strip_decision/capture_supervisor_02_after_scope_fix.py` | `credential_assignment_quoted` | 15 |
| `vesselforge/tmp/review_20261007/global_wall_distance_certificate_20261007/capture_once.py` | `credential_assignment_quoted` | 12 |
| `vesselforge/tmp/review_20261007/monotone_normal_strip_decision/capture_supervisor.py` | `credential_assignment_quoted` | 15 |
| `vesselforge/tmp/review_20261007/monotone_normal_strip_decision/capture_supervisor_02_after_scope_fix.py` | `credential_assignment_quoted` | 15 |

## Hash errors

No hashing errors.
