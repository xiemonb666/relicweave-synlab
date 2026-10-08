# Realism reference access log — 2026-10-03

This folder records what the independent realism QA actually inspected. No external image, dataset, or PDF was copied into the workspace. The only writes for this review are this log and the SynLab-repository-relative `docs/a12/REALISM_ACCEPTANCE_20261003.md`.

## Local artifacts inspected

| Artifact | Size | SHA-256 | Inspection note |
|---|---:|---|---|
| `tmp/review_20261003/implementation/vf/artifacts/preview_brep_semantics1_final/exterior_four_bands_brep_semantics1_final.png` | 973,541 B | `4D2A3E75EA8B8401425611CBC79ADF7422E87CA4CF34B10032AE03E2051ACBA9` | One hollow handled vessel and four painted bands are visible. This is a preview image, not a material or mechanics measurement. |
| `tmp/review_20261003/implementation/vf/artifacts/preview_brep_semantics1_final/axial_half_section.png` | 934,977 B | `7FE26ED47E4F1CB84D4F7B9E55396473B18C7B57751106AAA1933D6A5827B29C` | One section illustrates the cavity and visible wall shape; it does not prove minimum thickness over the full fused object. |
| `tmp/review_20261003/implementation/pg/visuals/osb_fracture_point_state.png` | 113,820 B | `20D85BF466AD4E27BF2BA301CC2C991985424949FB3381894EA399C0297E4205` | The figure itself labels calibration `UNVALIDATED_PROTOTYPE` and geometry surface reconstruction `absent`; it visualizes solver point/bond state only. |

Read-only project evidence included `docs/a12/degrade_realism.md`, `relicweave-synlab/docs/a12/INFRA_IMPLEMENTATION_20261003.md`, the VF preview, and `pg/visuals/osb_fracture_point_state_audit.json`. The implementation ledger states that the initial profile has C0 corners, abrupt handle-root transitions, no geometric ornament relief, and unvalidated style/mechanics. The wear document classifies its unmeasured material/exposure inputs as candidates. These are owner-reported implementation facts, not new measurements made by this review.

## Deliverable identity

The acceptance note is stored at SynLab-relative `docs/a12/REALISM_ACCEPTANCE_20261003.md` (9,301 bytes, SHA-256 `8F10A313CD83BF0E0D20139274DD2566D0C62B4CEE0197BE15B22EB76AB1AB54`). It was moved from the workspace-level `docs/a12` into the SynLab repository after review so it is included in that repository's backup boundary. Its material-parameter wording now preserves explicit candidate input values and distinguishes those values from the `UNKNOWN` / `UNVALIDATED` status of calibration for the actual ceramic.

## Official references checked

- NIST's fourth-edition record identifies George Quinn, NIST SP 960-16e4, publication date 2026-04-10, DOI `10.6028/NIST.SP.960-16e4`, and describes the guide as a free public service. The linked official PDF resolves to `https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=960651`; its front matter says April 2026 and 683 pages. The web PDF reader exposed the cover and initial front matter (three parsed pages), including the cover caption about recognizable Wallner lines on weathered Roman glass. No full 683-page download was attempted.
- The official third-edition record says its fundamentals are unchanged from earlier editions. The third-edition PDF is 64,164,484 bytes according to the web reader and the official second-edition PDF is 25,576,164 bytes. Neither full file was downloaded. Relevant official indexed excerpts were checked in the second-edition PDF at page 5-12 and Appendix D page D-2. Those excerpts support mechanism-sensitive markings and the warning that polycrystalline ceramic microstructure may obscure a mirror/mist boundary; they do not provide a universal roughness cutoff.
- NIST's official AFM paper record was checked for its abstract. It reports a silica-glass mirror-region case, not ceramic calibration; the local acceptance note uses it only to reject a universal roughness threshold.
- The Smithsonian surfaces page was checked as official explanatory text; no Smithsonian image was copied. The Met object pages were checked for object metadata and image status. Object 07.232.32 is marked Public Domain; the page states that Open Access images are available for unrestricted commercial and noncommercial use. No Met image was copied into this workspace.
