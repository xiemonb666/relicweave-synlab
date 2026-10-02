/**
 * U10 诊断面板 `/synlab/diagnostics`（计划 20.11）。
 *
 * 真实调用：`POST /specs/validate`（kind=diagnose）、`POST /budgets`、`POST /diagnostics/runs`、
 * `GET /diagnostics/runs`、`GET /diagnostics/runs/{id}`（summary / query refs / curves）、
 * `GET /pools`、`GET /training/runs`。
 *
 * 诚实点：
 * * 无邻片的 query 显示风险而不是 0 召回（用 `n=0` / `flag` 标记真实表达）；
 * * 不同 M/K 的结果不混在同一条曲线 —— 页面把每条曲线的来源 run/checkpoint 与 pool 标出来，
 *   并且只画后端返回的点；
 * * 样本数未达要求时不显示“已证明”（`minSamples` 交给 MeasuredQualityTable 提示）。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { MetricChart, MetricHeatmap, type HeatmapCell } from '../components/MetricChart';
import { SpecStudio } from '../components/SpecStudio';
import type { FieldSpec, FormValue } from '../components/SchemaForm';
import { MeasuredQualityTable, flattenMetrics } from '../components/MeasuredQualityTable';
import {
  Badge,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import { getCapabilities, getDiagnosticsRun, listDiagnosticsRuns, listPools, listTrainingRuns, postDiagnosticsRuns } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues } from '../lib/caps';
import { parseCurves } from '../lib/curves';
import { asNumber, asString, isRecord, pretty, truncate } from '../lib/format';
import { useAppState } from '../state/app-state';

const DIAGNOSE_FIELDS: FieldSpec[] = [
  {
    kind: 'group',
    label: '固定实验定义（DiagnosticSpec）',
    children: [
      { kind: 'string', path: 'protocol_id', label: 'protocol_id', required: true, hint: '冻结实验协议标识' },
      { kind: 'string', path: 'schema', label: 'schema', enumValues: ['synlab.diagnose.v1'] },
      { kind: 'string', path: 'checkpoint_ref', label: 'checkpoint 引用' },
      { kind: 'string', path: 'release_ref', label: 'release 引用' },
      { kind: 'string', path: 'candidate_pool_ref', label: '固定候选池引用（pool_id）' },
      { kind: 'string', path: 'query_roster_ref', label: '固定 query roster 引用' },
      { kind: 'string', path: 'variant_map_ref', label: '变体映射引用' },
      { kind: 'string', path: 'evaluation_split', label: '评估 split', enumValues: ['train', 'dev', 'confirm'] },
    ],
  },
  {
    kind: 'group',
    label: '轴 / 档位 / 配对',
    children: [
      { kind: 'stringList', path: 'axes', label: '轴列表', hint: '来自 registry axis；未注册的轴会被后端拒绝' },
      { kind: 'stringList', path: 'levels', label: '档位（0..4）' },
      { kind: 'boolean', path: 'paired_basis', label: '配对 basis' },
      { kind: 'string', path: 'perturbation_side', label: '扰动侧', enumValues: ['QUERY_ONLY', 'QUERY_AND_CANDIDATE', 'CANDIDATE_ONLY'] },
      { kind: 'string', path: 'input_profile', label: '输入档位', enumValues: ['PHONE_RGB', 'SENSOR_PROXY', 'SENSOR_UPPER_BOUND'] },
      { kind: 'string', path: 'observation_route', label: '观测路线', enumValues: ['photo_mvs', 'proxy_scan', 'ideal_visible'] },
      { kind: 'stringList', path: 'seeds', label: 'seeds（观察 basis）' },
      { kind: 'string', path: 'seed_kind', label: 'seed 类型', enumValues: ['observation_basis'] },
      { kind: 'string', path: 'training_replicates_ref', label: '训练重复引用' },
    ],
  },
  {
    kind: 'group',
    label: '指标与统计',
    children: [
      { kind: 'stringList', path: 'metrics', label: '指标列表' },
      { kind: 'string', path: 'statistics.unit', label: '统计单位', enumValues: ['shape_lineage'] },
      { kind: 'number', path: 'statistics.bootstrap_replicates', label: 'bootstrap 重采样数', integer: true, min: 100 },
      { kind: 'number', path: 'statistics.confidence', label: '置信度', min: 0, max: 1 },
      { kind: 'string', path: 'statistics.multiple_testing', label: '多重比较', enumValues: ['holm_for_registered_comparisons', 'none'] },
      { kind: 'boolean', path: 'confirmation.open', label: '开放 confirm 集（只运行已冻结比较）' },
    ],
  },
];

const INITIAL_SPEC: FormValue = {
  schema: 'synlab.diagnose.v1',
  protocol_id: 'E-SYN-01',
  evaluation_split: 'dev',
  axes: [],
  levels: [0, 1, 4],
  paired_basis: true,
  perturbation_side: 'QUERY_ONLY',
  input_profile: 'SENSOR_PROXY',
  observation_route: 'proxy_scan',
  seed_kind: 'observation_basis',
  seeds: [11],
  metrics: ['HitAtK', 'CovRecallAtK', 'PoolCovAtM'],
  statistics: { unit: 'shape_lineage', bootstrap_replicates: 10000, confidence: 0.95, multiple_testing: 'holm_for_registered_comparisons' },
  confirmation: { open: false },
};

export function DiagnosticsPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const runs = useResource((signal) => listDiagnosticsRuns({ limit: 50 }, signal), [], { intervalMs: 15_000 });
  const pools = useResource((signal) => listPools({ limit: 50 }, signal), []);
  const training = useResource((signal) => listTrainingRuns({ limit: 50 }, signal), []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [spec, setSpec] = useState<FormValue>(INITIAL_SPEC);
  const [selectedQuery, setSelectedQuery] = useState<Record<string, unknown> | null>(null);

  const detail = useResource((signal) => getDiagnosticsRun(selectedId as string, signal), [selectedId], {
    enabled: Boolean(selectedId),
    intervalMs: selectedId ? 10_000 : 0,
  });

  const issues = capabilityIssues(capabilities.data ?? null, ['diagnostics', 'training']);
  const parsed = parseCurves(detail.data?.curves ?? []);
  const queries = detail.data?.queries ?? [];

  /** query → 热图单元：只从真实字段取，缺字段就标缺失。 */
  const heatCells: HeatmapCell[] = queries.flatMap((query, rowIndex) => {
    const record = isRecord(query) ? query : {};
    const row = asString(record.query_id ?? record.id) ?? `q${rowIndex}`;
    const metrics = isRecord(record.metrics) ? record.metrics : record;
    return Object.entries(metrics)
      .filter(([, value]) => typeof value === 'number' || value === null)
      .map(([metric, value]) => ({
        row,
        column: metric,
        value: asNumber(value),
        n: asNumber(record.n ?? record.neighbour_count),
        flag: asNumber(record.n) === 0 ? ('missing' as const) : null,
        ref: asString(record.query_id ?? record.id),
      }));
  });

  return (
    <>
      <PageHeader
        title="诊断面板"
        plan="U10 · 计划 20.11"
        summary="checkpoint / 固定 gallery-query / N 子集 / 轴与五档 / 训练与测试质量 / 算法消融 / 时间与 step 视角 / seeds / 簇统计。每个图都显示母体 n、区间、实际质量单位、缺失与失败。"
        actions={
          <div className="row">
            <Badge tone="info">固定 query 才可比较</Badge>
            <Badge tone="warn">无邻片显示风险，不写 0 召回</Badge>
          </div>
        }
      />

      {issues.length > 0 ? (
        <SectionCard title="诊断能力阻塞" subtitle="GET /capabilities">
          <p className="warning">
            <Badge tone="warn">{issues[0]?.status}</Badge> {describeIssues(issues)}
          </p>
          <p className="muted small">
            诊断阶段需要 <code className="mono">diagnostics</code> 与 <code className="mono">training</code> 能力；
            缺失时 <code className="mono">POST /diagnostics/runs</code> 返回 503 且不写入任何 run。
          </p>
        </SectionCard>
      ) : null}

      <SectionCard title="固定库与对照 run" subtitle="GET /pools · GET /training/runs">
        <div className="grid2">
          <div>
            <h3>关系池 / 固定 gallery</h3>
            {pools.data && pools.data.items.length > 0 ? (
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">pool_id</th>
                    <th scope="col">release</th>
                    <th scope="col">status</th>
                    <th scope="col">用作 pool_ref</th>
                  </tr>
                </thead>
                <tbody>
                  {pools.data.items.map((pool) => (
                    <tr key={pool.pool_id}>
                      <th scope="row" className="mono">
                        {truncate(pool.pool_id, 22)}
                      </th>
                      <td className="mono">{pool.release_id ?? '—'}</td>
                      <td>
                        <Badge tone={pool.status === 'NOT_RUN' ? 'warn' : 'neutral'}>{pool.status}</Badge>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--tiny"
                          onClick={() => setSpec({ ...spec, candidate_pool_ref: pool.pool_id })}
                        >
                          选为候选池
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="没有关系池" reason="诊断需要固定 gallery/query；池由 POST /pools 创建且需要 relations 能力。" />
            )}
          </div>
          <div>
            <h3>训练 checkpoint 候选</h3>
            {training.data && training.data.items.length > 0 ? (
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">training_run_id</th>
                    <th scope="col">status</th>
                    <th scope="col">job</th>
                    <th scope="col">用作 checkpoint</th>
                  </tr>
                </thead>
                <tbody>
                  {training.data.items.map((run) => (
                    <tr key={run.training_run_id}>
                      <th scope="row" className="mono">
                        {truncate(run.training_run_id, 22)}
                      </th>
                      <td>
                        <Badge tone={run.status === 'COMPLETED' ? 'ok' : 'warn'}>{run.status}</Badge>
                      </td>
                      <td className="mono small">{run.job_id ?? '—'}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--tiny"
                          onClick={() => setSpec({ ...spec, checkpoint_ref: run.training_run_id })}
                        >
                          选为 checkpoint
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="没有训练 run" reason="诊断必须对比真实 checkpoint；未训练的模型不能用示意权重代替。" />
            )}
          </div>
        </div>
      </SectionCard>

      <SpecStudio
        kind="diagnose"
        fields={DIAGNOSE_FIELDS}
        initialSpec={INITIAL_SPEC}
        value={spec}
        onValueChange={setSpec}
        jobStage="diagnostics"
        requiresGpu={true}
        submitLabel="提交诊断 run"
        submitOverrideLabel="POST /diagnostics/runs 原始响应"
        submitBlockReason={
          issues.length > 0 ? `能力不可用（${issues[0].status}）` : !spec.protocol_id ? 'protocol_id 不能为空' : null
        }
        submitOverride={(current) =>
          postDiagnosticsRuns({
            spec: current,
            checkpoint_ref: (current.checkpoint_ref as string) || null,
            pool_ref: (current.candidate_pool_ref as string) || null,
          })
        }
        onAccepted={(response) => {
          const id = (response as unknown as { diagnostics_run_id?: string }).diagnostics_run_id;
          if (id) setSelectedId(id);
          runs.reload();
        }}
      />

      <SectionCard
        title="诊断 run 列表"
        subtitle="GET /diagnostics/runs"
        actions={
          <button type="button" className="btn btn--tiny" onClick={runs.reload} disabled={runs.refreshing}>
            {runs.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        {runs.status === 'loading' ? <LoadingState label="读取诊断 run…" /> : null}
        {runs.status === 'error' ? <ErrorState error={runs.error} onRetry={runs.reload} /> : null}
        {runs.data ? (
          runs.data.items.length === 0 ? (
            <EmptyState title="还没有诊断 run" reason="提交后会以 202 受理；真实指标要等 worker 执行完。" />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">选择</th>
                  <th scope="col">diagnostics_run_id</th>
                  <th scope="col">protocol</th>
                  <th scope="col">status</th>
                  <th scope="col">job</th>
                  <th scope="col">result</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((run) => (
                  <tr key={run.diagnostics_run_id} className={selectedId === run.diagnostics_run_id ? 'row--selected' : undefined}>
                    <td>
                      <input
                        type="radio"
                        name="diag-run"
                        checked={selectedId === run.diagnostics_run_id}
                        onChange={() => setSelectedId(run.diagnostics_run_id)}
                        aria-label={`选择诊断 run ${run.diagnostics_run_id}`}
                      />
                    </td>
                    <td className="mono">{truncate(run.diagnostics_run_id, 24)}</td>
                    <td className="mono">{String((run.spec as Record<string, unknown>)?.protocol_id ?? '—')}</td>
                    <td>
                      <Badge tone={run.status === 'COMPLETED' ? 'ok' : run.status === 'FAILED' ? 'bad' : 'warn'}>{run.status}</Badge>
                    </td>
                    <td className="mono small">{run.job_id ?? '—'}</td>
                    <td>{Object.keys(run.result ?? {}).length > 0 ? <Badge tone="ok">有 result</Badge> : <Badge tone="warn">空（未运行）</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}
      </SectionCard>

      <SectionCard title="图表（全部来自后端 curves / queries）" subtitle="不替未运行的诊断生成指标">
        {!selectedId ? (
          <EmptyState title="未选择诊断 run" />
        ) : detail.status === 'error' ? (
          <ErrorState error={detail.error} onRetry={detail.reload} />
        ) : detail.data ? (
          <>
            <KeyValueList
              rows={[
                { label: 'diagnostics_run_id', value: detail.data.diagnostics_run.diagnostics_run_id, mono: true },
                { label: 'status', value: detail.data.diagnostics_run.status },
                { label: 'capability', value: `${detail.data.capability.status}（${detail.data.capability.module}）` },
                { label: 'curves', value: `${detail.data.curves.length} 条` },
                { label: 'queries', value: `${detail.data.queries.length} 条` },
                { label: 'not_run_reason', value: detail.data.not_run_reason ?? '（有 result）' },
              ]}
            />

            <h3>N 曲线 / 轴 P=f(d)（后端 curves）</h3>
            <MetricChart
              series={parsed.series}
              xLabel="step / level / N"
              yLabel="实测指标"
              caption="每条曲线的名称与单位来自后端；不同 M/K 的曲线名称不同，不会被合并"
              emptyReason={detail.data.not_run_reason ?? '后端没有返回可识别的曲线结构。'}
              onPointSelect={(point) => {
                const match = queries.find((query) => asString((query as Record<string, unknown>).query_id) === point.ref);
                if (match) setSelectedQuery(match as Record<string, unknown>);
              }}
            />
            {parsed.unparsed.length > 0 ? (
              <details open>
                <summary>结构未识别的曲线（原样展示）</summary>
                <pre className="mono pre">{pretty(parsed.unparsed)}</pre>
              </details>
            ) : null}

            <h3>N×Q / train-Q × test-Q 矩阵（来自 queries）</h3>
            <MetricHeatmap
              rows={[...new Set(heatCells.map((cell) => cell.row))]}
              columns={[...new Set(heatCells.map((cell) => cell.column))]}
              cells={heatCells}
              valueLabel="query 指标"
              caption="每个格子对应一条真实 per_query 记录；缺失显示“缺失”，n=0 的 query 标为风险"
              onCellSelect={(cell) => {
                const match = queries.find((query) => asString((query as Record<string, unknown>).query_id) === cell.ref);
                if (match) setSelectedQuery(match as Record<string, unknown>);
              }}
              emptyReason={detail.data.not_run_reason ?? '后端没有返回 per_query 记录。'}
            />

            <h3>per_query 下钻</h3>
            {queries.length === 0 ? (
              <EmptyState title="没有 per_query 记录" reason={detail.data.not_run_reason ?? '后端未返回 queries 数组。'} />
            ) : (
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">query</th>
                    <th scope="col">n（邻片数）</th>
                    <th scope="col">风险</th>
                    <th scope="col">详情</th>
                  </tr>
                </thead>
                <tbody>
                  {queries.map((query, index) => {
                    const record = isRecord(query) ? query : {};
                    const n = asNumber(record.n ?? record.neighbour_count);
                    return (
                      <tr key={asString(record.query_id) ?? index}>
                        <th scope="row" className="mono">
                          {asString(record.query_id ?? record.id) ?? `q${index}`}
                        </th>
                        <td className="mono">{n === null ? '未提供' : n}</td>
                        <td>
                          {n === 0 ? <Badge tone="warn">无邻片：显示风险而不是 0 召回</Badge> : <Badge tone="neutral">—</Badge>}
                        </td>
                        <td>
                          <button type="button" className="btn btn--tiny" onClick={() => setSelectedQuery(record)}>
                            查看输入帧与证据
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            {selectedQuery ? (
              <div className="drawer__section">
                <h4>per_query 记录（后端原样）</h4>
                <pre className="mono pre">{pretty(selectedQuery)}</pre>
                <p className="muted small">
                  每条记录里的 gallery/model/release hash、初检/TopK、全真邻集合引用、接受决定、失败与成本都应由后端写入；
                  页面不补齐缺失键。研究标签只在 researcher 会话下出现。
                </p>
              </div>
            ) : null}

            <MeasuredQualityTable
              rows={flattenMetrics(detail.data.diagnostics_run.result, {
                prefix: 'result',
                origin: 'GET /diagnostics/runs/{id}.result',
              })}
              caption="result 顶层标量与数组（数组只显示长度，不含像素数据）"
              emptyTitle="result 为空"
              emptyReason={detail.data.not_run_reason ?? '未运行的诊断没有 summary。'}
            />
            <p className="muted small">
              默认研究诊断入口与比赛现场候选页分开：部署会话的 <code className="mono">GET /diagnostics/runs/&#123;id&#125;</code>
              会隐藏 <code className="mono">per_query_truth</code> 与 <code className="mono">spurious_mask</code>。
            </p>
            <AssetBrowser
              title="诊断产物（diagnostic_report / query_roster / feature_bundle）"
              fixedRoles={['diagnostic_report', 'query_roster', 'feature_bundle']}
              selectable="none"
              onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
              pageSize={8}
              emptyReason="还没有诊断产物。导出表与图必须来自同一批实测点，未运行就没有产物。"
            />
          </>
        ) : (
          <LoadingState label="读取诊断详情…" />
        )}
      </SectionCard>

      <SectionCard title="诊断页未实现项（如实列出）" subtitle="计划 20.11 的图表清单">
        <ul className="notes">
          <li>
            <strong>材料/器型最差层</strong>：需要按 material/vessel 分层的真实统计表；后端 result 若提供该键，
            会在上表与曲线中原样出现，页面不自行分层推断。
          </li>
          <li>
            <strong>增益/成本图</strong>：需要后端给出成本（时间/step）字段；当前 API 的 curves 结构由实现模块决定，
            未识别结构会列在“结构未识别”里。
          </li>
          <li>
            <strong>跳回退化页面</strong>：U05 已经提供同一资产的比较视口；跨页跳转需要 query 记录里带 asset ref，
            后端未提供时该操作不可用（页面不会猜一个 id）。
          </li>
        </ul>
      </SectionCard>
    </>
  );
}
