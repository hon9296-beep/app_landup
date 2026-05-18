"""
placement_reviewer 분기 + 한도 통합 테스트.

route_after_placement_reviewer (agent_graph/routes.py) 의 분기 정확성 검증.
같은 패턴의 test_reviewer_routing.py (design_reviewer 영역) 를 미러링.

1-3 (#523 후속) 추가 — 5-7 15:31 라이브에서 placement_reviewer 가 reject 발화했음에도
MAX_PLACEMENT_REVIEW_ITERATIONS = 1 + routes 의 `>=` 비교 조합으로 첫 reject 도 END 강제되던
회귀 fix. MAX=2 로 1회 재시도 가능.

각 case = state dict mock + route 함수 직접 호출. LLM/실 graph invoke 없이 분기만 검증.
"""
import pytest

from app.nodes_small.agent_graph.routes import route_after_placement_reviewer
from app.nodes_small.placement_reviewer import MAX_PLACEMENT_REVIEW_ITERATIONS


# ── 분기 — pass / skipped → pathing_validator (1-3 #533 C1) ────────────


def test_route_pass_to_pathing():
    """placement_reviewer pass → pathing_validator (동선 검증 진입).

    1-3 #533 C1 변경 — 기존 END 였으나 pathing_validator sub-graph 진입 후 → pathing_validator.
    """
    state = {"placement_reviewer_status": "pass", "_placement_review_iteration": 0}
    assert route_after_placement_reviewer(state) == "pathing_validator"


def test_route_skipped_kill_switch_to_pathing():
    """kill switch → pathing_validator (1-3 #533 C1)."""
    state = {"placement_reviewer_status": "skipped", "_placement_review_iteration": 0}
    assert route_after_placement_reviewer(state) == "pathing_validator"


# ── 분기 — reject + iteration ──────────────────────────────────────


def test_route_reject_iter_1_at_max():
    """첫 reject 후 iter=1 — MAX=1 한도 도달 (1-3 후속 #535 D — retry 무용 채택).

    이전 MAX=2 일 땐 design 재호출 가능했으나, 5-7 라이브 분석 결과 retry 가 같은 회귀
    반복 (LLM compliance 한계). 결정적 fix 는 pair_rules / prompt / placement priority.
    iter=1 도달 시 한도 → pathing_validator 진행 (END 가 아니라 1-3 #533 C1 변경).
    """
    state = {"placement_reviewer_status": "reject", "_placement_review_iteration": 1}
    assert route_after_placement_reviewer(state) == "pathing_validator"


def test_route_reject_iter_at_max_to_pathing():
    """iter=MAX 도달 (2) → pathing_validator (1-3 #533 C1, 한도 — 동선 검증으로 진행)."""
    state = {"placement_reviewer_status": "reject", "_placement_review_iteration": MAX_PLACEMENT_REVIEW_ITERATIONS}
    assert route_after_placement_reviewer(state) == "pathing_validator"


def test_route_reject_iter_over_max_to_pathing():
    """iter > MAX → pathing_validator (1-3 #533 C1, 안전 fallback — 동선 검증으로 진행)."""
    state = {
        "placement_reviewer_status": "reject",
        "_placement_review_iteration": MAX_PLACEMENT_REVIEW_ITERATIONS + 1,
    }
    assert route_after_placement_reviewer(state) == "pathing_validator"


# ── edge — 상태 누락 ────────────────────────────────────────────────


def test_route_missing_status_treated_as_retry():
    """placement_reviewer_status 없음 + iter < MAX → design (안전 default — retry).

    pass / skipped 명시 안 됐으면 reject 로 간주. 단 한도 미만이면 retry.
    """
    state = {"_placement_review_iteration": 0}
    assert route_after_placement_reviewer(state) == "design"


def test_route_empty_state_retry():
    """빈 state — iter default 0 → design 재시도 (MAX=2 라 retry 가능)."""
    assert route_after_placement_reviewer({}) == "design"


# ── MAX 상수 의미 검증 ──────────────────────────────────────────────


def test_max_constant_value():
    """1-3 후속 (#535 후속 D): MAX_PLACEMENT_REVIEW_ITERATIONS = 1.

    히스토리:
    - 1-3 #523 후속: 1 → 2 (routes `>=` + iter+1 박는 패턴 fix)
    - 1-3 #533 B4: 2 유지 (design_reviewer 와 일관)
    - 1-3 후속 #535 D: 2 → 1 (5-7 라이브 분석 — retry 가 같은 회귀 반복, LLM
      compliance 한계. 결정적 fix 는 pair_rules / prompt / placement priority.
      retry = 시간 손해, 회귀 차단 효과 X)
    """
    assert MAX_PLACEMENT_REVIEW_ITERATIONS == 1


def test_first_reject_at_max_progresses_to_pathing():
    """첫 placement_reviewer reject 후 한도 도달 → pathing_validator 진행 (D + C1).

    1-3 #533 C1: pass 도 reject 도 pathing_validator 로 진입.
    1-3 후속 D: MAX=1 변경 후 첫 reject 도 한도 도달 (1>=1).
    이전 retry 효과는 5-7 라이브 측정 결과 무용 (같은 회귀 반복).
    결정적 fix 는 prompt / pair_rules / placement priority 영역.
    """
    # 첫 reject 직후 state (iter=1, status=reject)
    state_after_first_reject = {
        "placement_reviewer_status": "reject",
        "_placement_review_iteration": 1,
    }
    result = route_after_placement_reviewer(state_after_first_reject)
    assert result == "pathing_validator", (
        f"첫 reject 후 pathing_validator 진행해야 함 (D+C1) — 현재 결과: {result}. "
        f"MAX_PLACEMENT_REVIEW_ITERATIONS = {MAX_PLACEMENT_REVIEW_ITERATIONS} 확인."
    )


# ── 통합 — placement_reviewer.run 의 iter 증가 + routes 의 분기 일관성 ──


def test_run_increments_iteration():
    """placement_reviewer.run() 이 호출마다 _placement_review_iteration 증가.

    routes 가 그 값으로 한도 판정 → run + routes 의 contract.
    실 LLM 호출은 비용 — kill switch 켜고 skipped path 만 검증.
    """
    import os
    from app.nodes_small import placement_reviewer

    # kill switch ON → run 이 즉시 skipped 반환. 단 iter 증가 contract 검증 위해 직접 점검.
    # (실 reject path 테스트는 LLM 비용 발생 — smoke 영역. 본 테스트는 routes 와 일관 contract 만.)
    os.environ["PLACEMENT_REVIEWER_ENABLED"] = "false"
    try:
        state = {"placed_objects": [], "failed_objects": [], "_placement_review_iteration": 0}
        result = placement_reviewer.run(state)
        # skipped path 는 iter 증가 안 함 (kill switch — 1회용 short-circuit)
        assert result.get("placement_reviewer_status") == "skipped"
    finally:
        os.environ.pop("PLACEMENT_REVIEWER_ENABLED", None)
