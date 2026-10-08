# RelicWeave V1.46 direction review

Read-only review of `C:/Users/xiemo/Desktop/ShardForge/RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx` as a direction document, not as implementation authority. No DOCX or source edits were made.

SHA-256: `15978A3956FA33E8048CC54C1DAD6878A7E19D9C71B84415DCAF8732F041A3B4`

The plan supports the current core: observed fragments lead to ranked candidates, traceable evidence, a verification state, and a recapture or stop reason. It distinguishes historical adjacency from current fit and currently visible evidence, and keeps hidden truth out of deployment inputs. The ownership boundary is also explicit: VesselForge produces assets; PG-Frag produces physical fracture results; A12 orchestrates observations, degradation, relations, training, and diagnostics. This is directionally consistent with the requested priority.

Key source locations and short verbatim excerpts:

- P99: “输出包括有序候选、来源可追溯的证据、待核验状态、补采或停止原因。”
- P100: “historical_R2用于邻片检索；current_fit_valid用于当前实体贴合；evidence_visible用于当前观测对应。” Also: “磨损不能事后删去历史正例提高召回。”
- P168–P171: `PairOutput` carries candidate id, ranking score/type, support/conflict regions, observability, model version, and evidence revision; P171 restricts model inputs to sensor observations, estimates, and operator input, with features and labels built separately.
- P353–P354 and P1306–P1311: VesselForge Asset Contract → PG-Frag Job/Result Contract → A12; A12 owns relation truth and observation/label adaptation, while the child projects own geometry and fracture kernels.
- T30 R1 and T31 R1–R7: `ORACLE_WORLD` is isolated for audit; deployment features exclude object identity, generator seed, hidden pose, and adjacency truth; degradation recipes and synthetic provenance are recorded.
- P1366: the first closed loop is deliberately modest (one thin-shell bowl, a validated backend, 8–12 fragments as an integration-fixture scale, three erosion/blur levels, and a shallow 2D baseline); passing it only proves contract integration, not high-fidelity physics or real-world transfer.
- P406: the plan stages the ~2,000-fragment pilot before precision/resource benchmarks and any decision to scale toward 100k/500k. Annex J T160 and T163, plus P2284, specify geometry/material/initial-state/environment inputs and parameterized material plugins; material cannot be only a string preset.

Current-proof snapshot comes from the task context and the requested background draft, not a rerun: one fixed 93-DOF cohesive toy case (27 source points; 81 BASE + 12 front; 16 queries; 16 QP3 assemblies; one KKT check); physical package count remains 0. The supplied estimates (PG-Frag 25–35%, VesselForge 30–40%, A12 30–40%) are subjective engineering progress, not physical completion or pass rates. VesselForge currently has three source families (bowl/beaker/jar), two saved default STEP instances (bowl/jar), and zero parameter-domain-qualified styles; its current smooth C4 jar-inner work is local 2D. The draft is treated only as background, not as a plan update or completion record.

Actionable alignment risks (four):

1. **Contract completion could be overstated.** The document requires a validator-backed VesselForge asset, PG-Frag job/result with solver lineage, and A12 release/permission audit (P2051). The present toy case and unqualified style do not establish that three-project closure. Keep its accepted scope mathematical/interface-only and keep physical package count at 0 until the manifests and validators exist. Treat the plan’s 8–12 fragment count only as an integration-fixture size; actual fragment count must emerge from physics, and a fixed fixture count must not be enforced as fracture control.
2. **Candidate scores could be read as truth or probability.** P168 calls an uncalibrated value `ranking_score`; P169 says an open-library result means no reliable candidate under the current input/library, not that no neighbor exists. Preserve multi-neighbor results and route low observability/unknown cases to verification, recapture, or STOP rather than forced Top-1 acceptance.
3. **Truth and visible evidence can leak across the model boundary.** P100, P171, T10, T30, and T31 require the three label meanings to stay separate and hidden truth to remain offline. Build features only from ObsPack plus the explicit quality whitelist; keep labels and parent/seed/pose metadata in the audit path.
4. **The future physics/material and scale scope exceeds current proof.** Annex J expects calibrated, parameterized material/defect/event inputs and backend-qualified physics; the background records `rho=1` as an uncalibrated toy. A12’s 31-axis registry and later 100k/500k scale are future phases. Keep the local qualification small and defer bulk generation until the small contract path is validated; do not describe the 93-DOF toy as realistic fracture.

No architectural conflict was found between the document and the requested observed-fragment retrieval core. The mismatch is maturity and breadth: V1.46 describes planned capabilities, while current evidence supports only a narrow toy/interface result and partial VesselForge geometry work.
