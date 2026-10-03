# RelicWeave A12 接续与验收矩阵（2026-10-04）

A12 继续承担 RelicWeave synthetic / observation / degradation / retrieval diagnostics；主仓 A3/A4 集成待完成。本轮仅在本机做小规模验证，未运行 RTX5090 批量合成或训练。Astra 单次顾问已结束；后续仅保留 Akantu extrinsic cohesive tiny capability spike，PD baseline 冻结，不做全面迁移。

## 当前窄结果

| 范围 | 当前结果 | 边界 |
|---|---|---|
| Appearance | 46 tests PASS；100k unique-score rank median 0.0813744 s（81.37 ms），O(N log N）。 | 四个小盒输出为 toy；不证明真实器型外观或 aging。最终哈希后重跑仍计 46 项。 |
| Deploy boundary v2 | 85 tests PASS（81 + 4），覆盖 schema/runtime。 | 旧 5 GB 训练包未迁移，不能据此声称其安全或可训练。 |
| Native contact | native submit exit 0：1-step preflight、240-step baseline、480-step half-dt、240-step no-contact control。最大 opposite-body momentum residual 3.4188e-24 kg·m/s；nominal cell-envelope overlap 0.5904 mm。 | 未校准 toy。未导出 contact-force/energy history，energy 与 integrated impulse 为 UNKNOWN；不等于接触物理验收。 |
| C2 BREP | C2 profile、单次 native BREP 持久化、实际 y≥0 half-cut 的局部检查成功；一次 remesh 的 602 个样本最大偏差 0.0400846 mm。 | BREP candidate 未晋级；production STEP 仍 FAIL / NOT_PROMOTED。初次 coarse mesh 超门槛的 exit 2 保留；随后 refinement exit 0，且未再次写 BREP。 |
| Local ROI | h1：292 个 tet，292 个 centroid IN；292 个有限内部样本有 1 个 OUT，距原 CAD 0.000407289 mm，trial exit 2 / FAIL。h0.5：1506 tets、512 个有限样本全 IN，trial exit 0 / 有限几何 QA PASS。 | 两者均为局部静态几何/mesh QA，无 solver、裂纹或物理收敛结论。 |
| CAD clippedcells | 8 mm 单线程候选在 294 个盒中处理 58 个后因一个 component COM OUT 而 exit 1 / FAIL；49 个正体积 component、9 个 empty-material 结果。 | INCOMPLETE_COM_OUT；完整 partition volume accuracy 为 NOT_EVALUATED_INCOMPLETE_PARTITION。70.3% subtotal difference 不是 volume error。旧错误 plane-UV PNG 已标记 superseded；更正坐标轴图由 root 作为 representation 检查，未重跑 COMMON。 |
| QA / labels | 最终 source hash 下 QA/label 30 PASS，damage legality + face provenance 16 PASS；最终 appearance rerun 46 PASS，仍只计 46 个不同测试。 | 9 个 broader routing/narrowband FAIL 保留。P02/P03 actual 输出均 not watertight、各有 6 boundary edges。Measurement.valid 不代表 physical QA 有效。 |

Appearance pytest 命令为 .\\.venv\\Scripts\\python.exe -m pytest -q tests/a12/operators/test_appearance_continuity_20261003.py，exit 0；100k benchmark 命令为 .\\.venv\\Scripts\\python.exe tmp\\review_20261004\\implementation\\appearance_finish\\benchmark_rank_mask.py，exit 0。Deploy 两组 argv/exit 与对应代码 SHA 见证据副本 evidence/20261004/copies/deploy/checks.json。各 native case 的原始 argv、exit、source hashes 见 evidence/20261004/copies/native_contact/。

有效性核对的宽范围命令 .\\.venv\\Scripts\\python.exe -m pytest -q tests/a12/operators/test_narrowband.py tests/a12/degrade/test_axis_routing_audit.py exit 1；失败总数为 9，原始失败名见 evidence/20261004/copies/validity/pytest-routing-v2.log。最终源 SHA：synlab/physical/api.py 为 6f12a995ea689077e7ba8592d51b5c85be2044cb1cffc1a9256cb90949401661；synlab/degrade/physical_narrowband.py 为 88844f78af2366b2bdabdf2ab6b5dcc12df7579c91f5cc0a38873bd021d6a19d；synlab/degrade/api.py 为 b6a4962165868dd66fe38b8a088357bf10ea405d93a6dd09b7f45e0a442e4f8f。abs(volume) QA bug 在 physical.api 的 physical-result QA 路径；不是 h8/h6 signed-tet quality 问题，旧 h8/h6 signed tet orientation/quality 检查均为 positive。

## 六道门槛

1. **Geometry：** C2 BREP 与有限局部几何结果只通过各自窄检查；production STEP 未晋级，clippedcells partition 不完整。
2. **NativeRun：** toy native contact 确实完成非零 steps；未构成校准器物的物理验收。
3. **NumericPhysical：** convergence、独立 remesh 方向/seed、PD δ/h、surface correction、裂纹能量和响应仍待验证。
4. **CalibratedMaterial：** E/Gc 等实测校准为 UNKNOWN / UNVALIDATED。
5. **CrackSurface：** 需要事件产生的 positive-area 配对裂面与 lineage。未经验证的 tet facets 不能作为 physical truth；cohesive/tet-facet 路径经本构与收敛验证后可列 candidate。单独校准并标注的形貌 surrogate 可用于形貌表示，但不能替代 fracture physics。
6. **RelicWeaveData：** 不得由 geometry PASS 推出数据准入；contact energy history、physical labels/receipt 的端到端有效性仍受上述 FAIL/PENDING 项限制。

当前没有物理级资格结论，也没有用 morphology surrogate 替代裂纹 physics。主仓 A3/A4 retrieval / evidence rejection / recapture / STOP 集成仍由主仓负责。

## 可复核材料

小证据副本、每个原件与副本的 SHA-256、准确 argv/exit、文件字节数见 [2026-10-04 evidence index](evidence/20261004/index.md) 和 [机器可读索引](evidence/20261004/index.json)。大型 mesh、5 GB package、runtime/cache、完整 raw GT 均不在新 evidence bundle 内。
