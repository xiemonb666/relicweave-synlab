/**
 * 跨页共享的界面状态：当前 run、选中的展示资产、抽屉目标。
 *
 * 注意：这里**只放 UI 选择**，不放任何数据副本。所有数据仍然由各页面通过真实 API 拉取，
 * 所以刷新后状态与后端一致（计划 20.2 验收）。
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import type { ProvenanceTarget } from '../components/ProvenanceDrawer';

export interface AppStateValue {
  selectedRunId: string | null;
  setSelectedRunId: (runId: string | null) => void;
  /** 展示 LOD 资产选择（用于三维/比较视口）。 */
  selectedDisplayAssets: string[];
  setSelectedDisplayAssets: (ids: string[]) => void;
  provenance: ProvenanceTarget;
  openProvenance: (target: ProvenanceTarget) => void;
  closeProvenance: () => void;
  failureJobId: string | null;
  openFailure: (jobId: string | null) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedDisplayAssets, setSelectedDisplayAssets] = useState<string[]>([]);
  const [provenance, setProvenance] = useState<ProvenanceTarget>(null);
  const [failureJobId, setFailureJobId] = useState<string | null>(null);

  const openProvenance = useCallback((target: ProvenanceTarget) => setProvenance(target), []);
  const closeProvenance = useCallback(() => setProvenance(null), []);

  const value = useMemo<AppStateValue>(
    () => ({
      selectedRunId,
      setSelectedRunId,
      selectedDisplayAssets,
      setSelectedDisplayAssets,
      provenance,
      openProvenance,
      closeProvenance,
      failureJobId,
      openFailure: setFailureJobId,
    }),
    [selectedRunId, selectedDisplayAssets, provenance, openProvenance, closeProvenance, failureJobId],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateValue {
  const value = useContext(AppStateContext);
  if (!value) throw new Error('useAppState 必须在 AppStateProvider 内使用');
  return value;
}
