/**
 * ProjectContext — 파이프라인 전반 state 전역화
 * /project/new → /project/floor → /project/result 세 페이지가 공유
 *
 * 대부분 새로고침 시 휘발 (F6 세션 복원 API 미구현).
 * 예외: activeJob + projectId + resumingFilename + 3종 ID 은 sessionStorage 복구 (2026-04-20).
 *   → 새로고침해도 진행중인 job 배지 유지 + MyPage resume 흐름 보존.
 */
import { createContext, useContext, useEffect, useState, useRef, useCallback, type ReactNode } from 'react';
import axios from 'axios';
import type { BrandExtraction, AutoDetected, SpaceData, PlacementResult, LayoutObject } from '../types/floor';
import type { Wall } from '../components/ThreeViewer';
import type { JobType } from '../types/job';
import { useAuth } from './AuthContext';
import { getProject } from '../lib/api';

// ── 마킹 타입 ────────────────────────────────────────────
// 추후 스케일 수동 앵커 기능 필요 시 'scale_anchor' 다시 추가
export type MarkMode = 'entrance' | 'sprinkler' | 'fire_hydrant' | 'electrical_panel' /* | 'scale_anchor' */ | null;
export type Pt2 = { x_px: number; y_px: number };
export type EntranceMark = { points: Pt2[]; x_px: number; y_px: number; x2_px?: number; y2_px?: number };

type Snapshot = { placed: LayoutObject[]; walls: Wall[] };

/**
 * 진행중인 비동기 작업 기록.
 * useJob 훅이 폴링 중인 job_id + 타입. 헤더 뱃지/토스트 표시에 쓰임.
 */
export interface ActiveJob {
  id: number;
  type: JobType;
  startedAt: number; // Date.now()
  projectId?: number; // 이 job이 속한 프로젝트 — FloorPage/ResultPage가 버튼 비활성 판단에 사용
}

interface ProjectContextType {
  // ── 파일 ──
  floorFile: File | null;
  setFloorFile: (f: File | null) => void;
  brandFile: File | null;
  setBrandFile: (f: File | null) => void;
  crossSectionFile: File | null;
  setCrossSectionFile: (f: File | null) => void;

  // ── 파이프라인 결과 ──
  autoDetected: AutoDetected | null;
  setAutoDetected: (v: AutoDetected | null) => void;
  brandExtraction: BrandExtraction | null;
  setBrandExtraction: (v: BrandExtraction | null) => void;
  spaceData: SpaceData | null;
  setSpaceData: (v: SpaceData | null) => void;
  placementResult: PlacementResult | null;
  setPlacementResult: (v: PlacementResult | null) => void;

  // ── 비동기 작업 (B안) ──
  activeJob: ActiveJob | null;
  setActiveJob: (v: ActiveJob | null) => void;

  // ── 서버 측 식별자 (B안 플로우 진행용) ──
  // 2026-04-27 rename: pdfId → floorArchiveId (pdf 테이블 → floor_archive 박물관 일관)
  floorArchiveId: number | null;
  setFloorArchiveId: (v: number | null) => void;
  brandManualId: number | null;
  setBrandManualId: (v: number | null) => void;
  floorDetectionId: number | null;
  setFloorDetectionId: (v: number | null) => void;
  // B8 — 다중 백그라운드: /detect에서 받은 project_id를 후속 단계마다 전달
  projectId: number | null;
  setProjectId: (v: number | null) => void;
  // MyPage에서 진행중 프로젝트 열 때 원본 파일명 전달 (파일 바이너리는 복원 안 함)
  resumingFilename: string | null;
  setResumingFilename: (v: string | null) => void;

  // ── 마킹 ──
  markMode: MarkMode;
  setMarkMode: (v: MarkMode) => void;
  markedEntrance: EntranceMark | null;
  setMarkedEntrance: (v: EntranceMark | null | ((prev: EntranceMark | null) => EntranceMark | null)) => void;
  markedSprinklers: Pt2[];
  setMarkedSprinklers: (v: Pt2[] | ((prev: Pt2[]) => Pt2[])) => void;
  markedFH: Pt2[];
  setMarkedFH: (v: Pt2[] | ((prev: Pt2[]) => Pt2[])) => void;
  markedEP: Pt2[];
  setMarkedEP: (v: Pt2[] | ((prev: Pt2[]) => Pt2[])) => void;

  // ── polygon 편집 ──
  editablePolygon: number[][];
  setEditablePolygon: (v: number[][] | ((prev: number[][]) => number[][])) => void;
  // ── 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가 ──
  // anchorPoints: { x: number; y: number }[];
  // setAnchorPoints: (v: { x: number; y: number }[] | ((prev: { x: number; y: number }[]) => { x: number; y: number }[])) => void;
  // anchorMm: string;
  // setAnchorMm: (v: string) => void;
  // manualWidthMm: string;
  // setManualWidthMm: (v: string) => void;
  // manualHeightMm: string;
  // setManualHeightMm: (v: string) => void;

  // ── 설정 ──
  densityRatio: number;
  setDensityRatio: (v: number) => void;
  brandCategory: string;
  setBrandCategory: (v: string) => void;
  userRequirements: string;
  setUserRequirements: (v: string) => void;
  venueType: string;
  setVenueType: (v: string) => void;

  // ── 요구사항 ──
  reqText: string;
  setReqText: (v: string) => void;
  appliedReqs: string[];
  setAppliedReqs: (v: string[] | ((prev: string[]) => string[])) => void;

  // ── 결과 조작 ──
  localPlaced: LayoutObject[];
  setLocalPlaced: (v: LayoutObject[] | ((prev: LayoutObject[]) => LayoutObject[])) => void;
  walls: Wall[];
  setWalls: (v: Wall[] | ((prev: Wall[]) => Wall[])) => void;
  selectedObjectIndices: number[];
  setSelectedObjectIndices: (v: number[] | ((prev: number[]) => number[])) => void;
  selectedObjectIndicesRef: React.MutableRefObject<number[]>;
  selectedWallId: string | null;
  setSelectedWallId: (v: string | null | ((prev: string | null) => string | null)) => void;

  // ── Undo ──
  pushHistory: (placed: LayoutObject[], ws: Wall[]) => void;
  popHistory: () => Snapshot | null;

  // ── 리셋 ──
  reset: () => void;
}

const ProjectContext = createContext<ProjectContextType | null>(null);

// ── sessionStorage 복구 키 (새로고침 유지) ─────────────────
const SS_KEY_ACTIVE_JOB = 'landup:activeJob';
const SS_KEY_PROJECT_ID = 'landup:projectId';
const SS_KEY_RESUMING_FILENAME = 'landup:resumingFilename';
const SS_KEY_FLOOR_ARCHIVE_ID = 'landup:floorArchiveId';
const SS_KEY_BRAND_MANUAL_ID = 'landup:brandManualId';
const SS_KEY_FLOOR_DETECTION_ID = 'landup:floorDetectionId';
// 2026-04-28: 공간분석중 재진입 무한로딩 fix — spaceData 도 휘발 방지
// (TODO H3 후순위 fix). 페이지 전환 후 재진입 시 step='space_confirm' 으로 진입 가능.
const SS_KEY_SPACE_DATA = 'landup:spaceData';
/** 30분 이상 묵은 activeJob은 stale 취급 — 자동 드롭 */
const ACTIVE_JOB_TTL_MS = 30 * 60 * 1000;

function ssGet<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch { return null; }
}
function ssSet(key: string, value: unknown) {
  try {
    if (value == null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  // AuthProvider 가 바깥에 있어야 함 (main.tsx 기준)
  const { currentUser } = useAuth();

  // 파일
  const [floorFile, setFloorFile] = useState<File | null>(null);
  const [brandFile, setBrandFile] = useState<File | null>(null);
  const [crossSectionFile, setCrossSectionFile] = useState<File | null>(null);

  // 파이프라인 결과
  const [autoDetected, setAutoDetected] = useState<AutoDetected | null>(null);
  const [brandExtraction, setBrandExtraction] = useState<BrandExtraction | null>(null);
  // spaceData 만 sessionStorage 복구 (재진입 시 step='space_confirm' 분기 위해, H3 fix)
  const [spaceData, setSpaceDataState] = useState<SpaceData | null>(() => ssGet<SpaceData>(SS_KEY_SPACE_DATA));
  const setSpaceData = useCallback((v: SpaceData | null) => { setSpaceDataState(v); ssSet(SS_KEY_SPACE_DATA, v); }, []);
  const [placementResult, setPlacementResult] = useState<PlacementResult | null>(null);

  // B안 비동기 — sessionStorage 복구 (새로고침 유지)
  const [activeJob, setActiveJobState] = useState<ActiveJob | null>(() => {
    const stored = ssGet<ActiveJob>(SS_KEY_ACTIVE_JOB);
    if (!stored) return null;
    // TTL 검사 — 30분 초과면 drop
    if (Date.now() - (stored.startedAt ?? 0) > ACTIVE_JOB_TTL_MS) {
      ssSet(SS_KEY_ACTIVE_JOB, null);
      return null;
    }
    return stored;
  });
  const [floorArchiveId, setFloorArchiveIdState] = useState<number | null>(() => ssGet<number>(SS_KEY_FLOOR_ARCHIVE_ID));
  const [brandManualId, setBrandManualIdState] = useState<number | null>(() => ssGet<number>(SS_KEY_BRAND_MANUAL_ID));
  const [floorDetectionId, setFloorDetectionIdState] = useState<number | null>(() => ssGet<number>(SS_KEY_FLOOR_DETECTION_ID));
  const [projectId, setProjectIdState] = useState<number | null>(() => ssGet<number>(SS_KEY_PROJECT_ID));
  const [resumingFilename, setResumingFilenameState] = useState<string | null>(() => ssGet<string>(SS_KEY_RESUMING_FILENAME));

  // setter를 sessionStorage 동기화 래핑
  const setActiveJob = useCallback((v: ActiveJob | null) => { setActiveJobState(v); ssSet(SS_KEY_ACTIVE_JOB, v); }, []);
  const setFloorArchiveId = useCallback((v: number | null) => { setFloorArchiveIdState(v); ssSet(SS_KEY_FLOOR_ARCHIVE_ID, v); }, []);
  const setBrandManualId = useCallback((v: number | null) => { setBrandManualIdState(v); ssSet(SS_KEY_BRAND_MANUAL_ID, v); }, []);
  const setFloorDetectionId = useCallback((v: number | null) => { setFloorDetectionIdState(v); ssSet(SS_KEY_FLOOR_DETECTION_ID, v); }, []);
  const setProjectId = useCallback((v: number | null) => { setProjectIdState(v); ssSet(SS_KEY_PROJECT_ID, v); }, []);
  const setResumingFilename = useCallback((v: string | null) => { setResumingFilenameState(v); ssSet(SS_KEY_RESUMING_FILENAME, v); }, []);

  // activeJob TTL 자동 만료 — 탭이 오래 열려있는 경우 stale 방지
  useEffect(() => {
    if (!activeJob) return;
    const remaining = ACTIVE_JOB_TTL_MS - (Date.now() - activeJob.startedAt);
    if (remaining <= 0) { setActiveJob(null); return; }
    const timer = window.setTimeout(() => setActiveJob(null), remaining);
    return () => window.clearTimeout(timer);
  }, [activeJob, setActiveJob]);

  // sessionStorage stale projectId 단발 검증 — mount/사용자 변경 시 1회
  // 서버에서 삭제된 projectId 가 남아있으면 sessionStorage 6 종 일괄 정리
  // → ActiveJobBadge 의 stale 폴링 / NewProjectPage 의 resume 무한 루프 둘 다 차단
  useEffect(() => {
    if (!currentUser || !projectId) return;
    let cancelled = false;
    (async () => {
      try {
        await getProject(projectId);
        // 200 OK = 유효한 projectId, 그대로 유지
      } catch (e) {
        if (cancelled) return;
        if (axios.isAxiosError(e) && (e.response?.status === 404 || e.response?.status === 403)) {
          // 404 = 삭제된 프로젝트 / 403 = 다른 유저 프로젝트 (세션스토리지 stale)
          setActiveJob(null);
          setProjectId(null);
          setFloorArchiveId(null);
          setBrandManualId(null);
          setFloorDetectionId(null);
          setResumingFilename(null);
          setSpaceData(null);
        }
        // 그 외 에러 (네트워크 일시 오류 등) 는 무시 — 다음 mount/page 에서 재검증 기회
      }
    })();
    return () => { cancelled = true; };
    // projectId 는 dep 에서 제외 — clearing 시 재검증 무한 루프 방지
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser?.id]);

  // 마킹
  const [markMode, setMarkMode] = useState<MarkMode>(null);
  const [markedEntrance, setMarkedEntrance] = useState<EntranceMark | null>(null);
  const [markedSprinklers, setMarkedSprinklers] = useState<Pt2[]>([]);
  const [markedFH, setMarkedFH] = useState<Pt2[]>([]);
  const [markedEP, setMarkedEP] = useState<Pt2[]>([]);

  // polygon 편집
  const [editablePolygon, setEditablePolygon] = useState<number[][]>([]);
  // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가
  // const [anchorPoints, setAnchorPoints] = useState<{ x: number; y: number }[]>([]);
  // const [anchorMm, setAnchorMm] = useState('');
  // const [manualWidthMm, setManualWidthMm] = useState('');
  // const [manualHeightMm, setManualHeightMm] = useState('');

  // 설정
  const [densityRatio, setDensityRatio] = useState(0.25);
  const [brandCategory, setBrandCategory] = useState('기타');
  const [userRequirements, setUserRequirements] = useState('');
  const [venueType, setVenueType] = useState('street_complex');

  // 요구사항
  const [reqText, setReqText] = useState('');
  const [appliedReqs, setAppliedReqs] = useState<string[]>([]);

  // 결과 조작
  const [localPlaced, setLocalPlaced] = useState<LayoutObject[]>([]);
  const [walls, setWalls] = useState<Wall[]>([]);
  const [selectedObjectIndices, setSelectedObjectIndices] = useState<number[]>([]);
  const selectedObjectIndicesRef = useRef<number[]>([]);
  const [selectedWallId, setSelectedWallId] = useState<string | null>(null);

  // Undo (최대 50단계)
  const undoStack = useRef<Snapshot[]>([]);
  const pushHistory = useCallback((placed: LayoutObject[], ws: Wall[]) => {
    undoStack.current = [
      ...undoStack.current.slice(-49),
      { placed: placed.map(p => ({ ...p })), walls: ws.map(w => ({ ...w })) },
    ];
  }, []);
  const popHistory = useCallback((): Snapshot | null => {
    if (!undoStack.current.length) return null;
    const snap = undoStack.current[undoStack.current.length - 1];
    undoStack.current = undoStack.current.slice(0, -1);
    return snap;
  }, []);

  const reset = useCallback(() => {
    setFloorFile(null); setBrandFile(null); setCrossSectionFile(null);
    setAutoDetected(null); setBrandExtraction(null);
    setSpaceData(null); setPlacementResult(null);
    // 래퍼 setter들이 sessionStorage 자동 클리어
    setActiveJob(null);
    setFloorArchiveId(null); setBrandManualId(null); setFloorDetectionId(null);
    setProjectId(null);
    setResumingFilename(null);
    setMarkMode(null);
    setMarkedEntrance(null); setMarkedSprinklers([]); setMarkedFH([]); setMarkedEP([]);
    setEditablePolygon([]);
    setBrandCategory('기타'); setDensityRatio(0.25);
    setUserRequirements(''); setVenueType('street_complex');
    setReqText(''); setAppliedReqs([]);
    setLocalPlaced([]); setWalls([]);
    setSelectedObjectIndices([]); selectedObjectIndicesRef.current = [];
    setSelectedWallId(null);
    undoStack.current = [];
  }, []);

  // selectedObjectIndicesRef 동기화
  selectedObjectIndicesRef.current = selectedObjectIndices;

  return (
    <ProjectContext.Provider value={{
      floorFile, setFloorFile, brandFile, setBrandFile,
      crossSectionFile, setCrossSectionFile,
      autoDetected, setAutoDetected, brandExtraction, setBrandExtraction,
      spaceData, setSpaceData, placementResult, setPlacementResult,
      activeJob, setActiveJob,
      floorArchiveId, setFloorArchiveId,
      brandManualId, setBrandManualId,
      floorDetectionId, setFloorDetectionId,
      projectId, setProjectId,
      resumingFilename, setResumingFilename,
      markMode, setMarkMode,
      markedEntrance, setMarkedEntrance,
      markedSprinklers, setMarkedSprinklers,
      markedFH, setMarkedFH, markedEP, setMarkedEP,
      editablePolygon, setEditablePolygon,
      brandCategory, setBrandCategory,
      densityRatio, setDensityRatio,
      userRequirements, setUserRequirements,
      venueType, setVenueType,
      reqText, setReqText, appliedReqs, setAppliedReqs,
      localPlaced, setLocalPlaced, walls, setWalls,
      selectedObjectIndices, setSelectedObjectIndices, selectedObjectIndicesRef,
      selectedWallId, setSelectedWallId,
      pushHistory, popHistory, reset,
    }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject(): ProjectContextType {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error('useProject must be used within ProjectProvider');
  return ctx;
}
