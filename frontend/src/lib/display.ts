/**
 * 展示坐标系 ↔ 权威坐标系转换（计划 20.14.1，对应后端 `synlab/api/display.py`）。
 *
 * * 权威几何：**毫米、右手、Z-up**；
 * * GLB/glTF 展示几何：**米、Y-up**。
 *
 * `T_display_authority` 在派生展示资产时应用**恰好一次**，量尺反算时用其逆也**恰好一次**。
 * 应用两次就是经典的 1000 倍尺度错误，所以这里只暴露 `authorityToDisplay` /
 * `displayToAuthority` 两个入口，并用 100 mm 立方体自检（见 `cubeSelfCheck`）。
 */

export const MM_PER_M = 1000;
export const AUTHORITY_UNIT = 'mm';
export const DISPLAY_UNIT = 'm';
export const AUTHORITY_UP_AXIS = 'Z' as const;
export const DISPLAY_UP_AXIS = 'Y' as const;

export type Vec3 = [number, number, number];

/** 行主序 4x4，与后端 `T_DISPLAY_AUTHORITY` 完全一致。 */
export const T_DISPLAY_AUTHORITY: readonly number[][] = [
  [0.001, 0, 0, 0],
  [0, 0, 0.001, 0],
  [0, -0.001, 0, 0],
  [0, 0, 0, 1],
];

/** `T_DISPLAY_AUTHORITY` 的精确逆（基变换不引入浮点漂移）。 */
export const T_AUTHORITY_DISPLAY: readonly number[][] = [
  [1000, 0, 0, 0],
  [0, 0, -1000, 0],
  [0, 1000, 0, 0],
  [0, 0, 0, 1],
];

function apply(matrix: readonly number[][], point: Vec3): Vec3 {
  const [x, y, z] = point;
  return [
    matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
    matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
    matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
  ];
}

/** mm/Z-up → m/Y-up，恰好一次。 */
export function authorityToDisplay(pointMm: Vec3): Vec3 {
  return apply(T_DISPLAY_AUTHORITY, pointMm);
}

/** m/Y-up → mm/Z-up，恰好一次（`authorityToDisplay` 的逆）。 */
export function displayToAuthority(pointM: Vec3): Vec3 {
  return apply(T_AUTHORITY_DISPLAY, pointM);
}

export function scaleToAuthorityLength(lengthDisplayM: number): number {
  return lengthDisplayM * MM_PER_M;
}

export function scaleToDisplayLength(lengthMm: number): number {
  return lengthMm / MM_PER_M;
}

/** 把展示空间的包围盒尺寸（米）转成权威 mm 三元组。 */
export function displayExtentToAuthority(extentM: Vec3): Vec3 {
  const [x, y, z] = extentM.map((value) => Math.abs(value) * MM_PER_M) as Vec3;
  return [x, y, z];
}

export interface CubeSelfCheck {
  ok: boolean;
  authorityExtentMm: Vec3;
  displayExtentM: Vec3;
  roundTripExtentMm: Vec3;
  maxErrorMm: number;
  toleranceMm: number;
  detail: string;
}

/** 100 mm 立方体的 8 顶点（权威 mm/Z-up，与 API 测试 fixture 相同）。 */
export function cubeVerticesMm(edgeMm = 100): Vec3[] {
  const half = edgeMm / 2;
  return [
    [-half, -half, -half],
    [half, -half, -half],
    [half, half, -half],
    [-half, half, -half],
    [-half, -half, half],
    [half, -half, half],
    [half, half, half],
    [-half, half, half],
  ];
}

function extentOf(points: readonly Vec3[]): Vec3 {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const point of points) {
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis], point[axis]);
      max[axis] = Math.max(max[axis], point[axis]);
    }
  }
  return [max[0] - min[0], max[1] - min[1], max[2] - min[2]];
}

/**
 * 解析立方体自检：权威 100 mm → 展示米 → 反算 mm，必须仍是 100 mm。
 * 展示空间三轴尺寸都是 0.1 m；反算回来三轴都必须是 100 mm。
 */
export function cubeSelfCheck(edgeMm = 100, toleranceMm = 1e-6): CubeSelfCheck {
  const authority = cubeVerticesMm(edgeMm);
  const display = authority.map(authorityToDisplay);
  const displayExtentM = extentOf(display);
  const roundTrip = display.map(displayToAuthority);
  const roundTripExtentMm = extentOf(roundTrip);
  const authorityExtentMm = extentOf(authority);
  const maxErrorMm = Math.max(
    ...roundTripExtentMm.map((value, axis) => Math.abs(value - authorityExtentMm[axis])),
    ...displayExtentM.map((value) => Math.abs(value * MM_PER_M - edgeMm)),
  );
  const ok = maxErrorMm <= toleranceMm;
  return {
    ok,
    authorityExtentMm,
    displayExtentM,
    roundTripExtentMm,
    maxErrorMm,
    toleranceMm,
    detail: ok
      ? `${edgeMm} mm 立方体：展示 ${displayExtentM.map((v) => v.toFixed(4)).join(' × ')} m，反算 ${roundTripExtentMm
          .map((v) => v.toFixed(4))
          .join(' × ')} mm，误差 ${maxErrorMm.toExponential(2)} mm`
      : `尺度自检失败：误差 ${maxErrorMm} mm 超过容差 ${toleranceMm} mm`,
  };
}

/** 展示空间（m）的 mm 标尺刻度，按 1/2/5 序列取整。 */
export function mmTicks(extentM: number, target = 6): number[] {
  const extentMm = Math.abs(extentM) * MM_PER_M;
  if (!Number.isFinite(extentMm) || extentMm <= 0) return [];
  const raw = extentMm / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = (normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1) * magnitude;
  const ticks: number[] = [];
  for (let value = 0; value <= extentMm + step * 0.5; value += step) ticks.push(Number(value.toFixed(6)));
  return ticks;
}
