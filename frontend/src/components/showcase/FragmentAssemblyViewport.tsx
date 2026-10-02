/**
 * FragmentAssemblyViewport —— 把**多个真实碎片 GLB**放进同一个 three.js 场景，
 * 支持「原位 / 爆炸视图」两种展示模式（计划 20.14.5：视口只改展示状态，从不回写资产）。
 *
 * 单位契约与 `SceneViewport` 完全一致：GLB 是**米 / Y-up**，权威几何是**毫米 / Z-up**，
 * 标尺一律经 `displayToAuthority` 反算成 mm 再显示。
 *
 * 诚实规则：
 * * 只加载真实存在的碎片展示资产；任何一个加载失败都会列出真实的 code/message，
 *   不画示意几何补位；
 * * 爆炸视图是**纯展示变换**（沿碎片包围盒中心方向平移），面板上明确标注；
 * * 没有碎片时显示空状态并说明原因。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { formatBytes, truncate } from '../../lib/format';
import { cubeSelfCheck, displayToAuthority } from '../../lib/display';
import { disposeObject, loadDerivedGlb, type GlbMeasurement } from '../../lib/glb';
import { Badge, EmptyState, ErrorState, LoadingState } from '../states';

export interface FragmentRef {
  fragment_id: string;
  asset_id: string;
  role: string;
  file_key: string;
  volume_mm3?: number | null;
  label?: string;
  /** 权威面属性推出来的断面分组（来自清单 metrics，不是前端推断）。 */
  surface_groups?: Record<string, { faces?: number; area_mm2?: number; material?: string }>;
  /** 导出后逐字节复算的几何一致性测量（GLB vs 权威派生数组）。 */
  geometry_check?: {
    position_max_abs_error_vs_authority_m?: number;
    winding_matches_authority?: boolean;
    triangles_in_glb?: number;
    authority_faces?: number;
    mismatches?: string[];
  };
}

export interface FragmentAssemblyViewportProps {
  fragments: FragmentRef[];
  /** 爆炸位移上限（展示米）；0 = 原位。 */
  explode: number;
  height?: number;
  title?: string;
  onLoadInfo?: (info: GlbMeasurement[] | null) => void;
}

interface LoadedFragment {
  ref: FragmentRef;
  object: THREE.Group;
  measurement: GlbMeasurement;
  centerM: THREE.Vector3;
}

/** 展示材质名 → 权威断面分组（`_display_surface_groups` 写进 GLB 的材质名）。 */
export const SURFACE_MATERIAL_GROUPS: Record<string, string> = {
  synlab_display_new_fracture_surface: 'new_fracture_surface',
  synlab_display_original_surface: 'original_mother_surface',
  synlab_display_ambiguous_surface: 'ambiguous_surface',
};

/** 权威断面分组的文案（分组本身来自权威面属性 origin_kind / interface_id）。 */
export const SURFACE_GROUP_LABELS: Record<string, string> = {
  new_fracture_surface: '新断面（权威 origin_kind=INTERFACE / interface_id≥0）',
  original_mother_surface: '原表面（权威 origin_kind=mother_surface）',
  ambiguous_surface: '未判定面（权威 origin_kind=ambiguous）',
};

export interface SurfaceLegendRow {
  /** GLB 里真实的材质名（图例的一等公民：没有这个材质就不会出现在图例里）。 */
  material: string;
  group: string | null;
  label: string;
  colorHex: string | null;
  /** 本次加载的三维几何里该材质覆盖的三角面数（浏览器实测）。 */
  displayTriangles: number;
  /** 清单里该分组的权威面数与面积（来自 fragment.mesh 的面属性，单位 mm²）。 */
  authorityFaces: number | null;
  authorityAreaMm2: number | null;
}

export function collectSurfaceLegend(
  measurements: GlbMeasurement[],
  fragments: FragmentRef[],
): SurfaceLegendRow[] {
  const authority = new Map<string, { faces: number; area: number }>();
  for (const fragment of fragments) {
    for (const [group, row] of Object.entries(fragment.surface_groups ?? {})) {
      const current = authority.get(group) ?? { faces: 0, area: 0 };
      current.faces += Number(row?.faces ?? 0);
      current.area += Number(row?.area_mm2 ?? 0);
      authority.set(group, current);
    }
  }
  const rows = new Map<string, SurfaceLegendRow>();
  for (const measurement of measurements) {
    for (const group of measurement.materialGroups ?? []) {
      const existing = rows.get(group.material);
      if (existing) {
        existing.displayTriangles += group.triangles;
        continue;
      }
      const surface = SURFACE_MATERIAL_GROUPS[group.material] ?? null;
      const authorityRow = surface ? authority.get(surface) : undefined;
      rows.set(group.material, {
        material: group.material,
        group: surface,
        label: surface ? SURFACE_GROUP_LABELS[surface] ?? surface : group.material,
        colorHex: group.colorHex,
        displayTriangles: group.triangles,
        authorityFaces: authorityRow ? authorityRow.faces : null,
        authorityAreaMm2: authorityRow ? authorityRow.area : null,
      });
    }
  }
  return [...rows.values()].sort((a, b) => {
    const order = ['new_fracture_surface', 'original_mother_surface', 'ambiguous_surface'];
    const ai = a.group ? order.indexOf(a.group) : order.length;
    const bi = b.group ? order.indexOf(b.group) : order.length;
    return ai === bi ? b.displayTriangles - a.displayTriangles : ai - bi;
  });
}

export function FragmentAssemblyViewport({
  fragments,
  explode,
  height = 360,
  title = '碎片装配视图',
  onLoadInfo,
}: FragmentAssemblyViewportProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const loadedRef = useRef<LoadedFragment[]>([]);
  const frameRef = useRef<number | null>(null);
  const infoCallbackRef = useRef(onLoadInfo);
  infoCallbackRef.current = onLoadInfo;

  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<unknown>(null);
  const [measurements, setMeasurements] = useState<GlbMeasurement[]>([]);
  const [failures, setFailures] = useState<Array<{ fragment_id: string; message: string }>>([]);
  const [wireframe, setWireframe] = useState(false);
  const selfCheck = useMemo(() => cubeSelfCheck(100), []);

  /* ------------------------------------------------------------ 渲染器（挂载一次） */
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x11151c);
    sceneRef.current = scene;
    const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 5000);
    camera.position.set(0.3, 0.24, 0.3);
    cameraRef.current = camera;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controlsRef.current = controls;
    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(0.5, 1, 0.8);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.5);
    fill.position.set(-0.6, 0.3, -0.7);
    scene.add(fill);
    scene.add(new THREE.AxesHelper(0.15));
    const resize = () => {
      const width = mount.clientWidth || 480;
      const heightPx = mount.clientHeight || height;
      renderer.setSize(width, heightPx, false);
      camera.aspect = width / heightPx;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    const tick = () => {
      frameRef.current = window.requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();
    return () => {
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
      observer.disconnect();
      controls.dispose();
      for (const item of loadedRef.current) {
        scene.remove(item.object);
        disposeObject(item.object);
      }
      loadedRef.current = [];
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, [height]);

  /* ------------------------------------------------------------ 载入碎片 GLB */
  const fragmentKey = useMemo(
    () => fragments.map((f) => `${f.asset_id}:${f.role}:${f.file_key}`).join('|'),
    [fragments],
  );

  useEffect(() => {
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!scene || !camera || !controls) return undefined;

    for (const item of loadedRef.current) {
      scene.remove(item.object);
      disposeObject(item.object);
    }
    loadedRef.current = [];
    setFailures([]);
    setMeasurements([]);
    infoCallbackRef.current?.(null);

    if (fragments.length === 0) {
      setStatus('idle');
      return undefined;
    }

    let cancelled = false;
    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    const load = async () => {
      const loaded: LoadedFragment[] = [];
      const problems: Array<{ fragment_id: string; message: string }> = [];
      for (const ref of fragments) {
        try {
          const { object, measurement } = await loadDerivedGlb(ref.asset_id, {
            role: ref.role,
            fileKey: ref.file_key,
            signal: controller.signal,
            source: 'showcase',
          });
          if (cancelled) {
            disposeObject(object);
            return;
          }
          object.name = `fragment:${ref.fragment_id}`;
          scene.add(object);
          const box = new THREE.Box3().setFromObject(object);
          const center = new THREE.Vector3();
          box.getCenter(center);
          loaded.push({ ref, object, measurement, centerM: center });
        } catch (caught) {
          if (cancelled) return;
          if (caught instanceof DOMException && caught.name === 'AbortError') return;
          problems.push({
            fragment_id: ref.fragment_id,
            message: `${(caught as Error)?.name ?? 'Error'}: ${(caught as Error)?.message ?? String(caught)}`,
          });
        }
      }
      if (cancelled) return;
      loadedRef.current = loaded;
      setFailures(problems);
      const infos = loaded.map((item) => item.measurement);
      setMeasurements(infos);
      infoCallbackRef.current?.(infos);
      if (loaded.length === 0) {
        setError(new Error(problems[0]?.message ?? '没有碎片 GLB 被成功加载'));
        setStatus('error');
        return;
      }
      const box = new THREE.Box3();
      for (const item of loaded) box.expandByObject(item.object);
      const size = new THREE.Vector3();
      const center = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(center);
      for (const item of loaded) {
        item.object.position.sub(center);
      }
      const radius = Math.max(size.length() / 2, 0.02);
      const distance = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.8;
      camera.position.set(distance * 0.7, distance * 0.55, distance * 0.8);
      camera.near = Math.max(0.0005, radius / 200);
      camera.far = Math.max(10, radius * 400);
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();
      setStatus('ready');
    };
    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fragmentKey]);

  /* ------------------------------------------------------------ 爆炸（纯展示变换） */
  useEffect(() => {
    for (const item of loadedRef.current) {
      if (explode <= 0) {
        item.object.position.set(0, 0, 0);
        continue;
      }
      const direction = item.centerM.clone();
      if (direction.lengthSq() < 1e-12) direction.set(0, 1, 0);
      direction.normalize().multiplyScalar(explode);
      item.object.position.copy(direction);
    }
  }, [explode, status]);

  /* ------------------------------------------------------------ 线框（只改展示） */
  useEffect(() => {
    for (const item of loadedRef.current) {
      item.object.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if (!mesh.isMesh) return;
        const material = mesh.material as THREE.Material | THREE.Material[];
        for (const entry of Array.isArray(material) ? material : [material]) {
          const standard = entry as THREE.MeshStandardMaterial;
          if ('wireframe' in standard) standard.wireframe = wireframe;
          entry.needsUpdate = true;
        }
      });
    }
  }, [wireframe, status]);

  const totalTriangles = measurements.reduce((sum, item) => sum + item.triangleCount, 0);
  const meshesWithoutNormal = measurements.reduce(
    (sum, item) => sum + (item.meshesWithoutNormal ?? 0),
    0,
  );
  const legend = useMemo(
    () => collectSurfaceLegend(measurements, fragments),
    [measurements, fragments],
  );
  const legendIsSplit = legend.some((row) => row.group !== null);
  const geometryChecks = fragments
    .map((fragment) => fragment.geometry_check)
    .filter((check): check is NonNullable<FragmentRef['geometry_check']> => Boolean(check));
  const maxPositionError = geometryChecks.length
    ? Math.max(...geometryChecks.map((check) => Number(check.position_max_abs_error_vs_authority_m ?? 0)))
    : null;
  const windingOk = geometryChecks.length
    ? geometryChecks.every((check) => check.winding_matches_authority !== false)
    : null;
  const authorityFacesSum = legendIsSplit
    ? legend.reduce((sum, row) => sum + Number(row.authorityFaces ?? 0), 0)
    : null;
  const displayTrianglesSum = legendIsSplit
    ? legend.reduce((sum, row) => sum + row.displayTriangles, 0)
    : null;
  const authorityFacesTotal = fragments.reduce(
    (sum, fragment) => sum + Number(fragment.geometry_check?.authority_faces ?? 0),
    0,
  );
  const centerAuthority =
    measurements.length > 0
      ? displayToAuthority(measurements[0].displayCenterM).map((v) => v.toFixed(3)).join(', ')
      : null;

  return (
    <div className="viewport">
      <div className="viewport__head">
        <div className="viewport__title">
          {title}
          <Badge tone="info">展示：m / Y-up</Badge>
          <Badge tone="neutral">权威：mm / Z-up</Badge>
          <Badge tone={explode > 0 ? 'warn' : 'ok'}>
            {explode > 0 ? `爆炸视图（展示位移 ${explode.toFixed(3)} m）` : '原位'}
          </Badge>
          {status === 'ready' ? (
            <Badge tone={meshesWithoutNormal === 0 ? 'ok' : 'bad'}>
              {meshesWithoutNormal === 0
                ? `平滑着色：${measurements.reduce((sum, item) => sum + (item.meshesWithNormal ?? 0), 0)} 个 mesh 全带 NORMAL`
                : `${meshesWithoutNormal} 个 mesh 缺 NORMAL（three.js 会 flatShading）`}
            </Badge>
          ) : null}
        </div>
        <div className="viewport__tools">
          <label className="check">
            <input
              type="checkbox"
              checked={wireframe}
              onChange={(event) => setWireframe(event.target.checked)}
              disabled={status !== 'ready'}
            />
            线框
          </label>
        </div>
      </div>

      <div className="viewport__canvas" ref={mountRef} style={{ height: `${height}px` }} />

      {status === 'loading' ? (
        <div className="viewport__overlay">
          <LoadingState label={`正在加载 ${fragments.length} 个碎片 GLB…`} />
        </div>
      ) : null}
      {status === 'error' ? (
        <div className="viewport__overlay">
          <ErrorState error={error} compact title="无法加载碎片 GLB" />
        </div>
      ) : null}
      {status === 'idle' ? (
        <div className="viewport__overlay">
          <EmptyState
            title="没有可显示的碎片"
            reason="该事件没有成功产出碎片（或碎片没有派生展示 GLB 资产）。这里不会绘制任何示意几何。"
          />
        </div>
      ) : null}

      <div className="viewport__foot">
        <div className="viewport__scale">
          <Badge tone={selfCheck.ok ? 'ok' : 'bad'}>
            {selfCheck.ok ? '100 mm 解析立方体自检通过' : '立方体自检失败'}
          </Badge>
          <span className="mono">{selfCheck.detail}</span>
        </div>
        {status === 'ready' ? (
          <dl className="viewport__info">
            <div>
              <dt>碎片数 / 三角面</dt>
              <dd className="mono">
                {measurements.length} / {totalTriangles}
              </dd>
            </div>
            <div>
              <dt>GLB 字节合计</dt>
              <dd className="mono">
                {formatBytes(measurements.reduce((sum, item) => sum + item.bytes, 0))}
              </dd>
            </div>
            <div>
              <dt>服务端 sha256（首个碎片）</dt>
              <dd className="mono" title={measurements[0]?.serverSha256 ?? ''}>
                {measurements[0]?.serverSha256 ? truncate(measurements[0].serverSha256, 20) : '未提供'}
              </dd>
            </div>
            <div>
              <dt>坐标契约</dt>
              <dd className="mono">
                unit={measurements[0]?.unit ?? '?'} · frame={measurements[0]?.frame ?? '?'}
              </dd>
            </div>
            <div>
              <dt>装配中心 → 权威坐标</dt>
              <dd className="mono">{centerAuthority ?? '—'} mm</dd>
            </div>
          </dl>
        ) : null}
        {legendIsSplit ? (
          <div className="surface-legend">
            <div className="surface-legend__title">
              断面分色图例 —— 分组来自**权威面属性**（<code className="mono">origin_kind</code> /{' '}
              <code className="mono">interface_id</code>），色块取自 GLB 里真实的{' '}
              <code className="mono">material.baseColorFactor</code>
            </div>
            <ul className="surface-legend__list">
              {legend.map((row) => (
                <li key={row.material}>
                  <span
                    className="surface-legend__swatch"
                    style={{ background: row.colorHex ?? '#666' }}
                    aria-hidden="true"
                  />
                  <span className="surface-legend__label">{row.label}</span>
                  <span className="mono small">
                    显示三角面 {row.displayTriangles}
                    {row.authorityFaces !== null ? ` · 权威面 ${row.authorityFaces}` : ''}
                    {row.authorityAreaMm2 !== null
                      ? ` · 权威面积 ${row.authorityAreaMm2.toFixed(3)} mm²`
                      : ''}
                    {` · 材质 ${row.material}`}
                  </span>
                </li>
              ))}
            </ul>
            {displayTrianglesSum !== null && authorityFacesSum !== null ? (
              <p className="muted small mono">
                一致性：显示分组面数合计 {displayTrianglesSum} = 权威分组面数合计 {authorityFacesSum}
                {authorityFacesTotal ? `（本次事件权威碎片面数合计 ${authorityFacesTotal}）` : ''}
                {maxPositionError !== null
                  ? ` · GLB 顶点位置与权威最大偏差 ${maxPositionError.toExponential(2)} m（float32 舍入）`
                  : ''}
                {windingOk !== null ? ` · 绕向与权威一致：${windingOk ? '是' : '否'}` : ''}
              </p>
            ) : null}
            <p className="muted small">
              这是<b>显示着色</b>，<b>不代表几何真实起伏</b>：新断面与原表面是同一批顶点、同一批三角面，
              只是按权威面属性分成两个 primitive 换了个颜色。真实断口起伏需要{' '}
              <code className="mono">rough_shared_cut</code> 后端（本机 FAILED）或{' '}
              <code className="mono">warped_partition</code>（PENDING）/
              <code className="mono">fracture_modes</code>（MISSING）；页面对未实现的部分不做任何
              噪声位移或几何替换。
            </p>
          </div>
        ) : null}
        {failures.length > 0 ? (
          <div className="state state--error state--compact" role="alert">
            <div className="state__title">
              有 {failures.length} 个碎片 GLB 加载失败（其余照常显示）
            </div>
            <ul>
              {failures.map((item) => (
                <li key={item.fragment_id} className="mono small">
                  {item.fragment_id}: {item.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="muted">
          爆炸视图是纯展示变换（沿每个碎片包围盒中心方向平移 {explode.toFixed(3)} m），
          不写回任何权威资产；碎片几何始终是权威 mm/Z-up 的派生 GLB。
          {measurements.length > 0
            ? ` 权威尺寸示例：${measurements[0].authorityExtentMm.map((v: number) => v.toFixed(2)).join(' × ')} mm。`
            : ''}
        </p>
        <p className="muted small">
          当前显示的是展示几何 <b>L0 的平滑着色</b>（逐顶点 NORMAL 由权威网格算出：面积加权 +
          角度阈值 + 保持绕向；权威几何未变，清单里每个 GLB 都带导出后逐字节复算的{' '}
          <code className="mono">geometry_unchanged</code> 与{' '}
          <code className="mono">normals</code> 测量值）。
          若轮廓仍显棱角，那是 L0 网格本身的离散化限制，不是着色能修的；可选展示策略是改用清单里
          已实测的 L1/L2 层级 + 同一套平滑法线，那会<b>降低</b>几何精度、不会让几何更精细。
        </p>
        {measurements.length > 0 ? (
          <p className="muted small mono">
            原始（未爆炸）包围盒中心：
            {measurements
              .map((item: GlbMeasurement) => `[${item.displayCenterM.map((v: number) => v.toFixed(4)).join(',')}]`)
              .join(' ')}{' '}
            m
          </p>
        ) : null}
      </div>
    </div>
  );
}
