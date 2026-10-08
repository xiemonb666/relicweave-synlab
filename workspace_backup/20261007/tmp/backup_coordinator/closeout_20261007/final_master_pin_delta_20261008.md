# Final master pin delta — 2026-10-08

Added one exact entry to FINAL_ROOT_DOCX_PINS for the approved V1.47 master. Removing that single line from the current builder reconstructs the previous builder byte-for-byte (SHA-256 741319d107112aa2e06a4639a673b0000c2e1422aba907a2360ad4962d599d34). The builder passes Python AST parsing.

- Expected master: RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx, 786,150 bytes, SHA-256 883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d. The promoted root file now matches.
- Builder: tmp/backup_coordinator/closeout_20261007/build_closeout_inventory_v2.py, 56118 bytes, SHA-256 2cfeaa37b3afc1a4896dda8f071dcf4cd6f5b9a74dbcbfd3e5b30e90d6658581.
- An earlier mistaken --help invocation started the builder scan because it has no help-only entry point. Both Python processes were terminated immediately; no inventory outputs were overwritten. The child output streams were buffered in the terminated parent and could not be recovered. This attempt is marked ABORTED_NOT_FINAL.
- No completed inventory, credential scan, export, copy, or Git operation was performed.
