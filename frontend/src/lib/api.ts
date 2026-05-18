// API 호출 헬퍼 — B안 비동기 + JWT 자동 처리
//
// 모든 요청은 axiosClient 경유 → Authorization: Bearer 자동 첨부 + 401 refresh 자동.
// 응답 형식: 엔드포인트가 job 큐잉이면 {job_id}, 도메인 조회면 실제 데이터.
import axiosClient from './axiosClient'
import type { Job, JobEnqueued } from '../types/job'
import type { UserProjectDetail, UserProjectList, UserProjectListItem } from '../types/project'
import type { AutoDetected, BrandExtraction, SpaceData } from '../types/floor'

function getFileType(file: File): string {
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (ext === 'dxf') return 'dxf'
  if (ext === 'dwg') return 'dwg'
  if (['png', 'jpg', 'jpeg'].includes(ext)) return 'image'
  if (ext === 'pptx') return 'pptx'
  if (ext === 'docx') return 'docx'
  if (ext === 'xlsx') return 'xlsx'
  return 'pdf'
}

// ════════════════════════════════════════════════════════════════
// [LOCAL_TEST_USE_DIRECT] Python 직통 모드 (A안)
// ════════════════════════════════════════════════════════════════
// 활성화: frontend/.env.local 에 다음 두 줄 추가
//   VITE_USE_DIRECT=true
//   VITE_DIRECT_URL=http://localhost:8000
// 미설정 또는 false → 기존 B안 (Java 경유 + Job 폴링) 그대로 동작.
//
// 용도: 로컬에서 Python 백엔드만 띄우고 (Java/Redis/Worker 불요)
//       18평 LUMIA 같은 E2E 실측 테스트를 빠르게 수행.
// 실행: uvicorn app.api:app --port 8000 (backend/python/ 디렉토리)
// 검색: grep -rn "LOCAL_TEST_USE_DIRECT" frontend/src/
//
// Python 엔드포인트는 동기 직접 응답 (job_id 없음). 응답 구조가 Java 와 다르므로
// 호출부 (NewProjectPage / FloorPage) 에서 USE_DIRECT 분기 필요.
// ════════════════════════════════════════════════════════════════

// [LOCAL_TEST_USE_DIRECT] 환경변수 → 직통 모드 on/off
export const USE_DIRECT: boolean = import.meta.env.VITE_USE_DIRECT === 'true'
const DIRECT_URL: string = import.meta.env.VITE_DIRECT_URL || 'http://localhost:8000'

/** 단면도 파일(PDF/DXF/DWG)에서 ceiling_height_mm 추출.
 *  USE_DIRECT=true → Python 직통, false → Java 경유. */
export async function detectCeilingHeight(file: File): Promise<{ ceiling_height_mm: number | null }> {
  const form = new FormData()
  form.append('cross_section', file)
  form.append('file_type', getFileType(file))
  if (USE_DIRECT) {
    const res = await fetch(`${DIRECT_URL}/api/ceiling-height`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(`단면도 분석 실패: ${res.status} ${res.statusText}`)
    return res.json()
  }
  const res = await axiosClient.post('/ceiling-height', form)
  return res.data
}

/** [LOCAL_TEST_USE_DIRECT] /api/detect 직통 — auto_detected 또는 레이어 선택 요청 반환. */
export async function detectFloorDirect(file: File, forceLayer?: string): Promise<AutoDetected | LayerSelectNeeded> {
  const form = new FormData()
  form.append('floor_plan', file)
  form.append('file_type', getFileType(file))
  if (forceLayer) form.append('force_layer', forceLayer)
  const res = await fetch(`${DIRECT_URL}/api/detect`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`detect 직통 실패: ${res.status} ${res.statusText}`)
  const data = await res.json()
  if (data.parse_status === 'layer_select_needed') {
    return { needLayerSelect: true, layers: data.available_layers ?? [] }
  }
  return data as AutoDetected
}

/** [LOCAL_TEST_USE_DIRECT] /api/brand 직통 — brand_data 즉시 반환. */
export async function extractBrandDirect(file: File): Promise<BrandExtraction> {
  const form = new FormData()
  form.append('brand_manual', file)
  form.append('file_type', getFileType(file))
  const res = await fetch(`${DIRECT_URL}/api/brand`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`brand 직통 실패: ${res.status} ${res.statusText}`)
  return (await res.json()) as BrandExtraction
}

/** [LOCAL_TEST_USE_DIRECT] /api/space-data 직통 — SpaceData 즉시 반환. */
export async function calculateSpaceDirect(body: {
  auto_detected: Record<string, unknown>
  brand_dict?: Record<string, unknown>
  brand_category?: string
  venue_type?: string
}): Promise<SpaceData> {
  const res = await fetch(`${DIRECT_URL}/api/space-data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      auto_detected: body.auto_detected,
      brand_dict: body.brand_dict || {},
      brand_category: body.brand_category || '기타',
      venue_type: body.venue_type || 'street_complex',
    }),
  })
  if (!res.ok) throw new Error(`space-data 직통 실패: ${res.status} ${res.statusText}`)
  const data = await res.json()
  // Python 엔드포인트는 {space_data: {...}} 로 감싸서 반환
  return (data.space_data ?? data) as SpaceData
}

/** [LOCAL_TEST_USE_DIRECT] /api/place 직통 — placement 결과 즉시 반환.
 *
 * 주의: Java 의 placeObjects 와 body 구조가 다름.
 * - Java: {floor_detection_id, density_ratio, ...} → DB 에서 space_data 조회
 * - Python 직통: space_data 객체를 spread 해서 직접 전달 (floor/entrance/brand_dict/...)
 */
export async function placeObjectsDirect(body: {
  space_data: Record<string, unknown>           // calculateSpaceDirect 응답을 그대로 spread
  density_ratio?: number
  brand_dict?: Record<string, unknown>
  brand_category?: string
  user_requirements?: string
  locked_objects?: Record<string, unknown>[]
  venue_type?: string
}): Promise<{
  // Python /api/place 실제 응답 키. placed_objects/layout_objects 아님.
  objects?: unknown[]
  failed_objects?: unknown[]
  placed_count?: number
  failed_count?: number
  [k: string]: unknown
}> {
  const payload = {
    ...body.space_data,                          // floor / entrance / brand_dict / dead_zones / ...
    density_ratio: body.density_ratio,
    brand_dict: body.brand_dict ?? {},
    brand_category: body.brand_category ?? '기타',
    user_requirements: body.user_requirements,
    locked_objects: body.locked_objects ?? [],
    venue_type: body.venue_type ?? 'street_complex',
  }
  const res = await fetch(`${DIRECT_URL}/api/place`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`place 직통 실패: ${res.status} ${res.statusText}`)
  return res.json()
}

/** [LOCAL_TEST_USE_DIRECT] /api/report/latest 직통 — 분석 보고서 데이터 즉시 반환.
 *  AnalysisReportData 타입은 components/mypage/mockAnalysisReport.ts 참조.
 *  타입 import 의존성 회피 위해 unknown 으로 반환 → 호출부에서 캐스팅. */
export async function fetchAnalysisReportDirect(): Promise<unknown> {
  const res = await fetch(`${DIRECT_URL}/api/report/latest`)
  if (!res.ok) {
    if (res.status === 404) throw new Error('아직 배치 실행 이력이 없습니다. 먼저 배치를 1회 실행해 주세요.')
    throw new Error(`report 직통 실패: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

// ════════════════════════════════════════════════════════════════
// [LOCAL_TEST_USE_DIRECT] 끝 — 아래는 기존 B안 (Java 경유) 코드
// ════════════════════════════════════════════════════════════════

// ── 비동기 작업 생성 ─────────────────────────────────────────────────

/** 레이어 선택 필요 응답 타입 */
export type LayerSelectNeeded = {
  needLayerSelect: true
  layers: string[]
}

/** 도면 분석 — 즉시 job_id 반환. 결과는 useJob 폴링 필요. */
export async function detectFloor(file: File, forceLayer?: string): Promise<JobEnqueued & { floor_archive_id?: number; project_id?: number }> {
  const form = new FormData()
  form.append('floor_plan', file)
  form.append('file_type', getFileType(file))
  if (forceLayer) form.append('force_layer', forceLayer)
  const res = await axiosClient.post('/detect', form)
  return res.data
}

/**
 * job 에러 메시지에서 레이어 선택 요청 여부 파싱.
 * Worker가 "LAYER_SELECT:{available_layers:[...]}" 형식으로 전달.
 */
export function parseLayerSelectError(errorMessage: string | null | undefined): LayerSelectNeeded | null {
  if (!errorMessage?.startsWith('LAYER_SELECT:')) return null
  try {
    const json = JSON.parse(errorMessage.slice('LAYER_SELECT:'.length))
    return { needLayerSelect: true, layers: json.available_layers ?? [] }
  } catch {
    return null
  }
}

export async function extractBrand(file: File, projectId?: number): Promise<JobEnqueued & { brand_manual_id?: number }> {
  const form = new FormData()
  form.append('brand_manual', file)
  form.append('file_type', getFileType(file))
  if (projectId != null) form.append('project_id', String(projectId))
  const res = await axiosClient.post('/brand', form)
  return res.data
}

export async function calculateSpace(body: {
  auto_detected: Record<string, unknown>
  brand_dict?: Record<string, unknown>
  brand_category?: string
  venue_type?: string
  floor_archive_id?: number
  page_number?: number
  brand_manual_id?: number
  project_id?: number
}): Promise<JobEnqueued> {
  const res = await axiosClient.post('/space-data', {
    auto_detected: body.auto_detected,
    brand_dict: body.brand_dict || {},
    brand_category: body.brand_category || '기타',
    venue_type: body.venue_type || 'street_complex',
    floor_archive_id: body.floor_archive_id ?? null,
    page_number: body.page_number ?? null,
    brand_manual_id: body.brand_manual_id ?? null,
    project_id: body.project_id ?? null,
  })
  return res.data
}

export async function placeObjects(body: {
  floor_detection_id: number
  density_ratio?: number
  brand_dict?: Record<string, unknown>
  brand_category?: string
  user_requirements?: string
  locked_objects?: Record<string, unknown>[]
  venue_type?: string
  page_number?: number
  brand_manual_id?: number
  project_id?: number
}): Promise<JobEnqueued> {
  const res = await axiosClient.post('/place', body)
  return res.data
}

// ── Job 상태 조회 (useJob 훅이 폴링) ──────────────────────────────────

export async function getJob(jobId: number, signal?: AbortSignal): Promise<Job> {
  const res = await axiosClient.get(`/jobs/${jobId}`, { signal })
  return res.data
}

export async function cancelJob(jobId: number): Promise<void> {
  await axiosClient.post(`/jobs/${jobId}/cancel`)
}

// ── 중간 단계 결과 조회 (B안 async 플로우용) ─────────────────────────

export async function getDetectResult(floorArchiveId: number): Promise<AutoDetected> {
  const res = await axiosClient.get(`/floor-archives/${floorArchiveId}/pages`)
  return res.data.dimensions as AutoDetected
}

export async function getBrandResult(brandManualId: number): Promise<BrandExtraction> {
  const res = await axiosClient.get(`/brand-manuals/${brandManualId}`)
  return res.data.brand_data as BrandExtraction
}

export async function getFloorDetectionResult(floorDetectionId: number): Promise<SpaceData> {
  const res = await axiosClient.get(`/floor-detections/${floorDetectionId}`)
  return res.data.result as SpaceData
}

// ── 프로젝트 (user_projects) ──────────────────────────────────────────

export async function getMyProjects(): Promise<UserProjectListItem[]> {
  const res = await axiosClient.get('/me/projects')
  const data: UserProjectList = res.data
  return data.projects
}

export async function getProject(projectId: number): Promise<UserProjectDetail> {
  const res = await axiosClient.get(`/projects/${projectId}`)
  return res.data
}

export async function renameProject(projectId: number, name: string): Promise<UserProjectDetail> {
  const res = await axiosClient.patch(`/projects/${projectId}`, { name })
  return res.data
}

export async function deleteProject(projectId: number): Promise<void> {
  await axiosClient.delete(`/projects/${projectId}`)
}

// ── 오브젝트 카탈로그 (object_palette 테이블) ──────────────────────────
// 백엔드: com.landup.catalog.CatalogController.listAll() → GET /api/catalog/objects
export interface ObjectPaletteItem {
  id: number
  code: string                // object_type key (counter/display_table/...)
  nameKo: string              // 한글 표시명
  priority: number            // 배치 우선순위 (팔레트 정렬에도 활용)
  frontEdge: 'width' | 'depth'
  isStructural: boolean
  fixtureRole?: string | null
  widthStdMm: number
  depthStdMm: number
  heightStdMm: number
  createdAt?: string
}

/** 프로젝트별 구조화 리포트 조회. report_json 없으면 404 throw. */
export async function fetchProjectReport(projectId: number): Promise<unknown> {
  const res = await axiosClient.get(`/placements/projects/${projectId}/report`)
  return res.data.report_json ? JSON.parse(res.data.report_json) : res.data
}

/** 기존 프로젝트용 리포트 즉시 생성 — DB에 report_json 없을 때 Python 직접 호출 fallback. */
export async function generateReportFromResult(payload: {
  placed_objects: unknown[]
  failed_objects: unknown[]
  dead_zones: unknown[]
  token_usage: unknown[]
  pair_rules: unknown[]
  brand_data: Record<string, unknown>
  area_m2: number | null
  ceiling_height_mm: number | null
  entrance_count: number
  sprinkler_count: number
  brand_category: string
  ref_quality_score: number | null
}): Promise<unknown> {
  const res = await fetch(`${DIRECT_URL}/api/report/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`report/generate 실패: ${res.status}`)
  return res.json()
}

export async function getObjectPalette(): Promise<ObjectPaletteItem[]> {
  // [LOCAL_TEST_USE_DIRECT] Python 직통 모드에서는 catalog endpoint 미존재 → 빈 배열 반환
  // (ResultPalette 가 fallback 으로 자체 정의한 기본 오브젝트 목록 사용)
  if (USE_DIRECT) {
    return []
  }
  const res = await axiosClient.get('/catalog/objects')
  return res.data as ObjectPaletteItem[]
}
