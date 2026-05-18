"""agent_graph 의 conditional_edges 함수들.

각 reviewer / verify 후 분기 boolean 만 결정.
재시도 한도 / 수렴 검출 등은 reviewer 노드 자체 책임 (state 의 *_status / *_iteration 키 참조).

진규님 의도: 분기 조건만 graph 안에 격리 — agent_graph 만 보면 흐름 즉시 파악.
"""
from __future__ import annotations

from langgraph.graph import END

# 한도 상수 — reviewer 노드 자체 정의에서 import (single source of truth)
from app.nodes_small.design_reviewer import MAX_REVIEW_ITERATIONS as _DESIGN_MAX
from app.nodes_small.placement_reviewer import MAX_PLACEMENT_REVIEW_ITERATIONS as _PLACEMENT_MAX
from app.nodes_small.pathing_validator import MAX_PATHING_REVIEW_ITERATIONS as _PATHING_MAX


def route_after_design_reviewer(state: dict) -> str:
    """design_reviewer 후 분기.

    pass / 수렴 / 한도 초과 → 다음 단계 (partition_placement)
    reject + 미수렴 + iter < MAX → design 재시도
    skipped (kill switch) → partition_placement
    """
    status = state.get("reviewer_status")
    if status in ("pass", "skipped"):
        return "partition_placement"
    if state.get("_review_similarity_converged"):
        return "partition_placement"
    iter_count = state.get("_review_iteration", 0)
    if iter_count >= _DESIGN_MAX:
        return "partition_placement"
    return "design"


def route_after_verify(state: dict) -> str:
    """verify 후 분기 (fallback loop / placement_reviewer 진입).

    failed_objects 있고 fallback round < 2 → fallback loop
    failed 0 또는 round 한도 → placement_reviewer
    """
    failed = state.get("failed_objects") or []
    fallback_round = state.get("fallback_round", 0)
    if failed and fallback_round < 2:
        return "failure_classifier"
    return "placement_reviewer"


def route_after_placement_reviewer(state: dict) -> str:
    """placement_reviewer 후 분기 (1-3 #533 C1: pass → pathing_validator).

    pass / skipped / 한도 초과 → pathing_validator (동선 검증)
    reject + iter < MAX → design 재시도 (slot 양보 hint 가 _placement_reviewer_feedback 에 박힘)
    """
    status = state.get("placement_reviewer_status")
    if status in ("pass", "skipped"):
        return "pathing_validator"
    iter_count = state.get("_placement_review_iteration", 0)
    if iter_count >= _PLACEMENT_MAX:
        return "pathing_validator"
    return "design"


def route_after_pathing_validator(state: dict) -> str:
    """pathing_validator 후 분기 (1-3 #533 C1).

    pass (trapped 0) → END
    reject (trapped > 0) + iter < MAX → design 재시도 (trapped hint inject)
    한도 초과 → END (warning, 부분 배치 통과)
    """
    status = state.get("_pathing_validator_status")
    if status == "pass":
        return END
    iter_count = state.get("_pathing_review_iteration", 0)
    if iter_count >= _PATHING_MAX:
        return END
    return "design"
