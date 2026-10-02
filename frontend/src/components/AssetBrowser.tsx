/**
 * AssetBrowser —— 分页资产浏览器（计划 20.14.3：虚拟列表/分页，禁止一次加载十万 GLB）。
 *
 * 只调用真实 `GET /assets`（keyset cursor 分页 + 服务端 role/workspace 过滤），
 * 空结果直接显示后端返回的 `empty_reason`。角色清单不硬编码：可选角色来自当前已加载资产，
 * 手动输入的角色由服务端白名单/权限判定并把真实错误显示出来。
 */

import { useMemo, useState } from 'react';

import { listAssets } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AssetRecord } from '../api/types';
import { formatRelative, pretty, qaLabel, truncate } from '../lib/format';
import { Badge, CopyValue, Drawer, EmptyState, ErrorState, LoadingState } from './states';

export interface AssetBrowserProps {
  title?: string;
  /** 固定筛选（页面语义），会与用户输入合并。 */
  fixedRoles?: string[];
  fixedQaStatus?: string;
  fixedSplit?: string;
  lineageId?: string | null;
  pageSize?: number;
  /** 选中模式；`none` 时只浏览。 */
  selectable?: 'none' | 'single' | 'multi';
  selected?: string[];
  onSelect?: (assetIds: string[]) => void;
  /** 同时给出完整资产记录（视口需要 role 与真实的 payload key）。 */
  onSelectAssets?: (assets: AssetRecord[]) => void;
  onProvenance?: (assetId: string) => void;
  /** 页内跳转（例如“去退化页比较”）。 */
  renderRowActions?: (asset: AssetRecord) => React.ReactNode;
  emptyReason?: string;
}

export function AssetBrowser({
  title = '资产浏览器',
  fixedRoles,
  fixedQaStatus,
  fixedSplit,
  lineageId,
  pageSize = 25,
  selectable = 'single',
  selected = [],
  onSelect,
  onSelectAssets,
  onProvenance,
  renderRowActions,
  emptyReason,
}: AssetBrowserProps) {
  const [roleInput, setRoleInput] = useState('');
  const [qaStatus, setQaStatus] = useState(fixedQaStatus ?? '');
  const [split, setSplit] = useState(fixedSplit ?? '');
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<Array<string | null>>([]);
  const [detail, setDetail] = useState<AssetRecord | null>(null);

  const roles = useMemo(
    () => [...(fixedRoles ?? []), ...roleInput.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean)],
    [fixedRoles, roleInput],
  );

  const resource = useResource(
    (signal) =>
      listAssets(
        {
          role: roles.length > 0 ? roles : undefined,
          qa_status: qaStatus || undefined,
          split: split || undefined,
          lineage_id: lineageId || undefined,
          limit: pageSize,
          cursor: cursor ?? undefined,
          with_total: true,
        },
        signal,
      ),
    [roles.join('|'), qaStatus, split, lineageId, pageSize, cursor],
  );

  const items = resource.data?.items ?? [];
  const availableRoles = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) set.add(item.role);
    return [...set].sort();
  }, [items]);

  const toggle = (asset: AssetRecord) => {
    if (selectable === 'none') return;
    if (selectable === 'single') {
      onSelect?.([asset.asset_id]);
      onSelectAssets?.([asset]);
      return;
    }
    const nextIds = selected.includes(asset.asset_id)
      ? selected.filter((id) => id !== asset.asset_id)
      : [...selected, asset.asset_id];
    onSelect?.(nextIds);
    onSelectAssets?.(items.filter((item) => nextIds.includes(item.asset_id)));
  };

  return (
    <section className="card" aria-label={title}>
      <header className="card__head">
        <div>
          <h2 className="card__title">{title}</h2>
          <p className="card__subtitle">
            GET /assets（keyset 分页，服务端过滤 workspace/role）· 已加载 {items.length} 条
            {resource.data?.total !== undefined ? ` · total=${resource.data.total}` : ''}
          </p>
        </div>
        <div className="card__actions">
          <button type="button" className="btn btn--tiny" onClick={resource.reload} disabled={resource.refreshing}>
            {resource.refreshing ? '刷新中…' : '刷新'}
          </button>
        </div>
      </header>

      <div className="filters">
        <label className="field field--inline">
          <span className="field__label">角色过滤（空格/逗号分隔）</span>
          <input
            className="input input--tight"
            type="text"
            value={roleInput}
            placeholder="例如 mother_mesh fragment_mesh display_lod"
            list="asset-role-suggestions"
            onChange={(event) => {
              setRoleInput(event.target.value);
              setCursor(null);
              setCursorStack([]);
            }}
          />
          <datalist id="asset-role-suggestions">
            {availableRoles.map((role) => (
              <option key={role} value={role} />
            ))}
          </datalist>
        </label>
        <label className="field field--inline">
          <span className="field__label">QA 状态</span>
          <select
            className="input input--tight"
            value={qaStatus}
            onChange={(event) => {
              setQaStatus(event.target.value);
              setCursor(null);
              setCursorStack([]);
            }}
          >
            <option value="">（全部）</option>
            <option value="QA_PASS">QA_PASS</option>
            <option value="QA_PENDING">QA_PENDING</option>
            <option value="QA_FAIL">QA_FAIL</option>
          </select>
        </label>
        <label className="field field--inline">
          <span className="field__label">split</span>
          <input
            className="input input--tight"
            type="text"
            value={split}
            placeholder="train / dev / confirm"
            onChange={(event) => {
              setSplit(event.target.value);
              setCursor(null);
              setCursorStack([]);
            }}
          />
        </label>
        <label className="field field--inline">
          <span className="field__label">lineage_id</span>
          <input
            className="input input--tight"
            type="text"
            value={lineageId ?? ''}
            readOnly
            placeholder="由页面传入"
          />
        </label>
      </div>

      {resource.status === 'loading' ? <LoadingState label="加载资产列表…" /> : null}
      {resource.status === 'error' ? <ErrorState error={resource.error} onRetry={resource.reload} /> : null}

      {resource.status === 'ready' && items.length === 0 ? (
        <EmptyState
          title="没有匹配的资产"
          reason={
            <>
              {resource.data?.empty_reason ?? emptyReason ?? '后端返回的列表为空。'}
              {resource.data?.role_filter_default ? (
                <>
                  <br />
                  当前会话默认只返回部署安全角色：<code className="mono">{resource.data.role_filter_default}</code>。
                </>
              ) : null}
              {resource.data?.research_roles_hidden && resource.data.research_roles_hidden.length > 0 ? (
                <>
                  <br />
                  被隐藏的研究角色：
                  <code className="mono">{resource.data.research_roles_hidden.join(', ')}</code>
                </>
              ) : null}
            </>
          }
        />
      ) : null}

      {items.length > 0 ? (
        <div className="tablewrap">
          <table className="table">
            <caption>{title}：数据来自 GET /assets，未做任何本地补全</caption>
            <thead>
              <tr>
                {selectable !== 'none' ? <th scope="col">选择</th> : null}
                <th scope="col">asset_id</th>
                <th scope="col">role</th>
                <th scope="col">schema</th>
                <th scope="col">unit / frame</th>
                <th scope="col">QA</th>
                <th scope="col">lineage / split</th>
                <th scope="col">文件</th>
                <th scope="col">创建</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((asset) => {
                const qa = qaLabel(asset.qa_status);
                const isSelected = selected.includes(asset.asset_id);
                return (
                  <tr key={asset.asset_id} className={isSelected ? 'row--selected' : undefined}>
                    {selectable !== 'none' ? (
                      <td>
                        <input
                          type={selectable === 'single' ? 'radio' : 'checkbox'}
                          name={`asset-${title}`}
                          checked={isSelected}
                          onChange={() => toggle(asset)}
                          aria-label={`选择资产 ${asset.asset_id}`}
                        />
                      </td>
                    ) : null}
                    <td className="mono" title={asset.asset_id}>
                      {truncate(asset.asset_id, 22)}
                    </td>
                    <td>
                      <Badge tone="neutral">{asset.role}</Badge>
                    </td>
                    <td className="mono">{asset.schema}</td>
                    <td className="mono">
                      {asset.unit} / {asset.frame}
                    </td>
                    <td>
                      <Badge tone={qa.tone}>{qa.label}</Badge>
                    </td>
                    <td className="mono">
                      {asset.lineage_id ? truncate(asset.lineage_id, 14) : '—'} / {asset.split ?? '—'}
                    </td>
                    <td className="mono">{Object.keys(asset.files).join(', ') || '无'}</td>
                    <td title={String(asset.created_at)}>{formatRelative(asset.created_at)}</td>
                    <td className="rowactions">
                      <button type="button" className="btn btn--tiny" onClick={() => setDetail(asset)}>
                        详情
                      </button>
                      {onProvenance ? (
                        <button type="button" className="btn btn--tiny" onClick={() => onProvenance(asset.asset_id)}>
                          溯源
                        </button>
                      ) : null}
                      {renderRowActions?.(asset)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="pager">
        <button
          type="button"
          className="btn btn--tiny"
          onClick={() => {
            if (cursorStack.length === 0) return;
            const stack = [...cursorStack];
            const previous = stack.pop() ?? null;
            setCursorStack(stack);
            setCursor(previous);
          }}
          disabled={cursorStack.length === 0}
          title={cursorStack.length === 0 ? '已是第一页' : undefined}
        >
          上一页
        </button>
        <button
          type="button"
          className="btn btn--tiny"
          onClick={() => {
            if (!resource.data?.next_cursor) return;
            setCursorStack([...cursorStack, cursor]);
            setCursor(resource.data.next_cursor);
          }}
          disabled={!resource.data?.has_more || !resource.data?.next_cursor}
          title={!resource.data?.has_more ? '后端 has_more=false，没有下一页' : undefined}
        >
          下一页
        </button>
        <span className="muted">
          第 {cursorStack.length + 1} 页 · limit={resource.data?.limit ?? pageSize} · 排序 {resource.data?.order ?? '—'}
        </span>
      </div>

      <Drawer open={detail !== null} title={`资产详情 ${detail?.asset_id ?? ''}`} onClose={() => setDetail(null)}>
        {detail ? (
          <>
            <p className="muted">
              这里是列表接口返回的字段；文件完整性校验与文件 URL 需要 <code className="mono">GET /assets/&#123;id&#125;</code>。
              完整溯源请在“溯源”抽屉中查看。
            </p>
            <dl className="kv">
              <div className="kv__row">
                <dt>asset_id</dt>
                <dd>
                  <CopyValue value={detail.asset_id} label="asset_id" />
                </dd>
              </div>
              <div className="kv__row">
                <dt>role / schema</dt>
                <dd className="mono">
                  {detail.role} · {detail.schema}
                </dd>
              </div>
              <div className="kv__row">
                <dt>单位 / 坐标系</dt>
                <dd className="mono">
                  {detail.unit} · {detail.frame}
                </dd>
              </div>
              <div className="kv__row">
                <dt>blob_hash</dt>
                <dd className="mono">{detail.blob_hash}</dd>
              </div>
              <div className="kv__row">
                <dt>interpretation_hash</dt>
                <dd className="mono">{detail.interpretation_hash}</dd>
              </div>
              <div className="kv__row">
                <dt>qa</dt>
                <dd>
                  <pre className="mono pre">{pretty(detail.qa)}</pre>
                </dd>
              </div>
              <div className="kv__row">
                <dt>meta</dt>
                <dd>
                  <pre className="mono pre">{pretty(detail.meta)}</pre>
                </dd>
              </div>
              <div className="kv__row">
                <dt>files</dt>
                <dd>
                  <pre className="mono pre">{pretty(detail.files)}</pre>
                </dd>
              </div>
              <div className="kv__row">
                <dt>ancestry</dt>
                <dd className="mono">{detail.ancestry.length > 0 ? detail.ancestry.join(' → ') : '（后端未返回祖先）'}</dd>
              </div>
            </dl>
          </>
        ) : null}
      </Drawer>
    </section>
  );
}
