# Baseline QA report overwrite addendum

Date: 2026-10-07

While producing the final DOCX visual QA for pages 86–102, I wrote the updated report to the existing `master_086_102.md` and `master_086_102.json` filenames. The assigned write targets were the `final_master_086_102.*` filenames. This was a file ownership error.

Those two `master_086_102.*` files had contained the earlier QA report for the baseline DOCX with SHA-256 `7b15f365545d05538cddcd10801c90c9d10cfc741fa4a391bdc33706ea545fe0`. The exact earlier report files were overwritten. I did not preserve an exact copy before writing, and the scoped QA directory listing showed no separate exact-report backup. The original report cannot be restored exactly from the evidence retained here. This addendum records the loss and does not reconstruct or present the old report as recovered.

Per root's artifact check, the baseline DOCX (735,943 bytes, SHA-256 above) and its 203-page PNG render remain retained. This correction did not alter those artifacts.

The current 17-page final QA remains valid for the V1.47 DOCX with SHA-256 `9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436` and the 204-page `master_v147_render_v3` render. Exact byte copies of the current QA files are available as `final_master_086_102.md` and `final_master_086_102.json`; their hashes match the current `master_086_102.*` files.
