// Shin 타입 정의 포팅

export interface BrandExtraction {
  clearspace_mm?: { value: number; confidence: string }
  logo_clearspace_mm?: { value: number; confidence: string }
  character_orientation?: { value: string; confidence: string }
  placement_rules?: Array<Record<string, unknown>>
  brand_category?: string
  [key: string]: unknown
}

export interface AutoDetected {
  floor_polygon_px: number[][]
  scale_mm_per_px: number
  scale_confidence: number
  detected_width_mm?: number | null
  detected_height_mm?: number | null
  ceiling_height_mm?: number | null
  entrance: { x_px: number; y_px: number } | null
  sprinklers: Array<{ x_px: number; y_px: number }>
  fire_hydrants: Array<{ x_px: number; y_px: number }>
  electrical_panels: Array<{ x_px: number; y_px: number }>
  failures?: { scale?: boolean }
  disclaimer?: string[]
  image_base64?: string
  vision_transform?: {
    type: string
    range_x?: number
    range_y?: number
    [key: string]: unknown
  }
  [key: string]: unknown
}

export interface ZoneInfo {
  polygon_mm: number[][]
  reference_points: string[]
  slot_count: number
  walk_mm_range: number[]
}

export interface SpaceData {
  floor: {
    polygon_mm: number[][]
    usable_area_sqm: number
    max_object_w_mm: number
    [key: string]: unknown
  }
  entrance: { x_mm: number; y_mm: number; [key: string]: unknown }
  reference_points: Record<string, {
    x_mm: number; y_mm: number
    zone_label?: string
    concept_area?: string  // 2026-05-01 Phase 4-2 — 영역 색칠 (ref_point 마커)
    concept_area_id?: number | null
    wall_size_label?: string
    facing_entrance?: boolean
    is_entrance_wall?: boolean
    is_partition?: boolean
    walk_mm?: number
    [key: string]: unknown
  }>
  zone_map?: Record<string, ZoneInfo>
  /** 2026-05-01 Phase 4-2 갈래 3 — large concept_area 폴리곤 (영역별 바닥 채우기 + 레전드용). */
  concept_areas?: Array<{
    name: string  // 영문 키 (welcome / photo / ... — Viewer3D 색 매핑 + KO 라벨 lookup)
    polygon_mm: number[][]
    area_ratio?: number
  }>
  dead_zones: Array<{
    type: string
    center_mm: number[]
    radius_mm: number
    polygon_mm?: number[][]
  }>
  /** 소형·중형 slot 배치 후보 (Rendy 영역). large는 비어있음. */
  slots?: Record<string, {
    x_mm: number; y_mm: number
    zone_label?: string
    wall_size_label?: string
    [key: string]: unknown
  }>
  [key: string]: unknown
}

export interface LayoutObject {
  id: string
  object_type: string
  /** 사용자 표시 라벨 (Python 한국어, 예: "카운터"). 2026-05-10 백엔드 컬럼 복원 — Java placement_objects.label 직렬화. 누락 시 object_type 으로 fallback. */
  label?: string
  center_x_mm: number; center_y_mm: number
  width_mm: number; depth_mm: number; height_mm: number
  rotation_deg: number
  anchor_key?: string
  direction?: string
  placed_because?: string
  [key: string]: unknown
}

export interface PlacementRule {
  object_type: string
  width_mm?: number
  depth_mm?: number
  height_mm?: number
  preferred_wall?: string
  manual_note?: string
  [key: string]: unknown
}

export interface PlacementResult {
  // ── Java placement_result PK (GLB 다운로드 등 상세 endpoint 호출용) ──
  id?: number

  // ── 프론트 내부 표현 (DB 조회 후 정규화된 리스트) ──
  layout_objects: LayoutObject[]
  validation: {
    status: string
    violations: Array<{ type?: string; detail?: string; severity?: string; object_id?: string }>
  }
  placement_rules?: PlacementRule[]

  // ── Python _format_place_response scalar 필드 (정본 네이밍) ──
  placed_count?: number
  failed_count?: number
  fallback_round?: number
  verification_passed?: boolean
  density_ratio?: number
  user_requirements?: string
  report_text?: string
  glb_path?: string

  // ── Python 하위 리스트 (Java 저장 후 getProject 조회 시 포함) ──
  objects?: LayoutObject[]
  failed_objects?: Array<{ object_type: string; reason: string }>
  verifications?: Array<{ placement_object_id?: number; rule?: string; severity?: string; detail?: string }>
  cap_logs?: Array<{ object_type: string; reason?: string; dimension?: string; from_count?: number; to_count?: number }>
  token_usage?: Array<{ node_name: string; input_tokens?: number; output_tokens?: number; cache_read_tokens?: number; cache_write_tokens?: number; model?: string }>

  // ── 프론트/디버그 보조 ──
  requirement_failures?: Array<Record<string, unknown>>
  pathways?: Array<Record<string, unknown>>
  trapped_objects?: Array<Record<string, unknown>>
  ref_point_status?: Array<Record<string, unknown>>

  // ── 2026-04-29 (#264 fail-loud) — design 단계 fallback 발생 시 사유 ──
  // null = LLM 정상 / "REF_CONTEXT_MISSING" / "API_KEY_MISSING" / "CIRCUIT_BREAKER: ..."
  // 프론트는 이 값 != null 일 때 사용자에게 경고 표시 (배치 품질 저하 인지)
  design_fallback_reason?: string | null

  // ── 2026-04-29 (#116 F-8 복원) -> 2026-05-04 형식 변경 ──
  // 변경 전 - 단일 라인 [[x_mm, y_mm], ...]
  // 변경 후 - 여러 라인 [[[x_mm, y_mm], [x_mm, y_mm]], ...] (각 가지 = 별 라인)
  // main_artery 에서 좁은 가구 사이 영역 / 고립 ref_point 까지 일자 동선들.
  // Viewer3D 의 SubPathBranches 가 받아서 가지 별 라인 시각화.
  sub_path?: number[][][]

  // ── 2026-05-04 신설 - 주동선 좌표 (main_artery) ──
  // [[x_mm, y_mm], ...] 단일 라인. 순환 동선 (loop spine) 또는 일자 fallback.
  // walk_mm 노드가 b_space_data 에서 place 단계로 이동되면서 placement_result 에 박힘.
  main_artery?: number[][] | null

  // ── 2026-05-04 신설 - 레퍼런스 반영도 점수 (ref_quality_score) ──
  // 0.0 ~ 1.0. ref_trace_scorer 노드가 채점 (배치 결과 + design_intents + ref_analysis 매칭 정도).
  // 디자인 참조 로직 트랙 8번 - 점수 < 0.4 시 사용자 경고 모달 트리거 (수동).
  ref_quality_score?: number | null
}

// FloorPoint for polygon coordinates
export type FloorPoint = number[]
