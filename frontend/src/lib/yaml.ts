/**
 * spec → YAML 导出（浏览器侧，纯字符串处理）。
 *
 * 为什么前端自己写一个：仓库的 `synlab.config` 是 Python 侧编译器，前端没有 YAML 依赖；
 * 而向导要求“生成的配置能导出 YAML 并显示 spec_hash”。因此这里只做一件窄事：
 * 把**真实校验通过的 spec 对象**序列化成合法 YAML 子集（映射/序列/标量），
 * 不做任何字段补全、不做默认值注入 —— 导出的就是屏幕上那份、后端校验过的那份。
 *
 * 同时提供 `canonicalJson` / `specFingerprint`：与后端 `synlab.canonical.canonical_json`
 * 用同一套规则（键排序、紧凑分隔符、UTF-8），因此前端算出的指纹可以直接和
 * `POST /specs/validate` 返回的 `spec_hash` 对照；两者不一致时页面会同时显示两个值。
 */

import type { JsonObject } from '../api/types';

export function isPlainObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (isPlainObject(value)) {
    const out: JsonObject = {};
    for (const key of Object.keys(value).sort()) out[key] = sortKeys(value[key]);
    return out;
  }
  return value;
}

/** 与后端 `canonical_json` 同规则：sort_keys=True, separators=(",", ":"), UTF-8。 */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * `sha256:<hex>`（后端 `hash_json` 的规则）。浏览器没有 `crypto.subtle` 时返回 null，
 * 页面显示“本机无法计算”而不是编一个值。
 */
export async function specFingerprint(value: unknown): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) return null;
  try {
    const bytes = new TextEncoder().encode(canonicalJson(value));
    const digest = await subtle.digest('SHA-256', bytes);
    return `sha256:${hex(digest)}`;
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ YAML 序列化 */

const PLAIN_STRING = /^[A-Za-z_][A-Za-z0-9_\-./]*$/;
const KEY_LIKE = /^(true|false|null|yes|no|on|off|~|-?\d+(\.\d+)?([eE][-+]?\d+)?)$/i;

function quote(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

function scalar(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return quote(String(value));
    return String(value);
  }
  if (typeof value === 'string') {
    if (value === '') return "''";
    if (PLAIN_STRING.test(value) && !KEY_LIKE.test(value)) return value;
    return quote(value);
  }
  return quote(String(value));
}

function isScalar(value: unknown): boolean {
  return value === null || value === undefined || ['string', 'number', 'boolean'].includes(typeof value);
}

function render(value: unknown, indent: number): string[] {
  const pad = ' '.repeat(indent);
  if (Array.isArray(value)) {
    if (value.length === 0) return [`${pad}[]`];
    const lines: string[] = [];
    for (const item of value) {
      if (isScalar(item)) {
        lines.push(`${pad}- ${scalar(item)}`);
        continue;
      }
      const nested = render(item, indent + 2);
      // 序列项是映射/序列时，把第一个缩进行提到 "- " 同一行，保持 YAML 合法且好读。
      const head = nested[0].slice(indent + 2);
      lines.push(`${pad}- ${head}`);
      lines.push(...nested.slice(1));
    }
    return lines;
  }
  if (isPlainObject(value)) {
    const keys = Object.keys(value);
    if (keys.length === 0) return [`${pad}{}`];
    const lines: string[] = [];
    for (const key of keys) {
      const item = value[key];
      const renderedKey = PLAIN_STRING.test(key) && !KEY_LIKE.test(key) ? key : quote(key);
      if (isScalar(item)) {
        lines.push(`${pad}${renderedKey}: ${scalar(item)}`);
        continue;
      }
      const nestedEmpty = Array.isArray(item) ? item.length === 0 : Object.keys(item as JsonObject).length === 0;
      if (nestedEmpty) {
        lines.push(`${pad}${renderedKey}: ${Array.isArray(item) ? '[]' : '{}'}`);
        continue;
      }
      lines.push(`${pad}${renderedKey}:`);
      lines.push(...render(item, indent + 2));
    }
    return lines;
  }
  return [`${pad}${scalar(value)}`];
}

/** 对象 → YAML 文档（不带 `---`，末尾带换行）。 */
export function toYaml(value: unknown): string {
  return `${render(value, 0).join('\n')}\n`;
}

/** 对象 → 合法的 `<name>.yaml`（用于 Blob / 下载属性）。 */
export function yamlFilename(prefix: string, hash: string | null): string {
  const tail = (hash ?? 'unvalidated').replace(/^sha256:/, '').slice(0, 12) || 'unvalidated';
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  return `${prefix}_${tail}_${stamp}.yaml`;
}
