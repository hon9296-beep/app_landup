"""
1-3 (#533) C1 — pathing_validator sub-graph 진입 검증.

design_reviewer / placement_reviewer 와 동일 패턴 (status / iteration / feedback) 으로
agent_graph 의 9번째 노드. trapped_objects 발생 시 design 재호출 (재기획 권한).

회귀 차단:
- pathing_validator 가 sub-graph 노드로 등록 (place_service 직접 호출 X)
- placement_reviewer pass → pathing_validator 진입 (END 폐기)
- trapped 0 → status=pass / END
- trapped > 0 + iter<MAX → design 재시도 (feedback inject)
- iter>=MAX → END (warning)
- MAX 정책 = 2 (design_reviewer / placement_reviewer 와 일관)
- design.py 가 _pathing_validator_feedback 읽어 prompt 에 inject
"""
import inspect

from shapely.geometry import box

from app.nodes_small import pathing_validator
from app.nodes_small.pathing_validator import (
    MAX_PATHING_REVIEW_ITERATIONS,
    _build_trapped_feedback,
)


# ── 정책 상수 ────────────────────────────────────────────────


def test_max_pathing_iterations_is_1():
    """MAX_PATHING_REVIEW_ITERATIONS = 1 (1-3 후속 #535 D — retry 무용 fix, B4 일관)."""
    assert MAX_PATHING_REVIEW_ITERATIONS == 1


def test_max_pathing_consistent_with_other_reviewers():
    """design_reviewer / placement_reviewer (MAX=1, 1-3 후속 #535 D) 와 일관."""
    from app.nodes_small.design_reviewer import MAX_REVIEW_ITERATIONS
    from app.nodes_small.placement_reviewer import MAX_PLACEMENT_REVIEW_ITERATIONS
    assert MAX_PATHING_REVIEW_ITERATIONS == MAX_REVIEW_ITERATIONS == MAX_PLACEMENT_REVIEW_ITERATIONS


# ── _build_trapped_feedback ─────────────────────────────────


def test_build_trapped_feedback_empty():
    """trapped 0 → 빈 문자열."""
    assert _build_trapped_feedback([], []) == ""


def test_build_trapped_feedback_lists_trapped():
    """trapped obj_type 들이 feedback 에 명시."""
    feedback = _build_trapped_feedback(["photo_wall", "shelf_a"], [])
    assert "photo_wall" in feedback
    assert "shelf_a" in feedback
    assert "접근 불가" in feedback


def test_build_trapped_feedback_includes_retry_authority():
    """진규님 비전 — 재기획 권한 (양보 / 이동 / 띄움) 명시."""
    feedback = _build_trapped_feedback(["photo_wall"], [])
    assert "재기획 권한" in feedback
    assert "양보" in feedback or "이동" in feedback or "띄움" in feedback


def test_build_trapped_feedback_no_coordinate_injection():
    """피드백에 mm 좌표 / 강제 ref_point 명시 X — agent 자율 판단."""
    placed = [
        {"object_type": "counter_a", "zone_label": "zone_1",
         "center_x_mm": 1234, "center_y_mm": 5678},
    ]
    feedback = _build_trapped_feedback(["photo_wall"], placed)
    # 좌표 수치 직접 inject 금지 (zone_label / object_type 만)
    assert "1234" not in feedback
    assert "5678" not in feedback


# ── pathing_validator.run state shape ──────────────────────


def test_run_returns_status_pass_when_no_placed():
    """placed/usable_poly/entrance 없으면 status=pass + iter+1."""
    state = {}
    result = pathing_validator.run(state)
    assert result["_pathing_validator_status"] == "pass"
    assert result["_pathing_validator_feedback"] == ""
    assert result["_pathing_review_iteration"] == 1
    assert result["pathways"] == []
    assert result["trapped_objects"] == []


def test_run_increments_iteration():
    """매 호출마다 _pathing_review_iteration +1 (한도 추적용)."""
    state = {"_pathing_review_iteration": 1}
    result = pathing_validator.run(state)
    assert result["_pathing_review_iteration"] == 2


def test_run_trapped_when_no_grid_nodes():
    """usable_poly 가 너무 좁아 grid 노드 0 → 모든 placed obj trapped."""
    # 1mm 정도 폴리 → 1m grid step 안에 contain 노드 0
    tiny_poly = box(0, 0, 100, 100)
    state = {
        "placed_objects": [
            {"object_type": "counter_a", "center_x_mm": 50, "center_y_mm": 50,
             "width_mm": 600, "depth_mm": 400},
        ],
        "usable_poly": tiny_poly,
        "entrance_mm": (0, 0),
    }
    result = pathing_validator.run(state)
    assert result["_pathing_validator_status"] == "reject"
    assert "counter_a" in result["trapped_objects"]
    assert result["_pathing_validator_feedback"] != ""


def test_run_returns_required_keys():
    """state output schema — 5 keys (필수)."""
    result = pathing_validator.run({})
    expected_keys = {
        "pathways", "trapped_objects",
        "_pathing_validator_status",
        "_pathing_validator_feedback",
        "_pathing_review_iteration",
    }
    assert set(result.keys()) == expected_keys


# ── design.py inject 검증 ───────────────────────────────────


def test_design_py_reads_pathing_feedback():
    """design.py 가 _pathing_validator_feedback 을 prompt 에 주입."""
    from app.nodes_small import design
    src = inspect.getsource(design)
    assert "_pathing_validator_feedback" in src


# ── place_service.py 직접 호출 제거 검증 ────────────────────


def test_place_service_no_main_path_pathing_call():
    """place_service.place_small() 의 main path 에서 pathing_validator.run() 직접 호출 제거.

    early return path (intent_parse_error / NOOP+locked) 의 직접 호출은 유지.
    """
    from app.services import place_service
    src = inspect.getsource(place_service.place_small)
    # main path (sub_path 후 직접 호출) 제거 — sub_path 다음 라인에 pathing_validator.run() 없어야
    # early return path 의 직접 호출 (2개) 만 남음
    pathing_calls = src.count("pathing_validator.run(state)")
    assert pathing_calls == 2, (
        f"main path 직접 호출 제거 안 됨 — pathing_validator.run() {pathing_calls}회 (예상: 2 — early return path 만)"
    )


# ── builder 9 노드 검증 (재차) ───────────────────────────────


def test_builder_includes_pathing_validator_node():
    """build_agent_graph() 결과에 pathing_validator 노드 포함."""
    from app.nodes_small.agent_graph import build_agent_graph
    g = build_agent_graph()
    assert "pathing_validator" in g.nodes
