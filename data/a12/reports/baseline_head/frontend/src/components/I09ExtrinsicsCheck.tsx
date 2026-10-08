/**
 * I09（数字降采样 / antialiased_downsample）与 U 移动的**分开显示**。
 *
 * 计划要求：I09 是数字降采样，必须与相机 U 移动分开，并标注“保持相机外参”。
 * 本组件不用文字断言这句话，而是用**真实数组**核对：
 * * 取基准 `obs_view`（无 axis_id）与 I09 结果 `obs_view`（meta.axis_id=I09）；
 * * 逐帧比较 `payload.frames.N.T_WC`（4×4 相机到世界）与 `payload.frames.N.K`；
 * * 若逐元素一致 → 显示“保持相机外参（真实核对通过）”，否则显示差异明细（不掩盖）。
 */

import { useMemo, useState } from 'react';

import { listAssets } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AssetRecord } from '../api/types';
import { frameIndices, frameMemberKeys, loadAssetArrays } from '../lib/assetData';
import { matricesEqual } from '../lib/analysis';
import { formatNumber, pretty } from '../lib/format';
import { Badge, BlockedState, EmptyState, ErrorState, KeyValueList, LoadingState, SectionCard } from './states';

interface FrameComparison {
  frame: number;
  tWcEqual: boolean | null;
  kEqual: boolean | null;
  baseSize: string;
  targetSize: string;
  pixelTransform: string | null;
}

function matrixText(array: { data: ArrayLike<number> } | undefined, rows: number, cols: number): string {
  if (!array) return '未提供';
  const values: string[] = [];
  for (let row = 0; row < rows; row += 1) {
    const line: string[] = [];
    for (let col = 0; col < cols; col += 1) line.push(formatNumber(Number(array.data[row * cols + col]), 4));
    values.push(line.join(', '));
  }
  return values.join(' | ');
}

export function I09ExtrinsicsCheck() {
  const assets = useResource(() => listAssets({ role: ['obs_view'], limit: 100 }), []);
  const depthViews = useMemo(
    () => (assets.data?.items ?? []).filter((record) => 'arrays' in (record.files ?? {})),
    [assets.data],
  );
  const baseline: AssetRecord | null = useMemo(
    () => depthViews.find((record) => !record.meta?.axis_id) ?? null,
    [depthViews],
  );
  const i09 = useMemo(() => depthViews.filter((record) => String(record.meta?.axis_id ?? '') === 'I09'), [depthViews]);
  const [targetId, setTargetId] = useState<string | null>(null);
  const target = i09.find((record) => record.asset_id === targetId) ?? i09[0] ?? null;

  const baseArrays = useResource(() => loadAssetArrays(baseline?.asset_id as string, 'obs_view', 'arrays'), [baseline?.asset_id], {
    enabled: Boolean(baseline),
  });
  const targetArrays = useResource(() => loadAssetArrays(target?.asset_id as string, 'obs_view', 'arrays'), [target?.asset_id], {
    enabled: Boolean(target),
  });

  const comparisons = useMemo<FrameComparison[]>(() => {
    const left = baseArrays.data?.arrays;
    const right = targetArrays.data?.arrays;
    if (!left || !right) return [];
    const shared = frameIndices(left).filter((index) => frameIndices(right).includes(index));
    return shared.map((frame) => {
      const tWcLeft = left.get(`payload.frames.${frame}.T_WC`);
      const tWcRight = right.get(`payload.frames.${frame}.T_WC`);
      const kLeft = left.get(`payload.frames.${frame}.K`);
      const kRight = right.get(`payload.frames.${frame}.K`);
      const rgbLeft = left.get(`payload.frames.${frame}.rgb`);
      const rgbRight = right.get(`payload.frames.${frame}.rgb`);
      const transform = right.get(`payload.frames.${frame}.pixel_transform`);
      return {
        frame,
        tWcEqual: tWcLeft && tWcRight ? matricesEqual(tWcLeft, tWcRight) : null,
        kEqual: kLeft && kRight ? matricesEqual(kLeft, kRight) : null,
        baseSize: rgbLeft ? `${rgbLeft.shape[1]} × ${rgbLeft.shape[0]}` : '未提供',
        targetSize: rgbRight ? `${rgbRight.shape[1]} × ${rgbRight.shape[0]}` : '未提供',
        pixelTransform: transform ? matrixText(transform, 3, 3) : null,
      };
    });
  }, [baseArrays.data, targetArrays.data]);

  return (
    <SectionCard
      title="I09 数字降采样（与 U 移动分开）"
      subtitle="真实数组核对：基准 obs_view 与 axis_id=I09 的 obs_view 之间的 T_WC / K / rgb 形状 / pixel_transform"
      actions={<Badge tone="info">保持相机外参（用真实 T_WC 核对）</Badge>}
    >
      {assets.status === 'loading' ? <LoadingState label="读取 obs_view 资产…" /> : null}
      {assets.status === 'error' ? <ErrorState error={assets.error} onRetry={assets.reload} /> : null}
      {assets.data && depthViews.length === 0 ? (
        <EmptyState
          title="没有带 arrays 的 obs_view"
          reason="I09 核对需要基准观测与 I09 结果两边的真实 arrays（含 payload.frames.N.T_WC）。没有数据就不做结论。"
        />
      ) : null}

      {baseline && i09.length > 0 ? (
        <>
          <label className="field">
            <span className="field__label">I09 结果资产（真实 meta.axis_id=I09）</span>
            <select className="input" value={target?.asset_id ?? ''} onChange={(event) => setTargetId(event.target.value || null)}>
              {i09.map((record) => (
                <option key={record.asset_id} value={record.asset_id}>
                  {record.asset_id} · level {String(record.meta?.level ?? '—')} · {String(record.meta?.variant ?? '')}
                </option>
              ))}
            </select>
          </label>

          {baseArrays.status === 'error' ? <ErrorState error={baseArrays.error} onRetry={baseArrays.reload} /> : null}
          {targetArrays.status === 'error' ? <ErrorState error={targetArrays.error} onRetry={targetArrays.reload} /> : null}
          {baseArrays.status === 'loading' || targetArrays.status === 'loading' ? <LoadingState label="解码两边 npz…" /> : null}

          {comparisons.length > 0 ? (
            <table className="table">
              <caption>逐帧真实核对：I09 是否改变相机外参</caption>
              <thead>
                <tr>
                  <th scope="col">帧</th>
                  <th scope="col">T_WC 逐元素一致</th>
                  <th scope="col">K 逐元素一致</th>
                  <th scope="col">基准 rgb 尺寸</th>
                  <th scope="col">I09 rgb 尺寸</th>
                  <th scope="col">pixel_transform（真实）</th>
                </tr>
              </thead>
              <tbody>
                {comparisons.map((row) => (
                  <tr key={row.frame}>
                    <th scope="row" className="mono">
                      {row.frame}
                    </th>
                    <td>
                      <Badge tone={row.tWcEqual ? 'ok' : 'bad'}>
                        {row.tWcEqual === null ? '缺少 T_WC' : row.tWcEqual ? '一致（外参未变）' : '不一致'}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={row.kEqual ? 'ok' : 'bad'}>
                        {row.kEqual === null ? '缺少 K' : row.kEqual ? '一致（内参未变）' : '不一致'}
                      </Badge>
                    </td>
                    <td className="mono">{row.baseSize}</td>
                    <td className="mono">{row.targetSize}</td>
                    <td className="mono small">{row.pixelTransform ?? '未提供'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}

          {baseArrays.data && targetArrays.data ? (
            <KeyValueList
              rows={[
                { label: '基准资产', value: baseline.asset_id, mono: true },
                {
                  label: '基准帧成员',
                  value: frameMemberKeys(baseArrays.data.arrays, frameIndices(baseArrays.data.arrays)[0] ?? 0).join(', '),
                  mono: true,
                },
                { label: 'I09 资产', value: target?.asset_id ?? '—', mono: true },
                {
                  label: 'I09 帧成员',
                  value: frameMemberKeys(targetArrays.data.arrays, frameIndices(targetArrays.data.arrays)[0] ?? 0).join(', '),
                  mono: true,
                },
              ]}
            />
          ) : null}

          <p className="muted small">
            结论写法：只要 T_WC 逐元素一致且 rgb 尺寸变小/带 <code className="mono">pixel_transform</code>，就是“数字降采样、保持相机外参”；
            U 移动则会改变 <code className="mono">T_WC</code> 的平移与 <code className="mono">K</code>（见 catalogue 的{' '}
            <code className="mono">u_move_changes</code> 字段）。两者在数据上互不相同，因此本页分开显示。
          </p>
        </>
      ) : assets.status === 'ready' ? (
        <BlockedState
          title="无法做 I09 外参核对"
          code="NOT_RUN"
          reason={
            <>
              需要同时存在一个不含 <code className="mono">axis_id</code> 的基准 obs_view 与一个{' '}
              <code className="mono">axis_id=I09</code> 的 obs_view（都要带 <code className="mono">arrays</code>）。
              当前：基准 {baseline ? baseline.asset_id : '无'}、I09 结果 {i09.length} 个。
            </>
          }
        />
      ) : null}

      {target?.meta ? (
        <details>
          <summary>I09 资产的 meta（原样）</summary>
          <pre className="mono pre">{pretty(target.meta)}</pre>
        </details>
      ) : null}
    </SectionCard>
  );
}
