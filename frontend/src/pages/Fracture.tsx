/**
 * U04 断裂预览 `/synlab/fracture`（计划 20.5）。
 *
 * 真实调用：`GET /registry/fracture_backend`（“四必做后端”的真实清单）、`POST /specs/validate`、
 * `POST /budgets`、`POST /previews`（stage=fracture）、`POST /jobs`（stage=fracture）、
 * `GET /assets`（mother_mesh / fragment_mesh / display_lod / physical_result）、
 * `GET /research/assets/{id}/truth`（研究角色）。
 *
 * 明确不做的事：爆炸图只作为展示变换、邻边/装配放研究审计 tab、不允许手工“修正真值成绩”。
 * 断层面数/守恒等**实测**结论只从后端资产 qa/meta 与 worker 事件读出；后端未通过就显示失败。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { SceneViewport } from '../components/SceneViewport';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { MeasuredQualityTable, flattenMetrics, type QualityRow } from '../components/MeasuredQualityTable';
import { Badge, BlockedState, EmptyState, ErrorState, KeyValueList, PageHeader, SectionCard } from '../components/states';
import { getAsset, getCapabilities, getRegistry, getResearchTruth } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues, stageCapabilities } from '../lib/caps';
import { pretty } from '../lib/format';
import type { AssetRecord } from '../api/types';
import { useAppState } from '../state/app-state';

const FRACTURE_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: '母体版本与目标（dataset / fracture）',
    hint: '母体版本用 asset id 表达；在左侧资产浏览器选中 mother_mesh 后会作为 input_refs 提交。',
    children: [
      { kind: 'string', path: 'fracture.backend', label: '断裂后端 ID', hint: '真实清单来自 GET /registry/fracture_backend' },
      { kind: 'numberTuple', path: 'fracture.target_piece_range', label: '目标片数区间 [lo, hi]', length: 2, integer: true, unit: '片' },
      { kind: 'number', path: 'fracture.min_feature_wavelength_mm', label: '最小特征波长', unit: 'mm', min: 0 },
      { kind: 'number', path: 'fracture.shared_surface_max_error_mm', label: '共享面最大误差（误差预算）', unit: 'mm', min: 0 },
      { kind: 'number', path: 'fracture.max_attempts', label: '最大尝试次数', integer: true, min: 1 },
      { kind: 'number', path: 'fracture.secondary_probability', label: '二次破碎概率', min: 0, max: 1 },
      { kind: 'boolean', path: 'fracture.keep_parent_history', label: '保留父级历史（二次破碎裁剪旧邻边）' },
      { kind: 'string', path: 'dataset.debris_policy', label: 'tiny/debris 策略', enumValues: ['quarantine_and_record', 'keep'] },
      { kind: 'boolean', path: 'dataset.include_all_components', label: '包含全部连通块' },
    ],
  },
  {
    kind: 'group',
    label: 'Power / 形变（rough_shared_cut 与 warped_partition）',
    children: [
      { kind: 'number', path: 'fracture.rough_amplitude_mm', label: '粗糙幅度下界', unit: 'mm', min: 0, hint: '区间第二项请在高级 JSON 区写' },
      { kind: 'numberTuple', path: 'fracture.seed_count_range', label: '种子数区间', length: 2, integer: true, unit: '个' },
    ],
  },
  {
    kind: 'group',
    label: '全局',
    children: [
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.v3'] },
      { kind: 'string', path: 'release_profile', label: '发布 profile' },
      { kind: 'string', path: 'experiment_purpose', label: '实验用途', enumValues: ['SANDBOX', 'DEVELOPMENT', 'CONFIRMATION'] },
      { kind: 'number', path: 'master_seed', label: 'master seed', integer: true },
    ],
  },
];

const INITIAL_SPEC: FormValue = {
  schema: 'synlab.v3',
  data_scope: 'SYNTHETIC',
  release_profile: 'SANDBOX_CORE',
  experiment_purpose: 'DEVELOPMENT',
  master_seed: 20261001,
  dataset: { target_mothers: 1, target_fragments_estimate: 12, debris_policy: 'quarantine_and_record', include_all_components: true },
  fracture: {
    backend: 'rough_shared_cut',
    target_piece_range: [8, 20],
    min_feature_wavelength_mm: 0.24,
    shared_surface_max_error_mm: 0.01,
    max_attempts: 3,
    keep_parent_history: true,
  },
  implementation: { require_poc_before_custom: false },
};

export function FracturePage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const backends = useResource((signal) => getRegistry('fracture_backend', {}, signal), []);
  const [motherAsset, setMotherAsset] = useState<string | null>(null);
  const [fragmentAsset, setFragmentAsset] = useState<string | null>(null);
  const [displayAsset, setDisplayAsset] = useState<AssetRecord | null>(null);
  const [showTruth, setShowTruth] = useState(false);

  const fragmentDetail = useResource(
    (signal) => getAsset(fragmentAsset as string, signal),
    [fragmentAsset],
    { enabled: Boolean(fragmentAsset) },
  );
  const truth = useResource(
    (signal) => getResearchTruth(fragmentAsset as string, true, signal),
    [fragmentAsset],
    { enabled: Boolean(fragmentAsset) && showTruth },
  );

  const issues = capabilityIssues(
    capabilities.data ?? null,
    stageCapabilities(capabilities.data ?? null, 'fracture', ['fracture', 'mothers']),
  );

  const qaRows: QualityRow[] = fragmentDetail.data
    ? flattenMetrics(fragmentDetail.data.asset.qa, { prefix: 'qa', origin: 'GET /assets/{id}.qa' })
    : [];

  return (
    <>
      <PageHeader
        title="断裂预览"
        plan="U04 · 计划 20.5"
        summary="母体版本 + 断裂后端 + 片数/尺寸分布 + 切割方向 + RMS/波长 + 误差预算 → 真实断裂事件；结果给出实际片数、tiny/debris、体积守恒、共享距离/法向、歧义面积与错误码。"
        actions={
          <div className="row">
            <Badge tone="info">爆炸图仅为展示变换</Badge>
            <Badge tone="neutral">邻边/装配默认在研究审计 tab</Badge>
          </div>
        }
      />

      <SectionCard
        title="断裂后端清单（registry）"
        subtitle="GET /registry/fracture_backend —— “四必做后端”的真实来源"
      >
        {backends.status === 'loading' ? <p className="muted">读取 registry…</p> : null}
        {backends.data && backends.data.count === 0 ? (
          <BlockedState
            title="无法枚举断裂后端：registry 未注册"
            code="REGISTRY_EMPTY"
            reason={
              <>
                计划 20.5 要求“切换四必做后端并检查真实碎片/来源/QA”。后端的后端 ID 由{' '}
                <code className="mono">register_fracture_backend</code> 注册；当前返回 {backends.data.count} 条
                （empty_kinds={backends.data.empty_kinds.join(', ') || '—'}）。
                前端不复制后端 ID 列表，因此下拉框为空；可在表单里手填 ID 并由 <code className="mono">POST /specs/validate</code> 判定。
              </>
            }
            items={[
              { label: 'registry 指纹', value: <span className="mono">{backends.data.registry_fingerprint}</span> },
              { label: '后端说明', value: backends.data.note },
            ]}
          />
        ) : null}
        {backends.data && backends.data.count > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">id</th>
                <th scope="col">名称</th>
                <th scope="col">版本</th>
                <th scope="col">状态</th>
                <th scope="col">参数</th>
              </tr>
            </thead>
            <tbody>
              {backends.data.entries.map((entry) => (
                <tr key={entry.id}>
                  <th scope="row" className="mono">
                    {entry.id}
                  </th>
                  <td>{entry.name ?? '—'}</td>
                  <td className="mono">{entry.version ?? '—'}</td>
                  <td>
                    <Badge tone="neutral">{entry.status ?? '—'}</Badge>
                  </td>
                  <td className="mono small">
                    {Object.keys((entry.param_schema?.properties ?? {}) as Record<string, unknown>).join(', ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </SectionCard>

      <div className="threecol">
        <div className="threecol__left">
          <AssetBrowser
            title="母体版本（mother_mesh，作为 input_refs）"
            fixedRoles={['mother_mesh']}
            selectable="single"
            selected={motherAsset ? [motherAsset] : []}
            onSelect={(ids) => setMotherAsset(ids[0] ?? null)}
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={8}
            emptyReason="没有 mother_mesh 资产：断裂阶段必须有真实母体输入，本页不会用占位几何代替。"
          />
          <AssetBrowser
            title="碎片（fragment_mesh）"
            fixedRoles={['fragment_mesh']}
            selectable="single"
            selected={fragmentAsset ? [fragmentAsset] : []}
            onSelect={(ids) => setFragmentAsset(ids[0] ?? null)}
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={12}
            emptyReason="还没有碎片资产。fracture 阶段需要 fracture+mothers 能力；能力缺失时后端 503 且不创建 run。"
          />
          <AssetBrowser
            title="物理结果 / 切刀（physical_result / cutter_mesh）"
            fixedRoles={['physical_result', 'cutter_mesh']}
            selectable="none"
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={6}
          />
        </div>

        <div className="threecol__center">
          <AssetBrowser
            title="派生展示资产（display_lod_glb）"
            fixedRoles={['display_lod_glb']}
            selectable="single"
            selected={displayAsset ? [displayAsset.asset_id] : []}
            onSelectAssets={(assets) => setDisplayAsset(assets[0] ?? null)}
            pageSize={6}
          />
          <SceneViewport
            asset={displayAsset}
            title="碎片/母体三维视口"
            height={340}
            notice="爆炸图与剖切都只是展示变换，不能导出成模型观测装配位置"
          />

          <SectionCard title="碎片实测（来自资产 qa 字段）" subtitle="GET /assets/{id}">
            {fragmentAsset === null ? (
              <EmptyState title="未选择碎片" reason="在左侧选择一块 fragment_mesh 后，这里显示它真实的 qa 与 meta。" />
            ) : fragmentDetail.status === 'error' ? (
              <p className="warning">读取资产失败，请看错误提示。</p>
            ) : (
              <MeasuredQualityTable
                rows={qaRows}
                caption={`碎片 ${fragmentAsset} 的 qa（后端原样）`}
                emptyTitle="该碎片没有 qa 字段"
                emptyReason="后端没有为这个资产记录 qa；未实测的项不会补 0。"
              />
            )}
            {fragmentDetail.data ? (
              <details>
                <summary>资产 meta / ancestry（后端原样）</summary>
                <KeyValueList
                  rows={[
                    { label: 'role', value: fragmentDetail.data.asset.role },
                    { label: 'unit / frame', value: `${fragmentDetail.data.asset.unit} / ${fragmentDetail.data.asset.frame}` },
                    { label: 'qa_status', value: fragmentDetail.data.asset.qa_status },
                    { label: 'lineage', value: fragmentDetail.data.asset.lineage_id ?? '—' },
                    { label: 'ancestry', value: fragmentDetail.data.asset.ancestry.join(' → ') || '（空）', mono: true },
                  ]}
                />
                <pre className="mono pre">{pretty(fragmentDetail.data.asset.meta)}</pre>
              </details>
            ) : null}
          </SectionCard>
        </div>

        <div className="threecol__right">
          {issues.length > 0 ? (
            <BlockedState
              title="断裂阶段被后端能力阻塞"
              code={issues[0].status}
              reason={describeIssues(issues)}
              items={[
                { label: '阶段', value: 'fracture（make_closed_cutter / fracture_event）' },
                { label: '缺少入口函数', value: <span className="mono">{issues.flatMap((issue) => issue.missingEntryPoints).join(', ') || '—'}</span> },
                { label: '行为', value: 'POST /previews(stage=fracture) 与 POST /jobs(stage=fracture) 均 503，不创建半成品 run' },
              ]}
            />
          ) : (
            <SectionCard title="断裂阶段能力">
              <Badge tone="ok">capabilities fracture/mothers 可用</Badge>
            </SectionCard>
          )}

          <SpecStudio
            kind="generation"
            fields={FRACTURE_FIELDS}
            initialSpec={INITIAL_SPEC}
            registryKind="fracture_backend"
            previewStage="fracture"
            jobStage="fracture"
            inputRefs={motherAsset ? [motherAsset] : []}
            submitLabel="提交断裂任务"
            submitBlockReason={motherAsset ? null : '未选择母体资产：断裂阶段需要真实母体 input_refs'}
            onAccepted={(response) => app.setSelectedRunId(response.run_id)}
          />

          <SectionCard title="研究审计：邻边 / 装配 / 真值" subtitle="GET /research/assets/{id}/truth（研究角色专属）">
            <p className="muted small">
              邻边与装配信息属于研究审计；部署会话下该路由不挂载（<code className="mono">403 TRUTH_ROUTE_UNMOUNTED</code>）。
            </p>
            <button type="button" className="btn btn--tiny" onClick={() => setShowTruth(true)} disabled={!fragmentAsset || showTruth}>
              {showTruth ? '已请求' : '请求研究真值'}
            </button>
            {showTruth && truth.status === 'error' ? (
              <ErrorState error={truth.error} onRetry={truth.reload} compact title="研究真值入口被拒绝" />
            ) : null}
            {truth.data ? (
              <>
                <KeyValueList
                  rows={[
                    { label: 'truth_role', value: String(truth.data.truth_role) },
                    { label: 'array_keys', value: truth.data.array_keys.join(', ') || '（无）', mono: true },
                    { label: 'split', value: truth.data.split ?? '—' },
                  ]}
                />
                <pre className="mono pre">{pretty(truth.data.meta)}</pre>
              </>
            ) : null}
            <p className="warning">
              本页不提供“手工修正真值成绩”的任何入口：真值由后端资产与审计决定。
            </p>
          </SectionCard>
        </div>
      </div>
    </>
  );
}
