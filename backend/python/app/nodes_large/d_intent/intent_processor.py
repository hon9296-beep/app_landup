"""
intent_processor — resolved_intents 처리 + strategy 결정 + apply_* 적용 (large).

graph 랭그래프화 단계 1 (2026-05-02 신설). 기존 place_service.py:place_large_stages 의
wrapper 로직 (line ~74~86) 을 노드로 흡수해 build_place_large_graph 안에 들어가게 함.

호출 위치 (예정): intent_parser → intent_processor → object_selection
- intent_parser 가 사용자 요구 → resolved_intents 변환
- intent_processor 가 strategy 결정 + apply_* 적용
- object_selection 이 eligible_objects 산출

state 입력 키:
  - resolved_intents: list (intent_parser 결과)
  - locked_objects: list | None (재배치 모드 시 기존 배치)
  - brand_data: dict (apply_resize 의 VMD_BOUNDARIES lookup 용)
state 출력 키 갱신:
  - placement_strategy: str (NOOP / FULL_RELAYOUT / PARTIAL_REORIENT / RESIZE_ONLY / RESIZE_AND_ADD / ADD_ONLY)
  - _original_resolved_intents: list (최종 실패 시 사용자 요구 매핑용)
  - resolved_intents: list (apply_* 가 변환한 결과)
  - dimension_overrides: dict (apply_resize 가 채움, 있을 때)
"""
import logging

from app.services.intent_service import (
    apply_removal_intents,
    apply_reorient_intents,
    apply_resize_intents,
    resolve_strategy,
)

logger = logging.getLogger(__name__)


def run(state: dict) -> dict:
    """resolved_intents → strategy 결정 + apply_* 적용. state 갱신 후 반환.

    place_service.py:place_large_stages 의 직렬 wrapper 로직을 그대로 옮김.
    LangGraph 노드 표준 시그니처 (def run(state) -> dict).
    """
    # 1. 처리 전 원본 보존 (최종 실패 시 사용자 요구사항 매핑용)
    state["_original_resolved_intents"] = list(state.get("resolved_intents") or [])

    # 2. removal 처리 (resolved_intents 의 remove action 적용)
    apply_removal_intents(state)

    # 3. strategy 결정 (action 조합 → 파이프라인 전략)
    resolved = state.get("resolved_intents") or []
    strategy = resolve_strategy(resolved)
    state["placement_strategy"] = strategy
    logger.info(
        f"[intent_processor:large] strategy: {strategy}, resolved_intents: {len(resolved)}"
    )

    # 4. strategy 따라 reorient / resize 적용
    if strategy in ("FULL_RELAYOUT", "PARTIAL_REORIENT"):
        apply_reorient_intents(state, strategy)
    if strategy in ("RESIZE_ONLY", "RESIZE_AND_ADD"):
        apply_resize_intents(state)

    return state
