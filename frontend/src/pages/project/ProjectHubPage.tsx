/**
 * ProjectHubPage — 프로젝트 허브 (랜딩 ↔ /project/new 사이)
 *
 * 단일 리스트: 프로젝트별로 열기/GLB/보고서/편집/삭제 버튼 한 줄에.
 * (구 4탭 구조 → 1탭 통합, 2026-04-20)
 *
 * 스타일: docs/2026-04-23_frontend_style_guide.md 따름.
 *   - border-border / rounded-2xl / text-sm 기본 / font-bold
 *   - 랜딩과 /project/new 사이 허브라서 약간 큼직
 */
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Download, FileSearch, ExternalLink, Trash2, Edit2,
  Check, X, RefreshCw, Plus,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useProject } from '../../context/ProjectContext';
import { useToast } from '../../context/ToastContext';
import { getMyProjects, getProject, deleteProject, renameProject, USE_DIRECT } from '../../lib/api';
import { getPlanLimits } from '../../lib/paymentApi';
import LimitExceededModal from '../../components/LimitExceededModal';
import type { UserProjectListItem } from '../../types/project';

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

export default function ProjectHubPage() {
  const navigate = useNavigate();
  const { currentUser, authLoading } = useAuth();
  const { toast } = useToast();
  const {
    setSpaceData, setPlacementResult, setAutoDetected, setBrandExtraction,
    setProjectId, setFloorArchiveId, setBrandManualId, setFloorDetectionId,
    setResumingFilename,
    activeJob, setActiveJob, projectId: activeProjectId,
    reset,
  } = useProject();

  const stageMeta = (p: UserProjectListItem): { label: string; tone: 'done' | 'error' | 'progress' | 'waiting' } => {
    if (p.stage === 'done') return { label: '완료', tone: 'done' };
    if (p.stage === 'error') return { label: '실패', tone: 'error' };
    const isThisProjectActive = activeProjectId === p.id && !!activeJob;
    if (p.stage === 'detecting') return { label: '도면 분석중', tone: 'progress' };
    if (p.stage === 'space_ready') {
      if (isThisProjectActive && activeJob?.type === 'space_data') return { label: '공간 분석중', tone: 'progress' };
      return { label: '공간 분석 대기', tone: 'waiting' };
    }
    if (p.stage === 'place_ready') {
      if (isThisProjectActive && activeJob?.type === 'place') return { label: '배치 생성중', tone: 'progress' };
      return { label: '배치 생성 대기', tone: 'waiting' };
    }
    return { label: '대기', tone: 'waiting' };
  };

  const [list, setList] = useState<UserProjectListItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [opening, setOpening] = useState<number | null>(null);
  const [concurrentFull, setConcurrentFull] = useState(false);
  const [projectLimit, setProjectLimit] = useState<{ message: string; membership: string } | null>(null);
  const [showProjectLimitModal, setShowProjectLimitModal] = useState(false);

  const fetchList = async () => {
    if (!currentUser) return;
    // [LOCAL_TEST_USE_DIRECT] Java 미가동 환경 — 프로젝트 목록 fetch skip, 빈 상태 유지
    //  Python 직통 모드는 DB 미경유라 프로젝트 영속화가 없음 → 새 프로젝트 시작만 가능
    if (USE_DIRECT) {
      setList([]);
      setLoading(false);
      setError('');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const data = await getMyProjects();
      setList(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '목록 조회 실패');
    } finally {
      setLoading(false);
    }
  };

  // authLoading이 true인 동안은 토큰 복원 중 → fetch skip (race condition 방어)
  useEffect(() => {
    if (authLoading) return;
    void fetchList();
    if (!USE_DIRECT && currentUser) {
      getPlanLimits()
        .then(s => {
          setConcurrentFull(s.usedConcurrent >= s.maxConcurrent);
          const isBasic = s.membership === 'basic';
          if (s.usedProjects >= s.maxProjects && (isBasic || s.creditBalance < 3)) {
            const msg = isBasic
              ? `이번 달 무료 프로젝트를 모두 사용했어요. Premium은 월 3개, Max는 월 10개까지 만들 수 있어요.`
              : `이번 달 프로젝트 ${s.maxProjects}개를 모두 사용했어요. Max 플랜으로 업그레이드하면 월 10개까지 자유롭게 만들 수 있어요.`;
            setProjectLimit({ message: msg, membership: s.membership });
          }
        })
        .catch(() => {});
    }
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [currentUser?.id, authLoading]);

  const handleNew = () => {
    if (projectLimit) {
      setShowProjectLimitModal(true);
      return;
    }
    reset();
    navigate('/project/new');
  };

  const handleOpen = async (projectId: number, listItem?: UserProjectListItem) => {
    if (!currentUser) return;
    if (USE_DIRECT) {
      toast.info('직통 모드는 저장된 프로젝트 열기 미지원 — "+ 새 프로젝트" 로 시작하세요');
      return;
    }
    setOpening(projectId);
    try {
      const detail = await getProject(projectId);
      setProjectId(detail.id ?? projectId);
      setResumingFilename(listItem?.original_filename ?? null);
      if (detail.floor_archive_id) setFloorArchiveId(detail.floor_archive_id);
      if (detail.brand_manual_id) setBrandManualId(detail.brand_manual_id);
      if (detail.floor_detection_id) setFloorDetectionId(detail.floor_detection_id);
      // 2026-05-01 — 백엔드는 pages_json (JSON string) 으로 응답. JSON.parse 후 사용.
      let analysisData: any = null;
      if ((detail as any).pages_json) {
        try { analysisData = JSON.parse((detail as any).pages_json); }
        catch { analysisData = null; }
      }
      if (analysisData) setAutoDetected(analysisData);
      if (detail.brand_data) setBrandExtraction(detail.brand_data);
      if (detail.space_data) setSpaceData(detail.space_data);
      if (detail.layout_objects && detail.layout_objects.length > 0) {
        setPlacementResult({
          layout_objects: detail.layout_objects,
          validation: { status: 'ok', violations: [] },
          sub_path: (detail as any).sub_path ?? [],
          // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 placement_result 에 박힘 (Hub 재진입 시 복원).
          main_artery: (detail as any).main_artery ?? null,
          // 2026-05-04 신설 - ref_quality_score (모달 트리거용). 0.0 ~ 1.0.
          ref_quality_score: (detail as any).ref_quality_score ?? null,
        } as never);
      } else {
        setPlacementResult(null);
      }
      if (detail.status === 'done' && detail.layout_objects && detail.layout_objects.length > 0) {
        navigate('/project/result');
      } else if (analysisData) {
        navigate('/project/floor');
      } else {
        navigate('/project/new');
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '프로젝트 로드 실패');
    } finally {
      setOpening(null);
    }
  };

  const handleDelete = async (projectId: number, name: string) => {
    if (!currentUser) return;
    if (USE_DIRECT) {
      toast.info('직통 모드는 DB 미경유 — 삭제 불요');
      return;
    }
    if (!confirm(`"${name}" 프로젝트를 삭제할까요? (복구 불가)`)) return;
    try {
      await deleteProject(projectId);
      // 삭제한 프로젝트가 sessionStorage 에 stale 로 남아있으면 정리 (활성 배지·resume 폴링 차단)
      if (activeProjectId === projectId || activeJob?.projectId === projectId) {
        setActiveJob(null);
        setProjectId(null);
        setFloorArchiveId(null);
        setBrandManualId(null);
        setFloorDetectionId(null);
        setResumingFilename(null);
      }
      toast.success('삭제 완료');
      void fetchList();
      getPlanLimits().then(s => setConcurrentFull(s.usedConcurrent >= s.maxConcurrent)).catch(() => {});
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '삭제 실패');
    }
  };

  const handleRenameSave = async (projectId: number) => {
    if (!currentUser) return;
    // 빈값 — 토스트 + 편집 모드 유지 (TR_D [프로젝트이름_빈값_무반응] fix)
    if (!editName.trim()) {
      toast.error('이름을 입력해주세요');
      return;
    }
    if (USE_DIRECT) {
      toast.info('직통 모드는 DB 미경유 — 이름 변경 불가');
      setEditing(null);
      return;
    }
    try {
      await renameProject(projectId, editName.trim());
      toast.success('이름 변경 완료');
      setEditing(null);
      void fetchList();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '이름 변경 실패');
    }
  };

  // GLB/보고서 다운로드 — API 연동 대기 (옆 세션에 요청)
  const handleDownloadGlb = (_projectId: number, name: string) => {
    toast.info(`"${name}" GLB 다운로드는 API 연동 대기 중`);
  };
  const handleDownloadReport = (_projectId: number, name: string) => {
    toast.info(`"${name}" 보고서 다운로드는 API 연동 대기 중`);
  };

  return (
    <>
    <main className="flex-1 flex flex-col px-8 py-10 fade-in">
      <div className="max-w-6xl w-full mx-auto">
        {/* 헤더 */}
        <div className="mb-8 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-3xl font-bold text-white mb-2">프로젝트</h2>
            <p className="text-sm text-slate-400">
              {currentUser ? (
                <>
                  <span className="text-white font-bold">{currentUser.name}</span> 님의 작업 공간 ·
                  {' '}멤버십 <span className="text-accent font-bold capitalize">{currentUser.membership}</span>
                </>
              ) : (
                <span className="text-amber-400">로그인 필요 (현재 게스트)</span>
              )}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            <button
              onClick={handleNew}
              disabled={concurrentFull}
              className="flex items-center gap-2 bg-primary text-white font-bold rounded-xl px-6 py-3 text-sm hover:bg-primary/90 transition-colors shadow-lg disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus size={18} /> 새 프로젝트
            </button>
            {concurrentFull && (
              <p className="text-[11px] text-amber-400">
                진행 중인 작업이 완료된 후 새 프로젝트를 시작할 수 있어요
              </p>
            )}
          </div>
        </div>

        {/* 리스트 — 1탭 통합 (구 내이력/작업내역/GLB/보고서) */}
        {loading ? (
          <div className="flex items-center justify-center py-16 text-slate-400 text-sm">
            <RefreshCw size={16} className="animate-spin mr-2" /> 목록 불러오는 중...
          </div>
        ) : error ? (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-2xl px-5 py-4 text-sm">
            {error}
            <button onClick={() => void fetchList()} className="ml-3 underline">다시 시도</button>
          </div>
        ) : !list || list.length === 0 ? (
          <div className="bg-slate-800 border border-border rounded-2xl p-10 text-center shadow-sm">
            <p className="text-slate-300 text-sm mb-4">아직 작업 이력이 없어요</p>
            <Link
              to="/project/new"
              className="inline-flex items-center gap-2 bg-primary text-white font-bold rounded-xl px-6 py-3 text-sm hover:bg-primary/90 transition-colors shadow-lg"
            >
              <Plus size={16} /> 새 프로젝트 시작하기
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {list.map(p => {
              const displayName = p.name || p.original_filename || '(이름 없음)';
              const isDone = p.stage === 'done';
              return (
                <div
                  key={p.id}
                  className="flex items-center justify-between gap-4 bg-slate-800 border border-border rounded-2xl px-5 py-4 hover:border-white/20 transition-colors shadow-sm"
                >
                  {/* 좌: 이름/상태/날짜 */}
                  <div className="flex-1 min-w-0">
                    {editing === p.id ? (
                      <div className="flex items-center gap-2">
                        <input
                          value={editName}
                          onChange={e => setEditName(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') void handleRenameSave(p.id); if (e.key === 'Escape') setEditing(null); }}
                          autoFocus
                          maxLength={50}
                          className="flex-1 bg-black/40 border border-border rounded-lg px-3 py-2 text-sm text-white"
                        />
                        <button onClick={() => void handleRenameSave(p.id)} className="p-1.5 text-accent hover:bg-white/10 rounded">
                          <Check size={16} />
                        </button>
                        <button onClick={() => setEditing(null)} className="p-1.5 text-slate-400 hover:bg-white/10 rounded">
                          <X size={16} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-base font-bold text-white truncate">{displayName}</p>
                          {(() => {
                            const meta = stageMeta(p);
                            const toneClass =
                              meta.tone === 'done'     ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40' :
                              meta.tone === 'error'    ? 'bg-red-500/15 text-red-400 border-red-500/40' :
                              meta.tone === 'progress' ? 'bg-amber-500/15 text-amber-400 border-amber-500/40' :
                                                         'bg-sky-500/15 text-sky-400 border-sky-500/40';
                            return (
                              <span className={`shrink-0 inline-flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded-full border ${toneClass}`}>
                                {meta.tone === 'progress' && <RefreshCw size={10} className="animate-spin" />}
                                {meta.tone === 'done' && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />}
                                {meta.label}
                              </span>
                            );
                          })()}
                        </div>
                        <p className="text-xs text-slate-400 mt-1">
                          {formatDate(p.created_at)}
                          {p.original_filename && p.name && (
                            <span className="ml-2 opacity-70">· {p.original_filename}</span>
                          )}
                        </p>
                      </>
                    )}
                  </div>

                  {/* 우: 액션 버튼 (수정 중엔 숨김) */}
                  {editing !== p.id && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      {/* GLB 다운로드 — 완료된 프로젝트만 활성 */}
                      <button
                        onClick={() => handleDownloadGlb(p.id, displayName)}
                        disabled={!isDone}
                        title={isDone ? 'GLB 파일 다운로드' : '배치 완료 후 다운로드 가능'}
                        className="p-2.5 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <Download size={16} />
                      </button>
                      {/* 보고서 다운로드 */}
                      <button
                        onClick={() => handleDownloadReport(p.id, displayName)}
                        disabled={!isDone}
                        title={isDone ? '분석 보고서 다운로드' : '배치 완료 후 다운로드 가능'}
                        className="p-2.5 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <FileSearch size={16} />
                      </button>

                      {/* 구분선 */}
                      <span className="w-px h-5 bg-border mx-1" />

                      {/* 이름 변경 */}
                      <button
                        onClick={() => { setEditing(p.id); setEditName(p.name || ''); }}
                        title="이름 변경"
                        className="p-2.5 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                      >
                        <Edit2 size={16} />
                      </button>
                      {/* 삭제 */}
                      <button
                        onClick={() => void handleDelete(p.id, displayName)}
                        title="삭제"
                        className="p-2.5 text-slate-400 hover:text-red-400 hover:bg-white/10 rounded-lg transition-colors"
                      >
                        <Trash2 size={16} />
                      </button>

                      {/* 구분선 */}
                      <span className="w-px h-5 bg-border mx-1" />

                      {/* 열기 (primary) */}
                      <button
                        onClick={() => void handleOpen(p.id, p)}
                        disabled={opening === p.id}
                        className="text-sm text-slate-300 bg-white/5 hover:bg-white/10 border border-border hover:border-white/30 px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5 disabled:opacity-40 font-bold"
                      >
                        {opening === p.id ? <RefreshCw size={14} className="animate-spin" /> : <ExternalLink size={14} />}
                        열기
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </main>

    {showProjectLimitModal && projectLimit && (
      <LimitExceededModal
        message={projectLimit.message}
        membership={projectLimit.membership}
        onClose={() => setShowProjectLimitModal(false)}
      />
    )}
    </>
  );
}
