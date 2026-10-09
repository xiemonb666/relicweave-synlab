# Layout render failure diagnosis

This is a read-only diagnosis. I did not rerun the renderer or modify the DOCX, manifest, prior render directories, or scratch folders.

The latest candidate DOCX is the table-width-patched file at SHA-256 `164b65c96aa7701a0ad6036fc25c6402dc8bf86c8581c35d258c42eb17fc5a2d` (793,425 bytes). The packaged renderer exited 1 in `final_render_layout`. Its log shows DOCX→PDF and ODT→PDF commands all returning 0 and printing a successful export line, but the renderer raised `Failed to produce PDF for rasterization (direct and ODT fallback)`. The output folder is empty after failure.

The failed packaged run used the correct bundled executable, `C:/Users/xiemo/Desktop/ShardForge/third_party/doc-render-runtime/LibreOffice-26.8.0/program/soffice.exe`, with a unique profile and conversion directory. The detailed log shows both under `render_scratch/layout/tmp/`. The renderer source checks for a nonempty expected PDF, then checks for any nonempty `*.pdf` fallback; the final exception means neither candidate was available at check time.

A later direct probe of the current DOCX also logged return code 0 and PDF export success, but its convert folder contains only a 150-byte LibreOffice lock file and a zero-byte `lu*.tmp`, with no PDF. Its profile contains a LibreOffice crash dump. `dump.ini` identifies LibreOffice 26.8.0.3 (build `bce0998afefdbc355585ca324285661a2170ba77`) but provides no exception or stack trace.

A separate control conversion of the prefinal snapshot DOCX (SHA-256 `e22e15c52aff6b4590a5fba298d13516c27b37b944d3b3e779d82124b1ffc1f2`, 793,349 bytes) did produce a valid 228-page Letter PDF with the same bundled LibreOffice executable. That control is only evidence that the renderer path/runtime works on the earlier file; it is not QA for the current table-patched DOCX. No LibreOffice processes remain active now. A `soffice.exe`/`soffice.bin` pair seen in an earlier snapshot was converting that older control DOCX into its own separate `layout_base_probe` folder and later exited.

The evidence points to a LibreOffice export-worker failure triggered by the current table-width-patched DOCX, while the launcher still reports success. This is probable rather than proven because the dump has no stack trace. The `Could not find platform independent libraries <prefix>` warning also appears in earlier successful runs, so it does not explain the failure.

A useful next diagnostic for the writer is to compare the two table-width patches' OOXML width/grid/cell-width values and, if necessary, isolate one patch at a time using disposable copies. Keep using the bundled absolute LibreOffice path, a fresh unique profile, and a fresh output directory. Do not accept a render until a nonempty PDF exists and its page count matches the resulting PNG set.

Exact paths, timestamps, hashes, residual files, and the remaining uncertainty are recorded in `layout_render_diagnosis.json`.
