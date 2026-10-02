/**
 * run 归并：`GET /jobs` 是分页任务列表，run 级视图只能由这些**真实 job 行**聚合而来
 * （计划 20.2：成功统计由 accepted manifest 推得，不能由前端累加猜测）。
 */

import type { JobRecord } from '../api/types';
import { isRecord, jobStateLabel } from './format';

export interface RunSummary {
  run_id: string;
  rootJobId: string | null;
  jobs: JobRecord[];
  total: number;
  stateCounts: Record<string, number>;
  stages: string[];
  dominantState: string;
  terminal: boolean;
  failedStates: string[];
  firstSeen: number;
  lastSeen: number;
  specHash: string | null;
  profile: string | null;
  workspace: string | null;
  stage: string | null;
}

const TERMINAL_STATES = new Set(['COMMITTED', 'CANCELLED', 'FAILED']);
const PROBLEM_STATES = ['FAILED', 'QUARANTINED', 'RETRYABLE', 'BLOCKED'];

/** run 状态取“最需要关注”的那个：失败 > 隔离 > 可重试 > 运行中 > 待运行 > 已提交。 */
const PRIORITY = [
  'FAILED',
  'QUARANTINED',
  'RETRYABLE',
  'BLOCKED',
  'RUNNING',
  'OUTPUT_READY',
  'QA_PASS',
  'PENDING',
  'CANCELLED',
  'COMMITTED',
];

export function summarizeRuns(jobs: JobRecord[]): RunSummary[] {
  const buckets = new Map<string, JobRecord[]>();
  for (const job of jobs) {
    const list = buckets.get(job.run_id) ?? [];
    list.push(job);
    buckets.set(job.run_id, list);
  }

  const summaries: RunSummary[] = [];
  for (const [runId, list] of buckets) {
    const sorted = [...list].sort((a, b) => a.created_at - b.created_at);
    const stateCounts: Record<string, number> = {};
    for (const job of sorted) stateCounts[job.state] = (stateCounts[job.state] ?? 0) + 1;
    const stages = [...new Set(sorted.map((job) => job.stage))];
    const spec = sorted[0]?.spec;
    const meta = isRecord(spec) ? spec : {};
    const dominant =
      PRIORITY.find((state) => stateCounts[state] !== undefined) ?? sorted[0]?.state ?? 'PENDING';
    const rootJob =
      sorted.find((job) => job.stage !== 'audit' && (job.progress === null || job.progress === undefined)) ?? sorted[0];
    summaries.push({
      run_id: runId,
      rootJobId: rootJob?.job_id ?? null,
      jobs: sorted,
      total: sorted.length,
      stateCounts,
      stages,
      dominantState: dominant,
      terminal: sorted.every((job) => TERMINAL_STATES.has(job.state)),
      failedStates: PROBLEM_STATES.filter((state) => stateCounts[state] !== undefined),
      firstSeen: sorted[0]?.created_at ?? 0,
      lastSeen: sorted[sorted.length - 1]?.updated_at ?? 0,
      specHash: typeof meta.spec_hash === 'string' ? meta.spec_hash : null,
      profile: typeof meta.profile === 'string' ? meta.profile : null,
      workspace: typeof meta.workspace === 'string' ? meta.workspace : null,
      stage: typeof meta.stage === 'string' ? meta.stage : (sorted[0]?.stage ?? null),
    });
  }
  return summaries.sort((a, b) => b.lastSeen - a.lastSeen);
}

export function runStateLabel(state: string): { label: string; tone: 'ok' | 'warn' | 'bad' | 'info' | 'neutral' } {
  const mapped = jobStateLabel(state);
  if (state === 'RUNNING') return { label: '运行中', tone: 'info' };
  return mapped;
}

export function summarizeCounts(summary: RunSummary): string {
  return Object.entries(summary.stateCounts)
    .map(([state, count]) => `${jobStateLabel(state).label}×${count}`)
    .join(' · ');
}
