# PG-Frag v1 toy endpoint fixture

This is a byte-preserving, bounded fixture for the PG-Frag v1 source reader and
its A12 QA tests. `output/result.json` names the nine source output artifacts;
`job.json` is the matching job source used for explicit SHA-256 and job-ID checks.

The data describes a `uniform_box_bar_fixture` endpoint serialization sample.
Its intact-bond graph component labels are diagnostics and do not qualify as
physical fragments. The fixture contains no qualified crack surfaces, no
fracture event history, and no historical surface adjacency or R2 qualification.
It is not a physical-fragment, R2, or full-chain PASS fixture.

All nine result outputs, `result.json`, and the matching parent `job.json` are
copied byte for byte. Tests read these explicit fixture paths and never depend
on a local review directory.
