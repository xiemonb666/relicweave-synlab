# Independent delta review v2 — closeout backup sources

**Result: the prior unconditional receipt blocker is fixed for the normal push path.** The frozen delta is substantially improved. This remains a source-only review: I did not run the builder, executor, full inventory, tests, copies, or any Git mutation. The final generated inventory and source/destination pins still need their separate review.

## Frozen byte pins checked

| File | Bytes | SHA-256 |
|---|---:|---|
| `execute_closeout_backup.py` | 69,006 | `396c664f1386f6c33af8add423eb7b612678351803c40119a47e8771f47911a4` |
| `build_closeout_inventory_v2.py` | 55,967 | `741319d107112aa2e06a4639a673b0000c2e1422aba907a2360ad4962d599d34` |
| `README.md` | 4,566 | `c64dafaafbcc1b95752cde84c3f3be012f8feb90e0509333e4d1de65129f8d5b` |
| `independent_postverify_all_code_backup_20261007.py` | 51,017 | `7706e133102aaa4d47360e3e792d8ff21305267968a3d346119d7a836cef95ba` |

The original v1 reviewer report was left untouched. The root-provided previous-inventory evidence about zero explicit text/eol/filter risks, 86 pure-CRLF sources, and the one HANDOVER path remains a prior-candidate observation only; this reviewer did not run or validate the final inventory.

## Prior blocker and scope controls

The normal push path now writes the per-repository `push_exit_code` consumed by the frozen postverify helper, while retaining `push_returncode` (`execute_closeout_backup.py:1043–1044`). The helper accepts `push_exit_code` (`independent_postverify_all_code_backup_20261007.py:878–883`), so the earlier deterministic field-name mismatch is corrected.

The exact main-manifest SHA and root GO checks remain paired, and execution still requires an independently pinned supplementary manifest and its own matching GO SHA. The supplementary source/destination/role tuple set is exactly the three approved exports. The executor now preserves the supplementary source’s unresolved path through the symlink-component check before resolution. It restricts `--git` to the absolute bundled executable path, and the builder invokes that same absolute path and records its byte count and SHA in both the inventory and action manifest.

The updated builder fails on `check-attr` errors and validates a complete unique `(path, text/eol/filter)` result set. Its `check-ignore` handling accepts only Git’s expected `0` or `1` result and rejects returned paths outside the query. It explicitly includes only the two named portable JUnit XML files, each 4,877 bytes; their `closed_review_junit_or_xml_record` classification is accepted by the executor. The three selected NPZ inputs remain explicitly selected and below the executor’s 20 MiB limit. The 4,566-byte README pin is computed before scanning and checked against the scanned row and post-scan bytes without a later rewrite.

## Remaining conditional contract and provenance points

- **No-push resume path is not accepted by the frozen helper.** When the executor sees that the remote already equals the local commit and no successful push return code is available, it honestly writes `push_status: already_exact_remote_verified_without_push` and `push_exit_code: null` (`execute_closeout_backup.py:1012–1029`). The helper unconditionally requires a non-null zero return code before its remote-HEAD check (`:878–888`); it does not accept that explicit verified-no-push status. This is not the ordinary baseline-to-new-commit path, but an interrupted/reconciled execution can reach it. Either add a helper branch that accepts the explicit status only when its verified remote HEAD equals the committed HEAD, or define that such a recovery must remain failed closed.
- **Some resume and post-commit Git reads still parse stdout without checking return code.** The main `read_repo_state` and `stage_expected` parsing paths now use `command_bytes`, so the previous ordinary preflight/staging issue is fixed. The resume/post-commit paths still parse raw `.stdout` for `ls-tree`/`diff-tree` at `execute_closeout_backup.py:727, 731–733, 946, 948–950, 986–991`. Their later path and blob comparisons usually stop inconsistent results, but uniform return-code gating would make the failure behavior explicit, especially for resumed commits.
- **Binary hash is recorded but not compared with the manifest pin at execution time.** The builder records the bundled Git executable at `build_closeout_inventory_v2.py:593–596, 629–630, 664–665`, and the executor records its runtime hash in the receipt. However, `load_plan` does not compare that runtime hash/size to `manifest["git_executable"]`. The current bundled file is 46,464 B with SHA-256 `c53279919fdea03474bb23b465b3a82287157491f1bd69a5eb82dd9831582333`. The executor’s fixed path restriction is good, but it does not reject replacement bytes at that same path after the action manifest was frozen.

These are conditional recovery/provenance points rather than a repeat of the prior normal-push receipt blocker. Root should decide whether they need code changes before freezing the execution package.

## Decision boundary

The source delta fixes the reported push-return-code, primary read-state/staging command-status, supplementary symlink-path, `check-attr`, Git-path, and XML-coverage issues. I found no new unconditional failure in those fixes. Do not treat this review as approval of an inventory or backup run: the final inventory must still be generated and checked for current source pins, raw snapshot mappings, destination collisions, and per-repository pathsets before any execution GO.