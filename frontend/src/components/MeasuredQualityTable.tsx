/**
 * MeasuredQualityTable —— 实测质量表（计划 20.6 / 20.10：滑块只是参数，不能当测量值）。
 *
 * 只渲染后端真实给出的数值：`asset.qa`、job `progress`、训练 run 的 `metrics`、诊断 run 的
 * `queries`。缺失一律显示“未提供”，**不写 0、不插值、不补默认值**；同时列出 `n`（样本数）
 * 与单位，`n` 未达到页面要求时不给出“已证明”的措辞。
 */

import { useMemo } from 'react';

import { asNumber, asString, formatNumber, isRecord, pretty } from '../lib/format';
import { Badge, EmptyState } from './states';

export interface QualityRow {
  key: string;
  label: string;
  value: unknown;
  unit?: string | null;
  n?: number | null;
  /** 该指标真实来源（接口 + 字段路径），便于复核。 */
  source?: string | null;
  /** 后端给出的区间/置信信息，原样展示。 */
  interval?: unknown;
  /** 明确标记为缺失/失败的条目。 */
  flag?: 'missing' | 'failed' | 'na' | null;
}

export interface MeasuredQualityTableProps {
  rows: QualityRow[];
  caption?: string;
  emptyTitle?: string;
  emptyReason?: React.ReactNode;
  /** 低于该样本数时提示“样本不足，不能声称已证明”。 */
  minSamples?: number;
}

export function MeasuredQualityTable({
  rows,
  caption,
  emptyTitle = '没有实测质量数据',
  emptyReason,
  minSamples,
}: MeasuredQualityTableProps) {
  const insufficient = useMemo(
    () => (minSamples ? rows.filter((row) => row.n !== null && row.n !== undefined && row.n < minSamples) : []),
    [rows, minSamples],
  );

  if (rows.length === 0) {
    return (
      <EmptyState
        title={emptyTitle}
        reason={
          emptyReason ??
          '后端在这些资产/运行上还没有产出可测量值（未运行的阶段不会写 0 分或通过）。请先运行对应阶段，或换一个已完成的 run。'
        }
      />
    );
  }

  return (
    <div className="tablewrap">
      <table className="table table--metrics">
        <caption>{caption ?? '实测值（来自后端响应字段，缺失显示“未提供”）'}</caption>
        <thead>
          <tr>
            <th scope="col">指标</th>
            <th scope="col">实测值</th>
            <th scope="col">单位</th>
            <th scope="col">n（样本数）</th>
            <th scope="col">区间 / 备注</th>
            <th scope="col">来源</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const missing = row.value === null || row.value === undefined || row.flag === 'missing';
            return (
              <tr key={row.key} className={missing ? 'row--missing' : undefined}>
                <th scope="row">{row.label}</th>
                <td className="mono">
                  {missing ? (
                    <Badge tone="warn">未提供</Badge>
                  ) : isRecord(row.value) || Array.isArray(row.value) ? (
                    <pre className="mono pre pre--inline">{pretty(row.value)}</pre>
                  ) : (
                    String(row.value)
                  )}
                  {row.flag === 'failed' ? <Badge tone="bad">失败</Badge> : null}
                  {row.flag === 'na' ? <Badge tone="neutral">NA 不适用</Badge> : null}
                </td>
                <td className="mono">{row.unit ?? '—'}</td>
                <td className="mono">{row.n === null || row.n === undefined ? '未提供' : row.n}</td>
                <td className="mono">{row.interval === undefined || row.interval === null ? '—' : pretty(row.interval)}</td>
                <td className="mono small">{row.source ?? '未标注来源'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {insufficient.length > 0 ? (
        <p className="warning" role="status">
          以下指标样本数不足 {minSamples}：
          <code className="mono">{insufficient.map((row) => row.label).join('、')}</code>
          —— 样本数未达要求的结论不能写成“已证明”，此处只报实测值。
        </p>
      ) : null}
    </div>
  );
}

/** 把任意后端的度量对象拍平成表格行（保留真实 key 路径作为来源）。 */
export function flattenMetrics(
  source: unknown,
  options: { prefix?: string; unitHints?: Record<string, string>; nHints?: Record<string, number>; origin?: string } = {},
): QualityRow[] {
  const rows: QualityRow[] = [];
  const walk = (value: unknown, path: string) => {
    if (isRecord(value)) {
      for (const [key, child] of Object.entries(value)) walk(child, path ? `${path}.${key}` : key);
      return;
    }
    if (Array.isArray(value)) {
      rows.push({
        key: path,
        label: path,
        value: `${value.length} 项`,
        unit: null,
        n: value.length,
        source: options.origin ?? null,
      });
      return;
    }
    const numeric = asNumber(value);
    rows.push({
      key: path,
      label: path,
      value: typeof value === 'boolean' || typeof value === 'string' ? value : numeric === null ? null : formatNumber(numeric, 6),
      unit: options.unitHints?.[path] ?? null,
      n: options.nHints?.[path] ?? null,
      source: options.origin ?? null,
      flag: value === null || value === undefined ? 'missing' : null,
    });
  };
  walk(source, options.prefix ?? '');
  return rows.filter((row) => row.key !== '');
}

/** 便捷：把 job 的 progress 变成一行可读度量。 */
export function progressRows(progress: { done?: number; planned?: number; unit?: string } | null | undefined): QualityRow[] {
  if (!progress) {
    return [
      {
        key: 'progress',
        label: '可量化进度',
        value: null,
        unit: null,
        n: null,
        source: 'GET /jobs/{job_id}.progress',
        flag: 'missing',
      },
    ];
  }
  const done = asNumber(progress.done);
  const planned = asNumber(progress.planned);
  return [
    {
      key: 'progress.done',
      label: '已完成工作量',
      value: done === null ? null : String(done),
      unit: asString(progress.unit) ?? null,
      n: planned ?? null,
      source: 'GET /jobs/{job_id}.progress.done',
      flag: done === null ? 'missing' : null,
    },
    {
      key: 'progress.planned',
      label: '计划工作量',
      value: planned === null ? null : String(planned),
      unit: asString(progress.unit) ?? null,
      n: null,
      source: 'GET /jobs/{job_id}.progress.planned',
      flag: planned === null ? 'missing' : null,
    },
  ];
}
