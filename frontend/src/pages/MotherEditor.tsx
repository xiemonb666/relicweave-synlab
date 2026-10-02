/**
 * U02 母体编辑 `/synlab/mothers/new`（计划 20.3）。
 *
 * 真实调用：`GET /registry/{vessel,material,layer_combo}`、`POST /specs/validate`、
 * `POST /budgets`、`POST /previews`（stage=mother）、`GET /assets`（mother_mesh / display_lod）、
 * `GET /jobs?run_id=`（预览任务状态）、`GET /runtime`-类能力来自 `GET /capabilities`。
 *
 * 说明：计划 20.3 的“尺寸 mm / 轮廓控制点 / 壁厚 / 足圈-耳-柄-流 / 非对称 / 复杂度”属于
 * **器物参数模型**（registry 里 `register_vessel(param_model=...)` 的 JSONSchema）。本仓库当前
 * registry 为空，因此这些字段没有后端来源；页面据此显示阻塞，而不是在 js 里复制一份范围表。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { RegistryParamPanel } from '../components/RegistryParamPanel';
import { SceneViewport } from '../components/SceneViewport';
import { SurfaceTagView } from '../components/SurfaceTagView';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { Badge, BlockedState, EmptyState, PageHeader, SectionCard } from '../components/states';
import { getCapabilities, getRegistry } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues, stageCapabilities } from '../lib/caps';
import type { AssetRecord } from '../api/types';
import { useAppState } from '../state/app-state';

/**
 * 显式字段名逐一对应 `synlab/schemas/spec.py`（`extra="forbid"`），
 * 枚举取值来自后端 Pydantic 模型；服务端仍是最终判定（前端不做第二套校验）。
 */
const GENERATION_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: '器物与材料（dataset / sampling）',
    hint: 'ID 是否注册由后端 registry 判定：POST /specs/validate 会返回 registry_check 的真实结论。',
    children: [
      { kind: 'stringList', path: 'dataset.vessel_ids', label: '器物 ID', hint: '例如 V01；未注册的 ID 会被后端拒绝' },
      { kind: 'stringList', path: 'dataset.material_ids', label: '材料 ID', hint: '例如 M01' },
      { kind: 'stringList', path: 'dataset.layer_combo_ids', label: '层组合 ID', hint: '例如 L01（可留空）' },
      { kind: 'stringList', path: 'dataset.pattern_ids', label: '纹样 ID', hint: 'U03 使用；本页可先留空' },
      { kind: 'number', path: 'dataset.target_mothers', label: '目标独立母体数', integer: true, min: 1, unit: '个' },
      { kind: 'number', path: 'dataset.target_fragments_estimate', label: '预计碎片数', integer: true, min: 1, unit: '片' },
      { kind: 'string', path: 'sampling.method', label: '采样方法', enumValues: ['latin_hypercube', 'sobol', 'quota_uniform'] },
      { kind: 'string', path: 'sampling.quota_policy', label: '配额策略', enumValues: ['registry_balanced', 'uniform', 'explicit'] },
      { kind: 'number', path: 'sampling.seed_stride', label: '种子步长', integer: true, min: 1 },
    ],
  },
  {
    kind: 'group',
    label: '断裂与尺寸范围（fracture）',
    hint: 'min_feature_wavelength_mm 必须 ≤ 3 mm（后端模型约束）；target_piece_range 需满足 2 ≤ lo ≤ hi。',
    children: [
      { kind: 'string', path: 'fracture.backend', label: '断裂后端 ID', hint: '应由 /registry/fracture_backend 提供；当前为空时请手动填写并由服务端校验' },
      { kind: 'numberTuple', path: 'fracture.target_piece_range', label: '目标片数区间', length: 2, integer: true, unit: '片' },
      { kind: 'number', path: 'fracture.min_feature_wavelength_mm', label: '最小特征波长', unit: 'mm', min: 0 },
      { kind: 'number', path: 'fracture.shared_surface_max_error_mm', label: '共享面最大误差', unit: 'mm', min: 0 },
      { kind: 'number', path: 'fracture.rough_amplitude_mm', label: '粗糙幅度下界', unit: 'mm', min: 0, hint: '完整区间请在高级 JSON 区写 [lo, hi]' },
      { kind: 'number', path: 'fracture.max_attempts', label: '最大尝试次数', integer: true, min: 1 },
      { kind: 'boolean', path: 'fracture.keep_parent_history', label: '保留父级历史' },
    ],
  },
  {
    kind: 'group',
    label: '纹样与几何（pattern / physical）',
    children: [
      { kind: 'string', path: 'pattern.height_policy', label: '高度策略', enumValues: ['relief', 'engrave', 'none'] },
      { kind: 'boolean', path: 'pattern.periodic_azimuth', label: '方位角周期' },
      { kind: 'boolean', path: 'pattern.geometry_before_fracture', label: '断裂前几何化' },
      { kind: 'string', path: 'pattern.antialias', label: '抗锯齿', enumValues: ['analytic_or_mipmap', 'analytic', 'mipmap'] },
      { kind: 'boolean', path: 'physical.preserve_clean_assets', label: '保留 clean 资产' },
    ],
  },
  {
    kind: 'group',
    label: '观测与资源（observation / resources）',
    children: [
      { kind: 'string', path: 'observation.input_profile', label: '输入档位', enumValues: ['PHONE_RGB', 'SENSOR_PROXY', 'SENSOR_UPPER_BOUND'] },
      { kind: 'string', path: 'observation.renderer', label: '渲染器', enumValues: ['auto', 'software_rasterizer', 'blender'] },
      { kind: 'number', path: 'observation.views_per_fragment', label: '每片视角数', integer: true, min: 1 },
      { kind: 'number', path: 'observation.image_long_edge_px', label: '图像长边', unit: 'px', integer: true, min: 32 },
      { kind: 'number', path: 'resources.cpu_workers', label: 'CPU worker 数', integer: true, min: 1 },
      { kind: 'number', path: 'resources.cpu_rss_budget_gb', label: 'CPU RSS 预算', unit: 'GB', min: 0 },
      { kind: 'number', path: 'resources.gpu_budget_gb', label: 'GPU 显存预算', unit: 'GB', min: 0 },
    ],
  },
  {
    kind: 'group',
    label: '全局元数据',
    children: [
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.v3'] },
      { kind: 'string', path: 'data_scope', label: '数据口径', enumValues: ['SYNTHETIC', 'REAL'] },
      {
        kind: 'string',
        path: 'release_profile',
        label: '发布 profile',
        enumValues: [
          'SANDBOX_CORE',
          'PILOT',
          'CORE_COVERAGE',
          'SCALE_10K',
          'SCALE_50K',
          'SCALE_100K',
          'CALIBRATED_PHONE',
          'RESEARCH_EVIDENCE',
        ],
        hint: '取值来自后端 ReleaseProfile；release 页会用 PROFILE_GATES 的真实 gate 判定',
      },
      { kind: 'string', path: 'experiment_purpose', label: '实验用途', enumValues: ['SANDBOX', 'DEVELOPMENT', 'CONFIRMATION'] },
      { kind: 'number', path: 'master_seed', label: 'master seed', integer: true },
      { kind: 'boolean', path: 'implementation.require_poc_before_custom', label: '自研前需 PoC 证据' },
    ],
  },
];

const INITIAL_SPEC: FormValue = {
  schema: 'synlab.v3',
  data_scope: 'SYNTHETIC',
  release_profile: 'SANDBOX_CORE',
  experiment_purpose: 'DEVELOPMENT',
  master_seed: 20261001,
  dataset: {
    target_mothers: 1,
    target_fragments_estimate: 8,
    shape_lineage_split: { train: 0.8, dev: 0.1, confirm: 0.1 },
    vessel_ids: ['V01'],
    material_ids: ['M01'],
    layer_combo_ids: ['L01'],
    pattern_ids: ['PAT01'],
  },
  sampling: { method: 'latin_hypercube', quota_policy: 'registry_balanced', seed_stride: 1 },
  fracture: { backend: 'rough_shared_cut' },
  implementation: { require_poc_before_custom: false },
};

export function MotherEditorPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const vessels = useResource((signal) => getRegistry('vessel', {}, signal), []);
  const materials = useResource((signal) => getRegistry('material', {}, signal), []);
  const layers = useResource((signal) => getRegistry('layer_combo', {}, signal), []);
  const [displayAsset, setDisplayAsset] = useState<AssetRecord | null>(null);
  const [meshAssetId, setMeshAssetId] = useState<string | null>(null);

  const motherIssues = capabilityIssues(capabilities.data ?? null, stageCapabilities(capabilities.data ?? null, 'mother', ['mothers']));

  return (
    <>
      <PageHeader
        title="母体编辑"
        plan="U02 · 计划 20.3"
        summary="编辑参数化配方 → 服务端校验 → 低成本预览任务 → 返回 water-tight/volume/thickness 与错误 → 保存合格 draft asset。预览不会自动成为发布数据。"
        actions={
          <div className="row">
            <Badge tone="info">权威几何：mm / Z-up</Badge>
            <Badge tone="neutral">展示 GLB：m / Y-up</Badge>
          </div>
        }
      />

      <SectionCard
        title="器物参数模型（registry）"
        subtitle="GET /registry/vessel · /registry/material · /registry/layer_combo —— 20.3 的尺寸/壁厚/轮廓控制点字段来源"
      >
        <div className="grid3">
          {[
            { label: '器物 vessel', data: vessels },
            { label: '材料 material', data: materials },
            { label: '层组合 layer_combo', data: layers },
          ].map((item) => (
            <div key={item.label}>
              <h3>
                {item.label}
                <Badge tone={item.data.data && item.data.data.count > 0 ? 'ok' : 'warn'}>
                  {item.data.data?.count ?? '—'} 条
                </Badge>
              </h3>
              {item.data.status === 'loading' ? <p className="muted">读取中…</p> : null}
              {item.data.data && item.data.data.count === 0 ? (
                <p className="muted small">empty_kinds={item.data.data.empty_kinds.join(', ') || '—'}（后端未注册参数模型）</p>
              ) : null}
              {item.data.data && item.data.data.count > 0 ? (
                <ul className="chips">
                  {item.data.data.entries.map((entry) => (
                    <li key={entry.id}>
                      <Badge tone="neutral">
                        {entry.id} {entry.version ? `v${entry.version}` : ''}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
        </div>

        {vessels.data && vessels.data.count === 0 ? (
          <BlockedState
            title="器物参数表单不可用：registry 未注册"
            code="REGISTRY_EMPTY"
            reason={
              <>
                计划 20.3 要求的「尺寸 mm / 轮廓控制点 / 壁厚 / 足圈-耳-柄-流 / 非对称 / 复杂度」由器物的
                <code className="mono"> param_model </code>
                决定，只有 <code className="mono">GET /registry/vessel</code> 返回条目时才有真实字段与取值范围。
                当前后端返回 0 条，前端**不会**复制一份范围表来填空。
              </>
            }
            items={[
              { label: 'registry 指纹', value: <span className="mono">{vessels.data.registry_fingerprint}</span> },
              { label: '后端说明', value: vessels.data.note },
              { label: '降级路径', value: '本页仍可用显式字段构造 synlab.v3 spec，并让服务端校验；几何预览需要 mothers 能力。' },
            ]}
          />
        ) : null}
      </SectionCard>

      <div className="threecol">
        <div className="threecol__left">
          <AssetBrowser
            title="派生展示资产（display_lod_glb）"
            fixedRoles={['display_lod_glb']}
            selectable="single"
            selected={displayAsset ? [displayAsset.asset_id] : []}
            onSelectAssets={(assets) => {
              setDisplayAsset(assets[0] ?? null);
              app.setSelectedDisplayAssets(assets.map((item) => item.asset_id));
            }}
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={10}
            emptyReason="还没有派生过展示 LOD（role=display_lod_glb）。它由 display_lod 任务产出，需要 trimesh 环境能力。"
          />
          <AssetBrowser
            title="权威母体 mesh（mother_mesh）"
            fixedRoles={['mother_mesh']}
            selectable="single"
            selected={meshAssetId ? [meshAssetId] : []}
            onSelect={(ids) => setMeshAssetId(ids[0] ?? null)}
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={10}
            emptyReason="本工作区还没有 mother_mesh 资产。权威高精度 mesh 不会整份塞进浏览器，只在这里列出 metadata。"
          />
        </div>

        <div className="threecol__center">
          <SceneViewport asset={displayAsset} title="母体三维视口（派生展示 GLB）" height={380} />
          <SectionCard title="U02 三维能力对照（真实状态）" subtitle="哪些控件有真实数据、哪些没有">
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">计划要求</th>
                  <th scope="col">当前实现</th>
                  <th scope="col">数据来源 / 原因</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">旋转 / 缩放 / 重置</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>OrbitControls + 重置视角按钮</td>
                </tr>
                <tr>
                  <th scope="row">线框</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>材质 wireframe（仅展示状态）</td>
                </tr>
                <tr>
                  <th scope="row">剖切平面</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>three.js clipping plane，按 mm 读数；不回写权威实体</td>
                </tr>
                <tr>
                  <th scope="row">量尺（mm）</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>display_to_authority 换算 + 100 mm 立方体自检</td>
                </tr>
                <tr>
                  <th scope="row">内外壁颜色 / 厚度热图</th>
                  <td>
                    <Badge tone="ok">内外壁：已实现</Badge> <Badge tone="warn">厚度：无数据</Badge>
                  </td>
                  <td>
                    内外壁/口沿/足/底来自权威 <code className="mono">mother_mesh</code> 的真实逐面数组{' '}
                    <code className="mono">mesh.face__surface_tag</code>（名称取 meta.surface_tag_names），在下方“真实面属性视图”里着色；
                    厚度场不在该资产的数组里，因此显示“无厚度数据”并列出真实可得的量（面标签 / 法向 / 到轴距离），不编造厚度。
                  </td>
                </tr>
              </tbody>
            </table>
          </SectionCard>
        </div>

        <div className="threecol__right">
          {motherIssues.length > 0 ? (
            <BlockedState
              title="母体阶段被后端能力阻塞"
              code={motherIssues[0].status}
              reason={describeIssues(motherIssues)}
              items={[
                { label: '阶段', value: 'mother（create_mother + audit_mother）' },
                {
                  label: '缺少入口函数',
                  value: <span className="mono">{motherIssues.flatMap((issue) => issue.missingEntryPoints).join(', ') || '—'}</span>,
                },
                { label: 'previews/jobs 行为', value: 'POST /previews 与 POST /jobs 会返回 503 DEPENDENCY_CAPABILITY_MISSING，且不创建半成品 run' },
              ]}
            />
          ) : (
            <SectionCard title="母体阶段能力" subtitle="GET /capabilities">
              <p>
                <Badge tone="ok">capability mothers 可用</Badge>
              </p>
            </SectionCard>
          )}

          <RegistryParamPanel
            registryKind="vessel"
            title="器物参数（registry param_schema → 表单）"
            note={
              <>
                这些参数属于 <code className="mono">synlab.mothers.create_mother</code> 的 builder，**不在**
                GenerationSpec 内（后端 <code className="mono">extra=&quot;forbid&quot;</code> 会拒绝多出的键）。
                当前 HTTP API 没有把 override 传入生成流程的路由；spec 里可用的真实通道是{' '}
                <code className="mono">sampling.parameter_bounds_ref</code>。因此本面板的草稿只用于查看/准备参数，
                下方的生成 spec 仍然只写 <code className="mono">dataset.*</code> 等真实字段。
              </>
            }
          />

          <SpecStudio
            kind="generation"
            fields={GENERATION_FIELDS}
            initialSpec={INITIAL_SPEC}
            previewStage="mother"
            jobStage="mother"
            plannedJobs={1}
            requiresGpu={false}
            submitLabel="提交母体任务"
            onAccepted={(response) => app.setSelectedRunId(response.run_id)}
          />
        </div>
      </div>

      <SectionCard
        title="真实面属性视图（surface_tag / 法向 / 到轴距离）"
        subtitle="在左侧“权威母体 mesh（mother_mesh）”里选中一个资产；数据来自 GET /assets/{id}/files/mother_mesh?key=arrays"
      >
        <SurfaceTagView assetId={meshAssetId} height={340} />
      </SectionCard>

      <SectionCard title="配置编译器说明" subtitle="POST /specs/validate 的 expanded 字段来自后端编译器，不是前端推导">
        <EmptyState
          title="编译器展开结果只在校验后出现"
          reason={
            <>
              generation spec 通过 <code className="mono">compile_spec</code> 后会返回 DAG/替换/警告；
              当前 registry 为空时编译器会产生 <code className="mono">compile</code> 类错误，页面会把它们逐条显示在
              “校验结果”面板里（不隐藏、不降级成警告）。
            </>
          }
        />
      </SectionCard>
    </>
  );
}
