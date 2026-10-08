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
