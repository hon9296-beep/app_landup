/**
 * AnalysisReportPreview — 임시 dev 전용 페이지.
 *
 * 목적: AnalysisReport 컴포넌트 렌더 확인용. 대시보드 완성 후 제거 예정.
 * 경로: /report-preview
 * 대시보드 완성 시: AppRoutes.tsx 의 /report-preview 라우트 + 본 파일 전부 삭제.
 */
import AnalysisReport from '../components/mypage/AnalysisReport';

export default function AnalysisReportPreview() {
  return (
    <main className="w-full max-w-6xl mx-auto px-6 py-8">
      <div className="text-xs text-slate-500 mb-4 font-bold">
        [DEV PREVIEW] /report-preview — 대시보드 완성 후 본 라우트/페이지 제거
      </div>
      <AnalysisReport />
    </main>
  );
}
