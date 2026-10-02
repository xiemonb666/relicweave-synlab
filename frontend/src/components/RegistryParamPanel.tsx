/**
 * RegistryParamPanel —— 用**后端 registry 的 `param_schema`** 生成参数表单（计划 20.14.7）。
 *
 * 数据链路：`GET /registry/{kind}` → `entries[i].param_schema`（Pydantic v2 `model_json_schema()`）
 * → `SchemaForm` 的 `jsonSchema` 模式 → 真实控件（label 取 `title`，范围取 `minimum/maximum`，
 * 单位从 `description`/字段名后缀推断）。
 *
 * 重要边界（如实标注）：这些参数属于实现模块的 builder（例如 `synlab.mothers` 的
 * `create_mother`），**不在** `GenerationSpec` 内 —— `synlab/schemas/spec.py` 是 `extra="forbid"`，
 * 把它们塞进 spec 会被 422 拒绝。当前 HTTP API 没有把 override 传入生成流程的路由；
 * spec 里可用的真实通道是 `sampling.parameter_bounds_ref`（指向参数边界文件）。
 */

import { useEffect, useMemo, useState } from 'react';

import { getRegistry } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { JsonSchemaNode, RegistryEntry } from '../api/types';
import { asArray, isRecord, pretty } from '../lib/format';
import { SchemaForm, schemaToFields, type FormValue } from './SchemaForm';
import { Badge, EmptyState, ErrorState, KeyValueList, LoadingState, SectionCard } from './states';

export interface RegistryParamPanelProps {
  registryKind: string;
  title: string;
  subtitle?: string;
  /** 卡片下方的额外说明（例如该参数如何去重/覆盖）。 */
  note?: React.ReactNode;
  /** 选中条目变化时回调，方便页面把它同步到 spec 的 ID 列表里。 */
  onSelectId?: (id: string) => void;
  /** 用 schema 默认值初始化草稿。 */
  useDefaults?: boolean;
  /** 额外的“空状态”原因（registry 返回 0 条时显示）。 */
  emptyReason?: React.ReactNode;
}

function defaultsFromSchema(schema: JsonSchemaNode | undefined): FormValue {
  if (!schema?.properties) return {};
  const out: FormValue = {};
  for (const [key, raw] of Object.entries(schema.properties)) {
    if (raw.default !== undefined) out[key] = raw.default;
  }
  return out;
}

export function RegistryParamPanel({
  registryKind,
  title,
  subtitle,
  note,
  onSelectId,
  useDefaults = true,
  emptyReason,
}: RegistryParamPanelProps) {
  const registry = useResource((signal) => getRegistry(registryKind, {}, signal), [registryKind]);
  const entries: RegistryEntry[] = registry.data?.entries ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, FormValue>>({});

  const selected = useMemo(
    () => entries.find((entry) => entry.id === selectedId) ?? entries[0] ?? null,
    [entries, selectedId],
  );

  useEffect(() => {
    if (selected && onSelectId) onSelectId(selected.id);
    // onSelectId 由页面提供，避免把它放进依赖导致循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  useEffect(() => {
    if (!selected) return;
    setDrafts((current) =>
      current[selected.id] ? current : { ...current, [selected.id]: useDefaults ? defaultsFromSchema(selected.param_schema) : {} },
    );
  }, [selected, useDefaults]);

  const schema = selected?.param_schema;
  const { fields, skipped } = useMemo(() => schemaToFields(schema ?? {}), [schema]);
  const draft = selected ? (drafts[selected.id] ?? {}) : {};

  return (
    <SectionCard
      title={title}
      subtitle={
        subtitle ?? (
          <>
            GET <code className="mono">/registry/{registryKind}</code> → <code className="mono">param_schema</code> →
            SchemaForm（真实 label/范围/默认值）
          </>
        )
      }
      actions={
        <button type="button" className="btn btn--tiny" onClick={registry.reload} disabled={registry.refreshing}>
          {registry.refreshing ? '刷新中…' : '刷新'}
        </button>
      }
    >
      {registry.status === 'loading' ? <LoadingState label={`读取 /registry/${registryKind}…`} /> : null}
      {registry.status === 'error' ? <ErrorState error={registry.error} onRetry={registry.reload} /> : null}

      {registry.data && entries.length === 0 ? (
        <EmptyState
          title={`registry/${registryKind} 返回 0 条`}
          reason={
            <>
              {emptyReason ?? '后端没有为这个 kind 注册条目，因此没有可用的参数模型。前端不会复制一份范围表。'}
              <div className="muted small">
                empty_kinds={registry.data.empty_kinds.join(', ') || '—'} · fingerprint=
                <span className="mono">{registry.data.registry_fingerprint}</span>
              </div>
              <div className="muted small">{registry.data.note}</div>
            </>
          }
        />
      ) : null}

      {entries.length > 0 ? (
        <>
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">条目</span>
              <select
                className="input input--tight"
                value={selected?.id ?? ''}
                onChange={(event) => setSelectedId(event.target.value)}
              >
                {entries.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.id}
                    {entry.name ? ` · ${entry.name}` : ''}
                    {entry.version ? ` (v${entry.version})` : ''}
                  </option>
                ))}
              </select>
            </label>
            {selected ? (
              <>
                <Badge tone={selected.status === 'IMPLEMENTED' ? 'ok' : 'neutral'}>{selected.status ?? '状态未提供'}</Badge>
                <span className="mono small">
                  {String(selected.module ?? '模块未提供')} · {entries.length} 条
                </span>
              </>
            ) : null}
          </div>

          {selected ? (
            <>
              {selected.applicable ? (
                <details>
                  <summary>适用组合 applicable（后端声明，用于“只对当前族展示适用字段”）</summary>
                  <pre className="mono pre">{pretty(selected.applicable)}</pre>
                  {isRecord(selected.applicable) ? (
                    <KeyValueList
                      rows={Object.entries(selected.applicable).map(([key, value]) => ({
                        label: key,
                        value: Array.isArray(value) ? asArray<string>(value).join(', ') : String(value),
                      }))}
                    />
                  ) : null}
                </details>
              ) : null}

              {selected.notes ? <p className="muted small">{String(selected.notes)}</p> : null}

              {fields.length === 0 ? (
                <EmptyState
                  title="该条目的 param_schema 没有可生成的标量字段"
                  reason="后端 schema 里只有嵌套对象/数组等未展开构造；下方原始 schema 可作为参考。"
                />
              ) : (
                <div className="registry-form">
                  <SchemaForm
                    jsonSchema={schema}
                    value={draft}
                    onChange={(next) => setDrafts((current) => ({ ...current, [selected.id]: next }))}
                    advanced={false}
                    label={`${registryKind} 参数`}
                  />
                </div>
              )}

              {skipped.length > 0 ? (
                <p className="muted small">
                  未生成控件的构造：<code className="mono">{skipped.map((item) => item.path).join(', ')}</code>
                </p>
              ) : null}

              <details>
                <summary>当前参数草稿（{Object.keys(draft).length} 个键）</summary>
                <pre className="mono pre">{pretty(draft)}</pre>
              </details>

              <details>
                <summary>原始 param_schema（后端 Pydantic model_json_schema 输出）</summary>
                <pre className="mono pre">{pretty(schema)}</pre>
              </details>

              <p className="muted small">
                上表的 label / 单位 / min-max / 默认值全部读自后端 <code className="mono">param_schema</code>；
                前端不维护第二份范围表。共 {Object.keys(schema?.properties ?? {}).length} 个 schema 属性。
              </p>
            </>
          ) : null}

          {note ? <div className="warning">{note}</div> : null}
        </>
      ) : null}
    </SectionCard>
  );
}
