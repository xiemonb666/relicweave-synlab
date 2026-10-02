import { defineConfig } from '@playwright/test';

/**
 * 真实端到端配置：**同时**启动真实后端（`synlab.api.app:create_app` 通过
 * `tests/a12/api_ui/_serve.py`）与构建产物预览（`vite preview`，`/api` 反代到后端）。
 *
 * 环境变量（都有默认值，默认指向仓库里真实存在的演示数据根 `data/a12_demo/store`）：
 * | 变量 | 作用 |
 * |---|---|
 * | `SYNLAB_E2E_STORE` | 后端 store_root（默认 `../data/a12_demo/store`） |
 * | `SYNLAB_E2E_BACKEND_PORT` | 后端端口（默认 8081） |
 * | `SYNLAB_E2E_PREVIEW_PORT` | 预览端口（默认 4178） |
 * | `SYNLAB_E2E_PYTHON` | python 可执行文件（默认 `../.venv/Scripts/python.exe`） |
 *
 * `reuseExistingServer` 为 true：已经手动起好后端/预览时会直接复用，不会重复占端口。
 */
const BACKEND_PORT = Number(process.env.SYNLAB_E2E_BACKEND_PORT ?? 8081);
const PREVIEW_PORT = Number(process.env.SYNLAB_E2E_PREVIEW_PORT ?? 4178);
const STORE = process.env.SYNLAB_E2E_STORE ?? '../data/a12_demo/store';
const PYTHON = process.env.SYNLAB_E2E_PYTHON ?? '..\\.venv\\Scripts\\python.exe';

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 30_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PREVIEW_PORT}`,
    viewport: { width: 1440, height: 1000 },
    trace: 'off',
  },
  webServer: [
    {
      command: `"${PYTHON}" ../tests/a12/api_ui/_serve.py --store-root "${STORE}" --port ${BACKEND_PORT} --role researcher`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/synlab/health`,
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `node node_modules/vite/bin/vite.js preview --port ${PREVIEW_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${PREVIEW_PORT}/synlab`,
      reuseExistingServer: true,
      timeout: 180_000,
      env: { VITE_SYNLAB_PROXY_TARGET: `http://127.0.0.1:${BACKEND_PORT}` },
    },
  ],
});
