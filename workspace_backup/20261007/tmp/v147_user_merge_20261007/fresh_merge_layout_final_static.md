# Final layout relocation static proof

- Source SHA-256: 835fc8f257d902e817a9e44bdf8c7e9d51da93da02205ee3901adffac2eb9173
- Candidate SHA-256: 883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d (786,150 bytes)
- All 22 non-document package parts are byte-identical; table count remains 194 and the target table has one fewer row.
- All 18,217 w:t values retain their exact sequence (SHA-256 cce38756a63b7866583c90071e7c9c725896768a5ec5bcee91c0d7fcb594d333).
- The Solver label and two explanation paragraphs were moved in order from the unique last row to immediately after its table. First two paragraphs have keepNext=true; all three have keepLines=true; the last has keepNext=false.
- Removing those three paragraphs and restoring the original row reconstructs the original document.xml exactly.
