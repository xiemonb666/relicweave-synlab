/** 展示层格式化助手。所有数值都必须能追到真实来源；缺失一律显示“未提供”，不写 0。 */

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) return Number(value);
  return null;
}

export function asString(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

export function formatNumber(value: unknown, digits = 2): string {
  const number = asNumber(value);
  if (number === null) return '未提供';
  if (Number.isInteger(number) && digits <= 2) return String(number);
  return number.toFixed(digits);
}

export function formatBytes(value: unknown): string {
  const number = asNumber(value);
  if (number === null) return '未提供';
  if (number < 1024) return `${number} B`;
  if (number < 1024 ** 2) return `${(number / 1024).toFixed(1)} KiB`;
  if (number < 1024 ** 3) return `${(number / 1024 ** 2).toFixed(1)} MiB`;
  return `${(number / 1024 ** 3).toFixed(2)} GiB`;
}

export function formatGb(value: unknown, digits = 2): string {
  const number = asNumber(value);
  return number === null ? '未提供' : `${number.toFixed(digits)} GB`;
}

export function formatMs(value: unknown): string {
  const number = asNumber(value);
  if (number === null) return '未提供';
  if (number < 1000) return `${number.toFixed(0)} ms`;
  if (number < 60_000) return `${(number / 1000).toFixed(1)} s`;
  if (number < 3_600_000) return `${(number / 60_000).toFixed(1)} min`;
  return `${(number / 3_600_000).toFixed(2)} h`;
}

export function formatSeconds(value: unknown): string {
  return formatMs(asNumber(value) === null ? null : Number(value) * 1000);
}

export function formatTimestamp(value: unknown): string {
  const number = asNumber(value);
  if (number === null || number <= 0) return '未提供';
  const date = new Date(number * 1000);
  if (Number.isNaN(date.getTime())) return '未提供';
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function formatRelative(value: unknown, now = Date.now()): string {
  const number = asNumber(value);
  if (number === null || number <= 0) return '未提供';
  const delta = now / 1000 - number;
  if (delta < 0) return `未来 ${Math.abs(delta).toFixed(0)} s`;
  if (delta < 60) return `${delta.toFixed(0)} s 前`;
  if (delta < 3600) return `${(delta / 60).toFixed(1)} min 前`;
  if (delta < 86_400) return `${(delta / 3600).toFixed(1)} h 前`;
  return `${(delta / 86_400).toFixed(1)} d 前`;
}

export function truncate(value: string, length = 16): string {
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}

/** 任务状态 → 中文标签与语义色（颜色之外同时有文字，不依赖颜色单独传达信息）。 */
export function jobStateLabel(state: string): { label: string; tone: Tone } {
  const table: Record<string, { label: string; tone: Tone }> = {
    PENDING: { label: '待运行', tone: 'neutral' },
    RUNNING: { label: '运行中', tone: 'info' },
    OUTPUT_READY: { label: '产出就绪', tone: 'info' },
    QA_PASS: { label: 'QA 通过', tone: 'ok' },
    COMMITTED: { label: '已提交', tone: 'ok' },
    RETRYABLE: { label: '可重试失败', tone: 'warn' },
    QUARANTINED: { label: '已隔离', tone: 'warn' },
    FAILED: { label: '失败', tone: 'bad' },
    CANCELLED: { label: '已取消', tone: 'neutral' },
    BLOCKED: { label: '被依赖阻塞', tone: 'warn' },
  };
  return table[state] ?? { label: state, tone: 'neutral' };
}

export function qaLabel(status: string): { label: string; tone: Tone } {
  const table: Record<string, { label: string; tone: Tone }> = {
    QA_PASS: { label: 'QA 通过', tone: 'ok' },
    QA_PENDING: { label: 'QA 待定', tone: 'warn' },
    QA_FAIL: { label: 'QA 失败', tone: 'bad' },
  };
  return table[status] ?? { label: status, tone: 'neutral' };
}

export function runStatusLabel(status: string | null | undefined): { label: string; tone: Tone } {
  const table: Record<string, { label: string; tone: Tone }> = {
    ACCEPTED: { label: '已受理', tone: 'info' },
    RUNNING: { label: '运行中', tone: 'info' },
    PAUSED: { label: '已暂停', tone: 'warn' },
    CANCELLED: { label: '已取消', tone: 'neutral' },
    COMPLETED: { label: '已完成', tone: 'ok' },
    FAILED: { label: '失败', tone: 'bad' },
  };
  if (!status) return { label: '未知（后端未返回 run 状态）', tone: 'neutral' };
  return table[status] ?? { label: status, tone: 'neutral' };
}

export function gateTone(status: string): Tone {
  if (status === 'PASS') return 'ok';
  if (status === 'FAIL') return 'bad';
  if (status === 'NA') return 'neutral';
  return 'warn';
}

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral';

export function gateLabel(status: string): string {
  const table: Record<string, string> = {
    PASS: 'PASS 通过',
    FAIL: 'FAIL 未通过',
    PENDING: 'PENDING 未证明',
    NA: 'NA 不适用',
  };
  return table[status] ?? status;
}

/** 把任意值安全地格式化为可读文本（用于详情抽屉里的原始证据）。 */
export function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
