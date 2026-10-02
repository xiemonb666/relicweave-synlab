/**
 * 真实数组热图：把后端 `arrays` 资产里的 2D 标量场（depth_z / 逐点距离等）直接画出来。
 *
 * 诚实约定：
 * * 只画真实存在的有限值；缺测像素完全透明，并在读数里给出“有效像素数 / 总像素数”；
 * * 色标同时给出数值刻度（不是只靠颜色表意），并提供“前若干项真实数值表”给键盘/读屏用户；
 * * `provenance` 必须由调用方写明这些数字是哪来的（资产 ID + 数组键 + 是否前端计算）。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { drawHeatmap, finiteStats, rgbCss, viridis, type AnyNumberArray } from '../lib/analysis';
import { formatNumber } from '../lib/format';
import { Badge, EmptyState } from './states';

export interface RealArrayHeatmapProps {
  title: string;
  /** 数据来源说明（必须写清资产 ID / 数组键 / 是否前端计算）。 */
  provenance: string;
  values: AnyNumberArray | Float64Array | null;
  width: number;
  height: number;
  mask?: ArrayLike<number> | null;
  unit: string;
  /** 真实样本值表（例如逐点距离最大的若干项）。 */
  samples?: Array<{ label: string; value: number }>;
  maxScale?: number;
  caption?: string;
}

export function RealArrayHeatmap({
  title,
  provenance,
  values,
  width,
  height,
  mask,
  unit,
  samples,
  maxScale = 4,
  caption,
}: RealArrayHeatmapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [scale, setScale] = useState(1);
  const [painted, setPainted] = useState(0);

  const stats = useMemo(() => (values ? finiteStats(values, mask ?? null) : null), [values, mask]);

  const inRange = useMemo(() => {
    if (!values || !mask) return 0;
    let count = 0;
    for (let index = 0; index < values.length; index += 1) if (mask[index]) count += 1;
    return count;
  }, [values, mask]);

  useEffect(() => {
    if (!values || !canvasRef.current || !stats) return;
    setPainted(
      drawHeatmap(canvasRef.current, {
        values,
        width,
        height,
        mask: mask ?? null,
        min: stats.min,
        max: stats.max,
        scale,
      }),
    );
  }, [values, width, height, mask, scale, stats]);

  if (!values || !stats) {
    return (
      <EmptyState
        title={`${title}：没有可绘制的真实数组`}
        reason="该资产的 arrays 里没有对应的标量场（或全部为无效值）。这里不会用零值或示意图代替。"
      />
    );
  }

  return (
    <figure className="realmap">
      <figcaption>
        <strong>{title}</strong>
        <Badge tone="info">真实数组</Badge>
        <span className="muted small">
          {' '}
          {width} × {height} px · 有效 {inRange || stats.n} / {width * height} · 单位 {unit}
        </span>
      </figcaption>
      <p className="muted small">{provenance}</p>
      <div className="realmap__body">
        <canvas ref={canvasRef} role="img" aria-label={`${title}：真实数值热图，范围 ${formatNumber(stats.min, 4)} 到 ${formatNumber(stats.max, 4)} ${unit}`} />
        <div className="realmap__legend">
          <div className="realmap__bar" aria-hidden="true">
            {Array.from({ length: 9 }, (_, index) => (
              <span key={index} style={{ background: rgbCss(viridis(index / 8)) }} />
            ))}
          </div>
          <dl className="kv kv--tight">
            <div className="kv__row">
              <dt>最大值</dt>
              <dd className="mono">
                {formatNumber(stats.max, 4)} {unit}
              </dd>
            </div>
            <div className="kv__row">
              <dt>p99</dt>
              <dd className="mono">
                {formatNumber(stats.p99, 4)} {unit}
              </dd>
            </div>
            <div className="kv__row">
              <dt>p95</dt>
              <dd className="mono">
                {formatNumber(stats.p95, 4)} {unit}
              </dd>
            </div>
            <div className="kv__row">
              <dt>中位数</dt>
              <dd className="mono">
                {formatNumber(stats.p50, 4)} {unit}
              </dd>
            </div>
            <div className="kv__row">
              <dt>平均值</dt>
              <dd className="mono">
                {formatNumber(stats.mean, 4)} {unit}
              </dd>
            </div>
            <div className="kv__row">
              <dt>最小值</dt>
              <dd className="mono">
                {formatNumber(stats.min, 4)} {unit}
              </dd>
            </div>
            <div className="kv__row">
              <dt>有效样本 n</dt>
              <dd className="mono">{stats.n}</dd>
            </div>
          </dl>
          <label className="field field--inline">
            <span className="field__label">显示抽样</span>
            <select className="input input--tight" value={scale} onChange={(event) => setScale(Number(event.target.value))}>
              {Array.from({ length: maxScale }, (_, index) => index + 1).map((value) => (
                <option key={value} value={value}>
                  每 {value}×{value} 像素取 1 个（不平均）
                </option>
              ))}
            </select>
          </label>
          <p className="muted small">
            实际绘制 {painted} 个真实像元；未绘制的位置是缺测或抽样跳过，不是 0。颜色之外另有上方数值刻度。
          </p>
        </div>
      </div>
      {caption ? <p className="muted small">{caption}</p> : null}
      {samples && samples.length > 0 ? (
        <details>
          <summary>最大若干项真实数值（读数替代颜色）</summary>
          <table className="table table--tight">
            <caption>{title} · 逐项真实数值</caption>
            <thead>
              <tr>
                <th scope="col">位置 / 索引</th>
                <th scope="col">
                  数值（{unit}）
                </th>
              </tr>
            </thead>
            <tbody>
              {samples.map((sample) => (
                <tr key={sample.label}>
                  <th scope="row" className="mono">
                    {sample.label}
                  </th>
                  <td className="mono">{formatNumber(sample.value, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </figure>
  );
}

/** 取一维数组里最大的若干项的索引与数值（真实值，不做插值）。 */
export function topIndices(values: ArrayLike<number>, count: number): Array<{ index: number; value: number }> {
  const kept: Array<{ index: number; value: number }> = [];
  for (let index = 0; index < values.length; index += 1) {
    const value = Number(values[index]);
    if (Number.isFinite(value)) kept.push({ index, value });
  }
  kept.sort((a, b) => b.value - a.value);
  return kept.slice(0, count);
}
