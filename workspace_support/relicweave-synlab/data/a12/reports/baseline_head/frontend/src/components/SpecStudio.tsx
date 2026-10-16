/**
 * SpecStudio —— 通用“草稿 → 校验 → 预算 → 预览/提交”工作台（计划 20.1 的流程要求）。
 *
 * 被 U02/U03/U04（generation）、U05（recipe）、U09（train）、U10（diagnose）复用。
 * 所有按钮的禁用都带**具体原因**；所有动作都打真实 API：
 *
 * * `POST /specs/validate` —— 字段/单位/组合/版本；
 * * `POST /budgets`        —— 实测基准引用 + 准入；
 * * `POST /previews`       —— 版本化 preview job（只改本地草稿，未运行前标“未计算”）；
 * * `POST /jobs`           —— 冻结 spec + 幂等键 → run/job refs。
 *
 * 任何一步失败都把后端错误原样展示（code/status/stage/request_id/details），不做本地兜底。
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { postBudgets, postJobs, postPreviews, validateSpec } from '../api/endpoints';
import { getRegistry } from '../api/endpoints';
import { newIdempotencyKey, useResource } from '../api/hooks';
import type {
  BudgetReport,
  JobAcceptedResponse,
  JsonSchemaNode,
  SpecValidationResponse,
} from '../api/types';
import { pretty } from '../lib/format';
import { SchemaForm, type FieldSpec, type FormValue } from './SchemaForm';
import { ResourceBudgetCard } from './ResourceBudgetCard';
import { ActionButton, Badge, CopyValue, ErrorState, KeyValueList, SectionCard } from './states';

export interface SpecStudioProps {
  kind: 'generation' | 'recipe' | 'train' | 'diagnose';
  fields: FieldSpec[];
  initialSpec: FormValue;
  /** registry kind；提供时会读取 `GET /registry/{kind}` 并用 `param_schema` 追加字段。 */
  registryKind?: string;
  registryPrefix?: string;
  registryInclude?: string[];
  /** 预览阶段（POST /previews 的 stage）。 */
  previewStage?: string;
  /** 提交阶段（POST /jobs 的 stage）。 */
  jobStage?: string;
  plannedJobs?: number;
  inputRefs?: string[];
  requiresGpu?: boolean | null;
  /** 页面特有的附加面板（视口、资产选择等），渲染在表单之后。 */
  children?: ReactNode;
  /** 提交/被受理后回调（页面可以切到任务页或选中 run）。 */
  onAccepted?: (response: JobAcceptedResponse, mode: 'preview' | 'job') => void;
  /** 额外禁用提交的原因（例如缺少输入资产）。 */
  submitBlockReason?: string | null;
  submitLabel?: string;
  /**
   * 受控模式：页面自己持有 spec（例如需要在 children 里编辑 `operators` 这类数组结构）。
   * 同时提供 `value` 与 `onValueChange` 时启用。
   */
  value?: FormValue;
  onValueChange?: (next: FormValue) => void;
  /**
   * 自定义提交：某些页面必须走专用路由而不是 `POST /jobs`
   * （训练用 `POST /training/runs`、诊断用 `POST /diagnostics/runs`）。
   */
  submitOverride?: (spec: FormValue) => Promise<Record<string, unknown>>;
  submitOverrideLabel?: string;
}

interface AsyncState<T> {
  status: 'idle' | 'loading' | 'ready' | 'error';
  data: T | null;
  error: unknown;
}

const IDLE = { status: 'idle', data: null, error: null } as const;

export function SpecStudio({
  kind,
  fields,
  initialSpec,
  registryKind,
  registryPrefix,
  registryInclude,
  previewStage,
  jobStage,
  plannedJobs = 1,
  inputRefs = [],
  requiresGpu = null,
  children,
  onAccepted,
  submitBlockReason,
  submitLabel,
  value: controlledValue,
  onValueChange,
  submitOverride,
  submitOverrideLabel,
}: SpecStudioProps) {
  const [draft, setDraft] = useState<FormValue>(initialSpec);
  const controlled = controlledValue !== undefined && onValueChange !== undefined;
  const spec = controlled ? (controlledValue as FormValue) : draft;
  const setSpec = (next: FormValue) => {
    if (controlled) onValueChange?.(next);
    else setDraft(next);
  };
  const [validation, setValidation] = useState<AsyncState<SpecValidationResponse>>(IDLE);
  const [budget, setBudget] = useState<AsyncState<BudgetReport>>(IDLE);
  const [accepted, setAccepted] = useState<{ response: JobAcceptedResponse; mode: 'preview' | 'job' } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey(jobStage ?? previewStage ?? 'ui'));
  const [busy, setBusy] = useState<'validate' | 'budget' | 'preview' | 'job' | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const registry = useResource(
    (signal) => getRegistry(registryKind as string, {}, signal),
    [registryKind],
    { enabled: Boolean(registryKind) },
  );

  useEffect(() => {
    setValidation(IDLE);
    setBudget(IDLE);
    setAccepted(null);
    setActionError(null);
    setIdempotencyKey(newIdempotencyKey(jobStage ?? previewStage ?? 'ui'));
  }, [jobStage, previewStage]);

  const registryEntry = registry.data?.entries?.[0];
  const registrySchema = registryEntry?.param_schema as JsonSchemaNode | undefined;

  const run = async (which: 'validate' | 'budget' | 'preview' | 'job') => {
    setBusy(which);
    setActionError(null);
    try {
      if (which === 'validate') {
        const response = await validateSpec({ spec, kind });
        setValidation({ status: 'ready', data: response, error: null });
      } else if (which === 'budget') {
        const response = await postBudgets({ spec, kind, stage: jobStage ?? previewStage ?? 'generate', planned_jobs: plannedJobs, requires_gpu: requiresGpu });
        setBudget({ status: 'ready', data: response, error: null });
      } else if (which === 'preview' && previewStage) {
        const response = await postPreviews({
          stage: previewStage,
          spec,
          input_refs: inputRefs,
          idempotency_key: `${idempotencyKey}:preview`,
          budget_ref: budget.data?.budget_ref ?? null,
        });
        setAccepted({ response, mode: 'preview' });
        onAccepted?.(response, 'preview');
      } else if (which === 'job' && jobStage) {
        if (submitOverride) {
          const raw = await submitOverride(spec);
          const response = raw as unknown as JobAcceptedResponse;
          setAccepted({ response, mode: 'job' });
          onAccepted?.(response, 'job');
        } else {
          const response = await postJobs({
            schema_version: kind === 'train' ? 'synlab.train.v1' : kind === 'diagnose' ? 'synlab.diagnose.v1' : 'synlab.v3',
            stage: jobStage,
            spec,
            input_refs: inputRefs,
            idempotency_key: idempotencyKey,
            planned_jobs: plannedJobs,
            budget_ref: budget.data?.budget_ref ?? null,
          });
          setAccepted({ response, mode: 'job' });
          onAccepted?.(response, 'job');
        }
      }
    } catch (caught) {
      setActionError(caught);
      if (which === 'validate') setValidation({ status: 'error', data: null, error: caught });
      if (which === 'budget') setBudget({ status: 'error', data: null, error: caught });
    } finally {
      setBusy(null);
    }
  };

  const specErrors = validation.data?.errors ?? [];
  const validationOk = validation.data?.ok ?? null;

  const previewDisabledReason = useMemo(() => {
    if (!previewStage) return '本页不提供预览阶段';
    if (busy) return '正在执行上一个请求';
    if (validationOk === false) return `spec 未通过校验（${specErrors.length} 个错误），先修正再预览`;
    return null;
  }, [previewStage, busy, validationOk, specErrors.length]);

  const jobDisabledReason = useMemo(() => {
    if (!jobStage) return '本页不提供任务提交';
    if (busy) return '正在执行上一个请求';
    if (submitBlockReason) return submitBlockReason;
    if (validationOk === false) return `spec 未通过校验（${specErrors.length} 个错误）`;
    return null;
  }, [jobStage, busy, submitBlockReason, validationOk, specErrors.length]);

  return (
    <>
      <SectionCard
        title="参数草稿"
        subtitle={
          <>
            <code className="mono">POST /specs/validate</code> · <code className="mono">POST /budgets</code> ·{' '}
            <code className="mono">POST /previews</code> · <code className="mono">POST /jobs</code>
            {registryKind ? (
              <>
                {' '}
                · registry：<code className="mono">/registry/{registryKind}</code>
              </>
            ) : null}
          </>
        }
        actions={
          <div className="row">
            <ActionButton onClick={() => void run('validate')} busy={busy === 'validate'}>
              校验 spec
            </ActionButton>
            <ActionButton onClick={() => void run('budget')} busy={busy === 'budget'}>
              估算资源
            </ActionButton>
            <ActionButton
              tone="primary"
              onClick={() => void run('preview')}
              busy={busy === 'preview'}
              disabledReason={previewDisabledReason}
            >
              请求真实预览
            </ActionButton>
            <ActionButton
              tone="primary"
              onClick={() => void run('job')}
              busy={busy === 'job'}
              disabledReason={jobDisabledReason}
            >
              {submitLabel ?? '提交任务（冻结 spec）'}
            </ActionButton>
          </div>
        }
      >
        <p className="muted small">
          滑块/输入只改本地草稿；松手后需要点击上面的按钮才会发出真实请求。未运行前一律标“未计算”，
          旧预览在新草稿下会提示“参数已变化”。
        </p>

        <div className="studio">
          <div className="studio__form">
            <SchemaForm
              fields={fields}
              jsonSchema={registrySchema}
              schemaPrefix={registryPrefix}
              schemaInclude={registryInclude}
              value={spec}
              onChange={setSpec}
              issues={specErrors}
              disabled={busy !== null}
            />
            {registryKind && registry.status === 'ready' && !registrySchema ? (
              <div className="warning" role="status">
                <code className="mono">/registry/{registryKind}</code> 返回 {registry.data?.count ?? 0} 条目
                {registry.data?.empty_kinds?.length ? `（empty_kinds=${registry.data.empty_kinds.join(', ')}）` : ''}
                ：后端还没有注册该 kind 的参数模型，因此本页只能用显式字段构造 spec。
                {registry.data?.note ? <div className="muted small">{registry.data.note}</div> : null}
              </div>
            ) : null}
            {registryKind && registry.status === 'error' ? (
              <ErrorState error={registry.error} onRetry={registry.reload} compact title="registry 读取失败" />
            ) : null}
          </div>

          <aside className="studio__side">
            <h3>校验结果</h3>
            {validation.status === 'idle' ? (
              <p className="muted">尚未校验。点击“校验 spec”。</p>
            ) : validation.status === 'loading' ? (
              <p className="muted">校验中…</p>
            ) : validation.data ? (
              <>
                <p>
                  <Badge tone={validation.data.ok ? 'ok' : 'bad'}>
                    {validation.data.ok ? 'spec 通过' : `spec 被拒绝（${validation.data.errors.length} 个错误）`}
                  </Badge>
                  <Badge tone="neutral">{validation.data.schema_id}</Badge>
                </p>
                {validation.data.spec_hash ? (
                  <p className="mono small">
                    spec_hash=<CopyValue value={validation.data.spec_hash} label="spec_hash" />
                  </p>
                ) : null}
                {validation.data.errors.length > 0 ? (
                  <ul className="problems">
                    {validation.data.errors.map((issue, index) => (
                      <li key={index} className="mono small">
                        {issue.loc.join('.') || '（顶层）'} · {issue.type} · {issue.msg}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {validation.data.warnings.length > 0 ? (
                  <details>
                    <summary>后端 warnings（{validation.data.warnings.length}）</summary>
                    <ul className="problems">
                      {validation.data.warnings.map((warning) => (
                        <li key={warning} className="small">
                          {warning}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                {Object.keys(validation.data.expanded ?? {}).length > 0 ? (
                  <details>
                    <summary>编译器展开结果（expanded）</summary>
                    <pre className="mono pre">{pretty(validation.data.expanded)}</pre>
                  </details>
                ) : null}
                <p className="muted small">{validation.data.note}</p>
              </>
            ) : null}

            {validation.status === 'error' ? (
              <ErrorState error={validation.error} compact onRetry={() => void run('validate')} />
            ) : null}

            <h3>幂等键</h3>
            <p className="mono small">
              <CopyValue value={idempotencyKey} label="幂等键" />
            </p>
            <button
              type="button"
              className="btn btn--tiny"
              onClick={() => setIdempotencyKey(newIdempotencyKey(jobStage ?? previewStage ?? 'ui'))}
            >
              重新生成幂等键
            </button>
            <p className="muted small">
              相同幂等键 + 相同 payload 返回原任务（idempotent_replay=true）；同键不同 payload 后端返回 409。
            </p>
          </aside>
        </div>

        {actionError ? <ErrorState error={actionError} title="请求被后端拒绝" /> : null}

        {accepted ? (
          <div className="accepted" role="status">
            <h3>
              {accepted.mode === 'preview' ? '预览任务已受理' : '任务已受理'}
              <Badge tone={accepted.response.idempotent_replay ? 'info' : 'ok'}>
                {accepted.response.idempotent_replay ? '幂等重放（未新建）' : '新建'}
              </Badge>
            </h3>
            {accepted.response.run_id && accepted.response.job_id ? (
              <KeyValueList
                rows={[
                  { label: 'run_id', value: <CopyValue value={accepted.response.run_id} label="run_id" /> },
                  { label: 'job_id', value: <CopyValue value={accepted.response.job_id} label="job_id" /> },
                  { label: 'status', value: accepted.response.status ?? '未提供' },
                  { label: 'spec_hash', value: <span className="mono">{accepted.response.spec_hash ?? '未提供'}</span> },
                  { label: 'events_url', value: <span className="mono">{accepted.response.events_url ?? '未提供'}</span> },
                  { label: 'job_ids', value: (accepted.response.job_ids ?? []).join(', ') || '单个 job' },
                ]}
              />
            ) : (
              <p className="muted small">
                该路由返回的不是通用 job 信封（例如 <code className="mono">POST /training/runs</code> /
                <code className="mono">POST /diagnostics/runs</code>），下面原样展示后端响应。
              </p>
            )}
            {accepted.response.dag && accepted.response.dag.length > 0 ? (
              <details open>
                <summary>真实 DAG（{accepted.response.dag.length} 个节点）</summary>
                <table className="table table--tight">
                  <thead>
                    <tr>
                      <th scope="col">node</th>
                      <th scope="col">stage</th>
                      <th scope="col">job_id</th>
                      <th scope="col">depends_on</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accepted.response.dag.map((node) => (
                      <tr key={node.node_id}>
                        <th scope="row" className="mono">
                          {node.node_id}
                        </th>
                        <td className="mono">{node.stage}</td>
                        <td className="mono">{node.job_id}</td>
                        <td className="mono small">{node.depends_on.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ) : null}
            <p className="muted small">{accepted.response.note}</p>
            {accepted.response.preview_note ? <p className="muted small">{accepted.response.preview_note}</p> : null}
            {submitOverrideLabel ? (
              <details open>
                <summary>后端原始响应（{submitOverrideLabel}）</summary>
                <pre className="mono pre">{pretty(accepted.response)}</pre>
              </details>
            ) : null}
          </div>
        ) : null}

        {children}
      </SectionCard>

      <ResourceBudgetCard
        budget={budget.data}
        emptyReason="点击上方“估算资源”调用真实的 POST /budgets；后端不可行时会返回 409 BUDGET_EXCEEDED。"
      />
      {budget.status === 'error' ? <ErrorState error={budget.error} title="预算估算被拒绝" /> : null}
    </>
  );
}
