# Merge helper loss and current artifact record

Recorded 2026-10-07 (Asia/Shanghai), after read-only file-size and SHA-256 checks.

The original `tmp/v147_user_merge_20261007/merge_compact_preflight.py` was 4,026 bytes. It was intentionally deleted and rewritten during a compact-proof edit. Its exact original bytes and original SHA-256 were not preserved. The current file at that path is a replacement; it must not be treated as a byte-exact recovery or as the complete historical helper backup. No attempt was made to reconstruct the old file.

Current artifacts:

- `tmp/v147_user_merge_20261007/merge_compact_preflight.py` — 9,916 bytes; SHA-256 `f22b79928d2641becb893514c5bbbd49f730759371f498475946019d2804dddf`.
- `tmp/v147_user_merge_20261007/merge_compact_preflight.json` — 15,490 bytes; SHA-256 `c96fef9069fa70ce9a8719b3795b90c543e506cba1f89e9527e38d0a47af4121`.
- `tmp/v147_user_merge_20261007/merge_preflight.json` — 4,555,553 bytes; current SHA-256 `6dee7252624803dd432ed14f664ed68e5e8a0c2db52e3b9044478f6a7e3e65b8`. Its hash was recalculated without reading or printing the payload.
- `tmp/v147_user_merge_20261007/merge_candidate_20261007/build_merged_candidate.py` — 50,206 bytes; SHA-256 `abdcb140facae8b91db7bdfe16c31bc2f9eb91d47e36ff723bcd9811a02257ad`. This script was created but never executed.
- `tmp/v147_user_merge_20261007/merge_candidate_20261007/RelicWeave_V1.47_userdiff_merged_candidate.docx` — absent at the time of this check; no merged candidate was produced by this task.

The frozen root master and handover documents were not modified. These records describe only the helper loss and the files actually present; they do not claim a completed merge, render, or historical byte recovery. The current helper, its JSON output, the candidate-builder source, and this addendum should be included in the final current-code backup, with the missing original helper called out as an unrecovered historical file.
