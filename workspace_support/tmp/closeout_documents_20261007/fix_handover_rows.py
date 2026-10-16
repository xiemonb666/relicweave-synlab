from pathlib import Path
p=Path('docs/handover/20261007/HANDOVER.md')
s=p.read_text(encoding='utf-8-sig')
lines=s.splitlines()
out=[]
for line in lines:
    if line.startswith('| 来源目录 | pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/'):
        line='| 来源目录 | `pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/`；历史 attempt receipt `capture_once01/capture_receipt.json` SHA-256 `779b503781d711a6b06257cfbc72fd00938af34c315307bb2de948e6908240f3`。 |'
    elif line.startswith('| 解析器型 |'):
        line='| 解析器型 | `vesselforge/src/vesselforge/profile_catalog.py` SHA-256 `e9d4bc1458a107208e537449d6526f1c0077d6d3afc6953a6200d86512f9c26f`，定义 bowl、beaker、jar 三个解析参数族；catalog-native pilot 只有 bowl_default 与 jar_default 两个实例，beaker 无实例，无非默认域 sweep。 |'
    elif line.startswith('| 变更范围 | 相对保留的 321 行原始快照'):
        line='| 变更范围 | 相对快照 `pgfrag/tmp/review_20261007/mixed93_mechanics_objectivity_20261007/mechanics_objectivity_adapter.precloseout.snapshot.py`（321 行，SHA-256 `f9b35bd271e1ac9e86bedb813435f3a0b9b045bc84f4b1e1e56c1f10244c346f`），窄修正只增加 FrameState.mls_origin_world_m 字段及从构造函数传入计算所得 MLS origin。根任务核对 20/20 当前 pins。 |'
    out.append(line)
    if line.startswith('| 当前证据入口 | `relicweave-synlab/docs/a12/reviews/20261007/REVIEW.md`'):
        out.append('| 进度与 readiness | `pgfrag/docs/progress/20261006_physics_core_review_addendum.md`（3,962 B，SHA-256 `379c3f9079cb25aa97797ccd40a76bb2bd5c303b50ee3992b409f4c932ffd8f3`）及其 pins `pgfrag/tmp/review_20261006/20261006_physics_core_review_addendum.pins.json`（62,911 B，SHA-256 `389656a11ce48037ce1be66e86d310a235ae65b2fff5c5b63c685e8fdda80f33`）；跨项目 readiness `tmp/review_20261007/core_readiness_inventory/READINESS.md`（21,701 B，SHA-256 `7f38cc3a9c330d646a07a108321ea528aeaa3755072943f718a9baa5b49bd939`）及 `readiness.json`（72,333 B，SHA-256 `c8459dbac69a4e5cab3c5b3dcea752805a8b605d2176512c5bdba8eee4dfd9f1`）。根任务已签收这些状态文件；它们没有新增源代码或数值运行。 |')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
