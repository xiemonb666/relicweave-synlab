/**
 * DegradationPairPanel —— 退化预览的「L0（真恒等） vs Ln」并排面板。
 *
 * 数据来源（全部真实）：
 * * `GET /synthesis/degradation-pairs` —— 同一 axis 的 level=0 与 level=n 资产、它们的
 *   `basis_id` / `source_asset_id` / `meta.measured`，以及后端按 `measured` 逐键相减得到的
 *   `deltas`；
 * * `GET /synthesis/inventory` —— 哪些轴已经物化（`degradation_axes`），未物化的轴显示 NA；
 * * `GET /research/assets/{id}/truth?include_arrays=true` —— 该资产真实存在的数组键名，
 *   用来定位真实 RGB 帧（研究角色专属；部署会话下该路由不挂载，面板会显示真实的 403）；
 * * `GET /assets/{id}/files/{role}?key=arrays` —— 数组字节（`RgbFrameView` 在浏览器里解码）。
 *
 * 诚实规则：
 * * 没有 level 0 就**不并排**：左栏显示「L0 未物化」+ 补齐命令，而不是拿 level 1 冒充 baseline；
 * * `basis_id` 不一致时明确写出「这不是 paired 比较」，差值照原样显示但加了说明；
 * * 未物化的轴不显示任何数值（显示 NA）。
 */

import { useEffect, useMemo, useState } from 'react';

import { getDegradationPairs, getResearchTruth, getSynthesisInventory } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { DegradationPairsResponse, SynthesisInventoryResponse } from '../api/types';
import { formatNumber } from '../lib/format';
import { FailureCard, failureFromError } from './AsyncOperation';
import { MeasuredQualityTable, type QualityRow } from './MeasuredQualityTable';
import { RgbFrameView, declaredOrFirstFrame } from './RgbFrameView';
import { Badge, BlockedState, EmptyState, ErrorState, KeyValueList, LoadingState, SectionCard, Tabs } from './states';

const GROUP_ORDER = ['P', 'I', 'G', 'X'];

function groupOf(axisId: string): string {
  const prefix = axisId.charAt(0).toUpperCase();
  return GROUP_ORDER.includes(prefix) ? prefix : 'X';
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** 逐键实测差值表（值来自后端 `deltas`，本组件只做格式化）。 */
function DeltaTable({ deltas }: { deltas: DegradationPairsResponse['pairs'][number]['deltas'] }) {
  if (deltas.length === 0) {
    return (
      <EmptyState
        title="这两级都没有 meta.measured"
        reason="退化阶段没有写 measured 字段时无法给出真实变化量；本表不会用参数档位反推一个数字。"
      />
    );
  }
  return (
    <div className="tablewrap">
      <table className="table table--metrics">
        <caption>measured 变化量（L0 → Ln，逐键相减，后端计算）</caption>
        <thead>
          <tr>
            <th scope="col">measured 键</th>
            <th scope="col">L0</th>
            <th scope="col">Ln</th>
            <th scope="col">变化量</th>
          </tr>
        </thead>
        <tbody>
          {deltas.map((row) => (
            <tr key={row.key}>
              <th scope="row" className="mono">{row.key}</th>
              <td className="mono">{row.from === null ? '未提供' : formatNumber(row.from, 6)}</td>
              <td className="mono">{row.to === null ? '未提供' : formatNumber(row.to, 6)}</td>
              <td className="mono">
                {row.delta === null ? (
                  <Badge tone="warn">不可比</Badge>
                ) : (
                  <span className={row.delta === 0 ? 'mono' : 'mono strong'}>
                    {row.delta > 0 ? '+' : ''}
                    {formatNumber(row.delta, 6)}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AxisSide({
  title,
  side,
  assetKeys,
  role,
}: {
  title: string;
  side: DegradationPairsResponse['pairs'][number]['level_0'];
  assetKeys: string[] | null;
  role: string;
}) {
  const rgbKey = useMemo(() => declaredOrFirstFrame(assetKeys), [assetKeys]);
  if (!side) {
    return (
      <div className="pairside pairside--missing">
        <h4>{title}</h4>
        <BlockedState
          title="这一级没有物化资产"
          code="LEVEL_NOT_MATERIALIZED"
          reason={
            <>
              后端返回 null：该 (axis, basis, source) 组合下没有这一级的退化资产。
              补齐命令见下方「未物化轴」说明；本面板不用另一级的数据顶替。
            </>
          }
        />
      </div>
    );
  }
  const rows: QualityRow[] = Object.entries(side.measured).map(([key, value]) => ({
    key,
    label: key,
    value: asNumber(value) === null ? (value === null ? null : String(value)) : formatNumber(asNumber(value), 6),
    source: 'GET /synthesis/degradation-pairs → meta.measured',
    flag: value === null || value === undefined ? 'missing' : null,
  }));
  return (
    <div className="pairside">
      <h4>
        {title}
        <Badge tone={side.identity ? 'ok' : 'info'}>
          {side.identity === true ? 'identity=true（真恒等）' : `identity=${String(side.identity)}`}
        </Badge>
        <Badge tone="neutral">level={String(side.level)}</Badge>
      </h4>
      <KeyValueList
        rows={[
          { label: 'asset_id', value: side.asset_id, mono: true },
          { label: 'role', value: side.role, mono: true },
          { label: 'basis_id', value: side.basis_id ?? '未提供', mono: true },
          { label: 'source_asset_id', value: String(side.meta.source_asset_id ?? '未提供'), mono: true },
          { label: 'variant', value: String(side.meta.variant ?? '—') },
          { label: 'realized', value: String(side.realized) },
        ]}
      />
      <RgbFrameView
        assetId={side.asset_id}
        role={role}
        rgbKey={rgbKey}
        label={`${side.asset_id} 的真实帧`}
        height={200}
      />
      <MeasuredQualityTable
        rows={rows}
        caption={`${side.asset_id} 的 meta.measured（后端原样）`}
        emptyTitle="该资产没有 measured"
        emptyReason="退化阶段未写 measured，这一级就没有可比较的实测量。"
      />
      <details>
        <summary>meta 原文（后端原样）</summary>
        <pre className="mono pre">{JSON.stringify(side.meta, null, 2)}</pre>
      </details>
    </div>
  );
}

export function DegradationPairPanel({ onSelectRun }: { onSelectRun?: (runId: string) => void }) {
  const inventory = useResource((signal) => getSynthesisInventory(signal), []);
  const [axisId, setAxisId] = useState<string | null>(null);
  const [group, setGroup] = useState('P');
  const pairs = useResource(
    (signal) => getDegradationPairs(axisId, signal),
    [axisId],
    { enabled: axisId !== null },
  );

  const axes: SynthesisInventoryResponse['degradation_axes'] = inventory.data?.degradation_axes ?? [];
  const materialized = axes.filter((entry) => entry.materialized);
  const grouped = useMemo(() => {
    const map = new Map<string, typeof materialized>();
    for (const entry of materialized) {
      const key = groupOf(entry.axis_id);
      map.set(key, [...(map.get(key) ?? []), entry]);
    }
    return map;
  }, [materialized]);

  const selected = axisId ? materialized.find((entry) => entry.axis_id === axisId) ?? null : null;
  const selectedPairs = pairs.data?.pairs ?? [];
  const pair = selectedPairs[0] ?? null;

  // 真实数组键名：研究角色读 truth 路由；部署会话下这里会显示真实的 403。
  const l0Id = pair?.level_0?.asset_id ?? null;
  const lnId = pair?.level_n?.asset_id ?? null;
  const l0Role = pair?.level_0?.role ?? '';
  const lnRole = pair?.level_n?.role ?? '';
  const l0Truth = useResource(
    (signal) => getResearchTruth(l0Id as string, true, signal),
    [l0Id],
    { enabled: Boolean(l0Id) },
  );
  const lnTruth = useResource(
    (signal) => getResearchTruth(lnId as string, true, signal),
    [lnId],
    { enabled: Boolean(lnId) },
  );

  useEffect(() => {
    if (axisId !== null) return;
    const first = materialized.find((entry) => groupOf(entry.axis_id) === group) ?? materialized[0];
    if (first) setAxisId(first.axis_id);
  }, [materialized, axisId, group]);

  return (
    <SectionCard
      title="L0（真恒等）与 Ln 并排预览（同 basis、同 source）"
      subtitle="GET /synthesis/degradation-pairs —— 配对与 deltas 由后端从 meta 计算，前端只格式化"
      actions={
        <button
          type="button"
          className="btn btn--tiny"
          onClick={() => {
            inventory.reload();
            pairs.reload();
          }}
          disabled={inventory.refreshing || pairs.refreshing}
        >
          {inventory.refreshing || pairs.refreshing ? '刷新中…' : '刷新配对'}
        </button>
      }
    >
      {inventory.status === 'loading' ? <LoadingState label="读取退化轴物化情况…" /> : null}
      {inventory.status === 'error' ? (
        <FailureCard
          title="退化配对读取失败"
          failure={failureFromError(inventory.error)}
          onRetry={inventory.reload}
        />
      ) : null}

      {inventory.data ? (
        materialized.length === 0 ? (
          <BlockedState
            title="没有任何已物化的退化轴"
            code="NO_MATERIALIZED_AXIS"
            reason={
              <>
                assets 表里没有任何带 <code className="mono">meta.axis_id</code> 的退化资产，
                因此没有可配对的 L0/Ln。面板不显示任何数值。
              </>
            }
            items={[
              { label: '补齐命令', value: <code className="mono">python -m synlab.api.worker --store-root &lt;store&gt; --once --workspace default</code> },
              { label: '配方', value: 'degrade 阶段的 level=0 与 level=n 需要写进 degraded_recipe_refs' },
            ]}
          />
        ) : (
          <>
            <Tabs
              label="退化轴分组"
              active={group}
              onChange={setGroup}
              tabs={GROUP_ORDER.map((key) => ({
                id: key,
                label: `${key}（${grouped.get(key)?.length ?? 0} 个已物化）`,
                disabledReason: grouped.has(key) ? null : `没有 ${key} 前缀的已物化轴`,
              }))}
            />
            <div className="row">
              <label className="field field--inline">
                <span className="field__label">axis</span>
                <select
                  className="input input--tight"
                  value={axisId ?? ''}
                  aria-label="选择退化轴"
                  onChange={(event) => setAxisId(event.target.value || null)}
                >
                  {(grouped.get(group) ?? []).map((entry) => (
                    <option key={entry.axis_id} value={entry.axis_id}>
                      {entry.axis_id}（level {entry.levels.map((row) => row.level).join('/')}；
                      basis {entry.basis_ids.length}）
                    </option>
                  ))}
                </select>
              </label>
              {selected ? (
                <span className="muted small">
                  <Badge tone={selected.paired_levels ? 'ok' : 'warn'}>
                    {selected.paired_levels ? '存在同 basis 的 L0 与非 0 级' : '缺少 L0 或跨 basis'}
                  </Badge>
                  {selected.note}
                </span>
              ) : null}
            </div>

            <div className="tablewrap">
              <table className="table table--tight">
                <caption>本 store 已物化的轴与档位（来自资产表，未物化的档位就是 NA）</caption>
                <thead>
                  <tr>
                    <th scope="col">axis</th>
                    <th scope="col">level → 资产数（identity 正身）</th>
                    <th scope="col">basis_id 数</th>
                    <th scope="col">paired</th>
                    <th scope="col">选择</th>
                  </tr>
                </thead>
                <tbody>
                  {(grouped.get(group) ?? []).map((entry) => (
                    <tr key={entry.axis_id}>
                      <th scope="row" className="mono">{entry.axis_id}</th>
                      <td className="mono small">
                        {entry.levels.map((row) => `${row.level}:${row.assets}(id${row.identity})`).join(' · ')}
                        {entry.levels.every((row) => row.level !== 0) ? (
                          <Badge tone="warn">level 0 = NA</Badge>
                        ) : null}
                      </td>
                      <td className="mono">{entry.basis_ids.length}</td>
                      <td>
                        <Badge tone={entry.paired_levels ? 'ok' : 'warn'}>
                          {entry.paired_levels ? '是' : '否'}
                        </Badge>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--tiny"
                          onClick={() => setAxisId(entry.axis_id)}
                          disabled={axisId === entry.axis_id}
                        >
                          {axisId === entry.axis_id ? '当前' : '查看 L0/Ln'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {selected && selected.levels.every((row) => row.level !== 0) ? (
              <BlockedState
                title={`${selected.axis_id} 的 level 0 未物化 → 本面板显示 NA`}
                code="LEVEL_0_NOT_MATERIALIZED"
                reason={
                  <>
                    该轴只有 level {selected.levels.map((row) => row.level).join('/')} 的资产。
                    level 0 必须是<b>真恒等</b>（与 baseline 同源、同 basis），所以不能用 level 1 顶替。
                  </>
                }
                items={[
                  {
                    label: '补齐命令',
                    value: (
                      <code className="mono">
                        python -m synlab.api.worker --store-root &lt;store&gt; --once --workspace default
                        （spec.degraded_recipe_refs 需包含 {selected.axis_id} 的 level 0 算子）
                      </code>
                    ),
                  },
                  { label: '已物化 basis', value: <span className="mono">{selected.basis_ids.join(', ') || '未提供'}</span> },
                ]}
              />
            ) : null}
          </>
        )
      ) : null}

      {axisId && pairs.status === 'loading' ? <LoadingState label={`读取 ${axisId} 的配对…`} /> : null}
      {pairs.status === 'error' ? (
        <FailureCard
          title={`${axisId} 配对读取失败`}
          failure={{ ...failureFromError(pairs.error), repro: pairs.data?.repro }}
          onRetry={pairs.reload}
        />
      ) : null}
      {pairs.data && pairs.data.empty_reason && !pair ? (
        <EmptyState title={`${axisId} 没有可配对的 L0/Ln`} reason={pairs.data.empty_reason} />
      ) : null}

      {pair ? (
        <>
          <div className="row">
            <Badge tone={pair.paired ? 'ok' : 'bad'}>
              {pair.paired ? '同 basis（paired）' : 'basis 不一致（非 paired）'}
            </Badge>
            <Badge tone={pair.same_source ? 'ok' : 'warn'}>
              {pair.same_source ? '同 source 资产' : 'source 不同'}
            </Badge>
            <span className="mono small">basis_id={pair.basis_id ?? '未提供'}</span>
            <span className="mono small">source={pair.source_asset_id ?? '未提供'}</span>
            {onSelectRun && pair.level_n?.meta.run_id ? (
              <button
                type="button"
                className="btn btn--tiny"
                onClick={() => onSelectRun(String(pair.level_n?.meta.run_id))}
              >
                选中该 run（{String(pair.level_n?.meta.run_id)}）
              </button>
            ) : null}
          </div>
          <p className="muted small">{pair.note}</p>

          <div className="grid2">
            <AxisSide
              title="L0（baseline，真恒等）"
              side={pair.level_0}
              assetKeys={l0Truth.data?.array_keys ?? null}
              role={l0Role}
            />
            <AxisSide
              title={`Ln（level ${String(pair.level_n?.level ?? '?')}）`}
              side={pair.level_n}
              assetKeys={lnTruth.data?.array_keys ?? null}
              role={lnRole}
            />
          </div>

          {l0Truth.status === 'error' || lnTruth.status === 'error' ? (
            <ErrorState
              error={l0Truth.error ?? lnTruth.error}
              onRetry={() => {
                l0Truth.reload();
                lnTruth.reload();
              }}
              compact
              title="数组键清单读取失败（帧预览会退化为按已知键名尝试）"
            />
          ) : null}

          <DeltaTable deltas={pair.deltas} />

          <p className="muted small">
            并排的 L0 与 Ln 来自两条真实资产记录；差值列是后端按 <code className="mono">meta.measured</code>
            逐键相减的结果，前端不做任何单位换算或插值。arrays 字节由{' '}
            <code className="mono">GET /assets/&#123;id&#125;/files/&#123;role&#125;?key=arrays</code> 提供，
            同一 asset_id 在本会话内只下载一次。
          </p>
        </>
      ) : null}
    </SectionCard>
  );
}
