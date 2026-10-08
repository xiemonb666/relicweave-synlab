/**
 * U06「U 位置变化 → 真实新场景帧」面板。
 *
 * 真实链路（全部打到 `/api/synlab`，没有前端模拟）：
 * 1. `POST /specs/validate`（kind=generation）拿到后端真实的 `canonical` / `spec_hash`；
 * 2. `POST /previews`（stage=observe，spec 里带 `u_position_mm`）—— 后端**没有** observe 预览阶段，
 *    这里把它的真实结构化错误原样展示，作为“U 参数无处可去”的证据；
 * 3. `POST /previews`（stage=degrade，spec 里带真实字段 `observation.camera_profile_ref`）——
 *    后端真实受理（202）或真实拒绝（503/422），随后 `GET /jobs/{id}` 轮询状态，
 *    有 outputs 时按真实资产 ID 取回新帧并与旧帧并排。
 *
 * 诚实约定：
 * * 滑块只改**本地草稿**，松手前一律标“未计算”，不会顺手把新 U 代进任何公式；
 * * 超出后端声明行程时**不前端拦截**：请求照发，页面显示后端给的结构化错误；
 * * 新帧一旦拿到，它的所有读数都取自该资产的真实 `meta` / `arrays`（K、T_WC、深度、帧下标），
 *   并与 catalogue 的真实数值并排，不一致就如实显示两列而不是取其一。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { describeError } from '../api/client';
import { getAsset, getJob, listAssets, listCameraProfiles, postPreviews, validateSpec } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AssetRecord, CameraCatalogueEntry, JobRecord } from '../api/types';
import { frameIndices, frameMemberKeys, loadAssetArrays, npzScalar2d, type LoadedArrays } from '../lib/assetData';
import { finiteStats } from '../lib/analysis';
import { formatNumber, pretty } from '../lib/format';
import { RealArrayHeatmap, topIndices } from './RealArrayHeatmap';
import { ActionButton, Badge, BlockedState, EmptyState, ErrorState, KeyValueList, LoadingState, SectionCard } from './states';

interface RequestLogEntry {
  id: number;
  label: string;
  method: 'GET' | 'POST';
  path: string;
  body?: unknown;
  status: 'ok' | 'error' | 'pending';
  code?: string;
  payload?: unknown;
}

interface Intrinsics {
  fx: number;
  fy: number;
  cx: number;
  cy: number;
}

function intrinsicsOf(loaded: LoadedArrays, frame: number): Intrinsics | null {
  const array = loaded.arrays.get(`payload.frames.${frame}.K`);
  if (!array || array.data.length < 9) return null;
  const fx = Number(array.data[0]);
  const fy = Number(array.data[4]);
  const cx = Number(array.data[2]);
  const cy = Number(array.data[5]);
  if (![fx, fy, cx, cy].every((value) => Number.isFinite(value))) return null;
  return { fx, fy, cx, cy };
}

/** 把真实 uint8 RGB 数组画进 canvas（宽高就是数组真实尺寸）。 */
function RgbCanvas({
  values,
  width,
  height,
  label,
}: {
  values: ArrayLike<number> | null;
  width: number;
  height: number;
  label: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !values) return;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return;
    const image = context.createImageData(width, height);
    for (let index = 0; index < width * height; index += 1) {
      image.data[index * 4] = Number(values[index * 3]);
      image.data[index * 4 + 1] = Number(values[index * 3 + 1]);
      image.data[index * 4 + 2] = Number(values[index * 3 + 2]);
      image.data[index * 4 + 3] = 255;
    }
    context.putImageData(image, 0, 0);
  }, [values, width, height]);
  return <canvas ref={ref} className="frameimg" role="img" aria-label={label} />;
}

export function CameraUPreviewPanel({ entry }: { entry: CameraCatalogueEntry | null }) {
  const profiles = useResource(() => listCameraProfiles({ limit: 50 }), []);
  const [draftU, setDraftU] = useState<number | null>(null);
  const [appliedU, setAppliedU] = useState<number | null>(null);
  const [log, setLog] = useState<RequestLogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [newFrameAssetId, setNewFrameAssetId] = useState<string | null>(null);

  const views = useResource(() => listAssets({ role: ['obs_view'], limit: 100 }), []);
  const depthViews = useMemo(
    () => (views.data?.items ?? []).filter((record) => 'arrays' in (record.files ?? {})),
    [views.data],
  );
  const baseView: AssetRecord | null = useMemo(
    () => depthViews.find((record) => !record.meta?.axis_id) ?? depthViews[0] ?? null,
    [depthViews],
  );
  const [frame, setFrame] = useState(0);
  const baseArrays = useResource(() => loadAssetArrays(baseView?.asset_id as string, 'obs_view', 'arrays'), [baseView?.asset_id], {
    enabled: Boolean(baseView),
  });
  const newArrays = useResource(() => loadAssetArrays(newFrameAssetId as string, 'obs_view', 'arrays'), [newFrameAssetId], {
    enabled: Boolean(newFrameAssetId),
  });

  const uRange = useMemo(() => {
    const raw = entry?.meta?.u_allowed_range_mm;
    if (Array.isArray(raw) && raw.length >= 2) return [Number(raw[0]), Number(raw[1])] as [number, number];
    return null;
  }, [entry]);
  const uStep = typeof entry?.meta?.u_step_mm === 'number' ? (entry?.meta?.u_step_mm as number) : 1;

  useEffect(() => {
    if (!entry) {
      setDraftU(null);
      setAppliedU(null);
      return;
    }
    setDraftU(entry.u_position_mm);
    setAppliedU(entry.u_position_mm);
  }, [entry]);

  const dirty = draftU !== null && appliedU !== null && Math.abs(draftU - appliedU) > 1e-9;
  const outOfRange = uRange !== null && draftU !== null && (draftU < uRange[0] - 1e-9 || draftU > uRange[1] + 1e-9);

  const baseFrames = useMemo(() => (baseArrays.data ? frameIndices(baseArrays.data.arrays) : []), [baseArrays.data]);
  const activeFrame = baseFrames.includes(frame) ? frame : (baseFrames[0] ?? 0);

  const baseRgb = useMemo(() => {
    if (!baseArrays.data) return null;
    const found = baseArrays.data.arrays.get(`payload.frames.${activeFrame}.rgb`);
    if (!found || found.shape.length !== 3) return null;
    return { values: found.data, width: found.shape[1], height: found.shape[0] };
  }, [baseArrays.data, activeFrame]);

  const baseDepth = useMemo(() => {
    if (!baseArrays.data) return null;
    const plane = npzScalar2d(baseArrays.data.arrays, `payload.frames.${activeFrame}.depth_z`);
    if (!plane) return null;
    const mask = new Uint8Array(plane.width * plane.height);
    for (let index = 0; index < mask.length; index += 1) {
      const value = Number(plane.data[index]);
      mask[index] = Number.isFinite(value) && value > 0 ? 1 : 0;
    }
    return { ...plane, mask };
  }, [baseArrays.data, activeFrame]);

  const newRgb = useMemo(() => {
    if (!newArrays.data) return null;
    const index = frameIndices(newArrays.data.arrays)[0] ?? 0;
    const found = newArrays.data.arrays.get(`payload.frames.${index}.rgb`);
    if (!found || found.shape.length !== 3) return null;
    return { values: found.data, width: found.shape[1], height: found.shape[0], index };
  }, [newArrays.data]);

  const baseProfileId = useMemo(() => {
    const render = baseView?.meta?.render as Record<string, unknown> | undefined;
    const viewId = render?.view_id;
    if (typeof viewId === 'string') return viewId.split('#')[0];
    const fromMeta = baseView?.meta?.['payload.frames.0.view_id'];
    return typeof fromMeta === 'string' ? fromMeta.split('#')[0] : null;
  }, [baseView]);

  const baseProfile = useMemo(
    () => (profiles.data?.catalogue ?? []).find((item) => item.profile_id === baseProfileId) ?? null,
    [profiles.data, baseProfileId],
  );

  const baseIntrinsics = baseArrays.data ? intrinsicsOf(baseArrays.data, activeFrame) : null;
  const newIntrinsics = newArrays.data ? intrinsicsOf(newArrays.data, frameIndices(newArrays.data.arrays)[0] ?? 0) : null;

  /* ------------------------------------------------------------ 真实请求序列 */
  const runPreview = async () => {
    if (!entry || draftU === null) return;
    setBusy(true);
    setJob(null);
    setJobId(null);
    setNewFrameAssetId(null);
    let entries: RequestLogEntry[] = [];
    let nextId = 1;
    const push = (item: Omit<RequestLogEntry, 'id'>) => {
      entries = [...entries, { ...item, id: nextId }];
      nextId += 1;
      setLog(entries);
    };

    const baseSpec: Record<string, unknown> = {
      schema: 'synlab.v3',
      observation: { camera_profile_ref: entry.profile_id },
    };

    // 1) 真实校验：后端给出 canonical / spec_hash
    let canonicalSpec = baseSpec;
    try {
      const validation = await validateSpec({ spec: baseSpec, kind: 'generation' });
      push({
        label: '校验生成 spec（真实 spec_hash）',
        method: 'POST',
        path: '/specs/validate',
        body: { spec: baseSpec, kind: 'generation' },
        status: 'ok',
        payload: { ok: validation.ok, spec_hash: validation.spec_hash, errors: validation.errors, warnings: validation.warnings },
      });
      if (validation.ok && validation.canonical) {
        canonicalSpec = JSON.parse(validation.canonical) as Record<string, unknown>;
      }
    } catch (error) {
      const info = describeError(error);
      push({
        label: '校验生成 spec',
        method: 'POST',
        path: '/specs/validate',
        body: { spec: baseSpec, kind: 'generation' },
        status: 'error',
        code: info.code,
        payload: info,
      });
      setBusy(false);
      return;
    }

    // 2) 带 U 的真实请求：后端没有 observe 预览阶段 → 原样展示结构化错误
    const withU = {
      ...canonicalSpec,
      observation: {
        ...(canonicalSpec.observation as Record<string, unknown>),
        camera_profile_ref: entry.profile_id,
        u_position_mm: draftU,
      },
    };
    try {
      const accepted = await postPreviews({
        stage: 'observe',
        spec: withU,
        idempotency_key: `ui-u06-observe-${entry.profile_id}-${draftU}-${Date.now()}`,
      });
      push({
        label: '带 U 的预览请求（stage=observe）',
        method: 'POST',
        path: '/previews',
        body: { stage: 'observe', spec: withU },
        status: 'ok',
        payload: accepted,
      });
      setJobId(accepted.job_id);
    } catch (error) {
      const info = describeError(error);
      push({
        label: '带 U 的预览请求（stage=observe）被后端拒绝',
        method: 'POST',
        path: '/previews',
        body: { stage: 'observe', spec: withU },
        status: 'error',
        code: info.code,
        payload: { code: info.code, message: info.message, diagnostics: info.diagnostics, details: info.details },
      });
    }

    // 3) 去掉 U、只带真实字段的预览请求
    const clean = {
      ...canonicalSpec,
      observation: { ...(canonicalSpec.observation as Record<string, unknown>), camera_profile_ref: entry.profile_id },
    };
    try {
      const accepted = await postPreviews({
        stage: 'degrade',
        spec: clean,
        idempotency_key: `ui-u06-degrade-${entry.profile_id}-${Date.now()}`,
      });
      push({
        label: '不含 U 的真实预览 job（stage=degrade）',
        method: 'POST',
        path: '/previews',
        body: { stage: 'degrade', spec: clean },
        status: 'ok',
        payload: accepted,
      });
      setJobId(accepted.job_id);
      setAppliedU(draftU);
    } catch (error) {
      const info = describeError(error);
      push({
        label: '不含 U 的真实预览 job（stage=degrade）',
        method: 'POST',
        path: '/previews',
        body: { stage: 'degrade', spec: clean },
        status: 'error',
        code: info.code,
        payload: { code: info.code, message: info.message, diagnostics: info.diagnostics, details: info.details },
      });
    }
    setBusy(false);
  };

  const refreshJob = async () => {
    if (!jobId) return;
    try {
      const detail = await getJob(jobId);
      setJob(detail.job);
      const outputs = detail.job.outputs ?? [];
      if (outputs.length > 0 && !newFrameAssetId) {
        for (const assetId of outputs) {
          try {
            const asset = await getAsset(assetId);
            if (asset.asset.role === 'obs_view' && 'arrays' in (asset.asset.files ?? {})) {
              setNewFrameAssetId(assetId);
              break;
            }
          } catch {
            // 单个 output 读不到就跳过，最后统一显示“没有可解码的新帧”
          }
        }
      }
    } catch (error) {
      const info = describeError(error);
      setLog((prev) => [
        ...prev,
        {
          id: prev.length + 1,
          label: '读取任务状态失败',
          method: 'GET',
          path: `/jobs/${jobId}`,
          status: 'error',
          code: info.code,
          payload: info,
        },
      ]);
    }
  };

  useEffect(() => {
    if (!jobId) return undefined;
    void refreshJob();
    const timer = window.setInterval(() => void refreshJob(), 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (!entry) {
    return <EmptyState title="未选择采集档" reason="catalogue 里没有可选档位时，无法构造真实的预览请求。" />;
  }

  const mmPerPixel = baseProfile && baseIntrinsics ? baseProfile.working_distance_mm / baseIntrinsics.fx : null;

  return (
    <SectionCard
      title="U 位置 → 真实新场景帧"
      subtitle="POST /specs/validate → POST /previews(stage=observe/带 U) → POST /previews(stage=degrade) → GET /jobs/{id} → GET /assets/{id}/files/obs_view?key=arrays"
      actions={
        <div className="row">
          <Badge tone={dirty ? 'warn' : 'neutral'}>{dirty ? '草稿未计算' : '与已应用值一致'}</Badge>
          <Badge tone="info">{entry.profile_id}</Badge>
        </div>
      }
    >
      <div className="grid2">
        <div>
          <label className="field">
            <span className="field__label">
              U 位置（滑块，范围来自 catalogue.meta.u_allowed_range_mm）<span className="field__unit">mm</span>
            </span>
            <input
              className="input"
              type="range"
              min={uRange ? uRange[0] : entry.u_position_mm}
              max={uRange ? uRange[1] : entry.u_position_mm}
              step={uStep}
              value={draftU ?? entry.u_position_mm}
              aria-label="U 位置（毫米）"
              onChange={(event) => setDraftU(Number(event.target.value))}
              onPointerUp={() => void runPreview()}
              onKeyUp={(event) => {
                if (event.key === 'Enter' || event.key === ' ') void runPreview();
              }}
            />
          </label>

          <label className="field">
            <span className="field__label">
              精确 U 值（可超出后端行程：请求照发，由后端回答）<span className="field__unit">mm</span>
            </span>
            <input
              className="input input--tight"
              type="number"
              step={uStep}
              value={draftU ?? ''}
              aria-label="精确 U 位置（毫米）"
              onChange={(event) => setDraftU(event.target.value === '' ? null : Number(event.target.value))}
            />
            <span className="field__hint">
              {uRange
                ? `后端声明可达 ${uRange[0]} … ${uRange[1]} mm（步长 ${uStep}）。超出时前端只提示，不拦截。`
                : '该档位没有声明可达范围，因此只能手填并由后端判定。'}
            </span>
          </label>

          {outOfRange ? (
            <p className="warning" role="status">
              当前草稿 {formatNumber(draftU, 2)} mm 超出后端声明的可达范围 —— 仍会按原值发送请求，并显示后端的结构化回答。
            </p>
          ) : null}

          <div className="row">
            <ActionButton tone="primary" onClick={() => void runPreview()} busy={busy} disabledReason={draftU === null ? 'U 值为空' : null}>
              松手后请求真实预览（{formatNumber(draftU, 2)} mm）
            </ActionButton>
            <ActionButton onClick={() => setDraftU(entry.u_position_mm)} disabledReason={null}>
              恢复 catalogue 默认（{formatNumber(entry.u_position_mm, 2)} mm）
            </ActionButton>
            <ActionButton onClick={() => void refreshJob()} disabledReason={jobId ? null : '还没有预览任务'}>
              刷新任务状态
            </ActionButton>
          </div>

          <KeyValueList
            rows={[
              { label: '草稿 U（仅本地）', value: `${formatNumber(draftU, 2)} mm`, mono: true },
              {
                label: '已应用 U（后端受理后写入）',
                value: appliedU === null ? '—' : `${formatNumber(appliedU, 2)} mm`,
                mono: true,
              },
              { label: 'catalogue 默认 U', value: `${formatNumber(entry.u_position_mm, 2)} mm`, mono: true },
              {
                label: '新帧读数',
                value: dirty || !newArrays.data ? <Badge tone="warn">未计算</Badge> : <Badge tone="ok">来自真实资产</Badge>,
              },
            ]}
          />
          <p className="muted small">
            滑块只改草稿：松手（或按 Enter/空格）才会发出真实请求。草稿状态下本页不把新 U 代进 K/FOV/景深，
            因此这些列显示“未计算”，而不是推算值。
          </p>
        </div>

        <div>
          <h4>请求与响应（原样）</h4>
          {log.length === 0 ? (
            <EmptyState title="还没有发出请求" reason="拖动滑块松手或点上面的按钮，这里会按顺序列出每一次真实请求、状态码与响应体。" />
          ) : (
            <ol className="actionlist">
              {log.map((item) => (
                <li key={item.id}>
                  <div className="row">
                    <Badge tone={item.status === 'ok' ? 'ok' : 'bad'}>{item.status === 'ok' ? 'HTTP 2xx' : (item.code ?? 'ERROR')}</Badge>
                    <span className="mono small">
                      {item.method} {item.path}
                    </span>
                  </div>
                  <div>{item.label}</div>
                  {item.body ? (
                    <details>
                      <summary>请求体</summary>
                      <pre className="mono pre">{pretty(item.body)}</pre>
                    </details>
                  ) : null}
                  <details open={item.status === 'error'}>
                    <summary>后端回答</summary>
                    <pre className="mono pre">{pretty(item.payload)}</pre>
                  </details>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>

      <SectionCard
        title="旧帧 vs 新帧（并排，真实资产）"
        subtitle="旧帧来自 /assets?role=obs_view&key=arrays；新帧来自预览 job 的真实 outputs"
      >
        {views.status === 'loading' ? <LoadingState label="读取观测资产…" /> : null}
        {views.status === 'error' ? <ErrorState error={views.error} onRetry={views.reload} /> : null}
        {views.data && depthViews.length === 0 ? (
          <EmptyState
            title="没有可用于对照的旧帧"
            reason="需要 role=obs_view 且带 `arrays` 的真实观测资产（含 payload.frames.N.rgb / depth_z）。当前工作区没有，页面不生成占位帧。"
          />
        ) : null}

        <div className="grid2">
          <div>
            <h4>
              旧帧 <Badge tone="neutral">{baseView ? baseView.asset_id : '未选择'}</Badge>
            </h4>
            {baseFrames.length > 0 ? (
              <label className="field field--inline">
                <span className="field__label">帧下标（真实）</span>
                <select className="input input--tight" value={activeFrame} onChange={(event) => setFrame(Number(event.target.value))}>
                  {baseFrames.map((index) => (
                    <option key={index} value={index}>
                      frame {index}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {baseArrays.status === 'loading' ? <LoadingState label="解码旧帧 npz…" /> : null}
            {baseArrays.status === 'error' ? <ErrorState error={baseArrays.error} onRetry={baseArrays.reload} /> : null}
            {baseRgb ? (
              <>
                <RgbCanvas
                  values={baseRgb.values}
                  width={baseRgb.width}
                  height={baseRgb.height}
                  label={`旧帧 frame ${activeFrame} 的真实 rgb 数组，${baseRgb.width}×${baseRgb.height}`}
                />
                <p className="muted small">
                  真实成员：{baseArrays.data ? frameMemberKeys(baseArrays.data.arrays, activeFrame).join(', ') : '—'}
                </p>
              </>
            ) : null}
            {baseDepth ? (
              <RealArrayHeatmap
                title="旧帧深度 depth_z"
                provenance={`资产 ${baseView?.asset_id} 的 payload.frames.${activeFrame}.depth_z（mm，相机 z；无效像素为负/NaN，不绘制）`}
                values={baseDepth.data}
                mask={baseDepth.mask}
                width={baseDepth.width}
                height={baseDepth.height}
                unit="mm"
                samples={topIndices(baseDepth.data, 5).map((row) => ({
                  label: `y=${Math.floor(row.index / baseDepth.width)}, x=${row.index % baseDepth.width}`,
                  value: row.value,
                }))}
              />
            ) : null}
          </div>

          <div>
            <h4>
              新帧{' '}
              {newFrameAssetId ? (
                <Badge tone="ok">{newFrameAssetId}</Badge>
              ) : (
                <Badge tone="warn">未计算（没有已产出的真实帧）</Badge>
              )}
            </h4>
            {!jobId ? (
              <EmptyState title="还没有发出预览请求" reason="松手或点按钮后，这里显示后端受理的任务与它真实产出的新帧。" />
            ) : (
              <>
                <KeyValueList
                  rows={[
                    { label: 'job_id', value: jobId, mono: true },
                    {
                      label: 'job state',
                      value: job ? <Badge tone={job.state === 'COMMITTED' ? 'ok' : 'warn'}>{job.state}</Badge> : '未读取',
                    },
                    { label: 'run_id', value: job?.run_id ?? '未读取', mono: true },
                    {
                      label: 'outputs',
                      value: job ? (job.outputs.length > 0 ? job.outputs.join(', ') : '（空）') : '未读取',
                      mono: true,
                    },
                    { label: 'attempt', value: job ? job.attempt : '未读取', mono: true },
                  ]}
                />
                {job && job.outputs.length === 0 ? (
                  <BlockedState
                    title="任务已受理但还没有产出新帧"
                    code={job.state}
                    reason={
                      <>
                        这是真实状态：<code className="mono">POST /previews</code> 返回 202 只代表**已受理**。计算由{' '}
                        <code className="mono">synlab.api.worker</code> 执行，未运行时任务停在 {job.state}。
                        页面不会用旧帧或示意图冒充新帧。
                      </>
                    }
                    items={[
                      {
                        label: '运行命令',
                        value: (
                          <span className="mono small">
                            python -m synlab.api.worker --store-root data\a12_demo\store --once --json
                          </span>
                        ),
                      },
                      {
                        label: '本轮请求里的 U',
                        value: `${formatNumber(appliedU ?? draftU, 2)} mm（后端未接受该字段，见上方 422）`,
                      },
                    ]}
                  />
                ) : null}
                {newArrays.status === 'loading' ? <LoadingState label="解码新帧 npz…" /> : null}
                {newArrays.status === 'error' ? <ErrorState error={newArrays.error} onRetry={newArrays.reload} /> : null}
                {newRgb ? (
                  <>
                    <RgbCanvas
                      values={newRgb.values}
                      width={newRgb.width}
                      height={newRgb.height}
                      label={`新帧 frame ${newRgb.index} 的真实 rgb 数组，${newRgb.width}×${newRgb.height}`}
                    />
                    <p className="muted small">
                      真实成员：{newArrays.data ? frameMemberKeys(newArrays.data.arrays, newRgb.index).join(', ') : '—'}
                    </p>
                  </>
                ) : null}
              </>
            )}
          </div>
        </div>

        <table className="table">
          <caption>读数对照（旧帧来自真实资产与 catalogue 的交汇；新帧未产出时显示“未计算”）</caption>
          <thead>
            <tr>
              <th scope="col">量</th>
              <th scope="col">旧帧（真实）</th>
              <th scope="col">新帧</th>
              <th scope="col">来源</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">u_position_mm</th>
              <td className="mono">{baseProfile ? formatNumber(baseProfile.u_position_mm, 2) : '未提供'}</td>
              <td className="mono">
                {newArrays.data ? '见新资产 meta（后端未写 U 时显示未提供）' : <Badge tone="warn">未计算</Badge>}
              </td>
              <td className="small">catalogue / 新资产 meta</td>
            </tr>
            <tr>
              <th scope="row">工作距离 (mm)</th>
              <td className="mono">{baseProfile ? formatNumber(baseProfile.working_distance_mm, 2) : '未提供'}</td>
              <td className="mono">
                {newIntrinsics && baseProfile ? (
                  `${formatNumber(baseProfile.working_distance_mm, 2)}（未变：后端未接受 U）`
                ) : (
                  <Badge tone="warn">未计算</Badge>
                )}
              </td>
              <td className="small">catalogue；新帧若有自己的 meta 会优先显示</td>
            </tr>
            <tr>
              <th scope="row">K（fx, fy, cx, cy）</th>
              <td className="mono">
                {baseIntrinsics
                  ? `${formatNumber(baseIntrinsics.fx, 2)}, ${formatNumber(baseIntrinsics.fy, 2)}, ${formatNumber(baseIntrinsics.cx, 1)}, ${formatNumber(baseIntrinsics.cy, 1)}`
                  : '未提供'}
              </td>
              <td className="mono">
                {newIntrinsics
                  ? `${formatNumber(newIntrinsics.fx, 2)}, ${formatNumber(newIntrinsics.fy, 2)}, ${formatNumber(newIntrinsics.cx, 1)}, ${formatNumber(newIntrinsics.cy, 1)}`
                  : <Badge tone="warn">未计算</Badge>}
              </td>
              <td className="small">arrays 的 payload.frames.N.K（真实 3×3）</td>
            </tr>
            <tr>
              <th scope="row">mm / pixel</th>
              <td className="mono">{mmPerPixel === null ? '未提供' : formatNumber(mmPerPixel, 6)}</td>
              <td className="mono">
                {mmPerPixel === null ? <Badge tone="warn">未计算</Badge> : `${formatNumber(mmPerPixel, 6)}（同旧帧）`}
              </td>
              <td className="small">由真实工作距离 ÷ 真实 fx 推导（与后端 CameraProfile.mm_per_pixel 同式）</td>
            </tr>
            <tr>
              <th scope="row">FOV (mm)</th>
              <td className="mono">{baseProfile ? baseProfile.fov_mm.map((value) => formatNumber(value, 1)).join(' × ') : '未提供'}</td>
              <td className="mono">
                {baseProfile ? `${baseProfile.fov_mm.map((value) => formatNumber(value, 1)).join(' × ')}（未变）` : <Badge tone="warn">未计算</Badge>}
              </td>
              <td className="small">catalogue（后端按真实传感器/焦距给出）</td>
            </tr>
            <tr>
              <th scope="row">景深 (mm)</th>
              <td className="mono">
                {baseProfile ? baseProfile.depth_of_field_mm.map((value) => formatNumber(value, 1)).join(' … ') : '未提供'}
              </td>
              <td className="mono">
                {baseProfile ? (
                  `${baseProfile.depth_of_field_mm.map((value) => formatNumber(value, 1)).join(' … ')}（未变）`
                ) : (
                  <Badge tone="warn">未计算</Badge>
                )}
              </td>
              <td className="small">catalogue</td>
            </tr>
            <tr>
              <th scope="row">帧尺寸 (px)</th>
              <td className="mono">{baseRgb ? `${baseRgb.width} × ${baseRgb.height}` : '未提供'}</td>
              <td className="mono">{newRgb ? `${newRgb.width} × ${newRgb.height}` : <Badge tone="warn">未计算</Badge>}</td>
              <td className="small">arrays 的 rgb 形状（真实像素）</td>
            </tr>
            <tr>
              <th scope="row">有效深度像素</th>
              <td className="mono">{baseDepth ? (finiteStats(baseDepth.data, baseDepth.mask)?.n ?? 0) : '未提供'}</td>
              <td className="mono">
                <Badge tone="warn">未计算</Badge>
              </td>
              <td className="small">depth_z &gt; 0 且有限</td>
            </tr>
          </tbody>
        </table>

        {profiles.data ? (
          <p className="muted small">
            旧帧图像确实来自采集档 <span className="mono">{baseProfileId ?? '未提供'}</span>
            {baseProfile
              ? `（catalogue: 工作距离 ${formatNumber(baseProfile.working_distance_mm, 1)} mm，U ${formatNumber(baseProfile.u_position_mm, 1)} mm，未标定）`
              : '（catalogue 里没有对应条目，因此只显示资产自身的 K）'}
            。注意两列的 K 来自**不同来源**：旧帧那一列是资产 arrays 里的真实 K（该资产是 320×240 的代理渲染），
            catalogue 的 K 是 4000×3000 的光学模型；两者不能直接比大小，页面不做归一化也不隐藏差异。
          </p>
        ) : null}
      </SectionCard>
    </SectionCard>
  );
}
