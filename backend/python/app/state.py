"""
LangGraph Pipeline State -- 노드 간 데이터 전달 타입 정의.

규모별 완전 분리:
  LargeState  -- Shin 전용 (대형·야외, ref_point + LLM 자율 배치)
  SmallState  -- Rendy 전용 (소·중형, slot 룰 기반)

두 State는 상속 관계 없이 독립. 겹치는 필드가 있어도 각자 관리.
"""
from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from shapely.geometry import LineString, Polygon


# ── ref_image_analyzer 출력 명세 (#263 B 안) ──────────────────────────
# Pydantic VisionAnalysisResult (nodes_*/ref_image_analyzer.py) 와 1:1.
# 다른 노드의 envelope 가정 (status/result 키 검사) 회귀 차단용 — A-fix (1725cb2)
# 후속 정식 정의. analyzer 의 모든 path (성공/빈 입력/API key 없음/에러) 가
# 동일 flat dict 또는 빈 dict 반환. envelope 구조 X.
class RefAnalysisDict(TypedDict, total=False):
    """레퍼런스 이미지 Vision 분석 결과 (flat dict). 빈 dict 가능."""
    layout_patterns: list
    partition_usage: list
    focal_points: list
    flow_description: str
    density_impression: str
    space_mood: str
    composition_principle: str
    design_highlights: list


def is_ref_analysis_empty(ref_analysis: Optional[RefAnalysisDict]) -> bool:
    """ref_analysis 비어있는지 통일 helper. analyzer 4 path (성공/빈 입력/API key 없음/에러)
    중 비정상 path 가 모두 빈 dict 반환하므로 'not ref_analysis' 만으로 충분.
    envelope (status/result) 가정 금지 — 5-1 A-fix 회귀 차단."""
    return not ref_analysis


# ── Shin 전용 (대형·야외) ─────────────────────────────────────────────

class LargeState(TypedDict, total=False):
    """대형·야외 파이프라인 State."""

    # ── 입력 ──
    file_bytes: bytes
    file_type: str
    brand_bytes: Optional[bytes]
    density_ratio: Optional[float]

    # ── 2026-05-05 burning_task 1단계 — pillar_toilet_detect (Haiku Vision) ──
    # 별도 검출 노드. dead_zone 이 dead_zones 통합 흡수 (DB 컬럼 신설 X).
    pillars_mm: list   # [{x_mm, y_mm, w_mm, h_mm}, ...] — 기둥 사각형
    toilets_mm: list   # [{x_mm, y_mm, w_mm, h_mm, label}, ...] — 화장실 사각형

    # ── 파싱 결과 ──
    floor_polygon_px: list                  # 1200x900 정규화 좌표 [[x,y], ...]
    scale_mm_per_px: Optional[float]        # 픽셀→mm 변환 비율(스케일)
    scale_confirmed: bool
    detected_width_mm: Optional[float]
    detected_height_mm: Optional[float]
    ceiling_height_mm: Optional[float]      # 단면도에서 추출한 층고
    entrance: Optional[dict]
    entrances: list
    entrance_width_mm: Optional[float]
    inner_walls: list
    inaccessible_rooms: list
    is_vector: bool
    image_bytes: Optional[bytes]
    vision_transform: Optional[dict]

    # ── Vision 감지 결과 ──
    sprinklers: list
    fire_hydrants: list
    electrical_panels: list

    # ── 브랜드 ──
    brand_data: dict

    # ── mm 변환 후 Shapely ──
    usable_poly: Optional[Polygon]
    entrance_mm: Optional[tuple]
    all_entrances_mm: list
    sprinklers_mm: list
    hydrants_mm: list
    electric_panels_mm: list
    inaccessible_polys: list
    inaccessible_types: list   # 2026-05-06: parser_dxf type list (toilet/pillar/core/stair). state drop 방지.
    floor_px_min_x: float
    floor_px_min_y: float

    # ── 공간 기초 ──
    dead_zones: list
    inner_wall_linestrings: list

    # ── ref_point / zone / 동선 ──
    reference_points: list
    main_artery: Optional[LineString]
    entrance_line: Optional[LineString]
    entrance_buffer: Optional[Polygon]

    # ── 기능 영역 (concept_area) ──
    concept_areas: list

    # ── 영역 배치 검증 결과 (lg_layout_validator, 2026-05-04) ──
    # LAYOUT_VALIDATION_RULES 의 각 rule key + key_reason 동적 박힘.
    # 예: {"welcome_at_entrance": "WARN", "welcome_at_entrance_reason": "..."}
    # design 노드 prompt 에 자연어로 inject 됨. 강제 차단 X.
    concept_area_check: dict

    # ── 사용자 디자인 컨셉 ──
    user_design_concept: Optional[str]

    # ── 레퍼런스 ──
    reference_images: list
    reference_images_by_zone: dict          # 존별 레퍼런스 {"체험존": [...], "포토존": [...]}
    layout_examples: list
    ref_analysis: RefAnalysisDict
    reference_meta: dict                    # ref_image_loader 가 기록한 검색 메타 (쿼리/카테고리/영역별 통계)
    analyzer_status: Optional[str]          # ref_image_analyzer 결과 상태: ok/skipped/empty_response/no_tool_block/error
    analyzer_skip_reason: Optional[str]     # status 가 skipped/error 일 때 상세 사유

    # ── 디자인 의도 (Agent 3) ──
    design_intents: list
    eligible_objects: list

    # ── 배치 결과 ──
    placed_objects: list
    placed_raw: list
    failed_objects: list
    placement_log: list
    sub_path: list                            # 부동선 좌표 [[x_mm, y_mm], ...] (#116, F-8). 부재 시 빈 list

    # ── 검증 ──
    verification: dict

    # ── 레퍼런스 반영도 ──
    ref_trace: dict
    ref_quality_score: Optional[float]

    # ── fallback ──
    fallback_round: int

    # ── 2026-05-05 TR_TH 트랙 1 = concept_area 3노드 패턴 (작업+검증+수정) ──
    # layout_validator 가 fix_needed 판정 시 concept_area_fix 노드 호출. max 2회 재시도.
    concept_area_fix_retry_count: Optional[int]
    # 2026-05-08 안전망 H 강화 — 1차 + retry 결과 모두 누적. max_retry 후 history 안 위반 가장 적은 결과 선택.
    # history[0] = 1차 BSP 결과, history[1] = fix retry 1, history[2] = fix retry 2.
    # 폐기: concept_areas_initial (history[0] 와 동일) — 2026-05-08 history 로 통합.
    concept_areas_history: Optional[list]
    # 2026-05-06 design 3노드 패턴 — design_validator 출력 (rule key 별 OK/WARN + verdict).
    design_check: Optional[dict]
    # design_fix 노드 호출 retry count. max 2.
    design_fix_retry_count: Optional[int]
    # layout_validator 출력 — verdict + violations + needs_fix. 기존 concept_area_check (rule key 별 OK/WARN) 와 병행.
    layout_validator_result: Optional[dict]
    # 2026-05-06 burning_task 2단계 본질 정비 — Tool 1개 (Voronoi) 단일화로 algorithm 추적 폐기.

    # ── 사용자 요구사항 / 인텐트 ──
    user_requirements: Optional[str]         # 자연어 배치 요구사항
    resolved_intents: list                   # intent_parser 출력 (ResolvedIntent 직렬화)

    # ── 배치 전략 (strategy resolver 출력) ──
    placement_strategy: Optional[str]        # ADD_ONLY / RESIZE_ONLY / RESIZE_AND_ADD / PARTIAL_REORIENT / FULL_RELAYOUT / NOOP
    global_direction_hint: Optional[str]     # FULL_RELAYOUT 시 모든 design_intent에 적용할 방향
    dimension_overrides: dict                # {object_type: {width_mm, depth_mm}} — resize 시 obj_map 덮어씌움

    # ── 2026-05-02 graph 랭그래프화 — 누락 키 보강 (LangGraph TypedDict drop 방지) ──
    floor_detection_id: Optional[int]        # Java 영속화용 (concept_area / placement_object FK)
    user_project_id: Optional[int]           # ref_image_loader Java handoff 추적
    _scale_type: Optional[str]               # "large" / "small" — handle_place 분기 결과 (graph 안 dropped 방지)
    intent_parse_error: Optional[str]        # intent_parser LLM 실패 사유 (early return 분기 결정)
    locked_objects: list                     # 재배치 모드 시 기존 배치 유지 list
    _original_resolved_intents: list         # intent_processor 가 보존 — 최종 실패 시 사용자 요구 매핑용
    _no_fallback: Optional[bool]             # early return 분기 (intent_parse_error / NOOP+locked) 가 verify 후 fallback skip 신호
    token_usage_summary: dict                # invoke wrapper 가 dump_and_reset() 결과 박음 (Java INSERT 용)
    intent_parse_fallback_reason: Optional[str]  # small intent_parser 의 fallback 사유 (미사용, schema 만)
    placed_partitions: list                  # small partition_placement 출력 (호환용)
    design_fallback_reason: Optional[str]    # design 노드 fallback 사유 (REF_CONTEXT_MISSING / API_KEY_MISSING / CIRCUIT_BREAKER)


# ── Rendy 전용 (소·중형) ──────────────────────────────────────────────

class SmallState(TypedDict, total=False):
    """소·중형 파이프라인 State."""

    # ── 입력 ──
    file_bytes: bytes
    file_type: str
    brand_bytes: Optional[bytes]
    density_ratio: Optional[float]
    venue_type: Optional[str]           # "street_complex" | "street_standalone"
    facade_type: Optional[str]          # "open_glass" | "show_window" | "closed" — 파사드 타입 (app/facade_rules.py)

    # ── 파싱 결과 ──
    floor_polygon_px: list
    scale_mm_per_px: Optional[float]
    scale_confirmed: bool
    detected_width_mm: Optional[float]
    detected_height_mm: Optional[float]
    ceiling_height_mm: Optional[float]      # 단면도에서 추출한 층고
    entrance: Optional[dict]
    entrances: list
    entrance_width_mm: Optional[float]
    inner_walls: list
    inaccessible_rooms: list
    is_vector: bool
    image_bytes: Optional[bytes]
    vision_transform: Optional[dict]

    # ── Vision 감지 결과 ──
    sprinklers: list
    fire_hydrants: list
    electrical_panels: list

    # ── 브랜드 ──
    brand_data: dict

    # ── mm 변환 후 Shapely ──
    usable_poly: Optional[Polygon]
    entrance_mm: Optional[tuple]
    all_entrances_mm: list
    sprinklers_mm: list
    hydrants_mm: list
    electric_panels_mm: list
    inaccessible_polys: list
    inaccessible_types: list   # 2026-05-06: parser_dxf type list (toilet/pillar/core/stair). state drop 방지.
    floor_px_min_x: float
    floor_px_min_y: float

    # ── 공간 기초 ──
    dead_zones: list
    dead_zone_types: list      # 2026-05-08: dead_zone.py 가 박는 type list (electrical_panel/toilet/stair/pillar/...). state drop 방지 — 미정의 시 LangGraph schema 가 drop → extract_structural_dead_zones 가 dz_types 빈 list 로 모두 skip → core_access 미생성 → 계단 입구 1500mm 감압존 무력화 (5-7~5-8 라이브 회귀 근본 원인).
    inner_wall_linestrings: list

    # ── slot 기반 ──
    slots: dict

    # ── 디자인 의도 ──
    design_intents: list
    eligible_objects: list

    # ── #474 anti-pattern reviewer (도박수, Phase 1) ──
    # design_reviewer 노드 결과. graph.py 의 conditional edge 가 분기에 사용.
    # kill switch: ANTI_PATTERN_REVIEWER_ENABLED=false (env var)
    reviewer_status: Optional[str]               # "pass" | "reject" | "skipped"
    reviewer_violations: list                    # [{rule_id, severity, intent_object_type, intent_zone, violation_detail}, ...]
    reviewer_feedback: str                       # designer 재호출 prompt inject 용 자연어
    _reviewer_feedback: str                      # state 영속 — design 재호출 시 prompt 에 inject
    _review_iteration: int                       # 0, 1, 2 — MAX_REVIEW_ITERATIONS 추적
    _review_similarity_converged: Optional[bool] # 유사도 95%+ 수렴 검출 (재호출 종료 신호)
    prev_design_intents: list                    # 직전 iteration 의 intents — 유사도 비교용

    # ── #490 placement reviewer (5-5 진규님 의도 — slot 양보 hint) ──
    # placement 후 placed/failed 검증. design 재호출 시 _placement_reviewer_feedback inject.
    # kill switch: PLACEMENT_REVIEWER_ENABLED=false (env var)
    placement_reviewer_status: Optional[str]     # "pass" | "reject" | "skipped"
    placement_reviewer_violations: list          # [{rule_id, severity, ...}]
    placement_reviewer_feedback: str             # design 재호출 prompt inject 용 자연어
    _placement_reviewer_feedback: str            # state 영속 — design 재호출 시 inject
    _placement_review_iteration: int             # 0, 1 — MAX_PLACEMENT_REVIEW_ITERATIONS 추적

    # ── 파이프라인 내부 디버그 기록 ──
    # cap_log: dict                          # [DEPRECATED 2026-04-22 S-8e] legacy _cap_max_count_by_space 이력. allocation_log 로 대체.
    allocation_log: dict                     # object_selection._allocate_eligible 상세 할당 기록 (budget_summary/type_allocation/rejection_details)
    scaled_clearances: dict                  # placement.py가 산출한 obj_type별 초기 시도 clearance ({obj_type: {front, back}})
    reference_meta: dict                     # ref_image_loader가 기록한 검색 메타데이터 (쿼리, 선정 근거, 이미지별 메타)
    ref_analysis: RefAnalysisDict                       # ref_image_analyzer 출력 — 레퍼런스 이미지 Vision 분석 결과
    ref_image_index_map: dict                # {0: "ref_d4da29f6", 1: "ref_3251a67d", ...} — Phase 2 image_id tracking (PR #226 복원)

    # ── ref_point + 이미지 + 동선 (sub-graph 진입 시 outer state 보존 위해 명시) ──
    # LangGraph StateGraph(SmallState) 가 정의 안 된 키를 sub-graph 진입 시 누락시킬 수 있어
    # outer place_service 가 박은 reference_points / reference_images 가 sub-graph 안 design.py 등에서
    # 0 으로 도착하는 회귀 발견 (2026-05-06 진단). 명시적 정의로 보존 확정.
    reference_points: list                   # ref_point_gen / walk_mm 출력 — sub-graph design / placement 가 사용
    reference_images: list                   # ref_image_loader 출력 — sub-graph design 의 LLM 컨텍스트
    reference_images_by_zone: dict           # 존별 레퍼런스 (large 호환)
    layout_examples: list                    # ref_image_loader 의 layouts/ 예시
    main_artery: Optional[LineString]        # walk_mm 산출 메인 동선 — sub-graph 안 placement 가 사용
    entrance_line: Optional[LineString]      # walk_mm 산출
    entrance_buffer: Optional[Polygon]       # walk_mm 산출 — sub-graph 안 placement 의 static_cache

    # ── LargeState 와 정합 — sub-graph 안 노드끼리 통신 + place_service 응답 흐름 보존 ──
    # 2026-05-06 전수 추가: large 와 small 양쪽 sub-graph 가 사용하는 키 SmallState 에도 명시.
    # 누락 시 LangGraph state reduce 에서 outer 값 / sub-graph 안 노드 출력이 누락 위험.
    user_design_concept: Optional[str]               # design 입력
    locked_objects: list                              # 재배치 모드 — sub-graph 안 design 이 받음
    user_project_id: Optional[int]                    # Java handoff (ref_image_loader)
    floor_detection_id: Optional[int]                 # Java handoff (concept_area)
    analyzer_status: Optional[str]                    # ref_image_analyzer 출력
    analyzer_skip_reason: Optional[str]               # ref_image_analyzer 출력
    design_fallback_reason: Optional[str]             # design 노드 fallback 사유
    intent_parse_error: Optional[str]                 # intent_parser LLM 실패 사유
    intent_parse_fallback_reason: Optional[str]       # intent_parser fallback 사유
    placed_partitions: list                           # partition_placement → placement 전달
    ref_quality_score: Optional[float]                # 응답
    ref_trace: dict                                   # ref_image 추적 디버그
    token_usage_summary: dict                         # invoke wrapper 토큰 결과 (Java INSERT)
    _no_fallback: Optional[bool]                      # early return 분기에서 fallback skip 신호
    _original_resolved_intents: list                  # intent_processor 보존 — 최종 실패 시 사용자 매핑용
    _scale_type: Optional[str]                        # "small" / "large" — handle_place 분기 결과 (graph 안 dropped 방지)

    # ── 배치 결과 ──
    placed_objects: list
    placed_raw: list
    failed_objects: list
    placement_log: list
    sub_path: list                            # 부동선 좌표 [[x_mm, y_mm], ...] (#116, F-8). 부재 시 빈 list

    # ── 검증 ──
    verification: dict

    # ── fallback ──
    fallback_round: int

    # ── 사용자 요구사항 / 인텐트 ──
    user_requirements: Optional[str]         # 자연어 배치 요구사항
    resolved_intents: list                   # intent_parser 출력 (ResolvedIntent 직렬화)

    # ── 배치 전략 (strategy resolver 출력) ──
    placement_strategy: Optional[str]        # ADD_ONLY / RESIZE_ONLY / RESIZE_AND_ADD / PARTIAL_REORIENT / FULL_RELAYOUT / NOOP
    global_direction_hint: Optional[str]     # FULL_RELAYOUT 시 모든 design_intent에 적용할 방향
    dimension_overrides: dict                # {object_type: {width_mm, depth_mm}} — resize 시 obj_map 덮어씌움
