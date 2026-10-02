# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: ui-real-backend.spec.ts >> U07 批量面板：真实计数、失败错误码与覆盖矩阵
- Location: e2e\ui-real-backend.spec.ts:241:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('region', { name: '批量合成（真实计数 · 覆盖矩阵 · 一键续跑）' }).getByRole('button', { name: '一键续跑下一批' })
Expected: visible
Timeout: 30000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('region', { name: '批量合成（真实计数 · 覆盖矩阵 · 一键续跑）' }).getByRole('button', { name: '一键续跑下一批' }) with timeout 30000ms
  - waiting for getByRole('region', { name: '批量合成（真实计数 · 覆盖矩阵 · 一键续跑）' }).getByRole('button', { name: '一键续跑下一批' })

```

```yaml
- link "跳到主内容":
  - /url: "#main"
- banner:
  - strong: RelicWeave
  - text: A12 合成实验室 工作区 default 角色 researcher（可读真值） 数据口径 SYNTHETIC 当前 run 未选择（在任务页选择） 任务 未终止 run 1 失败/隔离/可重试 0 total=1 GPU OK API /api/synlab 已连接 v1.0.0 · store_a1e1b5224830f47c
- navigation "合成实验室页面":
  - list:
    - listitem:
      - link "U01 实验室概览":
        - /url: /synlab
    - listitem:
      - link "U14 合成向导":
        - /url: /synlab/synthesis
    - listitem:
      - link "U02 母体编辑":
        - /url: /synlab/mothers/new
    - listitem:
      - link "U03 花纹编辑":
        - /url: /synlab/patterns
    - listitem:
      - link "U04 断裂预览":
        - /url: /synlab/fracture
    - listitem:
      - link "U05 退化对比":
        - /url: /synlab/degradation
    - listitem:
      - link "U06 相机与采集档":
        - /url: /synlab/camera-profiles
    - listitem:
      - link "U07 批量生成与任务":
        - /url: /synlab/jobs
    - listitem:
      - link "U08 数据发布":
        - /url: /synlab/releases
    - listitem:
      - link "U09 预训练":
        - /url: /synlab/training
    - listitem:
      - link "U10 诊断面板":
        - /url: /synlab/diagnostics
    - listitem:
      - link "U11 主动观察":
        - /url: /synlab/episodes
    - listitem:
      - link "U12 质量与故障":
        - /url: /synlab/quality
    - listitem:
      - link "U13 合成数据展示":
        - /url: /synlab/showcase
  - paragraph:
    - text: 所有页面数据来自
    - code: /api/synlab
    - text: 真实路由；无后端时显示具体错误码， 不使用任何 mock 数据。
- main:
  - heading "批量生成与任务 U07 · 计划 20.8" [level=1]
  - paragraph: 先 validate + budget 再提交 run；监控 planned/attempted/accepted/quarantined、DAG 阶段、可量化阶段进度、失败按类型筛选；暂停/恢复/停止新任务/重试可恢复错误；取消不删已提交数据。
  - text: 幂等键防双击 P50/P95 与实测资源：后端未产出
  - region "创建任务（冻结 spec）":
    - heading "创建任务（冻结 spec）" [level=2]
    - paragraph: POST /jobs —— HTTP 202 只表示已受理，不代表计算通过；stage 与能力需求来自 GET /stages
    - text: stage
    - combobox "任务阶段":
      - option "审计（覆盖/闭包/权限/门）（audit）"
      - option "退化轴应用（degrade）"
      - option "诊断评测（diagnostics）"
      - option "派生展示 GLB（L0/L1/L2）（display_lod）"
      - option "主动观察 episode（episode）"
      - option "导出（manifest / obs pack）（export）"
      - option "断裂事件（fracture）"
      - option "冻结输入合同（freeze_spec）"
      - option "批量生成（完整 DAG）（generate）" [selected]
      - option "材料剖面（material）"
      - option "母体生成（mother）"
      - option "观测渲染/重建（observe）"
      - option "纹样生成与几何化（pattern）"
      - option "物理损伤（physical）"
      - option "关系池构建（pool）"
      - option "预训练（training）"
      - option "三层真值（truth）"
    - text: 能力需求：
    - code: mothers, materials, patterns, fracture, degrade, observe
    - text: · 实现方 worker
    - paragraph:
      - code: freeze_spec
      - text: /
      - code: audit
      - text: /
      - code: export
      - text: 由本 API 包自身实现，无能力依赖，一定会被受理；其余阶段只要有一个能力缺失，后端就返回
      - code: 503 DEPENDENCY_CAPABILITY_MISSING
      - text: 且不创建半成品 run。
    - text: 幂等键：jobs:14a1169f-afca-4060-afad-59638a402319
    - button "换一个幂等键（模拟第二次点击）"
    - region "参数草稿":
      - heading "参数草稿" [level=2]
      - paragraph:
        - code: POST /specs/validate
        - text: ·
        - code: POST /budgets
        - text: ·
        - code: POST /previews
        - text: ·
        - code: POST /jobs
      - button "校验 spec"
      - button "估算资源"
      - button "请求真实预览" [disabled]
      - text: 不可用：本页不提供预览阶段
      - button "提交 generate 任务"
      - paragraph: 滑块/输入只改本地草稿；松手后需要点击上面的按钮才会发出真实请求。未运行前一律标“未计算”， 旧预览在新草稿下会提示“参数已变化”。
      - group "生成规模与配额（dataset / sampling）":
        - text: 生成规模与配额（dataset / sampling） 母体数 （个）
        - spinbutton "母体数 （个）": "1"
        - text: 目标片数 （片）
        - spinbutton "目标片数 （片）": "8"
        - text: 配额/组合策略
        - combobox "配额/组合策略":
          - option "（不设置 / 使用后端默认）"
          - option "registry_balanced" [selected]
          - option "uniform"
          - option "explicit"
        - text: 采样方法
        - combobox "采样方法":
          - option "（不设置 / 使用后端默认）"
          - option "latin_hypercube" [selected]
          - option "sobol"
          - option "quota_uniform"
        - text: 器物组合
        - textbox "器物组合": V01
        - text: 多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验 材料组合
        - textbox "材料组合": M01
        - text: 多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验 纹样组合
        - textbox "纹样组合": PAT01
        - text: 多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验 层组合
        - textbox "层组合": L01
        - text: 多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验 split · train
        - spinbutton "split · train": "0.8"
        - text: split · dev（留出）
        - spinbutton "split · dev（留出）": "0.1"
        - text: split · confirm（留出）
        - spinbutton "split · confirm（留出）": "0.1"
        - text: 生成前切分（防同谱系泄漏）
        - checkbox "生成前切分（防同谱系泄漏） 是" [checked]
        - text: 是
      - group "断裂 / 观察 / 退化":
        - text: 断裂 / 观察 / 退化 事件后端（断裂）
        - textbox "事件后端（断裂）": rough_shared_cut
        - text: 目标片数区间 （片）
        - spinbutton "目标片数区间 第 1 项": "8"
        - spinbutton "目标片数区间 第 2 项": "20"
        - text: 观察输入档
        - combobox "观察输入档":
          - option "（不设置 / 使用后端默认）"
          - option "PHONE_RGB"
          - option "SENSOR_PROXY" [selected]
          - option "SENSOR_UPPER_BOUND"
        - text: 每片视角数
        - spinbutton "每片视角数": "12"
        - text: 相机档引用（camera_profile_id）
        - textbox "相机档引用（camera_profile_id）"
        - text: 退化配方引用（recipe_id 列表）
        - textbox "退化配方引用（recipe_id 列表）"
        - text: 多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验 物理损伤配方
        - textbox "物理损伤配方"
        - text: 多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验
      - group "资源与 checkpoint 策略":
        - text: 资源与 checkpoint 策略 CPU worker
        - spinbutton "CPU worker": "2"
        - text: CPU RSS 预算 （GB）
        - spinbutton "CPU RSS 预算 （GB）": "30"
        - text: GPU 显存预算 （GB）
        - spinbutton "GPU 显存预算 （GB）": "26"
        - text: 预留临时峰值
        - checkbox "预留临时峰值 是" [checked]
        - text: 是 分片目标 （MB）
        - spinbutton "分片目标 （MB）": "512"
        - text: QA 协议引用
        - textbox "QA 协议引用"
        - text: QA fail-closed
        - checkbox "QA fail-closed 是" [checked]
        - text: 是
      - group "全局":
        - text: 全局 schema
        - combobox "schema":
          - option "（不设置 / 使用后端默认）"
          - option "synlab.v3" [selected]
        - text: 数据口径
        - combobox "数据口径":
          - option "（不设置 / 使用后端默认）"
          - option "SYNTHETIC" [selected]
          - option "REAL"
        - text: 发布 profile
        - textbox "发布 profile": SANDBOX_CORE
        - text: 实验用途
        - combobox "实验用途":
          - option "（不设置 / 使用后端默认）"
          - option "SANDBOX"
          - option "DEVELOPMENT" [selected]
          - option "CONFIRMATION"
        - text: master seed
        - spinbutton "master seed": "20261001"
      - group: 高级：直接编辑 spec JSON（字段名与后端 extra="forbid" 模型一致）
      - paragraph:
        - text: 表单只产生草稿；合法性以
        - code: POST /specs/validate
        - text: 与
        - code: POST /jobs
        - text: 的回答为准（本页原样展示后端 errors）。共 31 个字段。
      - complementary:
        - heading "校验结果" [level=3]
        - paragraph: 尚未校验。点击“校验 spec”。
        - heading "幂等键" [level=3]
        - paragraph:
          - code: generate:80c433f5-4b97-4eb6-a790-7275416781f9
          - button "复制幂等键": 复制
        - button "重新生成幂等键"
        - paragraph: 相同幂等键 + 相同 payload 返回原任务（idempotent_replay=true）；同键不同 payload 后端返回 409。
    - region "资源预算":
      - heading "资源预算" [level=2]
      - status: 尚未请求预算估算 点击上方“估算资源”调用真实的 POST /budgets；后端不可行时会返回 409 BUDGET_EXCEEDED。
  - region "批量合成（真实计数 · 覆盖矩阵 · 一键续跑）":
    - heading "批量合成（真实计数 · 覆盖矩阵 · 一键续跑）" [level=2]
    - paragraph: "GET /synthesis/inventory + POST /synthesis/batch-plan + POST /jobs + GET /runs/{id}/events"
    - button "刷新计数"
    - text: planned
    - strong: "1"
    - text: attempted
    - strong: "0"
    - text: accepted
    - strong: "0"
    - text: failed
    - strong: "0"
    - text: pending
    - strong: "1"
    - term: 磁盘实测（资产 payload）
    - definition: 229.2 MiB（626 个文件）
    - term: 本批磁盘增量
    - definition: 未记录基线
    - term: 资产数 / run 数 / 事件数
    - definition: 276 / 1 / 286
    - term: jobs 状态分布
    - definition: PENDING=1
    - term: 计数口径
    - definition: planned/attempted/accepted/failed 全部由 jobs 表的权威 state 计数（attempted = 已离开 PENDING/BLOCKED/CANCELLED 的 job；accepted = OUTPUT_READY/QA_PASS/COMMITTED）；disk_bytes 是资产 payload 文件的 stat() 实测字节和，不是估算
    - paragraph: jobs 表里没有带错误的行 —— 未运行过的阶段不会产生失败码。
  - region "覆盖矩阵（器型 × 材料 × 花纹 × 层）":
    - heading "覆盖矩阵（器型 × 材料 × 花纹 × 层）" [level=2]
    - paragraph: covered/required 来自 reports/coverage_aggregate.json（跨 run 聚合）；桶内计数来自 assets 表
    - text: 已覆盖桶 0 / 8 scanned_assets 276 basis vessel_id+material_id+family_id source null
    - table "覆盖维度（真实 aggregate）（required/covered 与缺失 ID 均来自后端响应）":
      - caption: 覆盖维度（真实 aggregate）（required/covered 与缺失 ID 均来自后端响应）
      - rowgroup:
        - row "维度 声明字段 已覆盖 / 需要 完成 缺失 ID 证据资产":
          - columnheader "维度"
          - columnheader "声明字段"
          - columnheader "已覆盖 / 需要"
          - columnheader "完成"
          - columnheader "缺失 ID"
          - columnheader "证据资产"
      - rowgroup:
        - row "24 器物 UNKNOWN coverage.vessels 0 / 24 不完整 V01, V02, V03, V04, V05, V06, V07, V08, V09, V10, V11, V12, V13, V14, V15, V16, V17, V18, V19, V20, V21, V22, V23, V24 无":
          - rowheader "24 器物 UNKNOWN"
          - cell "coverage.vessels"
          - cell "0 / 24"
          - cell "不完整"
          - cell "V01, V02, V03, V04, V05, V06, V07, V08, V09, V10, V11, V12, V13, V14, V15, V16, V17, V18, V19, V20, V21, V22, V23, V24"
          - cell "无"
        - row "12 材料 UNKNOWN coverage.materials 0 / 12 不完整 M01, M02, M03, M04, M05, M06, M07, M08, M09, M10, M11, M12 无":
          - rowheader "12 材料 UNKNOWN"
          - cell "coverage.materials"
          - cell "0 / 12"
          - cell "不完整"
          - cell "M01, M02, M03, M04, M05, M06, M07, M08, M09, M10, M11, M12"
          - cell "无"
        - row "16 纹样 UNKNOWN coverage.patterns 0 / 16 不完整 PAT01, PAT02, PAT03, PAT04, PAT05, PAT06, PAT07, PAT08, PAT09, PAT10, PAT11, PAT12, PAT13, PAT14, PAT15, PAT16 无":
          - rowheader "16 纹样 UNKNOWN"
          - cell "coverage.patterns"
          - cell "0 / 16"
          - cell "不完整"
          - cell "PAT01, PAT02, PAT03, PAT04, PAT05, PAT06, PAT07, PAT08, PAT09, PAT10, PAT11, PAT12, PAT13, PAT14, PAT15, PAT16"
          - cell "无"
        - row "4 层组合 UNKNOWN coverage.layer_combos 0 / 4 不完整 L01, L02, L03, L04 无":
          - rowheader "4 层组合 UNKNOWN"
          - cell "coverage.layer_combos"
          - cell "0 / 4"
          - cell "不完整"
          - cell "L01, L02, L03, L04"
          - cell "无"
        - row "4 断裂后端 UNKNOWN coverage.fracture_backends 0 / 4 不完整 fracture_modes, plane_shared_cut, rough_shared_cut, secondary_fracture, warp_voronoi_cut, warped_partition 无":
          - rowheader "4 断裂后端 UNKNOWN"
          - cell "coverage.fracture_backends"
          - cell "0 / 4"
          - cell "不完整"
          - cell "fracture_modes, plane_shared_cut, rough_shared_cut, secondary_fracture, warp_voronoi_cut, warped_partition"
          - cell "无"
        - row "31 退化轴 UNKNOWN coverage.axes 0 / 31 不完整 G01, G02, G03, G04, G05, G06, G07, G08, I01, I02, I03, I04, I05, I06, I07, I08, I09, I10, P01, P02, P03, P04, P05, P06, P07, P08, X01, X02, X03, X04, X05 无":
          - rowheader "31 退化轴 UNKNOWN"
          - cell "coverage.axes"
          - cell "0 / 31"
          - cell "不完整"
          - cell "G01, G02, G03, G04, G05, G06, G07, G08, I01, I02, I03, I04, I05, I06, I07, I08, I09, I10, P01, P02, P03, P04, P05, P06, P07, P08, X01, X02, X03, X04, X05"
          - cell "无"
    - group: 原始 coverage JSON（后端原样返回）
    - paragraph:
      - text: 覆盖来源：
      - code: reports 里没有 coverage 文件
      - text: ；覆盖值只来自 reports/coverage_aggregate.json（跨 run 聚合）或 reports/coverage.json；两者都不存在时这里如实为空，不会用 registry 的目标数冒充已覆盖数
    - table "已实现的组合桶（vessel_id+material_id+family_id）—— 来自 assets 表，逐桶给出真实资产数":
      - caption: 已实现的组合桶（vessel_id+material_id+family_id）—— 来自 assets 表，逐桶给出真实资产数
      - rowgroup:
        - row "组合 assets fragments lineages 覆盖 run 数":
          - columnheader "组合"
          - columnheader "assets"
          - columnheader "fragments"
          - columnheader "lineages"
          - columnheader "覆盖"
          - columnheader "run 数"
      - rowgroup:
        - row "V01 / M03 / layer=未记录 2 0 1 未计入覆盖 0":
          - rowheader "V01 / M03 / layer=未记录"
          - cell "2"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V02 / M03 / layer=未记录 2 0 1 未计入覆盖 0":
          - rowheader "V02 / M03 / layer=未记录"
          - cell "2"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V03 / M03 / layer=未记录 2 0 1 未计入覆盖 0":
          - rowheader "V03 / M03 / layer=未记录"
          - cell "2"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V04 / M03 / layer=未记录 2 0 1 未计入覆盖 0":
          - rowheader "V04 / M03 / layer=未记录"
          - cell "2"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V06 / M03 / layer=未记录 2 0 1 未计入覆盖 0":
          - rowheader "V06 / M03 / layer=未记录"
          - cell "2"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V07 / M03 / layer=未记录 2 0 1 未计入覆盖 0":
          - rowheader "V07 / M03 / layer=未记录"
          - cell "2"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V13 / M03 / layer=未记录 1 0 1 未计入覆盖 0":
          - rowheader "V13 / M03 / layer=未记录"
          - cell "1"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
        - row "V18 / M03 / layer=未记录 1 0 1 未计入覆盖 0":
          - rowheader "V18 / M03 / layer=未记录"
          - cell "1"
          - cell "0"
          - cell "1"
          - cell "未计入覆盖"
          - cell "0"
    - paragraph: 每个组合的 assets/fragments/lineages 都来自资产表；regime 覆盖标志取 coverage aggregate 的 vessels/materials 集合。layer_combo_id 在已提交资产的 meta 里不存在（后端 coverage sources 已说明它只出现在逐谱系 coverage rows），因此这里如实为 null，而不是从 registry 猜一个
    - group: coverage 原始 JSON（后端原样）
  - region "下一批与续跑（--resume 语义）":
    - heading "下一批与续跑（--resume 语义）" [level=2]
    - paragraph: POST /synthesis/batch-plan：resume=true 忽略客户端 cursor，按 assets 表推进到第一个未实现组合
    - text: 批大小
    - spinbutton "批大小": "4"
    - button "规划（cursor 0）"
    - button "一键续跑下一批"
    - status: 还没有批次计划 点上面的按钮会按真实覆盖情况算出下一批组合；没有规划前这里不显示任何组合。
  - region "run 选择与实时监控":
    - heading "run 选择与实时监控" [level=2]
    - paragraph: "GET /jobs?run_id= · GET /runs/{run_id}/events"
    - button "刷新"
    - group "选择 run":
      - text: 共 1 个 run（由 GET /jobs 的真实 job 行按 run_id 归并）
      - button "清除选择" [disabled]
      - list:
        - listitem:
          - button "run_60b5675732dc86c56ebe 待运行 未终止 1 个 job · degrade · 最近更新 12.2 h 前 待运行×1 spec_hash=sha256:cfcd9d21c9d9221a5c5fec0de…"
    - status: 未选择 run 选择上面的一个 run 后，这里显示真实 SSE 事件时间线与进度。
  - region "任务列表与筛选":
    - heading "任务列表与筛选" [level=2]
    - paragraph: GET /jobs（keyset 分页；state 可多选，stage 单选）
    - group "状态筛选":
      - text: 状态筛选
      - checkbox "待运行"
      - text: 待运行
      - checkbox "运行中"
      - text: 运行中
      - checkbox "产出就绪"
      - text: 产出就绪
      - checkbox "QA 通过"
      - text: QA 通过
      - checkbox "已提交"
      - text: 已提交
      - checkbox "可重试失败"
      - text: 可重试失败
      - checkbox "已隔离"
      - text: 已隔离
      - checkbox "失败"
      - text: 失败
      - checkbox "已取消"
      - text: 已取消
      - checkbox "被依赖阻塞"
      - text: 被依赖阻塞
      - button "清除状态筛选" [disabled]
    - text: stage
    - combobox "stage":
      - option "（全部）" [selected]
      - option "审计（覆盖/闭包/权限/门）（audit）"
      - option "退化轴应用（degrade）"
      - option "诊断评测（diagnostics）"
      - option "派生展示 GLB（L0/L1/L2）（display_lod）"
      - option "主动观察 episode（episode）"
      - option "导出（manifest / obs pack）（export）"
      - option "断裂事件（fracture）"
      - option "冻结输入合同（freeze_spec）"
      - option "批量生成（完整 DAG）（generate）"
      - option "材料剖面（material）"
      - option "母体生成（mother）"
      - option "观测渲染/重建（observe）"
      - option "纹样生成与几何化（pattern）"
      - option "物理损伤（physical）"
      - option "关系池构建（pool）"
      - option "预训练（training）"
      - option "三层真值（truth）"
    - text: 待运行
    - strong: "1"
    - text: total=1
    - table "任务行（state 为权威状态；progress 缺失表示 handler 尚未计数）":
      - caption: 任务行（state 为权威状态；progress 缺失表示 handler 尚未计数）
      - rowgroup:
        - row "选择 job_id stage state attempt progress error 更新 操作":
          - columnheader "选择"
          - columnheader "job_id"
          - columnheader "stage"
          - columnheader "state"
          - columnheader "attempt"
          - columnheader "progress"
          - columnheader "error"
          - columnheader "更新"
          - columnheader "操作"
      - rowgroup:
        - row "选择任务 job_09a0fddcd4c0d8713ed3 job_09a0fddcd4c0d871… degrade 待运行 0 未计数 — 12.2 h 前 溯源":
          - cell "选择任务 job_09a0fddcd4c0d8713ed3":
            - radio "选择任务 job_09a0fddcd4c0d8713ed3" [checked]
          - cell "job_09a0fddcd4c0d871…"
          - cell "degrade"
          - cell "待运行"
          - cell "0"
          - cell "未计数"
          - cell "—"
          - cell "12.2 h 前"
          - cell "溯源":
            - button "溯源"
    - button "回到第一页" [disabled]
    - button "下一页" [disabled]
    - text: limit=100 · scanned=1 · cursor=首页
  - region "任务详情与控制":
    - heading "任务详情与控制" [level=2]
    - paragraph: "GET /jobs/{id} · POST /jobs/{id}/pause|resume|cancel|retry"
    - term: job_id
    - definition: job_09a0fddcd4c0d8713ed3
    - term: stage
    - definition: degrade（退化轴应用）
    - term: state
    - definition: 待运行
    - term: attempt / fencing
    - definition: 0 / 0
    - term: run 状态
    - definition: 已受理
    - term: run revision
    - definition: "2"
    - term: 队列位置
    - definition: "0"
    - term: 依赖
    - definition: 无
    - term: 被它阻塞
    - definition: 无
    - term: 输出资产
    - definition: 无
    - button "暂停（安全点）"
    - button "恢复" [disabled]
    - text: 不可用：只有 PAUSED 的 run 能恢复（当前 ACCEPTED）
    - button "停止新任务（取消）"
    - button "重试（可恢复错误）" [disabled]
    - text: 不可用：后端 error.retryable=无 error
    - button "查看证据 / 隔离资产"
    - heading "资源（估算）与实测进度" [level=3]
    - paragraph:
      - text: 下表第一组来自
      - code: resource_estimate
      - text: （后端按 stage 给出的**估算**，不是实测）， 第二组来自
      - code: progress
      - text: （真实计数）与 job spec。
    - table "估算与实测分开显示；缺失项不补 0":
      - caption: 估算与实测分开显示；缺失项不补 0
      - rowgroup:
        - row "指标 实测值 单位 n（样本数） 区间 / 备注 来源":
          - columnheader "指标"
          - columnheader "实测值"
          - columnheader "单位"
          - columnheader "n（样本数）"
          - columnheader "区间 / 备注"
          - columnheader "来源"
      - rowgroup:
        - 'row "RSS 估算 3.00 GB GB 未提供 — GET /jobs/{id}.resource_estimate（估算）"':
          - rowheader "RSS 估算"
          - cell "3.00 GB"
          - cell "GB"
          - cell "未提供"
          - cell "—"
          - 'cell "GET /jobs/{id}.resource_estimate（估算）"'
        - 'row "VRAM 估算 0.00 GB GB 未提供 — GET /jobs/{id}.resource_estimate（估算）"':
          - rowheader "VRAM 估算"
          - cell "0.00 GB"
          - cell "GB"
          - cell "未提供"
          - cell "—"
          - 'cell "GET /jobs/{id}.resource_estimate（估算）"'
        - 'row "临时磁盘估算 1.20 GB GB 未提供 — GET /jobs/{id}.resource_estimate（估算）"':
          - rowheader "临时磁盘估算"
          - cell "1.20 GB"
          - cell "GB"
          - cell "未提供"
          - cell "—"
          - 'cell "GET /jobs/{id}.resource_estimate（估算）"'
        - 'row "CPU 时间估算 2.5 min — 未提供 — GET /jobs/{id}.resource_estimate（估算）"':
          - rowheader "CPU 时间估算"
          - cell "2.5 min"
          - cell "—"
          - cell "未提供"
          - cell "—"
          - 'cell "GET /jobs/{id}.resource_estimate（估算）"'
        - 'row "可量化进度 未提供 — 未提供 — GET /jobs/{job_id}.progress"':
          - rowheader "可量化进度"
          - cell "未提供"
          - cell "—"
          - cell "未提供"
          - cell "—"
          - 'cell "GET /jobs/{job_id}.progress"'
        - row "RSS 实测峰值 未提供 — 未提供 — API 未提供实测采样":
          - rowheader "RSS 实测峰值"
          - cell "未提供"
          - cell "—"
          - cell "未提供"
          - cell "—"
          - cell "API 未提供实测采样"
        - row "IO / 磁盘实测 未提供 — 未提供 — API 未提供实测采样":
          - rowheader "IO / 磁盘实测"
          - cell "未提供"
          - cell "—"
          - cell "未提供"
          - cell "—"
          - cell "API 未提供实测采样"
    - group: job.spec / error 原文
  - region "输出资产":
    - heading "输出资产" [level=2]
    - paragraph: GET /assets（keyset 分页，服务端过滤 workspace/role）· 已加载 12 条 · total=276
    - button "刷新"
    - text: 角色过滤（空格/逗号分隔）
    - combobox "角色过滤（空格/逗号分隔）"
    - text: QA 状态
    - combobox "QA 状态":
      - option "（全部）" [selected]
      - option "QA_PASS"
      - option "QA_PENDING"
      - option "QA_FAIL"
    - text: split
    - textbox "split":
      - /placeholder: train / dev / confirm
    - text: lineage_id
    - textbox "lineage_id":
      - /placeholder: 由页面传入
    - table "输出资产：数据来自 GET /assets，未做任何本地补全":
      - caption: 输出资产：数据来自 GET /assets，未做任何本地补全
      - rowgroup:
        - row "asset_id role schema unit / frame QA lineage / split 文件 创建 操作":
          - columnheader "asset_id"
          - columnheader "role"
          - columnheader "schema"
          - columnheader "unit / frame"
          - columnheader "QA"
          - columnheader "lineage / split"
          - columnheader "文件"
          - columnheader "创建"
          - columnheader "操作"
      - rowgroup:
        - row "asset_167bef6a43a93438… mother_mesh synlab.mother.v1 mm / W_mm QA 通过 a12_demo / train arrays, meta 12.4 h 前 详情 溯源":
          - cell "asset_167bef6a43a93438…"
          - cell "mother_mesh"
          - cell "synlab.mother.v1"
          - cell "mm / W_mm"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_f8dd1f356638dd5b… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情 溯源":
          - cell "asset_f8dd1f356638dd5b…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_5d64c292bfc303f5… mother_mesh synlab.mother.v1 mm / W_mm QA 通过 a12_demo / train arrays, meta 12.4 h 前 详情 溯源":
          - cell "asset_5d64c292bfc303f5…"
          - cell "mother_mesh"
          - cell "synlab.mother.v1"
          - cell "mm / W_mm"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_b1319403f7d76e8b… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情 溯源":
          - cell "asset_b1319403f7d76e8b…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_ab4fd6493ce77c26… mother_mesh synlab.mother.v1 mm / W_mm QA 通过 a12_demo / train arrays, meta 12.4 h 前 详情 溯源":
          - cell "asset_ab4fd6493ce77c26…"
          - cell "mother_mesh"
          - cell "synlab.mother.v1"
          - cell "mm / W_mm"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_121639c62ae3c6ab… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情 溯源":
          - cell "asset_121639c62ae3c6ab…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_8c3598afab393bda… mother_mesh synlab.mother.v1 mm / W_mm QA 通过 a12_demo / train arrays, meta 12.4 h 前 详情 溯源":
          - cell "asset_8c3598afab393bda…"
          - cell "mother_mesh"
          - cell "synlab.mother.v1"
          - cell "mm / W_mm"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_3cc24107c2990d3f… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情 溯源":
          - cell "asset_3cc24107c2990d3f…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_a5a5e547c544d731… mother_mesh synlab.mother.v1 mm / W_mm QA 通过 a12_demo / train arrays, meta 12.4 h 前 详情 溯源":
          - cell "asset_a5a5e547c544d731…"
          - cell "mother_mesh"
          - cell "synlab.mother.v1"
          - cell "mm / W_mm"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_59f7b916c1431c67… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情 溯源":
          - cell "asset_59f7b916c1431c67…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_518054a63abc8dd9… mother_mesh synlab.mother.v1 mm / W_mm QA 通过 a12_demo / train arrays, meta 12.4 h 前 详情 溯源":
          - cell "asset_518054a63abc8dd9…"
          - cell "mother_mesh"
          - cell "synlab.mother.v1"
          - cell "mm / W_mm"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "asset_d030be8aac7459ad… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情 溯源":
          - cell "asset_d030be8aac7459ad…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
    - button "上一页" [disabled]
    - button "下一页"
    - text: 第 1 页 · limit=12 · 排序 created_at.asc,id.asc
  - region "失败/隔离任务（按类型）":
    - heading "失败/隔离任务（按类型）" [level=2]
    - paragraph: 筛选出的真实 FAILED/QUARANTINED/RETRYABLE 行
    - status: 当前筛选下没有失败/隔离任务
  - region "run 汇总":
    - heading "run 汇总" [level=2]
    - paragraph: 由真实 job 行按 run_id 归并
    - list:
      - listitem: run_60b5675732dc86c56ebe 未终止 最近更新 12.2 h 前 待运行×1
    - paragraph: 成功统计由 accepted manifest / job.state 推得，不由前端累加猜测；取消或失败不会被计成成功。
    - button "选中第一行"
    - text: 已选 job_09a0fddcd4c0d8713ed3
```

# Test source

```ts
  166 |   const axisGroup = page.getByRole('group', { name: /PHYSICAL/ });
  167 |   await expect(axisGroup).toBeVisible();
  168 |   await expect(axisGroup.locator('tbody tr').first()).toBeVisible({ timeout: 60_000 });
  169 |   await axisGroup.locator('tbody tr').first().getByRole('button', { name: '加入' }).click();
  170 |   const levelSelect = axisGroup.locator('tbody tr').first().locator('select');
  171 |   await expect(levelSelect).toBeVisible();
  172 |   await expect(levelSelect.locator('option')).toHaveCount(5);
  173 |   await expect(levelSelect.locator('option', { hasText: '真恒等' })).toHaveCount(1);
  174 | 
  175 |   // ---------------------------------------------------------------- ④ 观测
  176 |   await page.getByRole('button', { name: /④ 观测/ }).click();
  177 |   const routeSelect = page.getByLabel('观测路线');
  178 |   await expect(routeSelect).toBeVisible();
  179 |   const routeOptions = await routeSelect.locator('option').allInnerTexts();
  180 |   expect(routeOptions.join(' ')).toContain('photo_mvs');
  181 |   await expect(page.getByLabel('每片视角数')).toBeVisible();
  182 |   await expect(page.getByLabel('长边像素')).toBeVisible();
  183 |   const rendererSelect = page.getByLabel('渲染后端');
  184 |   const rendererOptions = await rendererSelect.locator('option').allInnerTexts();
  185 |   expect(rendererOptions.join(' ')).toContain('software_rasterizer');
  186 |   expect(rendererOptions.join(' ')).toContain('blender');
  187 | 
  188 |   // ---------------------------------------------------------------- ⑤ 预览（真实跑一条谱系）
  189 |   await page.getByRole('button', { name: /⑤ 预览/ }).click();
  190 |   const previewHash = page.getByText('预览 spec_hash（后端 /specs/validate）');
  191 |   await expect(previewHash).toBeVisible();
  192 |   // 后端 /specs/validate 的真实 hash 必须出现（sha256: 前缀）
  193 |   await expect(page.locator('dd.mono', { hasText: /^sha256:/ }).first()).toBeVisible({ timeout: 60_000 });
  194 | 
  195 |   const runPreview = page.getByRole('button', { name: '跑一次单谱系预览' });
  196 |   await expect(runPreview).toBeEnabled({ timeout: 60_000 });
  197 |   await runPreview.click();
  198 | 
  199 |   // 真实结果：要么跑完（阶段耗时表出现），要么停在真实阻塞点并显示错误码 + 复现命令。
  200 |   const stagesTable = page.getByRole('table', { name: /每阶段真实耗时/ });
  201 |   const failureCard = page.locator('.state--error').filter({ hasText: /复现命令|预览未完成/ });
  202 |   await expect(stagesTable.or(failureCard).first()).toBeVisible({ timeout: 300_000 });
  203 | 
  204 |   if (await stagesTable.count()) {
  205 |     const stageRows = await stagesTable.locator('tbody tr').count();
  206 |     expect(stageRows).toBeGreaterThan(0);
  207 |     // 阶段耗时列必须是真实数字（不是“未提供”占位）
  208 |     const firstSeconds = await stagesTable.locator('tbody tr').first().locator('td').first().innerText();
  209 |     expect(firstSeconds.trim().length).toBeGreaterThan(0);
  210 |     await expect(page.getByText('产出资产', { exact: false }).first()).toBeVisible();
  211 |   } else {
  212 |     // 真实阻塞：必须能看到后端错误码与复现命令，而不是空状态
  213 |     await expect(failureCard.first()).toContainText(/CHAIN_|INTEGRATION_PENDING|ENV_CAPABILITY_MISSING|SCHEMA_INVALID/);
  214 |     await expect(failureCard.first().getByRole('button', { name: /复制/ }).first()).toBeVisible();
  215 |   }
  216 | 
  217 |   // ---------------------------------------------------------------- ⑥ 入队批量（真实规划 + 真实受理）
  218 |   await page.getByRole('button', { name: /⑥ 入队批量/ }).click();
  219 |   await expect(page.getByLabel('批大小')).toBeVisible();
  220 |   const resumeButton = page.getByRole('button', { name: '一键续跑下一批（resume）' });
  221 |   await expect(resumeButton).toBeVisible();
  222 |   await resumeButton.click();
  223 |   await expect(page.getByText('本批组合', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
  224 | 
  225 |   const submitBatch = page.getByRole('button', { name: '提交这一批（POST /jobs）' });
  226 |   if (await submitBatch.isEnabled().catch(() => false)) {
  227 |     await submitBatch.click();
  228 |     // 受理（202）后必须出现真实 run_id 与权威 job state 计数
  229 |     await expect(page.getByText('run_id', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
  230 |     await expect(page.locator('.statrow').first()).toBeVisible({ timeout: 60_000 });
  231 |   }
  232 | 
  233 |   // ---------------------------------------------------------------- 导出 YAML 与 spec_hash
  234 |   await expect(page.getByRole('button', { name: '下载 .yaml' })).toBeVisible();
  235 |   await expect(page.locator('pre.mono').filter({ hasText: 'schema:' }).first()).toBeVisible();
  236 | 
  237 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  238 | });
  239 | 
  240 | /** U07 批量合成面板：真实 planned/attempted/accepted/failed 与覆盖矩阵。 */
  241 | test('U07 批量面板：真实计数、失败错误码与覆盖矩阵', async ({ page }) => {
  242 |   const console = watchConsole(page);
  243 |   await page.goto('/synlab/jobs');
  244 | 
  245 |   const panel = region(page, '批量合成（真实计数 · 覆盖矩阵 · 一键续跑）');
  246 |   await expect(panel).toBeVisible();
  247 | 
  248 |   // 真实计数：planned/attempted/accepted/failed 四个数字必须来自 /synthesis/inventory
  249 |   for (const label of ['planned', 'attempted', 'accepted', 'failed']) {
  250 |     await expect(panel.getByText(label, { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  251 |   }
  252 |   const stats = panel.locator('.statrow').first();
  253 |   await expect(stats.locator('.stat').first()).toBeVisible({ timeout: 60_000 });
  254 |   const statText = await stats.innerText();
  255 |   expect(statText).toMatch(/planned\s*\d+/);
  256 |   expect(statText).toMatch(/failed\s*\d+/);
  257 | 
  258 |   // 覆盖矩阵：维度名与来源必须可见（没有 reports/coverage*.json 时显示“没有覆盖矩阵”而不是假数据）
  259 |   const coverageCard = region(page, '覆盖矩阵（器型 × 材料 × 花纹 × 层）');
  260 |   await expect(coverageCard).toBeVisible();
  261 |   await expect(
  262 |     coverageCard.getByText('24 器物').or(coverageCard.getByText('没有覆盖矩阵')).first(),
  263 |   ).toBeVisible({ timeout: 60_000 });
  264 | 
  265 |   // 一键续跑：真实规划出组合（或显示真实的“组合空间已走完/registry 为空”原因）
> 266 |   await expect(panel.getByRole('button', { name: '一键续跑下一批' })).toBeVisible();
      |                                                                ^ Error: expect(locator).toBeVisible() failed
  267 |   await panel.getByRole('button', { name: '一键续跑下一批' }).click();
  268 |   await expect(
  269 |     panel.getByText('本批组合').or(panel.locator('.state--error')).first(),
  270 |   ).toBeVisible({ timeout: 60_000 });
  271 | 
  272 |   await expect(panel.locator('.state--error')).toHaveCount(0);
  273 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  274 | });
  275 | 
  276 | /** U04 断裂预览：审计数值原样展示 + 目标片数对照 + 断面属性诚实处理。 */
  277 | test('U04 断裂预览：审计数值与断面属性', async ({ page }) => {
  278 |   const console = watchConsole(page);
  279 |   await page.goto('/synlab/fracture');
  280 | 
  281 |   const panel = region(page, '断裂预览：目标片数 vs 实测片数 + 审计数值');
  282 |   await expect(panel).toBeVisible();
  283 |   // 目标片数来自 spec；实测片数来自真实资产清单（未选碎片时如实显示未选择）
  284 |   await expect(panel.getByText('目标片数区间')).toBeVisible();
  285 |   await expect(panel.getByText('实测片数（同谱系）')).toBeVisible();
  286 |   // 断面视图必须在（未选碎片时显示真实空状态；选了缺属性的资产则显示“该资产缺断面属性”）
  287 |   await expect(panel.getByText('碎片 3D（原位 / 爆炸）+ 断面高亮')).toBeVisible();
  288 |   await expect(panel.getByText('权威：mm / Z-up')).toBeVisible();
  289 |   // 爆炸是展示变换的声明必须存在
  290 |   await expect(panel.getByText('爆炸位移（mm，展示用）')).toBeVisible();
  291 | 
  292 |   // 选择一块真实碎片（若 store 里有）后，必须出现审计数值表或“缺断面属性”的诚实提示
  293 |   const fragmentBrowser = region(page, '碎片（fragment_mesh）');
  294 |   await expect(fragmentBrowser).toBeVisible();
  295 |   const rows = await fragmentBrowser.locator('tbody tr').count();
  296 |   if (rows > 0) {
  297 |     await fragmentBrowser.locator('tbody tr').first().locator('input').check();
  298 |     await expect(
  299 |       panel.getByText('审计数值（后端原样）').first(),
  300 |     ).toBeVisible({ timeout: 60_000 });
  301 |     await expect(
  302 |       panel.getByText('qa.parent_qa', { exact: false })
  303 |         .or(panel.getByText('该资产缺断面属性'))
  304 |         .or(panel.getByText('该碎片没有 qa 字段')).first(),
  305 |     ).toBeVisible({ timeout: 90_000 });
  306 |   }
  307 | 
  308 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  309 | });
  310 | 
  311 | /** U05 退化预览：L0 与 Ln 并排（未物化时显示 NA + 补齐命令，绝不用别的级别顶替）。 */
  312 | test('U05 退化预览：L0 与 Ln 并排或 NA', async ({ page }) => {
  313 |   const console = watchConsole(page);
  314 |   await page.goto('/synlab/degradation');
  315 | 
  316 |   const panel = region(page, 'L0（真恒等）与 Ln 并排预览（同 basis、同 source）');
  317 |   await expect(panel).toBeVisible();
  318 |   await expect(
  319 |     panel.getByText('L0（baseline，真恒等）').or(panel.getByText('没有任何已物化的退化轴')).first(),
  320 |   ).toBeVisible({ timeout: 90_000 });
  321 | 
  322 |   // 有物化轴时必须给出 axis 选择器与“已物化档位”表，且 level 0 缺失要标 NA
  323 |   const axisSelect = panel.getByLabel('选择退化轴');
  324 |   if (await axisSelect.count()) {
  325 |     await expect(axisSelect).toBeVisible();
  326 |     const table = panel.getByRole('table', { name: /已物化的轴与档位/ });
  327 |     await expect(table).toBeVisible();
  328 |     const levelCell = await table.locator('tbody tr').first().locator('td').first().innerText();
  329 |     expect(levelCell).toMatch(/\d+:\d+/);
  330 |     // 缺 level 0 的轴必须显式标 NA（而不是拿 L1 冒充）
  331 |     await expect(table.getByText('level 0 = NA').first()).toBeVisible({ timeout: 30_000 });
  332 |   }
  333 | 
  334 |   // 未物化/无配对时必须给出真实原因，且不出现任何“L1 作为 baseline”的说法
  335 |   await expect(panel.getByText('L1').first()).toHaveCount(0);
  336 | 
  337 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  338 | });
  339 | 
```