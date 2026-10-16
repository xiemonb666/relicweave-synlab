/**
 * U05 退化对比的真实差异视图：误差热图 + 点云叠加。
 *
 * 数据来源（全部真实）：
 * * 点云模式：`obs_fused_geometry` 资产的 `payload.points` / `payload.reference_points` /
 *   `payload.point_valid` / `payload.roi`，逐点距离由前端计算；
 * * 深度模式：两个 `obs_view` 资产的 `payload.frames.N.depth_z`（mm）逐像素绝对差，
 *   `depth_z > 0` 决定有效像素。
 *
 * 明确标注：**前端由真实 depth/points 计算，非后端误差场**。后端 `meta.measured` 原样并排展示。
 */

import { useMemo, useState } from 'react';

import { listAssets } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AssetRecord } from '../api/types';
import { absoluteDifference, finiteStats } from '../lib/analysis';
import { frameIndices, frameMemberKeys, loadAssetArrays, npzPoints, npzScalar2d, npzVector } from '../lib/assetData';
import { formatNumber } from '../lib/format';
import { PointCloudDiffView } from './PointCloudDiffView';
import { RealArrayHeatmap, topIndices } from './RealArrayHeatmap';
import { Badge, BlockedState, EmptyState, ErrorState, KeyValueList, LoadingState, SectionCard, Tabs } from './states';

function labelOf(record: AssetRecord): string {
  const meta = record.meta ?? {};
  const bits = [
    String(record.asset_id),
    meta.axis_id ? String(meta.axis_id) : null,
    meta.level !== undefined ? `L${meta.level}` : null,
    meta.variant ? String(meta.variant) : null,
  ].filter(Boolean);
  return bits.join(' · ');
}

function hasArrays(record: AssetRecord): boolean {
  return Object.prototype.hasOwnProperty.call(record.files ?? {}, 'arrays');
}

export function DegradationDiffPanel() {
  const assets = useResource(
    () => listAssets({ role: ['obs_view', 'obs_fused_geometry'], limit: 200, with_total: true }),
    [],
  );
  const [mode, setMode] = useState<'points' | 'depth'>('points');

  const fused = useMemo(
    () => (assets.data?.items ?? []).filter((record) => record.role === 'obs_fused_geometry'),
    [assets.data],
  );
  const views = useMemo(() => (assets.data?.items ?? []).filter((record) => record.role === 'obs_view'), [assets.data]);
  const depthCapable = useMemo(() => views.filter(hasArrays), [views]);
  const baseline = useMemo(() => depthCapable.find((record) => !record.meta?.axis_id) ?? null, [depthCapable]);
  const degraded = useMemo(() => depthCapable.find((record) => Boolean(record.meta?.axis_id)) ?? null, [depthCapable]);

  const [fusedId, setFusedId] = useState<string | null>(null);
  const [baseId, setBaseId] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);

  /**
   * 默认选一个**带退化轴**的点云资产：没有 axis_id 的资产是同一份参考几何，
   * points 与 reference_points 逐点相同（真实差值恒为 0），默认选中它会让面板看起来“没数据”。
   */
  const defaultFused = useMemo(() => {
    const withAxis = fused.filter((record) => Boolean(record.meta?.axis_id));
    const pool = withAxis.length > 0 ? withAxis : fused;
    const sorted = [...pool].sort((a, b) => {
      const axisA = String(a.meta?.axis_id ?? '');
      const axisB = String(b.meta?.axis_id ?? '');
      if (axisA !== axisB) return axisA.localeCompare(axisB);
      return Number(b.meta?.level ?? 0) - Number(a.meta?.level ?? 0);
    });
    return sorted[0]?.asset_id ?? null;
  }, [fused]);

  const effectiveFused = fusedId ?? defaultFused ?? fused[0]?.asset_id ?? null;
  const effectiveBase = baseId ?? baseline?.asset_id ?? depthCapable[0]?.asset_id ?? null;
  const effectiveTarget = targetId ?? degraded?.asset_id ?? depthCapable[1]?.asset_id ?? null;

  const fusedArrays = useResource(() => loadAssetArrays(effectiveFused as string, 'obs_fused_geometry', 'arrays'), [effectiveFused], {
    enabled: Boolean(effectiveFused) && mode === 'points',
  });
  const baseArrays = useResource(() => loadAssetArrays(effectiveBase as string, 'obs_view', 'arrays'), [effectiveBase], {
    enabled: Boolean(effectiveBase) && mode === 'depth',
  });
  const targetArrays = useResource(() => loadAssetArrays(effectiveTarget as string, 'obs_view', 'arrays'), [effectiveTarget], {
    enabled: Boolean(effectiveTarget) && mode === 'depth',
  });

  const fusedRecord = fused.find((record) => record.asset_id === effectiveFused) ?? null;
  const baseRecord = views.find((record) => record.asset_id === effectiveBase) ?? null;
  const targetRecord = views.find((record) => record.asset_id === effectiveTarget) ?? null;

  /* ------------------------------------------------------------ 点云模式 */
  const pointData = useMemo(() => {
    const map = fusedArrays.data?.arrays;
    if (!map) return null;
    return {
      points: npzPoints(map, 'payload.points'),
      reference: npzPoints(map, 'payload.reference_points'),
      valid: npzVector(map, 'payload.point_valid'),
      roi: npzVector(map, 'payload.roi'),
      keys: [...map.keys()].sort(),
    };
  }, [fusedArrays.data]);

  /* ------------------------------------------------------------ 深度模式 */
  const depthFrames = useMemo(() => {
    const baseMap = baseArrays.data?.arrays;
    const targetMap = targetArrays.data?.arrays;
    if (!baseMap || !targetMap) return [] as number[];
    return frameIndices(baseMap).filter((index) => frameIndices(targetMap).includes(index));
  }, [baseArrays.data, targetArrays.data]);

  const activeFrame = depthFrames.includes(frameIndex) ? frameIndex : (depthFrames[0] ?? 0);

  const depthDiff = useMemo(() => {
    const baseMap = baseArrays.data?.arrays;
    const targetMap = targetArrays.data?.arrays;
    if (!baseMap || !targetMap) return null;
    const left = npzScalar2d(baseMap, `payload.frames.${activeFrame}.depth_z`);
    const right = npzScalar2d(targetMap, `payload.frames.${activeFrame}.depth_z`);
    if (!left || !right) return null;
    if (left.width !== right.width || left.height !== right.height) {
      return {
        mismatched: true as const,
        left: { width: left.width, height: left.height },
        right: { width: right.width, height: right.height },
      };
    }
    // 真实有效像素：两边 depth 都是正有限值（渲染器用 NaN/负值表示无效）
    const mask = new Uint8Array(left.width * left.height);
    for (let index = 0; index < mask.length; index += 1) {
      const a = Number(left.data[index]);
      const b = Number(right.data[index]);
      mask[index] = Number.isFinite(a) && Number.isFinite(b) && a > 0 && b > 0 ? 1 : 0;
    }
    const diff = absoluteDifference(left.data, right.data);
    const stats = finiteStats(diff, mask);
    return {
      mismatched: false as const,
      width: left.width,
      height: left.height,
      diff,
      mask,
      stats,
      leftKeys: frameMemberKeys(baseMap, activeFrame),
      rightKeys: frameMemberKeys(targetMap, activeFrame),
    };
  }, [baseArrays.data, targetArrays.data, activeFrame]);

  return (
    <SectionCard
      title="误差热图与点云叠加（真实数组）"
      subtitle="GET /assets?role=obs_view,obs_fused_geometry → GET /assets/{id}/files/{role}?key=arrays（npz 在浏览器内解码）"
      actions={
        <div className="row">
          <Badge tone="warn">前端由真实 depth/points 计算，非后端误差场</Badge>
          <button type="button" className="btn btn--tiny" onClick={assets.reload} disabled={assets.refreshing}>
            {assets.refreshing ? '刷新中…' : '刷新资产'}
          </button>
        </div>
      }
    >
      {assets.status === 'loading' ? <LoadingState label="读取观测资产列表…" /> : null}
      {assets.status === 'error' ? <ErrorState error={assets.error} onRetry={assets.reload} /> : null}

      {assets.data ? (
        <>
          <p className="muted small">
            扫描到 {assets.data.items.length} 个资产（obs_view {views.length} 个，其中含 <code className="mono">arrays</code> 的{' '}
            {depthCapable.length} 个；obs_fused_geometry {fused.length} 个）。后端 total={assets.data.total ?? '未请求'}。
          </p>

          <Tabs
            label="差异视图模式"
            active={mode}
            onChange={(id) => setMode(id as 'points' | 'depth')}
            tabs={[
              {
                id: 'points',
                label: `点云叠加（obs_fused_geometry：${fused.length}）`,
                disabledReason: fused.length === 0 ? '工作区里没有 obs_fused_geometry 资产' : null,
              },
              {
                id: 'depth',
                label: `深度差热图（obs_view 含 arrays：${depthCapable.length}）`,
                disabledReason: depthCapable.length < 2 ? '可比较的 obs_view（含 arrays）少于 2 个' : null,
              },
            ]}
          />

          {mode === 'points' ? (
            fused.length === 0 ? (
              <EmptyState
                title="没有 obs_fused_geometry 资产"
                reason="点云叠加需要后端产出 `obs_fused_geometry`（含 payload.points / payload.reference_points）。空状态不是 0 差异，而是没有数据。"
              />
            ) : (
              <>
                <label className="field">
                  <span className="field__label">选择真实点云资产</span>
                  <select className="input" value={effectiveFused ?? ''} onChange={(event) => setFusedId(event.target.value || null)}>
                    {fused.map((record) => (
                      <option key={record.asset_id} value={record.asset_id}>
                        {labelOf(record)}（{record.qa_status}）
                      </option>
                    ))}
                  </select>
                  <span className="field__hint">
                    轴与 level 来自资产 meta（axis_id / level / variant）；本页不推断它们是哪一档退化。
                  </span>
                </label>
                {fusedArrays.status === 'error' ? (
                  <ErrorState error={fusedArrays.error} onRetry={fusedArrays.reload} title="读取 npz 失败" />
                ) : null}
                {pointData ? (
                  <>
                    <PointCloudDiffView
                      title="观测重建点 vs 同资产参考点"
                      provenance={`资产 ${effectiveFused} 的 payload.points 与 payload.reference_points（单位 mm，frame=${fusedRecord?.frame ?? '未提供'}）。逐点距离由前端计算。`}
                      points={pointData.points}
                      reference={pointData.reference}
                      valid={pointData.valid}
                      roi={pointData.roi}
                      backendMeasured={(fusedRecord?.meta?.measured as Record<string, unknown>) ?? null}
                    />
                    <details>
                      <summary>该资产 arrays 的真实键名（{pointData.keys.length} 个）</summary>
                      <p className="mono small">{pointData.keys.join(', ')}</p>
                    </details>
                  </>
                ) : fusedArrays.status === 'loading' ? (
                  <LoadingState label="下载并解码 npz…" />
                ) : null}
              </>
            )
          ) : depthCapable.length < 2 ? (
            <BlockedState
              title="深度差需要两个含 arrays 的 obs_view 资产"
              code="INSUFFICIENT_ASSETS"
              reason={
                <>
                  当前只有 {depthCapable.length} 个 obs_view 资产带 <code className="mono">arrays</code>。深度差是两个真实资产的{' '}
                  <code className="mono">payload.frames.N.depth_z</code> 逐像素绝对差，缺一个就不画。
                </>
              }
            />
          ) : (
            <>
              <div className="grid2">
                <label className="field">
                  <span className="field__label">基准资产 A（含 arrays）</span>
                  <select className="input" value={effectiveBase ?? ''} onChange={(event) => setBaseId(event.target.value || null)}>
                    {depthCapable.map((record) => (
                      <option key={record.asset_id} value={record.asset_id}>
                        {labelOf(record)}
                      </option>
                    ))}
                  </select>
                  <span className="field__hint">
                    {baseRecord?.meta?.axis_id
                      ? `该资产本身也是退化结果（axis=${String(baseRecord.meta.axis_id)}）`
                      : '该资产没有 axis_id，视为本条流水线的基准观测'}
                  </span>
                </label>
                <label className="field">
                  <span className="field__label">对比资产 B（含 arrays）</span>
                  <select className="input" value={effectiveTarget ?? ''} onChange={(event) => setTargetId(event.target.value || null)}>
                    {depthCapable.map((record) => (
                      <option key={record.asset_id} value={record.asset_id}>
                        {labelOf(record)}
                      </option>
                    ))}
                  </select>
                  <span className="field__hint">
                    {targetRecord?.meta?.axis_id
                      ? `axis=${String(targetRecord.meta.axis_id)} · level=${String(targetRecord.meta.level)} · variant=${String(targetRecord.meta.variant)}`
                      : '该资产没有 axis_id'}
                  </span>
                </label>
              </div>

              {depthFrames.length > 0 ? (
                <label className="field">
                  <span className="field__label">视角帧下标（两个资产共有的真实帧）</span>
                  <select className="input input--tight" value={activeFrame} onChange={(event) => setFrameIndex(Number(event.target.value))}>
                    {depthFrames.map((index) => (
                      <option key={index} value={index}>
                        frame {index}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              {baseArrays.status === 'error' ? <ErrorState error={baseArrays.error} onRetry={baseArrays.reload} /> : null}
              {targetArrays.status === 'error' ? <ErrorState error={targetArrays.error} onRetry={targetArrays.reload} /> : null}
              {baseArrays.status === 'loading' || targetArrays.status === 'loading' ? (
                <LoadingState label="下载并解码两个 npz…" />
              ) : null}

              {depthDiff && depthDiff.mismatched ? (
                <BlockedState
                  title="两个资产的深度图尺寸不同，无法逐像素比较"
                  code="SHAPE_MISMATCH"
                  reason={
                    <>
                      A 的 <code className="mono">depth_z</code> 为 {depthDiff.left.width}×{depthDiff.left.height}，B 为{' '}
                      {depthDiff.right.width}×{depthDiff.right.height}。前端不做缩放对齐（缩放会产生并不存在的对应关系）。
                      请改选同分辨率的一对资产，或查看该轴自己的 <code className="mono">pixel_transform</code>。
                    </>
                  }
                />
              ) : null}

              {depthDiff && !depthDiff.mismatched ? (
                <>
                  <RealArrayHeatmap
                    title={`深度绝对差 |A − B|（frame ${activeFrame}）`}
                    provenance={`A = ${effectiveBase} 的 payload.frames.${activeFrame}.depth_z；B = ${effectiveTarget} 的 payload.frames.${activeFrame}.depth_z；两者都是后端真实深度（mm，相机 z）。差值由前端逐像素计算，不是后端误差场。`}
                    values={depthDiff.diff}
                    mask={depthDiff.mask}
                    width={depthDiff.width}
                    height={depthDiff.height}
                    unit="mm"
                    samples={topIndices(depthDiff.diff, 8).map((row) => ({
                      label: `y=${Math.floor(row.index / depthDiff.width)}, x=${row.index % depthDiff.width}`,
                      value: row.value,
                    }))}
                    caption={`有效像素 = 两边 depth 均为正有限值的像素；其余像素不绘制。A 的成员：${depthDiff.leftKeys.join(', ')}；B 的成员：${depthDiff.rightKeys.join(', ')}。`}
                  />
                  <KeyValueList
                    rows={[
                      { label: 'A 资产', value: effectiveBase ?? '—', mono: true },
                      { label: 'B 资产', value: effectiveTarget ?? '—', mono: true },
                      { label: '帧下标', value: activeFrame, mono: true },
                      {
                        label: '差异 > 0 的像素数',
                        value: depthDiff.diff.reduce((count, value) => (Number.isFinite(value) && value > 0 ? count + 1 : count), 0),
                        mono: true,
                      },
                      { label: '中位绝对差', value: `${formatNumber(depthDiff.stats?.p50 ?? 0, 5)} mm`, mono: true },
                    ]}
                  />
                </>
              ) : null}
            </>
          )}
        </>
      ) : null}
    </SectionCard>
  );
}
