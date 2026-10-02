/**
 * 真实点云偏差叠加：把 `obs_fused_geometry` 资产里的 `payload.points`（观测重建点）与
 * `payload.reference_points`（同一资产内的参考点，逐点对应）求欧氏距离，画成点云叠加图。
 *
 * 诚实约定：
 * * 逐点距离由**前端**用真实数组计算 —— 页面上必须写明“非后端误差场”，并把后端
 *   `meta.measured` 的原始数值并排展示，两者是否一致由读者判断；
 * * 不做平滑、插值、补点；无效点（point_valid=0 或参考点非有限）不绘制，也不当 0；
 * * 位置读数用真实毫米坐标，投影轴显式写出。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { finiteStats, pointDistances, projectPoints, rgbCss, viridis, type ProjectionAxis } from '../lib/analysis';
import { formatNumber, pretty } from '../lib/format';
import { Badge, EmptyState, KeyValueList, Tabs } from './states';

export interface PointCloudDiffViewProps {
  title: string;
  provenance: string;
  points: Float64Array | null;
  reference: Float64Array | null;
  valid?: ArrayLike<number> | null;
  roi?: ArrayLike<number> | null;
  /** 后端 `meta.measured`（原样展示，用于与前端计算值对照）。 */
  backendMeasured?: Record<string, unknown> | null;
  height?: number;
}

const AXES: Array<{ id: ProjectionAxis; label: string }> = [
  { id: 'iso', label: '等轴测' },
  { id: 'xy', label: 'XY（俯视）' },
  { id: 'xz', label: 'XZ（正视）' },
  { id: 'yz', label: 'YZ（侧视）' },
];

export function PointCloudDiffView({
  title,
  provenance,
  points,
  reference,
  valid,
  roi,
  backendMeasured,
  height = 320,
}: PointCloudDiffViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [axis, setAxis] = useState<ProjectionAxis>('iso');
  const [drawn, setDrawn] = useState(0);

  const distances = useMemo(() => {
    if (!points || !reference) return null;
    return pointDistances(points, reference, 3);
  }, [points, reference]);

  const mask = useMemo(() => {
    if (!distances) return null;
    const out = new Uint8Array(distances.length);
    for (let index = 0; index < distances.length; index += 1) {
      const finite = Number.isFinite(distances[index]);
      const flag = valid ? Boolean(valid[index]) : true;
      out[index] = finite && flag ? 1 : 0;
    }
    return out;
  }, [distances, valid]);

  const stats = useMemo(() => (distances ? finiteStats(distances, mask) : null), [distances, mask]);

  const top = useMemo(() => {
    if (!distances || !mask) return [];
    const kept: Array<{ index: number; value: number }> = [];
    for (let index = 0; index < distances.length; index += 1) {
      if (mask[index]) kept.push({ index, value: distances[index] });
    }
    kept.sort((a, b) => b.value - a.value);
    return kept.slice(0, 10);
  }, [distances, mask]);

  const roiCount = useMemo(() => {
    if (!roi) return null;
    let count = 0;
    for (let index = 0; index < roi.length; index += 1) if (roi[index]) count += 1;
    return count;
  }, [roi]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !points || !distances || !mask || !stats) return;
    const projection = projectPoints(points, axis);
    const width = canvas.clientWidth || 640;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.fillStyle = '#11151c';
    context.fillRect(0, 0, width, height);

    let minU = Infinity;
    let maxU = -Infinity;
    let minV = Infinity;
    let maxV = -Infinity;
    for (let index = 0; index < projection.u.length; index += 1) {
      if (!mask[index]) continue;
      minU = Math.min(minU, projection.u[index]);
      maxU = Math.max(maxU, projection.u[index]);
      minV = Math.min(minV, projection.v[index]);
      maxV = Math.max(maxV, projection.v[index]);
    }
    if (!Number.isFinite(minU)) return;
    const pad = 12;
    const spanU = maxU - minU || 1;
    const spanV = maxV - minV || 1;
    const sx = (width - pad * 2) / spanU;
    const sy = (height - pad * 2) / spanV;
    const step = Math.max(1, Math.ceil(projection.u.length / 40000));
    const span = stats.max - stats.min;
    let count = 0;
    for (let index = 0; index < projection.u.length; index += step) {
      if (!mask[index]) continue;
      const t = span > 0 ? (distances[index] - stats.min) / span : 0;
      context.fillStyle = rgbCss(viridis(t));
      const px = pad + (projection.u[index] - minU) * sx;
      const py = height - pad - (projection.v[index] - minV) * sy;
      context.fillRect(px, py, 1.6, 1.6);
      count += 1;
    }
    setDrawn(count);
  }, [points, distances, mask, stats, axis, height]);

  if (!points || !reference || !distances || !stats || !mask) {
    return (
      <EmptyState
        title={`${title}：没有可比较的真实点集`}
        reason="该资产里同时需要 `payload.points` 与 `payload.reference_points`（均为 (N,3) mm）。缺一个就不画：前端不会用另一份数据的形状去凑。"
      />
    );
  }

  const total = distances.length;
  const validCount = stats.n;
  const invalid = total - validCount;
  const identical = stats.max - stats.min < 1e-12;

  return (
    <figure className="realmap">
      <figcaption>
        <strong>{title}</strong>
        <Badge tone="info">前端由真实 depth/points 计算，非后端误差场</Badge>
      </figcaption>
      <p className="muted small">{provenance}</p>
      {identical ? (
        <p className="muted small" role="status">
          真实结果：该资产的 <code className="mono">payload.points</code> 与{' '}
          <code className="mono">payload.reference_points</code> 逐点完全相同，因此逐点距离恒为{' '}
          {formatNumber(stats.max, 6)} mm（不是渲染失败，也不是缺数据）。想看非零差异请选择一个带{' '}
          <code className="mono">axis_id</code> 的退化资产（例如 G05 抽面、G03 补洞）。
        </p>
      ) : null}
      <Tabs label="投影轴" tabs={AXES} active={axis} onChange={(id) => setAxis(id as ProjectionAxis)} />
      <div className="realmap__body">
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height }}
          role="img"
          aria-label={`点云偏差叠加（${axis}）：逐点距离 ${formatNumber(stats.min, 4)} 到 ${formatNumber(stats.max, 4)} mm`}
        />
        <div className="realmap__legend">
          <div className="realmap__bar" aria-hidden="true">
            {Array.from({ length: 9 }, (_, index) => (
              <span key={index} style={{ background: rgbCss(viridis(index / 8)) }} />
            ))}
          </div>
          <p className="muted small">
            色标：低（{formatNumber(stats.min, 4)} mm）→ 高（{formatNumber(stats.max, 4)} mm）
          </p>
          <KeyValueList
            rows={[
              { label: '总点数', value: total, mono: true },
              { label: '有效点数（point_valid 且距离有限）', value: validCount, mono: true },
              { label: '未绘制点数', value: invalid, mono: true },
              { label: '本帧绘制', value: drawn, mono: true },
              { label: '逐点距离 均值', value: `${formatNumber(stats.mean, 4)} mm`, mono: true },
              { label: '逐点距离 p50', value: `${formatNumber(stats.p50, 4)} mm`, mono: true },
              { label: '逐点距离 p95', value: `${formatNumber(stats.p95, 4)} mm`, mono: true },
              { label: '逐点距离 最大值', value: `${formatNumber(stats.max, 4)} mm`, mono: true },
              ...(roiCount === null ? [] : [{ label: 'roi=True 点数', value: roiCount, mono: true }]),
            ]}
          />
          <p className="muted small">
            参考点来自同一资产内的 `payload.reference_points`；距离是逐点欧氏范数（mm）。这是前端算式，
            不是后端误差场。
          </p>
        </div>
      </div>

      <details>
        <summary>按真实点索引列出最大的 10 个逐点距离</summary>
        <table className="table table--tight">
          <caption>{title} · 逐点距离（真实索引）</caption>
          <thead>
            <tr>
              <th scope="col">点索引</th>
              <th scope="col">观测点 (mm)</th>
              <th scope="col">参考点 (mm)</th>
              <th scope="col">距离（mm）</th>
            </tr>
          </thead>
          <tbody>
            {top.map((row) => (
              <tr key={row.index}>
                <th scope="row" className="mono">
                  {row.index}
                </th>
                <td className="mono small">
                  {[0, 1, 2].map((dim) => formatNumber(points[row.index * 3 + dim], 2)).join(', ')}
                </td>
                <td className="mono small">
                  {[0, 1, 2].map((dim) => formatNumber(reference[row.index * 3 + dim], 2)).join(', ')}
                </td>
                <td className="mono">{formatNumber(row.value, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {backendMeasured && Object.keys(backendMeasured).length > 0 ? (
        <details open>
          <summary>后端 `meta.measured`（原样，供与前端计算值对照）</summary>
          <pre className="mono pre">{pretty(backendMeasured)}</pre>
        </details>
      ) : null}
    </figure>
  );
}
