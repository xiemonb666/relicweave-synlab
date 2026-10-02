/**
 * U05 退化对比 `/synlab/degradation`（计划 20.6）。
 *
 * 真实调用：`GET /registry/axis`（31 轴与 P/I/G/X 分组的真实来源）、`POST /specs/validate`
 * （kind=recipe，含 `DegradationOperatorSpec` 的 stage/level/variant 校验）、`POST /budgets`、
 * `POST /previews`（stage=degrade）、`GET /assets`（clean/physical/observed/display_lod）、
 * `GET /camera-profiles`（共同 basis 的相机档）。
 *
 * 关键诚实点：
 * * 滑块只是参数，不是测量值；只有任务产出资产后才有实测表；
 * * G08 只应改右侧 Observed；clean/Physical 不变 —— 这一点由后端资产的 role/ancestry 决定，
 *   页面只按真实 role 分组显示，不做前端“模拟”；
 * * `level=0` 必须与 baseline 同源：后端 recipe 的 basis_policy 决定，页面显示编译结果。
 */

import { useMemo, useState } from 'react';

import { CompareViewport } from '../components/CompareViewport';
import { AssetBrowser } from '../components/AssetBrowser';
import { DegradationDiffPanel } from '../components/DegradationDiffPanel';
import { DegradationPairPanel } from '../components/DegradationPairPanel';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { MeasuredQualityTable, flattenMetrics } from '../components/MeasuredQualityTable';
import { Badge, BlockedState, EmptyState, PageHeader, SectionCard, Tabs } from '../components/states';
import { getAsset, getCapabilities, getRegistry, listCameraProfiles } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues, stageCapabilities } from '../lib/caps';
import { pretty } from '../lib/format';
import type { AssetRecord } from '../api/types';
import { useAppState } from '../state/app-state';

const GROUP_LABEL: Record<string, string> = {
  P: 'P 物理损伤',
  I: 'I 成像/观测',
  G: 'G 观测重建',
  X: 'X 其它',
};

const RECIPE_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: '配方与 basis（DegradationRecipeSpec）',
    children: [
      { kind: 'string', path: 'recipe_id', label: '配方 ID', required: true },
      {
        kind: 'string',
        path: 'basis_policy',
        label: 'basis 策略',
        enumValues: ['paired_across_levels', 'independent'],
        hint: 'paired_across_levels 表示 level0/1/4 共用同一 basis（强度零同源内容）',
      },
      {
        kind: 'string',
        path: 'source_role',
        label: '作用对象（source_role）',
        enumValues: ['clean', 'physical', 'observed'],
        hint: 'baseline/physical/observed 三层可切换；G 组只应作用于 observed',
      },
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.v3'] },
      { kind: 'number', path: 'master_seed', label: 'master seed（固定后重放一致）', integer: true },
    ],
  },
];

interface Operator {
  axis_id: string;
  stage: string;
  level: number;
  variant: string;
}

const STAGE_VALUES = ['PHYSICAL', 'SCENE', 'OPTICS', 'SENSOR', 'ISP', 'GEOMETRY_OBS', 'FEATURE_PROTOCOL'];

function readOperators(spec: FormValue): Operator[] {
  const raw = spec.operators;
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const record = (item ?? {}) as Record<string, unknown>;
    return {
      axis_id: String(record.axis_id ?? ''),
      stage: String(record.stage ?? 'PHYSICAL'),
      level: Number(record.level ?? 0),
      variant: String(record.variant ?? ''),
    };
  });
}

function writeOperators(spec: FormValue, operators: Operator[]): FormValue {
  return {
    ...spec,
    operators: operators.map((operator) => ({
      axis_id: operator.axis_id,
      stage: operator.stage,
      level: operator.level,
      variant: operator.variant,
      parameters: {},
    })),
  };
}

export function DegradationPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const axes = useResource((signal) => getRegistry('axis', {}, signal), []);
  const cameras = useResource((signal) => listCameraProfiles({}, signal), []);
  const [spec, setSpec] = useState<FormValue>({
    schema: 'synlab.v3',
    recipe_id: 'recipe_ui_draft',
    basis_policy: 'paired_across_levels',
    source_role: 'clean',
    master_seed: 20261001,
    operators: [],
  });
  const [activeGroup, setActiveGroup] = useState<string>('P');
  const [leftAsset, setLeftAsset] = useState<AssetRecord | null>(null);
  const [rightAsset, setRightAsset] = useState<AssetRecord | null>(null);
  const [detailAsset, setDetailAsset] = useState<string | null>(null);

  const assetDetail = useResource((signal) => getAsset(detailAsset as string, signal), [detailAsset], {
    enabled: Boolean(detailAsset),
  });

  const operators = readOperators(spec);
  const axisEntries = axes.data?.entries ?? [];

  /** 分组只从真实 axis id 的前缀推导（P/I/G/X），没有 registry 条目时不做任何分组。 */
  const grouped = useMemo(() => {
    const map = new Map<string, typeof axisEntries>();
    for (const entry of axisEntries) {
      const prefix = entry.id.charAt(0).toUpperCase();
      const list = map.get(prefix) ?? [];
      list.push(entry);
      map.set(prefix, list);
    }
    return map;
  }, [axisEntries]);

  const issues = capabilityIssues(
    capabilities.data ?? null,
    stageCapabilities(capabilities.data ?? null, 'degrade', ['degrade']),
  );

  const addOperator = (axisId: string) => {
    setSpec(writeOperators(spec, [...operators, { axis_id: axisId, stage: 'PHYSICAL', level: 1, variant: '' }]));
  };

  const updateOperator = (index: number, patch: Partial<Operator>) => {
    setSpec(writeOperators(spec, operators.map((item, position) => (position === index ? { ...item, ...patch } : item))));
  };

  const removeOperator = (index: number) => {
    setSpec(writeOperators(spec, operators.filter((_, position) => position !== index)));
  };

  return (
    <>
      <PageHeader
        title="退化对比"
        plan="U05 · 计划 20.6"
        summary="左 baseline、右 level，同视角/zoom/crop 联动；P/I/G/X 分组选轴 → 五档或具体参数 → 预览任务 → 待运行/排队/计算/检查 → 实测表。滑块不是测量值。"
        actions={
          <div className="row">
            <Badge tone="info">共享相机（结构联动）</Badge>
            <Badge tone="ok">误差热图 + 点云叠加（前端由真实 depth/points 计算）</Badge>
          </div>
        }
      />

      <SectionCard title="31 轴与 P/I/G/X 分组（registry）" subtitle="GET /registry/axis —— 轴清单与 level 0..4 的真实来源">
        {axes.status === 'loading' ? <p className="muted">读取 registry/axis…</p> : null}
        {axes.data && axes.data.count === 0 ? (
          <BlockedState
            title="无法枚举退化轴：registry 未注册"
            code="REGISTRY_EMPTY"
            reason={
              <>
                计划 20.6 要求按 P/I/G/X 分组选择轴与 variant。轴 ID 与 level 语义由{' '}
                <code className="mono">register_axis</code> 注册，并由后端 recipe 编译器校验
                （未注册轴会被 <code className="mono">/specs/validate</code> 拒绝）。
                当前 <code className="mono">/registry/axis</code> 返回 {axes.data.count} 条，前端不复制 31 轴表。
              </>
            }
            items={[
              { label: 'registry 指纹', value: <span className="mono">{axes.data.registry_fingerprint}</span> },
              { label: '后端说明', value: axes.data.note },
              { label: '降级路径', value: '在“算子”面板手填 axis_id（例如 P01），由服务端给出注册与否的真实结论。' },
            ]}
          />
        ) : null}

        {axisEntries.length > 0 ? (
          <>
            <Tabs
              label="退化分组"
              active={activeGroup}
              onChange={setActiveGroup}
              tabs={['P', 'I', 'G', 'X'].map((group) => ({
                id: group,
                label: `${GROUP_LABEL[group] ?? group}（${grouped.get(group)?.length ?? 0}）`,
                disabledReason: grouped.has(group) ? null : `registry 里没有 ${group} 前缀的轴`,
              }))}
            />
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">axis</th>
                  <th scope="col">名称</th>
                  <th scope="col">状态</th>
                  <th scope="col">适用组合</th>
                  <th scope="col">加入配方</th>
                </tr>
              </thead>
              <tbody>
                {(grouped.get(activeGroup) ?? []).map((entry) => (
                  <tr key={entry.id}>
                    <th scope="row" className="mono">
                      {entry.id}
                    </th>
                    <td>{entry.name ?? '—'}</td>
                    <td>
                      <Badge tone="neutral">{entry.status ?? '—'}</Badge>
                    </td>
                    <td className="mono small">{pretty(entry.applicable ?? {})}</td>
                    <td>
                      <button type="button" className="btn btn--tiny" onClick={() => addOperator(entry.id)}>
                        加入
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </SectionCard>

      <SectionCard title="算子（DegradationOperatorSpec[]）" subtitle="axis_id / stage / level(0..4) / variant / parameters">
        {operators.length === 0 ? (
          <EmptyState
            title="配方里还没有算子"
            reason="从上面的轴清单点“加入”，或直接在下方手填 axis_id（例如 P01）。stage 与 level 的合法性由服务端校验。"
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">axis_id</th>
                <th scope="col">stage</th>
                <th scope="col">level（0..4）</th>
                <th scope="col">variant</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {operators.map((operator, index) => (
                <tr key={index}>
                  <td>
                    <input
                      className="input input--tight"
                      value={operator.axis_id}
                      aria-label={`算子 ${index + 1} 的 axis_id`}
                      onChange={(event) => updateOperator(index, { axis_id: event.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      className="input input--tight"
                      value={operator.stage}
                      aria-label={`算子 ${index + 1} 的 stage`}
                      onChange={(event) => updateOperator(index, { stage: event.target.value })}
                    >
                      {STAGE_VALUES.map((stage) => (
                        <option key={stage} value={stage}>
                          {stage}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      className="input input--tight"
                      type="number"
                      min={0}
                      max={4}
                      value={operator.level}
                      aria-label={`算子 ${index + 1} 的 level`}
                      onChange={(event) => updateOperator(index, { level: Number(event.target.value) })}
                    />
                  </td>
                  <td>
                    <input
                      className="input input--tight"
                      value={operator.variant}
                      placeholder="variant 名称"
                      aria-label={`算子 ${index + 1} 的 variant`}
                      onChange={(event) => updateOperator(index, { variant: event.target.value })}
                    />
                  </td>
                  <td>
                    <button type="button" className="btn btn--tiny" onClick={() => removeOperator(index)}>
                      移除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row">
          <button type="button" className="btn btn--tiny" onClick={() => addOperator('')}>
            新增空算子
          </button>
          <span className="muted small">
            level 0 必须与 baseline 同源（依赖 basis_policy=paired_across_levels）；后端会校验，前端不做假设。
          </span>
        </div>
      </SectionCard>

      <div className="threecol">
        <div className="threecol__left">
          <AssetBrowser
            title="baseline（左）"
            fixedRoles={['display_lod_glb']}
            selectable="single"
            selected={leftAsset ? [leftAsset.asset_id] : []}
            onSelectAssets={(assets) => setLeftAsset(assets[0] ?? null)}
            pageSize={8}
            emptyReason="没有 display_lod_glb 资产可作为 baseline。"
          />
          <AssetBrowser
            title="level 结果（右）"
            fixedRoles={['display_lod_glb']}
            selectable="single"
            selected={rightAsset ? [rightAsset.asset_id] : []}
            onSelectAssets={(assets) => setRightAsset(assets[0] ?? null)}
            pageSize={8}
            emptyReason="没有 display_lod_glb 资产可作为 level 结果。"
          />
          <AssetBrowser
            title="观测与真值资产（obs_view / obs_result / clean_truth / physical_truth）"
            fixedRoles={['obs_view', 'obs_result', 'clean_truth', 'physical_truth']}
            selectable="single"
            selected={detailAsset ? [detailAsset] : []}
            onSelect={(ids) => setDetailAsset(ids[0] ?? null)}
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={10}
            emptyReason="还没有观测/真值资产。degrade 与 observe 阶段需要真实能力模块。"
          />
        </div>

        <div className="threecol__center">
          <CompareViewport
            left={{ asset: leftAsset, label: 'baseline' }}
            right={{ asset: rightAsset, label: 'level' }}
            height={330}
          />
          <SectionCard title="实测表（选中资产的 qa）" subtitle="GET /assets/{id}">
            {detailAsset === null ? (
              <EmptyState title="未选择资产" reason="在左侧选择观测/真值资产后，这里显示后端记录的实测字段。" />
            ) : assetDetail.status === 'error' ? (
              <p className="warning">读取资产失败：请看错误卡片中的 code 与 request_id。</p>
            ) : assetDetail.data ? (
              <>
                <MeasuredQualityTable
                  rows={flattenMetrics(assetDetail.data.asset.qa, { prefix: 'qa', origin: 'GET /assets/{id}.qa' })}
                  caption={`${detailAsset} 的 qa`}
                  emptyTitle="该资产没有 qa 字段"
                />
                <details>
                  <summary>资产 meta（role / ancestry / 坐标契约）</summary>
                  <pre className="mono pre">{pretty(assetDetail.data.asset.meta)}</pre>
                </details>
              </>
            ) : null}
          </SectionCard>
        </div>

        <div className="threecol__right">
          {issues.length > 0 ? (
            <BlockedState
              title="退化阶段被后端能力阻塞"
              code={issues[0].status}
              reason={describeIssues(issues)}
              items={[{ label: '阶段', value: 'degrade（apply_recipe / 算子实现）' }]}
            />
          ) : null}

          <SectionCard title="相机档与共同 basis" subtitle="GET /camera-profiles">
            {cameras.status === 'error' ? <p className="warning">相机档读取失败。</p> : null}
            {cameras.data ? (
              <>
                <p>
                  <Badge tone={cameras.data.capability.available ? 'ok' : 'warn'}>
                    capability cameras = {cameras.data.capability.status}
                  </Badge>
                  <span className="mono small"> catalogue={cameras.data.catalogue.length} · registered={cameras.data.registered.length}</span>
                </p>
                {cameras.data.blocked_reason ? <p className="warning">{cameras.data.blocked_reason}</p> : null}
                <ul className="chips">
                  {cameras.data.catalogue.map((entry) => (
                    <li key={entry.profile_id}>
                      <Badge tone={entry.calibrated ? 'ok' : 'warn'}>
                        {entry.profile_id}（{entry.calibrated ? '已标定' : '未标定'}）
                      </Badge>
                    </li>
                  ))}
                </ul>
                <p className="muted small">
                  切换相机档会改变“共同 basis”的观测条件；同轴不同档的结果不能混在同一条曲线（U10 曲线的 n/M/K 标注依赖这一点）。
                </p>
              </>
            ) : null}
          </SectionCard>

          <SpecStudio
            kind="recipe"
            fields={RECIPE_FIELDS}
            initialSpec={spec}
            value={spec}
            onValueChange={setSpec}
            submitLabel="（本页不提交任务）"
          />
          <SectionCard title="为什么本页不提供“提交退化任务”" subtitle="后端真实约束（见 docs/a12/api_ui.md 差异表）">
            <p className="muted small">
              <code className="mono">POST /jobs</code> 与 <code className="mono">POST /previews</code> 只把请求体里的{' '}
              <code className="mono">spec</code> 按 <code className="mono">synlab.v3</code> <strong>生成 spec</strong> 校验
              （<code className="mono">validate_spec(kind=&quot;generation&quot;)</code>），没有任何路由接受{' '}
              <code className="mono">DegradationRecipeSpec</code>。退化配方进入流水线的真实通道是生成 spec 里的{' '}
              <code className="mono">degraded_recipe_refs</code>（recipe_id 列表），由{' '}
              <code className="mono">synlab.degrade</code> 编译。
            </p>
            <p className="muted small">
              因此本页只做真实可做的事：<strong>校验配方</strong>（<code className="mono">POST /specs/validate</code>{' '}
              kind=recipe，返回真实的字段/单位/组合/注册结论）与<strong>查看已产出的观测资产实测值</strong>。
              提交类动作留给 U07（生成任务，含 <code className="mono">degraded_recipe_refs</code>）。
            </p>
          </SectionCard>
        </div>
      </div>

      <DegradationPairPanel onSelectRun={app.setSelectedRunId} />

      <DegradationDiffPanel />

      <SectionCard title="U05 交互提示（真实条件触发）" subtitle="计划 20.6 要求明确告知需要重新成像的情形">
        <ul className="notes">
          <li>
            <strong>高光 / 遮挡 / U 位移动</strong>：属于 OPTICS/SENSOR 组轴的真实成像条件变化，需要重新成像；
            页面在算子表里把 stage 原样显示，便于判断是否触碰了成像链。
          </li>
          <li>
            <strong>G08</strong>：观测重建伪表面。应当在 <code className="mono">source_role=observed</code> 下使用；
            后端 recipe 编译结果会给出真实节点，clean/Physical 是否变化由后端决定，本页不做前端模拟。
          </li>
          <li>
            <strong>强度零</strong>：level=0 与 baseline 必须同源；用 <code className="mono">basis_policy</code> 表达，
            校验结果会在“校验结果”面板显示编译后的节点。
          </li>
        </ul>
      </SectionCard>
    </>
  );
}
