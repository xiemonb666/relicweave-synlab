# SCIENCE v1 98-file backup independent postverification

Status: **PASS; earlier reviewer failures retained**.

The pinned SCIENCE v1 plan and execution receipt agree on 98 paths totaling 2,115,372 bytes across pgfrag (59), vesselforge (34), and relicweave-synlab (5). Current sources and destinations match the planned bytes and hashes. One raw cat-file batch per repository verified all 98 HEAD blobs and Git object IDs.

The audit keeps the 91 exact copies separate from 7 direct-stage items. It reconciles 91 copy receipts, 98 compact index summaries, 98 compact commit summaries, and detailed per-command captures. All three live HEAD/parent pairs, exact changed-path sets, remote refs, tracked/index cleanliness, and push return codes match.

Two reviewer issues are retained as byte-exact reports. Attempt 01 stopped before Git because its local VF hash pin omitted the final character. Attempt 02 completed the audit successfully, then its summary printer indexed the push return code at the wrong receipt level and incorrectly rewrote the status as FAIL. This report corrects that status from the saved audit only; it reran no Git commands or blob reads.

Plan SHA-256: f2729b22b197896906900107f2388fa3f80b1b02c6d8a856f97ebed56974da9e  
Execution receipt SHA-256: 72152fa9f79b378a02540785b3431bd4a0a12dd6cf6eb1cdc1762d64e6e79cb9  
Repository mutations: none. Tests: none.
