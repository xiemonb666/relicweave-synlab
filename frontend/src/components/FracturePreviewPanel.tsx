/**
 * FracturePreviewPanel —— U04「断裂预览」的真实结果面板。
 *
 * 与页面里原有部分的分工：原有部分负责 registry 清单与 spec 提交；本面板负责**看结果**，
 * 并且把 UI 要求的三件事做实：
 *
 * 1. **目标片数 vs 实测片数对照**：目标区间来自当前断裂 spec 的
 *    `fracture.target_piece_range`（真实 schema 字段），实测片数是
 *    `GET /assets?role=fragment_mesh&lineage_id=...` 返回的真实行数（同一 event 谱系）；
 * 2. **碎片 3D（原位 / 爆炸）+ 断面高亮**：由 `FragmentMeshViewport` 直接读权威
 *    `arrays.npz` 的 `mesh.face__origin_kind` / `mesh.face__interface_id`；没有这两个属性时
 *    面板显示「该资产缺断面属性」，不做任何假装着色；
 * 3. **审计数值原样展示**：`qa.parent_qa`、`meta`、`integrity` 直接进表，缺项显示「未提供」。
 *
 * 后端 PENDING/MISSING（例如 `warped_partition`、`fracture_modes`）时显示 registry 的真实 status，
 * 并给出后端的 503/422 结构化错误码与复现命令（`POST /previews` 的真实响应）。
 */

import { useEffect, useMemo, useState } from 'react';

import { getAsset, getRegistry, listAssets, postPreviews } from '../api/endpoints';
import { newIdempotencyKey, useResource } from '../api/hooks';
import type { JobAcceptedResponse } from '../api/types';
import { FailureCard, failureFromError, type FailureInfo } from './AsyncOperation';
import { FragmentMeshViewport, type LoadedFragmentMesh } from './FragmentMeshViewport';
import { MeasuredQualityTable, flattenMetrics, progressRows } from './MeasuredQualityTable';
import {
  ActionButton,
  Badge,
  BlockedState,
  CopyValue,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  SectionCard,
} from './states';
import { pretty } from '../lib/format';

export interface FracturePreviewPanelProps {
  /** 当前断裂 spec 里的目标片数区间；`null` 表示尚未填写。 */
  targetPieceRange: [number, number] | null;
  /** 断裂后端（本面板会核对 registry 的真实 status）。 */
  backend: string;
  /** 当前选中的碎片资产（由页面左侧的 fragment_mesh 浏览器决定）。 */
  fragmentId: string | null;
}

export function FracturePreviewPanel({ targetPieceRange, backend, fragmentId }: FracturePreviewPanelProps) {
  const backends = useResource((signal) => getRegistry('fracture_backend', {}, signal), []);
  const [explodeMm, setExplodeMm] = useState(0);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [mesh, setMesh] = useState<LoadedFragmentMesh | null>(null);
  const [previewAccepted, setPreviewAccepted] = useState<JobAcceptedResponse | null>(null);
  const [previewFailure, setPreviewFailure] = useState<FailureInfo | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);

  const detail = useResource((signal) => getAsset(fragmentId as string, signal), [fragmentId], {
    enabled: Boolean(fragmentId),
  });
  const lineageId = detail.data?.asset.lineage_id ?? null;
  const siblings = useResource(
    (signal) => listAssets({ role: ['fragment_mesh'], lineage_id: lineageId ?? undefined, limit: 200 }, signal),
    [lineageId],
    { enabled: Boolean(lineageId) },
  );

  // 换碎片时重置展示状态（爆炸/高亮是纯展示，不跨资产沿用）。
  useEffect(() => {
    setExplodeMm(0);
    setHighlight(null);
    setMesh(null);
  }, [fragmentId]);

  const backendStatus = useMemo(() => {
    const entry = (backends.data?.entries ?? []).find((item) => item.id === backend) ?? null;
    if (!entry) return { known: false, status: 'UNREGISTERED', usable: false };
    const usable = ['IMPLEMENTED', 'QA_PASSED', 'VALIDATED'].includes(String(entry.status));
    return { known: true, status: String(entry.status ?? 'UNKNOWN'), usable };
  }, [backends.data, backend]);

  const measuredPieces = siblings.data?.items.length ?? null;
  const qaRows = detail.data
    ? flattenMetrics(detail.data.asset.qa, { prefix: 'qa', origin: 'GET /assets/{id}.qa（后端原样）' })
    : [];

  const requestPreview = async () => {
    setPreviewBusy(true);
    setPreviewFailure(null);
    setPreviewAccepted(null);
    try {
      const response = await postPreviews({
        stage: 'fracture',
        spec: {
          schema: 'synlab.v3',
          data_scope: 'SYNTHETIC',
          release_profile: 'SANDBOX_CORE',
          experiment_purpose: 'DEVELOPMENT',
          master_seed: 20261001,
          dataset: { target_mothers: 1, target_fragments_estimate: 8 },
          fracture: {
            backend,
            target_piece_range: targetPieceRange ?? [4, 12],
          },
        },
        idempotency_key: newIdempotencyKey(`fracture-preview:${backend}`),
      });
      setPreviewAccepted(response);
    } catch (caught) {
      setPreviewFailure(failureFromError(caught));
    } finally {
      setPreviewBusy(false);
    }
  };

  return (
    <>
      <SectionCard
        title="断裂预览：目标片数 vs 实测片数 + 审计数值"
        subtitle="GET /registry/fracture_backend · GET /assets?role=fragment_mesh&lineage_id= · GET /assets/{id}"
        actions={
          <div className="row">
            <Badge tone={backendStatus.usable ? 'ok' : 'warn'}>
              {backend} = {backendStatus.status}
            </Badge>
            {!backendStatus.known ? <Badge tone="bad">registry 未注册该后端</Badge> : null}
          </div>
        }
      >
        <div className="grid2">
          <div>
            <h3>目标 vs 实测</h3>
            <table className="table table--metrics">
              <caption>目标来自断裂 spec；实测来自真实资产的真实行数</caption>
              <thead>
                <tr>
                  <th scope="col">量</th>
                  <th scope="col">值</th>
                  <th scope="col">来源</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">目标片数区间</th>
                  <td className="mono">
                    {targetPieceRange ? `${targetPieceRange[0]} – ${targetPieceRange[1]}` : '未提供'}
                  </td>
                  <td className="mono small">spec.fracture.target_piece_range</td>
                </tr>
                <tr>
                  <th scope="row">实测片数（同谱系）</th>
                  <td className="mono">
                    {measuredPieces === null ? (
                      <Badge tone="warn">未选择碎片 / 无谱系</Badge>
                    ) : (
                      <span className="strong">{measuredPieces}</span>
                    )}
                  </td>
                  <td className="mono small">GET /assets?role=fragment_mesh&amp;lineage_id=</td>
                </tr>
                <tr>
                  <th scope="row">落在区间内</th>
                  <td>
                    {measuredPieces === null || !targetPieceRange ? (
                      <Badge tone="neutral">无法判定</Badge>
                    ) : measuredPieces >= targetPieceRange[0] && measuredPieces <= targetPieceRange[1] ? (
                      <Badge tone="ok">是</Badge>
                    ) : (
                      <Badge tone="warn">否（实测 {measuredPieces}）</Badge>
                    )}
                  </td>
                  <td className="mono small">本页比较，不改后端结论</td>
                </tr>
                <tr>
                  <th scope="row">本页展示的碎片</th>
                  <td className="mono">{fragmentId ?? '未选择'}</td>
                  <td className="mono small">在页面左侧“碎片”浏览器里选择</td>
                </tr>
                <tr>
                  <th scope="row">谱系</th>
                  <td className="mono">{lineageId ?? '未提供'}</td>
                  <td className="mono small">asset.lineage_id</td>
                </tr>
              </tbody>
            </table>
            {siblings.status === 'error' ? (
              <ErrorState error={siblings.error} onRetry={siblings.reload} compact title="同谱系碎片清单读取失败" />
            ) : null}

            <div className="row">
              <ActionButton
                onClick={() => void requestPreview()}
                busy={previewBusy}
                tone="primary"
                disabledReason={backendStatus.known ? null : 'registry 未注册该后端：POST /previews 会返回 422 BAD_REQUEST'}
              >
                提交一次断裂预览（POST /previews, stage=fracture）
              </ActionButton>
            </div>
            {previewFailure ? (
              <FailureCard
                title="断裂预览被拒绝"
                failure={previewFailure}
                onRetry={() => void requestPreview()}
                extra={
                  <p className="muted small">
                    复现：<code className="mono">curl -s -X POST /api/synlab/previews -H &quot;Content-Type: application/json&quot;
                    -d &apos;&#123;&quot;stage&quot;:&quot;fracture&quot;,&quot;spec&quot;:&#123;...&#125;&#125;&apos;</code>
                    （后端返回的 code 就是真实原因；PENDING/MISSING 后端不会产出任何几何）
                  </p>
                }
              />
            ) : null}
            {previewAccepted ? (
              <KeyValueList
                rows={[
                  { label: 'run_id', value: previewAccepted.run_id, mono: true },
                  { label: 'job_id', value: previewAccepted.job_id, mono: true },
                  { label: '受理状态', value: previewAccepted.status },
                  { label: 'spec_hash', value: previewAccepted.spec_hash, mono: true },
                  { label: '幂等重放', value: String(previewAccepted.idempotent_replay) },
                  { label: '事件流', value: <CopyValue value={`/api/synlab${previewAccepted.events_url.replace('/api/synlab', '')}`} label="事件流地址" /> },
                ]}
              />
            ) : null}
            {previewAccepted ? (
              <p className="muted small">
                HTTP 202 只表示已受理。计算要由 <code className="mono">python -m synlab.api.worker --store-root &lt;store&gt; --once --workspace default</code> 执行；
                该 run 的每个 job 的权威 state 与错误码在 U07 / 本页下方的任务列表里。
              </p>
            ) : null}
          </div>

          <div>
            <h3>碎片 3D（原位 / 爆炸）+ 断面高亮</h3>
            <FragmentMeshViewport
              asset={detail.data?.asset ?? null}
              explodeMm={explodeMm}
              highlightInterface={highlight}
              height={320}
              onLoaded={setMesh}
              title="权威碎片网格（arrays.npz）"
            />
            <div className="row">
              <label className="field field--inline">
                <span className="field__label">爆炸位移（mm，展示用）</span>
                <input
                  className="input input--tight"
                  type="range"
                  min={0}
                  max={200}
                  step={5}
                  value={explodeMm}
                  aria-label="爆炸位移"
                  onChange={(event) => setExplodeMm(Number(event.target.value))}
                />
                <span className="mono small">{explodeMm} mm</span>
              </label>
              <button type="button" className="btn btn--tiny" onClick={() => setExplodeMm(0)} disabled={explodeMm === 0}>
                回到原位
              </button>
            </div>
            <div className="row">
              <label className="field field--inline">
                <span className="field__label">断面高亮（真实 interface_id）</span>
                <select
                  className="input input--tight"
                  value={highlight === null ? '' : String(highlight)}
                  aria-label="断面高亮 interface_id"
                  disabled={!mesh || mesh.stats.interfaceIds.length === 0}
                  onChange={(event) => setHighlight(event.target.value === '' ? null : Number(event.target.value))}
                >
                  <option value="">（不按 interface 高亮）</option>
                  {(mesh?.stats.interfaceIds ?? []).map((id) => (
                    <option key={id} value={id}>
                      interface_id={id}（{mesh?.stats.interfaceFaceCounts.get(id)} 面）
                    </option>
                  ))}
                </select>
              </label>
              {mesh && !mesh.stats.hasInterfaceId ? (
                <Badge tone="warn">该资产缺 mesh.face__interface_id，无法按断面对比色</Badge>
              ) : null}
            </div>
            {mesh && !mesh.stats.hasOriginKind ? (
              <BlockedState
                title="该资产缺断面属性"
                code="FACE_ATTR_MISSING"
                reason={
                  <>
                    数组里没有 <code className="mono">mesh.face__origin_kind</code>，因此无法区分新断面与母体原表面。
                    本页面不会用几何法向或人工颜色代替权威面属性。实际键：
                    <span className="mono">{mesh.stats.keys.join(', ')}</span>
                  </>
                }
              />
            ) : null}
          </div>
        </div>

        <h3>审计数值（后端原样）</h3>
        {!fragmentId ? (
          <EmptyState title="未选择碎片" reason="在左侧“碎片（fragment_mesh）”里选择一个资产后，这里显示它的 qa / meta / integrity。" />
        ) : detail.status === 'error' ? (
          <ErrorState error={detail.error} onRetry={detail.reload} title="碎片详情读取失败" />
        ) : detail.status === 'loading' && !detail.data ? (
          <LoadingState label="读取碎片详情…" />
        ) : detail.data ? (
          <>
            <MeasuredQualityTable
              rows={[
                ...qaRows,
                ...(detail.data.asset.meta?.volume_mm3 !== undefined
                  ? [{
                      key: 'meta.volume_mm3',
                      label: 'meta.volume_mm3',
                      value: String(detail.data.asset.meta.volume_mm3),
                      unit: 'mm³',
                      source: 'GET /assets/{id}.meta',
                    }]
                  : []),
                {
                  key: 'meta.is_tiny',
                  label: 'meta.is_tiny',
                  value: String(detail.data.asset.meta?.is_tiny ?? '未提供'),
                  source: 'GET /assets/{id}.meta',
                },
                {
                  key: 'integrity',
                  label: 'integrity.ok（逐文件 hash 核验）',
                  value: String(detail.data.asset.integrity?.ok ?? '未提供'),
                  source: 'GET /assets/{id}.integrity',
                  flag: detail.data.asset.integrity && !detail.data.asset.integrity.ok ? 'failed' : null,
                },
                ...progressRows(null),
              ]}
              caption={`${fragmentId} 的实测/审计字段（缺失显示“未提供”，不补 0）`}
              emptyTitle="该碎片没有 qa 字段"
              emptyReason="后端没有为这个资产记录 qa：未实测的项不会被填成 0。"
            />
            <details>
              <summary>qa.parent_qa / meta / ancestry（后端原样）</summary>
              <pre className="mono pre">{pretty({
                qa: detail.data.asset.qa,
                meta: detail.data.asset.meta,
                ancestry: detail.data.asset.ancestry,
                integrity: detail.data.asset.integrity,
              })}</pre>
            </details>
            {detail.data.asset.integrity && !detail.data.asset.integrity.ok ? (
              <p className="warning" role="alert">
                integrity 校验未通过：{detail.data.asset.integrity.problems.join('; ')}
              </p>
            ) : null}
          </>
        ) : null}
      </SectionCard>
    </>
  );
}
