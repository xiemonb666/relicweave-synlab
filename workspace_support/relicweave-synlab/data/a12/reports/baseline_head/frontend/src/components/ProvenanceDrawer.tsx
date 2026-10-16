/**
 * ProvenanceDrawer —— 溯源抽屉（计划 20.1：seed/hash/schema 放高级/追溯抽屉）。
 *
 * 三类对象：
 * * 资产：`GET /assets/{id}`（完整性/文件 URL/ancestry）+ 研究角色的
 *   `GET /research/assets/{id}/truth`（普通会话会拿到 `403 ROLE_FORBIDDEN` 或
 *   `403 TRUTH_ROUTE_UNMOUNTED`，这里如实显示该错误码而不是隐藏入口）；
 * * release：`GET /releases/{id}`（manifest_hash / 依赖闭包 / gates / coverage）；
 * * job：`GET /jobs/{id}`（spec_hash / 依赖 / 资源估计）。
 *
 * 只展示后端返回的 hash 与引用，不重新计算任何“真值”。
 */

import { useEffect, useState } from 'react';

import { getAsset, getJob, getRelease, getResearchTruth } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { formatTimestamp, pretty, truncate } from '../lib/format';
import { Badge, CopyValue, Drawer, EmptyState, ErrorState, KeyValueList, LoadingState, Tabs } from './states';

export type ProvenanceTarget =
  | { kind: 'asset'; id: string }
  | { kind: 'release'; id: string }
  | { kind: 'job'; id: string }
  | null;

export interface ProvenanceDrawerProps {
  target: ProvenanceTarget;
  onClose: () => void;
}

export function ProvenanceDrawer({ target, onClose }: ProvenanceDrawerProps) {
  const open = target !== null;
  const [tab, setTab] = useState<'main' | 'raw' | 'truth'>('main');
  const [truthRequested, setTruthRequested] = useState(false);

  useEffect(() => {
    setTruthRequested(false);
    setTab('main');
  }, [target?.kind, target === null ? null : target.id]);

  const asset = useResource(
    (signal) => getAsset((target as { id: string }).id, signal),
    [target?.kind === 'asset' ? target.id : null],
    { enabled: open && target?.kind === 'asset' },
  );
  const release = useResource(
    (signal) => getRelease((target as { id: string }).id, signal),
    [target?.kind === 'release' ? target.id : null],
    { enabled: open && target?.kind === 'release' },
  );
  const job = useResource(
    (signal) => getJob((target as { id: string }).id, signal),
    [target?.kind === 'job' ? target.id : null],
    { enabled: open && target?.kind === 'job' },
  );
  const truth = useResource(
    (signal) => getResearchTruth((target as { id: string }).id, true, signal),
    [target?.kind === 'asset' ? target.id : null, truthRequested],
    { enabled: open && target?.kind === 'asset' && truthRequested },
  );

  const title =
    target === null
      ? ''
      : `溯源 · ${target.kind} · ${truncate(target.id, 28)}`;

  return (
    <Drawer open={open} title={title} onClose={onClose}>
      {target && target.kind === 'asset' ? (
        <>
          <Tabs
            label="溯源视图"
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
            tabs={[
              { id: 'main', label: '资产与完整性' },
              { id: 'truth', label: '研究真值入口' },
              { id: 'raw', label: '原始 JSON' },
            ]}
          />
          {asset.status === 'loading' ? <LoadingState label="GET /assets/{id}…" /> : null}
          {asset.status === 'error' ? <ErrorState error={asset.error} onRetry={asset.reload} compact /> : null}
          {asset.data && tab === 'main' ? (
            <>
              <KeyValueList
                rows={[
                  { label: 'asset_id', value: <CopyValue value={asset.data.asset.asset_id} label="asset_id" /> },
                  { label: 'role / schema', value: `${asset.data.asset.role} · ${asset.data.asset.schema}`, mono: true },
                  { label: 'unit / frame', value: `${asset.data.asset.unit} · ${asset.data.asset.frame}`, mono: true },
                  { label: 'blob_hash', value: <span className="mono">{asset.data.asset.blob_hash}</span> },
                  {
                    label: 'interpretation_hash',
                    value: <span className="mono">{asset.data.asset.interpretation_hash}</span>,
                  },
                  { label: 'qa_status', value: asset.data.asset.qa_status },
                  { label: 'lineage / split', value: `${asset.data.asset.lineage_id ?? '—'} / ${asset.data.asset.split ?? '—'}`, mono: true },
                  { label: 'revision', value: asset.data.asset.revision },
                  { label: 'created_at', value: formatTimestamp(asset.data.asset.created_at) },
                  { label: '会话角色', value: asset.data.role },
                  {
                    label: '研究专用角色',
                    value: asset.data.asset.research_only_role ? '是（部署会话不可读取）' : '否',
                  },
                  {
                    label: 'display_transform',
                    value: asset.data.display_transform ? <pre className="mono pre pre--inline">{pretty(asset.data.display_transform)}</pre> : '未提供（非展示派生资产）',
                  },
                ]}
              />

              <h4>文件完整性（服务端逐文件 hash 校验）</h4>
              {asset.data.asset.integrity ? (
                <>
                  <p>
                    <Badge tone={asset.data.asset.integrity.ok ? 'ok' : 'bad'}>
                      {asset.data.asset.integrity.ok ? '全部文件通过' : '存在完整性错误'}
                    </Badge>
                    {asset.data.asset.integrity.problems.length > 0 ? (
                      <span className="mono small"> {asset.data.asset.integrity.problems.join('; ')}</span>
                    ) : null}
                  </p>
                  <table className="table table--tight">
                    <thead>
                      <tr>
                        <th scope="col">key</th>
                        <th scope="col">ok</th>
                        <th scope="col">size</th>
                        <th scope="col">sha256</th>
                        <th scope="col">校验状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(asset.data.asset.integrity.files).map(([key, file]) => (
                        <tr key={key}>
                          <th scope="row" className="mono">
                            {key}
                          </th>
                          <td>
                            <Badge tone={file.ok ? 'ok' : 'bad'}>{file.ok ? 'ok' : 'bad'}</Badge>
                          </td>
                          <td className="mono">{file.size}</td>
                          <td className="mono" title={file.sha256}>
                            {truncate(file.sha256, 20)}
                          </td>
                          <td className="mono">{String(file.hash_verified)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : (
                <p className="muted">后端未返回 integrity 字段。</p>
              )}

              <h4>祖先（ancestry）</h4>
              {asset.data.asset.ancestry_hidden ? (
                <p className="warning">当前会话没有 can_read_ancestry 权限，后端隐藏了祖先列表。</p>
              ) : asset.data.asset.ancestry.length === 0 ? (
                <p className="muted">后端返回空祖先列表（该资产是根资产，或 lineage 未记录）。</p>
              ) : (
                <ol className="ancestry">
                  {asset.data.asset.ancestry.map((id) => (
                    <li key={id} className="mono">
                      {id}
                    </li>
                  ))}
                </ol>
              )}

              <h4>文件 URL（点击进入下载接口，会带 sha256 响应头）</h4>
              <ul className="filelist">
                {Object.entries(asset.data.asset.file_urls ?? {}).map(([key, url]) => (
                  <li key={key}>
                    <a href={url} target="_blank" rel="noreferrer" className="mono">
                      {key}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {tab === 'truth' ? (
            <>
              <p className="muted">
                研究真值走独立入口 <code className="mono">GET /research/assets/&#123;id&#125;/truth</code>。
                部署/运维会话下该路由**不挂载**，会返回{' '}
                <code className="mono">403 TRUTH_ROUTE_UNMOUNTED</code>；研究路由挂载但角色不允许时返回{' '}
                <code className="mono">403 ROLE_FORBIDDEN</code>。这里按需请求并原样显示结果。
              </p>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setTruthRequested(true);
                  truth.reload();
                }}
                disabled={truth.refreshing}
              >
                {truth.refreshing ? '请求中…' : truthRequested ? '重新请求研究真值' : '请求研究真值'}
              </button>
              {truth.status === 'error' ? <ErrorState error={truth.error} compact onRetry={truth.reload} /> : null}
              {truth.data ? (
                <>
                  <KeyValueList
                    rows={[
                      { label: 'truth_role', value: String(truth.data.truth_role) },
                      { label: 'split', value: truth.data.split ?? '未提供' },
                      { label: 'array_keys', value: truth.data.array_keys.join(', ') || '无（未请求数组）' },
                      { label: 'integrity', value: truth.data.integrity.ok ? 'ok' : truth.data.integrity.problems.join('; ') },
                      { label: 'note', value: truth.data.access.note },
                    ]}
                  />
                  <pre className="mono pre">{pretty(truth.data.meta)}</pre>
                </>
              ) : null}
            </>
          ) : null}

          {asset.data && tab === 'raw' ? <pre className="mono pre">{pretty(asset.data)}</pre> : null}
        </>
      ) : null}

      {target && target.kind === 'release' ? (
        <>
          {release.status === 'loading' ? <LoadingState label="GET /releases/{id}…" /> : null}
          {release.status === 'error' ? <ErrorState error={release.error} onRetry={release.reload} compact /> : null}
          {release.data ? (
            (() => {
              const manifest = release.data;
              return (
                <>
                  <KeyValueList
                    rows={[
                      { label: 'release_id', value: <CopyValue value={manifest.release_id} label="release_id" /> },
                      { label: 'manifest_hash', value: <span className="mono">{manifest.manifest_hash}</span> },
                      { label: 'profile / scope', value: `${manifest.profile} / ${manifest.scope}` },
                      { label: 'asset_count', value: manifest.asset_count },
                      { label: 'frozen_at', value: formatTimestamp(manifest.frozen_at) },
                      { label: 'readonly', value: String(manifest.readonly) },
                    ]}
                  />
                  <h4>Gates（来自 release manifest）</h4>
                  <table className="table table--tight">
                    <thead>
                      <tr>
                        <th scope="col">gate</th>
                        <th scope="col">状态</th>
                        <th scope="col">是否必需</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(manifest.gates ?? {}).map(([gate, status]) => (
                        <tr key={gate}>
                          <th scope="row" className="mono">
                            {gate}
                          </th>
                          <td className="mono">{status}</td>
                          <td>{(manifest.required_gates ?? []).includes(gate) ? '必需' : '非必需'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <h4>依赖闭包（closure）</h4>
                  <pre className="mono pre">{pretty(manifest.closure)}</pre>
                  <h4>coverage</h4>
                  <pre className="mono pre">{pretty(manifest.coverage)}</pre>
                  <h4>资产</h4>
                  <pre className="mono pre">
                    {pretty(
                      manifest.assets.map((item) => ({
                        asset_id: item.asset_id,
                        role: item.role,
                        qa_status: item.qa_status,
                      })),
                    )}
                  </pre>
                </>
              );
            })()
          ) : null}
        </>
      ) : null}

      {target && target.kind === 'job' ? (
        <>
          {job.status === 'loading' ? <LoadingState label="GET /jobs/{id}…" /> : null}
          {job.status === 'error' ? <ErrorState error={job.error} onRetry={job.reload} compact /> : null}
          {job.data ? (
            <>
              <KeyValueList
                rows={[
                  { label: 'job_id', value: <CopyValue value={job.data.job.job_id} label="job_id" /> },
                  { label: 'run_id', value: <CopyValue value={job.data.job.run_id} label="run_id" /> },
                  { label: 'stage', value: `${job.data.job.stage}（${job.data.stage_title}）` },
                  { label: 'state', value: job.data.job.state },
                  { label: 'attempt / fencing', value: `${job.data.job.attempt} / ${job.data.job.fencing}` },
                  { label: 'spec_hash', value: <span className="mono">{job.data.run.spec_hash ?? '未提供'}</span> },
                  { label: 'profile', value: job.data.run.profile ?? '未提供' },
                  { label: 'run revision', value: job.data.run.revision ?? '未提供' },
                  { label: '输入 / 输出', value: `${job.data.job.inputs.length} / ${job.data.job.outputs.length}` },
                  { label: '资源估计', value: <pre className="mono pre pre--inline">{pretty(job.data.resource_estimate)}</pre> },
                ]}
              />
              <h4>job spec（含 workspace / 幂等上下文）</h4>
              <pre className="mono pre">{pretty(job.data.job.spec ?? {})}</pre>
            </>
          ) : null}
        </>
      ) : null}

      {!target ? <EmptyState title="未选择溯源对象" /> : null}
    </Drawer>
  );
}
