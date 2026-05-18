/**
 * ResultPage — 배치 결과 3D/2D 뷰어 + 요구사항 재생성 + 가벽 설치 + 오브젝트 조작
 * (구 AppShell step=result)
 *
 * 진입 조건: placementResult 있어야 함 (없으면 /project/new로)
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import {
  AlertCircle, ArrowLeft, Package, RotateCcw, Trash2,
  RefreshCw, Send, RotateCw, Download, FileText, ChevronDown,
} from 'lucide-react';
import { useProject } from '../../context/ProjectContext';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import {
  placeObjects, getJob, getProject, renameProject,
  getObjectPalette, type ObjectPaletteItem, fetchProjectReport, generateReportFromResult,
  // [LOCAL_TEST_USE_DIRECT] Python 직통 재배치 (env: VITE_USE_DIRECT=true)
  USE_DIRECT, placeObjectsDirect,
} from '../../lib/api';
import AnalysisReport from '../../components/mypage/AnalysisReport';
import type { AnalysisReportData } from '../../components/mypage/mockAnalysisReport';
import { downloadPythonGlb } from '../../lib/glbApi';
import { debugLog } from '../../lib/debug';
import { computePollInterval } from '../../hooks/useJob';
import FloorView2D from '../../components/FloorView2D';
import ShinViewer3D, { CONCEPT_AREA_BORDER_COLORS, CONCEPT_AREA_LABEL_KO } from '../../components/viewer/Viewer3D';
// GLB 뷰 모드 보류 — 재활성 시 import 해제
// import PythonGlbViewer3D from '../../components/viewer/PythonGlbViewer3D';
import GlbExportButton from '../../components/viewer/GlbExportButton';
import ResultPalette, { type EditMode, type ArteryMode } from '../../components/project/ResultPalette';
import RefTraceWarningModal from '../../components/project/RefTraceWarningModal';
import LimitExceededModal from '../../components/LimitExceededModal';
import type { PlacedObject as TPO, DetectedObject as TDO } from '../../components/ThreeViewer';
import type { LayoutObject } from '../../types/floor';
import {
  OBJECT_NAMES, OBJECT_COLORS,
  STATUS_MESSAGES, newWallId, toLO,
  calcAreaMm2FromMm, formatArea, isSmallScale,
  DEAD_ZONE_TYPES,
} from './_constants';

export default function ResultPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuth();
  const { toast } = useToast();
  const {
    spaceData, placementResult, setPlacementResult, densityRatio,
    reqText, setReqText, appliedReqs, setAppliedReqs,
    localPlaced, setLocalPlaced,
    walls, setWalls,
    selectedObjectIndices, setSelectedObjectIndices, selectedObjectIndicesRef,
    selectedWallId, setSelectedWallId,
    pushHistory, popHistory,
    reset,
    floorArchiveId, brandManualId, floorDetectionId,
    projectId,
    setActiveJob,
    brandExtraction, brandCategory,
    venueType,
    // 2026-05-07 — /project/result 새로고침/deep-link 진입 시 hydrate 용 setter.
    // ProjectResolver 안 거치는 케이스 (URL 직접 진입) 에서 ResultPage 가 직접 detail fetch + ProjectContext 복원.
    setProjectId, setResumingFilename,
    setFloorArchiveId, setBrandManualId, setFloorDetectionId,
    setAutoDetected, setBrandExtraction, setSpaceData,
  } = useProject();

  const [isProcessing, setIsProcessing] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [statusIdx, setStatusIdx] = useState(0);
  const [error, setError] = useState('');
  const [limitModal, setLimitModal] = useState<string | null>(null);
  const [mode, setMode] = useState<'3d' | '2d'>('3d');
  const [showBackConfirm, setShowBackConfirm] = useState(false);
  // 2026-05-07 — /project/result 새로고침/deep-link 진입 시 hydrate 진행 표시.
  // ProjectResolver 를 안 거치고 직접 ResultPage 에 마운트되는 케이스 (URL 새로고침 등) 에서 detail fetch 진행 중 표시.
  // 2026-05-08 race condition fix — useState 초기값 false 면 첫 render 시 isHydrating=false → <Navigate> 즉시 trigger
  // → unmount → useEffect 의 setIsHydrating(true) 가 안 도달 (cleanup 의 cancelled=true). 진단 console.log 가
  // 'hydrate start' 만 떠있고 'detail received' 안 뜬 게 그 증거. 초기값을 동기 계산 (projectId 있고 placementResult
  // 없으면 hydrate 시작 가정) 으로 첫 render 부터 Spinner → useEffect 정상 fetch.
  const [isHydrating, setIsHydrating] = useState(() => !!projectId && !placementResult);

  const handleBackToFloor = () => {
    setShowBackConfirm(false);
    setPlacementResult(null);
    setLocalPlaced([]);
    setWalls([]);
    setSelectedObjectIndices([]);
    setSelectedWallId(null);
    navigate('/project/floor');
  };

  // ── 팔레트 controlled state (Viewer3D 내부 툴바 대체) ──
  const [editMode, setEditMode] = useState<EditMode>('view');
  // 2026-05-07 fix — main_artery 가 walk_mm 이동(5/4) 으로 placementResult 에서 옴.
  // placementResult.main_artery 우선, fallback spaceData.main_artery (옛 위치).
  const [arteryMode, setArteryMode] = useState<ArteryMode>(() => {
    const arteryCoords = (placementResult as any)?.main_artery ?? (spaceData as any)?.main_artery;
    return (arteryCoords?.length ?? 0) >= 2 ? 'arrow' : 'off';
  });
  const [showRefPoints, setShowRefPoints] = useState(true);
  const [showSlots, setShowSlots] = useState(true);
  const [showConceptAreas, setShowConceptAreas] = useState(true);
  // small/large 통합 구역 토글 상태
  const [hiddenAreaKeys, setHiddenAreaKeys] = useState<Set<string>>(new Set());

  const isLargeProject = ((spaceData as any)?.concept_areas?.length ?? 0) > 0;

  const SMALL_ZONE_DEFS = [
    { key: 'entrance_zone', label: '입구', color: '#22c55e' },
    { key: 'mid_zone',      label: '중간', color: '#eab308' },
    { key: 'deep_zone',     label: '심화', color: '#3b82f6' },
  ];

  const conceptAreaDefs = useMemo(() => {
    if (isLargeProject) {
      const seen = new Set<string>();
      return ((spaceData as any)?.concept_areas ?? [])
        .filter((a: any) => { if (seen.has(a.name)) return false; seen.add(a.name); return true; })
        .map((a: any) => ({
          key: a.name,
          label: CONCEPT_AREA_LABEL_KO[a.name] ?? a.name,
          color: CONCEPT_AREA_BORDER_COLORS[a.name] ?? '#94a3b8',
        }));
    }
    // small: zone_map 키 기반 동적 생성
    const zoneMap = (spaceData as any)?.zone_map ?? {};
    return SMALL_ZONE_DEFS.filter(d => zoneMap[d.key] !== undefined);
  }, [spaceData, isLargeProject]);

  // small: hiddenAreaKeys → visibleZoneKeys 변환
  const visibleZoneKeys = useMemo(() => {
    if (isLargeProject) return new Set(['entrance_zone', 'mid_zone', 'deep_zone']);
    const allKeys = SMALL_ZONE_DEFS.map(d => d.key);
    return new Set(allKeys.filter(k => !hiddenAreaKeys.has(k)));
  }, [isLargeProject, hiddenAreaKeys]);

  // large: hiddenAreaKeys → visibleConceptAreaKeys 변환
  const visibleConceptAreaKeys = useMemo(() => {
    if (!isLargeProject || hiddenAreaKeys.size === 0) return undefined;
    const allKeys: string[] = conceptAreaDefs.map((d: { key: string }) => d.key);
    return new Set(allKeys.filter((k: string) => !hiddenAreaKeys.has(k)));
  }, [isLargeProject, hiddenAreaKeys, conceptAreaDefs]);
  // 이격구역 — 전체 타입 항상 표시 (고정값)
  const visibleDeadZoneTypes = new Set(DEAD_ZONE_TYPES.map(t => t.value));

  // GLB export 함수 — Viewer3D 가 onExportReady 로 전달. opts 포함 forward
  const exportGlbRef = useRef<((opts?: { includeZones?: boolean; includeFloorTexture?: boolean; filename?: string }) => void) | null>(null);

  // 프로젝트 이름 + placement_result_id — GLB export/뷰 에 사용.
  //  placementResult 에 merge 하지 않고 ResultPage 로컬 state 로 분리 보관 — 컨텍스트 간섭·무한루프 회피.
  const [projectName, setProjectName] = useState<string | null>(null);
  const [pResultId, setPResultId] = useState<number | null>(null);
  useEffect(() => {
    if (!projectId || !currentUser?.id) return;
    // [LOCAL_TEST_USE_DIRECT] 직통 모드는 Java/DB 미경유 → 프로젝트 이름/PK fetch skip
    if (USE_DIRECT) return;
    let cancelled = false;
    getProject(projectId)
      .then((d) => {
        if (cancelled) return;
        setProjectName(d.name ?? null);
        setPResultId(d.placement_result_id ?? null);
        debugLog(`[ResultPage] project fetched — name='${d.name}' placement_result_id=${d.placement_result_id}`);
      })
      .catch(() => { /* 실패 무시 — 기본값 사용됨 */ });
    return () => { cancelled = true; };
  }, [projectId, currentUser?.id]);

  // ── 리포트 모달 state ──
  const [reportData, setReportData] = useState<AnalysisReportData | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [reportCollapsed, setReportCollapsed] = useState(false);
  const [reportPos, setReportPos] = useState({ x: window.innerWidth - 480, y: 80 });

  // ── 기타 UI state ──
  const [showPalette, setShowPalette] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<number[] | null>(null);
  const reportDragRef = useRef<{ startX: number; startY: number; initX: number; initY: number } | null>(null);

  useEffect(() => {
    if (!projectId || USE_DIRECT) return;
    let cancelled = false;
    setReportLoading(true);
    fetchProjectReport(projectId)
      .then((d) => {
        if (!cancelled) setReportData(d as AnalysisReportData);
      })
      .catch(() => {
        // DB에 report_json 없음 → 현재 데이터로 즉시 생성
        if (!placementResult || cancelled) return;
        const placed = (placementResult as any).objects ?? placementResult.layout_objects ?? [];
        const brandRaw = (brandExtraction as unknown as Record<string, unknown>) ?? {};
        generateReportFromResult({
          placed_objects: placed,
          failed_objects: (placementResult as any).failed_objects ?? [],
          dead_zones: spaceData?.dead_zones ?? [],
          token_usage: (placementResult as any).token_usage ?? [],
          pair_rules: (brandRaw.pair_rules as unknown[]) ?? (brandRaw.placement_rules as unknown[]) ?? [],
          brand_data: brandRaw,
          area_m2: spaceData?.floor?.usable_area_sqm ?? null,
          ceiling_height_mm: (spaceData as any)?.ceiling_height_mm ?? null,
          entrance_count: spaceData ? 1 : 0,
          sprinkler_count: (spaceData as any)?.sprinklers_mm?.length ?? 0,
          brand_category: brandCategory ?? '기타',
          ref_quality_score: (placementResult as any).ref_quality_score ?? null,
        })
          .then((d) => { if (!cancelled) setReportData(d as AnalysisReportData); })
          .catch(() => { /* 생성 실패 — 리포트 없음 */ });
      })
      .finally(() => { if (!cancelled) setReportLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, placementResult]);

  const handleReportDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    reportDragRef.current = { startX: e.clientX, startY: e.clientY, initX: reportPos.x, initY: reportPos.y };
    const onMove = (ev: MouseEvent) => {
      if (!reportDragRef.current) return;
      const dx = ev.clientX - reportDragRef.current.startX;
      const dy = ev.clientY - reportDragRef.current.startY;
      setReportPos({ x: reportDragRef.current.initX + dx, y: reportDragRef.current.initY + dy });
    };
    const onUp = () => {
      reportDragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  // 이름 저장 모달
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);

  // 2026-05-04 신설 - 레퍼런스 반영도 경고 모달 (디자인 참조 로직 트랙 8번, 옵션 나).
  // 표시 방식 - 수동 (사용자 결정). 점수 영역 클릭 시만 표시. 자동 표시 X (무한 모달 방지).
  const [showRefTraceModal, setShowRefTraceModal] = useState(false);
  const refQualityScore = placementResult?.ref_quality_score ?? null;
  const isLowRefScore = refQualityScore !== null && refQualityScore < 0.4;

  const handleSaveName = async () => {
    if (!currentUser || !projectId || !saveName.trim()) return;
    if (USE_DIRECT) {
      toast.info('직통 모드는 DB 미경유 — 이름 저장 불가');
      setShowSaveModal(false);
      return;
    }
    setSaving(true);
    try {
      await renameProject(projectId, saveName.trim());
      toast.success(`"${saveName.trim()}" 이름으로 저장됨`);
      setShowSaveModal(false);
      setSaveName('');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '이름 저장 실패');
    } finally {
      setSaving(false);
    }
  };

  // placementResult 변경 시 localPlaced 초기화 (id 없으면 생성 — 3D 선택에 필수)
  useEffect(() => {
    if (placementResult) {
      setLocalPlaced(placementResult.layout_objects.map((o, i) =>
        o.id ? o : { ...o, id: `${o.object_type}_${i}_${Date.now()}` }
      ));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placementResult]);

  // Ctrl+Z 되돌리기
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        const snap = popHistory();
        if (!snap) return;
        setLocalPlaced(snap.placed);
        setWalls(snap.walls);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [popHistory, setLocalPlaced, setWalls]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedObjectIndices.length > 0) {
        if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return;
        e.preventDefault();
        handleObjectDelete();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedObjectIndices]);

  // ── 재배치 (요구사항 적용 or 재생성) ─────────
  const handleReplace = async (mergedReqs: string[], keepExisting = false) => {
    if (!spaceData) { setError('공간 계산 결과가 필요합니다'); return; }
    setError(''); setStatusIdx(0); setStatusMsg(STATUS_MESSAGES[0]);
    setIsProcessing(true);
    const interval = setInterval(() => {
      setStatusIdx(i => {
        const n = Math.min(i + 1, STATUS_MESSAGES.length - 1);
        setStatusMsg(STATUS_MESSAGES[n]);
        return n;
      });
    }, 4000);

    // [LOCAL_TEST_USE_DIRECT] 직통 모드는 floor_detection_id 미필요 (DB 미경유)
    if (!USE_DIRECT && (!floorDetectionId || !currentUser)) {
      clearInterval(interval);
      setError('floor_detection_id 없음 — 공간 계산 결과가 필요합니다');
      setIsProcessing(false);
      return;
    }
    try {
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] Python 직통 재배치
      // ════════════════════════════════════════════════════════════════
      if (USE_DIRECT) {
        const result = await placeObjectsDirect({
          space_data: spaceData as unknown as Record<string, unknown>,
          density_ratio: densityRatio,
          brand_dict: (brandExtraction as unknown as Record<string, unknown>) ?? {},
          brand_category: brandCategory,
          user_requirements: mergedReqs.join('. ') || undefined,
          locked_objects: keepExisting && localPlaced.length > 0
            ? (localPlaced as unknown as Record<string, unknown>[])
            : undefined,
          venue_type: venueType,
        });
        const rawObjs = ((result.objects ?? (result as any).layout_objects ?? (result as any).placed_objects ?? []) as Array<Record<string, unknown>>);
        const layoutObjects = rawObjs.map((o, i) => ({
          ...o,
          id: (o.id as string | undefined) ?? `direct_${i}`,
          label: (o.label as string | undefined) ?? String(o.object_type ?? 'object'),
        }));
        clearInterval(interval);
        const reqFailures: Array<{ user_message?: string; object_type?: string; technical_reason?: string }> = (result as any).requirement_failures ?? [];
        const failedObjs: Array<{ object_type?: string; reason?: string }> = (result as any).failed_objects ?? [];
        setPlacementResult({
          layout_objects: layoutObjects as never,
          validation: { status: 'ok', violations: [] },
          sub_path: (result as any).sub_path ?? [],
          // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 place 응답에 박힘 (이전엔 space 응답).
          main_artery: (result as any).main_artery ?? null,
          // 2026-05-04 신설 - ref_quality_score (모달 트리거용). 0.0 ~ 1.0.
          ref_quality_score: (result as any).ref_quality_score ?? null,
        } as never);
        setWalls([]); setSelectedObjectIndices([]); setSelectedWallId(null);
        if ((result as any).intent_parse_error) {
          console.error('[LandUP] 요구사항 파싱 실패 — 기존 배치 유지:', (result as any).intent_parse_error);
        }
        if (reqFailures.length > 0) {
          console.warn('[LandUP] 요구사항 배치 실패:', reqFailures);
          reqFailures.forEach(f => console.warn(`  · ${f.object_type}: ${f.user_message} (${f.technical_reason})`));
        }
        if (failedObjs.length > 0) {
          console.warn('[LandUP] 미배치 오브젝트:', failedObjs);
          failedObjs.forEach(f => console.warn(`  · ${f.object_type}: ${f.reason}`));
        }
        toast.success('재배치 완료 (직통)');
        return;
      }
      // ════════════════════════════════════════════════════════════════
      // [LOCAL_TEST_USE_DIRECT] 끝 — 아래는 기존 B안 (Java 경유) 로직
      // ════════════════════════════════════════════════════════════════
      if (!currentUser || !floorDetectionId) throw new Error('currentUser/floor_detection_id 누락');
      const enq = await placeObjects({
        floor_detection_id: floorDetectionId,
        density_ratio: densityRatio,
        user_requirements: mergedReqs.join('. ') || undefined,
        locked_objects: keepExisting && localPlaced.length > 0 ? localPlaced as unknown as Record<string, unknown>[] : undefined,
        page_number: (spaceData as any)?.page_number ?? undefined,
        brand_manual_id: brandManualId ?? undefined,
        project_id: projectId ?? undefined,
      });
      setActiveJob({ id: enq.job_id, type: 'place', startedAt: Date.now() });
      // 동적 polling (초반 5s, 중반 3s, 완료 임박 1s). Job Entity 재설계 후 progress flat 구조.
      let delay = 5000;
      while (true) {
        await new Promise(r => setTimeout(r, delay));
        const job = await getJob(enq.job_id);
        if (job.progress_message) setStatusMsg(job.progress_message);
        if (job.status === 'done') break;
        if (job.status === 'error') throw new Error(job.error_message || '작업 실패');
        delay = computePollInterval(job.progress_pct ?? undefined);
      }
      // project_id 는 state 그대로 사용 (Job 응답엔 파생 ID 없음)
      const finalProjectId = projectId;
      if (!finalProjectId) throw new Error('project_id 누락');
      const detail = await getProject(finalProjectId);
      clearInterval(interval);
      setPlacementResult({
        layout_objects: detail.layout_objects ?? [],
        validation: { status: 'ok', violations: [] },
        sub_path: (detail as any).sub_path ?? [],
        // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 place 응답에 박힘 (이전엔 space 응답).
        main_artery: (detail as any).main_artery ?? null,
        // 2026-05-04 신설 - ref_quality_score (모달 트리거용). 0.0 ~ 1.0.
        ref_quality_score: (detail as any).ref_quality_score ?? null,
      } as never);
      setWalls([]); setSelectedObjectIndices([]); setSelectedWallId(null);
      toast.success('재배치 완료');
    } catch (e: unknown) {
      clearInterval(interval);
      const res = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      const axiosDetail = res?.data?.detail;
      const msg = axiosDetail || (e instanceof Error ? e.message : '배치 생성 실패');
      if (res?.status === 429) {
        setLimitModal(msg);
      } else {
        setError(msg);
        toast.error(msg);
      }
    } finally {
      setIsProcessing(false); setStatusMsg('');
      setActiveJob(null);
    }
  };

  const handleApplyReq = () => {
    const newReq = reqText.trim();
    const newApplied = newReq ? [...appliedReqs, newReq] : appliedReqs;
    if (newReq) setAppliedReqs(newApplied);
    setReqText('');
    handleReplace(newApplied, true);
  };

  // roomPolygon — FloorView2D가 사용. (구 뷰어 드롭 기능은 2026-04-20 제거됨)
  const roomPolygon: [number, number][] = (spaceData?.floor?.polygon_mm ?? []).map((p: number[]) => [p[0], p[1]]);

  // ── 오브젝트 조작 ─────────────────────────────────────
  const handleObjectRotate = (index: number, deltaDeg: number) => {
    setLocalPlaced(prev => {
      pushHistory(prev, walls);
      const indices = selectedObjectIndicesRef.current.includes(index) ? selectedObjectIndicesRef.current : [index];
      return prev.map((p, i) => indices.includes(i) ? { ...p, rotation_deg: ((p.rotation_deg ?? 0) + deltaDeg + 360) % 360 } : p);
    });
  };
  const handleObjectClick = (idx: number | null, shiftKey = false) => {
    debugLog({ event: 'handle_object_click', idx, shiftKey, prev: selectedObjectIndices });
    if (idx === null) { debugLog({ event: 'deselect_all' }); setSelectedObjectIndices([]); setSelectedWallId(null); return; }
    setSelectedWallId(null);
    setSelectedObjectIndices(prev => {
      const next = shiftKey
        ? (prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx])
        : (prev.length === 1 && prev[0] === idx ? [] : [idx]);
      debugLog({ event: 'selection_update', mode: shiftKey ? 'shift_toggle' : 'single', next });
      return next;
    });
  };
  const handleWallRotate = (id: string) =>
    setWalls(prev => { pushHistory(localPlaced, prev); return prev.map(w => w.id === id ? { ...w, rotation: (w.rotation + 90) % 360 } : w); });
  const handleWallDelete = (id: string) =>
    setWalls(prev => { pushHistory(localPlaced, prev); if (selectedWallId === id) setSelectedWallId(null); return prev.filter(w => w.id !== id); });
  const handleAddWall = (length: number) => {
    const poly = spaceData?.floor?.polygon_mm ?? [];
    const cx = poly.length ? poly.reduce((s: number, p: number[]) => s + p[0], 0) / poly.length : 0;
    const cz = poly.length ? poly.reduce((s: number, p: number[]) => s + p[1], 0) / poly.length : 0;
    const count = walls.length;
    const id = newWallId();
    setWalls(prev => {
      pushHistory(localPlaced, prev);
      return [...prev, { id, x: cx + (count % 3 - 1) * 700, z: cz + Math.floor(count / 3) * 700, rotation: 0, length, height: 2500, thickness: 100 }];
    });
    setSelectedWallId(id);
    toast.success(`가벽 ${length / 1000}m 추가됨 — 도면 중앙에 생성`);
  };

  // ── 오브젝트 복사 (팔레트 버튼) ────────────────────────
  const handleObjectCopy = () => {
    if (selectedObjectIndices.length === 0) return;
    pushHistory(localPlaced, walls);
    const toCopy = selectedObjectIndices.map(i => localPlaced[i]).filter(Boolean);
    const copies: LayoutObject[] = toCopy.map(src => ({
      ...src,
      id: `copy_${src.object_type}_${Date.now()}_${Math.round(Math.random() * 1e6)}`,
      center_x_mm: src.center_x_mm + 500,
      center_y_mm: src.center_y_mm + 500,
      placed_because: `복사됨 (원본: ${src.anchor_key ?? 'unknown'})`,
    }));
    const newStartIndex = localPlaced.length;
    setLocalPlaced(prev => [...prev, ...copies]);
    setSelectedObjectIndices(copies.map((_, ci) => newStartIndex + ci));
    const names = toCopy.map(src => OBJECT_NAMES[src.object_type] || src.object_type).join(', ');
    toast.success(`[${names}] 복사됨 — 오른쪽 아래에 생성`);
  };

  const doDeleteObjects = (indices: number[]) => {
    pushHistory(localPlaced, walls);
    const names = [...new Set(indices.map(i => OBJECT_NAMES[localPlaced[i]?.object_type] || localPlaced[i]?.object_type || '오브젝트'))].join(', ');
    setLocalPlaced(prev => prev.filter((_, i) => !indices.includes(i)));
    setSelectedObjectIndices([]);
    toast.success(`[${names}] 삭제됨`);
  };

  const handleObjectDelete = () => {
    if (selectedObjectIndices.length === 0) return;
    const hasAi = selectedObjectIndices.some(i => {
      const obj = localPlaced[i];
      return obj && obj.placed_because !== '팔레트에서 추가' && !obj.placed_because?.startsWith('복사됨');
    });
    if (hasAi) {
      setDeleteConfirm([...selectedObjectIndices]);
    } else {
      doDeleteObjects([...selectedObjectIndices]);
    }
  };

  const handleExportGlb = (includeZones: boolean, filename: string, includeFloorTexture: boolean) => {
    if (!exportGlbRef.current) { toast.error('GLB 준비 중'); return; }
    exportGlbRef.current({ includeZones, filename, includeFloorTexture });
  };

  // ── DB object_palette 카탈로그 (팔레트 "+오브젝트" 팝업용) ────
  const [objectCatalog, setObjectCatalog] = useState<ObjectPaletteItem[] | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError(null);
    getObjectPalette()
      .then(items => {
        if (cancelled) return;
        setObjectCatalog(items);
      })
      .catch(e => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : '카탈로그 로드 실패';
        console.warn('[ResultPage] catalog load failed:', msg);
        setCatalogError(msg);
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // ── 팔레트에서 오브젝트 추가 — 뷰어 중앙(폴리곤 center)에 std 치수로 생성 ──
  const handleAddObject = (objectType: string, item?: ObjectPaletteItem) => {
    const poly = spaceData?.floor?.polygon_mm ?? [];
    if (poly.length < 3) { toast.error('도면 중앙 계산 불가 — 폴리곤 없음'); return; }
    const xs = poly.map((p: number[]) => p[0]);
    const ys = poly.map((p: number[]) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    // DB catalog item 있으면 그 규격 우선, 없으면 로컬 OBJECT_DEFAULTS fallback 불가 (이미 삭제됨) → 기본값
    const w = item?.widthStdMm ?? 1000;
    const d = item?.depthStdMm ?? 600;
    const h = item?.heightStdMm ?? 1200;
    const name = item?.nameKo ?? OBJECT_NAMES[objectType] ?? objectType;
    const newObj: LayoutObject = {
      id: `added_${objectType}_${Date.now()}_${Math.round(Math.random() * 1e6)}`,
      object_type: objectType,
      label: name,
      center_x_mm: cx,
      center_y_mm: cy,
      width_mm: w,
      depth_mm: d,
      height_mm: h,
      rotation_deg: 0,
      placed_because: '팔레트에서 추가',
    };
    pushHistory(localPlaced, walls);
    setLocalPlaced(prev => [...prev, newObj]);
    toast.success(`[${name}] 추가됨 — 도면 중앙에 생성`);
  };

  // ── 면적 기반 소형·중형 판정 (팔레트 ref_point/slot 분기용) ──
  const areaMm2 = useMemo(
    () => calcAreaMm2FromMm(spaceData?.floor?.polygon_mm ?? []),
    [spaceData]
  );
  const smallScale = isSmallScale(areaMm2);

  // ── 뷰어 변환 데이터 ───────────────────────────────────
  const viewerPlaced: TPO[] = localPlaced.map(toLO);
  const viewerDetected: TDO[] = [];
  const failedCount = placementResult ? (placementResult as any).failed_objects?.length ?? 0 : 0;

  const handleReset = () => { reset(); navigate('/project/new'); };

  // ── 2026-05-07 — /project/result 새로고침 / deep-link 진입 hydrate ──
  // URL 직접 진입 (새로고침, 북마크) 시 ProjectResolver 를 안 거치므로
  // placementResult state 가 비어있음. projectId 는 sessionStorage 에서 복원되니
  // 그것 기반으로 detail fetch + ProjectContext 복원.
  useEffect(() => {
    if (placementResult) return;       // 정상 진입 — 이미 set 됨
    if (!projectId) return;             // sessionStorage 비었음 — 아래 redirect
    let cancelled = false;
    setIsHydrating(true);
    (async () => {
      try {
        const detail = await getProject(projectId);
        if (cancelled) return;
        setProjectId(detail.id ?? projectId);
        setResumingFilename(detail.name ?? `프로젝트 #${projectId}`);
        if (detail.floor_archive_id) setFloorArchiveId(detail.floor_archive_id);
        if (detail.brand_manual_id) setBrandManualId(detail.brand_manual_id);
        if (detail.floor_detection_id) setFloorDetectionId(detail.floor_detection_id);
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
            main_artery: (detail as any).main_artery ?? null,
            ref_quality_score: (detail as any).ref_quality_score ?? null,
          } as never);
        }
      } catch {
        // fetch 실패 (404 등) — placementResult null 채로 두면 아래 분기에서 redirect
      } finally {
        if (!cancelled) setIsHydrating(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // 진입 조건: placementResult 없으면 hydrate 또는 redirect
  if (!placementResult) {
    if (isHydrating) {
      return (
        <div className="flex flex-1 items-center justify-center bg-[#070d1a]">
          <div className="flex flex-col items-center gap-3">
            <div className="w-10 h-10 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
            <p className="text-sm text-text-muted">결과 불러오는 중...</p>
          </div>
        </div>
      );
    }
    if (!projectId) return <Navigate to="/project" replace />;
    return <Navigate to="/project/new" replace />;
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* 서브툴바 — 좌측: 저장/처음부터/GLB, 우측: 미배치 배지만 (성공 배지 제거) */}
      <div className="flex items-center justify-between gap-1.5 px-3 lg:px-6 py-2 border-b border-border shrink-0 bg-black/20 flex-wrap">
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setSaveName(''); setShowSaveModal(true); }}
            disabled={!projectId}
            className="text-xs text-primary hover:text-white border border-primary/40 hover:border-primary/70 bg-primary/5 hover:bg-primary/10 px-3 py-1.5 rounded-lg transition-all font-bold disabled:opacity-40 disabled:cursor-not-allowed"
            title={projectId ? '이 프로젝트에 이름 지정' : '저장할 프로젝트 없음'}
          >
            저장하기
          </button>
          <GlbExportButton
            onExport={handleExportGlb}
            defaultFilename={projectName}
            buttonClassName="text-xs text-white bg-slate-800 hover:bg-slate-700 border border-slate-700/60 px-3 py-1.5 rounded-lg transition-all font-bold flex items-center gap-1"
            buttonContent={<><Download size={11} /> .glb</>}
            buttonTitle="GLB 파일로 내보내기"
          />
          <button onClick={handleReset}
            className="text-xs text-text-muted hover:text-white border border-border hover:border-white/30 px-3 py-1.5 rounded-lg transition-all">
            처음부터
          </button>
          {(reportData || reportLoading) && (
            <button
              onClick={() => setShowReport(v => !v)}
              className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-all flex items-center gap-1.5 ${showReport ? 'bg-primary/20 border-primary/60 text-primary' : 'border-border text-text-muted hover:text-white hover:border-white/30'}`}
            >
              <FileText size={11} />
              결과 리포트
              {reportLoading && <RefreshCw size={10} className="animate-spin" />}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {failedCount > 0 && (
            <span className="bg-red-500/10 text-red-400 px-3 py-1 rounded-full text-xs font-bold border border-red-500/20">
              미배치 {failedCount}
            </span>
          )}
        </div>
      </div>

      {/* 저장 모달 */}
      {showSaveModal && (
        <div
          className="fixed inset-0 z-[900] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => !saving && setShowSaveModal(false)}
        >
          <div
            className="bg-[#0d1526] border border-border rounded-2xl p-5 w-full max-w-sm shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold text-text-main mb-1">프로젝트 이름 저장</h3>
            <p className="text-[11px] text-text-muted mb-4">내이력에 표시될 이름을 입력해줘</p>
            <input
              autoFocus
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && saveName.trim() && !saving) void handleSaveName();
                if (e.key === 'Escape' && !saving) setShowSaveModal(false);
              }}
              placeholder="예: 강남점 v1"
              maxLength={50}
              className="w-full bg-black/40 border border-border rounded-lg px-3 py-2 text-sm text-text-main placeholder-text-muted focus:outline-none focus:border-primary/60 transition-colors mb-4"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowSaveModal(false)}
                disabled={saving}
                className="text-xs text-text-muted hover:text-white px-3 py-1.5 rounded-lg border border-border hover:border-white/30 transition-all disabled:opacity-40"
              >
                취소
              </button>
              <button
                onClick={() => void handleSaveName()}
                disabled={saving || !saveName.trim()}
                className="text-xs text-white bg-primary hover:bg-primary/90 font-bold px-4 py-1.5 rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                {saving && <RefreshCw size={11} className="animate-spin" />}
                확인
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ════ 플로팅 팔레트 (포토샵 스타일 세로 3열) ════ */}
      {showPalette && (
        <ResultPalette
          onAddWall={handleAddWall}
          onCopyObject={handleObjectCopy}
          onDeleteObject={handleObjectDelete}
          onAddObject={handleAddObject}
          objectCatalog={objectCatalog}
          objectCatalogLoading={catalogLoading}
          objectCatalogError={catalogError}
          canCopy={selectedObjectIndices.length > 0}
          canDelete={selectedObjectIndices.length > 0}
          onClose={() => setShowPalette(false)}
        />
      )}

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* ════ LEFT PANEL ════ */}
        <aside className="w-64 xl:w-80 shrink-0 flex flex-col border-r border-border overflow-y-auto">
          {/* 2026-05-01 — 글로벌 뒤로가기 (단계 무관). 동일 프로젝트 내 재구조화용 */}
          <div className="px-4 py-3 border-b border-border">
            <button
              onClick={() => setShowBackConfirm(true)}
              disabled={isProcessing}
              className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-main border border-border hover:border-white/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40"
            >
              <ArrowLeft size={12} /> 뒤로 (공간 재계산)
            </button>
          </div>

          {error && (
            <div className="mx-4 mt-3 p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
              <AlertCircle size={13} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}

          {/* 요구사항 / 재생성 */}
          <div className="px-4 py-3 border-b border-border">
            <div className="text-xs text-text-muted mb-2 flex items-center gap-1">
              <Send size={11} className="text-accent" /> 배치 요구사항
            </div>
            {appliedReqs.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {appliedReqs.map((req, idx) => (
                  <span key={idx}
                    className="flex items-center gap-1 bg-accent/10 border border-accent/30 text-accent text-[10px] px-2 py-0.5 rounded-full">
                    <span className="truncate max-w-[150px]" title={req}>{req}</span>
                    <button onClick={() => { const next = appliedReqs.filter((_, i) => i !== idx); setAppliedReqs(next); }}
                      className="shrink-0 text-accent/60 hover:text-accent ml-0.5">×</button>
                  </span>
                ))}
              </div>
            )}
            <textarea
              className="w-full bg-black/20 border border-border rounded-xl p-2.5 text-xs text-text-main placeholder-text-muted resize-none focus:outline-none focus:border-accent/60 transition-colors"
              rows={3} value={reqText} onChange={e => setReqText(e.target.value)}
              placeholder={"예) 진열대 2개 제거해줘 / 계산대 입구쪽으로 옮겨줘 / 3단 선반 1개 추가해줘\n오브젝트 종류·수량·위치를 명확하게 입력하세요. 추상적인 표현(\"넓게\", \"어울리게\" 등)은 적용되지 않을 수 있습니다."}
            />
            <div className="flex gap-2 mt-2">
              <button
                onClick={() => setShowBackConfirm(true)}
                disabled={isProcessing}
                className="px-3 py-2 rounded-xl border border-border text-text-muted text-xs hover:bg-white/5 hover:text-text-main disabled:opacity-40 transition-colors flex items-center gap-1"
              >
                <ArrowLeft size={12} /> 뒤로
              </button>
              <button onClick={handleApplyReq}
                disabled={isProcessing || (!reqText.trim() && appliedReqs.length === 0)}
                className="flex-1 flex items-center justify-center gap-1 py-2 rounded-xl bg-accent/20 border border-accent/40 text-accent text-xs font-bold hover:bg-accent/30 disabled:opacity-40 transition-colors">
                <Send size={12} />{isProcessing ? '적용 중...' : '요구사항 적용'}
              </button>
              <button onClick={() => handleReplace(appliedReqs)} disabled={isProcessing}
                className="px-3 py-2 rounded-xl border border-border text-text-muted text-xs hover:bg-white/10 hover:text-white disabled:opacity-40 transition-colors">
                <RefreshCw size={12} className={isProcessing ? 'animate-spin' : ''} />
              </button>
            </div>
          </div>

          {/* 도면 정보 */}
          {spaceData?.floor?.polygon_mm && areaMm2 > 0 && (
            <div className="px-4 py-3 border-b border-border">
              <div className="text-xs text-text-muted mb-2">📐 도면 정보</div>
              <div className="p-2.5 bg-black/20 border border-border rounded-lg flex items-center justify-between">
                <span className="text-xs text-text-main font-semibold">{formatArea(areaMm2)}</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold ${smallScale ? 'bg-accent/20 text-accent' : 'bg-primary/20 text-primary'}`}>
                  {smallScale ? '소형·중형' : '대형'}
                </span>
              </div>
            </div>
          )}

          {/* 2026-05-04 신설 — 레퍼런스 반영도 (디자인 참조 로직 트랙 8번 모달 트리거).
              수동 (사용자 결정) — 점수 영역 클릭 시만 모달 열림. 자동 X.
              점수 < 0.4 (isLowRefScore) 시 빨강 강조 — 클릭 유도. */}
          {refQualityScore !== null && (
            <div className="px-4 py-3 border-b border-border">
              <div className="text-xs text-text-muted mb-2">🎨 레퍼런스 반영도</div>
              <button
                onClick={() => setShowRefTraceModal(true)}
                className={`w-full p-2.5 rounded-lg flex items-center justify-between transition-colors border ${
                  isLowRefScore
                    ? 'bg-red-500/10 border-red-500/40 hover:bg-red-500/20'
                    : 'bg-black/20 border-border hover:bg-white/5'
                }`}
                title="클릭하여 상세 보기"
              >
                <span className={`text-xs font-semibold ${isLowRefScore ? 'text-red-300' : 'text-text-main'}`}>
                  {(refQualityScore * 100).toFixed(0)}점 / 100점
                </span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold ${
                  isLowRefScore
                    ? 'bg-red-500/20 text-red-300'
                    : refQualityScore >= 0.7
                      ? 'bg-green-500/20 text-green-300'
                      : 'bg-yellow-500/20 text-yellow-300'
                }`}>
                  {isLowRefScore ? '낮음' : refQualityScore >= 0.7 ? '우수' : '보통'}
                </span>
              </button>
            </div>
          )}

          {/* 가벽 목록 — 추가 버튼은 팔레트로 이동됨 */}
          {walls.length > 0 && (
            <div className="px-4 py-3 border-b border-border">
              <h4 className="text-xs font-bold mb-2 text-text-muted">설치된 가벽</h4>
              <div className="space-y-1.5">
                {walls.map(wall => {
                  const isSel = selectedWallId === wall.id;
                  return (
                    <div key={wall.id}
                      onClick={() => { setSelectedWallId(p => p === wall.id ? null : wall.id); setSelectedObjectIndices([]); }}
                      className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg border cursor-pointer text-xs transition-all ${isSel ? 'border-yellow-400/60 bg-yellow-400/10' : 'border-border bg-black/20 hover:bg-white/5'}`}>
                      <span className="font-bold">{(wall.length / 1000).toFixed(0)}m벽 · {wall.rotation}°</span>
                      <div className="flex gap-1">
                        <button onClick={e => { e.stopPropagation(); handleWallRotate(wall.id); }}
                          className="p-1 rounded hover:bg-white/10 text-text-muted hover:text-white"><RotateCcw size={11} /></button>
                        <button onClick={e => { e.stopPropagation(); handleWallDelete(wall.id); }}
                          className="p-1 rounded hover:bg-red-500/20 text-text-muted hover:text-red-400"><Trash2 size={11} /></button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 직접 추가한 항목 (복사 / 팔레트 추가) */}
          {(() => {
            const userItems = localPlaced
              .map((p, i) => ({ p, i }))
              .filter(({ p }) => p.placed_because === '팔레트에서 추가' || p.placed_because?.startsWith('복사됨'));
            if (userItems.length === 0) return null;
            return (
              <div className="px-4 py-3 border-b border-border">
                <h4 className="text-xs font-bold mb-2 flex items-center gap-1.5">
                  <Package size={13} className="text-emerald-400" /> 직접 추가한 항목
                  <span className="ml-auto text-[10px] text-text-muted">클릭·드래그</span>
                </h4>
                <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                  {userItems.map(({ p, i }) => {
                    const isSel = selectedObjectIndices.includes(i);
                    const color = OBJECT_COLORS[p.object_type] ?? '#ec4899';
                    const name = OBJECT_NAMES[p.object_type] ?? p.object_type;
                    const badge = p.placed_because?.startsWith('복사됨') ? '복사' : '추가';
                    return (
                      <div key={p.id || i} onClick={e => handleObjectClick(i, e.shiftKey)}
                        className={`w-full text-left px-2.5 py-2 rounded-lg border cursor-pointer transition-all ${isSel ? 'border-emerald-400/60 bg-emerald-400/10' : 'border-border bg-black/20 hover:bg-white/5'}`}>
                        <div className="flex items-center gap-1.5">
                          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: color }} />
                          <span className="text-xs font-bold text-text-main">{name}</span>
                          <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-400/20 text-emerald-400 font-bold">{badge}</span>
                          <button
                            onClick={e => { e.stopPropagation(); doDeleteObjects([i]); }}
                            className="ml-auto p-1 rounded hover:bg-red-500/20 text-text-muted hover:text-red-400 transition-colors"
                            title="삭제"
                          ><Trash2 size={11} /></button>
                        </div>
                        {isSel && (
                          <div className="flex items-center gap-1.5 mt-1.5 pl-4">
                            <span className="text-[10px] text-text-muted">{p.rotation_deg ?? 0}°</span>
                            <button onClick={e => { e.stopPropagation(); handleObjectRotate(i, -45); }}
                              className="p-1 rounded hover:bg-white/10 text-text-muted hover:text-white" title="반시계 45°"><RotateCcw size={11} /></button>
                            <button onClick={e => { e.stopPropagation(); handleObjectRotate(i, 45); }}
                              className="p-1 rounded hover:bg-white/10 text-text-muted hover:text-white" title="시계 45°"><RotateCw size={11} /></button>
                            <button onClick={e => { e.stopPropagation(); handleObjectRotate(i, 90); }}
                              className="px-1.5 py-0.5 rounded text-[10px] hover:bg-white/10 text-text-muted hover:text-white border border-border" title="90°">90°</button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}

          {/* 배치된 오브젝트 (AI 배치) */}
          <div className="px-4 py-3 border-b border-border">
            <h4 className="text-xs font-bold mb-2 flex items-center gap-1.5">
              <Package size={13} className="text-primary" /> AI 배치 오브젝트
              <span className="ml-auto text-[10px] text-text-muted">클릭·드래그</span>
            </h4>
            <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
              {localPlaced
                .map((p, i) => ({ p, i }))
                .filter(({ p }) => p.placed_because !== '팔레트에서 추가' && !p.placed_because?.startsWith('복사됨'))
                .map(({ p, i }) => {
                  const isSel = selectedObjectIndices.includes(i);
                  const color = OBJECT_COLORS[p.object_type] ?? '#ec4899';
                  const name = OBJECT_NAMES[p.object_type] ?? p.object_type;
                  return (
                    <div key={p.id || i} onClick={e => handleObjectClick(i, e.shiftKey)}
                      className={`w-full text-left px-2.5 py-2 rounded-lg border cursor-pointer transition-all ${isSel ? 'border-yellow-400/60 bg-yellow-400/10' : 'border-border bg-black/20 hover:bg-white/5'}`}>
                      <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: color }} />
                        <span className="text-xs font-bold text-text-main">{name}</span>
                        {isSel && <span className="text-yellow-400 text-[10px]">
                          {selectedObjectIndices.length > 1 ? `+${selectedObjectIndices.length}` : '선택됨'}
                        </span>}
                        <button
                          onClick={e => { e.stopPropagation(); setDeleteConfirm([i]); }}
                          className="ml-auto p-1 rounded hover:bg-red-500/20 text-text-muted hover:text-red-400 transition-colors"
                          title="삭제"
                        ><Trash2 size={11} /></button>
                      </div>
                      <div className="text-[10px] text-text-muted mt-0.5 pl-4">
                        {p.anchor_key ?? ''} · {p.width_mm}×{p.depth_mm} (H{p.height_mm})
                      </div>
                      {isSel && (
                        <>
                          <div className="flex items-center gap-1.5 mt-1.5 pl-4">
                            <span className="text-[10px] text-text-muted">{p.rotation_deg ?? 0}°</span>
                            <button onClick={e => { e.stopPropagation(); handleObjectRotate(i, -45); }}
                              className="p-1 rounded hover:bg-white/10 text-text-muted hover:text-white" title="반시계 45°"><RotateCcw size={11} /></button>
                            <button onClick={e => { e.stopPropagation(); handleObjectRotate(i, 45); }}
                              className="p-1 rounded hover:bg-white/10 text-text-muted hover:text-white" title="시계 45°"><RotateCw size={11} /></button>
                            <button onClick={e => { e.stopPropagation(); handleObjectRotate(i, 90); }}
                              className="px-1.5 py-0.5 rounded text-[10px] hover:bg-white/10 text-text-muted hover:text-white border border-border" title="90°">90°</button>
                          </div>
                          {p.placed_because && (
                            <div className="text-[10px] text-text-muted mt-1 pl-4 leading-relaxed border-t border-white/5 pt-1">
                              {p.placed_because}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  );
              })}
              {localPlaced.filter(p => p.placed_because !== '팔레트에서 추가' && !p.placed_because?.startsWith('복사됨')).length === 0 && (
                <p className="text-xs text-text-muted italic">배치된 오브젝트 없음</p>
              )}
            </div>
          </div>

          {/* 미배치 오브젝트 드래그 기능은 2026-04-20 제거됨 (Shin 결정 — 의미 없는 기능) */}
        </aside>

        {/* ════ RIGHT PANEL ════ */}
        <main className="flex-1 min-w-0 flex overflow-hidden">
          <div className="flex-1 min-w-0 flex flex-col bg-[#070d1a] relative overflow-hidden">
            <div className="absolute bottom-3 left-3 z-10 text-[9px] text-white/30 select-none">
              Ctrl+Z 되돌리기
            </div>
            {/* 3D/2D 토글 */}
            <div className="absolute top-14 right-3 z-10 flex gap-0.5 bg-slate-100 rounded-lg p-0.5 border border-slate-200">
              <button onClick={() => setMode('3d')}
                className={`px-2.5 py-1 text-[11px] rounded-md font-bold transition-all ${mode === '3d' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}>
                3D
              </button>
              <button onClick={() => setMode('2d')}
                className={`px-2.5 py-1 text-[11px] rounded-md font-bold transition-all ${mode === '2d' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}>
                2D
              </button>
              {/* GLB 뷰 모드 보류 — 재활성 시 아래 버튼 주석 해제
              <button onClick={() => setMode('glb' as any)}
                title="Python 파이프라인 GLB 프리뷰 (편집 불가)"
                className={`px-2.5 py-1 text-[11px] rounded-md font-bold transition-all text-slate-400 hover:text-slate-600`}>
                GLB
              </button>
              */}
            </div>

            {/* 로딩 오버레이 */}
            {isProcessing && (
              <div className="absolute inset-0 z-20 bg-black/60 flex flex-col items-center justify-center gap-4">
                <div className="w-14 h-14 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
                <p className="text-sm font-bold text-text-main">{statusMsg || '배치 생성 중...'}</p>
                <div className="flex gap-1">
                  {STATUS_MESSAGES.map((_, i) => (
                    <div key={i} className={`w-1.5 h-1.5 rounded-full ${i <= statusIdx ? 'bg-primary' : 'bg-white/20'}`} />
                  ))}
                </div>
              </div>
            )}

            {/* GLB 뷰 모드 분기 보류 — 재활성 시 아래 블록 주석 해제
            {mode === 'glb' ? (
              pResultId ? (
                <PythonGlbViewer3D placementResultId={pResultId} />
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center gap-2 text-slate-400 text-sm">
                  <div>GLB 생성 결과 없음</div>
                  <div className="text-xs text-slate-500">
                    배치를 한 번 실행한 뒤 다시 시도해주세요.
                  </div>
                </div>
              )
            ) : mode === '3d' ? (
            */}
            {mode === '3d' ? (
              spaceData ? (
                <ShinViewer3D
                  spaceData={spaceData}
                  layoutObjects={localPlaced}
                  walls={walls}
                  refPointStatus={(placementResult as any)?.ref_point_status ?? []}
                  subPath={((placementResult as any)?.sub_path?.length ?? 0) >= 2 ? [(placementResult as any).sub_path as number[][]] : []}
                  // 2026-05-04: main_artery 가 walk_mm 노드 이동으로 placementResult 에서 받음 (이전엔 spaceData).
                  mainArtery={(placementResult as any)?.main_artery ?? null}
                  onUpdateObject={(id, changes) => {
                    pushHistory(localPlaced, walls);
                    setLocalPlaced(prev => prev.map(o => o.id === id ? { ...o, ...changes } : o));
                  }}
                  onUpdateWall={(id, changes) => {
                    pushHistory(localPlaced, walls);
                    setWalls(prev => prev.map(w => w.id === id ? { ...w, ...changes } : w));
                  }}
                  onObjectSelect={(idx) => handleObjectClick(idx)}
                  // 팔레트 controlled props
                  editMode={editMode}
                  onEditModeChange={setEditMode}
                  visibleDeadZoneTypes={visibleDeadZoneTypes}
                  arteryMode={arteryMode}
                  onArteryModeChange={setArteryMode}
                  showRefPoints={showRefPoints}
                  showSlots={showSlots}
                  visibleZoneKeys={visibleZoneKeys}
                  showZoneFloors={(visibleZoneKeys.size ?? 0) > 0}
                  showConceptAreas={showConceptAreas}
                  visibleConceptAreaKeys={visibleConceptAreaKeys}
                  onToggleConceptAreas={() => setShowConceptAreas(v => !v)}
                  conceptAreaDefs={conceptAreaDefs}
                  hiddenConceptAreaKeys={hiddenAreaKeys}
                  onToggleConceptArea={(key: string) => setHiddenAreaKeys((prev: Set<string>) => {
                    const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next;
                  })}
                  onToggleAllConceptAreas={() => setHiddenAreaKeys((prev: Set<string>) =>
                    prev.size < conceptAreaDefs.length ? new Set(conceptAreaDefs.map((d: { key: string }) => d.key)) : new Set()
                  )}
                  onExportReady={(fn) => { exportGlbRef.current = fn; }}
                  onTogglePalette={() => setShowPalette(v => !v)}
                  paletteActive={showPalette}
                  projectName={projectName}
                  onDownloadPythonGlb={pResultId ? async () => {
                    const rid = pResultId;
                    debugLog(`[glb-client] ResultPage → downloadPythonGlb(${rid}) 호출`);
                    const r = await downloadPythonGlb(rid);
                    debugLog({ event: 'glb-client_result', ok: r.ok, sizeBytes: r.sizeBytes, status: r.status, error: r.error });
                    if (!r.ok) {
                      toast.error(`Python GLB 다운로드 실패: ${r.error ?? 'unknown'}`);
                    } else {
                      toast.success(`Python GLB 다운로드 완료 (${r.sizeBytes ?? '?'} bytes)`);
                    }
                  } : undefined}
                />
              ) : null
            ) : (
              <div className="flex-1 min-h-0 relative">
                <div className="absolute inset-0">
                  <FloorView2D
                    roomPolygon={roomPolygon}
                    placedObjects={viewerPlaced}
                    detectedObjects={viewerDetected}
                    walls={walls}
                    selectedIndices={selectedObjectIndices}
                    onObjectClick={handleObjectClick}
                    onObjectRotate={handleObjectRotate}
                  />
                </div>
              </div>
            )}
          </div>
        </main>
      </div>

      {/* ── 한도 초과 모달 ── */}
      {limitModal && (
        <LimitExceededModal
          message={limitModal}
          membership={currentUser?.membership ?? 'basic'}
          onClose={() => setLimitModal(null)}
        />
      )}

      {/* ── 레퍼런스 반영도 경고 모달 (2026-05-04 신설, 디자인 참조 로직 트랙 8번) ── */}
      {showRefTraceModal && refQualityScore !== null && (
        <RefTraceWarningModal
          score={refQualityScore}
          onRetry={() => handleReplace([], true)}
          onClose={() => setShowRefTraceModal(false)}
        />
      )}

      {/* ── AI 리포트 드래그 모달 ── */}
      {showReport && reportData && (
        <div
          className={`fixed z-[800] w-[440px] flex flex-col bg-[#0d1526]/95 backdrop-blur-md border border-white/20 rounded-2xl shadow-2xl overflow-hidden ${reportCollapsed ? '' : 'max-h-[80vh]'}`}
          style={{ left: reportPos.x, top: reportPos.y }}
        >
          {/* 드래그 핸들 (헤더) */}
          <div
            onMouseDown={handleReportDragStart}
            className={`flex items-center justify-between px-4 py-3 cursor-grab active:cursor-grabbing select-none shrink-0 ${reportCollapsed ? '' : 'border-b border-white/10'}`}
          >
            <span className="flex items-center gap-2 text-sm font-bold text-white">
              <FileText size={14} className="text-primary" />
              AI 결과 리포트
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setReportCollapsed(v => !v)}
                className="text-slate-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/10"
                title={reportCollapsed ? '펼치기' : '접기'}
              >
                <ChevronDown size={14} className={`transition-transform ${reportCollapsed ? '' : 'rotate-180'}`} />
              </button>
              <button
                onClick={() => setShowReport(false)}
                className="text-slate-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/10"
                title="닫기"
              >
                ✕
              </button>
            </div>
          </div>
          {/* 리포트 내용 */}
          {!reportCollapsed && (
            <div className="overflow-y-auto p-4">
              <AnalysisReport data={reportData} />
            </div>
          )}
        </div>
      )}

      {/* ── AI 오브젝트 삭제 확인 모달 ── */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-[900] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#1a1a2e] border border-border rounded-2xl p-5 w-[320px] shadow-2xl text-center">
            <h3 className="text-sm font-bold text-white mb-3">AI 배치 오브젝트 삭제</h3>
            <p className="text-[11px] text-white leading-relaxed mb-1">
              선택한 항목은 AI가 자동 배치한 오브젝트입니다.
            </p>
            <p className="text-[11px] text-white leading-relaxed mb-3">
              정말 삭제하시겠습니까?
            </p>
            <p className="text-[11px] text-text-muted leading-relaxed mb-4">
              삭제 후 <span className="font-medium">Ctrl+Z</span>로 되돌릴 수 있습니다.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="flex-1 py-2 rounded-xl border border-border text-xs text-text-muted hover:bg-white/5 transition-colors"
              >
                취소
              </button>
              <button
                onClick={() => { doDeleteObjects(deleteConfirm); setDeleteConfirm(null); }}
                className="flex-1 py-2 rounded-xl bg-red-500/80 hover:bg-red-500 text-white text-xs font-bold transition-colors"
              >
                삭제
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 뒤로가기 확인 모달 ── */}
      {showBackConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#1a1a2e] border border-border rounded-2xl p-6 w-[360px] shadow-2xl">
            <h3 className="text-sm font-bold text-text-main mb-2">공간 확인으로 돌아가기</h3>
            <p className="text-[11px] text-text-muted mb-4 leading-relaxed">
              배치 결과가 초기화됩니다.<br />
              공간 확인 단계에서 다시 배치를 생성할 수 있습니다.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setShowBackConfirm(false)}
                className="flex-1 py-2 rounded-xl border border-border text-xs text-text-muted hover:bg-white/5 transition-colors"
              >취소</button>
              <button
                onClick={handleBackToFloor}
                className="flex-1 py-2 rounded-xl bg-red-500/20 border border-red-500/40 text-xs text-red-300 hover:bg-red-500/30 transition-colors"
              >돌아가기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
