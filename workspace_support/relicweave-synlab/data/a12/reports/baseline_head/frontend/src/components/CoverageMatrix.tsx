/**
 * CoverageMatrix —— 覆盖矩阵（计划 20.9 U08）。
 *
 * 数据来自真实的 `coverage_matrix`（`POST /audits` 执行后写在 audit.result.coverage，
 * 或 release manifest 的 coverage 字段）。结构固定为：
 * `{ scanned_assets, basis, coverage_24_vessels: {kind, declared_field, required, covered,
 *   complete, covered_ids, missing_ids, evidence} , ... }`。
 *
 * `covered` 与 `required` 都原样来自后端；缺失 ID 与证据资产 id 也来自后端，不由前端推算。
 */

import { isRecord } from '../lib/format';
import { Badge, EmptyState } from './states';
import type { CoverageBlock, CoverageMatrixPayload } from '../api/types';

export interface CoverageMatrixProps {
  coverage: CoverageMatrixPayload | Record<string, unknown> | null;
  title?: string;
  onSelectAsset?: (assetId: string) => void;
  emptyReason?: React.ReactNode;
}

const DIMENSION_LABELS: Record<string, string> = {
  coverage_24_vessels: '24 器物',
  coverage_12_materials: '12 材料',
  coverage_4_layers: '4 层组合',
  coverage_16_patterns: '16 纹样',
  coverage_4_backends: '4 断裂后端',
  coverage_31_axes: '31 退化轴',
};

export function isCoverageBlock(value: unknown): value is CoverageBlock {
  return (
    isRecord(value) &&
    typeof value.required === 'number' &&
    typeof value.covered === 'number' &&
    Array.isArray(value.missing_ids)
  );
}

export function CoverageMatrix({ coverage, title = '覆盖矩阵', onSelectAsset, emptyReason }: CoverageMatrixProps) {
  if (!coverage) {
    return <EmptyState title="没有覆盖矩阵" reason={emptyReason ?? '审计尚未运行，因此没有任何覆盖结论。'} />;
  }

  const blocks = Object.entries(coverage).filter(([, value]) => isCoverageBlock(value)) as Array<[string, CoverageBlock]>;
  const meta = Object.entries(coverage).filter(([, value]) => !isCoverageBlock(value));

  if (blocks.length === 0) {
    return (
      <EmptyState
        title="这份 coverage 里没有可识别的覆盖维度"
        reason={
          <>
            后端返回的键：
            <code className="mono">{Object.keys(coverage).join(', ') || '（空对象）'}</code>
            。覆盖维度由后端 <code className="mono">COVERAGE_SPECS</code> 决定，前端不自行推导。
          </>
        }
      />
    );
  }

  return (
    <div className="coverage">
      <div className="coverage__meta">
        {meta.map(([key, value]) => (
          <div key={key} className="coverage__metaItem">
            <span className="muted">{key}</span>
            <span className="mono">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
          </div>
        ))}
      </div>

      <table className="table table--coverage">
        <caption>{title}（required/covered 与缺失 ID 均来自后端响应）</caption>
        <thead>
          <tr>
            <th scope="col">维度</th>
            <th scope="col">声明字段</th>
            <th scope="col">已覆盖 / 需要</th>
            <th scope="col">完成</th>
            <th scope="col">缺失 ID</th>
            <th scope="col">证据资产</th>
          </tr>
        </thead>
        <tbody>
          {blocks.map(([key, block]) => (
            <tr key={key}>
              <th scope="row">
                {DIMENSION_LABELS[key] ?? key}
                <div className="muted small mono">{block.kind}</div>
              </th>
              <td className="mono">{block.declared_field}</td>
              <td className="mono">
                {block.covered} / {block.required}
              </td>
              <td>
                <Badge tone={block.complete ? 'ok' : 'bad'}>{block.complete ? '完整' : '不完整'}</Badge>
              </td>
              <td className="mono small">{block.missing_ids.length > 0 ? block.missing_ids.join(', ') : '无'}</td>
              <td className="small">
                {Object.keys(block.evidence).length === 0
                  ? '无'
                  : Object.entries(block.evidence).map(([id, assetId]) => (
                      <div key={id}>
                        <span className="mono">{id}</span> →{' '}
                        {onSelectAsset ? (
                          <button type="button" className="linky" onClick={() => onSelectAsset(assetId)}>
                            {assetId}
                          </button>
                        ) : (
                          <span className="mono">{assetId}</span>
                        )}
                      </div>
                    ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <details className="coverage__raw">
        <summary>原始 coverage JSON（后端原样返回）</summary>
        <pre className="mono pre">{JSON.stringify(coverage, null, 2)}</pre>
      </details>
    </div>
  );
}
