VF-coupled backup independent postverify: FAIL_CORRECTED_POSTVERIFY

The stored read-only audit confirms 43/43 source, destination, and committed-blob rows match the plan (936,512 bytes). Plan SHA-256 d0564be84a6a51887db11a3aa2410fb9f3154935adc066e1c1d5487b8fb989e7; execution receipt SHA-256 32f8e57bda700e169c56720f0885f64499c543841e4f063f7fefbc88e3b0b35e.

The 86 index records were re-evaluated by their actual schema: each of 43 paths has one detailed passed record with index and cat-file rc=0, plus one compact passed summary record. All 43 commit checks and 34 copy receipts pass. PG 97d213c988323da39ddbaa9ebb2135b675190c93 has 15 exact paths; VF f75c1a464e5806268cf2d5e09fcd3b833c2c19df has 28. Both remotes match, and index/tracked worktrees are clean. Both captured pushes returned rc=0 and contain successful ref-update lines.

The initial checker FAIL JSON/MD are preserved byte-for-byte under C:\Users\xiemo\Desktop\ShardForge\tmp\backup_coordinator\next_vf_coupled_backup_independent_20261007_attempt01_preserved; hashes and checker cause are in the final JSON. Three earlier producer failures remain visible as no-mutation history. The full 43-file audit was not repeated. No repository mutations or tests were performed.
