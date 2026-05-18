/**
 * ProjectResolver — /project/:id 직접 접근 처리 (deep link)
 *
 * mount 시 getProject 호출 후 stage 따라 redirect:
 *   - status=done + layout_objects 있음 → /project/result
 *   - auto_detected 있음 → /project/floor
 *   - 그 외 (분석중) → /project/new (resume 모드)
 *   - 404 → /project (Hub) + toast
 *
 * 외부 링크 공유 / 새로고침 / 북마크 deep link 지원.
 * ProjectHubPage.handleOpen 과 같은 분기 로직 — 추후 공통화 가능.
 */
import { useEffect, useState } from 'react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useProject } from '../../context/ProjectContext';
import { useToast } from '../../context/ToastContext';
import { getProject } from '../../lib/api';

export default function ProjectResolver() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { currentUser } = useAuth();
  const { toast } = useToast();
  const {
    setProjectId, setResumingFilename,
    setFloorArchiveId, setBrandManualId, setFloorDetectionId,
    setAutoDetected, setBrandExtraction, setSpaceData, setPlacementResult,
  } = useProject();
  const [error, setError] = useState<string>('');

  useEffect(() => {
    if (!currentUser || !id) return;
    const projectId = Number(id);
    if (!Number.isFinite(projectId) || projectId <= 0) {
      toast.error('잘못된 프로젝트 ID');
      navigate('/project', { replace: true });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await getProject(projectId);
        if (cancelled) return;
        setProjectId(detail.id ?? projectId);
        // detail 응답에 original_filename 없음 → name fallback (resume 모드 진입에 필요)
        setResumingFilename(detail.name ?? `프로젝트 #${projectId}`);
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
            // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 placement_result 에 박힘 (재진입 시 복원).
            main_artery: (detail as any).main_artery ?? null,
            // 2026-05-04 신설 - ref_quality_score (모달 트리거용). 0.0 ~ 1.0.
            ref_quality_score: (detail as any).ref_quality_score ?? null,
          } as never);
        } else {
          setPlacementResult(null);
        }
        if (detail.status === 'done' && detail.layout_objects && detail.layout_objects.length > 0) {
          navigate('/project/result', { replace: true });
        } else if (analysisData) {
          // 도면 분석 완료 (pages_json 존재) → floor 페이지로
          navigate('/project/floor', { replace: true });
        } else {
          navigate('/project/new', { replace: true });
        }
      } catch (e) {
        if (cancelled) return;
        if (axios.isAxiosError(e) && e.response?.status === 404) {
          toast.error('프로젝트를 찾을 수 없습니다');
          navigate('/project', { replace: true });
          return;
        }
        const msg = e instanceof Error ? e.message : '프로젝트 로드 실패';
        setError(msg);
        toast.error(msg);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, currentUser?.id]);

  return (
    <div className="flex flex-1 items-center justify-center bg-[#070d1a]">
      <div className="flex flex-col items-center gap-3">
        <div className="w-10 h-10 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
        {error
          ? <p className="text-sm text-red-400">{error}</p>
          : <p className="text-sm text-text-muted">프로젝트 불러오는 중...</p>}
      </div>
    </div>
  );
}
