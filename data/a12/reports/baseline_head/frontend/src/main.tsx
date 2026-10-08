import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App';
import { AppStateProvider } from './state/app-state';
import './styles.css';
// U13 合成数据展示页的样式（独立文件，避免与既有样式表互相覆盖）
import './styles-showcase.css';

/**
 * 不启用 React.StrictMode：StrictMode 在开发模式下会双挂载组件，而三维视口会因此创建/销毁
 * 两个 WebGL 上下文（真实 GPU 资源），产生无意义的上下文丢失告警。生产构建行为一致。
 */
const container = document.getElementById('root');
if (!container) throw new Error('未找到 #root 挂载点');

createRoot(container).render(
  <BrowserRouter>
    <AppStateProvider>
      <App />
    </AppStateProvider>
  </BrowserRouter>,
);
