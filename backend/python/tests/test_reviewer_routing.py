"""
#474 design_reviewer 분기 로직 통합 테스트.

LangGraph 의 conditional edge 분기 로직 검증:
  - reviewer_status="pass" → "partition_placement" (next)
  - reviewer_status="skipped" (kill switch) → "partition_placement"
  - reviewer_status="reject" + iteration < MAX → "design" (retry)
  - iteration >= MAX → "partition_placement" (한도)
  - similarity_converged → "partition_placement" (수렴)

실 LLM 호출 없이 mock state 로 검증.

2026-05-06 1-1: graph.py build_small_graph dead 제거에 따라 `_route_after_reviewer_small`
대신 AGENT_GRAPH 의 `route_after_design_reviewer` 사용. 로직 동일, return 값만 다름.
"""
import pytest

from app.nodes_small.agent_graph.routes import route_after_design_reviewer
from app.nodes_small.design_reviewer import MAX_REVIEW_ITERATIONS


# ── 분기 — pass / skipped → partition_placement ─────────────────────


def test_route_pass_next():
    state = {"reviewer_status": "pass", "_review_iteration": 0}
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_skipped_kill_switch_next():
    state = {"reviewer_status": "skipped", "_review_iteration": 0}
    assert route_after_design_reviewer(state) == "partition_placement"


# ── 분기 — reject + iteration ───────────────────────────────────────


def test_route_reject_iter_0_retry():
    """iteration 0 + reject → design (1회차 재호출 가능)."""
    state = {"reviewer_status": "reject", "_review_iteration": 0}
    assert route_after_design_reviewer(state) == "design"


def test_route_reject_iter_1_at_max():
    """iteration 1 + reject → partition_placement (1-3 후속 #535 D — MAX=1 한도 도달).

    이전 MAX=2 일 땐 design retry, 1-3 후속 D 변경 후 MAX=1 → 첫 reject 도 한도.
    결정적 fix 는 prompt / pair_rules / placement priority.
    """
    state = {"reviewer_status": "reject", "_review_iteration": 1}
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_reject_iter_max_next():
    """iteration MAX 도달 + reject → partition_placement (한도)."""
    state = {"reviewer_status": "reject", "_review_iteration": MAX_REVIEW_ITERATIONS}
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_reject_iter_over_max_next():
    """iteration > MAX → partition_placement (안전 fallback)."""
    state = {"reviewer_status": "reject", "_review_iteration": MAX_REVIEW_ITERATIONS + 1}
    assert route_after_design_reviewer(state) == "partition_placement"


# ── 분기 — similarity_converged ─────────────────────────────────────


def test_route_reject_similarity_converged_next():
    """reject + similarity_converged → partition_placement (designer 수렴)."""
    state = {
        "reviewer_status": "reject",
        "_review_iteration": 1,
        "_review_similarity_converged": True,
    }
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_reject_similarity_not_converged_at_max():
    """reject + similarity_converged=False + iter=1 → partition_placement (D — MAX=1 한도)."""
    state = {
        "reviewer_status": "reject",
        "_review_iteration": 1,
        "_review_similarity_converged": False,
    }
    assert route_after_design_reviewer(state) == "partition_placement"


# ── edge / 누락 ──────────────────────────────────────────────────────


def test_route_missing_status_treated_as_retry():
    """reviewer_status 누락 + iter 0 → design (안전 default)."""
    state = {"_review_iteration": 0}
    assert route_after_design_reviewer(state) == "design"


def test_route_empty_state_retry():
    """빈 state — reviewer_status None / iter default 0 → design."""
    assert route_after_design_reviewer({}) == "design"


# ── design.py retry state 박힘 검증 ──────────────────────────────────


def test_design_retry_state_keys_increment():
    """design.py 의 return path 가 _review_iteration 증가 + prev_design_intents 보존 + _reviewer_feedback 초기화 박는지 검증.

    design.run 직접 호출은 LLM 비용이라 source 패턴 검사로 대체.
    """
    import inspect
    from app.nodes_small import design as design_module
    src = inspect.getsource(design_module)
    # 4 return path 모두 _review_iteration / prev_design_intents 박혔는지
    assert src.count('"_review_iteration":') >= 4, "_review_iteration 박힌 return < 4개"
    assert src.count('"prev_design_intents":') >= 4, "prev_design_intents 박힌 return < 4개"
    assert src.count('"_reviewer_feedback": ""') >= 4, "_reviewer_feedback 초기화 박힌 return < 4개"
    # prompt inject
    assert 'state.get("_reviewer_feedback"' in src, "_reviewer_feedback 받는 코드 없음"


# ── AGENT_GRAPH 무결성 검증 (1-1 후 build_small_graph 대체) ─────────


def test_agent_graph_has_design_reviewer_node():
    """AGENT_GRAPH 에 design_reviewer 노드 등록 + compile 가능."""
    from app.nodes_small.agent_graph import build_agent_graph
    g = build_agent_graph()
    assert "design_reviewer" in g.nodes
    compiled = g.compile()
    assert compiled is not None


def test_agent_graph_route_function_signature():
    """route_after_design_reviewer 함수 존재 + signature."""
    fn = route_after_design_reviewer
    assert callable(fn)
    import inspect
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert params == ["state"]


# ── state.py reviewer 필드 검증 ─────────────────────────────────────


def test_state_has_reviewer_fields():
    """SmallState 에 reviewer 필드 7개 추가 확인."""
    from typing import get_type_hints
    from app.state import SmallState
    hints = get_type_hints(SmallState)
    required = {
        "reviewer_status", "reviewer_violations", "reviewer_feedback",
        "_reviewer_feedback", "_review_iteration",
        "_review_similarity_converged", "prev_design_intents",
    }
    missing = required - set(hints.keys())
    assert not missing, f"누락 필드: {missing}"
