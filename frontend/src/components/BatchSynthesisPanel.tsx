/**
 * BatchSynthesisPanel —— U07 的「批量合成」面板（真实计数 / 覆盖矩阵 / 一键续跑）。
 *
 * 数据来源：
 * * `GET /synthesis/inventory` —— 每个覆盖桶的 assets/fragments/lineages、jobs 的
 *   planned/attempted/accepted/failed、失败错误码（job.error.code）、磁盘实测字节、
 *   coverage aggregate 的已覆盖/缺失 ID；
 * * `POST /synthesis/batch-plan` —— 下一批组合（按 assets 表去重）与 `--resume` 语义；
 * * `POST /jobs` —— 真正入队（幂等键含批游标，一键续跑得到新 run，重复点同一批复用原 run）；
 * * `GET /jobs?run_id=` + `GET /runs/{id}/events` —— 实时进度（SSE，断线退化为轮询）。
 *
 * 诚实规则：
 * * 所有计数原样来自后端；`planned` 是 jobs 表的行数，`accepted` 只数
 *   OUTPUT_READY/QA_PASS/COMMITTED，未运行的批次不会显示成 0 成功；
 * * 磁盘增量用两次 `GET /synthesis/inventory` 的实测字节差表示，并同时显示原始总量；
 * * 覆盖矩阵里 `layer_combo_id` 为 null 就照实显示「资产 meta 未记录」，不用 registry 的 4 个 ID 顶替。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  getSynthesisInventory,
  listJobs,
  postBatchPlan,
  postJobs,
} from '../api/endpoints';
import { newIdempotencyKey, useResource, useRunEventStream } from '../api/hooks';
import type {
  BatchPlanResponse,
  JobAcceptedResponse,
  JobRecord,
  SynthesisInventoryResponse,
} from '../api/types';
import { formatBytes, jobStateLabel, truncate } from '../lib/format';
import { FailureCard, RunningCard, failureFromError, type FailureInfo } from './AsyncOperation';
import { CoverageMatrix } from './CoverageMatrix';
import {
  ActionButton,
  Badge,
  CopyValue,
  EmptyState,
  KeyValueList,
  LoadingState,
  SectionCard,
} from './states';

export function BatchSynthesisPanel({ onSelectRun }: { onSelectRun?: (runId: string) => void }) {
  const inventory = useResource((signal) => getSynthesisInventory(signal), [], { intervalMs: 20_000 });
  const [cursor, setCursor] = useState(0);
  const [batchSize, setBatchSize] = useState(4);
  const [plan, setPlan] = useState<BatchPlanResponse | null>(null);
  const [planFailure, setPlanFailure] = useState<FailureInfo | null>(null);
  const [planning, setPlanning] = useState(false);
  const [accepted, setAccepted] = useState<JobAcceptedResponse | null>(null);
  const [enqueueFailure, setEnqueueFailure] = useState<FailureInfo | null>(null);
  const [enqueueing, setEnqueueing] = useState(false);
  const [diskBaseline, setDiskBaseline] = useState<number | null>(null);
  const [diskAfterBatch, setDiskAfterBatch] = useState<number | null>(null);
  const [batchStartedAt, setBatchStartedAt] = useState<number | null>(null);
  const baselineRef = useRef<number | null>(null);

  const data = inventory.data;
  const panel = data?.panel;

  useEffect(() => {
    if (data && baselineRef.current === null) baselineRef.current = data.panel.disk_bytes;
  }, [data]);

  const stream = useRunEventStream(accepted?.run_id ?? null, { enabled: Boolean(accepted?.run_id) });
  const runJobs = useResource(
    (signal) => listJobs({ run_id: accepted?.run_id, limit: 100, with_total: true }, signal),
    [accepted?.run_id],
    { enabled: Boolean(accepted?.run_id), intervalMs: 5000 },
  );

  const jobCounts = useMemo(() => {
    const table: Record<string, number> = {};
    for (const job of (runJobs.data?.items ?? []) as JobRecord[]) {
      table[job.state] = (table[job.state] ?? 0) + 1;
    }
    return table;
  }, [runJobs.data]);

  const runPlan = async (options: { resume: boolean; cursor: number }) => {
    setPlanning(true);
    setPlanFailure(null);
    try {
      const response = await postBatchPlan({
        spec: plan?.spec && Object.keys(plan.spec).length > 0 ? plan.spec : baseSpec(),
        requested: batchSize,
        batch_size: batchSize,
        cursor: options.cursor,
        resume: options.resume,
      });
      setPlan(response);
      setCursor(response.next_cursor);
    } catch (caught) {
      setPlan(null);
      setPlanFailure(failureFromError(caught));
    } finally {
      setPlanning(false);
    }
  };

  const enqueue = async () => {
    if (!plan || plan.selected === 0) return;
    setEnqueueing(true);
    setEnqueueFailure(null);
    try {
      const response = await postJobs({
        schema_version: 'synlab.v3',
        data_scope: 'SYNTHETIC',
        spec: plan.spec,
        stage: 'generate',
        planned_jobs: Math.max(1, Number((plan.spec.dataset as Record<string, unknown> | undefined)?.target_mothers ?? 1)),
        // 幂等键含批游标：续跑下一批 => 新 run；重复点同一批 => 后端幂等重放原 run。
        idempotency_key: newIdempotencyKey(`batch:c${plan.next_cursor}`),
      });
      setAccepted(response);
      setBatchStartedAt(Date.now());
      setDiskAfterBatch(null);
      if (data) setDiskBaseline(data.panel.disk_bytes);
      onSelectRun?.(response.run_id);
      inventory.reload();
    } catch (caught) {
      setEnqueueFailure(failureFromError(caught));
    } finally {
      setEnqueueing(false);
    }
  };

  // 入队后轮询 inventory 量磁盘增量（真实 stat() 字节差）。
  useEffect(() => {
    if (!accepted?.run_id) return undefined;
    const timer = window.setInterval(() => inventory.reload(), 15_000);
    return () => window.clearInterval(timer);
  }, [accepted?.run_id, inventory]);

  useEffect(() => {
    if (data && diskBaseline !== null && accepted) setDiskAfterBatch(data.panel.disk_bytes);
  }, [data, diskBaseline, accepted]);

  const buckets = data?.buckets.rows ?? [];
  const coveredBuckets = buckets.filter((row) => row.covered).length;

  return (
    <>
      <SectionCard
        title="批量合成（真实计数 · 覆盖矩阵 · 一键续跑）"
        subtitle="GET /synthesis/inventory + POST /synthesis/batch-plan + POST /jobs + GET /runs/{id}/events"
        actions={
          <div className="row">
            <button type="button" className="btn btn--tiny" onClick={inventory.reload} disabled={inventory.refreshing}>
              {inventory.refreshing ? '刷新中…' : '刷新计数'}
            </button>
          </div>
        }
      >
        {inventory.status === 'loading' ? <LoadingState label="读取 store 聚合计数…" /> : null}
        {inventory.status === 'error' ? (
          <FailureCard title="聚合计数读取失败" failure={failureFromError(inventory.error)} onRetry={inventory.reload} />
        ) : null}

        {panel ? (
          <>
            <div className="statrow">
              <span className="stat"><Badge tone="neutral">planned</Badge><strong>{panel.planned}</strong></span>
              <span className="stat"><Badge tone="info">attempted</Badge><strong>{panel.attempted}</strong></span>
              <span className="stat"><Badge tone="ok">accepted</Badge><strong>{panel.accepted}</strong></span>
              <span className="stat"><Badge tone={panel.failed > 0 ? 'bad' : 'neutral'}>failed</Badge><strong>{panel.failed}</strong></span>
              <span className="stat"><Badge tone="warn">pending</Badge><strong>{panel.pending}</strong></span>
            </div>
            <KeyValueList
              rows={[
                { label: '磁盘实测（资产 payload）', value: `${formatBytes(panel.disk_bytes)}（${panel.disk_files} 个文件）` },
                { label: '本批磁盘增量', value: diskBaseline === null ? '未记录基线' : diskAfterBatch === null
                  ? `等待首个刷新（基线 ${formatBytes(diskBaseline)}）`
                  : `${diskAfterBatch - diskBaseline >= 0 ? '+' : ''}${formatBytes(diskAfterBatch - diskBaseline)}（${formatBytes(diskBaseline)} → ${formatBytes(diskAfterBatch)}）` },
                { label: '资产数 / run 数 / 事件数', value: `${panel.asset_count} / ${panel.runs} / ${panel.events}` },
                {
                  label: 'jobs 状态分布',
                  value: <span className="mono small">{Object.entries(panel.by_state).map(([state, count]) => `${state}=${count}`).join(' · ') || '（无 job 行）'}</span>,
                },
                { label: '计数口径', value: panel.note },
              ]}
            />
            {panel.failure_codes.length > 0 ? (
              <table className="table table--tight">
                <caption>失败错误码（job.error_json 的真实 code）</caption>
                <thead>
                  <tr><th scope="col">code</th><th scope="col">次数</th><th scope="col">可重试</th><th scope="col">示例 job</th></tr>
                </thead>
                <tbody>
                  {panel.failure_codes.map((row) => (
                    <tr key={row.code}>
                      <th scope="row" className="mono">{row.code}</th>
                      <td className="mono">{row.count}</td>
                      <td>{row.retryable === null ? '未标注' : <Badge tone={row.retryable ? 'warn' : 'bad'}>{String(row.retryable)}</Badge>}</td>
                      <td className="mono small">{row.job_ids.slice(0, 3).map((id) => truncate(id, 14)).join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted small">jobs 表里没有带错误的行 —— 未运行过的阶段不会产生失败码。</p>
            )}
          </>
        ) : null}
      </SectionCard>

      <SectionCard
        title="覆盖矩阵（器型 × 材料 × 花纹 × 层）"
        subtitle="covered/required 来自 reports/coverage_aggregate.json（跨 run 聚合）；桶内计数来自 assets 表"
        actions={<span className="muted small">已覆盖桶 {coveredBuckets} / {buckets.length}</span>}
      >
        {data ? (
          <>
            <CoverageMatrix
              coverage={{
                scanned_assets: data.assets_total,
                basis: data.buckets.field,
                coverage_24_vessels: gateBlock(data, 'vessels'),
                coverage_12_materials: gateBlock(data, 'materials'),
                coverage_16_patterns: gateBlock(data, 'patterns'),
                coverage_4_layers: gateBlock(data, 'layer_combos'),
                coverage_4_backends: gateBlock(data, 'fracture_backends'),
                coverage_31_axes: gateBlock(data, 'axes'),
                source: data.buckets.source,
              }}
              title="覆盖维度（真实 aggregate）"
              emptyReason="reports 里既没有 coverage_aggregate.json 也没有 coverage.json：覆盖结论不存在。"
            />
            <p className="muted small">
              覆盖来源：<code className="mono">{data.buckets.source ?? 'reports 里没有 coverage 文件'}</code>；
              {data.coverage.note}
            </p>

            <div className="tablewrap">
              <table className="table">
                <caption>
                  已实现的组合桶（{data.buckets.field}）—— 来自 assets 表，逐桶给出真实资产数
                </caption>
                <thead>
                  <tr>
                    <th scope="col">组合</th>
                    <th scope="col">assets</th>
                    <th scope="col">fragments</th>
                    <th scope="col">lineages</th>
                    <th scope="col">覆盖</th>
                    <th scope="col">run 数</th>
                  </tr>
                </thead>
                <tbody>
                  {buckets.slice(0, 60).map((row) => (
                    <tr key={row.id}>
                      <th scope="row" className="mono">
                        {row.vessel_id} / {row.material_id}
                        {row.pattern_id ? ` / ${row.pattern_id}` : ''}
                        {row.layer_combo_id ? ` / ${row.layer_combo_id}` : (
                          <span className="muted small"> / layer=未记录</span>
                        )}
                      </th>
                      <td className="mono">{row.assets}</td>
                      <td className="mono">{row.fragments}</td>
                      <td className="mono">{row.lineages}</td>
                      <td>
                        <Badge tone={row.covered ? 'ok' : 'warn'}>{row.covered ? '已覆盖' : '未计入覆盖'}</Badge>
                      </td>
                      <td className="mono">{row.runs.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {buckets.length > 60 ? <p className="muted small">只显示前 60 个桶（共 {buckets.length}）。</p> : null}
            </div>
            <p className="muted small">{data.buckets.note}</p>
            <details>
              <summary>coverage 原始 JSON（后端原样）</summary>
              <pre className="mono pre">{JSON.stringify(data.coverage, null, 2)}</pre>
            </details>
          </>
        ) : (
          <EmptyState title="还没有覆盖数据" reason="等 GET /synthesis/inventory 返回；后端没有 reports/coverage*.json 时它会如实为空。" />
        )}
      </SectionCard>

      <SectionCard
        title="下一批与续跑（--resume 语义）"
        subtitle="POST /synthesis/batch-plan：resume=true 忽略客户端 cursor，按 assets 表推进到第一个未实现组合"
        actions={
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">批大小</span>
              <input
                className="input input--tight"
                type="number"
                min={1}
                max={64}
                value={batchSize}
                aria-label="批大小"
                onChange={(event) => setBatchSize(Number(event.target.value))}
              />
            </label>
            <ActionButton onClick={() => void runPlan({ resume: false, cursor })} busy={planning}>
              规划（cursor {cursor}）
            </ActionButton>
            <ActionButton tone="primary" onClick={() => void runPlan({ resume: true, cursor: 0 })} busy={planning}>
              一键续跑下一批
            </ActionButton>
          </div>
        }
      >
        {planFailure ? <FailureCard title="批次规划失败" failure={planFailure} onRetry={() => void runPlan({ resume: true, cursor })} /> : null}
        {plan ? (
          <>
            <KeyValueList
              rows={[
                { label: '本批组合', value: plan.selected },
                { label: '下一游标', value: plan.next_cursor },
                { label: '剩余组合', value: plan.pending_combinations },
                { label: 'spec_hash', value: plan.spec_hash ?? '未提供', mono: true },
                { label: 'resume', value: `${plan.resume.requested}：${plan.resume.semantics}` },
                { label: '说明', value: plan.resume.note },
              ]}
            />
            <div className="row">
              <ActionButton
                tone="primary"
                onClick={() => void enqueue()}
                busy={enqueueing}
                disabledReason={plan.selected === 0 ? '本批没有组合' : null}
              >
                提交本批（POST /jobs）
              </ActionButton>
              <span className="muted small">
                提交后可用 <code className="mono">python -m synlab.api.worker --store-root &lt;store&gt; --once --workspace default</code>
                真实执行；本页只读 state，不做本地推算。
              </span>
            </div>
            <details>
              <summary>本批组合与将提交的 spec</summary>
              <pre className="mono pre">{JSON.stringify({ combinations: plan.combinations, spec: plan.spec }, null, 2)}</pre>
            </details>
            {plan.repro.length > 0 ? (
              <KeyValueList
                rows={plan.repro.map((command, index) => ({
                  label: `repro ${index + 1}`,
                  value: <CopyValue value={command} label="复现命令" />,
                }))}
              />
            ) : null}
          </>
        ) : (
          <EmptyState
            title="还没有批次计划"
            reason="点上面的按钮会按真实覆盖情况算出下一批组合；没有规划前这里不显示任何组合。"
          />
        )}

        {enqueueFailure ? <FailureCard title="入队失败" failure={enqueueFailure} onRetry={() => void enqueue()} /> : null}
        {accepted ? (
          <>
            <KeyValueList
              rows={[
                { label: 'run_id', value: accepted.run_id, mono: true },
                { label: 'job_id', value: accepted.job_id, mono: true },
                { label: '受理状态', value: accepted.status },
                { label: 'spec_hash', value: accepted.spec_hash, mono: true },
                { label: '幂等重放', value: <Badge tone={accepted.idempotent_replay ? 'warn' : 'ok'}>{String(accepted.idempotent_replay)}</Badge> },
              ]}
            />
            {stream.state !== 'open' ? (
              <RunningCard
                title="等待事件流"
                label={`SSE ${stream.state}${stream.pollingFallback ? '（已退化为 GET /jobs?run_id= 轮询）' : ''}`}
                elapsedMs={batchStartedAt === null ? null : Date.now() - batchStartedAt}
                details={[
                  { label: '已接收事件', value: `${stream.events.length}（last seq ${stream.lastSeq}）` },
                  { label: 'job 数', value: String((runJobs.data?.items ?? []).length) },
                ]}
              />
            ) : (
              <p className="small">
                <Badge tone="ok">SSE open</Badge>
                <span className="mono small"> 事件 {stream.events.length} · last seq {stream.lastSeq}</span>
              </p>
            )}
            <div className="statrow">
              {Object.entries(jobCounts).map(([state, count]) => (
                <span key={state} className="stat">
                  <Badge tone={jobStateLabel(state).tone}>{jobStateLabel(state).label}</Badge>
                  <strong>{count}</strong>
                </span>
              ))}
              {Object.keys(jobCounts).length === 0 ? <span className="muted">该 run 还没有 job 行</span> : null}
            </div>
            <table className="table table--tight">
              <caption>本 run 的 job（GET /jobs?run_id=，权威 state 与错误码）</caption>
              <thead>
                <tr>
                  <th scope="col">job_id</th>
                  <th scope="col">stage</th>
                  <th scope="col">state</th>
                  <th scope="col">attempt</th>
                  <th scope="col">错误码</th>
                  <th scope="col">进度</th>
                </tr>
              </thead>
              <tbody>
                {((runJobs.data?.items ?? []) as JobRecord[]).map((job) => (
                  <tr key={job.job_id}>
                    <th scope="row" className="mono">{truncate(job.job_id, 20)}</th>
                    <td className="mono">{job.stage}</td>
                    <td><Badge tone={jobStateLabel(job.state).tone}>{jobStateLabel(job.state).label}</Badge></td>
                    <td className="mono">{job.attempt}</td>
                    <td className="mono small">{job.error ? String((job.error as Record<string, unknown>).code ?? '—') : '—'}</td>
                    <td className="mono small">
                      {job.progress && typeof job.progress.done === 'number'
                        ? `${job.progress.done}/${job.progress.planned ?? '?'} ${job.progress.unit ?? ''}`
                        : '未计数'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </SectionCard>
    </>
  );
}

/** 覆盖维度 → `CoverageMatrix` 需要的 block 形状（值全部来自后端）。 */
function gateBlock(data: SynthesisInventoryResponse, key: string) {
  const covered = data.coverage.covered[key] ?? [];
  const missing = data.coverage.missing[key] ?? [];
  const target = data.coverage.targets[key] ?? covered.length + missing.length;
  const gap = data.coverage.gaps?.[key];
  return {
    kind: gap?.status ?? 'UNKNOWN',
    declared_field: `coverage.${key}`,
    required: target,
    covered: covered.length,
    complete: covered.length >= target,
    covered_ids: covered,
    missing_ids: missing,
    evidence: Object.fromEntries(
      data.buckets.rows
        .filter((row) => row.covered && row.fragments > 0)
        .slice(0, 8)
        .map((row) => [row.id, row.runs[row.runs.length - 1] ?? row.id]),
    ),
  };
}

/** 规划用的基线 spec（真实字段；批大小会再被 backend 展开）。 */
function baseSpec(): Record<string, unknown> {
  return {
    schema: 'synlab.v3',
    data_scope: 'SYNTHETIC',
    release_profile: 'SANDBOX_CORE',
    experiment_purpose: 'DEVELOPMENT',
    master_seed: 20261001,
    dataset: { target_mothers: 1, target_fragments_estimate: 8 },
    fracture: { backend: 'plane_shared_cut', target_piece_range: [4, 12] },
    observation: {
      input_profile: 'SENSOR_PROXY',
      routes: ['proxy_scan'],
      views_per_fragment: 2,
      image_long_edge_px: 256,
      renderer: 'software_rasterizer',
    },
  };
}
