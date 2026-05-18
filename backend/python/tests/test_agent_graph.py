"""nodes_small/agent_graph — sub-graph 빌드 + 분기 함수 검증.

진규님 5-5 의도: nodes_small 안에 sub-graph 분리. graph.py 와 무관.
"""
from __future__ import annotations

from langgraph.graph import END

from app.nodes_small.agent_graph import AGENT_GRAPH, build_agent_graph
from app.nodes_small.agent_graph.routes import (
    route_after_design_reviewer,
    route_after_verify,
    route_after_placement_reviewer,
    route_after_pathing_validator,
)


def test_agent_graph_compiles_with_9_nodes():
    """build_agent_graph() 9 노드 등록 — design ~ pathing_validator (1-3 #533 C1)."""
    g = build_agent_graph()
    expected = {
        "design", "design_reviewer", "partition_placement",
        "placement", "verify", "failure_classifier", "fallback",
        "placement_reviewer", "pathing_validator",
    }
    assert set(g.nodes.keys()) == expected


def test_agent_graph_module_level_compiled():
    """AGENT_GRAPH = compile 결과 (1회 컴파일)."""
    from langgraph.graph.state import CompiledStateGraph
    assert isinstance(AGENT_GRAPH, CompiledStateGraph)


# ── route_after_design_reviewer ─────────────────────────────


def test_route_design_reviewer_pass_to_partition():
    state = {"reviewer_status": "pass"}
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_design_reviewer_skipped_to_partition():
    """kill switch 시 reviewer_status='skipped' → partition_placement."""
    state = {"reviewer_status": "skipped"}
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_design_reviewer_reject_iter_low_to_design():
    state = {"reviewer_status": "reject", "_review_iteration": 0}
    assert route_after_design_reviewer(state) == "design"


def test_route_design_reviewer_reject_max_to_partition():
    """iter 한도 도달 시 partition (warning)."""
    state = {"reviewer_status": "reject", "_review_iteration": 99}
    assert route_after_design_reviewer(state) == "partition_placement"


def test_route_design_reviewer_converged_to_partition():
    """수렴 검출 시 partition."""
    state = {
        "reviewer_status": "reject",
        "_review_iteration": 0,
        "_review_similarity_converged": True,
    }
    assert route_after_design_reviewer(state) == "partition_placement"


# ── route_after_verify ───────────────────────────────────────


def test_route_verify_failed_round_low_to_failure_classifier():
    state = {"failed_objects": [{"object_type": "x"}], "fallback_round": 0}
    assert route_after_verify(state) == "failure_classifier"


def test_route_verify_no_failed_to_placement_reviewer():
    state = {"failed_objects": [], "fallback_round": 0}
    assert route_after_verify(state) == "placement_reviewer"


def test_route_verify_failed_round_max_to_placement_reviewer():
    """fallback round 한도 도달 → placement_reviewer (loop 종료)."""
    state = {"failed_objects": [{"object_type": "x"}], "fallback_round": 2}
    assert route_after_verify(state) == "placement_reviewer"


# ── route_after_placement_reviewer ────────────────────────────


def test_route_placement_reviewer_pass_to_pathing():
    """1-3 #533 C1: pass → pathing_validator (END 폐기)."""
    state = {"placement_reviewer_status": "pass"}
    assert route_after_placement_reviewer(state) == "pathing_validator"


def test_route_placement_reviewer_skipped_to_pathing():
    """1-3 #533 C1: skipped → pathing_validator."""
    state = {"placement_reviewer_status": "skipped"}
    assert route_after_placement_reviewer(state) == "pathing_validator"


def test_route_placement_reviewer_reject_iter_low_to_design():
    """reject + iter 미달 → design 재시도 (slot 양보 hint)."""
    state = {"placement_reviewer_status": "reject", "_placement_review_iteration": 0}
    assert route_after_placement_reviewer(state) == "design"


def test_route_placement_reviewer_reject_max_to_pathing():
    """reject + iter 한도 → pathing_validator (warning, 1-3 #533 C1)."""
    state = {"placement_reviewer_status": "reject", "_placement_review_iteration": 99}
    assert route_after_placement_reviewer(state) == "pathing_validator"


# ── route_after_pathing_validator (1-3 #533 C1) ─────────────


def test_route_pathing_pass_to_end():
    """trapped 0 → END."""
    state = {"_pathing_validator_status": "pass"}
    assert route_after_pathing_validator(state) == END


def test_route_pathing_reject_iter_low_to_design():
    """trapped > 0 + iter 미달 → design 재시도 (trapped hint inject)."""
    state = {"_pathing_validator_status": "reject", "_pathing_review_iteration": 0}
    assert route_after_pathing_validator(state) == "design"


def test_route_pathing_reject_max_to_end():
    """trapped > 0 + iter 한도 → END (warning, 부분 통과)."""
    state = {"_pathing_validator_status": "reject", "_pathing_review_iteration": 99}
    assert route_after_pathing_validator(state) == END
