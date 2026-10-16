/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端基址；留空表示同源（dev/preview 由 vite proxy 反代 /api）。 */
  readonly VITE_SYNLAB_API_BASE?: string;
  /** vite dev/preview 的 /api 反代目标。 */
  readonly VITE_SYNLAB_PROXY_TARGET?: string;
  /** 只有显式设为 "1" 时才允许启用测试 fixture 兜底（UI 会打上醒目标记）。 */
  readonly VITE_SYNLAB_FIXTURES?: string;
  /** 可选：覆盖 X-SynLab-Role 请求头（默认不发送，使用服务端启动的角色）。 */
  readonly VITE_SYNLAB_ROLE?: string;
  /** 可选：覆盖 X-SynLab-Session 请求头。 */
  readonly VITE_SYNLAB_SESSION?: string;
  /** 可选：覆盖 X-SynLab-Workspace 请求头。 */
  readonly VITE_SYNLAB_WORKSPACE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
