# V1.48 archive manifest

Archive preparation is complete in the working tree; Git staging, commit, and push await a separate Root COMMIT_GO.

Archive size: 66 files, 2099918 bytes (including both manifests).

The final 228-page PASS covers document visual review and file integrity only. It does not promote engineering or physical qualification. Current estimate ranges remain PG-Frag 25–35%, VesselForge 30–40%, A12 30–40%; MC01–MC07 are SPECIFIED / NOT_RUN, member recovery interfaces are not implemented, development is paused, and physical qualification packs remain 0.

The mapping below records each selected source path, destination, exact bytes, and SHA-256. The V1.47 inputs point to their already existing byte-identical workspace_backup copies and were not duplicated. One identical prefinal aggregate_visual_qa.py source path is mapped to the same archived helper instead of copied twice.

archive_manifest.json and this Markdown file are intentionally excluded from their own map. Their final hashes will be recorded in the separate delivery receipt after the archive commit.

| Source workspace path | Archive path | Bytes | SHA-256 | Action |
|---|---|---:|---|---|
| tmp/master_contract_update_20261009/authoring_receipt.json | docs/master/20261009/authoring_receipt.json | 214995 | ccbf046b82cd85fa53779c34e02c76f8fd869ccd7718958afd33db4394267b3d | copy_exact |
| tmp/master_contract_update_20261009/authoring_receipt.md | docs/master/20261009/authoring_receipt.md | 4596 | cc863aa36556109d5c673a69db0ae75543b0eb8aaf2893b722b7761f16bbc572 | copy_exact |
| tmp/master_contract_update_20261009/independent_source_review.json | docs/master/20261009/independent_source_review.json | 18233 | 2eb4b1d1bf734659d16183159f4e61a062919b3c02a2840f2b865420d2fce4d5 | copy_exact |
| tmp/master_contract_update_20261009/independent_source_review.md | docs/master/20261009/independent_source_review.md | 7739 | 20b3399fe722360567d5d417ad2b5f5814514b15e1e8b7a92d240a7a0a130a60 | copy_exact |
| tmp/master_contract_update_20261009/render_manifest.json | docs/master/20261009/render_manifest.json | 80691 | 28b8ee1b6b8b9bbb24016540438bf70c4e31f1070766a72b1b98f18c877ca598 | copy_exact |
| tmp/master_contract_update_20261009/patch_plan.json | docs/master/20261009/patch_plan.json | 76958 | 8c611ffcc443f4d4b6374c8ba0c48c92f2034571f651238c1a7fbc8546606e08 | copy_exact |
| tmp/master_contract_update_20261009/patch_plan.md | docs/master/20261009/patch_plan.md | 48099 | 022df9010ceaa51da02cfe9ef8dd35300289298db25fb06718dba7a3c48272ca | copy_exact |
| tmp/master_contract_update_20261009/build_master_docx.py | docs/master/20261009/build_master_docx.py | 62963 | 72fed3dca8bf8c986d2c4612e5f8ea3ca3ffbcf85cb86c186f3ff432d72e944e | copy_exact |
| tmp/master_contract_update_20261009/aggregate_visual_qa.py | docs/master/20261009/aggregate_visual_qa.py | 21615 | e0a50134071a47c3ec62526f9527ec8876e9c7b0fe396d21291b3a6366d72bd4 | copy_exact |
| tmp/master_contract_update_20261009/render_environment.json | docs/master/20261009/render_environment.json | 7130 | c27c59442329714b0f12febd67894fbfe64acbc7b06ba8f5bb71c905fb0e0e7c | copy_exact |
| tmp/master_contract_update_20261009/render_environment.md | docs/master/20261009/render_environment.md | 6542 | e5ca11ba21430ef20552199c7a8703e1b92c7626ca669cf7be6247fa05fbabab | copy_exact |
| tmp/master_contract_update_20261009/layout_delta.json | docs/master/20261009/layout_delta.json | 6094 | 0f5ec02dcc3c29c8e05b647f55e70ac480162ee63b663e8761e3f6d56cf90d31 | copy_exact |
| tmp/master_contract_update_20261009/layout_delta.md | docs/master/20261009/layout_delta.md | 1925 | dcdb8665642cd560ae6777d38f95c782913059e5e05789d9b4d44cff09b5c57d | copy_exact |
| tmp/master_contract_update_20261009/layout_render_diagnosis.json | docs/master/20261009/history/diagnostics/layout_render_diagnosis.json | 6169 | 7f0be0c184b371e50d92aaf8a24851ad05fd2059bdbc8cb2ee3357b26ab5089c | copy_exact |
| tmp/master_contract_update_20261009/layout_render_diagnosis.md | docs/master/20261009/history/diagnostics/layout_render_diagnosis.md | 2947 | 9cd1b7f1555d72f0c8924e36a80d572127601c7d98dc44d8d2c631582f298f58 | copy_exact |
| tmp/master_contract_update_20261009/layout_source_precheck.json | docs/master/20261009/history/diagnostics/layout_source_precheck.json | 9768 | 14a2d046cce1ec5a92005c1d63950e747464712b39271d034caaf3a2e195d34e | copy_exact |
| tmp/master_contract_update_20261009/layout_source_precheck.md | docs/master/20261009/history/diagnostics/layout_source_precheck.md | 2493 | 499d61f00833c9f8b99787d43e2af809acbc6b6deb4e321e81469f5cb97f477a | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_001_015.json | docs/master/20261009/qa/visual_001_015.json | 3318 | 50315b05482e38a9db625fa59f5f7d4de1b1671e56438eff13d3a5c8abdb76a5 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_001_015.md | docs/master/20261009/qa/visual_001_015.md | 969 | fd1035a9b630bbf5ee911f4df9918a53c9e9b87657e963738881eee01ccfd531 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_016_030.json | docs/master/20261009/qa/visual_016_030.json | 5308 | 8e148a0f2db0a4c00028e064ec60ee1d9221f466312576b11a6deade13701d01 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_016_030.md | docs/master/20261009/qa/visual_016_030.md | 3096 | 09058f11482f8cc71aa3fa80c4cd0f4a20259e70187efd1c1c2e8b498afaf9e8 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_031_045.json | docs/master/20261009/qa/visual_031_045.json | 5206 | 29dcfa661820212cbae72886074f5c1126fa932f33f3da9988ca4b5a894a67ce | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_031_045.md | docs/master/20261009/qa/visual_031_045.md | 757 | 6fe19f8242ecb1f5fae6c09ed6ab2dba5ec8f794cb7acb343bc62155f99bd3ad | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_046_060.json | docs/master/20261009/qa/visual_046_060.json | 3328 | e187d5d03509f623421bf23e1d89b7ad4c634b883bbd3b45f6f1bd67258e31f9 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_046_060.md | docs/master/20261009/qa/visual_046_060.md | 750 | c6afe48a48c0ab877b8d4b13399ddee4052af8fb47c03095711f4ec9df3329fa | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_061_075.json | docs/master/20261009/qa/visual_061_075.json | 2705 | cd51a9bd4061178c704d68a12545ab421ba2f9524ed543e61fa889a40076401f | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_061_075.md | docs/master/20261009/qa/visual_061_075.md | 1034 | 56d1bd8a8e89c06c608f3e75385825f621587794a378d3cb9f7fcfc5527fec07 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_076_090.json | docs/master/20261009/qa/visual_076_090.json | 3941 | 08d05555a7510979e7ec0a5eb017d453c9c1fbd15443c9904a39f0987cdfff2f | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_076_090.md | docs/master/20261009/qa/visual_076_090.md | 687 | ba31f885bb6a0560ae75afa12397eb885a40d165995158b2931a337cdd4904f0 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_091_105.json | docs/master/20261009/qa/visual_091_105.json | 3222 | 5a52858d5aab55007eb2099c7f965f3ad59734a2697670d37e5e2ef2979dbcdf | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_091_105.md | docs/master/20261009/qa/visual_091_105.md | 537 | bbdef24feff8a18af07c11f38059a0498d4e8ffae347fa21ca167dd50fee906f | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_106_120.json | docs/master/20261009/qa/visual_106_120.json | 2962 | 355c3dbec031f0627ae4a8a07796d8ac55b291eff37fb033c8852f4e0ce25743 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_106_120.md | docs/master/20261009/qa/visual_106_120.md | 990 | 695b30e56f198c34a16c0ba6c5db2c4c85cf518f71a922aeec84fd2ca876b904 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_121_135.json | docs/master/20261009/qa/visual_121_135.json | 5323 | a77499807217a0eb419470b1e0b12457059db7e0d556517f23a9ee1e7bfe202c | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_121_135.md | docs/master/20261009/qa/visual_121_135.md | 1998 | 106470a6a0d8444299df6ffd07a07ac91d73a92d287f5ae0bfa71ad07ba40e99 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_136_150.json | docs/master/20261009/qa/visual_136_150.json | 3546 | ff37a6a4ed9c3e27b31ce11c61b7a26147bd2e1929573f915ed5116c8fdcfc34 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_136_150.md | docs/master/20261009/qa/visual_136_150.md | 1026 | 9fca72ffbb288a29ec72472eafc0b027dc850f4ee5c9e29d73838668ebf83532 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_151_165.json | docs/master/20261009/qa/visual_151_165.json | 2557 | 2d80f9ce45afb6b460f761a2535112191f9ff667acb3f989d3d3e9ac21ccd93c | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_151_165.md | docs/master/20261009/qa/visual_151_165.md | 757 | 790df86301f805fe79f1815e7b4b0b63a238b7157e7d2891950804c1cbe133b3 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_166_180.json | docs/master/20261009/qa/visual_166_180.json | 3758 | 9dd193a24573e4e98ab4a8c6ab9a9c2db9571c8502f9d71f5530f80fec94e722 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_166_180.md | docs/master/20261009/qa/visual_166_180.md | 1135 | 314f09c0114516296f158183c91bd3c10b1de7e96c437b6f9a0a0c66d652fb20 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_181_195.json | docs/master/20261009/qa/visual_181_195.json | 5979 | ecf225d4a73bce487175c6c6263af8bedbd58790f35516c504c3d88ae3c253e7 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_181_195.md | docs/master/20261009/qa/visual_181_195.md | 2117 | 2f18f500547181d76e6295d30655fc143705cefb2daf668e0bc04876ec668605 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_196_210.json | docs/master/20261009/qa/visual_196_210.json | 3754 | 361386cad323f8e725d2ee3c630a8d1a65e05f2a4a8c8d22c10cbbd1752697b4 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_196_210.md | docs/master/20261009/qa/visual_196_210.md | 1024 | 22936fc5a39b4a137b2c1ac0e8a34f6a627bdb311aa279dcd51fbf67ad30ada8 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_211_225.json | docs/master/20261009/qa/visual_211_225.json | 4131 | 625a166861eb71a7df8d973a3e3e881a9746979cff63e23737299ac42dbdd77f | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_211_225.md | docs/master/20261009/qa/visual_211_225.md | 1055 | 81b5d29c87aab011027d2dc236bd6c2152f5e304c47e7482468fa76423609a1a | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_226_228.json | docs/master/20261009/qa/visual_226_228.json | 1682 | 1ad4794aebfeef5b8662987b9d592c37689ee36499325776d7322d263ff12f48 | copy_exact |
| tmp/master_contract_update_20261009/qa/visual_226_228.md | docs/master/20261009/qa/visual_226_228.md | 1228 | f25dd921e57fa777ad7af3e2f2738480c6b0e90f5c92992352e2a4e15c86e35c | copy_exact |
| tmp/master_contract_update_20261009/prefinal_layout_snapshot/build_master_docx.py | docs/master/20261009/history/source_snapshots/build_master_docx.py.prefinal | 41698 | f9e26bbb1bfba25d6ae2616b8e9a9cbdb310fed094e94553532dd792a00a336f | copy_exact |
| tmp/master_contract_update_20261009/render_scratch/layout_retry2/make_layout_manifest.py | docs/master/20261009/helpers/render_scratch/layout_retry2/make_layout_manifest.py | 4053 | 80fb9eaae9d111e92612aebac2ecf2062741c30b94edb5ba70678a05a54365a9 | copy_exact |
| tmp/master_contract_update_20261009/render_scratch/layout_variants/check_patch_xml.py | docs/master/20261009/helpers/render_scratch/layout_variants/check_patch_xml.py | 2218 | 80f9b70b3886009129797f625bcdd702ec4f8ff022cf60d3e7ad176978e8531b | copy_exact |
| tmp/master_contract_update_20261009/render_scratch/layout_variants/make_gridonly_variant.py | docs/master/20261009/helpers/render_scratch/layout_variants/make_gridonly_variant.py | 2908 | f54516faa69f3aef02722edf2f354199ccb1f275eb387ba32088cbe2e6019f2f | copy_exact |
| tmp/master_contract_update_20261009/render_scratch/layout_variants/make_variants.py | docs/master/20261009/helpers/render_scratch/layout_variants/make_variants.py | 3385 | 31c5e9f33fab0c32d62a02d780e5bf0239444730420d9b8a4dcf85ed364b621f | copy_exact |
| tmp/master_contract_update_20261009/final_render_layout/render_manifest.json | docs/master/20261009/render_run_manifest.json | 78384 | 08e06c8ee8e22fdc5ce4853e0dc48db08cc885c2d027eeecec09bed048d553b6 | copy_exact |
| tmp/master_contract_update_20261009/marker.log | docs/master/20261009/history/run_records/marker.log | 426 | a68f2b2759f3bc29f3cb1d3c1101915c92d95429301349cd494a58474cf519ea | copy_exact |
| tmp/master_contract_update_20261009/render.log | docs/master/20261009/history/run_records/render.log | 3407 | 0523920cd8ea91d3128d6acdf36d2fbad2e103bfcf24da0a0c33c863feddc94c | copy_exact |
| tmp/master_contract_update_20261009/artifact.md | docs/master/20261009/history/run_records/artifact.md | 1495 | e06746d0bdbfa0de0330fb09caee90ff41fb4d8cb609624e2a679c7d55ede42e | copy_exact |
| tmp/master_contract_update_20261009/code_snapshots/build_master_docx_actual_5a74044e.py | docs/master/20261009/history/source_snapshots/build_master_docx_actual_5a74044e.py | 61698 | 5a74044e56ea08b61a0ad27675d7abc4364c945ede42bd0741080bc6140310e2 | copy_exact |
| tmp/master_contract_update_20261009/render_scratch/layout_retry2/update_final_receipt.py | docs/master/20261009/helpers/render_scratch/layout_retry2/update_final_receipt.py | 13674 | da11265ad1bede529b9e45a47f2f4625d292ecfa6b146ba70c8d009ade33be41 | copy_exact |
| RelicWeave_V1.48_ContractAligned.docx | docs/master/20261009/RelicWeave_V1.48_ContractAligned.docx | 793363 | 23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455 | copy_exact |
| tmp/master_contract_update_20261009/final_visual_coverage.json | docs/master/20261009/final_visual_coverage.json | 352826 | 3211cdfc3525e3bd4ac22b548504805130945dba5efbd84caadbf234b3cebf55 | copy_exact |
| tmp/master_contract_update_20261009/final_visual_coverage.md | docs/master/20261009/final_visual_coverage.md | 3734 | 83f1e2eb02b38797ce9e816cc674fde4eef201ace83b6a2214df1483a93ccb68 | copy_exact |
| tmp/master_contract_update_20261009/publication_readme_draft.md | docs/master/20261009/README.md | 5143 | eb6ddd4e5ed92a630c981134d19965899fc9ad9e4eb71bcc49f18580fbc88f7c | generated_final_from_approved_draft_and_final_pins |
| RelicWeave_V1.47.docx | workspace_backup/20261007/RelicWeave_V1.47.docx | 779513 | 41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b | reuse_existing_exact_verified_archive_no_duplicate |
| RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx | workspace_backup/20261007/RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx | 786150 | 883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d | reuse_existing_exact_verified_archive_no_duplicate |

## Important source mapping notes

- The final render run manifest is sourced from tmp/master_contract_update_20261009/final_render_layout/render_manifest.json and archived as docs/master/20261009/render_run_manifest.json; it is distinct from the canonical render_manifest.json.
- marker.log, render.log, and artifact.md are historical records. The render log includes an attempt with exit code 1 and is not final-QA evidence.
- The exact build helper pinned by the authoring receipt is retained at history/source_snapshots/build_master_docx_actual_5a74044e.py. The active helper, prefinal helper, and layout helpers are separately mapped by their actual source hashes.
- Runtime installations, fonts, caches, PNGs, and PDFs are not included. Restore source inputs to their original workspace-relative paths before running helpers.

## Deduplicated identical source alias

This source path has the same bytes as the active aggregate_visual_qa.py and therefore points to that single archived target instead of creating a duplicate.

| Source workspace path | Reused archive path | Bytes | SHA-256 |
|---|---|---:|---|
| tmp/master_contract_update_20261009/prefinal_layout_snapshot/aggregate_visual_qa.py | docs/master/20261009/aggregate_visual_qa.py | 21615 | e0a50134071a47c3ec62526f9527ec8876e9c7b0fe396d21291b3a6366d72bd4 |
