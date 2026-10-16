/**
 * SchemaForm —— 统一参数表单（计划 20.1 / 20.14）。
 *
 * 两种来源都被真实支持：
 *
 * 1. **后端 JSONSchema**：`GET /registry/{kind}` 的 `entries[].param_schema`
 *    （Pydantic v2 `model_json_schema()` 输出）由 `schemaToFields` 转成字段；
 * 2. **显式字段描述**：当 registry 为空（本仓库当前就是这种情况，见 docs/a12/api_ui.md）
 *    时用页面声明的 `FieldSpec[]`，字段名与后端 `synlab/schemas/spec.py` 的
 *    `extra="forbid"` 模型逐字对应。
 *
 * 前端**不做**“另一套范围表”：合法性最终由 `POST /specs/validate` 与 `POST /jobs` 判定，
 * 服务端返回的 `errors[].loc` 会精确落到对应字段上。
 */

import { useEffect, useId, useMemo, useState } from 'react';

import type { JsonSchemaNode, SpecValidationIssue } from '../api/types';
import { asArray, asNumber, asString, isRecord } from '../lib/format';
import { Field } from './states';

/* ------------------------------------------------------------------ 字段描述 */
export type FieldSpec =
  | {
      kind: 'string';
      path: string;
      label: string;
      unit?: string;
      hint?: string;
      placeholder?: string;
      enumValues?: string[];
      required?: boolean;
    }
  | {
      kind: 'number';
      path: string;
      label: string;
      unit?: string;
      hint?: string;
      min?: number;
      max?: number;
      step?: number;
      integer?: boolean;
      required?: boolean;
    }
  | { kind: 'boolean'; path: string; label: string; hint?: string }
  | {
      kind: 'stringList';
      path: string;
      label: string;
      hint?: string;
      placeholder?: string;
      required?: boolean;
    }
  | {
      kind: 'numberTuple';
      path: string;
      label: string;
      unit?: string;
      hint?: string;
      length: number;
      integer?: boolean;
    }
  | { kind: 'group'; label: string; hint?: string; children: FieldSpec[] };

export type FormValue = Record<string, unknown>;

/* ------------------------------------------------------------------ path 读写 */
export function getPath(source: unknown, path: string): unknown {
  const parts = path.split('.');
  let current: unknown = source;
  for (const part of parts) {
    if (!isRecord(current)) return undefined;
    current = current[part];
  }
  return current;
}

export function setPath<T extends FormValue>(source: T, path: string, value: unknown): T {
  const parts = path.split('.');
  const clone: FormValue = { ...source };
  let cursor: FormValue = clone;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const part = parts[index];
    const next = cursor[part];
    const copy = isRecord(next) ? { ...next } : {};
    cursor[part] = copy;
    cursor = copy;
  }
  const last = parts[parts.length - 1];
  if (value === undefined || value === '') delete cursor[last];
  else cursor[last] = value;
  return clone as T;
}

function flatten(fields: FieldSpec[], into: FieldSpec[] = []): FieldSpec[] {
  for (const field of fields) {
    if (field.kind === 'group') flatten(field.children, into);
    else into.push(field);
  }
  return into;
}

/* ------------------------------------------------------------------ JSONSchema */
function nullableInner(node: JsonSchemaNode): JsonSchemaNode {
  const variants = node.anyOf ?? node.oneOf;
  if (!variants || variants.length === 0) return node;
  const concrete = variants.filter((variant) => variant.type !== 'null');
  if (concrete.length >= 1) {
    const first = concrete[0];
    return {
      ...first,
      title: node.title ?? first.title,
      description: node.description ?? first.description,
      default: node.default ?? first.default,
      enum: concrete.length > 1 ? concrete.flatMap((variant) => variant.enum ?? []) : first.enum,
    };
  }
  return node;
}

function resolveRef(node: JsonSchemaNode, root: JsonSchemaNode): JsonSchemaNode {
  if (!node.$ref) return node;
  const name = node.$ref.split('/').pop() ?? '';
  const defs = root.$defs ?? root.definitions ?? {};
  return defs[name] ? { ...defs[name], title: node.title ?? defs[name].title } : node;
}

function jsonType(node: JsonSchemaNode): string {
  if (Array.isArray(node.type)) return node.type.find((value) => value !== 'null') ?? 'string';
  if (node.type) return node.type;
  if (node.enum) return 'enum';
  return 'string';
}

const UNIT_RE = /\((mm|m|px|s|ms|GB|gb|°|deg)\)/;
const UNIT_WORD_RE = /\b(mm|px|GB|deg)\b/;
const UNIT_SUFFIX: Array<[RegExp, string]> = [
  [/_mm$/, 'mm'],
  [/_px$/, 'px'],
  [/_gb$/, 'GB'],
  [/_mm_/, 'mm'],
];

/** 单位推断：优先括号里的单位，其次描述里的单位词，最后字段名后缀。全部来自后端 schema。 */
function inferUnit(key: string, description?: string): string | undefined {
  if (description) {
    const paren = description.match(UNIT_RE);
    if (paren) return paren[1];
    const word = description.match(UNIT_WORD_RE);
    if (word) return word[1];
  }
  for (const [pattern, unit] of UNIT_SUFFIX) {
    if (pattern.test(key)) return unit;
  }
  return undefined;
}

export interface SchemaToFieldsResult {
  fields: FieldSpec[];
  skipped: Array<{ path: string; reason: string }>;
}

/**
 * Pydantic v2 JSONSchema → FieldSpec[]。未覆盖的构造（`dict`、嵌套数组、联合类型）会进入
 * `skipped` 并在 UI 上显式列出，引导用户到高级 JSON 区，而不是静默丢字段。
 */
export function schemaToFields(
  schema: JsonSchemaNode,
  options: { prefix?: string; include?: string[]; skipKeys?: string[] } = {},
): SchemaToFieldsResult {
  const prefix = options.prefix ?? '';
  const skip = new Set(options.skipKeys ?? []);
  const fields: FieldSpec[] = [];
  const skipped: Array<{ path: string; reason: string }> = [];
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  for (const [key, rawNode] of Object.entries(properties)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (skip.has(key)) continue;
    if (options.include && !options.include.includes(key)) continue;
    const node = resolveRef(nullableInner(rawNode), schema);
    const label = node.title ?? key;
    const unit = inferUnit(key, node.description);
    const nullable = (rawNode.anyOf ?? rawNode.oneOf ?? []).some((variant) => variant.type === 'null');

    if (node.enum && node.enum.length > 0) {
      fields.push({
        kind: 'string',
        path,
        label,
        unit,
        hint: node.description,
        enumValues: node.enum.map((value) => String(value)),
        required: required.has(key) && !nullable,
      });
      continue;
    }

    switch (jsonType(node)) {
      case 'integer':
      case 'number':
        fields.push({
          kind: 'number',
          path,
          label,
          unit,
          hint: node.description,
          integer: jsonType(node) === 'integer',
          min: asNumber(node.minimum) ?? undefined,
          max: asNumber(node.maximum) ?? undefined,
          step: jsonType(node) === 'integer' ? 1 : undefined,
          required: required.has(key) && !nullable,
        });
        break;
      case 'boolean':
        fields.push({ kind: 'boolean', path, label, hint: node.description });
        break;
      case 'array': {
        const items = resolveRef(node.items ?? {}, schema);
        const itemType = jsonType(items);
        if (itemType === 'string' || itemType === 'integer' || itemType === 'number') {
          fields.push({ kind: 'stringList', path, label, hint: node.description, required: required.has(key) });
        } else {
          skipped.push({
            path,
            reason: '数组元素不是标量（Pydantic tuple / 嵌套数组）：请在高级 JSON 区填写，例如 [8, 20]',
          });
        }
        break;
      }
      case 'object':
        skipped.push({ path, reason: '嵌套 object：未展开为表单控件，请在高级 JSON 区填写' });
        break;
      default:
        fields.push({
          kind: 'string',
          path,
          label,
          unit,
          hint: node.description,
          placeholder: node.format === 'date-time' ? 'ISO 8601' : undefined,
          required: required.has(key) && !nullable,
        });
    }
  }
  return { fields, skipped };
}

/* ------------------------------------------------------------------ 错误归并 */
export function groupIssues(issues: SpecValidationIssue[]): { byPath: Map<string, string[]>; rest: string[] } {
  const byPath = new Map<string, string[]>();
  const rest: string[] = [];
  for (const issue of issues) {
    const loc = asArray<string>(issue.loc).map((part) => String(part));
    const message = `${issue.type ?? 'error'}: ${issue.msg ?? ''}`;
    const cleaned = loc.filter((part) => !/^\d+$/.test(part));
    const path = cleaned.join('.');
    if (!path) {
      rest.push(message);
      continue;
    }
    const list = byPath.get(path) ?? [];
    list.push(message);
    byPath.set(path, list);
  }
  return { byPath, rest };
}

/* ------------------------------------------------------------------ 控件 */
interface ControlProps {
  field: Exclude<FieldSpec, { kind: 'group' }>;
  value: unknown;
  onChange: (path: string, value: unknown) => void;
  errors: string[];
  disabled?: boolean;
}

function Control({ field, value, onChange, errors, disabled }: ControlProps) {
  const errorNode =
    errors.length > 0 ? (
      <ul className="field__errors">
        {errors.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    ) : undefined;

  if (field.kind === 'boolean') {
    return (
      <Field label={field.label} hint={field.hint} error={errorNode}>
        {(id) => (
          <label className="switch" htmlFor={id}>
            <input
              id={id}
              type="checkbox"
              checked={value === true}
              disabled={disabled}
              onChange={(event) => onChange(field.path, event.target.checked)}
            />
            <span>{value === true ? '是' : '否'}</span>
          </label>
        )}
      </Field>
    );
  }

  if (field.kind === 'number') {
    return (
      <Field label={field.label} unit={field.unit} hint={field.hint} required={field.required} error={errorNode}>
        {(id) => (
          <input
            id={id}
            className="input"
            type="number"
            inputMode={field.integer ? 'numeric' : 'decimal'}
            value={asNumber(value) ?? ''}
            min={field.min}
            max={field.max}
            step={field.step ?? (field.integer ? 1 : 'any')}
            disabled={disabled}
            aria-invalid={errors.length > 0}
            onChange={(event) => {
              const raw = event.target.value;
              onChange(field.path, raw === '' ? undefined : Number(raw));
            }}
          />
        )}
      </Field>
    );
  }

  if (field.kind === 'numberTuple') {
    const current = asArray<unknown>(value);
    return (
      <Field label={field.label} unit={field.unit} hint={field.hint} error={errorNode}>
        {() => (
          <div className="tuple">
            {Array.from({ length: field.length }, (_, index) => (
              <input
                key={index}
                className="input input--tight"
                type="number"
                value={asNumber(current[index]) ?? ''}
                step={field.integer ? 1 : 'any'}
                disabled={disabled}
                aria-label={`${field.label} 第 ${index + 1} 项`}
                onChange={(event) => {
                  const next: Array<number | undefined> = Array.from({ length: field.length }, (__, position) => {
                    if (position === index) {
                      return event.target.value === '' ? undefined : Number(event.target.value);
                    }
                    return asNumber(current[position]) ?? undefined;
                  });
                  onChange(field.path, next.some((item) => item === undefined) ? undefined : next);
                }}
              />
            ))}
          </div>
        )}
      </Field>
    );
  }

  if (field.kind === 'stringList') {
    const current = asArray<unknown>(value).map((item) => String(item));
    return (
      <Field
        label={field.label}
        hint={field.hint ?? '多个值用英文逗号或换行分隔；ID 是否合法由后端 registry 校验'}
        required={field.required}
        error={errorNode}
      >
        {(id) => (
          <textarea
            id={id}
            className="input input--area"
            rows={2}
            value={current.join(', ')}
            placeholder={field.placeholder}
            disabled={disabled}
            aria-invalid={errors.length > 0}
            onChange={(event) => {
              const parts = event.target.value
                .split(/[\n,]/)
                .map((part) => part.trim())
                .filter(Boolean);
              onChange(field.path, parts.length > 0 ? parts : undefined);
            }}
          />
        )}
      </Field>
    );
  }

  const stringValue = asString(value) ?? '';
  return (
    <Field label={field.label} unit={field.unit} hint={field.hint} required={field.required} error={errorNode}>
      {(id) =>
        field.enumValues && field.enumValues.length > 0 ? (
          <select
            id={id}
            className="input"
            value={stringValue}
            disabled={disabled}
            aria-invalid={errors.length > 0}
            onChange={(event) => onChange(field.path, event.target.value === '' ? undefined : event.target.value)}
          >
            <option value="">（不设置 / 使用后端默认）</option>
            {field.enumValues.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={id}
            className="input"
            type="text"
            value={stringValue}
            placeholder={field.placeholder}
            disabled={disabled}
            aria-invalid={errors.length > 0}
            onChange={(event) => onChange(field.path, event.target.value === '' ? undefined : event.target.value)}
          />
        )
      }
    </Field>
  );
}

/** 高级 JSON 文本编辑器状态：非法文本不会被解析回对象，错误就地提示。 */
function useAdvancedJson(value: FormValue, onChange: (next: FormValue) => void, enabled: boolean) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!enabled || dirty) return;
    setText(JSON.stringify(value, null, 2));
  }, [value, dirty, enabled]);

  const apply = (next: string) => {
    setText(next);
    setDirty(true);
    try {
      const parsed: unknown = JSON.parse(next);
      if (!isRecord(parsed)) {
        setError('spec 必须是 JSON 对象');
        return;
      }
      setError(null);
      onChange(parsed);
    } catch (caught) {
      setError(`JSON 解析失败：${(caught as Error).message}`);
    }
  };

  const format = () => {
    try {
      setText(JSON.stringify(JSON.parse(text), null, 2));
      setError(null);
    } catch (caught) {
      setError(`JSON 解析失败：${(caught as Error).message}`);
    }
  };

  const reset = () => {
    setDirty(false);
    setError(null);
    setText(JSON.stringify(value, null, 2));
  };

  return { text, error, apply, format, reset };
}

export interface SchemaFormProps {
  /** 显式字段描述（与 registry schema 可同时使用）。 */
  fields?: FieldSpec[];
  /** 后端 registry 返回的 JSONSchema；提供时追加一组由 schema 生成的字段。 */
  jsonSchema?: JsonSchemaNode;
  schemaPrefix?: string;
  schemaInclude?: string[];
  value: FormValue;
  onChange: (next: FormValue) => void;
  /** `POST /specs/validate` 返回的 errors，按 loc 落到字段上。 */
  issues?: SpecValidationIssue[];
  disabled?: boolean;
  advanced?: boolean;
  label?: string;
}

export function SchemaForm({
  fields = [],
  jsonSchema,
  schemaPrefix,
  schemaInclude,
  value,
  onChange,
  issues = [],
  disabled,
  advanced = true,
  label = '参数表单',
}: SchemaFormProps) {
  const advancedId = useId();
  const derived = useMemo(
    () => (jsonSchema ? schemaToFields(jsonSchema, { prefix: schemaPrefix, include: schemaInclude }) : { fields: [], skipped: [] }),
    [jsonSchema, schemaPrefix, schemaInclude],
  );
  const allFields = useMemo(() => [...fields, ...derived.fields], [fields, derived.fields]);
  const flat = useMemo(() => flatten(allFields), [allFields]);
  const grouped = useMemo(() => groupIssues(issues), [issues]);
  const advancedState = useAdvancedJson(value, onChange, advanced);

  const handleChange = (path: string, next: unknown) => onChange(setPath(value, path, next));

  const renderField = (field: FieldSpec, key: string) => {
    if (field.kind === 'group') {
      return (
        <fieldset className="formgroup" key={key}>
          <legend>{field.label}</legend>
          {field.hint ? <p className="formgroup__hint">{field.hint}</p> : null}
          <div className="formgrid">{field.children.map((child, index) => renderField(child, `${key}-${index}`))}</div>
        </fieldset>
      );
    }
    return (
      <Control
        key={key}
        field={field}
        value={getPath(value, field.path)}
        onChange={handleChange}
        errors={grouped.byPath.get(field.path) ?? []}
        disabled={disabled}
      />
    );
  };

  return (
    <div className="schemaform" aria-label={label}>
      <div className="schemaform__body">
        {allFields.length === 0 ? (
          <p className="muted">
            没有可生成的表单字段：registry 为空且本页未声明显式字段。请在高级 JSON 区直接编辑 spec，
            或先让实现模块注册到 <code className="mono">/registry/&lt;kind&gt;</code>。
          </p>
        ) : (
          allFields.map((field, index) => renderField(field, `f${index}`))
        )}
      </div>

      {grouped.rest.length > 0 ? (
        <div className="schemaform__issues" role="alert">
          <strong>后端未定位到具体字段的错误：</strong>
          <ul>
            {grouped.rest.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {derived.skipped.length > 0 ? (
        <div className="schemaform__issues schemaform__issues--info">
          <strong>未生成控件的 schema 构造（请在高级 JSON 区填写）：</strong>
          <ul>
            {derived.skipped.map((item) => (
              <li key={item.path}>
                <code className="mono">{item.path}</code>：{item.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {advanced ? (
        <details className="schemaform__advanced">
          <summary>高级：直接编辑 spec JSON（字段名与后端 extra=&quot;forbid&quot; 模型一致）</summary>
          <label className="visually-hidden" htmlFor={advancedId}>
            spec JSON
          </label>
          <textarea
            id={advancedId}
            className="input input--code"
            rows={12}
            spellCheck={false}
            value={advancedState.text}
            disabled={disabled}
            onChange={(event) => advancedState.apply(event.target.value)}
          />
          {advancedState.error ? (
            <div className="field__error" role="alert">
              {advancedState.error}
            </div>
          ) : null}
          <div className="row">
            <button type="button" className="btn btn--tiny" onClick={advancedState.format} disabled={disabled}>
              格式化
            </button>
            <button type="button" className="btn btn--tiny" onClick={advancedState.reset} disabled={disabled}>
              从对象重新载入
            </button>
            <span className="muted">顶层字段数：{Object.keys(value).length}</span>
          </div>
        </details>
      ) : null}

      <p className="muted schemaform__note">
        表单只产生草稿；合法性以 <code className="mono">POST /specs/validate</code> 与{' '}
        <code className="mono">POST /jobs</code> 的回答为准（本页原样展示后端 errors）。共 {flat.length} 个字段。
      </p>
    </div>
  );
}
