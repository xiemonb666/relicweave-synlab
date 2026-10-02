/**
 * U09 预训练 `/synlab/training`（计划 20.10）。
 *
 * 真实调用：`GET /releases`（合格 release 选择）、`POST /specs/validate`（kind=train）、
 * `POST /budgets`、`POST /training/runs`（GPU 租约 + 冻结输入合同）、`GET /training/runs`、
 * `GET /training/runs/{id}`（state/checkpoints/metrics/curves）、
 * `POST /training/runs/{id}/resume`（从实际 step/游标续训）、`POST /pools`。
 *
 * 诚实点：
 * * 曲线只来自后端 `result.curves`；未运行时 `not_run_reason` 会说明“不生成任何 loss 曲线”；
 * * 确认用途不得选 SANDBOX：本页把 `experiment_purpose`/`release_profile_required` 原样暴露并交给服务端校验；
 * * 没有 GPU 时 `gpu_blocked` 会带 `ENV_CAPABILITY_MISSING` 与真实原因。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { MetricChart } from '../components/MetricChart';
import { RunSelector } from '../components/RunSelector';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { MeasuredQualityTable } from '../components/MeasuredQualityTable';
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
import { getCapabilities, getTrainingRun, listPools, listReleases, listTrainingRuns, postPools, postTrainingRuns, resumeTrainingRun } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues } from '../lib/caps';
import { metricsToRows, parseCurves } from '../lib/curves';
import { formatTimestamp, pretty, truncate } from '../lib/format';
import { summarizeRuns } from '../lib/runs';
import { listJobs } from '../api/endpoints';
import { useAppState } from '../state/app-state';

const TRAIN_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: 'run 标识与阶段（TrainingSpec）',
    children: [
      { kind: 'string', path: 'run_name', label: 'run 名称', required: true },
      { kind: 'string', path: 'release_ref', label: 'release 引用', required: true, hint: '必须是已有 release_id' },
      { kind: 'string', path: 'stage', label: '阶段 P0–P4', enumValues: ['P0', 'P1', 'P2', 'P3', 'P4'] },
      {
        kind: 'string',
        path: 'migration_group',
        label: '迁移组 T0–T3',
        enumValues: ['T0_SCRATCH_REAL', 'T1_PUBLIC_REAL', 'T2_PUBLIC_SYN_REAL', 'T3_PUBLIC_MIXED_REAL'],
      },
      { kind: 'number', path: 'train_seed', label: '训练种子', integer: true },
      {
        kind: 'string',
        path: 'release_profile_required',
        label: '要求的 release profile',
        enumValues: ['SANDBOX_CORE', 'PILOT', 'CORE_COVERAGE', 'SCALE_10K', 'SCALE_50K', 'SCALE_100K', 'CALIBRATED_PHONE', 'RESEARCH_EVIDENCE'],
        hint: '确认用途不得选 SANDBOX：后端会按 profile/route/范围检查 release 资格',
      },
      { kind: 'string', path: 'device', label: '设备', enumValues: ['cpu', 'cuda', 'auto'] },
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.train.v1'] },
    ],
  },
  {
    kind: 'group',
    label: '输入合同与冻结边界（inputs / initialization）',
    children: [
      { kind: 'string', path: 'initialization.kind', label: '初始化', enumValues: ['existing_public_or_project_backbone', 'random', 'classical'] },
      { kind: 'string', path: 'initialization.checkpoint_ref', label: '初始化 checkpoint 引用' },
      { kind: 'boolean', path: 'initialization.allow_random_fallback', label: '允许随机回退' },
      { kind: 'number', path: 'inputs.local_token_budget', label: '局部 token 预算', integer: true, min: 1 },
      { kind: 'string', path: 'inputs.quality_source', label: '质量来源', enumValues: ['OBS_EST', 'GT_ORACLE'] },
      { kind: 'string', path: 'inputs.roi_source', label: 'ROI 来源', enumValues: ['observed_estimator', 'MANUAL_OBS', 'HEURISTIC_OBS', 'ORACLE_ROI'] },
      { kind: 'string', path: 'inputs.input_profile', label: '输入档位', enumValues: ['PHONE_RGB', 'SENSOR_PROXY', 'SENSOR_UPPER_BOUND'] },
      { kind: 'string', path: 'inputs.observation_route', label: '观测路线', enumValues: ['photo_mvs', 'proxy_scan', 'ideal_visible'] },
      { kind: 'string', path: 'inputs.feature_schema', label: '特征 schema' },
    ],
  },
  {
    kind: 'group',
    label: '采样与优化（sampling / optimization）',
    children: [
      { kind: 'number', path: 'sampling.queries_per_microbatch', label: 'microbatch 内 query 数', integer: true, min: 1 },
      { kind: 'number', path: 'sampling.positive_limit', label: '正例上限', integer: true, min: 1 },
      { kind: 'number', path: 'sampling.legal_negative_limit', label: '合法负例上限', integer: true, min: 0 },
      { kind: 'number', path: 'optimization.accumulation_steps', label: '梯度累积步数', integer: true, min: 1 },
      { kind: 'number', path: 'optimization.max_steps', label: '最大 step', integer: true, min: 1 },
      { kind: 'number', path: 'optimization.head_lr', label: 'head 学习率', min: 0 },
      { kind: 'number', path: 'optimization.backbone_lr', label: 'backbone 学习率', min: 0 },
      { kind: 'number', path: 'optimization.weight_decay', label: 'weight decay', min: 0 },
      { kind: 'number', path: 'optimization.gradient_clip_norm', label: '梯度裁剪范数', min: 0 },
      { kind: 'string', path: 'optimization.optimizer', label: '优化器', enumValues: ['AdamW', 'SGD'] },
      { kind: 'string', path: 'optimization.precision', label: '精度', enumValues: ['fp32', 'bf16_if_verified'] },
    ],
  },
  {
    kind: 'group',
    label: '五项 loss（losses）',
    children: [
      { kind: 'number', path: 'losses.rank', label: 'rank loss 权重', min: 0 },
      { kind: 'number', path: 'losses.view', label: 'view loss 权重', min: 0 },
      { kind: 'number', path: 'losses.correspondence', label: 'correspondence loss 权重', min: 0 },
      { kind: 'number', path: 'losses.quality', label: 'quality loss 权重', min: 0 },
      { kind: 'number', path: 'losses.contradiction', label: 'contradiction loss 权重', min: 0 },
    ],
  },
  {
    kind: 'group',
    label: '课程 / 评估 / checkpoint',
    children: [
      { kind: 'boolean', path: 'curriculum.enabled', label: '启用课程学习' },
      { kind: 'string', path: 'curriculum.comparison_ref', label: '课程对照引用（随机对照）' },
      { kind: 'number', path: 'curriculum.clean_minimum_fraction', label: 'clean 最低占比', min: 0, max: 1 },
      { kind: 'string', path: 'evaluation.split', label: '评估 split', enumValues: ['train', 'dev', 'confirm'] },
      { kind: 'number', path: 'evaluation.interval_steps', label: '评估间隔 step', integer: true, min: 1 },
      { kind: 'string', path: 'evaluation.candidate_pool_ref', label: '候选池引用（pool_id）' },
      { kind: 'number', path: 'checkpoint.interval_steps', label: 'checkpoint 间隔 step', integer: true, min: 1 },
      { kind: 'string', path: 'retrieval.first_stage', label: '检索一阶段', enumValues: ['normalized_dual_encoder', 'classical_descriptor'] },
      { kind: 'string', path: 'retrieval.refinement', label: '检索精化', enumValues: ['observed_local_pair_head', 'none', 'classical_local'] },
      { kind: 'number', path: 'retrieval.candidate_pool_size', label: '候选池大小', integer: true, min: 1 },
    ],
  },
];

const INITIAL_SPEC: FormValue = {
  schema: 'synlab.train.v1',
  run_name: 'ui_train_run',
  train_seed: 11,
  release_ref: '',
  split: 'train',
  release_profile_required: 'PILOT',
  stage: 'P0',
  device: 'auto',
  initialization: { kind: 'random' },
  inputs: { local_token_budget: 256, quality_source: 'OBS_EST', roi_source: 'observed_estimator', input_profile: 'SENSOR_PROXY', observation_route: 'proxy_scan', feature_schema: 'a12.obs.v1' },
  sampling: { queries_per_microbatch: 2, positive_limit: 2, legal_negative_limit: 8 },
  optimization: { optimizer: 'AdamW', head_lr: 0.0001, backbone_lr: 0.00001, weight_decay: 0.01, gradient_clip_norm: 1, accumulation_steps: 1, max_steps: 5000, precision: 'fp32' },
  losses: { rank: 1, view: 0.1, correspondence: 0, quality: 0, contradiction: 0 },
  curriculum: { enabled: false, clean_minimum_fraction: 0.2 },
  evaluation: { split: 'dev', interval_steps: 500 },
  checkpoint: { interval_steps: 500 },
  retrieval: { first_stage: 'normalized_dual_encoder', refinement: 'observed_local_pair_head', candidate_pool_size: 200 },
};

export function TrainingPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const releases = useResource((signal) => listReleases({ limit: 50 }, signal), []);
  const pools = useResource((signal) => listPools({ limit: 50 }, signal), []);
  const runs = useResource((signal) => listTrainingRuns({ limit: 50 }, signal), [], { intervalMs: 15_000 });
  const jobs = useResource((signal) => listJobs({ limit: 100 }, signal), [], { intervalMs: 15_000 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [spec, setSpec] = useState<FormValue>(INITIAL_SPEC);

  const detail = useResource((signal) => getTrainingRun(selectedId as string, signal), [selectedId], {
    enabled: Boolean(selectedId),
    intervalMs: selectedId ? 8000 : 0,
  });

  const issues = capabilityIssues(capabilities.data ?? null, ['training']);
  const cuda = capabilities.data?.env ? capabilities.data.env['cuda'] : undefined;

  const parsed = parseCurves(detail.data?.curves ?? []);
  const runSummaries = summarizeRuns(jobs.data?.items ?? []);

  const createPool = async () => {
    const releaseId = String(spec.release_ref ?? '');
    setBusy('pool');
    setActionError(null);
    try {
      await postPools({ release_id: releaseId, spec: { gallery: 'ui_requested' } });
      pools.reload();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(null);
    }
  };

  const resume = async () => {
    if (!selectedId) return;
    setBusy('resume');
    setActionError(null);
    try {
      await resumeTrainingRun(selectedId, { checkpoint_ref: null });
      runs.reload();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="预训练"
        plan="U09 · 计划 20.10"
        summary="release / P0–P4 / 模型与初始化 T 组 / 冻结边界 / 局部 token 预算 / microbatch 与累积 / 五项 loss / 课程与随机对照 / step 与预算 / dev-confirm 用途；曲线只来自实测日志。"
        actions={
          <div className="row">
            <Badge tone={cuda?.status === 'OK' ? 'ok' : 'warn'}>CUDA：{cuda?.status ?? '未探测'}</Badge>
            <Badge tone="info">确认用途不得选 SANDBOX</Badge>
          </div>
        }
      />

      {issues.length > 0 ? (
        <BlockedStateWrapper issues={issues} />
      ) : null}

      <SectionCard title="合格 release 与关系池" subtitle="GET /releases · GET /pools">
        {releases.status === 'error' ? <ErrorState error={releases.error} onRetry={releases.reload} compact /> : null}
        {releases.data ? (
          releases.data.items.length === 0 ? (
            <EmptyState
              title="没有可用 release"
              reason={
                <>
                  {releases.data.empty_reason ?? '后端没有 release。'}
                  <br />
                  训练只接受与训练目标、route 和声明范围兼容的**合格 release**；本页不会用未发布的资产充当训练输入。
                </>
              }
            />
          ) : (
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">release_id</th>
                  <th scope="col">profile</th>
                  <th scope="col">选择</th>
                </tr>
              </thead>
              <tbody>
                {releases.data.items.map((item) => {
                  const id = String((item as Record<string, unknown>).release_id ?? '');
                  return (
                    <tr key={id}>
                      <th scope="row" className="mono">
                        {id}
                      </th>
                      <td className="mono">{String((item as Record<string, unknown>).profile ?? '—')}</td>
                      <td>
                        <button type="button" className="btn btn--tiny" onClick={() => setSpec({ ...spec, release_ref: id })}>
                          用作 release_ref
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )
        ) : (
          <LoadingState label="读取 release 列表…" />
        )}

        <h3>
          关系池 <Badge tone={pools.data?.capability.available ? 'ok' : 'warn'}>{pools.data?.capability.status ?? '—'}</Badge>
        </h3>
        {pools.data?.capability.available === false ? (
          <p className="warning">
            能力 relations 不可用：{pools.data.capability.error ?? '后端未给出原因'}。构建 pool 会返回 503
            DEPENDENCY_CAPABILITY_MISSING，且不会写入任何行。
          </p>
        ) : null}
        {pools.data && pools.data.items.length > 0 ? (
          <table className="table table--tight">
            <thead>
              <tr>
                <th scope="col">pool_id</th>
                <th scope="col">release</th>
                <th scope="col">status</th>
                <th scope="col">job</th>
              </tr>
            </thead>
            <tbody>
              {pools.data.items.map((pool) => (
                <tr key={pool.pool_id}>
                  <th scope="row" className="mono">
                    {truncate(pool.pool_id, 24)}
                  </th>
                  <td className="mono">{pool.release_id ?? '—'}</td>
                  <td>
                    <Badge tone={pool.status === 'NOT_RUN' ? 'warn' : 'neutral'}>{pool.status}</Badge>
                  </td>
                  <td className="mono small">{pool.job_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="没有关系池" reason="池由 POST /pools 创建，需要 relations 能力。" />
        )}
        <div className="row">
          <ActionButton
            onClick={() => void createPool()}
            busy={busy === 'pool'}
            disabledReason={
              !spec.release_ref
                ? '先在 spec.release_ref 里指定 release'
                : pools.data?.capability.available === false
                  ? `能力 relations 不可用（${pools.data.capability.status}）`
                  : null
            }
          >
            按当前 release 构建关系池
          </ActionButton>
        </div>
        {actionError ? <ErrorState error={actionError} title="池/续训请求失败" /> : null}
      </SectionCard>

      <SpecStudio
        kind="train"
        fields={TRAIN_FIELDS}
        initialSpec={INITIAL_SPEC}
        value={spec}
        onValueChange={setSpec}
        jobStage="training"
        requiresGpu={true}
        submitLabel="提交训练 run"
        submitOverrideLabel="POST /training/runs 原始响应"
        submitBlockReason={
          issues.length > 0
            ? `能力 training 不可用（${issues[0].status}）`
            : !spec.release_ref
              ? 'spec.release_ref 不能为空：训练必须绑定真实 release'
              : !spec.run_name
                ? 'run_name 不能为空'
                : null
        }
        submitOverride={(current) =>
          postTrainingRuns({ spec: current, release_id: String(current.release_ref ?? '') || null })
        }
        onAccepted={(response) => {
          app.setSelectedRunId(response.run_id ?? null);
          const id = (response as unknown as { training_run_id?: string }).training_run_id;
          if (id) setSelectedId(id);
          runs.reload();
        }}
      />

      <SectionCard
        title="训练 run 列表"
        subtitle="GET /training/runs（status 与 result 来自真实 row）"
        actions={
          <button type="button" className="btn btn--tiny" onClick={runs.reload} disabled={runs.refreshing}>
            {runs.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        {runs.status === 'loading' ? <LoadingState label="读取训练 run…" /> : null}
        {runs.status === 'error' ? <ErrorState error={runs.error} onRetry={runs.reload} /> : null}
        {runs.data ? (
          runs.data.items.length === 0 ? (
            <EmptyState title="还没有训练 run" reason="POST /training/runs 成功后这里会出现真实 run 行。" />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">选择</th>
                  <th scope="col">training_run_id</th>
                  <th scope="col">release</th>
                  <th scope="col">status</th>
                  <th scope="col">job</th>
                  <th scope="col">result</th>
                  <th scope="col">更新</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((run) => (
                  <tr key={run.training_run_id} className={selectedId === run.training_run_id ? 'row--selected' : undefined}>
                    <td>
                      <input
                        type="radio"
                        name="training-run"
                        checked={selectedId === run.training_run_id}
                        onChange={() => setSelectedId(run.training_run_id)}
                        aria-label={`选择训练 run ${run.training_run_id}`}
                      />
                    </td>
                    <td className="mono">{truncate(run.training_run_id, 24)}</td>
                    <td className="mono">{run.release_id ?? '—'}</td>
                    <td>
                      <Badge tone={run.status === 'COMPLETED' ? 'ok' : run.status === 'FAILED' ? 'bad' : 'warn'}>{run.status}</Badge>
                    </td>
                    <td className="mono small">{run.job_id ?? '—'}</td>
                    <td>{Object.keys(run.result ?? {}).length > 0 ? <Badge tone="ok">有 result</Badge> : <Badge tone="warn">空（未运行）</Badge>}</td>
                    <td>{formatTimestamp(run.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}
      </SectionCard>

      <SectionCard title="训练详情：state / checkpoints / metrics / curves" subtitle="GET /training/runs/{id}">
        {!selectedId ? (
          <EmptyState title="未选择训练 run" />
        ) : detail.status === 'error' ? (
          <ErrorState error={detail.error} onRetry={detail.reload} />
        ) : detail.data ? (
          <>
            <KeyValueList
              rows={[
                { label: 'training_run_id', value: detail.data.training_run.training_run_id, mono: true },
                { label: 'status', value: detail.data.training_run.status },
                { label: 'release_id', value: detail.data.training_run.release_id ?? '—', mono: true },
                { label: 'job_id', value: detail.data.training_run.job_id ?? '—', mono: true },
                { label: 'checkpoint 资产', value: detail.data.checkpoint_assets.join(', ') || '无' },
                { label: 'capability', value: `${detail.data.capability.status}（${detail.data.capability.module}）` },
                { label: 'not_run_reason', value: detail.data.not_run_reason ?? '（有 result）' },
              ]}
            />

            <div className="row">
              <ActionButton
                onClick={() => void resume()}
                busy={busy === 'resume'}
                disabledReason={
                  ['COMPLETED', 'INTERRUPTED', 'PAUSED', 'RUNNING'].includes(detail.data.training_run.status)
                    ? null
                    : `后端只允许 COMPLETED / INTERRUPTED / PAUSED / RUNNING 续训（当前 ${detail.data.training_run.status}）`
                }
              >
                从 checkpoint 续训
              </ActionButton>
              <ActionButton
                onClick={() => {
                  const jobId = detail.data?.training_run.job_id;
                  if (jobId) app.openFailure(jobId);
                }}
                disabledReason={detail.data.training_run.job_id ? null : '该 run 没有关联 job'}
              >
                打开日志 / 失败详情
              </ActionButton>
              <ActionButton
                onClick={() => app.openProvenance({ kind: 'job', id: detail.data?.training_run.job_id ?? '' })}
                disabledReason={detail.data.training_run.job_id ? null : '该 run 没有关联 job'}
              >
                训练输入合同（job spec）
              </ActionButton>
            </div>

            <h3>metrics（后端 result.metrics，原样）</h3>
            <MeasuredQualityTable
              rows={metricsToRows(detail.data.metrics, 'GET /training/runs/{id}.metrics')}
              caption="训练 metrics"
              emptyTitle="没有 metrics"
              emptyReason="未运行的训练不会生成 metrics（后端 not_run_reason 会给出原因）。"
            />

            <h3>curves（后端 result.curves）</h3>
            <MetricChart
              series={parsed.series}
              xLabel="step / 索引"
              yLabel="实测值"
              caption="曲线点全部来自后端 curves；缺失点断线，不拟合"
              emptyReason={
                detail.data.not_run_reason ??
                '后端没有返回可识别的曲线结构；页面原样列出原始 JSON，不绘制示意曲线。'
              }
            />
            {parsed.unparsed.length > 0 ? (
              <details open>
                <summary>结构未识别的曲线条目（原样展示，不绘制）</summary>
                <ul className="problems">
                  {parsed.unparsed.map((item) => (
                    <li key={item.name}>
                      <strong className="mono">{item.name}</strong>：{item.reason}
                      <pre className="mono pre">{pretty(item.raw)}</pre>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}

            <details>
              <summary>job 列表 / 原始 result</summary>
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">job</th>
                    <th scope="col">stage</th>
                    <th scope="col">state</th>
                    <th scope="col">progress</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.data.jobs.map((job) => (
                    <tr key={job.job_id}>
                      <th scope="row" className="mono">
                        {truncate(job.job_id, 20)}
                      </th>
                      <td className="mono">{job.stage}</td>
                      <td>
                        <Badge tone={job.state === 'COMMITTED' ? 'ok' : job.state === 'FAILED' ? 'bad' : 'warn'}>{job.state}</Badge>
                      </td>
                      <td className="mono small">
                        {job.progress ? `${job.progress.done ?? '?'}/${job.progress.planned ?? '?'}` : '未计数'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <pre className="mono pre">{pretty(detail.data.training_run.result)}</pre>
            </details>
          </>
        ) : (
          <LoadingState label="读取训练 run 详情…" />
        )}
      </SectionCard>

      <div className="grid2">
        <RunSelector runs={runSummaries} value={app.selectedRunId} onChange={app.setSelectedRunId} label="训练相关 run（来自 GET /jobs）" />
        <AssetBrowser
          title="checkpoint 资产（train_checkpoint / train_metrics）"
          fixedRoles={['train_checkpoint', 'train_metrics']}
          selectable="none"
          onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
          pageSize={8}
          emptyReason="还没有 checkpoint 资产。训练未运行时不会产生 checkpoint。"
        />
      </div>

      <SectionCard title="导出模型观测输入合同" subtitle="job spec 即为冻结输入合同（GET /jobs/{job_id}）">
        <p className="muted">
          输入合同由 <code className="mono">POST /training/runs</code> 写入的 job spec 承载（feature_schema / local_token_budget /
          input_profile / observation_route / oracle_features=false 等），可在“训练输入合同”按钮打开的溯源抽屉中查看与复制。
        </p>
      </SectionCard>
    </>
  );
}

function BlockedStateWrapper({ issues }: { issues: ReturnType<typeof capabilityIssues> }) {
  return (
    <SectionCard title="训练能力阻塞" subtitle="GET /capabilities">
      <p className="warning">
        <Badge tone="warn">{issues[0]?.status}</Badge> {describeIssues(issues)}
      </p>
      <p className="muted small">
        训练阶段需要 capability <code className="mono">training</code>（以及真实的 GPU 环境）。
        能力缺失时 <code className="mono">POST /training/runs</code> 返回 503 且不创建任何 run。
      </p>
    </SectionCard>
  );
}
