/**
 * NewProjectPage — 업로드 + 분석 시작 (B안 비동기)
 *
 * 흐름:
 *   1. 파일 업로드 + "분석 시작"
 *   2. POST /api/detect → job_id
 *   3. (브랜드 파일 있으면) POST /api/brand → brand_job_id
 *   4. useJob으로 각각 폴링. 둘 다 done 되면 FloorPage로
 */
import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Upload, Layout, AlertCircle, ArrowRight,
  Layers, Box, RefreshCw, FileText, Square,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useProject } from '../../context/ProjectContext';
import { useToast } from '../../context/ToastContext';
import {
  detectFloor, extractBrand, getJob,
  getDetectResult, getBrandResult, getProject,
  parseLayerSelectError,
  // [LOCAL_TEST_USE_DIRECT] Python 직통 모드 (env: VITE_USE_DIRECT=true)
  USE_DIRECT, detectFloorDirect, extractBrandDirect, detectCeilingHeight,
} from '../../lib/api';
import { computePollInterval } from '../../hooks/useJob';
import LimitExceededModal from '../../components/LimitExceededModal';

export default function NewProjectPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser } = useAuth();
  const { toast } = useToast();
  const {
    floorFile, setFloorFile,
    brandFile, setBrandFile,
    crossSectionFile, setCrossSectionFile,
    setAutoDetected, setBrandExtraction,
    setEditablePolygon,
    setMarkedEntrance, setMarkedSprinklers, setMarkedFH, setMarkedEP,
    setActiveJob,
    setFloorArchiveId, setBrandManualId, setProjectId,
    projectId, resumingFilename, setResumingFilename,
    reset,
  } = useProject();

  // Resume 모드 — MyPage에서 진행중 프로젝트 열고 온 경우
  // projectId + resumingFilename 둘 다 있으면 "분석중" 화면 보여주고 폴링으로 완료 감지
  const isResuming = !!projectId && !!resumingFilename;

  // /project/new 진입 시 잔여물 초기화
  // - resume 모드: skip (폴링으로 이어받아야 함)
  // - fromBack: 파일 유지, 분석 결과만 초기화
  // - 일반 진입: 전체 reset
  useEffect(() => {
    if (isResuming) return;
    if ((location.state as { fromBack?: boolean } | null)?.fromBack) {
      setAutoDetected(null);
      setEditablePolygon([]);
      setMarkedEntrance(null);
      setMarkedSprinklers([]);
      setMarkedFH([]);
      setMarkedEP([]);
    } else {
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Resume 모드에서 자동 폴링 — detect 완료되면 /project/floor로 이동
  useEffect(() => {
    if (!isResuming || !currentUser || !projectId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelled) return;
      try {
        const detail = await getProject(projectId);
        if (cancelled) return;
        // 2026-05-01 — 백엔드는 pages_json (JSON string) 으로 응답. JSON.parse 후 사용.
        let analysisData: any = null;
        if ((detail as any).pages_json) {
          try { analysisData = JSON.parse((detail as any).pages_json); }
          catch { analysisData = null; }
        }
        if (analysisData) {
          // detect 완료됨 — context 세팅 후 floor로
          setAutoDetected(analysisData);
          if (detail.brand_data) setBrandExtraction(detail.brand_data);
          if (analysisData.floor_polygon_px) {
            setEditablePolygon(analysisData.floor_polygon_px);
          }
          // sessionStorage 초기화 후 resume 진입한 경우에도 FK state 복원
          // (FloorPage calculateSpace 에서 floor_archive_id null 전달 방지)
          if (detail.floor_archive_id) setFloorArchiveId(detail.floor_archive_id);
          if (detail.brand_manual_id) setBrandManualId(detail.brand_manual_id);
          toast.success('도면 분석 완료');
          navigate('/project/floor');
          return;
        }
        if (detail.status === 'error') {
          toast.error('도면 분석 실패');
          return;
        }
      } catch (e) {
        console.warn('[resume poll] 실패', e);
        // 404 = projectId 가 stale (서버에서 삭제됨) → sessionStorage 초기화 + 폴링 중단
        // 다른 에러 (네트워크 일시 오류 등) 는 재시도
        if (axios.isAxiosError(e) && e.response?.status === 404) {
          setProjectId(null);
          setResumingFilename(null);
          return;
        }
      }
      timer = setTimeout(() => void tick(), 3000);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isResuming, projectId, currentUser?.id]);

  const cancelledRef      = useRef(false);
  const sleepTimerRef     = useRef<number | null>(null);
  const sleepResolveRef   = useRef<(() => void) | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const interruptSleep = () => {
    if (sleepTimerRef.current !== null) {
      clearTimeout(sleepTimerRef.current);
      sleepTimerRef.current = null;
    }
    sleepResolveRef.current?.();
    sleepResolveRef.current = null;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  };

  const [isProcessing, setIsProcessing] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState('');
  const [limitModal, setLimitModal] = useState<string | null>(null);
  const [brandFileError, setBrandFileError] = useState('');
  const [floorFileError, setFloorFileError] = useState('');
  const [crossSectionFileError, setCrossSectionFileError] = useState('');
  const [isDraggingBrand, setIsDraggingBrand] = useState(false);
  const [isDraggingFloor, setIsDraggingFloor] = useState(false);
  const [isDraggingCrossSection, setIsDraggingCrossSection] = useState(false);
  const [showBrandWarning, setShowBrandWarning] = useState(false);
  const skipBrandCheck = useRef(false);

  // 레이어 선택 모달 상태 — DXF 자동 인식 실패 시 사용자가 레이어 직접 지정
  const [layerSelectLayers, setLayerSelectLayers] = useState<string[] | null>(null);
  const [selectedLayer, setSelectedLayer] = useState('');

  const floorInputRef = useRef<HTMLInputElement>(null);
  const brandInputRef = useRef<HTMLInputElement>(null);
  const crossSectionInputRef = useRef<HTMLInputElement>(null);

  // floorFile 체크는 handleAnalyze 안에서 — disabled 가 아니라 클릭 가능하게 두고 명시적 에러 노출
  const canAnalyze = !isProcessing && !!currentUser && !isResuming;

  const handleAnalyze = async () => {
    if (isProcessing) return;
    if (!floorFile) {
      setFloorFileError('도면 파일을 선택해 주세요. PDF · DXF · DWG · JPG · PNG 만 가능합니다.');
      return;
    }
    setFloorFileError('');
    if (!brandFile && !skipBrandCheck.current) {
      setShowBrandWarning(true);
      return;
    }
    skipBrandCheck.current = false;
    cancelledRef.current = false;
    setShowBrandWarning(false);
    setError('');
    setIsProcessing(true);

    if (!currentUser) return;
    setStatusMsg('작업 등록 중...');

    // ════════════════════════════════════════════════════════════════
    // [LOCAL_TEST_USE_DIRECT] Python 직통 모드 분기
    // ────────────────────────────────────────────────────────────────
    // VITE_USE_DIRECT=true 면 Java/Redis/Worker 우회하고 Python 동기 호출.
    // job_id / project_id / pdf_id 같은 DB 식별자 없이 결과만 받아 Context 세팅.
    // 미설정 시 아래 B안 블록 (기존 동작) 그대로 실행.
    // ════════════════════════════════════════════════════════════════
    if (USE_DIRECT) {
      try {
        setStatusMsg('도면 분석 중... (Python 직통)');
        const forceLayer = layerSelectLayers ? selectedLayer : undefined;
        const [detectResult, ceilingResult] = await Promise.all([
          detectFloorDirect(floorFile, forceLayer),
          crossSectionFile ? detectCeilingHeight(crossSectionFile).catch(() => null) : Promise.resolve(null),
        ]);

        // 레이어 선택 필요 — 모달 표시 후 종료
        if ('needLayerSelect' in detectResult) {
          const layers = (detectResult as { needLayerSelect: true; layers: string[] }).layers;
          setLayerSelectLayers(layers);
          setSelectedLayer(layers[0] ?? '');
          setIsProcessing(false);
          setStatusMsg('');
          return;
        }

        const autoDetected = detectResult;
        const mergedDetected = ceilingResult?.ceiling_height_mm != null
          ? { ...autoDetected, ceiling_height_mm: ceilingResult.ceiling_height_mm }
          : autoDetected;
        setAutoDetected(mergedDetected);
        if (mergedDetected?.floor_polygon_px) setEditablePolygon(mergedDetected.floor_polygon_px);

        // 자동 감지된 설비/입구 marking state 초기값 세팅
        const ent = mergedDetected?.entrance as { x_px?: number; y_px?: number; x2_px?: number; y2_px?: number } | null;
        if (ent && typeof ent.x_px === 'number' && typeof ent.y_px === 'number') {
          setMarkedEntrance({
            points: [{ x_px: ent.x_px, y_px: ent.y_px }],
            x_px: ent.x_px, y_px: ent.y_px,
            x2_px: ent.x2_px, y2_px: ent.y2_px,
          });
        }
        const sprs = (mergedDetected?.sprinklers ?? []) as Array<{ x_px: number; y_px: number }>;
        if (sprs.length) setMarkedSprinklers(sprs.map(s => ({ x_px: s.x_px, y_px: s.y_px })));
        // #198 의 단수형 키(fire_hydrant/electrical_panel) + 강제 캐스팅 반려 — 백엔드 응답은 복수형
        const fhs = mergedDetected?.fire_hydrants ?? [];
        if (fhs.length) setMarkedFH(fhs.map(s => ({ x_px: s.x_px, y_px: s.y_px })));
        const eps = mergedDetected?.electrical_panels ?? [];
        if (eps.length) setMarkedEP(eps.map(s => ({ x_px: s.x_px, y_px: s.y_px })));

        // 브랜드 파일 있으면 직통 호출
        if (brandFile) {
          setStatusMsg('브랜드 추출 중... (Python 직통)');
          const brand = await extractBrandDirect(brandFile);
          setBrandExtraction(brand);
        }

        toast.success('도면 분석 완료 (직통)');
        if (window.location.pathname.startsWith('/project/new')) {
          navigate('/project/floor');
        }
        return;
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '직통 분석 실패';
        setError(msg);
        toast.error(`직통 분석 실패: ${msg}`);
        return;
      } finally {
        setIsProcessing(false);
        setStatusMsg('');
      }
    }
    // ════════════════════════════════════════════════════════════════
    // [LOCAL_TEST_USE_DIRECT] 끝 — 아래는 기존 B안 (Java 경유) 로직
    // ════════════════════════════════════════════════════════════════

    try {
      // 1. detect 작업 생성 — stub user_project이 여기서 만들어짐 (status=processing)
      const forceLayer = layerSelectLayers ? selectedLayer : undefined;
      const detectRes = await detectFloor(floorFile, forceLayer);
      const detectJobId = detectRes.job_id;
      setActiveJob({ id: detectJobId, type: 'detect', startedAt: Date.now(), projectId: detectRes.project_id });
      if (detectRes.floor_archive_id) setFloorArchiveId(detectRes.floor_archive_id);
      const newProjectId = detectRes.project_id ?? null;
      if (newProjectId != null) setProjectId(newProjectId);

      setStatusMsg('도면 분석 중... (잠시 소요)');

      // 2. 브랜드 파일 있으면 brand 작업도 동시에 생성 (project_id 전달 → stub에 즉시 attach)
      let brandJobId: number | null = null;
      let brandManualIdLocal: number | null = null;
      if (brandFile) {
        const brandRes = await extractBrand(brandFile, newProjectId ?? undefined);
        brandJobId = brandRes.job_id;
        if (brandRes.brand_manual_id) {
          brandManualIdLocal = brandRes.brand_manual_id;
          setBrandManualId(brandRes.brand_manual_id);
        }
      }

      // 3. 폴링 — detect 완료 대기
      if (await pollJob(detectJobId, (msg) => setStatusMsg(msg)) === 'cancelled') {
        setActiveJob(null);
        toast.info('분석이 중단되었습니다. 완료되면 마이페이지에서 이어서 진행할 수 있습니다.');
        return;
      }

      // 4. detect 결과(auto_detected) 도메인 조회해서 Context에 세팅
      setStatusMsg('도면 결과 로드 중...');
      // floor_archive_id 는 detectRes 응답에 이미 있음 (Job 응답엔 파생 ID 없음)
      const detectFloorArchiveId = detectRes.floor_archive_id;
      if (!detectFloorArchiveId) throw new Error('floor_archive_id 누락');
      const [autoDetected, ceilingResult] = await Promise.all([
        getDetectResult(detectFloorArchiveId),
        crossSectionFile ? detectCeilingHeight(crossSectionFile).catch(() => null) : Promise.resolve(null),
      ]);
      const mergedDetected = ceilingResult?.ceiling_height_mm != null
        ? { ...autoDetected, ceiling_height_mm: ceilingResult.ceiling_height_mm }
        : autoDetected;
      setAutoDetected(mergedDetected);
      if (mergedDetected?.floor_polygon_px) setEditablePolygon(mergedDetected.floor_polygon_px);

      // 자동 감지된 설비/입구를 marking state에 초기값으로 세팅 (FloorPage에서 바로 표시됨)
      const ent = mergedDetected?.entrance as { x_px?: number; y_px?: number; x2_px?: number; y2_px?: number } | null;
      if (ent && typeof ent.x_px === 'number' && typeof ent.y_px === 'number') {
        setMarkedEntrance({
          points: [{ x_px: ent.x_px, y_px: ent.y_px }],
          x_px: ent.x_px,
          y_px: ent.y_px,
          x2_px: ent.x2_px,
          y2_px: ent.y2_px,
        });
      }
      const sprs = (mergedDetected?.sprinklers ?? []) as Array<{ x_px: number; y_px: number }>;
      if (sprs.length) setMarkedSprinklers(sprs.map(s => ({ x_px: s.x_px, y_px: s.y_px })));
      // #198 의 단수형 키(fire_hydrant/electrical_panel) + 강제 캐스팅 반려 — 백엔드 응답은 복수형
      const fhs = mergedDetected?.fire_hydrants ?? [];
      if (fhs.length) setMarkedFH(fhs.map(s => ({ x_px: s.x_px, y_px: s.y_px })));
      const eps = mergedDetected?.electrical_panels ?? [];
      if (eps.length) setMarkedEP(eps.map(s => ({ x_px: s.x_px, y_px: s.y_px })));

      // 5. 브랜드 폴링 + 결과 fetch
      if (brandJobId) {
        setStatusMsg('브랜드 추출 중...');
        if (await pollJob(brandJobId, (msg) => setStatusMsg(msg)) === 'cancelled') {
          setActiveJob(null);
          toast.info('분석이 중단되었습니다. 완료되면 마이페이지에서 이어서 진행할 수 있습니다.');
          return;
        }
        // brand_manual_id 는 extractBrand 응답에서 받음 (Job 응답엔 파생 ID 없음)
        if (brandManualIdLocal) {
          const brand = await getBrandResult(brandManualIdLocal);
          setBrandExtraction(brand);
        }
      }

      setActiveJob(null);
      toast.success('도면 분석 완료', {
        actionLabel: '마킹하러 가기 →',
        onAction: () => navigate('/project/floor'),
      });
      // 현재 /project/new에 머무르고 있을 때만 자동 이동. 홈/마이페이지 등으로 이동했다면 토스트만.
      if (window.location.pathname.startsWith('/project/new')) {
        navigate('/project/floor');
      }
    } catch (e: unknown) {
      const res = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      const axiosDetail = res?.data?.detail;
      const msg = axiosDetail || (e instanceof Error ? e.message : '분석 실패');

      // B안: 폴링 중 layer_select_needed 에러 감지
      const layerSelect = parseLayerSelectError(msg);
      if (layerSelect) {
        setLayerSelectLayers(layerSelect.layers);
        setSelectedLayer(layerSelect.layers[0] ?? '');
        setActiveJob(null);
        return;
      }

      if (res?.status === 429) {
        setLimitModal(msg);
      } else {
        setError(msg);
        toast.error(msg);
      }
      setActiveJob(null);
    } finally {
      setIsProcessing(false);
      setStatusMsg('');
    }
  };

  // ── 폴링 헬퍼 — progress.pct 기반 동적 interval (5s/3s/1s) ──
  const pollJob = async (
    jobId: number,
    onProgress?: (msg: string) => void,
  ): Promise<'cancelled' | unknown> => {
    let delay = 5000; // 초기 5s
    while (true) {
      await new Promise<void>(r => {
        sleepResolveRef.current = r;
        sleepTimerRef.current = window.setTimeout(() => {
          sleepTimerRef.current = null;
          sleepResolveRef.current = null;
          r();
        }, delay);
      });
      if (cancelledRef.current) return 'cancelled';
      abortControllerRef.current = new AbortController();
      try {
        const job = await getJob(jobId, abortControllerRef.current.signal);
        abortControllerRef.current = null;
        if (cancelledRef.current) return 'cancelled';
        if (job.progress_message && onProgress) onProgress(job.progress_message);
        if (job.status === 'done') return job;
        if (job.status === 'error') throw new Error(job.error_message || '작업 실패');
        delay = computePollInterval(job.progress_pct ?? undefined);
      } catch (e) {
        abortControllerRef.current = null;
        if (axios.isCancel(e)) return 'cancelled';
        throw e;
      }
    }
  };

  // NOTE: 언마운트 시 activeJob을 의도적으로 clear하지 않음.
  //  사용자가 분석 중에 홈/마이페이지로 이동해도 헤더 배지가 계속 보여야 하므로
  //  job은 성공(setActiveJob(null))·실패(catch 블록에서 setActiveJob(null))로만 종료.

  return (
    <div className="flex flex-1 overflow-hidden">
      {limitModal && (
        <LimitExceededModal
          message={limitModal}
          membership={currentUser?.membership ?? 'basic'}
          onClose={() => setLimitModal(null)}
        />
      )}
      {/* ════ LEFT PANEL ════ */}
      <aside className="w-80 shrink-0 flex flex-col border-r border-border overflow-y-auto">
        {error && (
          <div className="mx-4 mt-3 p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
            <AlertCircle size={13} className="shrink-0 mt-0.5" /> {error}
          </div>
        )}

        {!currentUser && (
          <div className="mx-4 mt-3 p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-xl text-xs text-amber-400">
            로그인이 필요합니다. 분석 결과가 내 이력에 저장됩니다.
          </div>
        )}

        <div className="border-b border-border">
          <div className="w-full flex items-center justify-between px-4 py-3">
            <span className="text-sm font-bold flex items-center gap-2">
              <Upload size={14} className="text-primary" /> 파일 업로드
              {(brandFile || floorFile) && <span className="w-2 h-2 rounded-full bg-accent ml-1" />}
            </span>
          </div>

          <div className={`px-4 pb-4 space-y-5 ${isProcessing ? 'pointer-events-none opacity-50' : ''}`}>
            {/* 브랜드 매뉴얼 */}
            <label className="block">
              <div className="text-xs text-text-muted mb-0.5 flex items-center gap-1">
                <Layout size={11} className="text-primary" /> 브랜드 매뉴얼 (PDF · PPTX · DOCX · XLSX)
              </div>
              <p className="text-[10px] text-text-muted/50 mb-1">브랜드 가이드라인, 색상·로고 규정 등 브랜드 규칙이 담긴 파일</p>
              {!brandFile ? (
                <div
                  onDragOver={e => { e.preventDefault(); setIsDraggingBrand(true); }}
                  onDragLeave={() => setIsDraggingBrand(false)}
                  onDrop={e => {
                    e.preventDefault(); setIsDraggingBrand(false);
                    const file = e.dataTransfer.files[0]; if (!file) return;
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'pptx', 'docx', 'xlsx'].includes(ext)) { setBrandFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · PPTX · DOCX · XLSX만 가능해요.`); return; }
                    setBrandFileError(''); setBrandFile(file);
                  }}
                  className={`border border-dashed rounded-xl p-3 cursor-pointer transition-colors group ${isDraggingBrand ? 'border-primary bg-primary/10' : 'border-border hover:border-primary hover:bg-primary/5'}`}>
                  <div className="flex items-center gap-2">
                    <Upload size={14} className={`shrink-0 transition-colors ${isDraggingBrand ? 'text-primary' : 'text-text-muted group-hover:text-primary'}`} />
                    <span className="text-xs text-text-muted">파일 선택 또는 드래그</span>
                  </div>
                </div>
              ) : (
                <div
                  onDragOver={e => { e.preventDefault(); setIsDraggingBrand(true); }}
                  onDragLeave={() => setIsDraggingBrand(false)}
                  onDrop={e => {
                    e.preventDefault(); setIsDraggingBrand(false);
                    const file = e.dataTransfer.files[0]; if (!file) return;
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'pptx', 'docx', 'xlsx'].includes(ext)) { setBrandFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · PPTX · DOCX · XLSX만 가능해요.`); return; }
                    setBrandFileError(''); setBrandFile(file);
                  }}
                  className={`border rounded-xl p-3 flex items-center gap-2 transition-colors ${isDraggingBrand ? 'border-primary bg-primary/10' : 'border-primary/30 bg-primary/5'}`}>
                  <FileText size={14} className="text-primary shrink-0" />
                  <span className="text-xs text-text-main truncate flex-1 min-w-0">{brandFile.name}</span>
                  <button type="button" onClick={e => { e.preventDefault(); setBrandFile(null); if (brandInputRef.current) brandInputRef.current.value = ''; }} className="text-text-muted hover:text-red-400 shrink-0">✕</button>
                </div>
              )}
              <input ref={brandInputRef} type="file" className="hidden" accept=".pdf,.pptx,.docx,.xlsx" disabled={isResuming}
                onChange={e => {
                  const file = e.target.files?.[0] || null;
                  if (file) {
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'pptx', 'docx', 'xlsx'].includes(ext)) {
                      setBrandFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · PPTX · DOCX · XLSX만 가능해요.`);
                      setBrandFile(null);
                      e.target.value = '';
                      return;
                    }
                  }
                  setBrandFileError('');
                  setBrandFile(file);
                }} />
              {brandFileError && (
                <div className="mt-2 px-3 py-2.5 rounded-xl border bg-red-500/10 border-red-500/40 text-red-300 flex items-start gap-2">
                  <AlertCircle size={14} className="shrink-0 mt-0.5" />
                  <p className="flex-1 text-xs leading-relaxed">{brandFileError}</p>
                  <button onClick={() => setBrandFileError('')} className="opacity-50 hover:opacity-100 text-xs">✕</button>
                </div>
              )}
            </label>

            {/* 도면 */}
            <label className="block">
              <div className="text-xs text-text-muted mb-0.5 flex items-center gap-1">
                <Layers size={11} className="text-accent" /> 도면 (PDF·DXF·DWG)
              </div>
              <p className="text-[10px] text-text-muted/50 mb-1">팝업스토어 공간의 평면도 파일</p>
              {isResuming ? (
                <div className="border border-amber-500/30 bg-amber-500/5 rounded-xl p-3 flex items-center gap-2">
                  <FileText size={14} className="text-amber-400 shrink-0" />
                  <span className="text-xs text-amber-400 truncate flex-1 min-w-0">{resumingFilename}</span>
                </div>
              ) : !floorFile ? (
                <div
                  onDragOver={e => { e.preventDefault(); setIsDraggingFloor(true); }}
                  onDragLeave={() => setIsDraggingFloor(false)}
                  onDrop={e => {
                    e.preventDefault(); setIsDraggingFloor(false);
                    const file = e.dataTransfer.files[0]; if (!file) return;
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'dxf', 'dwg' /* 이미지 지원 보류: 'jpg', 'jpeg', 'png' */].includes(ext)) { setFloorFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · DXF · DWG만 가능해요.`); return; }
                    setFloorFileError(''); setFloorFile(file);
                  }}
                  className={`border border-dashed rounded-xl p-3 cursor-pointer transition-colors group ${isDraggingFloor ? 'border-accent bg-accent/10' : 'border-border hover:border-accent hover:bg-accent/5'}`}>
                  <div className="flex items-center gap-2">
                    <Upload size={14} className={`shrink-0 transition-colors ${isDraggingFloor ? 'text-accent' : 'text-text-muted group-hover:text-accent'}`} />
                    <span className="text-xs text-text-muted">파일 선택 또는 드래그</span>
                  </div>
                </div>
              ) : (
                <div
                  onDragOver={e => { e.preventDefault(); setIsDraggingFloor(true); }}
                  onDragLeave={() => setIsDraggingFloor(false)}
                  onDrop={e => {
                    e.preventDefault(); setIsDraggingFloor(false);
                    const file = e.dataTransfer.files[0]; if (!file) return;
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'dxf', 'dwg' /* 이미지 지원 보류: 'jpg', 'jpeg', 'png' */].includes(ext)) { setFloorFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · DXF · DWG만 가능해요.`); return; }
                    setFloorFileError(''); setFloorFile(file);
                  }}
                  className={`border rounded-xl p-3 flex items-center gap-2 transition-colors ${isDraggingFloor ? 'border-accent bg-accent/10' : 'border-accent/30 bg-accent/5'}`}>
                  <FileText size={14} className="text-accent shrink-0" />
                  <span className="text-xs text-text-main truncate flex-1 min-w-0">{floorFile.name}</span>
                  {(floorFile.name.endsWith('.dxf') || floorFile.name.endsWith('.dwg')) && (
                    <span className="bg-accent/20 text-accent text-[9px] px-1 rounded font-bold shrink-0">CAD</span>
                  )}
                  <button type="button" onClick={e => { e.preventDefault(); setFloorFile(null); if (floorInputRef.current) floorInputRef.current.value = ''; }} className="text-text-muted hover:text-red-400 shrink-0">✕</button>
                </div>
              )}
              {/* 이미지 지원 보류: accept에서 .jpg,.jpeg,.png 제거 */}
              <input ref={floorInputRef} type="file" className="hidden" accept=".pdf,.dxf,.dwg" disabled={isResuming}
                onChange={e => {
                  const file = e.target.files?.[0] || null;
                  if (file) {
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'dxf', 'dwg' /* 이미지 지원 보류: 'jpg', 'jpeg', 'png' */].includes(ext)) {
                      setFloorFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · DXF · DWG만 가능해요.`);
                      setFloorFile(null);
                      e.target.value = '';
                      return;
                    }
                  }
                  setFloorFileError('');
                  setFloorFile(file);
                }} />
              {floorFileError && (
                <div className="mt-2 px-3 py-2.5 rounded-xl border bg-red-500/10 border-red-500/40 text-red-300 flex items-start gap-2">
                  <AlertCircle size={14} className="shrink-0 mt-0.5" />
                  <p className="flex-1 text-xs leading-relaxed">{floorFileError}</p>
                  <button onClick={() => setFloorFileError('')} className="opacity-50 hover:opacity-100 text-xs">✕</button>
                </div>
              )}
              {(floorFile?.name.endsWith('.dxf') || floorFile?.name.endsWith('.dwg')) && (
                <p className="mt-1.5 text-[10px] text-text-muted/60 leading-relaxed">
                  DXF 도면은 외벽이 완전히 닫힌 폴리라인(Closed Polyline)으로 그려져 있어야 자동 인식됩니다.
                </p>
              )}
            </label>

            {/* 단면도 (선택) — ceiling_height_mm 추출용 */}
            <label className="block">
              <div className="text-xs text-text-muted mb-0.5 flex items-center gap-1">
                <FileText size={11} className="text-primary/80" /> 단면도 (PDF·DXF·DWG)
              </div>
              <p className="text-[10px] text-text-muted/50 mb-1">공간 높이 분석용 · 없으면 생략 가능</p>
              {!crossSectionFile ? (
                <div
                  onDragOver={e => { e.preventDefault(); setIsDraggingCrossSection(true); }}
                  onDragLeave={() => setIsDraggingCrossSection(false)}
                  onDrop={e => {
                    e.preventDefault(); setIsDraggingCrossSection(false);
                    const file = e.dataTransfer.files[0]; if (!file) return;
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'dxf', 'dwg'].includes(ext)) { setCrossSectionFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · DXF · DWG만 가능해요.`); return; }
                    setCrossSectionFileError(''); setCrossSectionFile(file);
                  }}
                  className={`border border-dashed rounded-xl p-3 cursor-pointer transition-colors group ${isDraggingCrossSection ? 'border-primary/80 bg-primary/10' : 'border-border hover:border-primary/80 hover:bg-primary/5'}`}>
                  <div className="flex items-center gap-2">
                    <Upload size={14} className={`shrink-0 transition-colors ${isDraggingCrossSection ? 'text-primary/80' : 'text-text-muted group-hover:text-primary'}`} />
                    <span className="text-xs text-text-muted">파일 선택 또는 드래그</span>
                  </div>
                </div>
              ) : (
                <div
                  onDragOver={e => { e.preventDefault(); setIsDraggingCrossSection(true); }}
                  onDragLeave={() => setIsDraggingCrossSection(false)}
                  onDrop={e => {
                    e.preventDefault(); setIsDraggingCrossSection(false);
                    const file = e.dataTransfer.files[0]; if (!file) return;
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'dxf', 'dwg'].includes(ext)) { setCrossSectionFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · DXF · DWG만 가능해요.`); return; }
                    setCrossSectionFileError(''); setCrossSectionFile(file);
                  }}
                  className={`border rounded-xl p-3 flex items-center gap-2 transition-colors ${isDraggingCrossSection ? 'border-primary/80 bg-primary/10' : 'border-primary/30 bg-primary/5'}`}>
                  <FileText size={14} className="text-primary/80 shrink-0" />
                  <span className="text-xs text-text-main truncate flex-1 min-w-0">{crossSectionFile.name}</span>
                  <button type="button" onClick={e => { e.preventDefault(); setCrossSectionFile(null); if (crossSectionInputRef.current) crossSectionInputRef.current.value = ''; }} className="text-text-muted hover:text-red-400 shrink-0">✕</button>
                </div>
              )}
              <input ref={crossSectionInputRef} type="file" className="hidden" accept=".pdf,.dxf,.dwg"
                onChange={e => {
                  const file = e.target.files?.[0] || null;
                  if (file) {
                    const ext = file.name.split('.').pop()?.toLowerCase() || '';
                    if (!['pdf', 'dxf', 'dwg'].includes(ext)) {
                      setCrossSectionFileError(`'.${ext}' 파일은 지원하지 않아요. PDF · DXF · DWG만 가능해요.`);
                      e.target.value = '';
                      return;
                    }
                  }
                  setCrossSectionFileError('');
                  setCrossSectionFile(file);
                }} />
              {crossSectionFileError && (
                <div className="mt-2 px-3 py-2.5 rounded-xl border bg-red-500/10 border-red-500/40 text-red-300 flex items-start gap-2">
                  <AlertCircle size={14} className="shrink-0 mt-0.5" />
                  <p className="flex-1 text-xs leading-relaxed">{crossSectionFileError}</p>
                  <button onClick={() => setCrossSectionFileError('')} className="opacity-50 hover:opacity-100 text-xs">✕</button>
                </div>
              )}
            </label>

            {/* 배치 밀도는 FloorPage로 이동 (도면 크기 확인 후 조정) */}

            {/* 분석 버튼 */}
            <button onClick={handleAnalyze} disabled={!canAnalyze}
              className={`w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-sm font-bold transition-colors ${
                !canAnalyze ? 'bg-primary/30 text-white/40 cursor-not-allowed' : 'bg-primary text-white hover:bg-primary/90'
              }`}>
              {isResuming
                ? <><RefreshCw size={14} className="animate-spin" /> 분석 중...</>
                : isProcessing
                ? <><RefreshCw size={14} className="animate-spin" /> 분석 중...</>
                : <><ArrowRight size={14} /> 분석 시작하기</>}
            </button>
          </div>
        </div>

      </aside>

      {/* ════ RIGHT PANEL ════ */}
      <main className="flex-1 flex flex-col items-center justify-center gap-4 bg-[#070d1a]">
        {isResuming ? (
          <>
            <div className="w-16 h-16 rounded-full border-2 border-amber-500/20 border-t-amber-500 animate-spin" />
            <p className="text-sm font-bold text-text-main">도면 분석중</p>
            <p className="text-xs text-amber-400 font-medium">{resumingFilename}</p>
            <p className="text-xs text-text-muted">완료되면 자동으로 다음 단계로 이동됩니다.</p>
          </>
        ) : isProcessing ? (
          <>
            <div className="w-16 h-16 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
            <p className="text-sm font-bold text-text-main">{statusMsg || '분석 중...'}</p>
            <p className="text-xs text-text-muted">다른 페이지로 이동해도 작업은 계속됩니다</p>
            <button
              onClick={() => { cancelledRef.current = true; interruptSleep(); }}
              className="mt-2 flex items-center gap-2 px-4 py-2 rounded-xl border border-red-500/40 text-red-400 bg-red-500/10 hover:bg-red-500/20 text-xs font-semibold transition-colors"
            >
              <Square size={11} fill="currentColor" />
              중단
            </button>
          </>
        ) : layerSelectLayers ? (
          <>
            <div className="w-24 h-24 rounded-3xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
              <Layers size={40} className="text-amber-400" />
            </div>
            <p className="text-sm font-bold text-text-main">자동 인식에 실패했습니다</p>
            <p className="text-xs text-text-muted text-center leading-relaxed max-w-xs">
              도면의 외곽선이 닫혀있지 않거나 레이어가 혼재되어 있습니다.<br />
              '매장 가용 공간'을 나타내는 레이어를 직접 선택해 주세요.
            </p>
            <select
              value={selectedLayer}
              onChange={e => setSelectedLayer(e.target.value)}
              className="mt-1 w-64 px-3 py-2 rounded-xl border border-border bg-[#0d1525] text-sm text-text-main focus:outline-none focus:border-accent"
            >
              {layerSelectLayers.map(l => (
                <option key={l} value={l}>{l || '(이름 없는 레이어)'}</option>
              ))}
            </select>
            <div className="flex gap-2 mt-1">
              <button
                onClick={() => { setLayerSelectLayers(null); setSelectedLayer(''); }}
                className="px-4 py-2 rounded-xl border border-border text-xs text-text-muted hover:text-text-main transition-colors"
              >
                취소
              </button>
              <button
                onClick={() => { setLayerSelectLayers(null); void handleAnalyze(); }}
                disabled={!selectedLayer}
                className="px-4 py-2 rounded-xl bg-accent/20 border border-accent/40 text-xs text-accent hover:bg-accent/30 transition-colors disabled:opacity-40"
              >
                이 레이어로 재분석
              </button>
            </div>
          </>
        ) : showBrandWarning ? (
          <>
            <div className="w-24 h-24 rounded-3xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
              <AlertCircle size={40} className="text-amber-400" />
            </div>
            <p className="text-sm font-bold text-text-main">브랜드 매뉴얼 없이 진행할까요?</p>
            <p className="text-xs text-text-muted text-center leading-relaxed">
              매뉴얼이 없으면 기본값으로 배치됩니다.<br />브랜드 규칙을 반영하려면 매뉴얼을 추가해 주세요.
            </p>
            <div className="flex gap-2 mt-1">
              <button
                onClick={() => setShowBrandWarning(false)}
                className="px-4 py-2 rounded-xl border border-border text-xs text-text-muted hover:text-text-main transition-colors"
              >
                취소
              </button>
              <button
                onClick={() => { brandInputRef.current?.click(); setShowBrandWarning(false); }}
                className="px-4 py-2 rounded-xl border border-primary/40 text-xs text-primary hover:bg-primary/10 transition-colors"
              >
                매뉴얼 추가
              </button>
              <button
                onClick={() => { skipBrandCheck.current = true; void handleAnalyze(); }}
                className="px-4 py-2 rounded-xl bg-amber-500/20 border border-amber-500/40 text-xs text-amber-300 hover:bg-amber-500/30 transition-colors"
              >
                그래도 진행
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="w-24 h-24 rounded-3xl bg-primary/10 border border-primary/20 flex items-center justify-center">
              <Box size={40} className="text-primary/60" />
            </div>
            <p className="text-text-muted text-sm">도면과 브랜드 매뉴얼을 업로드하면 분석 결과가 여기에 표시됩니다</p>
          </>
        )}
      </main>
    </div>
  );
}
