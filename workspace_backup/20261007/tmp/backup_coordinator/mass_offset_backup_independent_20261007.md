# Mass-offset backup independent postverify

**Status:** `PASS_READ_ONLY_POSTVERIFY`

Verified 58 files / 959,548 planned bytes by raw source, destination, and committed blob comparison. Plan SHA-256 `ccc1d74153133251048b05482827f166cd36dc9834f314beda8ca7b9541ff007`; execution receipt SHA-256 `b9b203fdc6f4fbc8dcb0dc2399ff8526f233efddbfec8850baf724752d2ca011`.

- PG HEAD `6aabf6191eb232b4ad446334189d15e894bc3bff` (31 exact paths); remote matches; index/tracked clean True/True.
- VF HEAD `8acff8ac7db9cf212ed87ede3054a8311b69cc3a` (27 exact paths); remote matches; index/tracked clean True/True.
- Raw push captures returned rc=0 for both repositories; decoded receipt stderr contains each successful branch update, and independent `git ls-remote` matches each HEAD.
- PG receipt notes an assignment/logging failure after commit; commit rc=0 and expected ID/parent are verified. The commit was not repeated.

Untracked files were preserved. No tests or Git mutations were performed.
