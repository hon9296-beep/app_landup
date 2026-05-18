"""
LangGraph 파이프라인 그래프 -- 규모별 분기 구조.

dead_zone 이후 면적 기준으로 분기:
  - 소·중형 (< 165m², ~50평): nodes_small 경로 (Rendy, slot 룰 기반)
  - 대형·야외 (>= 165m²):     nodes_large 경로 (Shin, ref_point + LLM 자율)

┌─────────────── 비동기 병렬 ───────────────┐
│                                            │
▼                                            ▼
parser/parser_dxf/parser_image     reference (브랜드 규칙)
│                                            │
vision                                       │
│                                            │
dead_zone                                    │
│                                            │
├── route_by_scale ──────────────────────────┤
│                                            │
│  [대형·야외]              [소·중형]        │
│  ref_point_gen            slot_gen          │
│  walk_mm                  (Rendy 경로)     │
│  object_selection              │            │
│  concept_gen                   │            │
│  ref_image_loader              │            │
│  ref_image_analyzer            │            │
│  design                        │            │
│  placement                     │            │
│       │                        │            │
│       └────────┬───────────────┘            │
│                │                            │
└────────────────┴────────────────────────────┘
                 │
               verify ──(실패)──▶ failure_classifier → fallback ─┐
                 │                                                │
                 │◀──────────────────────────────────────────────┘
                 │ (통과)
          pathing_validator
                 │
         ┌───────┴───────┐
         ▼               ▼
    glb_exporter    report_gen
         │               │
         └───────┬───────┘
                 ▼
               [END]
"""
import logging

from langgraph.graph import StateGraph, END

from app.state import LargeState

logger = logging.getLogger(__name__)

# ── 대형·야외 노드 (Shin) ────────────────────────────────────────────
# 2026-05-04: nodes_large 8 sub-folder 분리 — 그룹별 폴더 (a_detect ~ h_output)
from app.nodes_large.a_detect import (
    parser as lg_parser,
    parser_dxf as lg_parser_dxf,
    parser_image as lg_parser_image,
    vision as lg_vision,
)
from app.nodes_large.b_space_data import (
    dead_zone as lg_dead_zone,
    ref_point_gen as lg_ref_point_gen,
    walk_mm as lg_walk_mm,
    pillar_toilet_detect as lg_pillar_toilet_detect,  # 2026-05-05 burning_task 1단계 — Haiku Vision
)
from app.nodes_large.c_brand_area import (
    reference as lg_reference,
    concept_area as lg_concept_area,
    keywords_gen as lg_keywords_gen,
    layout_validator as lg_layout_validator,
    concept_area_fix as lg_concept_area_fix,  # 2026-05-05 TR_TH 트랙 1 — 3노드 패턴 수정 LLM
)
from app.nodes_large.d_intent import (
    intent_parser as lg_intent_parser,
    intent_processor as lg_intent_processor,
)
from app.nodes_large.e_reference_pool import (
    ref_image_loader as lg_ref_image_loader,
    ref_image_analyzer as lg_ref_image_analyzer,
)
from app.nodes_large.f_placement import (
    object_selection as lg_object_selection,
    design as lg_design,
    placement as lg_placement,
    verify as lg_verify,
    design_validator as lg_design_validator,  # 2026-05-06 design 3노드 패턴 — 검증
    design_fix as lg_design_fix,                # 2026-05-06 design 3노드 패턴 — 수정
)
from app.nodes_large.g_fallback import (
    failure_classifier as lg_failure_classifier,
    fallback as lg_fallback,
)
from app.nodes_large.h_output import (
    ref_trace_scorer as lg_ref_trace_scorer,
    pathing_validator as lg_pathing_validator,
    glb_exporter as lg_glb_exporter,
    report_gen as lg_report_gen,
    sub_path as lg_sub_path,
)


# ── 라우터 함수들 ────────────────────────────────────────────────────

def _route_start_large(state: LargeState) -> list[str]:
    """대형·야외: 시작 시 파서(타입별) + reference 병렬 분기."""
    file_type = state.get("file_type", "pdf")
    if file_type == "dxf":
        return ["lg_parser_dxf", "lg_reference"]
    if file_type == "image":
        return ["lg_parser_image", "lg_reference"]
    return ["lg_parser", "lg_reference"]


def _route_after_verify_large(state: LargeState) -> str:
    """대형·야외: 검증 후 재호출 루프 or pathing_validator."""
    failed = state.get("failed_objects") or []
    fallback_round = state.get("fallback_round", 0)
    if failed and fallback_round < 4:
        return "lg_failure_classifier"
    return "lg_ref_trace_scorer"


def _route_after_classifier_large(state: LargeState) -> str:
    """대형·야외: failure_classifier 후 Agent 3 재호출 or 코드 fallback."""
    fallback_round = state.get("fallback_round", 0)
    if fallback_round < 3:
        return "lg_design"
    return "lg_fallback"


# ── 동기화 노드 (병렬 합류점) ─────────────────────────────────────────

def _join_noop(state: dict) -> dict:
    """병렬 브랜치 합류용 no-op 노드."""
    return {}


def _output_join(state: dict) -> dict:
    """출력 병렬 합류용 no-op 노드."""
    return {}


# ── 그래프 빌드 (대형·야외) ──────────────────────────────────────────

def build_large_graph() -> StateGraph:
    """대형·야외 통합 파이프라인 (Shin) — `/api/run` 디버그 entry.

    2026-05-02 graph 랭그래프화 단계 7 (옵션 B) — 두 운영 sub-graph 합성으로 재정의.
    drift 제거: 배치 흐름은 build_place_large_graph 가 단일 진실, 도면 분석 흐름은
    build_space_data_large_graph 가 단일 진실. 여기서는 sub-graph 노드로만 등록.

    구조:
      parser/parser_dxf/parser_image (entry 분기) → vision
        ↓
      space_data_large_subgraph (dead_zone → ref_point_gen → walk_mm)
        + reference (병렬 합류)
        ↓
      place_large_subgraph (concept_area ~ report_gen)
        ↓
      glb_exporter → END
    """
    graph = StateGraph(LargeState)

    # 파서 (3)
    graph.add_node("lg_parser", lg_parser.run)
    graph.add_node("lg_parser_dxf", lg_parser_dxf.run)
    graph.add_node("lg_parser_image", lg_parser_image.run)

    # vision
    graph.add_node("lg_vision", lg_vision.run)

    # 2026-05-05 burning_task 1단계 — 기둥/화장실 검출 (Haiku Vision, vision 다음)
    graph.add_node("lg_pillar_toilet_detect", lg_pillar_toilet_detect.run)

    # 도면 분석 sub-graph (compile 결과 = invocable, LangGraph 노드로 등록 가능)
    graph.add_node("lg_space_data_subgraph", build_space_data_large_graph().compile())

    # 브랜드 규칙
    graph.add_node("lg_reference", lg_reference.run)

    # 합류
    graph.add_node("lg_join", _join_noop)

    # 배치 sub-graph (compile 결과)
    graph.add_node("lg_place_subgraph", build_place_large_graph().compile())

    # 출력
    graph.add_node("lg_glb_exporter", lg_glb_exporter.run)

    # ── 엣지 ──
    graph.set_conditional_entry_point(
        _route_start_large,
        {
            "lg_parser": "lg_parser",
            "lg_parser_dxf": "lg_parser_dxf",
            "lg_parser_image": "lg_parser_image",
            "lg_reference": "lg_reference",
        },
    )

    graph.add_edge("lg_parser", "lg_vision")
    graph.add_edge("lg_parser_dxf", "lg_vision")
    graph.add_edge("lg_parser_image", "lg_vision")

    # vision → pillar_toilet_detect → 도면 분석 sub-graph
    # 2026-05-05 burning_task 1단계 — vision 후 기둥/화장실 검출 추가 (dead_zone 흡수)
    graph.add_edge("lg_vision", "lg_pillar_toilet_detect")
    graph.add_edge("lg_pillar_toilet_detect", "lg_space_data_subgraph")
    graph.add_edge("lg_space_data_subgraph", "lg_join")

    # reference 병렬 합류
    graph.add_edge("lg_reference", "lg_join")

    # join → 배치 sub-graph (concept_area ~ report_gen)
    graph.add_edge("lg_join", "lg_place_subgraph")

    # 출력
    graph.add_edge("lg_place_subgraph", "lg_glb_exporter")
    graph.add_edge("lg_glb_exporter", END)

    return graph


# ── 운영용 sub-graph (2026-05-02 graph 랭그래프화 단계 3, 4) ──────────────
#
# 기존 build_large_graph 는 /api/run 디버그 통합 흐름. 운영은 두 단계 분리:
#   - 도면 분석 (handlers/space_data) → space_data_large_graph
#   - 배치        (place_service:place_large) → place_large_graph
#
# 옵션 B (단계 7) 에서 build_large_graph 자체를 두 sub-graph 합성으로 재정의 예정.

# ── 배치 sub-graph 헬퍼 (early return 분기 setup 노드) ────────────────

def _early_locked_setup(state: dict) -> dict:
    """intent_parse_error + locked → 기존 배치 유지 setup.

    place_service.py:54-71 의 early return 분기 흡수.
    state 갱신: placed_objects=locked, failed_objects=[], design_intents=[],
                ref_quality_score=0.0, _no_fallback=True (verify 후 fallback skip)
    """
    locked = list(state.get("locked_objects") or [])
    state["placed_objects"] = locked
    state["failed_objects"] = []
    state["design_intents"] = []
    state["ref_quality_score"] = 0.0
    state["_no_fallback"] = True
    import logging
    logging.getLogger(__name__).warning(
        f"[place:large] intent_parse_error — 기존 배치 유지: {state.get('intent_parse_error')}"
    )
    return state


def _noop_locked_setup(state: dict) -> dict:
    """NOOP strategy + locked → design/placement 스킵, 기존 유지 setup.

    place_service.py:88-107 의 early return 분기 흡수.
    """
    locked = list(state.get("locked_objects") or [])
    state["placed_objects"] = locked
    state["failed_objects"] = []
    state["design_intents"] = []
    state["ref_quality_score"] = 0.0
    state["_no_fallback"] = True
    import logging
    logging.getLogger(__name__).info(
        f"[place:large] NOOP+locked — design/placement 스킵, {len(locked)}개 유지"
    )
    return state


def _route_after_design_validator(state: dict) -> str:
    """2026-05-06 design 3노드 패턴 — design_validator 후 분기.

    LLM verdict + WARN 개수 직접 세서 강제 결정 (concept_area 의 layout_validator 패턴 동일).
    분기:
      - WARN 0건 → 'pass' (다음 노드 walk_mm)
      - WARN ≥ 1 + retry_count < 2 → 'fix' (lg_design_fix → lg_placement 재호출 → 다시 검증)
      - WARN ≥ 1 + retry_count >= 2 → 'pass' (포기, log warning)
    max_retry 2 회.
    """
    from app.nodes_large.f_placement.prompts.design_validator import DESIGN_VALIDATION_RULES

    result = state.get("design_check") or {}
    retry_count = state.get("design_fix_retry_count") or 0

    warn_keys = [r["key"] for r in DESIGN_VALIDATION_RULES if result.get(r["key"]) == "WARN"]
    warn_count = len(warn_keys)

    if warn_count == 0:
        return "pass"

    if retry_count < 2:
        logger.info(f"[graph] design fix 호출 (retry {retry_count + 1}/2, WARN {warn_count}건: {warn_keys})")
        return "fix"
    else:
        logger.warning(f"[graph] design fix max_retry ({retry_count}) 도달 — 포기, pass 처리 (WARN {warn_count}건 잔존)")
        return "pass"


def _route_after_layout_validator(state: dict) -> str:
    """2026-05-05 TR_TH 트랙 1 — concept_area 3노드 패턴 분기.

    LLM verdict 만 신뢰하지 않고 **WARN 개수 직접 세서 강제 결정** (2026-05-05 갱신):
      - LLM 이 'WARN 가 사소하면 ok' description 받고 1건은 ok 로 판단하던 케이스 방어.
    분기:
      - WARN 0건 → 'pass'
      - WARN ≥ 1 + retry_count < 2 → 'fix'
      - WARN ≥ 1 + retry_count >= 2 → 'pass' (포기, log warning)
    max_retry 2 회.
    """
    from app.nodes_large.c_brand_area.prompts.layout_validator import LAYOUT_VALIDATION_RULES

    result = state.get("concept_area_check") or {}
    retry_count = state.get("concept_area_fix_retry_count") or 0

    # WARN 개수 세기 (LLM verdict 무시, 직접 카운트)
    warn_keys = [r["key"] for r in LAYOUT_VALIDATION_RULES if result.get(r["key"]) == "WARN"]
    warn_count = len(warn_keys)

    if warn_count == 0:
        return "pass"

    if retry_count < 2:
        logger.info(f"[graph] concept_area fix 호출 (retry {retry_count + 1}/2, WARN {warn_count}건: {warn_keys})")
        return "fix"
    else:
        logger.warning(f"[graph] concept_area fix max_retry ({retry_count}) 도달 — 포기, pass 처리 (WARN {warn_count}건 잔존)")
        return "pass"


def _route_after_intent_parser(state: dict) -> str:
    """intent_parser 후 — parse_error + locked + user_requirements → early_locked, 아니면 normal."""
    if (state.get("intent_parse_error")
            and state.get("user_requirements")
            and state.get("locked_objects")):
        return "early_locked"
    return "normal"


def _route_after_intent_processor(state: dict) -> str:
    """intent_processor 후 — NOOP + locked → noop_locked (early), 아니면 normal."""
    if state.get("placement_strategy") == "NOOP" and state.get("locked_objects"):
        return "noop_locked"
    return "normal"


def _route_after_verify_place(state: dict) -> str:
    """verify 후 분기 — early 면 fallback skip + trace skip → pathing 직행.

    2026-05-04: verify blocking 도 fallback 트리거 (사용자 의도 정합 — 동선 차단 시 자동 재배치).
    조건:
    - early (`_no_fallback=True`) → skip_to_pathing (early_locked / noop_locked 분기)
    - (failed_objects 있음 OR verification.blocking 있음) AND fallback_round < 2 → fallback
    - 그 외 → trace (ref_trace_scorer)

    failed_objects = placement 단계 좌표 계산 실패. blocking = verify 단계 동선/룰 검증 실패. 둘 다 재배치 트리거.
    """
    if state.get("_no_fallback"):
        return "skip_to_pathing"
    failed = state.get("failed_objects") or []
    verification = state.get("verification") or {}
    blocking = verification.get("blocking") or []
    fallback_round = state.get("fallback_round", 0)
    if (failed or blocking) and fallback_round < 2:
        return "fallback"
    return "trace"


def _fallback_with_round(state: dict) -> dict:
    """fallback 노드 wrapper — round 카운트 갱신 후 fallback.run 호출.

    place_service.py:132-140 의 fallback loop 의 round 갱신 (loop_i + 1) 흡수.
    2026-05-04: verify blocking 도 트리거 — failed 비었지만 blocking 있으면 그것 처리.
    """
    failed = state.get("failed_objects") or []
    verification = state.get("verification") or {}
    blocking = verification.get("blocking") or []
    if not failed and not blocking:
        return state  # no-op (안전망)
    # blocking 만 있고 failed 비었으면 = verify 동선 차단 케이스. failed_objects 에 blocking 흡수 시도.
    if blocking and not failed:
        # blocking 항목을 failed_objects 형식으로 변환 (failure_classifier 가 처리 가능)
        blocking_as_failed = [
            {"object_type": b.get("object_type", "unknown"), "reason": f"verify blocking: {b.get('rule', 'unknown')}"}
            for b in blocking
        ]
        state["failed_objects"] = blocking_as_failed
    state.update(lg_failure_classifier.run(state))
    current_round = state.get("fallback_round", 0)
    state["fallback_round"] = current_round + 1
    state.update(lg_fallback.run(state))
    return state


def build_space_data_large_graph() -> StateGraph:
    """도면 분석 sub-graph (large) — handlers/space_data large 분기에서 invoke.

    parser/vision 은 sub-graph 외부 (auto_detected 입력으로 이미 처리됨).
    reference 도 외부 (brand_data 입력).

    2026-05-04 변경: walk_mm 을 place sub-graph 로 이동.
    이유: 사용자 의도 흐름 정합 — 배치 후 동선 계산 (배치 전 동선이 ref_point 차단하던 문제 fix).
    """
    graph = StateGraph(LargeState)

    graph.add_node("lg_dead_zone", lg_dead_zone.run)
    graph.add_node("lg_ref_point_gen", lg_ref_point_gen.run)

    graph.set_entry_point("lg_dead_zone")
    graph.add_edge("lg_dead_zone", "lg_ref_point_gen")
    graph.add_edge("lg_ref_point_gen", END)

    return graph


# ── 컴파일 ───────────────────────────────────────────────────────────

def compile_large_graph():
    """대형·야외 그래프 컴파일."""
    return build_large_graph().compile()


def compile_space_data_large_graph():
    """도면 분석 sub-graph 컴파일 (large 운영 entry)."""
    return build_space_data_large_graph().compile()


def build_detect_large_graph() -> StateGraph:
    """detect (도면 vision) sub-graph (large) — file_type 별 parser → vision.

    2026-05-02 단계 1-5 신설. handlers/detect.py 는 매장 분기 전이라 nodes_small 사용 (공통).
    이 sub-graph 는 build_large_graph 디버그용 + nodes_large/parser·vision 의 LangGraph 화.
    nodes_large/parser·vision 은 2026-05-02 small mirror 업그레이드 완료.
    """
    graph = StateGraph(LargeState)

    # 노드 — file_type 별 parser 3개 + vision + pillar_toilet_detect (2026-05-05 burning_task 1단계)
    graph.add_node("lg_parser", lg_parser.run)
    graph.add_node("lg_parser_dxf", lg_parser_dxf.run)
    graph.add_node("lg_parser_image", lg_parser_image.run)
    graph.add_node("lg_vision", lg_vision.run)
    graph.add_node("lg_pillar_toilet_detect", lg_pillar_toilet_detect.run)

    # entry — file_type 별 conditional
    def _route_parser(state: dict) -> str:
        ft = state.get("file_type", "pdf")
        if ft == "dxf":
            return "lg_parser_dxf"
        if ft == "image":
            return "lg_parser_image"
        return "lg_parser"

    graph.set_conditional_entry_point(
        _route_parser,
        {
            "lg_parser": "lg_parser",
            "lg_parser_dxf": "lg_parser_dxf",
            "lg_parser_image": "lg_parser_image",
        },
    )

    # 모든 parser → vision → pillar_toilet_detect → END
    graph.add_edge("lg_parser", "lg_vision")
    graph.add_edge("lg_parser_dxf", "lg_vision")
    graph.add_edge("lg_parser_image", "lg_vision")
    graph.add_edge("lg_vision", "lg_pillar_toilet_detect")
    graph.add_edge("lg_pillar_toilet_detect", END)

    return graph


def compile_detect_large_graph():
    """detect sub-graph 컴파일."""
    return build_detect_large_graph().compile()


def build_place_large_graph() -> StateGraph:
    """배치 sub-graph (large) — place_service:place_large 가 invoke.

    구조:
      concept_area → keywords_gen → intent_parser
        → [early_locked_setup → verify (early)]  (parse_error + locked)
        → intent_processor
            → [noop_locked_setup → verify (early)]  (NOOP + locked)
            → object_selection → ref_image_loader → ref_image_analyzer
              → design → placement → verify
                → [fallback loop: failure_classifier+fallback → verify]  (failed + round<2)
                → ref_trace_scorer
        → pathing_validator → report_gen → END

    early 분기는 _no_fallback=True 박아서 verify 후 fallback/trace skip → pathing 직행.
    """
    graph = StateGraph(LargeState)

    # 노드 등록
    graph.add_node("lg_reference", lg_reference.run)  # 2026-05-03 graph 흡수 (brand 룰 적용)
    graph.add_node("lg_concept_area", lg_concept_area.run)
    graph.add_node("lg_layout_validator", lg_layout_validator.run)  # 2026-05-04 신설
    graph.add_node("lg_concept_area_fix", lg_concept_area_fix.run)  # 2026-05-05 TR_TH 트랙 1 — 수정 LLM (3노드 패턴)
    graph.add_node("lg_keywords_gen", lg_keywords_gen.run)
    graph.add_node("lg_intent_parser", lg_intent_parser.run)
    graph.add_node("lg_early_locked_setup", _early_locked_setup)
    graph.add_node("lg_intent_processor", lg_intent_processor.run)
    graph.add_node("lg_noop_locked_setup", _noop_locked_setup)
    graph.add_node("lg_object_selection", lg_object_selection.run)
    graph.add_node("lg_ref_image_loader", lg_ref_image_loader.run)
    graph.add_node("lg_ref_image_analyzer", lg_ref_image_analyzer.run)
    graph.add_node("lg_design", lg_design.run)
    graph.add_node("lg_placement", lg_placement.run)
    graph.add_node("lg_design_validator", lg_design_validator.run)  # 2026-05-06 design 3노드 패턴 — 검증
    graph.add_node("lg_design_fix", lg_design_fix.run)                # 2026-05-06 design 3노드 패턴 — 수정
    graph.add_node("lg_walk_mm", lg_walk_mm.run)  # 2026-05-04 — b_space_data 에서 이동. 배치 후 동선 계산.
    graph.add_node("lg_sub_path", lg_sub_path.run)  # 2026-05-04 신설 — main_artery 가지 (sub_path) 동선.
    graph.add_node("lg_verify", lg_verify.run)
    graph.add_node("lg_fallback_step", _fallback_with_round)
    graph.add_node("lg_ref_trace_scorer", lg_ref_trace_scorer.run)
    graph.add_node("lg_pathing_validator", lg_pathing_validator.run)
    graph.add_node("lg_report_gen", lg_report_gen.run)

    # entry — reference (brand 룰 적용) 먼저
    graph.set_entry_point("lg_reference")

    # 직선
    graph.add_edge("lg_reference", "lg_concept_area")
    graph.add_edge("lg_concept_area", "lg_layout_validator")  # 2026-05-04 신설

    # 2026-05-05 TR_TH 트랙 1 — concept_area 3노드 패턴 conditional edge.
    #   layout_validator (Haiku) 검증 → verdict 따라 분기:
    #   - 'pass' (verdict='ok' or retry max 도달) → keywords_gen
    #   - 'fix' (verdict='fix_needed' + retry < 2) → concept_area_fix (Sonnet) → 다시 layout_validator (재검증)
    graph.add_conditional_edges(
        "lg_layout_validator",
        _route_after_layout_validator,
        {
            "pass": "lg_keywords_gen",
            "fix": "lg_concept_area_fix",
        },
    )
    graph.add_edge("lg_concept_area_fix", "lg_layout_validator")  # 재검증 loop

    graph.add_edge("lg_keywords_gen", "lg_intent_parser")

    # intent_parser 후 분기 (early_locked / normal)
    graph.add_conditional_edges(
        "lg_intent_parser",
        _route_after_intent_parser,
        {
            "early_locked": "lg_early_locked_setup",
            "normal": "lg_intent_processor",
        },
    )
    graph.add_edge("lg_early_locked_setup", "lg_verify")

    # intent_processor 후 분기 (noop_locked / normal)
    graph.add_conditional_edges(
        "lg_intent_processor",
        _route_after_intent_processor,
        {
            "noop_locked": "lg_noop_locked_setup",
            "normal": "lg_object_selection",
        },
    )
    graph.add_edge("lg_noop_locked_setup", "lg_verify")

    # 일반 배치 흐름
    graph.add_edge("lg_object_selection", "lg_ref_image_loader")
    graph.add_edge("lg_ref_image_loader", "lg_ref_image_analyzer")
    graph.add_edge("lg_ref_image_analyzer", "lg_design")
    graph.add_edge("lg_design", "lg_placement")

    # 2026-05-06 design 3노드 패턴 — placement 후 design_validator 검증.
    #   verdict 따라 분기:
    #   - 'pass' (verdict='ok' or retry max 도달) → walk_mm
    #   - 'fix' (verdict='fix_needed' + retry < 2) → design_fix → placement 재호출 → 다시 design_validator
    graph.add_edge("lg_placement", "lg_design_validator")
    graph.add_conditional_edges(
        "lg_design_validator",
        _route_after_design_validator,
        {
            "pass": "lg_walk_mm",
            "fix": "lg_design_fix",
        },
    )
    graph.add_edge("lg_design_fix", "lg_placement")  # 재호출 cycle (배치 수정)

    # 2026-05-04: 배치 후 동선 계산 (walk_mm 이 main_artery 만들고 sub_path 가 가지 동선 만든 후 verify 가 동선 검증)
    graph.add_edge("lg_walk_mm", "lg_sub_path")
    graph.add_edge("lg_sub_path", "lg_verify")

    # verify 후 분기 (fallback loop / trace / skip_to_pathing)
    graph.add_conditional_edges(
        "lg_verify",
        _route_after_verify_place,
        {
            "fallback": "lg_fallback_step",
            "trace": "lg_ref_trace_scorer",
            "skip_to_pathing": "lg_pathing_validator",
        },
    )
    # 2026-05-04: fallback loop 도 walk_mm 다시 계산 (재배치 결과 따라 동선 갱신)
    graph.add_edge("lg_fallback_step", "lg_walk_mm")  # loop
    graph.add_edge("lg_ref_trace_scorer", "lg_pathing_validator")

    # 출력
    graph.add_edge("lg_pathing_validator", "lg_report_gen")
    graph.add_edge("lg_report_gen", END)

    return graph


def compile_place_large_graph():
    """배치 sub-graph 컴파일 (large 운영 entry)."""
    return build_place_large_graph().compile()
