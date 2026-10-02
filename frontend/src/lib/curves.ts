/**
 * 曲线解析：把后端 `curves` / `metrics` 的**真实**结构转成 `MetricSeries`。
 *
 * 后端目前没有固定曲线结构（不同 run 的 `result.curves` 由实现模块决定），因此这里只做
 * **结构识别**，不做任何插值或补点：
 *
 * 支持的结构（任一命中即解析）：
 * - `{name, points: [{x|step, y|value, n?}...], unit?}`
 * - `{name, steps: number[], values: (number|null)[], unit?}`
 * - `{name, series: {<label>: [{x,y}]}}`（一条曲线拆成多条）
 *
 * 识别不了的条目进入 `unparsed`，页面原样展示 JSON，并明确标注“结构未识别”，
 * 而不是丢弃它或画一条假线。
 */

import { asNumber, asString, isRecord } from './format';
import type { MetricPoint, MetricSeries } from '../components/MetricChart';

export interface ParsedCurves {
  series: MetricSeries[];
  unparsed: Array<{ name: string; raw: unknown; reason: string }>;
}

function toPoint(raw: unknown): MetricPoint | null {
  if (!isRecord(raw)) {
    const value = asNumber(raw);
    return value === null ? null : { x: 0, y: value };
  }
  const x = asNumber(raw.x ?? raw.step ?? raw.level ?? raw.k ?? raw.n);
  const yRaw = raw.y ?? raw.value ?? raw.metric ?? raw.score;
  const y = yRaw === null || yRaw === undefined ? null : asNumber(yRaw);
  if (x === null) return null;
  const flagRaw = asString(raw.flag);
  const flag =
    flagRaw === 'failed' || flagRaw === 'na' || flagRaw === 'missing'
      ? (flagRaw as 'failed' | 'na' | 'missing')
      : null;
  return {
    x,
    y: yRaw === null || yRaw === undefined ? null : y ?? null,
    n: asNumber(raw.n ?? raw.samples ?? raw.count),
    flag,
    ref: asString(raw.ref ?? raw.query_id ?? raw.id),
    label: asString(raw.label ?? raw.name),
  };
}

export function parseCurves(input: unknown): ParsedCurves {
  const series: MetricSeries[] = [];
  const unparsed: ParsedCurves['unparsed'] = [];
  const list = Array.isArray(input) ? input : isRecord(input) ? Object.entries(input).map(([name, value]) => ({ name, ...(isRecord(value) ? value : { values: value }) })) : [];

  list.forEach((entry, index) => {
    const record = isRecord(entry) ? entry : {};
    const name = asString(record.name ?? record.metric ?? record.id) ?? `curve[${index}]`;
    const unit = asString(record.unit ?? record.units);

    if (Array.isArray(record.points)) {
      const points = record.points.map(toPoint).filter((point): point is MetricPoint => point !== null);
      if (points.length > 0) {
        series.push({ name, unit, points });
        return;
      }
    }

    if (Array.isArray(record.steps) && Array.isArray(record.values)) {
      const steps = record.steps as unknown[];
      const values = record.values as unknown[];
      const ns = Array.isArray(record.ns) ? (record.ns as unknown[]) : [];
      const points: MetricPoint[] = [];
      steps.forEach((step, position) => {
        const x = asNumber(step);
        if (x === null) return;
        const rawValue = values[position];
        const y = rawValue === null || rawValue === undefined ? null : asNumber(rawValue);
        points.push({ x, y, n: asNumber(ns[position]) });
      });
      if (points.length > 0) {
        series.push({ name, unit, points });
        return;
      }
    }

    if (isRecord(record.series)) {
      let added = false;
      for (const [label, rawPoints] of Object.entries(record.series)) {
        if (!Array.isArray(rawPoints)) continue;
        const points = rawPoints.map(toPoint).filter((point): point is MetricPoint => point !== null);
        if (points.length === 0) continue;
        series.push({ name: `${name} · ${label}`, unit, points });
        added = true;
      }
      if (added) return;
    }

    unparsed.push({
      name,
      raw: entry,
      reason: '未识别为 {points}/{steps+values}/{series} 结构，页面原样展示 JSON 而不绘制',
    });
  });

  return { series, unparsed };
}

/** 把 `metrics` 里的标量登记为实测表友好的行（数组/对象保持原样）。 */
export function metricsToRows(input: unknown, origin: string): Array<{
  key: string;
  label: string;
  value: unknown;
  unit?: string | null;
  n?: number | null;
  source?: string | null;
}> {
  if (!isRecord(input)) return [];
  return Object.entries(input).map(([key, value]) => ({
    key,
    label: key,
    value: Array.isArray(value) ? `${value.length} 项` : value,
    n: Array.isArray(value) ? value.length : null,
    source: `${origin}.${key}`,
  }));
}
