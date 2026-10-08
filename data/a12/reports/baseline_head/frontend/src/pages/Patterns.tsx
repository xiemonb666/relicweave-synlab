/**
 * U03 花纹编辑 `/synlab/patterns`（计划 20.4）。
 *
 * 真实调用：`GET /registry/pattern`（16 主族的真实来源）、`POST /specs/validate`、
 * `POST /budgets`、`POST /previews`（stage=pattern）、`GET /assets`（pattern_recipe /
 * pattern_channels / pattern_audit / display_lod）、`POST /jobs`（stage=pattern）。
 *
 * “只对当前族展示适用字段”由 registry 的 `applicable` 与 `param_schema` 决定；registry 为空时
 * 该联动没有后端依据，页面据此显示阻塞而不是自造字段表。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { NegativeControlPanel } from '../components/NegativeControlPanel';
import { PatternChannelViewer } from '../components/PatternChannelViewer';
import { RegistryParamPanel } from '../components/RegistryParamPanel';
import { SceneViewport } from '../components/SceneViewport';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { Badge, BlockedState, EmptyState, PageHeader, SectionCard } from '../components/states';
import { getCapabilities, getRegistry } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues, stageCapabilities } from '../lib/caps';
import { pretty } from '../lib/format';
import type { AssetRecord } from '../api/types';
import { useAppState } from '../state/app-state';

const PATTERN_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: '纹样族与资源（pattern）',
    hint: '16 主族的真实清单由 GET /registry/pattern 提供；当前返回 0 条时只能手填并由服务端校验。',
    children: [
      { kind: 'stringList', path: 'dataset.pattern_ids', label: '纹样 ID 列表', hint: '纹样几何化阶段使用；与 dataset.vessel_ids 同属 spec.dataset' },
      { kind: 'string', path: 'pattern.coordinate_space', label: '坐标空间', enumValues: ['mother_surface_mm'] },
      { kind: 'boolean', path: 'pattern.periodic_azimuth', label: '方位角周期（u 接缝）' },
      { kind: 'string', path: 'pattern.antialias', label: '抗锯齿策略', enumValues: ['analytic_or_mipmap', 'analytic', 'mipmap'] },
      { kind: 'boolean', path: 'pattern.geometry_before_fracture', label: '断裂前完成几何化' },
      {
        kind: 'string',
        path: 'pattern.height_policy',
        label: '高度策略',
        enumValues: ['relief', 'engrave', 'none'],
        hint: 'relief/engrave 会真实改变几何；none 只是外观（页面会在此处显示后端返回的真实差别）',
      },
    ],
  },
  {
    kind: 'group',
    label: '母体与采样上下文',
    children: [
      { kind: 'stringList', path: 'dataset.vessel_ids', label: '器物 ID' },
      { kind: 'stringList', path: 'dataset.material_ids', label: '材料 ID' },
      { kind: 'stringList', path: 'dataset.layer_combo_ids', label: '层组合 ID' },
      { kind: 'number', path: 'dataset.target_mothers', label: '目标母体数', integer: true, min: 1 },
      { kind: 'number', path: 'master_seed', label: 'master seed（固定 seed 重放一致）', integer: true },
    ],
  },
  {
    kind: 'group',
    label: '全局',
    children: [
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.v3'] },
      { kind: 'string', path: 'data_scope', label: '数据口径', enumValues: ['SYNTHETIC', 'REAL'] },
      { kind: 'string', path: 'release_profile', label: '发布 profile' },
      { kind: 'string', path: 'experiment_purpose', label: '实验用途', enumValues: ['SANDBOX', 'DEVELOPMENT', 'CONFIRMATION'] },
      { kind: 'string', path: 'fracture.backend', label: '断裂后端（切碎后花纹继承）' },
    ],
  },
];

const INITIAL_SPEC: FormValue = {
  schema: 'synlab.v3',
  data_scope: 'SYNTHETIC',
  release_profile: 'SANDBOX_CORE',
  experiment_purpose: 'DEVELOPMENT',
  master_seed: 20261001,
  pattern: { height_policy: 'relief', periodic_azimuth: true, geometry_before_fracture: true, antialias: 'analytic_or_mipmap' },
  dataset: { target_mothers: 1, vessel_ids: ['V01'], material_ids: ['M01'], pattern_ids: ['PAT01'], layer_combo_ids: ['L01'] },
  fracture: { backend: 'rough_shared_cut' },
  implementation: { require_poc_before_custom: false },
};

export function PatternsPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const patterns = useResource((signal) => getRegistry('pattern', {}, signal), []);
  const [displayAsset, setDisplayAsset] = useState<AssetRecord | null>(null);
  const [recipeAsset, setRecipeAsset] = useState<string | null>(null);

  const issues = capabilityIssues(
    capabilities.data ?? null,
    stageCapabilities(capabilities.data ?? null, 'pattern', ['patterns', 'mothers']),
  );

  const catalogue = patterns.data;
  const families = catalogue?.entries ?? [];

  return (
    <>
      <PageHeader
        title="花纹编辑"
        plan="U03 · 计划 20.4"
        summary="16 主族选择 → 只展示该族适用字段 → 固定 seed 重放 → 展开 chart / albedo / roughness / height 通道 → 接缝与采样尺度审计。"
        actions={
          <div className="row">
            <Badge tone="info">pattern 与母体同 spec</Badge>
            <Badge tone="neutral">纹样保存到完整母体</Badge>
          </div>
        }
      />

      <SectionCard
        title="纹样族目录（registry）"
        subtitle="GET /registry/pattern —— “只对当前族展示适用字段”的唯一真实依据"
        actions={
          <button type="button" className="btn btn--tiny" onClick={patterns.reload} disabled={patterns.refreshing}>
            {patterns.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        {patterns.status === 'loading' ? <p className="muted">读取 registry/pattern…</p> : null}
        {catalogue && families.length === 0 ? (
          <BlockedState
            title="16 主族清单不可用：registry 未注册 pattern"
            code="REGISTRY_EMPTY"
            reason={
              <>
                计划 20.4 的「16 主族 / 调色板 / 线宽 / 相位 / u-s 区域 / 重复策略 / 噪声频带 / warp /
                height policy / 浮雕高 / 刻线深 / 字体-SVG 资源」都应由 <code className="mono">register_pattern</code>{' '}
                的 <code className="mono">param_model</code> 描述。后端当前返回 {catalogue.count} 条
                （empty_kinds={catalogue.empty_kinds.join(', ') || '—'}），因此页面无法枚举真实族，也不复制一份族表。
              </>
            }
            items={[
              { label: 'registry 指纹', value: <span className="mono">{catalogue.registry_fingerprint}</span> },
              { label: '后端说明', value: catalogue.note },
              { label: '降级路径', value: '仍可提交 spec 让服务端判定 ID 合法性；pattern 阶段本身还需要 patterns+mothers 能力。' },
            ]}
          />
        ) : null}
        {families.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">id</th>
                <th scope="col">名称</th>
                <th scope="col">版本</th>
                <th scope="col">状态</th>
                <th scope="col">适用组合（applicable）</th>
                <th scope="col">参数字段</th>
              </tr>
            </thead>
            <tbody>
              {families.map((family) => (
                <tr key={family.id}>
                  <th scope="row" className="mono">
                    {family.id}
                  </th>
                  <td>{family.name ?? '—'}</td>
                  <td className="mono">{family.version ?? '—'}</td>
                  <td>
                    <Badge tone="neutral">{family.status ?? '—'}</Badge>
                  </td>
                  <td className="mono small">{pretty(family.applicable ?? {})}</td>
                  <td className="mono small">
                    {Object.keys((family.param_schema?.properties ?? {}) as Record<string, unknown>).join(', ') || '—'}
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
            title="纹样资产（recipe / channels / audit）"
            fixedRoles={['pattern_recipe', 'pattern_channels', 'pattern_audit']}
            selectable="single"
            selected={recipeAsset ? [recipeAsset] : []}
            onSelect={(ids) => setRecipeAsset(ids[0] ?? null)}
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={10}
            emptyReason="还没有纹样资产。pattern 阶段需要 patterns+mothers 能力，能力缺失时 POST /previews 会返回 503 且不创建任何 run。"
          />
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
          />
          <AssetBrowser
            title="接缝 / 尺度审计产物"
            fixedRoles={['qa_report', 'coverage', 'provenance']}
            selectable="none"
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={5}
            emptyReason="接缝与采样尺度审计报告由 pattern-channels 任务产出；未运行时这里为空（报表不会伪造）。"
          />
        </div>

        <div className="threecol__center">
          <SceneViewport
            asset={displayAsset}
            title="母体 + 纹样几何（派生展示 GLB）"
            height={360}
            notice="height_policy=relief/engrave 的真实几何差异只能通过派生 GLB 观察"
          />
          <SectionCard title="U03 通道与审计的真实边界" subtitle="哪些能做、哪些没有数据">
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">计划要求</th>
                  <th scope="col">当前实现</th>
                  <th scope="col">原因</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">母体三维</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>display_lod GLB + mm 量尺</td>
                </tr>
                <tr>
                  <th scope="row">展开 chart</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>
                    选中 <code className="mono">pattern_channels</code> 资产后，下方“展开 chart 与三通道图”直接解码它的真实 PNG
                    字节（IHDR 尺寸 + 签名校验），并列出后端记录的 chart 参数（u/s 周期、x 周期、s 范围、面积）。
                  </td>
                </tr>
                <tr>
                  <th scope="row">albedo / roughness / height 通道</th>
                  <td>
                    <Badge tone="ok">已实现</Badge>
                  </td>
                  <td>
                    三个通道按真实成员键（<code className="mono">albedo_png</code> / <code className="mono">roughness_png</code> /{' '}
                    <code className="mono">height_png</code>）逐个解码显示，编码说明取后端{' '}
                    <code className="mono">meta.encoding_legend</code> 原文；资产没有图像成员时显示“尚未生成”及产出命令。
                  </td>
                </tr>
                <tr>
                  <th scope="row">周期接缝 / 采样尺度告警</th>
                  <td>
                    <Badge tone="ok">已实现（转发后端产物）</Badge>
                  </td>
                  <td>直接列出 pattern_audit / qa_report 资产及其 meta，不做本地推断</td>
                </tr>
              </tbody>
            </table>
          </SectionCard>
        </div>

        <div className="threecol__right">
          {issues.length > 0 ? (
            <BlockedState
              title="纹样阶段被后端能力阻塞"
              code={issues[0].status}
              reason={describeIssues(issues)}
              items={[
                { label: '阶段', value: 'pattern（build_pattern / evaluate / apply_pattern_geometry / audit_pattern）' },
                { label: '缺少入口函数', value: <span className="mono">{issues.flatMap((issue) => issue.missingEntryPoints).join(', ') || '—'}</span> },
                { label: 'previews 行为', value: 'POST /previews（stage=pattern）返回 503 DEPENDENCY_CAPABILITY_MISSING，不创建 run' },
              ]}
            />
          ) : (
            <SectionCard title="纹样阶段能力">
              <Badge tone="ok">capabilities patterns/mothers 可用</Badge>
            </SectionCard>
          )}

          <RegistryParamPanel
            registryKind="pattern"
            title="纹样族参数（registry param_schema → 表单）"
            emptyReason="后端还没有注册 pattern 条目，因此没有可用的族参数模型。"
            note={
              <>
                每个族的 <code className="mono">param_schema</code> 决定“只对当前族展示适用字段”；
                这些参数属于 <code className="mono">synlab.patterns.build_pattern</code> 的 builder，
                不在 GenerationSpec 内（后端 <code className="mono">extra=&quot;forbid&quot;</code>）。面板上方的
                “适用组合 applicable”字段表直接来自后端，用于判断当前族是否支持某组件/材料。
              </>
            }
          />

          <SpecStudio
            kind="generation"
            fields={PATTERN_FIELDS}
            initialSpec={INITIAL_SPEC}
            previewStage="pattern"
            jobStage="pattern"
            requiresGpu={false}
            submitLabel="提交纹样任务"
            onAccepted={(response) => app.setSelectedRunId(response.run_id)}
          />
        </div>
      </div>

      <SectionCard
        title="展开 chart 与三通道图（真实 PNG 解码）"
        subtitle="先在上方“纹样资产”里选中一个 pattern_channels 资产"
      >
        {recipeAsset ? (
          <PatternChannelViewer assetId={recipeAsset} />
        ) : (
          <EmptyState
            title="未选择纹样资产"
            reason="在左侧“纹样资产（recipe / channels / audit）”里选中一个 pattern_channels 资产，这里会解码它的真实 PNG 通道图（albedo / roughness / height）并显示后端记录的展开 chart 参数。"
          />
        )}
      </SectionCard>

      <NegativeControlPanel />

      <SectionCard title="没有“给每片独立随机贴图”的入口" subtitle="计划 20.4 的明确禁止项">
        <EmptyState
          title="本页刻意不提供随机贴图按钮"
          reason="纹样绑定在完整母体上，切碎后由断裂阶段继承；给每片独立随机贴图会使同一母体的替代事件混入不同纹理来源。API 也没有对应入口。"
        />
      </SectionCard>
    </>
  );
}
