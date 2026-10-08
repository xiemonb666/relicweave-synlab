# RelicWeave A12 接续与验收矩阵（2026-10-04）

A12 继续承担 RelicWeave synthetic / observation / degradation / retrieval diagnostics；主仓 A3/A4 集成待完成。本轮仅在本机做小规模验证，未运行 RTX5090 批量合成或训练。Astra 单次顾问已结束；Akantu 5.0.7.post1 extrinsic cohesive tiny capability spike 已完成但未晋级为物理结果；PD baseline 冻结；root 仅批准实验探索 native PD arbitrary rest-point input 与 per-step native-bond observer，该探索尚未运行，不做全面迁移。

## 当前窄结果

| 范围 | 当前结果 | 边界 |
|---|---|---|
| Appearance | 46 tests PASS；100k unique-score rank median 0.0813744 s（81.37 ms），O(N log N）。 | 四个小盒输出为 toy；不证明真实器型外观或 aging。最终哈希后重跑仍计 46 项。 |
| Deploy boundary v2 | 85 tests PASS（81 + 4），覆盖 schema/runtime。 | 旧 5 GB 训练包未迁移，不能据此声称其安全或可训练。 |
| Native contact | native submit exit 0：1-step preflight、240-step baseline、480-step half-dt、240-step no-contact control。最大 opposite-body momentum residual 3.4188e-24 kg·m/s；nominal cell-envelope overlap 0.5904 mm。 | 未校准 toy。未导出 contact-force/energy history，energy 与 integrated impulse 为 UNKNOWN；不等于接触物理验收。 |
| Akantu cohesive | Akantu 5.0.7.post1：zero 1707 steps（0 insertion、0 drift）；mode-I 1707 steps 与 half-dt 3414 steps。两组加载均有 8 个 native interfaces；两侧 rest area 各 4e-6 m²、mass 各 DOF 分量 4e-5 kg。 | 原始耗散分别为 −5.572968137645039e-5 J（coarse）与 −9.726359554870569e-6 J（half-dt）；均未达到目标 GcA=3.04e-5 J，两组相差 82.55%（按 coarse 绝对值归一），不通过。仅固定中央界面 API 基准，无自由裂纹或真实器物；full-debond、damage 与 native-energy 语义仍 UNKNOWN。runner 使用 `getEnergy('contact')`，reviewed native API 只确认 `cohesive contact` key；`contact` selector 的返回/未知-key fallback 未验证，故该通道和派生 energy ledger UNKNOWN。物理 contact 仍为 NOT_RUN；界面插入不等于断裂事件，也不构成物理 R2。 |
| C2 BREP | C2 profile、单次 native BREP 持久化、实际 y≥0 half-cut 的局部检查成功；一次 remesh 的 602 个样本最大偏差 0.0400846 mm。 | BREP candidate 未晋级；C2 无把手候选 STEP round-trip FAIL / NOT_PROMOTED。此状态不覆盖已把手原型的窄 STEP 路径。初次 coarse mesh 超门槛的 exit 2 保留；随后 refinement exit 0，且未再次写 BREP。 |
| Local ROI | h1：292 个 tet，292 个 centroid IN；292 个有限内部样本有 1 个 OUT，距原 CAD 0.000407289 mm，trial exit 2 / FAIL。h0.5：1506 tets、512 个有限样本全 IN，trial exit 0 / 有限几何 QA PASS。 | 两者均为局部静态几何/mesh QA，无 solver、裂纹或物理收敛结论。 |
| CAD clippedcells | 8 mm 单线程候选在 294 个盒中处理 58 个后因一个 component COM OUT 而 exit 1 / FAIL；49 个正体积 component、9 个 empty-material 结果。 | INCOMPLETE_COM_OUT；完整 partition volume accuracy 为 NOT_EVALUATED_INCOMPLETE_PARTITION。70.3% subtotal difference 不是 volume error。旧错误 plane-UV PNG 已标记 superseded；更正坐标轴图由 root 作为 representation 检查，未重跑 COMMON。 |
| QA / labels | 当时冻结 source hash 下 QA/label 30 PASS，damage legality + face provenance 16 PASS；最终 appearance rerun 46 PASS，仍只计 46 个不同测试。 | 9 个 broader routing/narrowband FAIL 保留。P02/P03 actual 输出均 not watertight、各有 6 boundary edges。QA v1 两模块定向运行 exit 1（22 PASS / 4 FAIL）；v2 exit 1（25 PASS / 3 FAIL），初报漏计的 10 项由 tmp/degradation_qa_fix/run_02/run02_counts_addendum.json 补正，3 项均因测试将 recipe.basis dict 传入 DegradationBasis 内部接口，未到 QA 断言；v3 准备后未运行，主审发现调用参数尚未修正。v4 run_03 两模块定向运行 exit 0，JUnit 28/28 distinct PASS、0 failures/errors/skips（stdout 28 dots，stderr 0）；六个源文件和 freeze 前后 SHA 完全一致。六源为 synlab/physical/api.py、synlab/physical/operators.py、synlab/degrade/axes.py、synlab/degrade/physical_narrowband.py、tests/a12/operators/test_postassembly_qa_20261003.py、tests/a12/degrade/test_physical_acceptance_20261004.py。freeze_manifest_v4.json SHA-256 be1aea30d145ff786fc301c57eb3f0893c049259720caee3755be1dc731c5fd5；run_03/junit.xml SHA-256 90a11212c34cc66f0af2e4dfcdd53ea9e224f4462a7be335f8136d07153da6bd，均位于 tmp/degradation_qa_fix/。本轮只验证 QA 状态传播、真值隔离及不将错误测量冒充壁厚；不清除 9 项 broader FAIL，也不证明 P03 真实退化成功。六源随本次备份保留。Measurement.valid 不代表 physical QA 有效。 |

Appearance pytest 命令为 .\\.venv\\Scripts\\python.exe -m pytest -q tests/a12/operators/test_appearance_continuity_20261003.py，exit 0；100k benchmark 命令为 .\\.venv\\Scripts\\python.exe tmp\\review_20261004\\implementation\\appearance_finish\\benchmark_rank_mask.py，exit 0。Deploy 两组 argv/exit 与对应代码 SHA 见证据副本 evidence/20261004/copies/deploy/checks.json。各 native case 的原始 argv、exit、source hashes 见 evidence/20261004/copies/native_contact/。

Akantu 执行源保真核对：canonical manifest SHA-256 前缀为 `21b563…`；current `run_contract` 保留的执行脚本为 29,542 B、SHA-256 前缀 `67dd1eb98…`，与冻结 manifest 的 `source_sha256` 和三份原始 status/receipt 哈希一致。此前 24,567 B 是较早未冻结代码尺寸，不是本轮执行源。此项只确认执行源码保留与哈希闭合，不代表全实验精确复现已验收；未声明另机重放或完整环境封装。后续每次 native run 都须在运行前将准确的 script、input、manifest 保存为不可覆盖快照并记录 bytes/SHA；post-run 诊断或标签修正另存，不改写原始脚本、manifest 或 receipt。只有 hash、没有对应 source bytes 不足以精确复现。

Akantu 固定界面试验、energy-key UNKNOWN 边界与源证据见 [Cohesive capability note](COHESIVE_CAPABILITY_20261004.md)；新增 case/status、runner、input、command 与 API/runtime 小副本列于 [evidence index](evidence/20261004/index.md)。

有效性核对的宽范围命令 .\\.venv\\Scripts\\python.exe -m pytest -q tests/a12/operators/test_narrowband.py tests/a12/degrade/test_axis_routing_audit.py exit 1；失败总数为 9，原始失败名见 evidence/20261004/copies/validity/pytest-routing-v2.log。最终源 SHA：synlab/physical/api.py 为 6f12a995ea689077e7ba8592d51b5c85be2044cb1cffc1a9256cb90949401661；synlab/degrade/physical_narrowband.py 为 88844f78af2366b2bdabdf2ab6b5dcc12df7579c91f5cc0a38873bd021d6a19d；synlab/degrade/api.py 为 b6a4962165868dd66fe38b8a088357bf10ea405d93a6dd09b7f45e0a442e4f8f。abs(volume) QA bug 在 physical.api 的 physical-result QA 路径；不是 h8/h6 signed-tet quality 问题，旧 h8/h6 signed tet orientation/quality 检查均为 positive。

## Cohesive 只读事件诊断（2026-10-04）

只读拓扑/能量诊断 exit 0、未运行 solver：96/96 tet signed volume 为正；输入拓扑 80 boundary / 152 internal，插入 8 个 coh6 后为 96 / 144，384 face slots 保持不变，局部 ordinal lineage 与 rest 坐标精确对应。名义 mode-I 实际为 mixed-mode；coarse 首次负耗散在 step 652 phase D，half-dt 在 1299，二者具体积分根因 UNKNOWN。原始只读报告、argv 与哈希见 [cohesive diagnostics note](COHESIVE_DIAGNOSTICS_20261004.md) 和 [证据索引](evidence/20261004/index.md)。

后续单次事件 probe 于 654-step cap 提前停止（1 attempt、2.932817 s、external exit 0，状态 `DIAGNOSTIC_EARLY_STOP_NOT_COMPLETE`）。捕获 phase 647–654；baseline 对比 1–654 共 654 行，energy/mass/reaction/count 最大差异均为 0，positions 因无 baseline frames 为 UNKNOWN。这是观测等价诊断，不是物理 PASS。8 个界面在 step 650 插入；step 651 phase D 耗散为 +1.726262e-7 J，step 652 phase D 首次为 −5.572968137645039e-5 J，而同一步 A/B/C 为正，且未发生新插入。32 组 opening/traction 可读：651D→652D 的 mean xy opening 为 0.156→350.186 nm、|z| 为 1.298→20.391 nm、max traction norm 为 143.978 MPa→0；damage/history 及 material update phase UNKNOWN。负值出现在首插入后两步，但时间相关性不证明因果；position、solver clock 与完整 case 均未验收。执行回执、derived 短结论和逐相位证据按类型列在 evidence index；大的 trace、NPZ、dense states 未复制。

暂停当前自由演化 extrinsic tiny case 的晋级和反复调参，保留其结果。下一门槛候选是受控原生本构 patch benchmark：pure opening、pure shear、mixed opening 与卸载/再加载，给定 separation history，核实原生 opening/traction/damage/history 的可读性与 GcA；它独立于自由动力学响应。intrinsic `cohesive_bilinear` 的 3D zero-step preflight_v3 实际读入 54 nodes / 96 tets / 8 coh6；8 个 cell-average opening、traction、damage 与 delta-max 初始字段可读。原 driver 的目录 inventory 步骤报错并 exit 2，独立递归字段核验通过；这只确认 preflight/字段可读性，不是非零求解或物理 PASS。201-point intrinsic controlled toy run02 外部 300 s timeout（WSL host exit −1、Python exit null、wrapper exit 124）；最终 closed-sample 为 168/201，partial opening/traction/damage/history 可读且部分数值检查符合，但 full 201-point run 与最终 GcA endpoint 均 incomplete，不能称 PASS。该 partial 不修复旧 extrinsic mixed-mode case；旧 case 的 negative-D 与 full-debond 根因仍 UNKNOWN。run03 使用相同物理参数和 201 points，`RAW_CLOSED_201`；单次运行 5.712 s，Python/WSL/PowerShell exit 均为 0，timeout marker 状态 UNKNOWN。原生→Windows 的 610/610 样本经 root 独立重算一致；窄数值审阅显示末端耗散能约 3.04e-5 J、与目标 GcA 相符，末端 traction=0、damage=1。root 已审 run03 analysis/PNG，18/18 gates PASS 仅覆盖 controlled all-DOF Mode-I toy 的数值本构与 representation；这不是整体 physics、自由裂纹、mesh-bias、R2 或 PRETRAIN 准入。run02 的 168/201 incomplete 和失败状态保持不变。优先评估内置 intrinsic `cohesive_bilinear`（有限初始弹性段 δ0），仅因 [Akantu 5.0.7-post1 模型文档](https://akantu.readthedocs.io/en/v5.0.7-post1/manual/models.html) 和 [v5.0.7 bilinear 源码](https://gitlab.com/akantu/akantu/-/raw/v5.0.7/src/model/solid_mechanics/solid_mechanics_model_cohesive/materials/constitutive_laws/material_cohesive_bilinear.cc) 可作候选依据；wheel 3D 能力仍须实际验证，也未采用为 production。新增界面柔度与 tet-face 方向影响都须实测。线性本构源码在近零开口处呈方向相关刚度；“bulk CFL 不保证 cohesive 积分收敛”是待检验推断，不是已证根因，也不把 tag 源等同于 post1 wheel。不得加全局 x/y 锚或仅靠减小 dt 宣称旧 case 已修复。壁厚 t/h 只覆盖几何分辨率；还需单独核对特定本构的 fracture/process-zone/regularization 尺度及初始界面刚度所需的时空分辨率，不能以 h0.5 有限几何 QA PASS 判定物理分辨率充分。

## SDF spacing 与 narrowband 诊断（2026-10-04）

`synlab/physical/sdf.py` 当前 SHA-256 `fd433876fa4df84d2316c93dbbe521e1094241829d5fccf93cedeeac02467b1d` 的明确 spacing 窄修复已由 root 接受：3 个既有定向 pytest PASS（输出仅为工具转录）；v3 boundary probe exit 0，且从原始快照做 AST 逐字段对照，自动路径 6/6 等价。它不清除 broader routing/narrowband 的 9 项 FAIL。更正后的 11 项 manifest 的全部 hash/bytes 已复核；narrowband 工作仍是诊断，不是修复。

诊断指出 P03 壁厚射线从外侧起算并采用首次命中，存在严重测量错误。P02/P03 的 Mesh32 与 Mesh64 四次冻结输入对照中，native 输出均含 7 个退化面且有 0 boundary edges；`clean` 移除退化面后均形成 21 条共线 boundary edges / 7 loops，结果仍 non-watertight。Mesh64 精度升级未消除该现象，单精度不是已证根因；下一步检查共线交界处的拓扑一致性。它与旧 88-face box fixture 的 6 条边是不同 fixture，不可合并或相互替代。归档的旧 `wall_interval_design` 是算法报告，不能代表后来单独实现的 `wall_intervals` helper：其 16 个定向测试仅覆盖局部 helper，尚未接入 P03。四个局部共线拓扑候选用例虽成功，正面积细长三角形仍存在，故未晋级；相关证据留在本地，未列入本次副本。精简候选包仍待主审放行再归档。

## 六道门槛

1. **Geometry：** C2 BREP 与有限局部几何结果只通过各自窄检查；C2 无把手候选 STEP round-trip 未晋级，clippedcells partition 不完整。
2. **NativeRun：** toy native contact 与 Akantu cohesive case 均完成非零 steps；cohesive 仅固定中央界面 API 基准，未构成校准器物的物理验收。
3. **NumericPhysical：** Akantu 两组原始耗散均未达到 GcA 目标且相差 82.55%；full-debond、damage、native-energy 语义仍 UNKNOWN。convergence、独立 remesh 方向/seed、PD δ/h、surface correction、自由裂纹能量和响应仍待验证。
4. **CalibratedMaterial：** E/Gc 等实测校准为 UNKNOWN / UNVALIDATED；当前 GcA 数值未通过上述比较。
5. **CrackSurface：** 当前固定界面插入不等同于断裂事件，尚无自由裂纹的 positive-area 配对裂面与 lineage。未经验证的 tet facets 不能作为 physical truth；cohesive/tet-facet 路径经本构与收敛验证后可列 candidate。单独校准并标注的形貌 surrogate 可用于形貌表示，但不能替代 fracture physics。
6. **RelicWeaveData：** 不得由 geometry PASS 推出数据准入；contact energy history、physical labels/receipt 的端到端有效性仍受上述 FAIL/PENDING 项限制。

当前没有物理级资格结论，也没有用 morphology surrogate 替代裂纹 physics。主仓 A3/A4 retrieval / evidence rejection / recapture / STOP 集成仍由主仓负责。

## 可复核材料

小证据副本、每个原件与副本的 SHA-256、准确 argv/exit、文件字节数见 [2026-10-04 evidence index](evidence/20261004/index.md) 和 [机器可读索引](evidence/20261004/index.json)。大型 mesh、5 GB package、runtime/cache、完整 raw GT 均不在新 evidence bundle 内。
