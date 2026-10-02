import { Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from './components/Layout';
import { OverviewPage } from './pages/Overview';
import { MotherEditorPage } from './pages/MotherEditor';
import { PatternsPage } from './pages/Patterns';
import { FracturePage } from './pages/Fracture';
import { DegradationPage } from './pages/Degradation';
import { CameraProfilesPage } from './pages/CameraProfiles';
import { JobsPage } from './pages/Jobs';
import { ReleasesPage } from './pages/Releases';
import { TrainingPage } from './pages/Training';
import { DiagnosticsPage } from './pages/Diagnostics';
import { EpisodesPage } from './pages/Episodes';
import { QualityPage } from './pages/Quality';
import { ShowcasePage } from './pages/Showcase';
import { NotFoundPage } from './pages/NotFound';

/** 12 个页面 + 首页重定向 + 404（计划 20.2–20.13）+ U13 合成数据展示页。 */
export function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/synlab" replace />} />
        <Route path="synlab" element={<OverviewPage />} />
        <Route path="synlab/mothers/new" element={<MotherEditorPage />} />
        <Route path="synlab/patterns" element={<PatternsPage />} />
        <Route path="synlab/fracture" element={<FracturePage />} />
        <Route path="synlab/degradation" element={<DegradationPage />} />
        <Route path="synlab/camera-profiles" element={<CameraProfilesPage />} />
        <Route path="synlab/jobs" element={<JobsPage />} />
        <Route path="synlab/releases" element={<ReleasesPage />} />
        <Route path="synlab/training" element={<TrainingPage />} />
        <Route path="synlab/diagnostics" element={<DiagnosticsPage />} />
        <Route path="synlab/episodes" element={<EpisodesPage />} />
        <Route path="synlab/quality" element={<QualityPage />} />
        <Route path="synlab/showcase" element={<ShowcasePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
