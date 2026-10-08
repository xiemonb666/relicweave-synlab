# Independent Git backup audit — attempt 02

**Status:** `PASS_CORRECTED_READ_ONLY_AUDIT_PRIOR_FAILURE_RETAINED`

Attempt 01 remains unchanged as `FAIL_READ_ONLY_INDEPENDENT_BACKUP_AUDIT` with nine checker-level failures; its full JSON SHA-256 is `e9baee8c6d2baa23e1d9c2f250b9afa7175df30166d263b15e65c4efe4a48221`. This attempt reuses its 118 successful source/destination/HEAD raw-byte comparisons bound to that pin and adds a raw `ls-tree`/`cat-file` check for the one long-path PNG.

Plan SHA-256 `37c830792b64a1119f5a321dff1a5aef184131056e566a10bdcefe1e13bdbd8d`; receipt SHA-256 `2c5276efb0ac48c369497342b12ffdf53556c4ef7904763c5a4dbeef20aaeae7`. Corrected accounting: 119 files / 3,401,423 bytes, 98 copies and 21 already-present staging entries (PG 51+16; VF 47+5). Current HEAD/parent, exact pathsets, remotes, and index/tracked cleanliness were checked read-only. Untracked files were counted and left untouched.

Original PG push stdout bytes were not persisted. The receipt records rc=0 and matching post-push remote state; this attempt independently checked the live refs with read-only `git ls-remote` without claiming recovery of original stdout. No tests or mutations were performed.
