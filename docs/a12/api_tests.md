# A12 后端 API 测试与安全证据（`synlab/api/**`）

范围：`synlab/api/**`、`tests/a12/api/**`、`tools/api_security_evidence.py`、`data/a12/reports/api_security.json`。
合同依据：执行计划第 21 节（后端 API、事件与函数合同）、21.2（任务创建与事件）、30.16（服务端权限、路径和输入限制）、验收行 A33。

## 1. 测试命令与结果

```
C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab> .venv\Scripts\python.exe -m pytest tests/a12/api -p no:cacheprovider -v
============================= test session starts =============================
platform win32 -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab
configfile: pyproject.toml
plugins: anyio-4.15.1, dash-4.4.1, platformdirs-4.12.2, zarr-3.4.0
collected 63 items

tests\a12\api\test_assets_and_paths.py .......s......                    [ 22%]
tests\a12\api\test_capabilities_and_specs.py ..........                  [ 38%]
tests\a12\api\test_events_sse.py .....                                   [ 46%]
tests\a12\api\test_jobs_and_budgets.py .....s.......                     [ 66%]
tests\a12\api\test_roles_and_isolation.py .....................          [100%]

======================= 61 passed, 2 skipped in 24.03s ========================
```

0 failed / 0 error。两条 skip 都是**环境限制或反向条件**，不是被跳过的安全检查：

| skip | 原因 | 说明 |
|---|---|---|
| `test_symlink_escape_is_refused` | 本机未提权时 `os.symlink` 抛 `OSError` | 该用例只在能创建 symlink 的主机上执行真实越界验证；`assert_within` 的 resolve 语义仍由 `test_safe_join_and_assert_within_block_escapes` 覆盖 |
| `test_jobs_capability_gate_is_fail_closed` | 本 checkout 中 `mothers/fracture/degrade/diagnostics` 全部可导入 | 该用例只在能力缺失时才有意义；503 路径本身在代码中 fail-closed，且 `POST /previews` 的同类门由 `test_previews_are_a_job_creation_route_and_are_gated` 覆盖 |

按文件统计（`--collect-only`，本轮新增前为 53 项，新增后 63 项）：

```
tests/a12/api/test_assets_and_paths.py: 14
tests/a12/api/test_capabilities_and_specs.py: 10
tests/a12/api/test_events_sse.py: 5
tests/a12/api/test_jobs_and_budgets.py: 13
tests/a12/api/test_roles_and_isolation.py: 21
```

## 2. 本轮最小修复清单

原则：**没有放宽任何真实安全检查**。所有被拒的请求仍然是 403/404/409/422，只是返回了正确的结构化错误码。

| # | 文件 | 判定 | 修复 |
|---|---|---|---|
| 1 | `synlab/api/integrity.py` | 实现错 | `api_file_integrity` 台账表只在 `AppContext`（`tables.ensure_api_schema`）里建；持裸 `AssetStore` 的调用方（worker、测试、worker 提交后立即记账）查询时 `no such table`。新增 `ensure_ledger()` + `LEDGER_DDL`，在 `record_integrity`/`resolve_file`/`_ledger_row` 入口幂等建表（`CREATE TABLE IF NOT EXISTS`，DDL 与 `tables.py` 一致）。不触碰 `synlab/storage/**`。 |
| 2 | `synlab/api/deps.py` | 实现错 | `ExportEnvelope.adapter` 原为 `Literal["manifest","obs_pack","feature_bundle","oracle_truth"]`，Pydantic 在进入 handler 前就把 `truth_pack`/`gt_oracle` 判成 422，**把角色拒绝掩盖成参数错误**。改为受限 `str`（`min_length=1, max_length=64`），让角色门先回答 403。 |
| 3 | `synlab/api/routers/governance.py` | 实现错 | `POST /exports` 原顺序是「白名单 422 → 角色 403」。改为**先 `require_oracle_adapter`（403 `ORACLE_EXPORT_FORBIDDEN`）后白名单（422 `UNSUPPORTED_ADAPTER`）**，与 30.16「deployment_client 不可请求 oracle export」一致；`adapter` 常量改为引用 `API_CODE_UNSUPPORTED_ADAPTER`。 |
| 4 | `synlab/api/deps.py` | 实现错 | `SpecEnvelope.kind` 原为 `Literal`，未知 kind 被请求体校验吞成无 `error` 对象的 422。改为 `str`（`SPEC_KINDS` 仅作文档常量），由 `synlab/api/specs.validate_spec` 回答 422 `BAD_REQUEST`（含合法 kind 列表）。 |
| 5 | `synlab/api/routers/jobs.py`（SSE） | 实现错 | 三处：① `Last-Event-ID` 非数字时 `int()` 抛 `ValueError` → 改用 `isdigit()` 并在**开始流式输出之前**判定；② 未知 run 的 404：`run` 查询本来就在 `StreamingResponse` 之前，但错误解析顺序被前面的 header 异常打断，现保证 run 404 先于 header 400 判定；③ **游标推进**：`events_since(cursor, limit=limit)` 用的是共享事件日志的全局 seq，`follow=false` 时只处理一批就关闭，若该批被其它 run 的事件占满，本 run 的历史会被静默截断。改为 `page_size = max(200, min(limit, MAX_EVENT_PAGE))` 的服务端页大小 + `drain()` 跨批推进到日志末尾；`limit` 只决定客户端拿到多少自己的事件。 |
| 6 | `synlab/api/app.py` | 实现错（缺结构化错误） | 路由层失败（未匹配路径、方法不允许）原本返回 FastAPI 默认 `{"detail": ...}`，与 30.16「拒绝操作给具体结构化错误」不符。新增 `StarletteHTTPException` 处理器 + `HTTP_CODE_BY_STATUS`，统一成 `{ok:false,error:{code,...}}`（不泄漏服务器路径）。 |
| 7 | `tests/a12/api/_sse_client.py` | 测试脚手架错 | starlette 1.7 + httpx2 的 `ASGITransport` **只有异步上下文管理器**（`httpx2.ASGITransport` 无 `__enter__`），且 `TestClient` 会把整条响应缓冲到 ASGI app 返回为止——`follow=true` 的 SSE 永不返回，两者都读不到流。改为直接驱动 ASGI：阻塞 portal + 缓冲 channel 增量读取，客户端可像浏览器一样发 `http.disconnect`；并复用 `app.build_middleware_stack()`（设置 `scope["app"]`）保证异常处理器真实生效，状态码/错误体与真实客户端一致。 |
| 8 | `tests/a12/api/test_events_sse.py` | 测试错 | ① `_parse_sse` 未排除 `stream_end` 传输哨兵（它不是 job 事件）；② 心跳用例读 4 行就在第一个事件帧返回，从未读到心跳，改为有界窗口 `read_for(1.5)` 并断言「客户端挂断前流仍开着」；③ 「不得出现假百分比」断言写成了「任何 `data:` 行都不能含 `progress` 字样」，而信封**永远**带 `progress` 键（诚实值 `null`）。改为断言心跳行不含 `progress`、所有事件 `progress is None`、`data:` 行不含 `%`。 |
| 9 | `tests/a12/api/test_assets_and_paths.py` | 测试错 | `resolve_file` 是面向 HTTP 的解析器，未知 key 抛 `ApiProblem(404,"NOT_FOUND")` 而非 `SynLabError`。改断言两者皆可，并显式校验 `code == "NOT_FOUND"`、消息含 key、异常对象上**不存在** `path` 属性（未注册 key 绝不能变成文件路径）。 |
| 10 | `synlab/api/security.py` | 实现错（新增守卫 helper） | 新增 `require_job_control()` / `require_training_start()`；只新增判断，未放宽任何既有判断。 |
| 11 | `synlab/api/routers/jobs.py`、`learning.py`、`cameras.py` | 实现错（**服务端角色缺口**） | `POST /previews`（真实建 job）、`POST /pools`、`POST /diagnostics/runs`、`POST /episodes/{id}/reset｜step`、`POST /camera-profiles` 原本**没有角色门**：`deployment_client` 会话可以真的入队 job（只是拿到 404/422，说明请求已经进到业务逻辑）。现于每条**入队/驱动类**路由最前面调用上述 helper；`training` 两处原为内联 `if not policy.can_start_training`，统一改用同一 helper。只读路由（`GET /jobs`、`/assets`、`/audits`、`/pools`、`/camera-profiles`、`/training/runs`、`/diagnostics/runs`、`/releases`、`/capabilities`、`/stages`）对 deployment 仍为 200。 |
| 12 | `tests/a12/api/test_events_sse.py` | 新增回归 | 新增 `test_events_of_one_run_are_never_diluted_by_other_runs`：先造 4 个其它 run 污染共享事件日志，再验证目标 run 的事件不混入他 run、seq 单调唯一，且 `limit=1`（远小于本 run 事件数）时仍能跨批取全。这个用例正是发现第 5 ③ 项的路径。 |
| 13 | `tests/a12/api/test_roles_and_isolation.py` | 新增回归 | 新增 `test_deployment_cannot_reach_any_enqueuing_route`（7 条入队路由参数化，全部必须 403 `ROLE_FORBIDDEN`）、`test_previews_are_a_job_creation_route_and_are_gated`、`test_read_only_routes_stay_available_to_deployment`（确认新门没有过度封锁）。 |

`synlab/storage/**`、`synlab/jobs/**`、`synlab/schemas/**`、`synlab/cli.py`、`synlab/qc/**`、`synlab/pipeline.py`、`frontend/**` **未修改**。

> 说明：第 1–6、10、11 项都是收紧或修正拒绝语义。唯一改的是两处类型标注（`ExportEnvelope.adapter` / `SpecEnvelope.kind`）：它们不再在 Pydantic 层拦截，而是交给域层回答**更具体**的结构化错误（403 `ORACLE_EXPORT_FORBIDDEN` / 422 `BAD_REQUEST`）。被拒绝的请求集合没有变小 —— `adapter` 仍受角色门 + `EXPORT_ADAPTERS` 白名单双重约束，`kind` 仍受 `specs.MODELS` 约束。

## 3. 真实路由清单（读自 `synlab/api/routers/*.py` 的装饰器）

由 `tools/api_security_evidence.py` 用 AST 从源码解析，并与运行中 app 的 OpenAPI 路径交叉核对：
`declared_not_mounted` 为空（每条声明都真的挂上了），`mounted_not_declared` 只含下面两条 app 级路径。

共 **41 条**路由（GET 23 / POST 18）：`assets.py` 3、`governance.py` 8、`jobs.py` 9、`learning.py` 13、`meta.py` 5、`cameras.py` 3。

| 方法 | 路径（前缀 `/api/synlab`） | 来源 | 声明状态 |
|---|---|---|---|
| GET | `/assets` | assets.py `get_assets` | 200 |
| GET | `/assets/{asset_id}` | assets.py `get_asset` | 200 |
| GET | `/assets/{asset_id}/files/{role}` | assets.py `get_asset_file` | 200 |
| GET | `/audits` | governance.py `list_audits` | 200 |
| POST | `/audits` | governance.py `post_audits` | **202** |
| GET | `/audits/{audit_id}` | governance.py `get_audit` | 200 |
| POST | `/budgets` | meta.py `post_budgets` | 200 |
| GET | `/camera-profiles` | cameras.py `list_camera_profiles` | 200 |
| POST | `/camera-profiles` | cameras.py `create_camera_profile` | **201** |
| GET | `/camera-profiles/{profile_id}` | cameras.py `get_camera_profile` | 200 |
| GET | `/capabilities` | meta.py `get_capabilities` | 200 |
| GET | `/diagnostics/runs` | learning.py `list_diagnostics_runs` | 200 |
| POST | `/diagnostics/runs` | learning.py `post_diagnostics_runs` | **202** |
| GET | `/diagnostics/runs/{diagnostics_run_id}` | learning.py `get_diagnostics_run` | 200 |
| GET | `/episodes/{episode_id}` | learning.py `get_episode` | 200 |
| POST | `/episodes/{episode_id}/reset` | learning.py `post_episode_reset` | 200 |
| POST | `/episodes/{episode_id}/step` | learning.py `post_episode_step` | 200 |
| POST | `/exports` | governance.py `post_exports` | **202** |
| GET | `/exports/{export_id}` | governance.py `get_export` | 200 |
| GET | `/jobs` | jobs.py `get_jobs` | 200 |
| POST | `/jobs` | jobs.py `post_jobs` | **202** |
| GET | `/jobs/{job_id}` | jobs.py `get_job` | 200 |
| POST | `/jobs/{job_id}/cancel` | jobs.py `post_cancel` | 200 |
| POST | `/jobs/{job_id}/pause` | jobs.py `post_pause` | 200 |
| POST | `/jobs/{job_id}/resume` | jobs.py `post_resume` | 200 |
| POST | `/jobs/{job_id}/retry` | jobs.py `post_retry` | **202** |
| GET | `/pools` | learning.py `list_pools` | 200 |
| POST | `/pools` | learning.py `post_pools` | **202** |
| GET | `/pools/{pool_id}` | learning.py `get_pool` | 200 |
| POST | `/previews` | jobs.py `post_previews` | **202** |
| GET | `/registry/{kind}` | meta.py `get_registry_kind` | 200 |
| GET | `/releases` | governance.py `list_releases` | 200 |
| POST | `/releases` | governance.py `post_releases` | **201** |
| GET | `/releases/{release_id}` | governance.py `get_release` | 200 |
| GET | `/runs/{run_id}/events` | jobs.py `get_run_events` | 200（SSE，`text/event-stream`） |
| POST | `/specs/validate` | meta.py `post_specs_validate` | 200（`ok=false` 表示 spec 被拒） |
| GET | `/stages` | meta.py `get_stages` | 200 |
| GET | `/training/runs` | learning.py `list_training_runs` | 200 |
| POST | `/training/runs` | learning.py `post_training_runs` | **202** |
| GET | `/training/runs/{training_run_id}` | learning.py `get_training_run` | 200 |
| POST | `/training/runs/{training_run_id}/resume` | learning.py `post_training_resume` | **202** |

app 级（不在 `routers/*.py` 装饰器里）：

| 方法 | 路径 | 来源 | 说明 |
|---|---|---|---|
| GET | `/health` | `app.py:create_app` | 存活探针，含 `research_routes_mounted`；不含敏感路径 |
| GET | `/research/assets/{asset_id}/truth` | `assets.py:research_router`，由 `create_app` 按角色挂载 | 仅 `researcher` 会话挂载；其余角色挂载**拒绝占位**路由 |

SSE 说明：`GET /runs/{id}/events` 支持 `after_seq`、`Last-Event-ID` 头、`follow=false`（回放后关闭）、`poll_ms`、`limit`；事件信封为
`{seq, revision, run_id, job_id, type, state, progress, metrics_ref, error_ref, message, created_at, payload}`（21.2 形状）。
`stream_end` 是关闭非 follow 流的传输哨兵，不是 job 事件；心跳是 `: heartbeat` 注释行，**不是**假进度事件。

## 4. 角色矩阵（服务端强制，UI 隐藏不算授权）

角色策略来自 `synlab/api/security.py`；矩阵由真实 `/capabilities` 请求读出：

| 策略位 | researcher | operator | deployment_client |
|---|---|---|---|
| `can_read_truth` | ✅ | ❌ | ❌ |
| `can_read_research` | ✅ | ❌ | ❌ |
| `can_read_ancestry` | ✅ | ❌ | ❌ |
| `truth_routes_mounted` | ✅ | ❌ | ❌ |
| `can_request_oracle_export` | ✅ | ❌ | ❌ |
| `can_control_jobs` | ✅ | ✅ | ❌ |
| `can_create_release` | ✅ | ✅ | ❌ |
| `can_audit` | ✅ | ✅ | ❌ |
| `can_start_training` | ✅ | ✅ | ❌ |

行为矩阵（每条都断言在服务端，见 `tests/a12/api/test_roles_and_isolation.py` 与证据文件）：

| 请求 | researcher | operator | deployment_client |
|---|---|---|---|
| `GET /research/assets/{id}/truth` | 200 | 403 `TRUTH_ROUTE_UNMOUNTED` | 403 `TRUTH_ROUTE_UNMOUNTED` |
| `GET /assets/{id}/truth`、`GET /truth/**` | 404（无此路由；真值只经研究入口） | 403 `TRUTH_ROUTE_UNMOUNTED` | 403 `TRUTH_ROUTE_UNMOUNTED` |
| `GET /assets?role=clean_truth` | 200 | 403 `ROLE_FORBIDDEN` | 403 `ROLE_FORBIDDEN` |
| `GET /assets`（默认过滤） | 全部角色 | 仅部署安全 role | 仅部署安全 role |
| `GET /assets/{id}`（研究 role 资产） | 200 | 403 `ROLE_FORBIDDEN` | 403 `ROLE_FORBIDDEN` |
| `GET /assets/{id}`（ancestry） | 完整 | `ancestry=[]` + `ancestry_hidden=true` | 同 operator |
| `POST /exports` `adapter=oracle_truth｜truth_pack｜gt_oracle` | 通过角色门（缺 release → 404） | 403 `ORACLE_EXPORT_FORBIDDEN` | 403 `ORACLE_EXPORT_FORBIDDEN` |
| `POST /exports` `adapter=manifest` | 202/404 | 202/404 | 202/404（非 oracle 不误伤） |
| `POST /jobs`、`POST /previews` | 202 | 202 | 403 `ROLE_FORBIDDEN` |
| `POST /pools` | 202/404 | 202/404 | 403 `ROLE_FORBIDDEN` |
| `POST /diagnostics/runs` | 202/422 | 202/422 | 403 `ROLE_FORBIDDEN` |
| `POST /episodes/{id}/reset｜step` | 200 | 200 | 403 `ROLE_FORBIDDEN` |
| `POST /camera-profiles` | 201/422 | 201/422 | 403 `ROLE_FORBIDDEN` |
| `GET /jobs` | 200 | 200 | 200（只读列表允许） |
| `POST /jobs/{id}/pause｜resume｜cancel｜retry` | 200/202 | 200/202 | 403 `ROLE_FORBIDDEN` |
| `POST /releases` | 201/409 | 201/409 | 403 `ROLE_FORBIDDEN` |
| `POST /training/runs`、`POST /training/runs/{id}/resume` | 202 | 202 | 403 `ROLE_FORBIDDEN` |
| `X-SynLab-Role` 头 ≠ 服务端角色 | 403 `ROLE_MISMATCH` | 403 `ROLE_MISMATCH` | 403 `ROLE_MISMATCH` |
| `X-SynLab-Workspace` 头 ≠ 会话 workspace | 403 `WORKSPACE_FORBIDDEN` | 同 | 同 |
| `X-SynLab-Session` 非法格式 | 400 | 400 | 400 |
| 跨 workspace 读资产 / 用他 workspace 资产建任务 | 403 `WORKSPACE_FORBIDDEN` | 同 | 同 |

只读路由对三种角色均为 200，且**不因角色不同而伪造数据**（`GET /jobs`、`/assets`、`/audits`、`/pools`、`/camera-profiles`、`/training/runs`、`/diagnostics/runs`、`/releases`、`/capabilities`、`/stages`、`/registry/{kind}`）；
研究专属字段对非研究角色是**服务端剥离**：`GET /assets/{id}` 给 `ancestry=[]` + `ancestry_hidden=true`，`GET /audits/{id}`、`GET /pools/{id}`、`GET /releases/{id}`、`GET /diagnostics/runs/{id}`、`GET /episodes/{id}` 去掉 truth/research 段落并标注隐藏标志。

未实现或降级的路由（明确列出；**没有一条返回假数据**）：

1. **`GET /research/assets/{id}/truth` 的数组真值载荷未实现。** 能力探测显示 `truth` 模块为
   `DEPENDENCY_CAPABILITY_MISSING`，因此该路由只返回资产记录中真实存在的 typed 标签（role/schema/unit/frame/qa/meta/ancestry/lineage/split/interpretation_hash）与逐文件完整性；
   `array_keys` 仅在 `include_arrays=true` 且 `load_arrays` 真实成功时才有内容，失败时返回 `[]`，**不会回填任何真值像素或标签**。
2. **`truth` 能力缺失状态如实上报**：`GET /capabilities` 的 `missing=["truth"]`、`modules.truth.status="DEPENDENCY_CAPABILITY_MISSING"` 并带真实错误原因。
3. **依赖能力的路由是能力门，不是假成功**：`POST /pools`、`POST /training/runs`、`POST /diagnostics/runs`、`POST /episodes/*`、`POST /camera-profiles` 在对应模块不可用时返回
   **503 `DEPENDENCY_CAPABILITY_MISSING`**（附 `capability` 真因）并且不写入任何行；本 checkout 中这些模块都可导入，所以实际返回 202。
4. **未运行的 run 不生成结果**：`GET /audits/{id}` 返回 `status="NOT_RUN"`；`GET /exports/{id}` 返回 `status="NOT_RUN"` 并注明「不返回占位包」；
   `GET /training/runs/{id}` 在无结果时给 `not_run_reason`（"未运行的训练不生成任何 loss 曲线"）、`metrics={}`、`curves=[]`；
   `GET /diagnostics/runs/{id}` 同理给 `not_run_reason`、`curves=[]`、`queries=[]`；`POST /episodes/{id}/reset` 返回 `status="RESET_PENDING"`、`observation={"revealed": false}`（未揭示的帧不进 state）。
5. **无 `GET /exports` 列表路由。** 21.1 只规定 `POST /exports` 与状态查询；导出列表未实现（请求会得到 404 `NOT_FOUND` 的结构化错误，而不是空列表伪造"没有导出"）。导出状态经 `GET /exports/{export_id}` 查询。
6. **21.1 表中未出现的增量路由**（如「诊断 run 更新」）本实现未提供。
7. `/assets/{id}/files/{role}` 一次只服务一个 payload key（`?key=`），缺省按确定性优先级 `glb.bin > mesh.bin > preview.bin > data.bin > arrays > meta` 选择；未知 key 返回 404，role 不在白名单返回 403 `FILE_ROLE_NOT_SERVABLE`，role 白名单但与资产注册 role 不符返回 409 `FILE_ROLE_MISMATCH`。

## 5. 真实证据脚本与 A33 验收文件

```
C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab> .venv\Scripts\python.exe tools\api_security_evidence.py
evidence -> C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\data\a12\reports\api_security.json
  PASS  deployment_truth_denied
  PASS  operator_truth_denied
  PASS  path_traversal_denied
  PASS  unregistered_file_role_denied
  PASS  oracle_export_denied
  PASS  idempotency_conflict_409
  PASS  sse_seq_monotonic
  PASS  workspace_isolation
ok=True  observations=31  routes=41  elapsed=4.72s
```

脚本行为：真实 `create_app`（researcher / operator / deployment_client / 另一 workspace 的 researcher 四个会话）+ 真实落盘 `AssetStore`
（提交一个真实 100 mm 母体网格立方体并记录 sha256 完整性）+ 真实 HTTP 请求；SSE 用与测试相同的直连 ASGI 读取器。
每个 bool 都要求**观察到预期的拒绝与结构化错误码**才为 true，否则为 false 并把原因写进 `observations`。
所以 **`ok` 恒等于 8 项实测的合取**，全为真实请求结果，没有任何预填值。

`data/a12/reports/api_security.json` 关键字段：

```json
{
  "ok": true,
  "metrics": {
    "deployment_truth_denied": true,
    "operator_truth_denied": true,
    "path_traversal_denied": true,
    "unregistered_file_role_denied": true,
    "oracle_export_denied": true,
    "idempotency_conflict_409": true,
    "sse_seq_monotonic": true,
    "workspace_isolation": true
  },
  "observations": [ ... 31 条真实请求/响应 ... ],
  "route_inventory": { "count": 41, "declared_not_mounted": [], ... },
  "contract": { "<metric>": "<对应 21.1/21.2/30.16 条款>" }
}
```

各指标的关键实测样本（摘自 `observations`）：

| 指标 | 实测 |
|---|---|
| `deployment_truth_denied` | `/health` → `research_routes_mounted=false`；`/research/assets/{id}/truth`、`/assets/{id}/truth`、`/truth/anything` → **403 `TRUTH_ROUTE_UNMOUNTED`** |
| `operator_truth_denied` | `/health` → `research_routes_mounted=false`；研究真值路由 → **403 `TRUTH_ROUTE_UNMOUNTED`**；同时 `can_control_jobs=true` 而 `can_read_truth=false` |
| `path_traversal_denied` | `files/../../../../etc/passwd`、`?key=../../../meta.json`、300 字符注入 key、`assets/../../etc/passwd` → 全部拒绝（404 `NOT_FOUND`）且响应体不含 store 路径或 `root:` |
| `unregistered_file_role_denied` | 未知 role → **403 `FILE_ROLE_NOT_SERVABLE`**；`nope_%2e%2e` → 403；白名单 role 与资产不符 → **409 `FILE_ROLE_MISMATCH`**；对照组：合法 `(mother_mesh, arrays)` → 200 且 `X-SynLab-Hash-Verified: recorded` |
| `oracle_export_denied` | deployment + `oracle_truth`/`truth_pack`/`gt_oracle` → **403 `ORACLE_EXPORT_FORBIDDEN`**；对照组 `manifest` → 404（缺 release，说明未过度封锁）；researcher + `oracle_truth` → 404（过角色门后在真实缺失的 release 上失败，本版本不伪造导出件） |
| `idempotency_conflict_409` | 首次 → 202；同键同 payload → 202 且 `idempotent_replay=true`、`run_id` 相同；同键不同 payload → **409 `IDEMPOTENCY_CONFLICT`** |
| `sse_seq_monotonic` | 回放 → 200 `text/event-stream`，seq `[2,3,4,5]` 严格单调唯一；`Last-Event-ID: 4` → 仅 `[5]`；`Last-Event-ID: abc` → **400 `BAD_REQUEST`**；空闲 follow 流 → 8 条 `: heartbeat` 注释、`fabricated_progress=0`、客户端未挂断前流保持打开 |
| `workspace_isolation` | 他 workspace `GET /assets` → `count=0` 且 `workspace="ws-evidence-other"`；跨 workspace 读资产 → **403 `WORKSPACE_FORBIDDEN`**；跨 workspace 资产建任务 → 403；`X-SynLab-Workspace` 头切范围 → 403 |
