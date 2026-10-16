import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * 数据来源说明（计划 20.14 / 25.2）：
 * 前端不做任何静态数据兜底，所有请求都打到真实的 `synlab.api.app:create_app`。
 * dev / preview 都把 `/api` 反代到本机后端，避免 CORS 且保证 build 产物行为一致；
 * 需要直连其它地址时用 `VITE_SYNLAB_API_BASE`（客户端会直接拼 `/api/synlab`）。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.VITE_SYNLAB_PROXY_TARGET || 'http://127.0.0.1:8077';
  const proxy = {
    '/api': { target, changeOrigin: true, ws: false },
  };
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: false, proxy },
    preview: { port: 4173, strictPort: false, proxy },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 2000,
    },
  };
});
