# Independent Git backup audit

**Status:** FAIL (`FAIL_READ_ONLY_INDEPENDENT_BACKUP_AUDIT`)

Read-only comparison of 119 plan files. Plan SHA-256 `37c830792b64a1119f5a321dff1a5aef184131056e566a10bdcefe1e13bdbd8d`; receipt SHA-256 `2c5276efb0ac48c369497342b12ffdf53556c4ef7904763c5a4dbeef20aaeae7`. Source, destination worktree file, and raw `HEAD:path` bytes were compared for every item; total planned bytes 3,401,423.

- PG: `c13770d7c99ae58d3b57c34b434d2eb1a743d814`; 67 changed paths; remote match True; index/tracked clean True/True; 1558 untracked entries preserved.
- VF: `f34800e69b83277cff14629f6b1cd386872d8ef8`; 52 changed paths; remote match True; index/tracked clean True/True; 686 untracked entries preserved.
- Gate failures: 9. See JSON for per-file byte/SHA evidence, pathset checks, command return codes, and input pins.

The original PG push stdout bytes were not persisted. The receipt records rc=0 and a matching post-push remote check; this review independently verified the remote ref with read-only `git ls-remote`. No original stdout bytes are claimed as recovered. No tests or mutations were performed.
