/**
 * MetricChart —— 轻量自绘 SVG 图表（计划 20.14.6：无点不画线，tooltip 显示 n/单位/区间/失败）。
 *
 * 刻意不引入 echarts：图表只需要“实测点 + 缺口 + 样本数”，自绘 SVG 能保证
 * 缺数据处**断线**而不是插值成光滑曲线，也不会为了好看把失败样本丢掉。
 *
 * `MetricChart`：折线/散点；`MetricHeatmap`：N×Q（或 train-Q × test-Q）矩阵。
 */

import { useMemo, useState } from 'react';

import { formatNumber } from '../lib/format';
import { Badge, EmptyState } from './states';

export interface MetricPoint {
  x: number;
  /** null 表示后端明确没有这个点的值（缺失/未运行），绘图时断线。 */
  y: number | null;
  /** 样本数（后端提供就显示）。 */
  n?: number | null;
  /** 失败/不适用标记，原样来自后端。 */
  flag?: 'failed' | 'na' | 'missing' | null;
  /** 该点对应的产物 ref（例如 per_query 记录 id），点击时回传。 */
  ref?: string | null;
  label?: string | null;
}

export interface MetricSeries {
  name: string;
  unit?: string | null;
  color?: string;
  points: MetricPoint[];
}

export interface MetricChartProps {
  series: MetricSeries[];
  xLabel: string;
  yLabel: string;
  caption?: string;
  emptyReason?: React.ReactNode;
  onPointSelect?: (point: MetricPoint & { series: string }) => void;
  height?: number;
  /** 母体区间（后端给出的 interval），按 x 值区间画一条带。 */
  intervalBand?: { from: number; to: number; label: string } | null;
}

const PALETTE = ['#63b3ed', '#f6ad55', '#68d391', '#e53e3e', '#b794f4', '#4fd1c5'];

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const span = max - min;
  const step = 10 ** Math.floor(Math.log10(span / count));
  const normalized = span / count / step;
  const factor = normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1;
  const finalStep = factor * step;
  const start = Math.ceil(min / finalStep) * finalStep;
  const ticks: number[] = [];
  for (let value = start; value <= max + finalStep * 0.5; value += finalStep) ticks.push(Number(value.toFixed(6)));
  return ticks;
}

export function MetricChart({
  series,
  xLabel,
  yLabel,
  caption,
  emptyReason,
  onPointSelect,
  height = 240,
  intervalBand,
}: MetricChartProps) {
  const [hover, setHover] = useState<{ series: string; point: MetricPoint } | null>(null);
  const width = 640;
  const padding = { top: 16, right: 16, bottom: 34, left: 56 };

  const allPoints = series.flatMap((item) => item.points);
  const validPoints = allPoints.filter((point) => point.y !== null && Number.isFinite(point.y));

  const bounds = useMemo(() => {
    const xs = allPoints.map((point) => point.x).filter(Number.isFinite);
    const ys = validPoints.map((point) => point.y as number);
    if (xs.length === 0 || ys.length === 0) return null;
    return {
      xMin: Math.min(...xs),
      xMax: Math.max(...xs),
      yMin: Math.min(0, ...ys),
      yMax: Math.max(...ys),
    };
  }, [allPoints, validPoints]);

  if (allPoints.length === 0 || !bounds) {
    return (
      <EmptyState
        title="没有可绘制的实测点"
        reason={
          emptyReason ?? (
            <>
              后端没有返回任何曲线点。本组件**不会**在没有点的情况下画线（计划 20.14.6）；未运行的诊断/训练不会生成曲线。
            </>
          )
        }
      />
    );
  }

  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const scaleX = (value: number) =>
    padding.left + (bounds.xMax === bounds.xMin ? plotWidth / 2 : ((value - bounds.xMin) / (bounds.xMax - bounds.xMin)) * plotWidth);
  const scaleY = (value: number) =>
    padding.top + plotHeight - (bounds.yMax === bounds.yMin ? plotHeight / 2 : ((value - bounds.yMin) / (bounds.yMax - bounds.yMin)) * plotHeight);

  const xTicks = niceTicks(bounds.xMin, bounds.xMax, 6);
  const yTicks = niceTicks(bounds.yMin, bounds.yMax, 5);

  const missingCount = allPoints.filter((point) => point.y === null).length;
  const failedCount = allPoints.filter((point) => point.flag === 'failed').length;
  const naCount = allPoints.filter((point) => point.flag === 'na').length;
  const noSampleCount = allPoints.filter((point) => point.n === 0).length;

  return (
    <figure className="chart">
      <figcaption>
        {caption ?? `${yLabel} — ${xLabel}`}
        <span className="chart__flags">
          {missingCount > 0 ? <Badge tone="warn">缺失 {missingCount}</Badge> : null}
          {failedCount > 0 ? <Badge tone="bad">失败 {failedCount}</Badge> : null}
          {naCount > 0 ? <Badge tone="neutral">NA {naCount}</Badge> : null}
          {noSampleCount > 0 ? <Badge tone="warn">n=0 的 query {noSampleCount}</Badge> : null}
        </span>
      </figcaption>

      <svg
        className="chart__svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${yLabel} 对 ${xLabel} 的实测曲线，共 ${validPoints.length} 个有效点`}
      >
        {intervalBand && intervalBand.to > intervalBand.from ? (
          <rect
            x={scaleX(intervalBand.from)}
            y={padding.top}
            width={Math.max(1, scaleX(intervalBand.to) - scaleX(intervalBand.from))}
            height={plotHeight}
            className="chart__band"
          />
        ) : null}

        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line x1={padding.left} x2={width - padding.right} y1={scaleY(tick)} y2={scaleY(tick)} className="chart__grid" />
            <text x={padding.left - 6} y={scaleY(tick) + 4} textAnchor="end" className="chart__axis">
              {formatNumber(tick, 3)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <g key={`x${tick}`}>
            <line x1={scaleX(tick)} x2={scaleX(tick)} y1={padding.top} y2={padding.top + plotHeight} className="chart__grid" />
            <text x={scaleX(tick)} y={height - 12} textAnchor="middle" className="chart__axis">
              {formatNumber(tick, 3)}
            </text>
          </g>
        ))}

        {series.map((item, index) => {
          const color = item.color ?? PALETTE[index % PALETTE.length];
          const sorted = [...item.points].sort((a, b) => a.x - b.x);
          const segments: string[] = [];
          let current: string[] = [];
          for (const point of sorted) {
            if (point.y === null || !Number.isFinite(point.y)) {
              if (current.length > 1) segments.push(current.join(' '));
              current = [];
              continue;
            }
            current.push(`${scaleX(point.x).toFixed(2)},${scaleY(point.y).toFixed(2)}`);
          }
          if (current.length > 1) segments.push(current.join(' '));
          return (
            <g key={item.name}>
              {segments.map((segment, segmentIndex) => (
                <polyline key={segmentIndex} points={segment} fill="none" stroke={color} strokeWidth={2} />
              ))}
              {sorted.map((point, pointIndex) => {
                const cx = scaleX(point.x);
                const cy = point.y === null || !Number.isFinite(point.y) ? padding.top + plotHeight - 4 : scaleY(point.y);
                const isHover = hover?.series === item.name && hover.point === point;
                return (
                  <g key={`${item.name}-${pointIndex}`}>
                    <circle
                      cx={cx}
                      cy={cy}
                      r={isHover ? 6 : 3.5}
                      fill={point.y === null ? 'none' : color}
                      stroke={point.y === null ? '#a0aec0' : color}
                      strokeWidth={point.y === null ? 1.2 : 1}
                      className={onPointSelect ? 'chart__point chart__point--clickable' : 'chart__point'}
                      tabIndex={onPointSelect ? 0 : -1}
                      role={onPointSelect ? 'button' : undefined}
                      aria-label={`${item.name} ${xLabel}=${point.x} ${yLabel}=${point.y ?? '缺失'} n=${point.n ?? '未提供'}`}
                      onMouseEnter={() => setHover({ series: item.name, point })}
                      onMouseLeave={() => setHover(null)}
                      onFocus={() => setHover({ series: item.name, point })}
                      onBlur={() => setHover(null)}
                      onClick={() => onPointSelect?.({ ...point, series: item.name })}
                      onKeyDown={(event) => {
                        if (onPointSelect && (event.key === 'Enter' || event.key === ' ')) {
                          event.preventDefault();
                          onPointSelect({ ...point, series: item.name });
                        }
                      }}
                    />
                  </g>
                );
              })}
            </g>
          );
        })}

        <line
          x1={padding.left}
          x2={width - padding.right}
          y1={padding.top + plotHeight}
          y2={padding.top + plotHeight}
          className="chart__axisline"
        />
        <line x1={padding.left} x2={padding.left} y1={padding.top} y2={padding.top + plotHeight} className="chart__axisline" />
        <text x={padding.left} y={padding.top - 4} className="chart__axis">
          {yLabel}
          {series[0]?.unit ? `（${series[0].unit}）` : ''}
        </text>
        <text x={width - padding.right} y={height - 2} textAnchor="end" className="chart__axis">
          {xLabel}
        </text>
      </svg>

      <div className="chart__legend">
        {series.map((item, index) => (
          <span key={item.name} className="chart__legendItem">
            <span className="chart__swatch" style={{ background: item.color ?? PALETTE[index % PALETTE.length] }} aria-hidden="true" />
            {item.name}
            <span className="muted small">
              （{item.points.filter((point) => point.y !== null).length} 点
              {item.unit ? ` · ${item.unit}` : ''}）
            </span>
          </span>
        ))}
      </div>

      {hover ? (
        <div className="chart__tooltip" role="status">
          <strong>{hover.series}</strong> · {xLabel}={formatNumber(hover.point.x, 3)} · {yLabel}=
          {hover.point.y === null ? '未提供（断线）' : formatNumber(hover.point.y, 4)} · n={hover.point.n ?? '未提供'}
          {hover.point.flag ? ` · flag=${hover.point.flag}` : ''}
          {hover.point.ref ? ` · ref=${hover.point.ref}` : ''}
        </div>
      ) : null}

      <p className="muted small">
        缺失点不插值、不外推；样本数 n=0 的 query 会标为风险而不是 0 召回。点击数据点可下钻（若后端提供 ref）。
      </p>
    </figure>
  );
}

/* ------------------------------------------------------------------ 热图 */
export interface HeatmapCell {
  row: string;
  column: string;
  value: number | null;
  n?: number | null;
  flag?: 'failed' | 'na' | 'missing' | null;
  ref?: string | null;
}

export interface MetricHeatmapProps {
  rows: string[];
  columns: string[];
  cells: HeatmapCell[];
  caption?: string;
  valueLabel: string;
  unit?: string | null;
  onCellSelect?: (cell: HeatmapCell) => void;
  emptyReason?: React.ReactNode;
}

export function MetricHeatmap({
  rows,
  columns,
  cells,
  caption,
  valueLabel,
  unit,
  onCellSelect,
  emptyReason,
}: MetricHeatmapProps) {
  const [hover, setHover] = useState<HeatmapCell | null>(null);
  const byKey = useMemo(() => {
    const map = new Map<string, HeatmapCell>();
    for (const cell of cells) map.set(`${cell.row}\u0000${cell.column}`, cell);
    return map;
  }, [cells]);

  if (rows.length === 0 || columns.length === 0 || cells.length === 0) {
    return <EmptyState title="没有可绘制的矩阵" reason={emptyReason ?? '后端没有返回矩阵数据。'} />;
  }

  const values = cells.map((cell) => cell.value).filter((value): value is number => value !== null && Number.isFinite(value));
  const min = values.length > 0 ? Math.min(...values) : 0;
  const max = values.length > 0 ? Math.max(...values) : 1;

  const tone = (value: number | null): string => {
    if (value === null) return 'heat heat--missing';
    const ratio = max === min ? 0.5 : (value - min) / (max - min);
    if (ratio < 0.25) return 'heat heat--q1';
    if (ratio < 0.5) return 'heat heat--q2';
    if (ratio < 0.75) return 'heat heat--q3';
    return 'heat heat--q4';
  };

  return (
    <figure className="heatmap">
      <figcaption>
        {caption ?? `${valueLabel} 矩阵`}
        <span className="muted small">
          {' '}
          · 值域 {formatNumber(min, 3)} … {formatNumber(max, 3)} {unit ?? ''}
        </span>
      </figcaption>
      <div className="tablewrap">
        <table className="table table--heat">
          <thead>
            <tr>
              <th scope="col">{valueLabel} ＼ 列</th>
              {columns.map((column) => (
                <th scope="col" key={column} className="mono">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                <th scope="row" className="mono">
                  {row}
                </th>
                {columns.map((column) => {
                  const cell = byKey.get(`${row}\u0000${column}`);
                  return (
                    <td
                      key={column}
                      className={cell ? tone(cell.value) : 'heat heat--absent'}
                      onMouseEnter={() => cell && setHover(cell)}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => cell && onCellSelect?.(cell)}
                    >
                      <button
                        type="button"
                        className="heat__button"
                        disabled={!cell || !onCellSelect}
                        aria-label={`${row} × ${column} = ${cell?.value ?? '无数据'}`}
                      >
                        {cell ? (cell.value === null ? '缺失' : formatNumber(cell.value, 2)) : '—'}
                        {cell?.n !== undefined && cell?.n !== null ? <span className="heat__n">n={cell.n}</span> : null}
                        {cell?.flag ? <span className="heat__flag">{cell.flag}</span> : null}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hover ? (
        <p className="chart__tooltip" role="status">
          {hover.row} × {hover.column} = {hover.value === null ? '缺失' : formatNumber(hover.value, 4)}
          {unit ? ` ${unit}` : ''} · n={hover.n ?? '未提供'}
          {hover.ref ? ` · ref=${hover.ref}` : ''}
        </p>
      ) : null}
    </figure>
  );
}
