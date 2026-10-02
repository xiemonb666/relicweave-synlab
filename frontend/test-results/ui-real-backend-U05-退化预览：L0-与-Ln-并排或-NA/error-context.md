# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: ui-real-backend.spec.ts >> U05 退化预览：L0 与 Ln 并排或 NA
- Location: e2e\ui-real-backend.spec.ts:312:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('region', { name: 'L0（真恒等）与 Ln 并排预览（同 basis、同 source）' }).getByRole('table', { name: /已物化的轴与档位/ }).getByText('level 0 = NA').first()
Expected: visible
Timeout: 30000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('region', { name: 'L0（真恒等）与 Ln 并排预览（同 basis、同 source）' }).getByRole('table', { name: /已物化的轴与档位/ }).getByText('level 0 = NA').first() with timeout 30000ms
  - waiting for getByRole('region', { name: 'L0（真恒等）与 Ln 并排预览（同 basis、同 source）' }).getByRole('table', { name: /已物化的轴与档位/ }).getByText('level 0 = NA').first()

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
  - heading "退化对比 U05 · 计划 20.6" [level=1]
  - paragraph: 左 baseline、右 level，同视角/zoom/crop 联动；P/I/G/X 分组选轴 → 五档或具体参数 → 预览任务 → 待运行/排队/计算/检查 → 实测表。滑块不是测量值。
  - text: 共享相机（结构联动） 误差热图 + 点云叠加（前端由真实 depth/points 计算）
  - region "31 轴与 P/I/G/X 分组（registry）":
    - heading "31 轴与 P/I/G/X 分组（registry）" [level=2]
    - paragraph: GET /registry/axis —— 轴清单与 level 0..4 的真实来源
    - tablist "退化分组":
      - tab "P 物理损伤（8）" [selected]
      - tab "I 成像/观测（10）"
      - tab "G 观测重建（8）"
      - tab "X 其它（5）"
    - table:
      - rowgroup:
        - row "axis 名称 状态 适用组合 加入配方":
          - columnheader "axis"
          - columnheader "名称"
          - columnheader "状态"
          - columnheader "适用组合"
          - columnheader "加入配方"
      - rowgroup:
        - 'row "P01 P01 IMPLEMENTED {} 加入"':
          - rowheader "P01"
          - cell "P01"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P02 P02 IMPLEMENTED {} 加入"':
          - rowheader "P02"
          - cell "P02"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P03 P03 IMPLEMENTED {} 加入"':
          - rowheader "P03"
          - cell "P03"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P04 P04 IMPLEMENTED {} 加入"':
          - rowheader "P04"
          - cell "P04"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P05 P05 IMPLEMENTED {} 加入"':
          - rowheader "P05"
          - cell "P05"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P06 P06 IMPLEMENTED {} 加入"':
          - rowheader "P06"
          - cell "P06"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P07 P07 IMPLEMENTED {} 加入"':
          - rowheader "P07"
          - cell "P07"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
        - 'row "P08 P08 IMPLEMENTED {} 加入"':
          - rowheader "P08"
          - cell "P08"
          - cell "IMPLEMENTED"
          - 'cell "{}"'
          - cell "加入":
            - button "加入"
  - region "算子（DegradationOperatorSpec[]）":
    - heading "算子（DegradationOperatorSpec[]）" [level=2]
    - paragraph: axis_id / stage / level(0..4) / variant / parameters
    - status: 配方里还没有算子 从上面的轴清单点“加入”，或直接在下方手填 axis_id（例如 P01）。stage 与 level 的合法性由服务端校验。
    - button "新增空算子"
    - text: level 0 必须与 baseline 同源（依赖 basis_policy=paired_across_levels）；后端会校验，前端不做假设。
  - region "baseline（左）":
    - heading "baseline（左）" [level=2]
    - paragraph: GET /assets（keyset 分页，服务端过滤 workspace/role）· 已加载 8 条 · total=118
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
    - table "baseline（左）：数据来自 GET /assets，未做任何本地补全":
      - caption: baseline（左）：数据来自 GET /assets，未做任何本地补全
      - rowgroup:
        - row "选择 asset_id role schema unit / frame QA lineage / split 文件 创建 操作":
          - columnheader "选择"
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
        - row "选择资产 asset_f8dd1f356638dd5b6e12 asset_f8dd1f356638dd5b… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_f8dd1f356638dd5b6e12":
            - radio "选择资产 asset_f8dd1f356638dd5b6e12"
          - cell "asset_f8dd1f356638dd5b…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_b1319403f7d76e8b44af asset_b1319403f7d76e8b… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_b1319403f7d76e8b44af":
            - radio "选择资产 asset_b1319403f7d76e8b44af"
          - cell "asset_b1319403f7d76e8b…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_121639c62ae3c6abd5bc asset_121639c62ae3c6ab… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_121639c62ae3c6abd5bc":
            - radio "选择资产 asset_121639c62ae3c6abd5bc"
          - cell "asset_121639c62ae3c6ab…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_3cc24107c2990d3f33aa asset_3cc24107c2990d3f… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_3cc24107c2990d3f33aa":
            - radio "选择资产 asset_3cc24107c2990d3f33aa"
          - cell "asset_3cc24107c2990d3f…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_59f7b916c1431c67028f asset_59f7b916c1431c67… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_59f7b916c1431c67028f":
            - radio "选择资产 asset_59f7b916c1431c67028f"
          - cell "asset_59f7b916c1431c67…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_d030be8aac7459ad2624 asset_d030be8aac7459ad… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_d030be8aac7459ad2624":
            - radio "选择资产 asset_d030be8aac7459ad2624"
          - cell "asset_d030be8aac7459ad…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_3abbd28e8a8efe9f66ca asset_3abbd28e8a8efe9f… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_3abbd28e8a8efe9f66ca":
            - radio "选择资产 asset_3abbd28e8a8efe9f66ca"
          - cell "asset_3abbd28e8a8efe9f…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_9e75749f77fb3ff1962b asset_9e75749f77fb3ff1… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_9e75749f77fb3ff1962b":
            - radio "选择资产 asset_9e75749f77fb3ff1962b"
          - cell "asset_9e75749f77fb3ff1…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
    - button "上一页" [disabled]
    - button "下一页"
    - text: 第 1 页 · limit=8 · 排序 created_at.asc,id.asc
  - region "level 结果（右）":
    - heading "level 结果（右）" [level=2]
    - paragraph: GET /assets（keyset 分页，服务端过滤 workspace/role）· 已加载 8 条 · total=118
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
    - table "level 结果（右）：数据来自 GET /assets，未做任何本地补全":
      - caption: level 结果（右）：数据来自 GET /assets，未做任何本地补全
      - rowgroup:
        - row "选择 asset_id role schema unit / frame QA lineage / split 文件 创建 操作":
          - columnheader "选择"
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
        - row "选择资产 asset_f8dd1f356638dd5b6e12 asset_f8dd1f356638dd5b… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_f8dd1f356638dd5b6e12":
            - radio "选择资产 asset_f8dd1f356638dd5b6e12"
          - cell "asset_f8dd1f356638dd5b…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_b1319403f7d76e8b44af asset_b1319403f7d76e8b… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_b1319403f7d76e8b44af":
            - radio "选择资产 asset_b1319403f7d76e8b44af"
          - cell "asset_b1319403f7d76e8b…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_121639c62ae3c6abd5bc asset_121639c62ae3c6ab… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_121639c62ae3c6abd5bc":
            - radio "选择资产 asset_121639c62ae3c6abd5bc"
          - cell "asset_121639c62ae3c6ab…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_3cc24107c2990d3f33aa asset_3cc24107c2990d3f… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_3cc24107c2990d3f33aa":
            - radio "选择资产 asset_3cc24107c2990d3f33aa"
          - cell "asset_3cc24107c2990d3f…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_59f7b916c1431c67028f asset_59f7b916c1431c67… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_59f7b916c1431c67028f":
            - radio "选择资产 asset_59f7b916c1431c67028f"
          - cell "asset_59f7b916c1431c67…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_d030be8aac7459ad2624 asset_d030be8aac7459ad… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_d030be8aac7459ad2624":
            - radio "选择资产 asset_d030be8aac7459ad2624"
          - cell "asset_d030be8aac7459ad…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_3abbd28e8a8efe9f66ca asset_3abbd28e8a8efe9f… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_3abbd28e8a8efe9f66ca":
            - radio "选择资产 asset_3abbd28e8a8efe9f66ca"
          - cell "asset_3abbd28e8a8efe9f…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
        - row "选择资产 asset_9e75749f77fb3ff1962b asset_9e75749f77fb3ff1… display_lod_glb synlab.display_glb.v1 m / Y_up_m QA 通过 a12_demo / train glb, meta 12.4 h 前 详情":
          - cell "选择资产 asset_9e75749f77fb3ff1962b":
            - radio "选择资产 asset_9e75749f77fb3ff1962b"
          - cell "asset_9e75749f77fb3ff1…"
          - cell "display_lod_glb"
          - cell "synlab.display_glb.v1"
          - cell "m / Y_up_m"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "glb, meta"
          - cell "12.4 h 前"
          - cell "详情":
            - button "详情"
    - button "上一页" [disabled]
    - button "下一页"
    - text: 第 1 页 · limit=8 · 排序 created_at.asc,id.asc
  - region "观测与真值资产（obs_view / obs_result / clean_truth / physical_truth）":
    - heading "观测与真值资产（obs_view / obs_result / clean_truth / physical_truth）" [level=2]
    - paragraph: GET /assets（keyset 分页，服务端过滤 workspace/role）· 已加载 10 条 · total=59
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
    - table "观测与真值资产（obs_view / obs_result / clean_truth / physical_truth）：数据来自 GET /assets，未做任何本地补全":
      - caption: 观测与真值资产（obs_view / obs_result / clean_truth / physical_truth）：数据来自 GET /assets，未做任何本地补全
      - rowgroup:
        - row "选择 asset_id role schema unit / frame QA lineage / split 文件 创建 操作":
          - columnheader "选择"
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
        - row "选择资产 asset_fd5eb693a4a06c7477cd asset_fd5eb693a4a06c74… obs_view synlab.obs.v1 px / S_mm QA 待定 a12_demo / train arrays, meta 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_fd5eb693a4a06c7477cd":
            - radio "选择资产 asset_fd5eb693a4a06c7477cd"
          - cell "asset_fd5eb693a4a06c74…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / S_mm"
          - cell "QA 待定"
          - cell "a12_demo / train"
          - cell "arrays, meta"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_85e04c40cccbad71f6cb asset_85e04c40cccbad71… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_85e04c40cccbad71f6cb":
            - radio "选择资产 asset_85e04c40cccbad71f6cb"
          - cell "asset_85e04c40cccbad71…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_2cac92c696a0cc5dc4d7 asset_2cac92c696a0cc5d… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_2cac92c696a0cc5dc4d7":
            - radio "选择资产 asset_2cac92c696a0cc5dc4d7"
          - cell "asset_2cac92c696a0cc5d…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_ad8420a332e0caa4ff3b asset_ad8420a332e0caa4… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_ad8420a332e0caa4ff3b":
            - radio "选择资产 asset_ad8420a332e0caa4ff3b"
          - cell "asset_ad8420a332e0caa4…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_3fd22b474fb661de91d2 asset_3fd22b474fb661de… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_3fd22b474fb661de91d2":
            - radio "选择资产 asset_3fd22b474fb661de91d2"
          - cell "asset_3fd22b474fb661de…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_5e97c3dd2ec9211a6a88 asset_5e97c3dd2ec9211a… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_5e97c3dd2ec9211a6a88":
            - radio "选择资产 asset_5e97c3dd2ec9211a6a88"
          - cell "asset_5e97c3dd2ec9211a…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_d3ee5085de6a0ab772ee asset_d3ee5085de6a0ab7… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_d3ee5085de6a0ab772ee":
            - radio "选择资产 asset_d3ee5085de6a0ab772ee"
          - cell "asset_d3ee5085de6a0ab7…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_6ae1468fc7f941d13abb asset_6ae1468fc7f941d1… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_6ae1468fc7f941d13abb":
            - radio "选择资产 asset_6ae1468fc7f941d13abb"
          - cell "asset_6ae1468fc7f941d1…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_f5d179682a538a237129 asset_f5d179682a538a23… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_f5d179682a538a237129":
            - radio "选择资产 asset_f5d179682a538a237129"
          - cell "asset_f5d179682a538a23…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
        - row "选择资产 asset_4273e0fb5c43c37f9aab asset_4273e0fb5c43c37f… obs_view synlab.obs.v1 px / pixel_cv_center QA 通过 a12_demo / train meta, png 12.3 h 前 详情 溯源":
          - cell "选择资产 asset_4273e0fb5c43c37f9aab":
            - radio "选择资产 asset_4273e0fb5c43c37f9aab"
          - cell "asset_4273e0fb5c43c37f…"
          - cell "obs_view"
          - cell "synlab.obs.v1"
          - cell "px / pixel_cv_center"
          - cell "QA 通过"
          - cell "a12_demo / train"
          - cell "meta, png"
          - cell "12.3 h 前"
          - cell "详情 溯源":
            - button "详情"
            - button "溯源"
    - button "上一页" [disabled]
    - button "下一页"
    - text: 第 1 页 · limit=10 · 排序 created_at.asc,id.asc
  - text: 比较视口 共享相机（结构联动） 左：baseline 右：level
  - tablist "比较模式":
    - tab "RGB wipe" [selected]
    - tab "并列"
    - tab "叠加"
  - text: 分界 50%
  - slider "分界 50%": "0.5"
  - text: 右侧透明度 0.55
  - slider "右侧透明度 0.55" [disabled]: "0.55"
  - button "重置视角"
  - text: baseline level
  - status: 没有可比较的展示资产 比较视口只加载真实的 display_lod GLB。请先在左侧资产列表里为两侧各选一个派生展示资产；不会用示意几何代替。
  - table "实测读数（来自真实 GLB 与响应头，展示 m/Y-up → 权威 mm/Z-up 换算一次）":
    - caption: 实测读数（来自真实 GLB 与响应头，展示 m/Y-up → 权威 mm/Z-up 换算一次）
    - rowgroup:
      - row "指标 左：baseline 右：level 右 − 左":
        - columnheader "指标"
        - columnheader "左：baseline"
        - columnheader "右：level"
        - columnheader "右 − 左"
    - rowgroup:
      - row "资产 未选择 未选择 —":
        - rowheader "资产"
        - cell "未选择"
        - cell "未选择"
        - cell "—"
      - row "权威尺寸 (mm) — — —":
        - rowheader "权威尺寸 (mm)"
        - cell "—"
        - cell "—"
        - cell "—"
      - row "展示尺寸 (m) — — —":
        - rowheader "展示尺寸 (m)"
        - cell "—"
        - cell "—"
        - cell "—"
      - row "三角面 — — —":
        - rowheader "三角面"
        - cell "—"
        - cell "—"
        - cell "—"
      - row "GLB 大小 — — —":
        - rowheader "GLB 大小"
        - cell "—"
        - cell "—"
        - cell "—"
      - row "QA / 坐标契约 — — —":
        - rowheader "QA / 坐标契约"
        - cell "—"
        - cell "—"
        - cell "—"
      - row "中心 → 权威坐标 (mm) — — —":
        - rowheader "中心 → 权威坐标 (mm)"
        - cell "—"
        - cell "—"
        - cell "—"
  - heading "本视口（GLB 展示几何）不做的事（如实列出，不用假数据填充）" [level=4]
  - list:
    - listitem:
      - strong: 误差热图
      - text: ：本视口只比较 GLB 展示几何，不画误差场。真实数组的差异视图在 U05 页面下方的 “误差热图与点云叠加（真实数组）”面板里，由后端
      - code: depth_z
      - text: /
      - code: points
      - text: 在前端计算，并标注“非后端误差场”。
    - listitem:
      - strong: 点云 / mesh 叠加
      - text: ：本视口不解析点云资产（role 形如
      - code: obs_fused_geometry
      - text: ）；点云叠加同样在上面的面板里实现（浏览器内解码 npz）。
    - listitem:
      - strong: 真实差分表
      - text: ：需要成对的实测指标。可用数据在
      - code: GET /assets?role=...
      - text: 的
      - code: qa
      - text: 字段里， U05 页面下方按资产原样列出。
  - region "实测表（选中资产的 qa）":
    - heading "实测表（选中资产的 qa）" [level=2]
    - paragraph: "GET /assets/{id}"
    - status: 未选择资产 在左侧选择观测/真值资产后，这里显示后端记录的实测字段。
  - region "相机档与共同 basis":
    - heading "相机档与共同 basis" [level=2]
    - paragraph: GET /camera-profiles
    - paragraph: capability cameras = OK catalogue=3 · registered=0
    - list:
      - listitem: CAM_GLOBAL_V3（未标定）
      - listitem: CAM_MID_V3（未标定）
      - listitem: CAM_LOCAL_V3（未标定）
    - paragraph: 切换相机档会改变“共同 basis”的观测条件；同轴不同档的结果不能混在同一条曲线（U10 曲线的 n/M/K 标注依赖这一点）。
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
    - button "（本页不提交任务）" [disabled]
    - text: 不可用：本页不提供任务提交
    - paragraph: 滑块/输入只改本地草稿；松手后需要点击上面的按钮才会发出真实请求。未运行前一律标“未计算”， 旧预览在新草稿下会提示“参数已变化”。
    - group "配方与 basis（DegradationRecipeSpec）":
      - text: 配方与 basis（DegradationRecipeSpec） 配方 ID
      - textbox "配方 ID": recipe_ui_draft
      - text: basis 策略
      - combobox "basis 策略":
        - option "（不设置 / 使用后端默认）"
        - option "paired_across_levels" [selected]
        - option "independent"
      - text: paired_across_levels 表示 level0/1/4 共用同一 basis（强度零同源内容） 作用对象（source_role）
      - combobox "作用对象（source_role）":
        - option "（不设置 / 使用后端默认）"
        - option "clean" [selected]
        - option "physical"
        - option "observed"
      - text: baseline/physical/observed 三层可切换；G 组只应作用于 observed schema
      - combobox "schema":
        - option "（不设置 / 使用后端默认）"
        - option "synlab.v3" [selected]
      - text: master seed（固定后重放一致）
      - spinbutton "master seed（固定后重放一致）": "20261001"
    - group: 高级：直接编辑 spec JSON（字段名与后端 extra="forbid" 模型一致）
    - paragraph:
      - text: 表单只产生草稿；合法性以
      - code: POST /specs/validate
      - text: 与
      - code: POST /jobs
      - text: 的回答为准（本页原样展示后端 errors）。共 5 个字段。
    - complementary:
      - heading "校验结果" [level=3]
      - paragraph: 尚未校验。点击“校验 spec”。
      - heading "幂等键" [level=3]
      - paragraph:
        - code: ui:232ebdd3-ce3a-4e7f-b685-d578f9619f00
        - button "复制幂等键": 复制
      - button "重新生成幂等键"
      - paragraph: 相同幂等键 + 相同 payload 返回原任务（idempotent_replay=true）；同键不同 payload 后端返回 409。
  - region "资源预算":
    - heading "资源预算" [level=2]
    - status: 尚未请求预算估算 点击上方“估算资源”调用真实的 POST /budgets；后端不可行时会返回 409 BUDGET_EXCEEDED。
  - region "为什么本页不提供“提交退化任务”":
    - heading "为什么本页不提供“提交退化任务”" [level=2]
    - paragraph: 后端真实约束（见 docs/a12/api_ui.md 差异表）
    - paragraph:
      - code: POST /jobs
      - text: 与
      - code: POST /previews
      - text: 只把请求体里的
      - code: spec
      - text: 按
      - code: synlab.v3
      - strong: 生成 spec
      - text: 校验 （
      - code: validate_spec(kind="generation")
      - text: ），没有任何路由接受
      - code: DegradationRecipeSpec
      - text: 。退化配方进入流水线的真实通道是生成 spec 里的
      - code: degraded_recipe_refs
      - text: （recipe_id 列表），由
      - code: synlab.degrade
      - text: 编译。
    - paragraph:
      - text: 因此本页只做真实可做的事：
      - strong: 校验配方
      - text: （
      - code: POST /specs/validate
      - text: kind=recipe，返回真实的字段/单位/组合/注册结论）与
      - strong: 查看已产出的观测资产实测值
      - text: 。 提交类动作留给 U07（生成任务，含
      - code: degraded_recipe_refs
      - text: ）。
  - region "L0（真恒等）与 Ln 并排预览（同 basis、同 source）":
    - heading "L0（真恒等）与 Ln 并排预览（同 basis、同 source）" [level=2]
    - paragraph: GET /synthesis/degradation-pairs —— 配对与 deltas 由后端从 meta 计算，前端只格式化
    - button "刷新配对"
    - tablist "退化轴分组":
      - tab "P（3 个已物化）" [selected]
      - tab "I（4 个已物化）"
      - tab "G（3 个已物化）"
      - tab "X（2 个已物化）"
    - text: axis
    - combobox "选择退化轴":
      - option "P03（level 0/1/2/3/4； basis 1）" [selected]
      - option "P05（level 0/1/2/3/4； basis 1）"
      - option "P06（level 0/1/2/3/4； basis 1）"
    - text: 存在同 basis 的 L0 与非 0 级 assets 表里出现 1 个 basis_id
    - table "本 store 已物化的轴与档位（来自资产表，未物化的档位就是 NA）":
      - caption: 本 store 已物化的轴与档位（来自资产表，未物化的档位就是 NA）
      - rowgroup:
        - row "axis level → 资产数（identity 正身） basis_id 数 paired 选择":
          - columnheader "axis"
          - columnheader "level → 资产数（identity 正身）"
          - columnheader "basis_id 数"
          - columnheader "paired"
          - columnheader "选择"
      - rowgroup:
        - row "P03 0:4(id2) · 1:2(id0) · 2:2(id0) · 3:2(id0) · 4:4(id0) 1 是 当前":
          - rowheader "P03"
          - cell "0:4(id2) · 1:2(id0) · 2:2(id0) · 3:2(id0) · 4:4(id0)"
          - cell "1"
          - cell "是"
          - cell "当前":
            - button "当前" [disabled]
        - row "P05 0:3(id2) · 1:4(id0) · 2:4(id0) · 3:4(id0) · 4:4(id0) 1 是 查看 L0/Ln":
          - rowheader "P05"
          - cell "0:3(id2) · 1:4(id0) · 2:4(id0) · 3:4(id0) · 4:4(id0)"
          - cell "1"
          - cell "是"
          - cell "查看 L0/Ln":
            - button "查看 L0/Ln"
        - row "P06 0:3(id2) · 1:4(id0) · 2:4(id0) · 3:4(id0) · 4:4(id0) 1 是 查看 L0/Ln":
          - rowheader "P06"
          - cell "0:3(id2) · 1:4(id0) · 2:4(id0) · 3:4(id0) · 4:4(id0)"
          - cell "1"
          - cell "是"
          - cell "查看 L0/Ln":
            - button "查看 L0/Ln"
    - text: basis 不一致（非 paired） source 不同 basis_id=未提供 source=未提供
    - paragraph: basis_id 不一致：这两级不是 paired 的，差值不能当作同一 basis 上的退化量
    - heading "L0（baseline，真恒等） identity=null level=0" [level=4]
    - term: asset_id
    - definition: asset_895ff9aeeae024b22d3b
    - term: role
    - definition: display_lod_glb
    - term: basis_id
    - definition: 未提供
    - term: source_asset_id
    - definition: 未提供
    - term: variant
    - definition: smooth_recession_field
    - term: realized
    - definition: "null"
    - strong: asset_895ff9aeeae024b22d3b 的真实帧
    - status: 没有可显示的帧 未选择资产或该资产没有声明 RGB 数组键。
    - status: 该资产没有 measured 退化阶段未写 measured，这一级就没有可比较的实测量。
    - group: meta 原文（后端原样）
    - heading "Ln（level 4） identity=null level=4" [level=4]
    - term: asset_id
    - definition: asset_53d62c31f5be7e3705d8
    - term: role
    - definition: display_lod_glb
    - term: basis_id
    - definition: 未提供
    - term: source_asset_id
    - definition: 未提供
    - term: variant
    - definition: smooth_recession_field
    - term: realized
    - definition: "null"
    - strong: asset_53d62c31f5be7e3705d8 的真实帧
    - status: 没有可显示的帧 未选择资产或该资产没有声明 RGB 数组键。
    - status: 该资产没有 measured 退化阶段未写 measured，这一级就没有可比较的实测量。
    - group: meta 原文（后端原样）
    - status: 这两级都没有 meta.measured 退化阶段没有写 measured 字段时无法给出真实变化量；本表不会用参数档位反推一个数字。
    - paragraph:
      - text: 并排的 L0 与 Ln 来自两条真实资产记录；差值列是后端按
      - code: meta.measured
      - text: 逐键相减的结果，前端不做任何单位换算或插值。arrays 字节由
      - code: "GET /assets/{id}/files/{role}?key=arrays"
      - text: 提供， 同一 asset_id 在本会话内只下载一次。
  - region "误差热图与点云叠加（真实数组）":
    - heading "误差热图与点云叠加（真实数组）" [level=2]
    - paragraph: "GET /assets?role=obs_view,obs_fused_geometry → GET /assets/{id}/files/{role}?key=arrays（npz 在浏览器内解码）"
    - text: 前端由真实 depth/points 计算，非后端误差场
    - button "刷新资产"
    - paragraph:
      - text: 扫描到 72 个资产（obs_view 59 个，其中含
      - code: arrays
      - text: 的 17 个；obs_fused_geometry 13 个）。后端 total=72。
    - tablist "差异视图模式":
      - tab "点云叠加（obs_fused_geometry：13）" [selected]
      - tab "深度差热图（obs_view 含 arrays：17）"
    - text: 选择真实点云资产
    - combobox "选择真实点云资产 轴与 level 来自资产 meta（axis_id / level / variant）；本页不推断它们是哪一档退化。":
      - option "asset_3367387de335d6c3dbb8（QA_PENDING）"
      - option "asset_09a5d0ee3b5f77860f02 · G03 · L1 · connected_hole_removal（QA_PENDING）"
      - option "asset_51ca427d4e61cabd7581 · G03 · L2 · connected_hole_removal（QA_PENDING）"
      - option "asset_87a4fea69e2890f25d81 · G03 · L3 · connected_hole_removal（QA_PENDING）"
      - option "asset_09bc4505110774375b5c · G03 · L4 · connected_hole_removal（QA_PENDING）" [selected]
      - option "asset_b2df149baa5084cc7fe5 · G05 · L1 · qem_decimation（QA_PENDING）"
      - option "asset_add7c0c0541ebda90610 · G05 · L2 · qem_decimation（QA_PENDING）"
      - option "asset_94c51481c6433d3502fd · G05 · L3 · qem_decimation（QA_PENDING）"
      - option "asset_14a59c0fd08e550ee746 · G05 · L4 · qem_decimation（QA_PENDING）"
      - option "asset_e41d959b105048532b4c · G08 · L1 · bump（QA_PENDING）"
      - option "asset_05692c48d601b33d3c48 · G08 · L2 · bump（QA_PENDING）"
      - option "asset_0fd0170a6f734e00a7c1 · G08 · L3 · bump（QA_PENDING）"
      - option "asset_7872f381d557909e1c66 · G08 · L4 · bump（QA_PENDING）"
    - text: 轴与 level 来自资产 meta（axis_id / level / variant）；本页不推断它们是哪一档退化。
    - figure "观测重建点 vs 同资产参考点 前端由真实 depth/points 计算，非后端误差场":
      - strong: 观测重建点 vs 同资产参考点
      - text: 前端由真实 depth/points 计算，非后端误差场
      - paragraph: 资产 asset_09bc4505110774375b5c 的 payload.points 与 payload.reference_points（单位 mm，frame=S_mm）。逐点距离由前端计算。
      - tablist "投影轴":
        - tab "等轴测" [selected]
        - tab "XY（俯视）"
        - tab "XZ（正视）"
        - tab "YZ（侧视）"
      - img "点云偏差叠加（iso）：逐点距离 6.6440 到 178.4450 mm"
      - paragraph: 色标：低（6.6440 mm）→ 高（178.4450 mm）
      - term: 总点数
      - definition: "11663"
      - term: 有效点数（point_valid 且距离有限）
      - definition: "11663"
      - term: 未绘制点数
      - definition: "0"
      - term: 本帧绘制
      - definition: "11663"
      - term: 逐点距离 均值
      - definition: 86.5308 mm
      - term: 逐点距离 p50
      - definition: 85.2921 mm
      - term: 逐点距离 p95
      - definition: 153.9295 mm
      - term: 逐点距离 最大值
      - definition: 178.4450 mm
      - term: roi=True 点数
      - definition: "11663"
      - paragraph: "参考点来自同一资产内的 `payload.reference_points`；距离是逐点欧氏范数（mm）。这是前端算式， 不是后端误差场。"
      - group: 按真实点索引列出最大的 10 个逐点距离
      - group: "后端 `meta.measured`（原样，供与前端计算值对照） { \"cell_mm\": 4.174396490867117, \"coverage_retained\": 0.19986495611073596, \"largest_hole_area_mm2\": 20649.319484611988, \"n_holes\": 1, \"points_after\": 11663, \"points_before\": 73120, \"radius_cells\": 10.75, \"radius_saturated\": 0, \"removed_area_mm2\": 20649.319484611988, \"retained_coverage\": 0.2, \"roi_quota_after\": 1 }"
    - group: 该资产 arrays 的真实键名（31 个）
  - region "U05 交互提示（真实条件触发）":
    - heading "U05 交互提示（真实条件触发）" [level=2]
    - paragraph: 计划 20.6 要求明确告知需要重新成像的情形
    - list:
      - listitem:
        - strong: 高光 / 遮挡 / U 位移动
        - text: ：属于 OPTICS/SENSOR 组轴的真实成像条件变化，需要重新成像； 页面在算子表里把 stage 原样显示，便于判断是否触碰了成像链。
      - listitem:
        - strong: G08
        - text: ：观测重建伪表面。应当在
        - code: source_role=observed
        - text: 下使用； 后端 recipe 编译结果会给出真实节点，clean/Physical 是否变化由后端决定，本页不做前端模拟。
      - listitem:
        - strong: 强度零
        - text: ：level=0 与 baseline 必须同源；用
        - code: basis_policy
        - text: 表达， 校验结果会在“校验结果”面板显示编译后的节点。
```

# Test source

```ts
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
  266 |   await expect(panel.getByRole('button', { name: '一键续跑下一批' })).toBeVisible();
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
> 331 |     await expect(table.getByText('level 0 = NA').first()).toBeVisible({ timeout: 30_000 });
      |                                                           ^ Error: expect(locator).toBeVisible() failed
  332 |   }
  333 | 
  334 |   // 未物化/无配对时必须给出真实原因，且不出现任何“L1 作为 baseline”的说法
  335 |   await expect(panel.getByText('L1').first()).toHaveCount(0);
  336 | 
  337 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  338 | });
  339 | 
```