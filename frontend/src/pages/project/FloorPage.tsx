/**
 * FloorPage — 마킹 + 공간확인 + 배치 생성 중 (구 AppShell step=marking/space_confirm/generating)
 *
 * 3개 로컬 step으로 분기:
 *  - 'marking': 입구/스프링클러 등 마킹 + 공간 계산 버튼
 *  - 'space_confirm': 공간 분석 결과 확인 + 배치 생성 버튼
 *  - 'generating': 배치 생성 중 스피너
 *
 * 진입 조건: autoDetected 있어야 함 (없으면 /project/new로 리다이렉트)
 */
import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useNavigate, Navigate } from 'react-router-dom';
import {
  AlertCircle, ArrowLeft, Layers, Box, RefreshCw, ChevronDown, ChevronUp, Square,
} from 'lucide-react';
import { useProject } from '../../context/ProjectContext';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import {
  calculateSpace, placeObjects, getJob, cancelJob,
  getFloorDetectionResult, getProject,
  // [LOCAL_TEST_USE_DIRECT] Python 직통 모드 (env: VITE_USE_DIRECT=true)
  USE_DIRECT, calculateSpaceDirect, placeObjectsDirect,
} from '../../lib/api';
import MarkingSVG from '../../components/project/MarkingSVG';
import SpaceConfirmSVG from '../../components/project/SpaceConfirmSVG';
import { MODE_CFG, STATUS_MESSAGES, calcAreaMm2, formatArea, isSmallScale } from './_constants';
import { debugLog } from '../../lib/debug';

type LocalStep = 'marking' | 'space_confirm' | 'generating';

export default function FloorPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuth();
  const { toast } = useToast();
  const {
    autoDetected, brandExtraction, setBrandExtraction, brandCategory, setBrandCategory,
    densityRatio, setDensityRatio,
    userRequirements, venueType, setVenueType,
    spaceData, setSpaceData, setPlacementResult,
    markMode, setMarkMode,
    markedEntrance, setMarkedEntrance,
    markedSprinklers, setMarkedSprinklers,
    markedFH, setMarkedFH,
    markedEP, setMarkedEP,
    editablePolygon, setEditablePolygon,
    // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가
    // anchorPoints, setAnchorPoints,
    // anchorMm, setAnchorMm,
    // manualWidthMm, setManualWidthMm,
    // manualHeightMm, setManualHeightMm,
    setWalls, setSelectedObjectIndices, setSelectedWallId,
    floorArchiveId, brandManualId, floorDetectionId, setFloorDetectionId,
    projectId,
    activeJob,
    setActiveJob,
  } = useProject();

  // 이 프로젝트에 진행중인 job (다른 탭·홈에서 시작해서 계속 도는 경우 포함)
  const isJobRunningHere = !!activeJob && (activeJob.projectId === projectId || activeJob.projectId === undefined);
  const spaceJobRunning = isJobRunningHere && activeJob?.type === 'space_data';
  const placeJobRunning = isJobRunningHere && activeJob?.type === 'place';

  const cancelledRef       = useRef(false);
  const sleepTimerRef      = useRef<number | null>(null);
  const sleepResolveRef    = useRef<(() => void) | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // 2026-05-08 — 자동 이동 buggy fix. projectId 가 polling 진행 중에 변경 (다른 프로젝트 이동) 되면 ref 로 추적.
  // closure 안 projectId = startup 시점 (옛 값). 비교용으로 시작 시점 startProjectId vs 완료 시점 projectIdRef.current.
  const projectIdRef = useRef(projectId);
  useEffect(() => { projectIdRef.current = projectId; }, [projectId]);

  const [showBackConfirm, setShowBackConfirm] = useState(false);

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

  const [step, setStep] = useState<LocalStep>(spaceData ? 'space_confirm' : 'marking');
  const [markingOpen, setMarkingOpen] = useState(true);
  const [spaceOpen, setSpaceOpen] = useState(true);
  const [brandOpen, setBrandOpen] = useState(true);
  const [error, setError] = useState('');
  const [statusMsg, setStatusMsg] = useState('');
  const [statusIdx, setStatusIdx] = useState(0);
  const [showVenueModal, setShowVenueModal] = useState(false);
  const [venueModalDone, setVenueModalDone] = useState(false);
  const [showVertexTip, setShowVertexTip] = useState(true);

  // AI가 처음 추출한 brand_category 원본 보관 — updateBrandField가 brandExtraction을 덮어써도 유지
  const llmBrandCategoryRef = useRef<string | null>(null);

  // LLM 추출값으로 brandCategory context 자동 업데이트
  useEffect(() => {
    if (!brandExtraction) return;
    const be = brandExtraction as any;
    const merged = { ...(be?.brand ?? {}), ...be };

    const extracted = merged.brand_category;
    const catValue = typeof extracted === 'object' ? extracted?.value : extracted;
    if (catValue && typeof catValue === 'string') {
      if (!llmBrandCategoryRef.current) llmBrandCategoryRef.current = catValue;
      setBrandCategory(catValue);
    }

  }, [brandExtraction, setBrandCategory]);

  // 브랜드 추출 결과 필드 수정. value/confidence 쌍 구조 가정.
  const updateBrandField = (key: string, value: string) => {
    if (!brandExtraction) return;
    const next: Record<string, unknown> = { ...brandExtraction };
    const existing = next[key];
    const isValueConfidencePair = (v: unknown): v is { value: unknown; confidence?: string } =>
      typeof v === 'object' && v !== null && 'value' in v;
    // clearspace_mm 는 숫자로 저장 — Python이 산술 연산에 사용하므로 string이면 오작동
    const storedValue: unknown = key === 'clearspace_mm' ? Number(value) : value;
    const newFieldValue = isValueConfidencePair(existing)
      ? { ...existing, value: storedValue, confidence: 'user_edited' }
      : { value: storedValue, confidence: 'user_edited' };
    next[key] = newFieldValue;
    // .brand 내부도 동기화 — Python은 brand_dict.brand.[key] 에서 값을 읽음
    if (next.brand && typeof next.brand === 'object') {
      next.brand = { ...(next.brand as object), [key]: newFieldValue };
    }
    // brand_category 수정 시 추가 처리 (plain string으로 덮어씀)
    if (key === 'brand_category') {
      setBrandCategory(value);
      if (next.brand && typeof next.brand === 'object') {
        next.brand = { ...(next.brand as object), brand_category: value };
      }
      next[key] = value;
    }
    setBrandExtraction(next as typeof brandExtraction);
  };

  // 꼭짓점 말풍선 5초 후 자동 숨김
  useEffect(() => {
    if (!showVertexTip) return;
    const t = setTimeout(() => setShowVertexTip(false), 5000);
    return () => clearTimeout(t);
  }, [showVertexTip]);

  // 소형 매장 → venue_type 모달 자동 표시 (최초 1회)
  useEffect(() => {
    if (!autoDetected) return;
    const areaMm2 = calcAreaMm2(autoDetected.floor_polygon_px, autoDetected.scale_mm_per_px || 1);
    if (isSmallScale(areaMm2) && !venueModalDone && step === 'marking') {
      setShowVenueModal(true);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Backspace로 이전 단계
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Backspace') return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement).isContentEditable) return;
      if (step === 'generating') return;
      e.preventDefault();
      if (step === 'space_confirm') {
        setStep('marking');
        setSpaceData(null);
      } else if (step === 'marking') {
        navigate('/project/new');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [step, navigate, setSpaceData]);

  // 진입 조건: autoDetected 없거나 floor_polygon_px 비어있으면 /project/new
  // 2026-05-04 (M4 fix) - autoDetected 가 빈 객체 ({}) 거나 floor_polygon_px 비어있는 케이스 가드.
  //   Floor 페이지는 polygon 없으면 의미 X — guard 통과 후 빈 화면 / 에러 발생 방지.
  if (!autoDetected || !autoDetected.floor_polygon_px || autoDetected.floor_polygon_px.length === 0) {
    return <Navigate to="/project/new" replace />;
  }

  // ── SVG 마킹 클릭 ────────────────────────────────────────
  const handleSvgClick = (x: number, y: number) => {
    if (markMode === 'entrance') {
      setMarkedEntrance(prev => {
        const prevPoints = prev?.points ?? [];
        const newPoints = [...prevPoints, { x_px: x, y_px: y }];
        const first = newPoints[0]; const last = newPoints[newPoints.length - 1];
        return { points: newPoints, x_px: first.x_px, y_px: first.y_px, x2_px: last.x_px, y2_px: last.y_px };
      });
    } else if (markMode === 'sprinkler') setMarkedSprinklers(s => [...s, { x_px: x, y_px: y }]);
    else if (markMode === 'fire_hydrant') setMarkedFH(s => [...s, { x_px: x, y_px: y }]);
    else if (markMode === 'electrical_panel') setMarkedEP(s => [...s, { x_px: x, y_px: y }]);
    // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가
    // else if (markMode === 'scale_anchor') {
    //   const SNAP_THRESHOLD = 40;
    //   let snappedX = x, snappedY = y;
    //   let minDist = Infinity;
    //   for (const [vx, vy] of editablePolygon) {
    //     const d = Math.sqrt((x - vx) ** 2 + (y - vy) ** 2);
    //     if (d < SNAP_THRESHOLD && d < minDist) { minDist = d; snappedX = vx; snappedY = vy; }
    //   }
    //   if (minDist === Infinity) return;
    //   setAnchorPoints(prev => prev.length >= 2 ? [{ x: snappedX, y: snappedY }] : [...prev, { x: snappedX, y: snappedY }]);
    //   setAnchorMm('');
    // }
  };

  // ── 마킹 초기화 — autoDetected 원본 감지 결과로 복원 ─────────
  const resetMarkingsToAutoDetected = () => {
    const ent = autoDetected.entrance as { x_px?: number; y_px?: number; x2_px?: number; y2_px?: number } | null;
    if (ent && typeof ent.x_px === 'number' && typeof ent.y_px === 'number') {
      setMarkedEntrance({ points: [{ x_px: ent.x_px, y_px: ent.y_px }], x_px: ent.x_px, y_px: ent.y_px, x2_px: ent.x2_px, y2_px: ent.y2_px });
    } else {
      setMarkedEntrance(null);
    }
    setMarkedSprinklers((autoDetected.sprinklers ?? []).map(s => ({ x_px: s.x_px, y_px: s.y_px })));
    setMarkedFH((autoDetected.fire_hydrants ?? []).map(s => ({ x_px: s.x_px, y_px: s.y_px })));
    setMarkedEP((autoDetected.electrical_panels ?? []).map(s => ({ x_px: s.x_px, y_px: s.y_px })));
    setMarkMode(null);
  };

  // 자동 감지 결과와 현재 마킹이 다른지 — 마킹 초기화 버튼 활성 여부
  const isMarkingModified = (() => {
    const autoEnt = autoDetected.entrance as { x_px?: number; y_px?: number } | null;
    const autoSprCount = (autoDetected.sprinklers ?? []).length;
    const autoFhCount = (autoDetected.fire_hydrants ?? []).length;
    const autoEpCount = (autoDetected.electrical_panels ?? []).length;
    const entranceChanged = autoEnt
      ? !markedEntrance || markedEntrance.x_px !== autoEnt.x_px || markedEntrance.y_px !== autoEnt.y_px
      : !!markedEntrance;
    return entranceChanged || markedSprinklers.length !== autoSprCount || markedFH.length !== autoFhCount || markedEP.length !== autoEpCount;
  })();

  // 꼭짓점 드래그로 폴리곤이 수정됐는지 — 경계 재설정 버튼 활성 여부
  const isPolygonModified = (() => {
    const orig = autoDetected.floor_polygon_px;
    if (orig.length !== editablePolygon.length) return true;
    return orig.some((p, i) => p[0] !== editablePolygon[i][0] || p[1] !== editablePolygon[i][1]);
  })();

  // ── 면적 계산 + 규모 판별 (백엔드 기준 50평 = 165㎡) ─────────
  const areaMm2 = calcAreaMm2(autoDetected.floor_polygon_px, autoDetected.scale_mm_per_px || 1);
  const areaText = formatArea(areaMm2);
  const isSmall = isSmallScale(areaMm2);  // ≤50평 = 진규 영역 (venue_type·density 적용)

  // 폴링 헬퍼 — Job Entity 재설계 후: progress_stage/pct/message flat 구조
  const pollJob = async (
    jobId: number,
    onProgress?: (msg: string) => void,
  ): Promise<'cancelled' | void> => {
    if (!currentUser) throw new Error('로그인 필요');
    while (true) {
      await new Promise<void>(r => {
        sleepResolveRef.current = r;
        sleepTimerRef.current = window.setTimeout(() => {
          sleepTimerRef.current = null;
          sleepResolveRef.current = null;
          r();
        }, 2000);
      });
      if (cancelledRef.current) return 'cancelled';
      abortControllerRef.current = new AbortController();
      try {
        const job = await getJob(jobId, abortControllerRef.current.signal);
        abortControllerRef.current = null;
        if (cancelledRef.current) return 'cancelled';
        if (job.progress_message && onProgress) onProgress(job.progress_message);
        if (job.status === 'done') return;
        if (job.status === 'error') throw new Error(job.error_message || '작업 실패');
      } catch (e) {
        abortControllerRef.current = null;
        if (axios.isCancel(e)) return 'cancelled';
        throw e;
      }
    }
  };

  // ── 공간 계산 (B안 async) ──────────────────────────────────
  const handleCalculate = async () => {
    if (!autoDetected || !currentUser) return;
    cancelledRef.current = false;
    setError('');
    const ad = {
      ...autoDetected,
      entrance: markedEntrance,
      sprinklers: markedSprinklers,
      fire_hydrants: markedFH,
      electrical_panels: markedEP,
      floor_polygon_px: editablePolygon,
      // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가 (manualWidthMm/manualHeightMm 기반 scale 재계산)
      // ...(manualWidthMm || manualHeightMm ? (() => {
      //   const xs = editablePolygon.map(p => p[0]);
      //   const ys = editablePolygon.map(p => p[1]);
      //   const polyW = Math.max(...xs) - Math.min(...xs) || 1;
      //   const polyH = Math.max(...ys) - Math.min(...ys) || 1;
      //   const baseScale = autoDetected.scale_mm_per_px;
      //   const scaleX = manualWidthMm ? parseFloat(manualWidthMm) / polyW : baseScale;
      //   const scaleY = manualHeightMm ? parseFloat(manualHeightMm) / polyH : baseScale;
      //   return { scale_mm_per_px: (scaleX + scaleY) / 2 };
      // })() : {}),
    };
    try {
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] Python 직통 — Job 폴링 / floor_detection_id 우회
      // ════════════════════════════════════════════════════════════════
      if (USE_DIRECT) {
        const result = await calculateSpaceDirect({
          auto_detected: ad,
          brand_dict: brandExtraction ?? {},
          brand_category: brandCategory,
          venue_type: venueType,
        });
        setSpaceData(result);
        setStep('space_confirm');
        toast.success('공간 계산 완료 (직통)');
        return;
      }
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] 끝 — 아래는 기존 B안 (Java 경유) 로직
      // ════════════════════════════════════════════════════════════════
      const enq = await calculateSpace({
        auto_detected: ad,
        brand_dict: brandExtraction ?? {},
        brand_category: brandCategory,
        venue_type: venueType,
        floor_archive_id: floorArchiveId ?? undefined,
        page_number: (autoDetected as any).page_number ?? undefined,
        brand_manual_id: brandManualId ?? undefined,
        project_id: projectId ?? undefined,
      });
      setActiveJob({ id: enq.job_id, type: 'space_data', startedAt: Date.now(), projectId: projectId ?? undefined });
      if (await pollJob(enq.job_id) === 'cancelled') {
        setActiveJob(null);
        toast.info('공간 계산이 중단되었습니다.');
        return;
      }
      // space_data done 후 user_projects.floor_detection_id 조회 (Job Entity 재설계로 job 응답엔 없음)
      if (!projectId) throw new Error('project_id 없음 — detect 단계 실패');
      const project = await getProject(projectId);
      const fdId = project.floor_detection_id;
      if (!fdId) throw new Error('floor_detection_id 생성 안 됨');
      setFloorDetectionId(fdId);
      const result = await getFloorDetectionResult(fdId);
      setSpaceData(result);
      setStep('space_confirm');
      toast.success('공간 계산 완료');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '공간 계산 실패';
      setError(msg);
      toast.error(`공간 계산 실패: ${msg}`);
    } finally {
      setActiveJob(null);
    }
  };

  // ── 배치 생성 ──────────────────────────────────
  const handlePlace = async () => {
    if (!spaceData) return;
    cancelledRef.current = false;
    setError(''); setStatusIdx(0); setStatusMsg(STATUS_MESSAGES[0]); setStep('generating');
    // 2026-05-08 — buggy 자동 이동 fix. polling 시작 시점 projectId 캡처 → 완료 시 현재 projectId 와 비교.
    // 다른 프로젝트로 이동했으면 자동 이동 X (사용자 작업 방해 방지).
    const startProjectId = projectId;

    // [LOCAL_TEST_USE_DIRECT] 직통 모드는 floor_detection_id 미필요 (DB 미경유)
    if (!USE_DIRECT && (!floorDetectionId || !currentUser)) {
      setError('floor_detection_id 없음 — 공간 계산을 먼저 실행해주세요');
      return;
    }
    const interval = setInterval(() => {
      setStatusIdx(i => {
        const n = Math.min(i + 1, STATUS_MESSAGES.length - 1);
        setStatusMsg(STATUS_MESSAGES[n]);
        return n;
      });
    }, 4000);
    try {
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] Python 직통 — space_data 직접 전달, 결과 즉시 반환
      // ════════════════════════════════════════════════════════════════
      if (USE_DIRECT) {
        const result = await placeObjectsDirect({
          space_data: spaceData as unknown as Record<string, unknown>,
          density_ratio: densityRatio,
          brand_dict: brandExtraction ?? {},
          brand_category: brandCategory,
          user_requirements: userRequirements.trim() || undefined,
          venue_type: venueType,
        });
        // [LOCAL_TEST_USE_DIRECT] Python /api/place 응답 구조:
        //   { objects: [...], failed_objects: [...], placed_count, failed_count, ... }
        //   Java B안 응답은 layout_objects 키라 다름. 직통 분기는 objects 사용.
        const rawObjs = ((result.objects ?? (result as any).layout_objects ?? (result as any).placed_objects ?? []) as Array<Record<string, unknown>>);
        // Viewer3D L790 이 obj.id 를 React key 로 사용 → DB 미경유 직통 모드에서 id 수동 부여 필수.
        const layoutObjects = rawObjs.map((o, i) => ({
          ...o,
          id: (o.id as string | undefined) ?? `direct_${i}`,
          label: (o.label as string | undefined) ?? String(o.object_type ?? 'object'),
        }));
        debugLog({ event: 'USE_DIRECT_place', objects: rawObjs.length, withIds: layoutObjects.length });
        setPlacementResult({
          layout_objects: layoutObjects as never,
          validation: { status: 'ok', violations: [] },
          design_fallback_reason: (result as any).design_fallback_reason ?? null,
          sub_path: (result as any).sub_path ?? [],
          // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 place 응답에 박힘 (이전엔 space 응답).
          main_artery: (result as any).main_artery ?? null,
          // 2026-05-04 신설 - ref_quality_score (모달 트리거용). 0.0 ~ 1.0.
          ref_quality_score: (result as any).ref_quality_score ?? null,
        } as never);
        // 2026-05-01 Phase 4-2 갈래 3 — 사이클 응답의 concept_areas 로 spaceData 갱신.
        // 도면 분석 시점엔 concept_area 노드 안 돌아서 spaceData.concept_areas 비어있음.
        const respConceptAreas = (result as any).concept_areas;
        if (Array.isArray(respConceptAreas) && respConceptAreas.length > 0 && spaceData) {
          setSpaceData({ ...spaceData, concept_areas: respConceptAreas } as any);
        }
        setWalls([]); setSelectedObjectIndices([]); setSelectedWallId(null);
        clearInterval(interval);
        // 2026-04-29 (#264 fail-loud): design 단계 fallback 발생 시 사용자 경고.
        // REF_CONTEXT_MISSING / API_KEY_MISSING / CIRCUIT_BREAKER 등 → 배치 품질 저하 가능.
        const fbReason = (result as any).design_fallback_reason as string | null | undefined;
        if (fbReason) {
          toast.error(`배치 품질 저하 가능 — design fallback: ${fbReason}. 레퍼런스 이미지/API 점검 필요.`);
        } else {
          toast.success('배치 생성 완료 (직통)', {
            actionLabel: '결과 보기 →',
            onAction: () => navigate('/project/result'),
          });
        }
        // 2026-05-09: 직통 분기 강제 이동 fix — B 안과 같은 패턴 (sameProject 검증).
        // 이전: 무조건 navigate('/project/result') → 다른 프로젝트에 있어도 강제 이동 발생.
        // 이제: 같은 프로젝트 페이지에 머물러 있을 때만 자동 이동, 그 외엔 토스트만.
        {
          const path = window.location.pathname;
          const sameProject = projectIdRef.current === startProjectId;
          const onProjectPage = path.startsWith('/project/new')
                             || path.startsWith('/project/floor')
                             || path.startsWith('/project/result');
          if (onProjectPage && sameProject) {
            debugLog(`[handlePlace] 직통 완료 → /project/result 자동 이동 (projectId=${startProjectId})`);
            navigate('/project/result');
          } else if (onProjectPage && !sameProject) {
            debugLog(`[handlePlace] 직통 완료 — 다른 프로젝트 작업 중 (start=${startProjectId}, current=${projectIdRef.current}), 토스트만 표시`);
          } else {
            debugLog('[handlePlace] 직통 완료 — 사용자가 프로젝트 페이지 떠남, 토스트만 표시');
          }
        }
        return;
      }
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] 끝 — 아래는 기존 B안 (Java 경유) 로직
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] 위 분기로 currentUser null 가드 narrowing 깨짐 → 재확인
      if (!currentUser || !floorDetectionId) {
        throw new Error('currentUser 또는 floor_detection_id 누락');
      }
      const enq = await placeObjects({
        floor_detection_id: floorDetectionId,
        density_ratio: densityRatio,
        brand_dict: brandExtraction ?? {},
        brand_category: brandCategory,
        user_requirements: userRequirements.trim() || undefined,
        page_number: (autoDetected as any)?.page_number ?? undefined,
        brand_manual_id: brandManualId ?? undefined,
        project_id: projectId ?? undefined,
      });
      setActiveJob({ id: enq.job_id, type: 'place', startedAt: Date.now(), projectId: projectId ?? undefined });
      if (await pollJob(enq.job_id, (msg) => setStatusMsg(msg)) === 'cancelled') {
        clearInterval(interval);
        setActiveJob(null);
        setStep('space_confirm');
        toast.info('배치 생성이 중단되었습니다.');
        return;
      }
      // place done 후 projectId state 로 결과 조회 (Job 응답엔 project_id 없음)
      const finalProjectId = projectId ?? undefined;
      if (!finalProjectId) throw new Error('project_id 누락');
      const detail = await getProject(finalProjectId);
      setPlacementResult({
        layout_objects: detail.layout_objects ?? [],
        validation: { status: 'ok', violations: [] },
        sub_path: (detail as any).sub_path ?? [],
        // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 placement_result 에 박힘 (Java getProjectDetail 응답에 포함).
        main_artery: (detail as any).main_artery ?? null,
        // 2026-05-04 신설 - ref_quality_score (모달 트리거용). 0.0 ~ 1.0.
        ref_quality_score: (detail as any).ref_quality_score ?? null,
      } as never);
      // 2026-05-01 Phase 4-2 갈래 3 — Java detail.space_data 에 concept_areas 박혀있음.
      // 도면 분석 시점에 박은 spaceData 는 concept_areas 비어있어서 갱신 필요.
      if (detail.space_data) setSpaceData(detail.space_data as any);
      setWalls([]); setSelectedObjectIndices([]); setSelectedWallId(null);
      clearInterval(interval);
      toast.success('배치 생성 완료', {
        actionLabel: '결과 보기 →',
        onAction: () => navigate('/project/result'),
      });
      // 2026-04-28 fix → 2026-05-08 추가 fix:
      // (1) 사용자가 같은 프로젝트의 /project/new / /project/floor / /project/result 에 있을 때만 자동 이동.
      // (2) 다른 프로젝트로 이동했거나 다른 페이지 (홈 / 마이페이지) 면 토스트만.
      // 핵심: startProjectId (시작 시점) 와 projectIdRef.current (완료 시점) 비교. 다르면 = 다른 프로젝트 작업 중 → 자동 이동 X.
      const path = window.location.pathname;
      const sameProject = projectIdRef.current === startProjectId;
      const onProjectPage = path.startsWith('/project/new')
                         || path.startsWith('/project/floor')
                         || path.startsWith('/project/result');
      if (onProjectPage && sameProject) {
        debugLog(`[handlePlace] 완료 → /project/result 자동 이동 (projectId=${startProjectId})`);
        navigate('/project/result');
      } else if (onProjectPage && !sameProject) {
        debugLog(`[handlePlace] 완료 — 다른 프로젝트 작업 중 (start=${startProjectId}, current=${projectIdRef.current}), 토스트만 표시`);
      } else {
        debugLog('[handlePlace] 완료 — 사용자가 프로젝트 페이지 떠남, 토스트만 표시');
      }
    } catch (e: unknown) {
      clearInterval(interval);
      const msg = e instanceof Error ? e.message : '배치 생성 실패';
      setError(msg);
      toast.error(`배치 실패: ${msg}`);
      setStep('space_confirm');
    } finally {
      setStatusMsg('');
      setActiveJob(null);
    }
  };


  return (
    <div className="flex flex-1 overflow-hidden">
      {/* ════ LEFT PANEL ════ */}
      <aside className="w-80 shrink-0 flex flex-col border-r border-border overflow-y-auto">
        {/* 2026-05-01 — 글로벌 뒤로가기 (단계 무관). 동일 프로젝트 내 재구조화용 */}
        <div className="px-4 py-3 border-b border-border">
          <button
            onClick={() => setShowBackConfirm(true)}
            disabled={spaceJobRunning || placeJobRunning}
            className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-main border border-border hover:border-white/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40"
          >
            <ArrowLeft size={12} /> 뒤로 (도면 다시)
          </button>
        </div>

        {error && (
          <div className="mx-4 mt-3 p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
            <AlertCircle size={13} className="shrink-0 mt-0.5" /> {error}
          </div>
        )}

        {/* 브랜드 파싱 결과 — 매뉴얼 없을 때도 섹션 유지 */}
        <div className="border-b border-border">
          <button
            onClick={() => setBrandOpen(v => !v)}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors"
          >
            <span className="text-sm font-bold flex items-center gap-2">
              📄 브랜드 파싱 결과
            </span>
            {brandOpen ? <ChevronUp size={14} className="text-text-muted" /> : <ChevronDown size={14} className="text-text-muted" />}
          </button>
          {!brandExtraction && (
            <div className="px-4 pb-1 text-[10px] text-text-muted">
              브랜드 매뉴얼 없음 · <span className="text-text-main font-semibold">{brandCategory}</span> 카테고리
              {brandCategory !== '기타' && <span className="text-text-muted"> (직접 선택)</span>}
            </div>
          )}
          {!brandExtraction && brandOpen && (
            <div className="px-4 pb-3 space-y-2">
<div className="bg-black/30 rounded-xl p-2.5 border border-border">
                <p className="text-[10px] text-text-muted mb-1.5">브랜드 카테고리</p>
                <select
                  value={brandCategory}
                  onChange={e => setBrandCategory(e.target.value)}
                  disabled={step !== 'marking'}
                  className="w-full bg-black/20 border border-border rounded-md px-2 py-1 text-xs text-text-main focus:outline-none focus:border-accent/60 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ backgroundColor: '#1a2035', color: '#e2e8f0' }}
                >
                  {['캐릭터 IP', '패션 브랜드', '뷰티·코스메틱', 'F&B', '기타'].map(c => (
                    <option key={c} value={c} style={{ backgroundColor: '#1a2035', color: '#e2e8f0' }}>{c}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
          {brandExtraction && brandOpen && (() => {
            const be = brandExtraction as any;
            const brand = be?.brand ?? {};
            const merged = { ...brand, ...be };
            const getVal = (obj: any) => obj?.value ?? (typeof obj === 'string' || typeof obj === 'number' ? obj : null);

            const charOrientation = getVal(merged.character_orientation);
            const prohibitedMaterial = getVal(merged.prohibited_material);
            const logoSpacing = getVal(merged.logo_clearspace_mm);
            const figures: string[] = merged.figures_mentioned ?? [];
            const placementRules: any[] = merged.placement_rules ?? [];

            const CATEGORIES = ['캐릭터 IP', '패션 브랜드', '뷰티·코스메틱', 'F&B', '기타'];
            const zoneLabel: Record<string, string> = { entrance_zone: '입구존', mid_zone: '중앙존', deep_zone: '후방존' };
            const wallLabel: Record<string, string> = { flush: '벽 밀착', near: '벽 근처', free: '자유 배치' };

            return (
              <div className="px-4 pb-3 space-y-3 max-h-[360px] overflow-y-auto [&::-webkit-scrollbar]:w-2.5 [&::-webkit-scrollbar-track]:bg-white/5 [&::-webkit-scrollbar-track]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/25 [&::-webkit-scrollbar-thumb]:rounded-full hover:[&::-webkit-scrollbar-thumb]:bg-white/40">
                {/* 브랜드 카테고리 */}
                <div className="bg-black/30 rounded-xl p-3 border border-border">
                  <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wide mb-2">브랜드 카테고리</p>
                  <select
                    value={brandCategory}
                    onChange={e => updateBrandField('brand_category', e.target.value)}
                    disabled={step !== 'marking'}
                    className="w-full bg-black/20 border border-border rounded-md px-2 py-1.5 text-xs text-text-main focus:outline-none focus:border-accent/60 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ backgroundColor: '#1a2035', color: '#e2e8f0' }}
                  >
                    {CATEGORIES.map(c => (
                      <option key={c} value={c} style={{ backgroundColor: '#1a2035', color: '#e2e8f0' }}>{c}</option>
                    ))}
                  </select>
                  {(() => {
                    const aiValue = llmBrandCategoryRef.current;
                    const isChanged = aiValue && brandCategory !== aiValue;
                    return isChanged ? (
                      <p className="text-[10px] mt-2 text-amber-400">
                        사용자가 <span className="font-semibold">"{brandCategory}"</span>로 변경했습니다.
                        <span className="text-text-muted"> (AI 추출: "{aiValue}")</span>
                      </p>
                    ) : (
                      <p className="text-[10px] text-text-muted mt-2">
                        AI가 <span className="text-text-main font-semibold">"{brandCategory}"</span>로 추출했습니다. 변경이 필요하면 위 드롭다운에서 선택하세요.
                      </p>
                    );
                  })()}
                </div>

                {/* 조형물 */}
                {figures.length > 0 && (
                  <div className="bg-black/30 rounded-xl p-3 border border-border">
                    <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wide mb-2">조형물</p>
                    <div className="flex flex-wrap gap-1.5">
                      {figures.map((fig: string, i: number) => (
                        <span key={i} className="px-2 py-0.5 rounded-full bg-primary/15 border border-primary/30 text-[10px] text-primary/90">
                          {fig}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* 집기(오브젝트) 배치 규칙 */}
                {placementRules.length > 0 && (
                  <div className="bg-black/30 rounded-xl p-3 border border-border">
                    <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wide mb-2">집기(오브젝트) 배치 규칙</p>
                    <div className="divide-y divide-border/50">
                      {placementRules.map((rule: any, i: number) => {
                        const tags: { label: string; color: string }[] = [];
                        const min = rule.min_count, max = rule.max_count;
                        if (min != null && max != null && min !== max) tags.push({ label: `${min}~${max}개`, color: 'bg-accent/15 text-accent border-accent/30' });
                        else if (max != null) tags.push({ label: `${max}개`, color: 'bg-accent/15 text-accent border-accent/30' });
                        else if (min != null) tags.push({ label: `${min}개 이상`, color: 'bg-accent/15 text-accent border-accent/30' });
                        if (rule.preferred_zone) tags.push({ label: zoneLabel[rule.preferred_zone] ?? rule.preferred_zone, color: 'bg-blue-500/10 text-blue-400 border-blue-500/30' });
                        if (rule.wall_attachment) tags.push({ label: wallLabel[rule.wall_attachment] ?? rule.wall_attachment, color: 'bg-purple-500/10 text-purple-400 border-purple-500/30' });
                        if (rule.preferred_wall) tags.push({ label: rule.preferred_wall, color: 'bg-purple-500/10 text-purple-400 border-purple-500/30' });
                        return (
                          <div key={i} className="py-2 first:pt-0 last:pb-0">
                            <p className="text-xs text-text-main font-medium mb-1">{rule.name || rule.object_type}</p>
                            {tags.length > 0 && (
                              <div className="flex flex-wrap gap-1">
                                {tags.map((tag, j) => (
                                  <span key={j} className={`px-1.5 py-0.5 rounded border text-[9px] ${tag.color}`}>{tag.label}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* 추가 정보 */}
                {(charOrientation || prohibitedMaterial || logoSpacing != null) && (
                  <div className="bg-black/30 rounded-xl p-3 border border-border">
                    <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wide mb-2">추가 정보</p>
                    <div className="space-y-1.5">
                      {charOrientation && (
                        <div className="grid grid-cols-[72px_1fr] gap-1">
                          <span className="text-[10px] text-text-muted">캐릭터 방향</span>
                          <span className="text-[10px] text-text-main">{charOrientation}</span>
                        </div>
                      )}
                      {prohibitedMaterial && (
                        <div className="grid grid-cols-[72px_1fr] gap-1">
                          <span className="text-[10px] text-text-muted">금지 소재</span>
                          <span className="text-[10px] text-text-main leading-relaxed">{prohibitedMaterial}</span>
                        </div>
                      )}
                      {logoSpacing != null && (
                        <div className="grid grid-cols-[72px_1fr] gap-1">
                          <span className="text-[10px] text-text-muted">로고 여백</span>
                          <span className="text-[10px] text-text-main">{logoSpacing}mm</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        {/* 위치 마킹 */}
        <div className="border-b border-border">
          <button
            className={`w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors ${step !== 'marking' ? 'opacity-50' : ''}`}
            onClick={() => { if (step === 'marking') setMarkingOpen(v => !v); }}
          >
            <span className="text-sm font-bold flex items-center gap-2">
              <Layers size={14} className="text-accent" /> 위치 마킹
              {markedEntrance && <span className="w-2 h-2 rounded-full bg-accent ml-1" />}
            </span>
            {step === 'marking' && (markingOpen ? <ChevronUp size={14} className="text-text-muted" /> : <ChevronDown size={14} className="text-text-muted" />)}
          </button>
          {step === 'marking' && markingOpen && (
            <div className="px-4 pb-3">
              {/* 도면 크기 (항상 표시) */}
              <div className="mb-1.5 p-2.5 bg-black/20 border border-border rounded-lg">
                <div className="text-[10px] text-text-muted mb-0.5">📐 도면 크기</div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-text-main font-semibold">{areaText}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold ${isSmall ? 'bg-accent/20 text-accent' : 'bg-primary/20 text-primary'}`}>
                    {isSmall ? '소형·중형' : '대형'}
                  </span>
                </div>
              </div>

              {/* 건물 유형 — 소형·중형(≤50평)만 표시 */}
              {isSmall && (
                <div className="mb-3">
                  <label className="text-[10px] text-text-muted block mb-1">건물 유형</label>
                  <div className="flex gap-1">
                    <button
                      onClick={() => setVenueType('street_complex')}
                      className={`flex-1 px-2 py-1.5 rounded-lg text-[11px] border transition-all ${
                        venueType === 'street_complex'
                          ? 'bg-accent/20 border-accent/50 text-accent font-semibold'
                          : 'bg-black/20 border-border text-text-muted hover:border-white/20'
                      }`}
                    >집합 상가</button>
                    <button
                      onClick={() => setVenueType('street_standalone')}
                      className={`flex-1 px-2 py-1.5 rounded-lg text-[11px] border transition-all ${
                        venueType === 'street_standalone'
                          ? 'bg-accent/20 border-accent/50 text-accent font-semibold'
                          : 'bg-black/20 border-border text-text-muted hover:border-white/20'
                      }`}
                    >단독 로드샵</button>
                  </div>
                </div>
              )}

              {/* 배치 밀도 슬라이더 — 소형·중형만 표시 */}
              {isSmall && (
                <div className="mb-3">
                  <div className="text-[10px] text-text-muted mb-1 flex items-center justify-between">
                    <span>배치 밀도</span>
                    <span className="text-accent font-bold">{Math.round(densityRatio * 100)}%</span>
                  </div>
                  <input type="range" min={10} max={50} step={5} value={densityRatio * 100}
                    onChange={e => setDensityRatio(Number(e.target.value) / 100)}
                    className="w-full accent-primary h-1.5 rounded-full cursor-pointer" />
                </div>
              )}
              <p className="text-xs text-text-muted mt-5 mb-0.5">필요한 위치를 직접 클릭해 추가하세요</p>
              <p className="text-[10px] text-text-muted/60 mb-1.5">버튼을 다시 클릭하면 모드가 해제됩니다</p>
              <div className="flex mb-3">
                <button
                  onClick={resetMarkingsToAutoDetected}
                  disabled={!isMarkingModified}
                  className={`px-3 py-1 rounded-lg text-xs border transition-all ${
                    isMarkingModified
                      ? 'border-amber-500/50 text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 cursor-pointer'
                      : 'border-border text-text-muted/30 cursor-not-allowed pointer-events-none'
                  }`}
                >
                  ↺ 마킹 초기화
                </button>
              </div>
              <div className="space-y-1 mb-3">
                {(['entrance', 'sprinkler', 'fire_hydrant', 'electrical_panel'] as const).map(mode => {
                  const cfg = MODE_CFG[mode];
                  const count = mode === 'entrance' ? (markedEntrance ? 1 : 0)
                    : mode === 'sprinkler' ? markedSprinklers.length
                    : mode === 'fire_hydrant' ? markedFH.length : markedEP.length;
                  return (
                    <div key={mode} className="flex items-center gap-1">
                      <button onClick={() => setMarkMode(markMode === mode ? null : mode)}
                        className={`flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs border transition-all ${markMode === mode ? cfg.activeClass : 'bg-black/20 border-border text-text-muted hover:border-white/20'}`}>
                        <span>{cfg.label}</span>
                        <span className={count > 0 ? 'text-accent font-semibold' : 'text-text-muted/50'}>
                          {mode === 'entrance' ? (count > 0 ? '✓' : '미설정') : `${count}개`}
                        </span>
                      </button>
                      {count > 0 && (
                        <button onClick={() => {
                          if (mode === 'entrance') setMarkedEntrance(null);
                          else if (mode === 'sprinkler') setMarkedSprinklers([]);
                          else if (mode === 'fire_hydrant') setMarkedFH([]);
                          else setMarkedEP([]);
                        }} className="text-[10px] text-red-400/60 hover:text-red-400 px-1.5 py-1.5 rounded-lg border border-border hover:border-red-400/40 transition-all">✕</button>
                      )}
                    </div>
                  );
                })}
              </div>
              {/* 스케일 수동 앵커 UI — 추후 기능 필요 시 다시 추가 */}
              {/* {autoDetected && (autoDetected.scale_confidence ?? 1) < 0.5 && !manualWidthMm && !manualHeightMm && (
                <p className="text-[10px] text-amber-400 mb-2">
                  자동 스케일 신뢰도 낮음 — 스케일 앵커로 수동 설정 권장
                </p>
              )}
              <div className="mb-2">
                <button
                  onClick={() => { setMarkMode(markMode === 'scale_anchor' ? null : 'scale_anchor'); setAnchorPoints([]); setAnchorMm(''); }}
                  className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs border transition-all ${
                    markMode === 'scale_anchor' ? 'bg-yellow-500/20 border-yellow-500/50 text-yellow-300' : 'bg-black/20 border-border text-text-muted hover:border-white/20'
                  }`}>
                  <span>스케일 앵커</span>
                  <span className={(manualWidthMm || manualHeightMm) ? 'text-accent font-semibold' : 'text-text-muted/50'}>
                    {(manualWidthMm || manualHeightMm)
                      ? [manualWidthMm && `가로 ${manualWidthMm}`, manualHeightMm && `세로 ${manualHeightMm}`].filter(Boolean).join(' / ') + 'mm'
                      : '미설정'}
                  </span>
                </button>
                {(manualWidthMm || manualHeightMm) && (
                  <button onClick={() => { setManualWidthMm(''); setManualHeightMm(''); }}
                    className="text-[9px] text-text-muted hover:text-red-400 underline mt-0.5">초기화</button>
                )}
              </div>
              {markMode === 'scale_anchor' && anchorPoints.length === 2 && (() => {
                const dx = Math.abs(anchorPoints[1].x - anchorPoints[0].x);
                const dy = Math.abs(anchorPoints[1].y - anchorPoints[0].y);
                const isHorizontal = dx >= dy;
                return (
                  <div className="mb-3 p-2.5 bg-yellow-500/10 border border-yellow-500/30 rounded-xl space-y-2">
                    <p className="text-[10px] text-yellow-300/70">
                      두 점이 {isHorizontal ? '가로' : '세로'} 방향 — 거리 입력 시 자동 반영
                    </p>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-yellow-300 w-16 shrink-0">거리</span>
                      <input type="number" value={anchorMm}
                        onChange={e => { setAnchorMm(e.target.value); if (isHorizontal) setManualWidthMm(e.target.value); else setManualHeightMm(e.target.value); }}
                        placeholder="mm" className="flex-1 px-2 py-1 text-xs rounded-lg bg-black/30 border border-border text-text-main" />
                      <span className="text-[10px] text-text-muted">mm</span>
                    </div>
                    <button onClick={() => { setAnchorPoints([]); setAnchorMm(''); setMarkMode(null); }}
                      className="w-full py-1.5 text-xs rounded-lg bg-yellow-500 text-black font-semibold hover:bg-yellow-400">적용</button>
                  </div>
                );
              })()} */}
              {!markedEntrance && <p className="text-[10px] text-amber-400 mb-2">입구 위치를 클릭하세요</p>}
              <div className="flex gap-2 mt-4">
                <button
                  onClick={() => setShowBackConfirm(true)}
                  disabled={spaceJobRunning || placeJobRunning}
                  className="px-3 py-2.5 rounded-xl border border-border text-text-muted text-xs hover:bg-white/5 hover:text-text-main disabled:opacity-40 transition-colors flex items-center gap-1"
                >
                  <ArrowLeft size={13} /> 뒤로
                </button>
                <button onClick={handleCalculate} disabled={!markedEntrance || spaceJobRunning || placeJobRunning}
                  className="flex-1 py-2.5 rounded-xl bg-primary text-white text-xs font-bold hover:bg-primary/90 disabled:opacity-40 transition-colors flex items-center justify-center gap-1.5">
                  {spaceJobRunning
                    ? <><RefreshCw size={12} className="animate-spin" /> 공간 분석중...</>
                    : <>공간 계산 →</>}
                </button>
              </div>
            </div>
          )}
          {step === 'generating' && (
            <div className="px-4 pb-3 text-xs text-text-muted space-y-1">
              <div className="flex justify-between"><span>입구</span><span className="text-accent">{markedEntrance ? '✓' : '—'}</span></div>
              <div className="flex justify-between"><span>스프링클러</span><span>{markedSprinklers.length}개</span></div>
              <div className="flex justify-between"><span>소화전</span><span>{markedFH.length}개</span></div>
              <div className="flex justify-between"><span>분전반</span><span>{markedEP.length}개</span></div>
            </div>
          )}
        </div>

        {/* 공간 분석 */}
        {spaceData && (
          <div className="border-b border-border">
            <button
              className={`w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors ${step !== 'space_confirm' ? 'opacity-50' : ''}`}
              onClick={() => { if (step === 'space_confirm') setSpaceOpen(v => !v); }}
            >
              <span className="text-sm font-bold flex items-center gap-2">
                <Box size={14} className="text-primary" /> 공간 분석
                <span className="w-2 h-2 rounded-full bg-accent ml-1" />
              </span>
              {step === 'space_confirm' && (spaceOpen ? <ChevronUp size={14} className="text-text-muted" /> : <ChevronDown size={14} className="text-text-muted" />)}
            </button>
            {step === 'space_confirm' && spaceOpen && (
              <div className="px-4 pb-3">
                <div className="space-y-1.5 mb-3 text-xs">
                  {[
                    { label: '기준점 수', val: Object.keys(spaceData.reference_points ?? {}).length },
                    { label: 'Dead Zone', val: `${spaceData.dead_zones?.length ?? 0}개` },
                  ].map(({ label, val }) => (
                    <div key={label} className="flex justify-between bg-black/20 rounded-lg px-2.5 py-1.5 border border-border">
                      <span className="text-text-muted">{label}</span>
                      <span className="text-text-main font-bold">{val}</span>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setSpaceData(null); setFloorDetectionId(null); setStep('marking'); }}
                    disabled={placeJobRunning || spaceJobRunning}
                    className="px-3 py-2.5 rounded-xl border border-border text-text-muted text-xs hover:bg-white/5 hover:text-text-main disabled:opacity-40 transition-colors flex items-center gap-1"
                  >
                    <ArrowLeft size={13} /> 뒤로
                  </button>
                  <button onClick={handlePlace} disabled={placeJobRunning || spaceJobRunning}
                    className="flex-1 py-2.5 rounded-xl bg-primary text-white text-xs font-bold hover:bg-primary/90 disabled:opacity-40 transition-colors flex items-center justify-center gap-1.5">
                    {placeJobRunning
                      ? <><RefreshCw size={12} className="animate-spin" /> 배치 생성중...</>
                      : <>배치 생성 →</>}
                  </button>
                </div>
              </div>
            )}
            {step === 'generating' && (
              <div className="px-4 pb-3 text-xs text-text-muted space-y-1">
                <div className="flex justify-between"><span>기준점</span><span>{Object.keys(spaceData?.reference_points ?? {}).length}개</span></div>
                <div className="flex justify-between"><span>Dead Zone</span><span>{spaceData?.dead_zones?.length ?? 0}개</span></div>
                <div className="flex justify-between"><span>밀도</span><span className="text-accent">{Math.round(densityRatio * 100)}%</span></div>
              </div>
            )}
          </div>
        )}
      </aside>

      {/* ════ RIGHT PANEL ════ */}
      <main className="flex-1 flex overflow-hidden">
        {step === 'marking' && (
          <div className="flex-1 flex flex-col items-center justify-center bg-[#070d1a] p-4 gap-2">
            <div className="w-full max-w-2xl max-h-[70vh] relative">
              <MarkingSVG polygon={editablePolygon} markMode={markMode}
                entrance={markedEntrance} sprinklers={markedSprinklers}
                fireHydrants={markedFH} electricalPanels={markedEP}
                onSvgClick={handleSvgClick}
                // anchorPoints={anchorPoints} — 스케일 수동 앵커 필요 시 다시 추가
                imageBase64={autoDetected.image_base64}
                visionTransform={autoDetected.vision_transform}
                onPolygonChange={(poly) => { setEditablePolygon(poly); setShowVertexTip(false); }} />
              {showVertexTip && !markMode && (
                <div className="absolute top-3 left-1/2 -translate-x-1/2 pointer-events-none"
                  style={{ animation: 'pulse 1.5s cubic-bezier(0.4,0,0.6,1) 3' }}>
                  <div className="bg-slate-700 border border-blue-400/70 rounded-xl px-4 py-2.5 text-xs text-blue-100 shadow-lg whitespace-nowrap">
                    도면의 <span className="font-bold text-white">파란 꼭짓점</span>을 드래그해 경계를 조정할 수 있습니다.
                  </div>
                  <div className="w-2 h-2 bg-slate-700 border-r border-b border-blue-400/70 rotate-45 mx-auto -mt-1" />
                </div>
              )}
            </div>
            {editablePolygon.length > 0 && (() => {
              const scale = autoDetected.scale_mm_per_px || 1;
              const xs = editablePolygon.map(p => p[0]);
              const ys = editablePolygon.map(p => p[1]);
              const wMm = Math.round((Math.max(...xs) - Math.min(...xs)) * scale);
              const hMm = Math.round((Math.max(...ys) - Math.min(...ys)) * scale);
              return (
                <div className="flex flex-col items-center gap-3">
                  <p className="text-xs text-text-main font-medium">
                    가로 {wMm}mm · 세로 {hMm}mm{autoDetected.ceiling_height_mm ? ` · 층고 ${autoDetected.ceiling_height_mm}mm` : ''}
                  </p>
                  <button
                    onClick={() => { setEditablePolygon(autoDetected.floor_polygon_px); setShowVertexTip(true); }}
                    disabled={!isPolygonModified}
                    className={`text-sm rounded-md px-5 py-2 border transition-all ${
                      isPolygonModified
                        ? 'border-amber-500/50 text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 cursor-pointer'
                        : 'border-border text-text-muted/30 cursor-not-allowed pointer-events-none'
                    }`}
                  >
                    ↺ 경계 재설정 (자동 감지 결과로 복원)
                  </button>
                </div>
              );
            })()}
          </div>
        )}
        {step === 'space_confirm' && spaceData && (
          <div className="flex-1 flex items-center justify-center bg-[#070d1a] p-4">
            <div className="w-full max-w-2xl max-h-[70vh]">
              <SpaceConfirmSVG spaceData={spaceData} />
            </div>
          </div>
        )}
        {step === 'generating' && (
          <div className="flex-1 flex flex-col items-center justify-center gap-6 bg-[#070d1a]">
            <div className="w-16 h-16 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
            <div className="text-center">
              <p className="text-sm font-bold text-text-main mb-1">{statusMsg}</p>
              <div className="flex gap-1 justify-center mt-3">
                {STATUS_MESSAGES.map((_, i) => (
                  <div key={i} className={`w-1.5 h-1.5 rounded-full transition-all ${i <= statusIdx ? 'bg-primary' : 'bg-white/10'}`} />
                ))}
              </div>
            </div>
            <button
              onClick={() => {
                cancelledRef.current = true;
                interruptSleep();
                if (activeJob?.id) {
                  cancelJob(activeJob.id).catch(e => console.warn('[cancel] 서버 취소 실패', e));
                }
              }}
              className="flex items-center gap-2 px-4 py-2 rounded-xl border border-red-500/40 text-red-400 bg-red-500/10 hover:bg-red-500/20 text-xs font-semibold transition-colors"
            >
              <Square size={11} fill="currentColor" />
              중단하고 돌아가기
            </button>
          </div>
        )}
      </main>

      {/* ── 뒤로가기 확인 모달 ── */}
      {showBackConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#1a1a2e] border border-border rounded-2xl p-6 w-[360px] shadow-2xl">
            <h3 className="text-sm font-bold text-text-main mb-2">파일 업로드로 돌아가기</h3>
            <p className="text-[11px] text-text-muted mb-4 leading-relaxed">
              도면 분석 결과가 초기화됩니다.<br />
              파일은 유지되며 다시 분석할 수 있습니다.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setShowBackConfirm(false)}
                className="flex-1 py-2 rounded-xl border border-border text-xs text-text-muted hover:bg-white/5 transition-colors"
              >취소</button>
              <button
                onClick={() => { setShowBackConfirm(false); navigate('/project/new', { state: { fromBack: true } }); }}
                className="flex-1 py-2 rounded-xl bg-red-500/20 border border-red-500/40 text-xs text-red-300 hover:bg-red-500/30 transition-colors"
              >돌아가기</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Venue Type 모달 (소형 매장 최초 진입 시) ── */}
      {showVenueModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#1a1a2e] border border-border rounded-2xl p-6 w-[360px] shadow-2xl">
            <h3 className="text-sm font-bold text-text-main mb-1">건물 유형 선택</h3>
            <p className="text-[11px] text-text-muted mb-4">
              소형 매장({areaText})으로 감지되었습니다. 건물 유형을 선택해주세요.
            </p>
            <div className="flex gap-2 mb-4">
              <button
                onClick={() => { setVenueType('street_complex'); setShowVenueModal(false); setVenueModalDone(true); }}
                className="flex-1 py-3 rounded-xl text-xs font-bold border-2 transition-all bg-accent/10 border-accent/40 text-accent hover:bg-accent/20"
              >
                집합 상가<br/><span className="text-[10px] font-normal text-text-muted">상업건축물 · 소방 엄격</span>
              </button>
              <button
                onClick={() => { setVenueType('street_standalone'); setShowVenueModal(false); setVenueModalDone(true); }}
                className="flex-1 py-3 rounded-xl text-xs font-bold border-2 transition-all bg-primary/10 border-primary/40 text-primary hover:bg-primary/20"
              >
                단독 로드샵<br/><span className="text-[10px] font-normal text-text-muted">개인건축물 · 제약 완화</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
