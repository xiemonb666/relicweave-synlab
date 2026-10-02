/**
 * U14 合成向导 `/synlab/synthesis`。
 *
 * 一条自然流程走完六步，每一步都只读**真实**后端：
 *
 * | 步骤 | 真实数据源 |
 * |---|---|
 * | ① 器型 / 材料 / 花纹族 / 层组合 | `GET /registry/{vessel,material,pattern,layer_combo}` |
 * | ② 断裂参数 | `GET /registry/fracture_backend`（含每个后端真实 status）+ `GET /capabilities` |
 * | ③ 退化（轴分组 6 阶段、多选轴 + 档位 0–4） | `GET /registry/axis`（31 轴真实清单） |
 * | ④ 观测（路线 / 视角数 / 长边 px / 渲染后端） | `synlab/schemas/spec.py::ObservationConfig` 的真实枚举 + 环境探测 |
 * | ⑤ 预览（真实跑一条谱系） | `POST /synthesis/chain-preview`（mode=pipeline，真实资产 + 真实阶段耗时） |
 * | ⑥ 入队批量 | `POST /synthesis/batch-plan` → `POST /jobs`（含 `--resume` 语义） |
 *
 * 诚实规则：
 * * 下拉选项**只**来自 registry / capabilities 的真实响应；registry 为空时下拉为空并说明原因，
 *   绝不写死 24 器型 / 12 材料 / 16 花纹；
 * * 渲染后端 `blender` 在 `env.blender_bpy != OK` 时按真实探测结果标注为不可用；
 * * ⑤ 步的真实结果是后端跑出来的资产与阶段耗时；失败时显示后端 code + 复现命令；
 * * 导出的 YAML 就是屏幕上这份 spec，`spec_hash` 来自 `POST /specs/validate`。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { postBatchPlan, postChainPreview, postJobs, validateSpec } from '../api/endpoints';
import { getCapabilities, getRegistry, listJobs } from '../api/endpoints';
import { newIdempotencyKey, useResource, useRunEventStream } from '../api/hooks';
import type {
  BatchPlanResponse,
  ChainPreviewResponse,
  JobAcceptedResponse,
  JobRecord,
  RegistryResponse,
  SpecValidationResponse,
  SynthesisInventoryResponse,
} from '../api/types';
import { getSynthesisInventory } from '../api/endpoints';
import { FailureCard, RunningCard, failureFromError, type FailureInfo } from '../components/AsyncOperation';
import {
  ActionButton,
  Badge,
  BlockedState,
  CopyValue,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import { formatBytes, formatNumber, jobStateLabel, pretty, truncate } from '../lib/format';
import { toYaml, yamlFilename, specFingerprint } from '../lib/yaml';
import { useAppState } from '../state/app-state';

/* ------------------------------------------------------------------ 常量（来自真实 schema） */

/** `synlab/schemas/spec.py::ObservationRoute`。 */
const ROUTES = [
  { value: 'ideal_visible', label: 'ideal_visible（理想可见性，真值侧）' },
  { value: 'proxy_scan', label: 'proxy_scan（代理扫描，SENSOR_PROXY）' },
  { value: 'photo_mvs', label: 'photo_mvs（照片 MVS 重建）' },
] as const;

/** `synlab/schemas/spec.py::InputProfile`。 */
const INPUT_PROFILES = ['PHONE_RGB', 'SENSOR_PROXY', 'SENSOR_UPPER_BOUND'] as const;

/** `synlab/schemas/spec.py::ObservationConfig.renderer` 的真实取值。 */
const RENDERERS = [
  { value: 'auto', label: 'auto（后端自选）', env: null },
  { value: 'software_rasterizer', label: 'software_rasterizer（CPU 光栅）', env: null },
  { value: 'blender', label: 'blender（bpy 渲染）', env: 'blender_bpy' },
] as const;

/** `synlab/schemas/spec.py::ReleaseProfile`。 */
const RELEASE_PROFILES = [
  'SANDBOX_CORE', 'PILOT', 'CORE_COVERAGE', 'SCALE_10K', 'SCALE_50K', 'SCALE_100K',
  'CALIBRATED_PHONE', 'RESEARCH_EVIDENCE',
] as const;

/** ③ 步的「6 阶段」：`synlab/schemas/spec.py::STAGE_ORDER` 里的真实阶段（MATERIAL/PHYSICAL 同级）。 */
const OPERATOR_STAGES = [
  { stage: 'PHYSICAL', label: 'P0 PHYSICAL / MATERIAL（物理损伤、材料）' },
  { stage: 'SCENE', label: '1 SCENE（场景）' },
  { stage: 'OPTICS', label: '2 OPTICS（光学）' },
  { stage: 'SENSOR', label: '3 SENSOR / ISP（传感器与成像链）' },
  { stage: 'GEOMETRY_OBS', label: '7 GEOMETRY_OBS（观测重建）' },
  { stage: 'FEATURE_PROTOCOL', label: '8 FEATURE_PROTOCOL（特征协议）' },
] as const;

/** 轴的真实阶段归属来自 registry 的 `applicable`；缺失时按前缀给出**可核对**的默认分组。 */
const STAGE_BY_PREFIX: Record<string, string> = {
  P: 'PHYSICAL', I: 'OPTICS', G: 'GEOMETRY_OBS', X: 'FEATURE_PROTOCOL',
};

const LEVELS = [0, 1, 2, 3, 4] as const;

/* ------------------------------------------------------------------ 表单模型 */

export interface WizardOperator {
  axis_id: string;
  stage: string;
  level: number;
  variant: string;
}

export interface WizardState {
  vessels: string[];
  materials: string[];
  patterns: string[];
  layers: string[];
  targetMothers: number;
  fragmentsEstimate: number;
  masterSeed: number;
  releaseProfile: string;
  experimentPurpose: string;
  fractureBackend: string;
  pieceLo: number;
  pieceHi: number;
  minFeatureWavelengthMm: number;
  sharedSurfaceMaxErrorMm: number;
  maxAttempts: number;
  operators: WizardOperator[];
  basisPolicy: string;
  sourceRole: string;
  inputProfile: string;
  route: string;
  viewsPerFragment: number;
  imageLongEdgePx: number;
  renderer: string;
  cameraProfileRef: string;
  batchSize: number;
  resume: boolean;
}

const INITIAL: WizardState = {
  vessels: ['V01'],
  materials: ['M01'],
  patterns: ['PAT01'],
  layers: [],
  targetMothers: 1,
  fragmentsEstimate: 8,
  masterSeed: 20261001,
  releaseProfile: 'SANDBOX_CORE',
  experimentPurpose: 'DEVELOPMENT',
  fractureBackend: 'plane_shared_cut',
  pieceLo: 4,
  pieceHi: 12,
  minFeatureWavelengthMm: 0.24,
  sharedSurfaceMaxErrorMm: 0.01,
  maxAttempts: 3,
  operators: [],
  basisPolicy: 'paired_across_levels',
  sourceRole: 'clean',
  inputProfile: 'SENSOR_PROXY',
  route: 'proxy_scan',
  viewsPerFragment: 2,
  imageLongEdgePx: 256,
  renderer: 'software_rasterizer',
  cameraProfileRef: '',
  batchSize: 4,
  resume: true,
};

/** 退化算子 → 真实 `DegradationRecipeSpec`（`/specs/validate` 的 `kind="recipe"`）。 */
export function buildRecipeSpec(state: WizardState): Record<string, unknown> {
  return {
    schema: 'synlab.v3',
    recipe_id: `recipe_wizard_${state.operators.map((op) => `${op.axis_id}L${op.level}`).join('_') || 'empty'}`,
    basis_policy: state.basisPolicy,
    source_role: state.sourceRole,
    operators: state.operators.map((op) => ({
      axis_id: op.axis_id,
      stage: op.stage,
      level: op.level,
      variant: op.variant,
      parameters: {},
    })),
  };
}

/** 表单 → 真实 `synlab.v3` spec（只写 schema 里存在的字段）。 */
export function buildSpec(state: WizardState, options: { lineage: boolean }): Record<string, unknown> {
  const spec: Record<string, unknown> = {
    schema: 'synlab.v3',
    data_scope: 'SYNTHETIC',
    release_profile: state.releaseProfile,
    experiment_purpose: state.experimentPurpose,
    master_seed: state.masterSeed,
    dataset: {
      target_mothers: options.lineage ? 1 : Math.max(1, state.targetMothers),
      target_fragments_estimate: Math.max(1, state.fragmentsEstimate),
      split_before_generation: true,
      vessel_ids: state.vessels,
      material_ids: state.materials,
      pattern_ids: state.patterns,
      layer_combo_ids: state.layers,
    },
    fracture: {
      backend: state.fractureBackend,
      target_piece_range: [state.pieceLo, state.pieceHi],
      min_feature_wavelength_mm: state.minFeatureWavelengthMm,
      shared_surface_max_error_mm: state.sharedSurfaceMaxErrorMm,
      max_attempts: Math.max(1, state.maxAttempts),
    },
    observation: {
      input_profile: state.inputProfile,
      routes: [state.route],
      views_per_fragment: Math.max(1, state.viewsPerFragment),
      image_long_edge_px: Math.max(32, state.imageLongEdgePx),
      renderer: state.renderer,
    },
  };
  if (state.cameraProfileRef) {
    (spec.observation as Record<string, unknown>).camera_profile_ref = state.cameraProfileRef;
  }
  if (state.operators.length > 0) {
    // 退化进入生成 spec 的真实通道只有 `degraded_recipe_refs`（recipe_id 列表）。
    // `GenerationSpec` 是 extra=forbid，所以这里**只**写这个字段；算子本体作为独立 recipe
    // 由 `POST /specs/validate(kind=recipe)` 真实编译（返回 nodes），见 ③ 步的校验结果。
    spec.degraded_recipe_refs = [String(buildRecipeSpec(state).recipe_id)];
  }
  return spec;
}

/* ------------------------------------------------------------------ 小组件 */

function ChipPicker({
  legend,
  entries,
  selected,
  onToggle,
  emptyReason,
  idPrefix,
}: {
  legend: string;
  entries: Array<{ id: string; status?: string | null; name?: string | null }>;
  selected: string[];
  onToggle: (id: string) => void;
  emptyReason: React.ReactNode;
  idPrefix: string;
}) {
  if (entries.length === 0) {
    return (
      <fieldset className="picker">
        <legend>{legend}</legend>
        <BlockedState title={`${legend}：registry 未返回任何条目`} code="REGISTRY_EMPTY" reason={emptyReason} />
      </fieldset>
    );
  }
  return (
    <fieldset className="picker">
      <legend>
        {legend}
        <span className="muted small">（已选 {selected.length}）</span>
      </legend>
      <div className="chips">
        {entries.map((entry) => (
          <label key={entry.id} className="check">
            <input
              type="checkbox"
              id={`${idPrefix}-${entry.id}`}
              checked={selected.includes(entry.id)}
              onChange={() => onToggle(entry.id)}
            />
            <span className="mono">{entry.id}</span>
            {entry.status && entry.status !== 'IMPLEMENTED' ? (
              <Badge tone={entry.status === 'MISSING' ? 'bad' : 'warn'}>{entry.status}</Badge>
            ) : null}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/* ------------------------------------------------------------------ 主组件 */

export function SynthesisWizardPage() {
  const app = useAppState();
  const [state, setState] = useState<WizardState>(INITIAL);
  const [step, setStep] = useState(1);

  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const vessels = useResource((signal) => getRegistry('vessel', {}, signal), []);
  const materials = useResource((signal) => getRegistry('material', {}, signal), []);
  const patterns = useResource((signal) => getRegistry('pattern', {}, signal), []);
  const layers = useResource((signal) => getRegistry('layer_combo', {}, signal), []);
  const backends = useResource((signal) => getRegistry('fracture_backend', {}, signal), []);
  const axes = useResource((signal) => getRegistry('axis', {}, signal), []);
  const inventory = useResource((signal) => getSynthesisInventory(signal), []);

  const env = capabilities.data?.env ?? {};
  const blenderOk = env['blender_bpy']?.status === 'OK';

  const patch = useCallback((next: Partial<WizardState>) => {
    setState((previous) => ({ ...previous, ...next }));
  }, []);

  const toggle = (key: 'vessels' | 'materials' | 'patterns' | 'layers', id: string) => {
    setState((previous) => {
      const current = previous[key];
      const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id];
      return { ...previous, [key]: next };
    });
  };

  /* ---------------------------------------------------------------- 校验（真实 /specs/validate） */
  const [validation, setValidation] = useState<SpecValidationResponse | null>(null);
  const [validationError, setValidationError] = useState<FailureInfo | null>(null);
  const [validating, setValidating] = useState(false);
  const previewSpec = useMemo(() => buildSpec(state, { lineage: true }), [state]);
  const batchSpec = useMemo(() => buildSpec(state, { lineage: false }), [state]);
  const requestRef = useRef(0);

  const runValidation = useCallback(async (spec: Record<string, unknown>) => {
    const ticket = requestRef.current + 1;
    requestRef.current = ticket;
    setValidating(true);
    setValidationError(null);
    try {
      const response = await validateSpec({ spec, kind: 'generation', registry_check: true });
      if (requestRef.current !== ticket) return;
      setValidation(response);
    } catch (caught) {
      if (requestRef.current !== ticket) return;
      setValidation(null);
      setValidationError(failureFromError(caught));
    } finally {
      if (requestRef.current === ticket) setValidating(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void runValidation(previewSpec), 400);
    return () => window.clearTimeout(timer);
  }, [previewSpec, runValidation]);

  /* ③ 步的算子作为**独立 recipe** 真实校验：返回 compiled nodes（含 level 0 节点）。 */
  const recipeSpec = useMemo(() => buildRecipeSpec(state), [state]);
  const [recipeValidation, setRecipeValidation] = useState<SpecValidationResponse | null>(null);
  const [recipeError, setRecipeError] = useState<FailureInfo | null>(null);
  const recipeRequestRef = useRef(0);

  useEffect(() => {
    if (state.operators.length === 0) {
      setRecipeValidation(null);
      setRecipeError(null);
      return undefined;
    }
    const ticket = recipeRequestRef.current + 1;
    recipeRequestRef.current = ticket;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const response = await validateSpec({ spec: recipeSpec, kind: 'recipe', registry_check: true });
          if (cancelled || recipeRequestRef.current !== ticket) return;
          setRecipeValidation(response);
          setRecipeError(null);
        } catch (caught) {
          if (cancelled || recipeRequestRef.current !== ticket) return;
          setRecipeValidation(null);
          setRecipeError(failureFromError(caught));
        }
      })();
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [recipeSpec, state.operators.length]);

  const [localHash, setLocalHash] = useState<string | null>(null);
  const [canonicalHash, setCanonicalHash] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void specFingerprint(previewSpec).then((value) => {
      if (!cancelled) setLocalHash(value);
    });
    return () => {
      cancelled = true;
    };
  }, [previewSpec]);
  // 后端返回的 canonical 文档重算一遍：这必须等于它给的 spec_hash（同一个 hash_json 规则）。
  useEffect(() => {
    const canonical = validation?.canonical;
    if (!canonical) {
      setCanonicalHash(null);
      return undefined;
    }
    let cancelled = false;
    void (async () => {
      const subtle = globalThis.crypto?.subtle;
      if (!subtle) {
        if (!cancelled) setCanonicalHash(null);
        return;
      }
      try {
        const digest = await subtle.digest('SHA-256', new TextEncoder().encode(canonical));
        const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
        if (!cancelled) setCanonicalHash(`sha256:${hex}`);
      } catch {
        if (!cancelled) setCanonicalHash(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [validation?.canonical]);

  /* ---------------------------------------------------------------- ⑤ 预览 */
  const [preview, setPreview] = useState<ChainPreviewResponse | null>(null);
  const [previewFailure, setPreviewFailure] = useState<FailureInfo | null>(null);
  const [previewRunning, setPreviewRunning] = useState(false);
  const [previewStarted, setPreviewStarted] = useState<number | null>(null);
  const [previewElapsed, setPreviewElapsed] = useState<number | null>(null);

  useEffect(() => {
    if (!previewRunning || previewStarted === null) return undefined;
    const timer = window.setInterval(() => setPreviewElapsed(Date.now() - previewStarted), 250);
    return () => window.clearInterval(timer);
  }, [previewRunning, previewStarted]);

  const runPreview = async () => {
    setPreviewRunning(true);
    setPreview(null);
    setPreviewFailure(null);
    setPreviewStarted(Date.now());
    setPreviewElapsed(0);
    try {
      const response = await postChainPreview({
        spec: previewSpec,
        mode: 'pipeline',
        // 不做自动重试：重试会重跑整条谱系并真的再写一份资产，是否重试由用户按错误码决定。
        max_retries: 0,
        timeout_seconds: 900,
      });
      setPreview(response);
      if (response.blocked) {
        setPreviewFailure({
          code: response.blocked.code,
          message: response.blocked.message,
          stage: response.blocked.stage,
          repro: response.blocked.repro ?? response.repro,
          hint: response.blocked.hint,
          details: response.blocked as unknown as Record<string, unknown>,
        });
      }
      if (response.run_id) app.setSelectedRunId(response.run_id);
      inventory.reload();
    } catch (caught) {
      setPreviewFailure(failureFromError(caught));
    } finally {
      setPreviewRunning(false);
    }
  };

  /* ---------------------------------------------------------------- ⑥ 批量入队 */
  const [plan, setPlan] = useState<BatchPlanResponse | null>(null);
  const [planFailure, setPlanFailure] = useState<FailureInfo | null>(null);
  const [planning, setPlanning] = useState(false);
  const [accepted, setAccepted] = useState<JobAcceptedResponse | null>(null);
  const [enqueueFailure, setEnqueueFailure] = useState<FailureInfo | null>(null);
  const [enqueueing, setEnqueueing] = useState(false);
  const [cursor, setCursor] = useState(0);

  const runPlan = async (options: { resume: boolean; cursor: number }) => {
    setPlanning(true);
    setPlanFailure(null);
    try {
      const response = await postBatchPlan({
        spec: batchSpec,
        requested: state.batchSize,
        batch_size: state.batchSize,
        cursor: options.cursor,
        resume: options.resume,
      });
      setPlan(response);
      setCursor(response.next_cursor);
    } catch (caught) {
      setPlan(null);
      setPlanFailure(failureFromError(caught));
    } finally {
      setPlanning(false);
    }
  };

  const enqueue = async () => {
    if (!plan || plan.selected === 0) return;
    setEnqueueing(true);
    setEnqueueFailure(null);
    try {
      const response = await postJobs(
        {
          schema_version: 'synlab.v3',
          data_scope: 'SYNTHETIC',
          spec: plan.spec,
          stage: 'generate',
          planned_jobs: Math.max(1, state.targetMothers),
          // 幂等键含 batch 游标：`一键续跑下一批` 用新游标得到新 run，重复点击同一批则复用原 run。
          idempotency_key: newIdempotencyKey(`wizard:b${plan.next_cursor}`),
        },
      );
      setAccepted(response);
      app.setSelectedRunId(response.run_id);
      inventory.reload();
    } catch (caught) {
      setEnqueueFailure(failureFromError(caught));
    } finally {
      setEnqueueing(false);
    }
  };

  /* ---------------------------------------------------------------- 批量实时进度（真实 SSE + jobs 轮询） */
  const stream = useRunEventStream(accepted?.run_id ?? null, { enabled: Boolean(accepted?.run_id) });
  const runJobs = useResource(
    (signal) => listJobs({ run_id: accepted?.run_id, limit: 100, with_total: true }, signal),
    [accepted?.run_id],
    { enabled: Boolean(accepted?.run_id), intervalMs: 5000 },
  );
  const jobCounts = useMemo(() => {
    const table: Record<string, number> = {};
    for (const job of (runJobs.data?.items ?? []) as JobRecord[]) {
      table[job.state] = (table[job.state] ?? 0) + 1;
    }
    return table;
  }, [runJobs.data]);

  /* ---------------------------------------------------------------- YAML 导出 */
  const [yamlText, setYamlText] = useState<string>('');
  const [yamlFor, setYamlFor] = useState<'preview' | 'batch'>('preview');
  useEffect(() => {
    setYamlText(toYaml(buildSpec(state, { lineage: yamlFor === 'preview' })));
  }, [state, yamlFor]);

  const downloadYaml = () => {
    const blob = new Blob([yamlText], { type: 'application/x-yaml' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = yamlFilename('synlab_generation', validation?.spec_hash ?? localHash);
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const registryEntries = (response: RegistryResponse | null) =>
    (response?.entries ?? []).map((entry) => ({ id: entry.id, status: entry.status ?? null, name: entry.name ?? null }));

  const axisEntries = axes.data?.entries ?? [];
  const groupedAxes = useMemo(() => {
    const map = new Map<string, typeof axisEntries>();
    for (const entry of axisEntries) {
      const prefix = entry.id.charAt(0).toUpperCase();
      const list = map.get(prefix) ?? [];
      list.push(entry);
      map.set(prefix, list);
    }
    return map;
  }, [axisEntries]);

  const axisMaterialized = useMemo(() => {
    const map = new Map<string, SynthesisInventoryResponse['degradation_axes'][number]>();
    for (const entry of inventory.data?.degradation_axes ?? []) map.set(entry.axis_id, entry);
    return map;
  }, [inventory.data]);

  const selectedCount = state.vessels.length * state.materials.length * state.patterns.length;
  const canPreview = state.vessels.length > 0 && state.materials.length > 0 && state.patterns.length > 0;

  const steps = [
    { id: 1, label: '① 器型/材料/花纹/层' },
    { id: 2, label: '② 断裂参数' },
    { id: 3, label: '③ 退化' },
    { id: 4, label: '④ 观测' },
    { id: 5, label: '⑤ 预览' },
    { id: 6, label: '⑥ 入队批量' },
  ];

  return (
    <>
      <PageHeader
        title="合成向导"
        plan="U14 · 操作逻辑"
        summary="六步走完：真实 registry 选组合 → 断裂后端与片数 → 退化轴/档位 → 观测路线 → 真实跑一条谱系预览 → 一键入队批量并实时看进度。所有下拉都来自后端 registry，缺能力时显示真实错误码。"
        actions={
          <div className="row">
            <Badge tone={validation?.ok ? 'ok' : validationError ? 'bad' : 'neutral'}>
              {validation?.ok ? 'spec 校验通过' : validationError ? `校验请求失败 ${validationError.code}` : '校验中…'}
            </Badge>
            <Badge tone="info">组合空间 {selectedCount}</Badge>
            {inventory.data ? (
              <Badge tone="neutral">
                覆盖 {inventory.data.buckets.covered}/{inventory.data.buckets.target ?? '—'}
              </Badge>
            ) : null}
          </div>
        }
      />

      <nav className="wizardsteps" aria-label="合成向导步骤">
        <ol>
          {steps.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={`wizardsteps__btn${step === item.id ? ' wizardsteps__btn--active' : ''}`}
                aria-current={step === item.id ? 'step' : undefined}
                onClick={() => setStep(item.id)}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ol>
      </nav>

      {step === 1 ? (
        <SectionCard
          title="① 选择器型 / 材料 / 花纹族 / 层组合"
          subtitle="GET /registry/{vessel,material,pattern,layer_combo} —— 选项与状态都来自真实 registry"
          actions={
            <span className="muted small">
              当前组合空间 = {state.vessels.length}×{state.materials.length}×{state.patterns.length} = {selectedCount}
            </span>
          }
        >
          {capabilities.status === 'error' ? <ErrorState error={capabilities.error} onRetry={capabilities.reload} /> : null}
          <div className="grid2">
            <ChipPicker
              legend="器型（vessel）"
              idPrefix="vessel"
              entries={registryEntries(vessels.data)}
              selected={state.vessels}
              onToggle={(id) => toggle('vessels', id)}
              emptyReason={<>该 build 没有注册任何 vessel：后端拒绝按空清单生成，前端也不会补一份名单。</>}
            />
            <ChipPicker
              legend="材料（material）"
              idPrefix="material"
              entries={registryEntries(materials.data)}
              selected={state.materials}
              onToggle={(id) => toggle('materials', id)}
              emptyReason={<>该 build 没有注册任何 material。</>}
            />
            <ChipPicker
              legend="花纹族（pattern）"
              idPrefix="pattern"
              entries={registryEntries(patterns.data)}
              selected={state.patterns}
              onToggle={(id) => toggle('patterns', id)}
              emptyReason={<>该 build 没有注册任何 pattern family。</>}
            />
            <ChipPicker
              legend="层组合（layer_combo）"
              idPrefix="layer"
              entries={registryEntries(layers.data)}
              selected={state.layers}
              onToggle={(id) => toggle('layers', id)}
              emptyReason={<>该 build 没有注册任何 layer combo。</>}
            />
          </div>
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">母体数（batch 用）</span>
              <input
                className="input input--tight"
                type="number"
                min={1}
                value={state.targetMothers}
                aria-label="母体数"
                onChange={(event) => patch({ targetMothers: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">目标片数估计</span>
              <input
                className="input input--tight"
                type="number"
                min={1}
                value={state.fragmentsEstimate}
                aria-label="目标片数估计"
                onChange={(event) => patch({ fragmentsEstimate: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">master seed</span>
              <input
                className="input input--tight"
                type="number"
                value={state.masterSeed}
                aria-label="master seed"
                onChange={(event) => patch({ masterSeed: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">release profile</span>
              <select
                className="input input--tight"
                value={state.releaseProfile}
                aria-label="release profile"
                onChange={(event) => patch({ releaseProfile: event.target.value })}
              >
                {RELEASE_PROFILES.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="muted small">
            registry 指纹：<code className="mono">{vessels.data?.registry_fingerprint ?? '未获取'}</code>；⑤ 步预览固定
            <code className="mono"> target_mothers=1</code>（一条谱系），⑥ 步才按母体数展开。
          </p>
        </SectionCard>
      ) : null}

      {step === 2 ? (
        <SectionCard
          title="② 断裂参数（后端可用性 + 切面法向/偏移 + 目标片数）"
          subtitle="GET /registry/fracture_backend 的 status 是后端真实实现状态；POST /specs/validate 会拒绝未注册后端"
        >
          <table className="table">
            <caption>可选断裂后端（真实 registry，包含未实现项）</caption>
            <thead>
              <tr>
                <th scope="col">选择</th>
                <th scope="col">backend</th>
                <th scope="col">状态</th>
                <th scope="col">实测可用性</th>
              </tr>
            </thead>
            <tbody>
              {(backends.data?.entries ?? []).map((entry) => {
                const usable = entry.status === 'IMPLEMENTED' || entry.status === 'QA_PASSED'
                  || entry.status === 'VALIDATED';
                return (
                  <tr key={entry.id} className={state.fractureBackend === entry.id ? 'row--selected' : undefined}>
                    <td>
                      <input
                        type="radio"
                        name="fracture-backend"
                        checked={state.fractureBackend === entry.id}
                        aria-label={`选择断裂后端 ${entry.id}`}
                        onChange={() => patch({ fractureBackend: entry.id })}
                      />
                    </td>
                    <th scope="row" className="mono">{entry.id}</th>
                    <td>
                      <Badge tone={usable ? 'ok' : entry.status === 'MISSING' ? 'bad' : 'warn'}>
                        {entry.status ?? 'UNKNOWN'}
                      </Badge>
                    </td>
                    <td className="small">
                      {usable
                        ? 'registry 标记已实现：可直接用于预览与批量'
                        : `registry 标记为 ${entry.status}：本向导仍允许选中，但 /specs/validate 与流水线会给出真实拒绝码`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {backends.data && backends.data.count === 0 ? (
            <BlockedState
              title="无法枚举断裂后端：registry 未注册"
              code="REGISTRY_EMPTY"
              reason="后端 ID 由 register_fracture_backend 注册；前端不复制名单，因此这里为空。"
            />
          ) : null}

          <div className="row">
            <label className="field field--inline">
              <span className="field__label">切面法向（由片数区间间接决定）</span>
              <span className="muted small">
                schema 里没有独立法向字段；真实可用表达是 <code className="mono">fracture.target_piece_range</code> 与
                <code className="mono"> seed_count_range</code>，切面法向由后端从种子推导
              </span>
            </label>
          </div>
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">目标片数 lo</span>
              <input
                className="input input--tight"
                type="number"
                min={2}
                value={state.pieceLo}
                aria-label="目标片数下界"
                onChange={(event) => patch({ pieceLo: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">目标片数 hi</span>
              <input
                className="input input--tight"
                type="number"
                min={state.pieceLo}
                value={state.pieceHi}
                aria-label="目标片数上界"
                onChange={(event) => patch({ pieceHi: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">最小特征波长（mm）</span>
              <input
                className="input input--tight"
                type="number"
                step="0.01"
                min={0.01}
                value={state.minFeatureWavelengthMm}
                aria-label="最小特征波长"
                onChange={(event) => patch({ minFeatureWavelengthMm: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">共享面最大误差（mm）</span>
              <input
                className="input input--tight"
                type="number"
                step="0.001"
                min={0.0001}
                value={state.sharedSurfaceMaxErrorMm}
                aria-label="共享面最大误差"
                onChange={(event) => patch({ sharedSurfaceMaxErrorMm: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">最大尝试次数</span>
              <input
                className="input input--tight"
                type="number"
                min={1}
                value={state.maxAttempts}
                aria-label="最大尝试次数"
                onChange={(event) => patch({ maxAttempts: Number(event.target.value) })}
              />
            </label>
          </div>
          {state.pieceLo < 2 || state.pieceHi < state.pieceLo ? (
            <p className="field__error" role="alert">
              就地校验：schema 要求 <code className="mono">2 &lt;= lo &lt;= hi</code>（当前 {state.pieceLo}–{state.pieceHi}）。
            </p>
          ) : null}
        </SectionCard>
      ) : null}

      {step === 3 ? (
        <SectionCard
          title="③ 退化（轴分组 6 阶段，多选轴 + 档位 0–4）"
          subtitle="GET /registry/axis 是 31 轴的真实来源；GET /synthesis/inventory 说明哪些轴在本 store 已物化"
        >
          <p className="warning">
            <strong>level 0 = 真恒等</strong>：与 baseline 同源、同 basis（schema 的{' '}
            <code className="mono">basis_policy=paired_across_levels</code>）。它必须真实跑出来才有比较意义 ——
            本向导不会用 level 1 冒充 baseline。
          </p>
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">basis 策略</span>
              <select
                className="input input--tight"
                value={state.basisPolicy}
                aria-label="basis 策略"
                onChange={(event) => patch({ basisPolicy: event.target.value })}
              >
                <option value="paired_across_levels">paired_across_levels（推荐：L0 与 Ln 同 basis）</option>
                <option value="independent">independent</option>
              </select>
            </label>
            <label className="field field--inline">
              <span className="field__label">作用对象 source_role</span>
              <select
                className="input input--tight"
                value={state.sourceRole}
                aria-label="source_role"
                onChange={(event) => patch({ sourceRole: event.target.value })}
              >
                <option value="clean">clean（干净几何）</option>
                <option value="physical">physical（物理损伤后）</option>
                <option value="observed">observed（观测重建）</option>
              </select>
            </label>
          </div>

          {OPERATOR_STAGES.map((group) => {
            const entries = (['P', 'I', 'G', 'X'] as const)
              .flatMap((prefix) => groupedAxes.get(prefix) ?? [])
              .filter((entry) => (STAGE_BY_PREFIX[entry.id.charAt(0).toUpperCase()] ?? group.stage) === group.stage);
            return (
              <fieldset key={group.stage} className="picker">
                <legend>
                  {group.label}
                  <span className="muted small">（{entries.length} 轴）</span>
                </legend>
                {entries.length === 0 ? (
                  <p className="muted small">该阶段在 /registry/axis 里没有对应轴。</p>
                ) : (
                  <table className="table table--tight">
                    <thead>
                      <tr>
                        <th scope="col">加入</th>
                        <th scope="col">axis</th>
                        <th scope="col">DAG 内已物化档位</th>
                        <th scope="col">档位（0–4）</th>
                        <th scope="col">variant</th>
                        <th scope="col">移除</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entries.map((entry) => {
                        const picked = state.operators.filter((op) => op.axis_id === entry.id);
                        const materialized = axisMaterialized.get(entry.id);
                        return (
                          <tr key={entry.id}>
                            <td>
                              <button
                                type="button"
                                className="btn btn--tiny"
                                onClick={() =>
                                  patch({
                                    operators: [
                                      ...state.operators,
                                      { axis_id: entry.id, stage: group.stage, level: 1, variant: '' },
                                    ],
                                  })
                                }
                              >
                                加入
                              </button>
                            </td>
                            <th scope="row" className="mono">{entry.id}</th>
                            <td className="mono small">
                              {materialized
                                ? materialized.levels.map((row) => `${row.level}:${row.assets}`).join(' · ')
                                : <Badge tone="warn">NA（未物化）</Badge>}
                            </td>
                            <td>
                              {picked.length === 0 ? <span className="muted">—</span> : (
                                <select
                                  className="input input--tight"
                                  value={String(picked[0].level)}
                                  aria-label={`${entry.id} 的档位`}
                                  onChange={(event) =>
                                    patch({
                                      operators: state.operators.map((op) =>
                                        op.axis_id === entry.id && op === picked[0]
                                          ? { ...op, level: Number(event.target.value) }
                                          : op),
                                    })
                                  }
                                >
                                  {LEVELS.map((level) => (
                                    <option key={level} value={level}>
                                      {level}{level === 0 ? '（真恒等）' : ''}
                                    </option>
                                  ))}
                                </select>
                              )}
                            </td>
                            <td>
                              {picked.length === 0 ? <span className="muted">—</span> : (
                                <input
                                  className="input input--tight"
                                  value={picked[0].variant}
                                  placeholder="variant"
                                  aria-label={`${entry.id} 的 variant`}
                                  onChange={(event) =>
                                    patch({
                                      operators: state.operators.map((op) =>
                                        op.axis_id === entry.id && op === picked[0]
                                          ? { ...op, variant: event.target.value }
                                          : op),
                                    })
                                  }
                                />
                              )}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn btn--tiny"
                                disabled={picked.length === 0}
                                onClick={() =>
                                  patch({
                                    operators: state.operators.filter((op) => op.axis_id !== entry.id),
                                  })
                                }
                              >
                                移除
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </fieldset>
            );
          })}

          <SectionCard
            title="本向导选择的算子（作为独立 recipe 提交后端校验）"
            subtitle="POST /specs/validate kind=recipe —— 真实编译成 nodes；生成 spec 里只带 degraded_recipe_refs"
          >
            {state.operators.length === 0 ? (
              <EmptyState
                title="还没有选任何退化轴"
                reason="不选轴时生成 spec 里不会出现 degraded_recipe_refs，⑤ 步预览仍可跑（只是不含退化阶段）。"
              />
            ) : (
              <>
                <table className="table table--tight">
                  <thead>
                    <tr>
                      <th scope="col">axis</th>
                      <th scope="col">stage</th>
                      <th scope="col">level</th>
                      <th scope="col">variant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.operators.map((op) => (
                      <tr key={`${op.axis_id}-${op.level}-${op.variant}`}>
                        <th scope="row" className="mono">{op.axis_id}</th>
                        <td className="mono">{op.stage}</td>
                        <td className="mono">
                          {op.level}
                          {op.level === 0 ? <Badge tone="ok">真恒等</Badge> : null}
                        </td>
                        <td className="mono">{op.variant || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <KeyValueList
                  rows={[
                    { label: 'recipe_id', value: String(recipeSpec.recipe_id), mono: true },
                    { label: 'recipe spec_hash（后端）', value: recipeValidation?.spec_hash ?? '未校验', mono: true },
                    {
                      label: 'recipe_hash（编译产物）',
                      value: String((recipeValidation?.expanded?.recipe_hash as string | undefined) ?? '未返回'),
                      mono: true,
                    },
                    {
                      label: '编译结果',
                      value: recipeValidation
                        ? (recipeValidation.ok
                            ? <Badge tone="ok">ok（{((recipeValidation.expanded?.nodes as unknown[]) ?? []).length} 个节点）</Badge>
                            : <Badge tone="bad">{recipeValidation.errors.length} 个错误</Badge>)
                        : '未校验',
                    },
                    {
                      label: '为什么生成 spec 里只有 refs',
                      value: 'GenerationSpec 是 extra=forbid：算子本体不是生成 spec 的字段，只能作为独立 recipe 编译，再由 degraded_recipe_refs 引用',
                    },
                  ]}
                />
                {recipeValidation && !recipeValidation.ok ? (
                  <table className="table table--tight">
                    <caption>recipe 校验错误（后端原样）</caption>
                    <thead>
                      <tr><th scope="col">字段</th><th scope="col">类型</th><th scope="col">消息</th></tr>
                    </thead>
                    <tbody>
                      {recipeValidation.errors.map((issue, index) => (
                        <tr key={`${issue.loc.join('.')}-${index}`}>
                          <th scope="row" className="mono">{issue.loc.join('.')}</th>
                          <td className="mono small">{issue.type}</td>
                          <td className="small">{issue.msg}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
                {recipeError ? (
                  <FailureCard title="recipe 校验请求失败" failure={recipeError} />
                ) : null}
                {recipeValidation?.expanded?.nodes ? (
                  <details>
                    <summary>编译出的 DAG 节点（后端原样，含 level 0 节点）</summary>
                    <pre className="mono pre">{pretty(recipeValidation.expanded.nodes)}</pre>
                  </details>
                ) : null}
              </>
            )}
          </SectionCard>
        </SectionCard>
      ) : null}

      {step === 4 ? (
        <SectionCard
          title="④ 观测（路线 / 视角数 / 长边 px / 渲染后端）"
          subtitle="取值来自 synlab/schemas/spec.py::ObservationConfig；渲染后端可用性来自 GET /capabilities 的真实环境探测"
        >
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">观测路线 route</span>
              <select
                className="input input--tight"
                value={state.route}
                aria-label="观测路线"
                onChange={(event) => patch({ route: event.target.value })}
              >
                {ROUTES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="field__label">输入档 input_profile</span>
              <select
                className="input input--tight"
                value={state.inputProfile}
                aria-label="输入档"
                onChange={(event) => patch({ inputProfile: event.target.value })}
              >
                {INPUT_PROFILES.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="field__label">每片视角数</span>
              <input
                className="input input--tight"
                type="number"
                min={1}
                value={state.viewsPerFragment}
                aria-label="每片视角数"
                onChange={(event) => patch({ viewsPerFragment: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">长边像素</span>
              <input
                className="input input--tight"
                type="number"
                min={32}
                value={state.imageLongEdgePx}
                aria-label="长边像素"
                onChange={(event) => patch({ imageLongEdgePx: Number(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">渲染后端 renderer</span>
              <select
                className="input input--tight"
                value={state.renderer}
                aria-label="渲染后端"
                onChange={(event) => patch({ renderer: event.target.value })}
              >
                {RENDERERS.map((item) => (
                  <option
                    key={item.value}
                    value={item.value}
                    disabled={item.env === 'blender_bpy' && !blenderOk}
                  >
                    {item.label}
                    {item.env === 'blender_bpy' && !blenderOk ? '（本机 ENV_CAPABILITY_MISSING）' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="field__label">相机档引用（可空）</span>
              <input
                className="input input--tight"
                value={state.cameraProfileRef}
                placeholder="camera_profile_id"
                aria-label="相机档引用"
                onChange={(event) => patch({ cameraProfileRef: event.target.value })}
              />
            </label>
          </div>
          <KeyValueList
            rows={[
              {
                label: 'blender_bpy',
                value: (
                  <>
                    <Badge tone={blenderOk ? 'ok' : 'warn'}>{env['blender_bpy']?.status ?? '未探测'}</Badge>
                    <span className="muted small"> {env['blender_bpy']?.detail ?? ''}</span>
                  </>
                ),
              },
              {
                label: 'cuda',
                value: (
                  <>
                    <Badge tone={env['cuda']?.status === 'OK' ? 'ok' : 'warn'}>
                      {env['cuda']?.status ?? '未探测'}
                    </Badge>
                    <span className="muted small"> {env['cuda']?.detail ?? ''}</span>
                  </>
                ),
              },
              { label: 'trimesh（display_lod 需要）', value: env['trimesh']?.status ?? '未探测' },
              { label: '可用能力', value: <span className="mono small">{(capabilities.data?.available ?? []).join(', ') || '未提供'}</span> },
              { label: '缺失能力', value: <span className="mono small">{(capabilities.data?.missing ?? []).join(', ') || '（无）'}</span> },
            ]}
          />
          {state.renderer === 'blender' && !blenderOk ? (
            <p className="field__error" role="alert">
              就地校验：本机 <code className="mono">blender_bpy</code> 为 ENV_CAPABILITY_MISSING，
              选它会在观测阶段被后端拒绝（真实 code）。请改用 <code className="mono">software_rasterizer</code>。
            </p>
          ) : null}
        </SectionCard>
      ) : null}

      {step === 5 ? (
        <SectionCard
          title="⑤ 预览（真实跑一条谱系）"
          subtitle="POST /synthesis/chain-preview（mode=pipeline）—— 真实资产、真实每阶段耗时、真实 coverage 行"
          actions={
            <ActionButton
              tone="primary"
              onClick={() => void runPreview()}
              busy={previewRunning}
              disabledReason={
                !canPreview
                  ? '① 步至少要选一个器型/材料/花纹'
                  : validation && !validation.ok
                    ? `spec 未通过后端校验（${validation.errors.length} 个错误）`
                    : null
              }
            >
              跑一次单谱系预览
            </ActionButton>
          }
        >
          <KeyValueList
            rows={[
              { label: '预览 spec_hash（后端 /specs/validate）', value: validation?.spec_hash ?? '未校验', mono: true },
              { label: 'canonical（后端返回的规范化 JSON，前 200 字符）', value: validation?.canonical ? truncate(validation.canonical, 200) : '未返回', mono: true },
              {
                label: 'canonical 重算指纹（自检）',
                value: canonicalHash ?? (localHash === null ? '本机无法计算（无 crypto.subtle）' : '计算中…'),
                mono: true,
              },
              {
                label: 'canonical 自检一致',
                value: canonicalHash && validation?.spec_hash
                  ? (canonicalHash === validation.spec_hash ? <Badge tone="ok">一致</Badge> : <Badge tone="bad">不一致</Badge>)
                  : <Badge tone="neutral">无法比较</Badge>,
              },
              {
                label: '本机指纹（未展开默认值的提交 spec）',
                value: (
                  <>
                    <span className="mono">{localHash ?? '本机无法计算'}</span>{' '}
                    <Badge tone="neutral">与后端 spec_hash 必然不同：后端对 pydantic 展开默认值后的完整文档取哈希</Badge>
                  </>
                ),
              },
              { label: '目标谱系', value: `${state.vessels[0] ?? '—'} / ${state.materials[0] ?? '—'} / ${state.patterns[0] ?? '—'}（target_mothers=1）` },
              { label: '退化算子', value: state.operators.length > 0 ? state.operators.map((op) => `${op.axis_id}L${op.level}`).join(', ') : '（未选，预览不含退化阶段）' },
            ]}
          />
          {validation ? (
            <details open={!validation.ok}>
              <summary>
                校验结果（errors {validation.errors.length} / warnings {validation.warnings.length}）
              </summary>
              {validation.errors.length > 0 ? (
                <table className="table table--tight">
                  <thead>
                    <tr><th scope="col">字段</th><th scope="col">类型</th><th scope="col">消息</th></tr>
                  </thead>
                  <tbody>
                    {validation.errors.map((issue, index) => (
                      <tr key={`${issue.loc.join('.')}-${index}`}>
                        <th scope="row" className="mono">{issue.loc.join('.')}</th>
                        <td className="mono small">{issue.type}</td>
                        <td className="small">{issue.msg}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted small">后端未报告任何错误。expanded 字段：<code className="mono">{(Object.keys(validation.expanded ?? {})).join(', ')}</code></p>
              )}
              {validation.warnings.length > 0 ? (
                <ul className="notes">
                  {validation.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              ) : null}
            </details>
          ) : null}
          {validationError ? (
            <FailureCard title="spec 校验请求失败" failure={validationError} onRetry={() => void runValidation(previewSpec)} />
          ) : null}
          {validating ? <LoadingState label="POST /specs/validate 校验中…" /> : null}

          {previewRunning ? (
            <RunningCard
              title="正在真实跑这一条谱系"
              label={`${state.vessels[0] ?? '—'} / ${state.materials[0] ?? '—'} / ${state.patterns[0] ?? '—'}：母体→纹样→断裂→真值→物理→退化→观测→特征/标注/provenance→出土上下文`}
              elapsedMs={previewElapsed}
            />
          ) : null}

          {previewFailure ? (
            <FailureCard
              title="预览未完成"
              failure={previewFailure}
              onRetry={() => void runPreview()}
            />
          ) : null}

          {preview ? (
            <>
              <KeyValueList
                rows={[
                  { label: 'run_id', value: preview.run_id, mono: true },
                  { label: 'lineage_id', value: preview.lineage_id ?? '未提供', mono: true },
                  { label: 'executed', value: <Badge tone={preview.executed ? 'ok' : 'bad'}>{String(preview.executed)}</Badge> },
                  { label: 'state', value: preview.state },
                  { label: 'spec_hash', value: preview.spec_hash, mono: true },
                  { label: '端到端耗时', value: `${formatNumber(preview.wall_seconds, 2)} s` },
                  { label: '产出资产', value: `${preview.assets?.length ?? 0} 个 · ${formatBytes(preview.asset_bytes)}` },
                  { label: 'coverage 账本', value: preview.coverage_ref ?? '未提供', mono: true },
                ]}
              />
              <table className="table table--metrics">
                <caption>每阶段真实耗时（管线内部 perf_counter）与产出</caption>
                <thead>
                  <tr>
                    <th scope="col">阶段</th>
                    <th scope="col">耗时 (s)</th>
                    <th scope="col">产出资产</th>
                    <th scope="col">字节</th>
                    <th scope="col">role</th>
                  </tr>
                </thead>
                <tbody>
                  {(preview.stages ?? []).map((row) => (
                    <tr key={`${row.stage}-${row.seconds ?? 'na'}`}>
                      <th scope="row" className="mono">{row.stage}</th>
                      <td className="mono">{row.seconds === null || row.seconds === undefined ? '未提供' : formatNumber(row.seconds, 3)}</td>
                      <td className="mono">{row.outputs ?? 0}</td>
                      <td className="mono">{formatBytes(row.output_bytes ?? 0)}</td>
                      <td className="mono small">{(row.roles ?? []).join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <details>
                <summary>产出资产明细（{preview.assets?.length ?? 0}）</summary>
                <table className="table table--tight">
                  <thead>
                    <tr><th scope="col">asset_id</th><th scope="col">role</th><th scope="col">qa_status</th><th scope="col">溯源</th></tr>
                  </thead>
                  <tbody>
                    {(preview.assets ?? []).map((asset) => (
                      <tr key={asset.asset_id}>
                        <th scope="row" className="mono">{truncate(asset.asset_id, 26)}</th>
                        <td className="mono">{asset.role}</td>
                        <td><Badge tone={asset.qa_status === 'QA_PASS' ? 'ok' : 'warn'}>{asset.qa_status}</Badge></td>
                        <td>
                          <button type="button" className="btn btn--tiny" onClick={() => app.openProvenance({ kind: 'asset', id: asset.asset_id })}>
                            溯源
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
              <details>
                <summary>coverage 行（后端写入 reports/coverage.json 的那一行）</summary>
                <pre className="mono pre">{pretty(preview.coverage_row ?? {})}</pre>
              </details>
              <p className="muted small">{preview.timing_note}</p>
            </>
          ) : null}

          {!previewRunning && !preview && !previewFailure ? (
            <EmptyState
              title="还没有预览结果"
              reason="点上面的按钮会真实跑一条谱系；结果里的耗时与资产都不是估算值，未运行前这里保持为空。"
            />
          ) : null}
        </SectionCard>
      ) : null}

      {step === 6 ? (
        <SectionCard
          title="⑥ 入队批量（批大小 / 续跑 / 实时进度）"
          subtitle="POST /synthesis/batch-plan 选组合 → POST /jobs 入队 → GET /runs/{id}/events 与 GET /jobs?run_id= 看真实进度"
          actions={
            <div className="row">
              <ActionButton onClick={() => void runPlan({ resume: false, cursor })} busy={planning}>
                规划下一批（从游标 {cursor}）
              </ActionButton>
              <ActionButton tone="primary" onClick={() => void runPlan({ resume: true, cursor: 0 })} busy={planning}>
                一键续跑下一批（resume）
              </ActionButton>
            </div>
          }
        >
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">批大小</span>
              <input
                className="input input--tight"
                type="number"
                min={1}
                max={64}
                value={state.batchSize}
                aria-label="批大小"
                onChange={(event) => patch({ batchSize: Number(event.target.value) })}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={state.resume}
                onChange={(event) => patch({ resume: event.target.checked })}
              />
              续跑语义（忽略游标，按 assets 表推进到第一个未实现组合）
            </label>
          </div>

          {inventory.data ? (
            <KeyValueList
              rows={[
                { label: '组合空间剩余', value: plan?.pending_combinations ?? '未规划' },
                { label: '已实现组合（assets 表）', value: inventory.data.buckets.rows.length },
                { label: '覆盖矩阵来源', value: inventory.data.buckets.source ?? 'reports 里没有 coverage 文件', mono: true },
                {
                  label: '覆盖（vessel/material）',
                  value: `${inventory.data.buckets.covered} / ${inventory.data.buckets.target ?? '—'}`,
                },
                { label: '磁盘实测', value: formatBytes(inventory.data.panel.disk_bytes) },
                { label: 'jobs 计数', value: `planned ${inventory.data.panel.planned} · attempted ${inventory.data.panel.attempted} · accepted ${inventory.data.panel.accepted} · failed ${inventory.data.panel.failed}` },
              ]}
            />
          ) : null}

          {planFailure ? <FailureCard title="批次规划失败" failure={planFailure} onRetry={() => void runPlan({ resume: state.resume, cursor })} /> : null}

          {plan ? (
            <>
              <KeyValueList
                rows={[
                  { label: '本批组合数', value: plan.selected },
                  { label: '下一个游标', value: plan.next_cursor },
                  { label: '剩余组合', value: plan.pending_combinations },
                  { label: '批次 spec_hash', value: plan.spec_hash ?? '未提供', mono: true },
                  { label: 'resume 说明', value: plan.resume.note },
                ]}
              />
              <table className="table table--tight">
                <caption>本批组合（来自 registry 的真实 id，按 assets 表去重）</caption>
                <thead>
                  <tr><th scope="col">#</th><th scope="col">vessel</th><th scope="col">material</th><th scope="col">pattern</th></tr>
                </thead>
                <tbody>
                  {plan.combinations.map((combo) => (
                    <tr key={String(combo.index)}>
                      <td className="mono">{String(combo.index)}</td>
                      <td className="mono">{String(combo.vessel_id)}</td>
                      <td className="mono">{String(combo.material_id)}</td>
                      <td className="mono">{String(combo.pattern_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {plan.empty_reason ? <p className="warning">{plan.empty_reason}</p> : null}
              <div className="row">
                <ActionButton
                  tone="primary"
                  onClick={() => void enqueue()}
                  busy={enqueueing}
                  disabledReason={plan.selected === 0 ? '本批没有组合可提交' : null}
                >
                  提交这一批（POST /jobs）
                </ActionButton>
                <button type="button" className="btn btn--tiny" onClick={() => setCursor(plan.next_cursor)}>
                  把游标设为 {plan.next_cursor}
                </button>
              </div>
            </>
          ) : null}

          {enqueueFailure ? <FailureCard title="入队失败" failure={enqueueFailure} onRetry={() => void enqueue()} /> : null}

          {accepted ? (
            <>
              <KeyValueList
                rows={[
                  { label: 'run_id', value: accepted.run_id, mono: true },
                  { label: 'job_id', value: accepted.job_id, mono: true },
                  { label: '受理状态', value: accepted.status },
                  { label: 'spec_hash', value: accepted.spec_hash, mono: true },
                  { label: '幂等重放', value: <Badge tone={accepted.idempotent_replay ? 'warn' : 'ok'}>{String(accepted.idempotent_replay)}</Badge> },
                  { label: '事件流', value: accepted.events_url, mono: true },
                ]}
              />
              <p className="muted small">{accepted.note}</p>
              <div className="row">
                <Badge tone={stream.state === 'open' ? 'ok' : stream.state === 'error' ? 'bad' : 'info'}>
                  SSE {stream.state}
                </Badge>
                <span className="mono small">已接收事件 {stream.events.length} · last seq {stream.lastSeq}</span>
                {stream.pollingFallback ? (
                  <Badge tone="warn">事件流不可用，已退化为 GET /jobs?run_id= 轮询</Badge>
                ) : null}
              </div>
              <div className="statrow">
                {Object.entries(jobCounts).map(([jobState, count]) => (
                  <span key={jobState} className="stat">
                    <Badge tone={jobStateLabel(jobState).tone}>{jobStateLabel(jobState).label}</Badge>
                    <strong>{count}</strong>
                  </span>
                ))}
                {Object.keys(jobCounts).length === 0 ? <span className="muted">还没有 job 行</span> : null}
              </div>
              <table className="table table--tight">
                <caption>本 run 的 job（GET /jobs?run_id=，权威 state）</caption>
                <thead>
                  <tr><th scope="col">job_id</th><th scope="col">stage</th><th scope="col">state</th><th scope="col">attempt</th><th scope="col">错误码</th></tr>
                </thead>
                <tbody>
                  {((runJobs.data?.items ?? []) as JobRecord[]).map((job) => (
                    <tr key={job.job_id}>
                      <th scope="row" className="mono">{truncate(job.job_id, 22)}</th>
                      <td className="mono">{job.stage}</td>
                      <td><Badge tone={jobStateLabel(job.state).tone}>{jobStateLabel(job.state).label}</Badge></td>
                      <td className="mono">{job.attempt}</td>
                      <td className="mono small">
                        {job.error ? String((job.error as Record<string, unknown>).code ?? '—') : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {runJobs.status === 'error' ? <ErrorState error={runJobs.error} onRetry={runJobs.reload} /> : null}
              <p className="muted small">
                入队只表示已受理（HTTP 202）。真正的计算由独立 worker 进程执行：
                <code className="mono"> python -m synlab.api.worker --store-root &lt;store&gt; --once --workspace default</code>
              </p>
            </>
          ) : null}
        </SectionCard>
      ) : null}

      <SectionCard
        title="配置导出（YAML + spec_hash）"
        subtitle="导出的就是屏幕上这份 spec；spec_hash 来自 POST /specs/validate，本机指纹用同一套 canonical JSON 规则另算一遍"
        actions={
          <div className="row">
            <button
              type="button"
              className={`btn btn--tiny${yamlFor === 'preview' ? ' btn--primary' : ''}`}
              onClick={() => setYamlFor('preview')}
            >
              预览 spec（target_mothers=1）
            </button>
            <button
              type="button"
              className={`btn btn--tiny${yamlFor === 'batch' ? ' btn--primary' : ''}`}
              onClick={() => setYamlFor('batch')}
            >
              批量 spec（按母体数）
            </button>
            <button type="button" className="btn btn--tiny" onClick={downloadYaml}>
              下载 .yaml
            </button>
            <button type="button" className="btn btn--tiny" onClick={() => void runValidation(yamlFor === 'preview' ? previewSpec : batchSpec)}>
              用后端校验这份配置
            </button>
          </div>
        }
      >
        <KeyValueList
          rows={[
            { label: 'spec_hash（后端 /specs/validate）', value: validation?.spec_hash ?? '未校验', mono: true },
            {
              label: 'canonical 自检（用后端返回的 canonical 重算）',
              value: canonicalHash && validation?.spec_hash
                ? (canonicalHash === validation.spec_hash
                    ? <Badge tone="ok">一致（hash 规则相同）</Badge>
                    : <Badge tone="bad">不一致</Badge>)
                : <Badge tone="neutral">未校验</Badge>,
            },
            {
              label: '本机指纹（提交的 spec，未展开默认值）',
              value: localHash ?? '本机无法计算（无 crypto.subtle）',
              mono: true,
            },
            { label: 'schema_id', value: validation?.schema_id ?? 'synlab.v3', mono: true },
            { label: '文件名建议', value: yamlFilename('synlab_generation', validation?.spec_hash ?? null), mono: true },
          ]}
        />
        <div className="row">
          <CopyValue value={yamlText} label="YAML 配置" />
        </div>
        <pre className="mono pre">{yamlText}</pre>
      </SectionCard>
    </>
  );
}
