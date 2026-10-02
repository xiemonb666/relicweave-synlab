/**
 * U07 批量生成与任务 `/synlab/jobs`（计划 20.8）。
 *
 * 真实调用：`GET /stages`、`POST /specs/validate` + `POST /budgets`（先校验再提交）、
 * `POST /jobs`（幂等键防双击）、`GET /jobs`（分页 + state/stage/run 过滤 + with_total）、
 * `GET /jobs/{id}`（权威状态/阶段/依赖/资源估计/error）、`POST /jobs/{id}/pause|resume|cancel|retry`、
 * `GET /runs/{run_id}/events`（SSE，seq/revision 单调，断线按 Last-Event-ID 恢复）。
 *
 * 诚实点：
 * * **P50/P95 时间与实测 RSS/VRAM/IO 后端没有产出**，页面显示“未提供”，不用估算值冒充实测；
 * * 未知剩余时间显示“估算不足”，不按墙钟假装增长；
 * * 旧 SSE 不回退新状态（按 seq 归并），断线后可退化为 `GET /jobs?run_id=` 轮询。
 */

import { useEffect, useMemo, useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { BatchSynthesisPanel } from '../components/BatchSynthesisPanel';
import { JobTimeline } from '../components/JobTimeline';
import { MetricChart } from '../components/MetricChart';
import { RunSelector } from '../components/RunSelector';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { MeasuredQualityTable, progressRows } from '../components/MeasuredQualityTable';
import {
  ActionButton,
  Badge,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import {
  cancelJob,
  getJob,
  getStages,
  listJobs,
  pauseJob,
  resumeJob,
  retryJob,
} from '../api/endpoints';
import { newIdempotencyKey, useResource, useRunEventStream } from '../api/hooks';
import type { ControlResponse, JobRecord } from '../api/types';
import { formatGb, formatRelative, formatSeconds, jobStateLabel, pretty, runStatusLabel, truncate } from '../lib/format';
import { summarizeCounts, summarizeRuns } from '../lib/runs';
import { useAppState } from '../state/app-state';

const CREATE_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: '生成规模与配额（dataset / sampling）',
    children: [
      { kind: 'number', path: 'dataset.target_mothers', label: '母体数', integer: true, min: 1, unit: '个' },
      { kind: 'number', path: 'dataset.target_fragments_estimate', label: '目标片数', integer: true, min: 1, unit: '片' },
      { kind: 'string', path: 'sampling.quota_policy', label: '配额/组合策略', enumValues: ['registry_balanced', 'uniform', 'explicit'] },
      { kind: 'string', path: 'sampling.method', label: '采样方法', enumValues: ['latin_hypercube', 'sobol', 'quota_uniform'] },
      { kind: 'stringList', path: 'dataset.vessel_ids', label: '器物组合' },
      { kind: 'stringList', path: 'dataset.material_ids', label: '材料组合' },
      { kind: 'stringList', path: 'dataset.pattern_ids', label: '纹样组合' },
      { kind: 'stringList', path: 'dataset.layer_combo_ids', label: '层组合' },
      { kind: 'number', path: 'dataset.shape_lineage_split.train', label: 'split · train', min: 0, max: 1 },
      { kind: 'number', path: 'dataset.shape_lineage_split.dev', label: 'split · dev（留出）', min: 0, max: 1 },
      { kind: 'number', path: 'dataset.shape_lineage_split.confirm', label: 'split · confirm（留出）', min: 0, max: 1 },
      { kind: 'boolean', path: 'dataset.split_before_generation', label: '生成前切分（防同谱系泄漏）' },
    ],
  },
  {
    kind: 'group',
    label: '断裂 / 观察 / 退化',
    children: [
      { kind: 'string', path: 'fracture.backend', label: '事件后端（断裂）' },
      { kind: 'numberTuple', path: 'fracture.target_piece_range', label: '目标片数区间', length: 2, integer: true, unit: '片' },
      { kind: 'string', path: 'observation.input_profile', label: '观察输入档', enumValues: ['PHONE_RGB', 'SENSOR_PROXY', 'SENSOR_UPPER_BOUND'] },
      { kind: 'number', path: 'observation.views_per_fragment', label: '每片视角数', integer: true, min: 1 },
      { kind: 'string', path: 'observation.camera_profile_ref', label: '相机档引用（camera_profile_id）' },
      { kind: 'stringList', path: 'degraded_recipe_refs', label: '退化配方引用（recipe_id 列表）' },
      { kind: 'stringList', path: 'physical.recipes', label: '物理损伤配方' },
    ],
  },
  {
    kind: 'group',
    label: '资源与 checkpoint 策略',
    children: [
      { kind: 'number', path: 'resources.cpu_workers', label: 'CPU worker', integer: true, min: 1 },
      { kind: 'number', path: 'resources.cpu_rss_budget_gb', label: 'CPU RSS 预算', unit: 'GB', min: 0 },
      { kind: 'number', path: 'resources.gpu_budget_gb', label: 'GPU 显存预算', unit: 'GB', min: 0 },
      { kind: 'boolean', path: 'resources.reserve_temp_peak', label: '预留临时峰值' },
      { kind: 'number', path: 'storage.shard_target_mb', label: '分片目标', unit: 'MB', integer: true, min: 1 },
      { kind: 'string', path: 'quality.protocol_ref', label: 'QA 协议引用' },
      { kind: 'boolean', path: 'quality.fail_closed', label: 'QA fail-closed' },
    ],
  },
  {
    kind: 'group',
    label: '全局',
    children: [
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.v3'] },
      { kind: 'string', path: 'data_scope', label: '数据口径', enumValues: ['SYNTHETIC', 'REAL'] },
      { kind: 'string', path: 'release_profile', label: '发布 profile' },
      { kind: 'string', path: 'experiment_purpose', label: '实验用途', enumValues: ['SANDBOX', 'DEVELOPMENT', 'CONFIRMATION'] },
      { kind: 'number', path: 'master_seed', label: 'master seed', integer: true },
    ],
  },
];

const INITIAL_SPEC: FormValue = {
  schema: 'synlab.v3',
  data_scope: 'SYNTHETIC',
  release_profile: 'SANDBOX_CORE',
  experiment_purpose: 'DEVELOPMENT',
  master_seed: 20261001,
  dataset: {
    target_mothers: 1,
    target_fragments_estimate: 8,
    shape_lineage_split: { train: 0.8, dev: 0.1, confirm: 0.1 },
    split_before_generation: true,
    vessel_ids: ['V01'],
    material_ids: ['M01'],
    pattern_ids: ['PAT01'],
    layer_combo_ids: ['L01'],
  },
  sampling: { method: 'latin_hypercube', quota_policy: 'registry_balanced' },
  fracture: { backend: 'rough_shared_cut', target_piece_range: [8, 20] },
  observation: { input_profile: 'SENSOR_PROXY', views_per_fragment: 12 },
  resources: { cpu_workers: 2, cpu_rss_budget_gb: 30, gpu_budget_gb: 26, reserve_temp_peak: true },
  storage: { shard_target_mb: 512 },
  quality: { fail_closed: true },
  implementation: { require_poc_before_custom: false },
};

const JOB_STATE_FILTERS = ['PENDING', 'RUNNING', 'OUTPUT_READY', 'QA_PASS', 'COMMITTED', 'RETRYABLE', 'QUARANTINED', 'FAILED', 'CANCELLED', 'BLOCKED'];

export function JobsPage() {
  const app = useAppState();
  const stages = useResource((signal) => getStages(signal), []);
  const [stateFilters, setStateFilters] = useState<string[]>([]);
  const [stageFilter, setStageFilter] = useState('');
  const [createStage, setCreateStage] = useState('generate');
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey('jobs'));
  const [actionResult, setActionResult] = useState<ControlResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const jobs = useResource(
    (signal) =>
      listJobs(
        {
          run_id: app.selectedRunId ?? undefined,
          state: stateFilters.length > 0 ? stateFilters : undefined,
          stage: stageFilter || undefined,
          limit: 100,
          cursor: cursor ?? undefined,
          with_total: true,
        },
        signal,
      ),
    [app.selectedRunId, stateFilters.join('|'), stageFilter, cursor],
    { intervalMs: 12_000 },
  );

  const jobDetail = useResource((signal) => getJob(selectedJobId as string, signal), [selectedJobId], {
    enabled: Boolean(selectedJobId),
    intervalMs: selectedJobId ? 5_000 : 0,
  });

  const stream = useRunEventStream(app.selectedRunId, { enabled: Boolean(app.selectedRunId) });

  const items = jobs.data?.items ?? [];
  const runs = useMemo(() => summarizeRuns(items), [items]);
  const stageInfo = useMemo(
    () => (stages.data?.stages ?? []).find((stage) => stage.stage === createStage) ?? null,
    [stages.data, createStage],
  );

  useEffect(() => {
    if (!selectedJobId && items.length > 0) setSelectedJobId(items[0].job_id);
  }, [items, selectedJobId]);

  /** 计数直接来自真实 job 行；P50/P95 与实测资源后端没有产出，如实标“未提供”。 */
  const counts = useMemo(() => {
    const table: Record<string, number> = {};
    for (const job of items) table[job.state] = (table[job.state] ?? 0) + 1;
    return table;
  }, [items]);

  const failureCodes = useMemo(() => {
    const table = new Map<string, number>();
    for (const job of items) {
      if (!job.error) continue;
      const code = String((job.error as Record<string, unknown>).code ?? 'UNKNOWN');
      table.set(code, (table.get(code) ?? 0) + 1);
    }
    return [...table.entries()].sort((a, b) => b[1] - a[1]);
  }, [items]);

  const acceptedEvents = stream.events.filter((event) => event.type === 'run.accepted');
  const progressPoints = stream.events
    .filter((event) => event.progress && typeof event.progress.done === 'number')
    .map((event) => ({
      x: event.seq,
      y: event.progress?.done ?? null,
      n: event.progress?.planned ?? null,
      ref: event.job_id,
      label: event.type,
    }));

  const revision = jobDetail.data?.run.revision ?? null;
  const runStatus = jobDetail.data?.run.status ?? null;

  const act = async (action: 'pause' | 'resume' | 'cancel' | 'retry') => {
    if (!selectedJobId) return;
    setBusy(action);
    setActionResult(null);
    try {
      const response =
        action === 'pause'
          ? await pauseJob(selectedJobId, { revision, reason: 'UI 暂停（安全点）' })
          : action === 'resume'
            ? await resumeJob(selectedJobId, { revision, reason: 'UI 恢复' })
            : action === 'cancel'
              ? await cancelJob(selectedJobId, { revision, reason: 'UI 取消（停新步骤，保留已提交）' })
              : await retryJob(selectedJobId, { revision, reason: 'UI 重试' });
      setActionResult(response);
      jobDetail.reload();
      jobs.reload();
    } catch (error) {
      setActionResult({
        ok: false,
        action,
        run_id: '',
        run_status: '',
        previous_revision: revision ?? -1,
        revision: revision ?? -1,
        note: '',
        error: { message: (error as Error).message, raw: error },
      } as unknown as ControlResponse);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="批量生成与任务"
        plan="U07 · 计划 20.8"
        summary="先 validate + budget 再提交 run；监控 planned/attempted/accepted/quarantined、DAG 阶段、可量化阶段进度、失败按类型筛选；暂停/恢复/停止新任务/重试可恢复错误；取消不删已提交数据。"
        actions={
          <div className="row">
            <Badge tone="info">幂等键防双击</Badge>
            <Badge tone="warn">P50/P95 与实测资源：后端未产出</Badge>
          </div>
        }
      />

      <SectionCard
        title="创建任务（冻结 spec）"
        subtitle="POST /jobs —— HTTP 202 只表示已受理，不代表计算通过；stage 与能力需求来自 GET /stages"
      >
        <div className="row">
          <label className="field field--inline">
            <span className="field__label">stage</span>
            <select
              className="input input--tight"
              value={createStage}
              onChange={(event) => setCreateStage(event.target.value)}
              aria-label="任务阶段"
            >
              {(stages.data?.stages ?? [{ stage: 'generate', title: '批量生成（完整 DAG）', capabilities: [], requires_gpu: false, env: [], cost_class: '', estimate: {}, description: '', implemented_by: '' }]).map(
                (stage) => (
                  <option key={stage.stage} value={stage.stage}>
                    {stage.title}（{stage.stage}）
                  </option>
                ),
              )}
            </select>
          </label>
          {stageInfo ? (
            <span className="muted small">
              能力需求：
              <code className="mono">{stageInfo.capabilities.join(', ') || '无需能力模块'}</code>
              {stageInfo.env.length > 0 ? (
                <>
                  {' '}
                  · 环境需求：<code className="mono">{stageInfo.env.join(', ')}</code>
                </>
              ) : null}
              {stageInfo.requires_gpu ? ' · 需要 GPU' : ''} · 实现方 {stageInfo.implemented_by}
            </span>
          ) : null}
        </div>
        <p className="muted small">
          <code className="mono">freeze_spec</code> / <code className="mono">audit</code> / <code className="mono">export</code>{' '}
          由本 API 包自身实现，无能力依赖，一定会被受理；其余阶段只要有一个能力缺失，后端就返回{' '}
          <code className="mono">503 DEPENDENCY_CAPABILITY_MISSING</code> 且不创建半成品 run。
        </p>
        <div className="row">
          <span className="mono small">幂等键：{idempotencyKey}</span>
          <button type="button" className="btn btn--tiny" onClick={() => setIdempotencyKey(newIdempotencyKey('jobs'))}>
            换一个幂等键（模拟第二次点击）
          </button>
        </div>
        <SpecStudio
          kind="generation"
          fields={CREATE_FIELDS}
          initialSpec={INITIAL_SPEC}
          jobStage={createStage}
          plannedJobs={Number((INITIAL_SPEC.dataset as FormValue)?.target_mothers ?? 1)}
          requiresGpu={stageInfo?.requires_gpu ?? null}
          submitLabel={`提交 ${createStage} 任务`}
          onAccepted={(response) => {
            app.setSelectedRunId(response.run_id);
            if (response.job_id) setSelectedJobId(response.job_id);
          }}
        />
      </SectionCard>

      <BatchSynthesisPanel onSelectRun={app.setSelectedRunId} />

      <SectionCard
        title="run 选择与实时监控"
        subtitle="GET /jobs?run_id= · GET /runs/{run_id}/events"
        actions={
          <button type="button" className="btn btn--tiny" onClick={jobs.reload} disabled={jobs.refreshing}>
            {jobs.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        <RunSelector
          runs={runs}
          value={app.selectedRunId}
          onChange={app.setSelectedRunId}
          loading={jobs.status === 'loading'}
          error={jobs.status === 'error' ? jobs.error : null}
          onRetry={jobs.reload}
          emptyReason="GET /jobs 在这个工作区没有 job；先用上面的表单提交一个 run。"
        />

        {app.selectedRunId ? (
          <div className="grid2">
            <JobTimeline
              events={stream.events}
              streamState={stream.state}
              lastSeq={stream.lastSeq}
              streamError={stream.error}
              pollingFallback={stream.pollingFallback}
            />
            <div>
              <h3>可量化进度（来自 SSE 事件，不按墙钟推算）</h3>
              <MetricChart
                series={[{ name: '已完成工作量', unit: 'work units', points: progressPoints }]}
                xLabel="事件 seq"
                yLabel="done"
                caption="事件里的 progress.done 随 seq 递增；没有 progress 的事件不产生点"
                emptyReason="该 run 还没有携带 progress 的事件。后端只在 handler 真正计数时写 progress，本条不按时间估算。"
                height={200}
              />
              <KeyValueList
                rows={[
                  { label: '已接收事件', value: stream.events.length },
                  { label: 'run.accepted 事件', value: acceptedEvents.length },
                  { label: '最大 seq（Last-Event-ID）', value: stream.lastSeq },
                  { label: '流状态', value: stream.state },
                  {
                    label: 'P50 / P95 时间',
                    value: '未提供：API 没有 per-stage 耗时统计，页面不估算',
                  },
                  {
                    label: '实测 RSS / VRAM / IO / 磁盘',
                    value: '未提供：API 只返回 resource_estimate（估算），没有实测采样',
                  },
                  { label: '未知剩余时间', value: '估算不足（无历史吞吐基准时不给数字）' },
                ]}
              />
              <div className="row">
                <ActionButton onClick={stream.restart} disabledReason={stream.state === 'open' ? '事件流已连接' : null}>
                  重连事件流
                </ActionButton>
                <span className="muted small">
                  断线重连会带上 Last-Event-ID={stream.lastSeq}，旧 seq 不会回退新状态。
                </span>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState title="未选择 run" reason="选择上面的一个 run 后，这里显示真实 SSE 事件时间线与进度。" />
        )}
      </SectionCard>

      <SectionCard title="任务列表与筛选" subtitle="GET /jobs（keyset 分页；state 可多选，stage 单选）">
        <div className="filters">
          <fieldset className="filters__group">
            <legend>状态筛选</legend>
            {JOB_STATE_FILTERS.map((state) => (
              <label key={state} className="check">
                <input
                  type="checkbox"
                  checked={stateFilters.includes(state)}
                  onChange={(event) => {
                    setStateFilters(
                      event.target.checked ? [...stateFilters, state] : stateFilters.filter((value) => value !== state),
                    );
                    setCursor(null);
                  }}
                />
                {jobStateLabel(state).label}
              </label>
            ))}
            <button
              type="button"
              className="btn btn--tiny"
              onClick={() => setStateFilters([])}
              disabled={stateFilters.length === 0}
              title={stateFilters.length === 0 ? '当前没有筛选' : undefined}
            >
              清除状态筛选
            </button>
          </fieldset>
          <label className="field field--inline">
            <span className="field__label">stage</span>
            <select
              className="input input--tight"
              value={stageFilter}
              onChange={(event) => {
                setStageFilter(event.target.value);
                setCursor(null);
              }}
            >
              <option value="">（全部）</option>
              {(stages.data?.stages ?? []).map((stage) => (
                <option key={stage.stage} value={stage.stage}>
                  {stage.title}（{stage.stage}）
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="statrow">
          {Object.entries(counts).map(([state, count]) => (
            <span key={state} className="stat">
              <Badge tone={jobStateLabel(state).tone}>{jobStateLabel(state).label}</Badge>
              <strong>{count}</strong>
            </span>
          ))}
          {items.length === 0 ? <span className="muted">没有匹配的 job</span> : null}
          {jobs.data?.total !== undefined ? <span className="muted small">total={jobs.data.total}</span> : null}
        </div>

        {failureCodes.length > 0 ? (
          <p className="small">
            失败按类型：
            {failureCodes.map(([code, count]) => (
              <Badge key={code} tone="bad">
                {code} × {count}
              </Badge>
            ))}
          </p>
        ) : null}

        {jobs.status === 'loading' ? <LoadingState label="读取任务列表…" /> : null}
        {jobs.status === 'error' ? <ErrorState error={jobs.error} onRetry={jobs.reload} /> : null}

        {items.length > 0 ? (
          <div className="tablewrap">
            <table className="table">
              <caption>任务行（state 为权威状态；progress 缺失表示 handler 尚未计数）</caption>
              <thead>
                <tr>
                  <th scope="col">选择</th>
                  <th scope="col">job_id</th>
                  <th scope="col">stage</th>
                  <th scope="col">state</th>
                  <th scope="col">attempt</th>
                  <th scope="col">progress</th>
                  <th scope="col">error</th>
                  <th scope="col">更新</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((job) => (
                  <JobRow
                    key={job.job_id}
                    job={job}
                    selected={job.job_id === selectedJobId}
                    onSelect={() => setSelectedJobId(job.job_id)}
                    onFailure={() => app.openFailure(job.job_id)}
                    onProvenance={() => app.openProvenance({ kind: 'job', id: job.job_id })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="pager">
          <button
            type="button"
            className="btn btn--tiny"
            onClick={() => setCursor(null)}
            disabled={cursor === null}
            title={cursor === null ? '已是第一页（本页只支持回到首页；keyset 游标不能反向解码）' : undefined}
          >
            回到第一页
          </button>
          <button
            type="button"
            className="btn btn--tiny"
            onClick={() => setCursor(jobs.data?.next_cursor ?? null)}
            disabled={!jobs.data?.has_more}
            title={!jobs.data?.has_more ? '后端 has_more=false' : undefined}
          >
            下一页
          </button>
          <span className="muted small">
            limit={jobs.data?.limit ?? '—'} · scanned={jobs.data?.scanned ?? '—'} · cursor={cursor ? truncate(cursor, 12) : '首页'}
          </span>
        </div>
      </SectionCard>

      <SectionCard title="任务详情与控制" subtitle="GET /jobs/{id} · POST /jobs/{id}/pause|resume|cancel|retry">
        {!selectedJobId ? (
          <EmptyState title="未选择任务" reason="在上表中选择一个 job。" />
        ) : jobDetail.status === 'loading' && !jobDetail.data ? (
          <LoadingState label="读取 job 详情…" />
        ) : jobDetail.status === 'error' ? (
          <ErrorState error={jobDetail.error} onRetry={jobDetail.reload} />
        ) : jobDetail.data ? (
          <>
            <KeyValueList
              rows={[
                { label: 'job_id', value: jobDetail.data.job.job_id, mono: true },
                { label: 'stage', value: `${jobDetail.data.job.stage}（${jobDetail.data.stage_title}）` },
                { label: 'state', value: jobStateLabel(jobDetail.data.job.state).label },
                { label: 'attempt / fencing', value: `${jobDetail.data.job.attempt} / ${jobDetail.data.job.fencing}`, mono: true },
                { label: 'run 状态', value: runStatusLabel(runStatus).label },
                { label: 'run revision', value: revision ?? '未提供' },
                { label: '队列位置', value: jobDetail.data.queue_position === null ? '不在 PENDING 队列' : jobDetail.data.queue_position },
                { label: '依赖', value: jobDetail.data.dependencies.join(', ') || '无', mono: true },
                { label: '被它阻塞', value: jobDetail.data.blocked_dependents.join(', ') || '无', mono: true },
                { label: '输出资产', value: jobDetail.data.job.outputs.join(', ') || '无' },
              ]}
            />

            <div className="row">
              <ActionButton
                onClick={() => void act('pause')}
                busy={busy === 'pause'}
                disabledReason={
                  runStatus === 'PAUSED'
                    ? 'run 已经是 PAUSED'
                    : runStatus === 'CANCELLED'
                      ? 'run 已取消，无法暂停'
                      : revision === null
                        ? '后端未返回 run revision，无法做乐观并发控制'
                        : null
                }
              >
                暂停（安全点）
              </ActionButton>
              <ActionButton
                onClick={() => void act('resume')}
                busy={busy === 'resume'}
                disabledReason={runStatus !== 'PAUSED' ? `只有 PAUSED 的 run 能恢复（当前 ${runStatus ?? '未知'}）` : null}
              >
                恢复
              </ActionButton>
              <ActionButton
                tone="danger"
                onClick={() => void act('cancel')}
                busy={busy === 'cancel'}
                disabledReason={
                  runStatus === 'CANCELLED'
                    ? 'run 已取消'
                    : revision === null
                      ? '后端未返回 run revision'
                      : null
                }
              >
                停止新任务（取消）
              </ActionButton>
              <ActionButton
                tone="primary"
                onClick={() => void act('retry')}
                busy={busy === 'retry'}
                disabledReason={
                  jobDetail.data.error && (jobDetail.data.error as Record<string, unknown>).retryable
                    ? null
                    : `后端 error.retryable=${String((jobDetail.data.error as Record<string, unknown> | null)?.retryable ?? '无 error')}`
                }
              >
                重试（可恢复错误）
              </ActionButton>
              <ActionButton onClick={() => app.openFailure(selectedJobId)}>查看证据 / 隔离资产</ActionButton>
            </div>

            {actionResult ? (
              <div className="accepted" role="status">
                <h4>控制结果：{actionResult.action}</h4>
                {actionResult.ok ? (
                  <KeyValueList
                    rows={[
                      { label: 'run 状态', value: `${actionResult.run_status}（之前 revision ${actionResult.previous_revision} → ${actionResult.revision}）` },
                      { label: '未开始 job', value: (actionResult.jobs_not_started ?? []).join(', ') || '无' },
                      { label: '运行中 job', value: (actionResult.running_jobs ?? []).join(', ') || '无' },
                      { label: '已取消 job', value: (actionResult.cancelled_jobs ?? []).join(', ') || '无' },
                      { label: '保留已提交', value: (actionResult.committed_jobs_kept ?? []).join(', ') || '无' },
                      { label: '仍在阻塞', value: (actionResult.still_blocked ?? []).join(', ') || '无' },
                      { label: '说明', value: actionResult.note },
                    ]}
                  />
                ) : (
                  <ErrorState error={(actionResult.error as Record<string, unknown>)?.raw ?? actionResult.error} title="控制请求失败" />
                )}
              </div>
            ) : null}

            <h3>资源（估算）与实测进度</h3>
            <p className="muted small">
              下表第一组来自 <code className="mono">resource_estimate</code>（后端按 stage 给出的**估算**，不是实测），
              第二组来自 <code className="mono">progress</code>（真实计数）与 job spec。
            </p>
            <MeasuredQualityTable
              rows={[
                {
                  key: 'estimate.rss',
                  label: 'RSS 估算',
                  value: formatGb(jobDetail.data.resource_estimate.rss_gb),
                  unit: 'GB',
                  source: 'GET /jobs/{id}.resource_estimate（估算）',
                },
                {
                  key: 'estimate.vram',
                  label: 'VRAM 估算',
                  value: formatGb(jobDetail.data.resource_estimate.vram_gb),
                  unit: 'GB',
                  source: 'GET /jobs/{id}.resource_estimate（估算）',
                },
                {
                  key: 'estimate.temp',
                  label: '临时磁盘估算',
                  value: formatGb(jobDetail.data.resource_estimate.temp_disk_gb),
                  unit: 'GB',
                  source: 'GET /jobs/{id}.resource_estimate（估算）',
                },
                {
                  key: 'estimate.cpu',
                  label: 'CPU 时间估算',
                  value: formatSeconds(jobDetail.data.resource_estimate.cpu_seconds),
                  source: 'GET /jobs/{id}.resource_estimate（估算）',
                },
                ...progressRows(jobDetail.data.progress),
                {
                  key: 'measured.rss',
                  label: 'RSS 实测峰值',
                  value: null,
                  source: 'API 未提供实测采样',
                  flag: 'missing',
                },
                {
                  key: 'measured.io',
                  label: 'IO / 磁盘实测',
                  value: null,
                  source: 'API 未提供实测采样',
                  flag: 'missing',
                },
              ]}
              caption="估算与实测分开显示；缺失项不补 0"
            />

            <details>
              <summary>job.spec / error 原文</summary>
              <pre className="mono pre">{pretty(jobDetail.data.job.spec ?? {})}</pre>
              <pre className="mono pre">{pretty(jobDetail.data.job.error ?? null)}</pre>
            </details>
          </>
        ) : null}
      </SectionCard>

      <div className="grid2">
        <AssetBrowser
          title="输出资产"
          selectable="none"
          onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
          pageSize={12}
          emptyReason="工作区还没有资产；任务提交只代表已受理，产出由 worker 真实写入。"
        />
        <SectionCard title="失败/隔离任务（按类型）" subtitle="筛选出的真实 FAILED/QUARANTINED/RETRYABLE 行">
          {items.filter((job) => ['FAILED', 'QUARANTINED', 'RETRYABLE'].includes(job.state)).length === 0 ? (
            <EmptyState title="当前筛选下没有失败/隔离任务" />
          ) : (
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">job</th>
                  <th scope="col">状态</th>
                  <th scope="col">错误码</th>
                  <th scope="col">可重试</th>
                  <th scope="col">详情</th>
                </tr>
              </thead>
              <tbody>
                {items
                  .filter((job) => ['FAILED', 'QUARANTINED', 'RETRYABLE'].includes(job.state))
                  .map((job) => {
                    const error = job.error as Record<string, unknown> | null;
                    return (
                      <tr key={job.job_id}>
                        <td className="mono">{truncate(job.job_id, 18)}</td>
                        <td>
                          <Badge tone={jobStateLabel(job.state).tone}>{jobStateLabel(job.state).label}</Badge>
                        </td>
                        <td className="mono small">{error ? String(error.code ?? '—') : '未提供'}</td>
                        <td>{error ? <Badge tone={error.retryable ? 'warn' : 'bad'}>{String(error.retryable)}</Badge> : '—'}</td>
                        <td>
                          <button type="button" className="btn btn--tiny" onClick={() => app.openFailure(job.job_id)}>
                            打开
                          </button>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          )}
        </SectionCard>
      </div>

      <SectionCard title="run 汇总" subtitle="由真实 job 行按 run_id 归并">
        {runs.length === 0 ? (
          <EmptyState title="没有 run" />
        ) : (
          <ul className="runlist">
            {runs.map((run) => (
              <li key={run.run_id}>
                <div className="row">
                  <span className="mono">{truncate(run.run_id, 30)}</span>
                  <Badge tone={run.terminal ? 'neutral' : 'info'}>{run.terminal ? '已终止' : '未终止'}</Badge>
                  <span className="muted small">最近更新 {formatRelative(run.lastSeen)}</span>
                </div>
                <div className="muted small">{summarizeCounts(run)}</div>
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">
          成功统计由 accepted manifest / job.state 推得，不由前端累加猜测；取消或失败不会被计成成功。
        </p>
        <button
          type="button"
          className="btn btn--tiny"
          onClick={() => setSelectedJobId(items[0]?.job_id ?? null)}
          disabled={items.length === 0}
          title={items.length === 0 ? '列表为空' : undefined}
        >
          选中第一行
        </button>
        <span className="mono small"> 已选 {selectedJobId ?? '无'}</span>
      </SectionCard>
    </>
  );
}

function JobRow({
  job,
  selected,
  onSelect,
  onFailure,
  onProvenance,
}: {
  job: JobRecord;
  selected: boolean;
  onSelect: () => void;
  onFailure: () => void;
  onProvenance: () => void;
}) {
  const state = jobStateLabel(job.state);
  const error = job.error as Record<string, unknown> | null;
  return (
    <tr className={selected ? 'row--selected' : undefined}>
      <td>
        <input type="radio" name="job-select" checked={selected} onChange={onSelect} aria-label={`选择任务 ${job.job_id}`} />
      </td>
      <td className="mono" title={job.job_id}>
        {truncate(job.job_id, 20)}
      </td>
      <td className="mono">{job.stage}</td>
      <td>
        <Badge tone={state.tone}>{state.label}</Badge>
      </td>
      <td className="mono">{job.attempt}</td>
      <td className="mono small">
        {job.progress && typeof job.progress.done === 'number'
          ? `${job.progress.done}/${job.progress.planned ?? '?'} ${job.progress.unit ?? ''}`
          : '未计数'}
      </td>
      <td className="mono small">{error ? String(error.code ?? '—') : '—'}</td>
      <td>{formatRelative(job.updated_at)}</td>
      <td className="rowactions">
        {error ? (
          <button type="button" className="btn btn--tiny" onClick={onFailure}>
            失败详情
          </button>
        ) : null}
        <button type="button" className="btn btn--tiny" onClick={onProvenance}>
          溯源
        </button>
      </td>
    </tr>
  );
}
