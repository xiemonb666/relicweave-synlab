import { Link } from 'react-router-dom';

import { EmptyState, PageHeader, SectionCard } from '../components/states';

export function NotFoundPage() {
  return (
    <>
      <PageHeader
        title="页面不存在"
        plan="404"
        summary="当前路由不在 A12 合成实验室的 12 个页面之内。本应用没有为未知路由准备任何占位数据。"
      />
      <SectionCard title="可用页面" subtitle="12 个页面（计划 20.2–20.13）">
        <EmptyState
          title="没有匹配的路由"
          reason="请从左侧导航进入：概览 / 母体编辑 / 花纹编辑 / 断裂预览 / 退化对比 / 相机与采集档 / 批量生成与任务 / 数据发布 / 预训练 / 诊断面板 / 主动观察 / 质量与故障。"
          action={
            <Link className="btn btn--primary" to="/synlab">
              返回概览
            </Link>
          }
        />
      </SectionCard>
    </>
  );
}
