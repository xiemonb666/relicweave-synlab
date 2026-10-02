/**
 * RunSelector —— 选择一个真实 run（由 `GET /jobs` 的 job 行聚合而来）。
 *
 * 不构造 run 列表：没有 job 数据就没有可选项，并显示后端给出的空原因。
 */

import type { RunSummary } from '../lib/runs';
import { summarizeCounts, runStateLabel } from '../lib/runs';
import { formatRelative, truncate } from '../lib/format';
import { Badge, EmptyState, ErrorState, LoadingState } from './states';

export interface RunSelectorProps {
  runs: RunSummary[];
  value: string | null;
  onChange: (runId: string | null) => void;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyReason?: React.ReactNode;
  label?: string;
}

export function RunSelector({
  runs,
  value,
  onChange,
  loading,
  error,
  onRetry,
  emptyReason,
  label = '选择 run',
}: RunSelectorProps) {
  if (loading) return <LoadingState label="加载 run 列表（GET /jobs）…" />;
  if (error) return <ErrorState error={error} onRetry={onRetry} compact />;
  if (runs.length === 0) {
    return (
      <EmptyState
        title="没有可选的 run"
        reason={emptyReason ?? 'GET /jobs 在这个工作区没有返回任何 job；本页不构造占位 run。'}
      />
    );
  }

  return (
    <div className="runselector" role="group" aria-label={label}>
      <div className="runselector__head">
        <span className="muted small">
          共 {runs.length} 个 run（由 GET /jobs 的真实 job 行按 run_id 归并）
        </span>
        <button
          type="button"
          className="btn btn--tiny"
          onClick={() => onChange(null)}
          disabled={value === null}
          title={value === null ? '当前已是不限定 run' : undefined}
        >
          清除选择
        </button>
      </div>
      <ul className="runselector__list">
        {runs.map((run) => {
          const state = runStateLabel(run.dominantState);
          const selected = run.run_id === value;
          return (
            <li key={run.run_id}>
              <button
                type="button"
                className={`runselector__item${selected ? ' runselector__item--active' : ''}`}
                aria-pressed={selected}
                onClick={() => onChange(selected ? null : run.run_id)}
              >
                <span className="runselector__row">
                  <span className="mono" title={run.run_id}>
                    {truncate(run.run_id, 24)}
                  </span>
                  <Badge tone={state.tone}>{state.label}</Badge>
                  {run.failedStates.length > 0 ? <Badge tone="bad">含 {run.failedStates.join('/')}</Badge> : null}
                  <span className="muted small">{run.terminal ? '已终止' : '未终止'}</span>
                </span>
                <span className="runselector__row muted small">
                  {run.total} 个 job · {run.stages.join(' → ') || '阶段未提供'} · 最近更新 {formatRelative(run.lastSeen)}
                </span>
                <span className="runselector__row mono small">{summarizeCounts(run)}</span>
                {run.specHash ? <span className="runselector__row mono small">spec_hash={truncate(run.specHash, 32)}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
