/**
 * 状态与布局原语。所有页面共用同一套“加载 / 空 / 错误 / 阻塞 / 断线”表达，
 * 并且**必须**能显示后端返回的具体错误码与 request_id（计划 20.15）。
 */

import { useEffect, useId, useRef, type ReactNode } from 'react';

import { describeError } from '../api/client';
import type { Tone } from '../lib/format';

/** fixture 横幅文案（常驻 UI 标签，本身不含任何数据）。 */
export const FIXTURE_BANNER_TEXT = 'FIXTURE 模式：以下内容来自本地测试 fixture，不是真实后端响应';

export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner" role="status" aria-live="polite">
      <span className="spinner__dot" aria-hidden="true" />
      {label ?? '加载中…'}
    </span>
  );
}

export function LoadingState({ label, detail }: { label?: string; detail?: ReactNode }) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <Spinner label={label} />
      {detail ? <div className="state__detail">{detail}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  reason,
  action,
}: {
  title: string;
  reason?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state state--empty" role="status">
      <div className="state__title">{title}</div>
      {reason ? <div className="state__detail">{reason}</div> : null}
      {action ? <div className="state__action">{action}</div> : null}
    </div>
  );
}

/**
 * 后端错误卡片：显示 code / HTTP 状态 / stage / message / request_id，并允许展开 details。
 * 后端不可达时显示请求地址与原因，提示如何启动后端。
 */
export function ErrorState({
  error,
  onRetry,
  compact,
  title,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
  title?: string;
}) {
  const info = describeError(error);
  const connectivity = info.kind === 'network' || info.kind === 'unreachable';
  const isNetwork = connectivity;
  return (
    <div className={`state state--error${compact ? ' state--compact' : ''}`} role="alert">
      <div className="state__title">
        {title ?? info.title}
        <Badge tone={isNetwork ? 'warn' : 'bad'}>{info.code}</Badge>
        {info.retryable ? <Badge tone="info">后端标记可重试</Badge> : null}
      </div>
      <div className="state__detail">{info.message}</div>
      <div className="state__meta mono">{info.diagnostics}</div>
      {isNetwork ? (
        <div className="state__detail">
          请确认后端已启动：<code>python tests/a12/api_ui/_serve.py --store-root data/a12 --port 8077</code>
          （前端通过 <code>/api</code> 反代访问；如需直连请设置 <code>VITE_SYNLAB_API_BASE</code>）。
        </div>
      ) : null}
      {info.details && Object.keys(info.details).length > 0 ? (
        <details className="state__details">
          <summary>后端 details（原样展示）</summary>
          <pre className="mono pre">{JSON.stringify(info.details, null, 2)}</pre>
        </details>
      ) : null}
      {onRetry ? (
        <div className="state__action">
          <button type="button" className="btn" onClick={onRetry}>
            重试
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** 能力缺失 / 前端未实现导致的阻塞：与错误区分，因为它不是“坏了”，而是“做不了且有原因”。 */
export function BlockedState({
  title,
  code,
  reason,
  action,
  items,
}: {
  title: string;
  code?: string;
  reason: ReactNode;
  action?: ReactNode;
  items?: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <div className="state state--blocked" role="status">
      <div className="state__title">
        {title}
        {code ? <Badge tone="warn">{code}</Badge> : null}
      </div>
      <div className="state__detail">{reason}</div>
      {items && items.length > 0 ? (
        <dl className="kv kv--tight">
          {items.map((item) => (
            <div className="kv__row" key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {action ? <div className="state__action">{action}</div> : null}
    </div>
  );
}

export function FixtureBanner({ enabled }: { enabled: boolean }) {
  if (!enabled) return null;
  return (
    <div className="banner banner--fixture" role="alert">
      {FIXTURE_BANNER_TEXT}（VITE_SYNLAB_FIXTURES=1）
    </div>
  );
}

export function SectionCard({
  title,
  subtitle,
  actions,
  children,
  anchor,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  anchor?: string;
}) {
  return (
    <section className="card" id={anchor} aria-label={typeof title === 'string' ? title : undefined}>
      <header className="card__head">
        <div>
          <h2 className="card__title">{title}</h2>
          {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="card__actions">{actions}</div> : null}
      </header>
      <div className="card__body">{children}</div>
    </section>
  );
}

export interface FieldProps {
  label: string;
  hint?: ReactNode;
  unit?: string;
  required?: boolean;
  error?: ReactNode;
  children: (id: string) => ReactNode;
}

/** 标签 + 单位 + 错误提示统一布局；`children` 拿到 id 以便 label/aria 关联。 */
export function Field({ label, hint, unit, required, error, children }: FieldProps) {
  const id = useId();
  return (
    <div className={`field${error ? ' field--invalid' : ''}`}>
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
        {unit ? <span className="field__unit">（{unit}）</span> : null}
      </label>
      {children(id)}
      {hint ? <div className="field__hint">{hint}</div> : null}
      {error ? (
        <div className="field__error" role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}

/** 带禁用原因的按钮：`disabledReason` 存在时不可点，并把原因显示在 title 与页面上。 */
export function ActionButton({
  children,
  onClick,
  disabledReason,
  tone = 'default',
  busy,
  type = 'button',
}: {
  children: ReactNode;
  onClick?: () => void;
  disabledReason?: string | null;
  tone?: 'default' | 'primary' | 'danger';
  busy?: boolean;
  type?: 'button' | 'submit';
}) {
  const disabled = Boolean(disabledReason) || Boolean(busy);
  return (
    <span className="actionwrap">
      <button
        type={type}
        className={`btn btn--${tone}`}
        onClick={disabled ? undefined : onClick}
        disabled={disabled}
        aria-disabled={disabled}
        title={disabledReason ?? undefined}
      >
        {busy ? <span className="spinner__dot" aria-hidden="true" /> : null}
        {children}
      </button>
      {disabledReason ? <span className="actionwrap__reason">不可用：{disabledReason}</span> : null}
    </span>
  );
}

export function KeyValueList({ rows }: { rows: Array<{ label: string; value: ReactNode; mono?: boolean }> }) {
  if (rows.length === 0) return <EmptyState title="没有可显示的字段" />;
  return (
    <dl className="kv">
      {rows.map((row) => (
        <div className="kv__row" key={row.label}>
          <dt>{row.label}</dt>
          <dd className={row.mono ? 'mono' : undefined}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CopyValue({ value, label }: { value: string; label?: string }) {
  return (
    <span className="copy">
      <code className="mono">{value}</code>
      <button
        type="button"
        className="btn btn--tiny"
        onClick={() => void navigator.clipboard?.writeText(value)}
        aria-label={`复制${label ?? ''}`}
      >
        复制
      </button>
    </span>
  );
}

/** 右侧/底部抽屉；ESC 关闭，焦点进入抽屉，符合键盘可访问性。 */
export function Drawer({
  open,
  title,
  onClose,
  children,
  side = 'right',
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  side?: 'right' | 'bottom';
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    ref.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <div
        className={`drawer drawer--${side}`}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : '详情'}
        tabIndex={-1}
        ref={ref}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer__head">
          <h3>{title}</h3>
          <button type="button" className="btn btn--tiny" onClick={onClose} aria-label="关闭抽屉">
            关闭 (Esc)
          </button>
        </header>
        <div className="drawer__body">{children}</div>
      </div>
    </div>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: Array<{ id: string; label: string; disabledReason?: string | null }>;
  active: string;
  onChange: (id: string) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tab) => {
        const disabled = Boolean(tab.disabledReason);
        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={active === tab.id}
            className={`tab${active === tab.id ? ' tab--active' : ''}`}
            onClick={disabled ? undefined : () => onChange(tab.id)}
            disabled={disabled}
            title={tab.disabledReason ?? undefined}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function PageHeader({
  title,
  plan,
  summary,
  actions,
}: {
  title: string;
  plan: string;
  summary: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="pagehead">
      <div>
        <h1>
          {title}
          <span className="pagehead__plan">{plan}</span>
        </h1>
        <p className="pagehead__summary">{summary}</p>
      </div>
      {actions ? <div className="pagehead__actions">{actions}</div> : null}
    </header>
  );
}
