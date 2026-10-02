/** 能力判定助手：把 `/capabilities` 的真实回答翻译成页面可显示的阻塞理由。 */

import type { CapabilitiesResponse, CapabilityProbe, EnvProbe } from '../api/types';

export interface CapabilityIssue {
  key: string;
  module: string;
  status: string;
  error: string | null;
  missingEntryPoints: string[];
  resolvedFrom: Record<string, string>;
}

export function probeFor(capabilities: CapabilitiesResponse | null, key: string): CapabilityProbe | null {
  if (!capabilities) return null;
  return capabilities.modules[key] ?? null;
}

/** 返回**不可用**的能力（可用则为空数组）。没有任何猜测：缺就是缺。 */
export function capabilityIssues(capabilities: CapabilitiesResponse | null, keys: string[]): CapabilityIssue[] {
  if (!capabilities) {
    return keys.map((key) => ({
      key,
      module: `（未知：/capabilities 尚未返回）`,
      status: 'UNKNOWN',
      error: '尚未取得能力探测结果',
      missingEntryPoints: [],
      resolvedFrom: {},
    }));
  }
  return keys
    .map((key) => capabilities.modules[key])
    .filter((probe): probe is CapabilityProbe => Boolean(probe) && !probe.available)
    .map((probe) => ({
      key: probe.key,
      module: probe.module,
      status: probe.status,
      error: probe.error,
      missingEntryPoints: probe.missing_entry_points ?? [],
      resolvedFrom: probe.resolved_from ?? {},
    }));
}

export function envProbe(capabilities: CapabilitiesResponse | null, key: string): EnvProbe | null {
  if (!capabilities?.env) return null;
  return capabilities.env[key] ?? null;
}

/** 汇总阻塞原因的一句话（用于 BlockedState 的 reason）。 */
export function describeIssues(issues: CapabilityIssue[]): string {
  if (issues.length === 0) return '';
  return issues
    .map((issue) => `${issue.key}（${issue.module}）= ${issue.status}：${issue.error ?? '后端未给出原因'}`)
    .join('；');
}

/**
 * 阶段要求的真实能力：优先用 `/capabilities.stage_requirements`（后端 STAGES 推导），
 * 缺失时回退到 `/stages` 里的 `capabilities` 字段。
 */
export function stageCapabilities(
  capabilities: CapabilitiesResponse | null,
  stage: string,
  fallback: string[] = [],
): string[] {
  const fromCaps = capabilities?.stage_requirements?.[stage];
  if (fromCaps && fromCaps.length > 0) return fromCaps;
  return fallback;
}
