/**
 * ActiveJobBadge — 전역 진행 중 작업 표시 배지
 *
 * ProjectContext.activeJob 이 set 되어 있으면 헤더 우측에 "분석 중..." 뱃지 표시.
 * 어느 페이지에 있든 보임 → 사용자가 다른 페이지로 이동해도 작업 상태 인지 가능.
 *
 * 2026-04-20: sessionStorage 복구로 인해 새로고침 시에도 배지 유지.
 *   stale 방지 — 마운트 시 백엔드 status 단발 체크 → done/error면 즉시 클리어.
 */
import { useEffect } from 'react';
import axios from 'axios';
import { RefreshCw } from 'lucide-react';
import { useProject } from '../context/ProjectContext';
import { useAuth } from '../context/AuthContext';
import { getJob } from '../lib/api';

const JOB_TYPE_LABEL: Record<string, string> = {
  detect: '도면 분석',
  brand: '브랜드 추출',
  space_data: '공간 계산',
  place: '배치 생성',
  export: '내보내기',
};

export default function ActiveJobBadge() {
  const { activeJob, setActiveJob } = useProject();
  const { currentUser } = useAuth();

  // 마운트/복원 시 단발 status 체크 — done/error면 stale 배지 즉시 제거
  useEffect(() => {
    if (!activeJob || !currentUser) return;
    let cancelled = false;
    (async () => {
      try {
        const job = await getJob(activeJob.id);
        if (cancelled) return;
        if (job.status === 'done' || job.status === 'error') {
          setActiveJob(null);
        }
      } catch (e) {
        // 404 = job 이 cascade 삭제됨 → stale 배지 즉시 정리
        // 그 외 (네트워크 일시 오류 등) 는 무시 — 배지 유지
        if (axios.isAxiosError(e) && e.response?.status === 404) {
          setActiveJob(null);
        }
      }
    })();
    return () => { cancelled = true; };
    // activeJob.id가 바뀌거나 유저가 바뀌면 재체크
  }, [activeJob?.id, currentUser?.id, setActiveJob, activeJob]);

  if (!activeJob) return null;

  const label = JOB_TYPE_LABEL[activeJob.type] ?? activeJob.type;

  return (
    <div className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-[11px] text-amber-400 font-bold">
      <RefreshCw size={11} className="animate-spin" />
      <span>{label}중</span>
    </div>
  );
}
