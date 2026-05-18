"""
#474 design_reviewer.py 통합 테스트.

run(state) 시나리오:
  1. kill switch (env var false) → reviewer_status="skipped"
  2. 정상 intents (python 위반 X, LLM 미호출) → "pass"
  3. blocking 위반 다수 → "reject" + feedback
  4. warning 만 → "pass" (logger.warning)
  5. 유사도 95%+ 수렴 검출 → similarity_converged=True
  6. graceful — python validator exception → skip 처리
  7. graceful — LLM 호출 실패 (API key 없음) → python 결과만 사용
"""
import os
import pytest
from shapely.geometry import LineString, Polygon

from app.nodes_small.design_reviewer import (
    run,
    _flag_enabled,
    _merge_violations,
    _build_combined_feedback,
    MAX_REVIEW_ITERATIONS,
    SIMILARITY_THRESHOLD,
)


def _build_state(**overrides):
    """공통 mock state — anti_patterns 테스트와 동일 구조."""
    base = {
        "entrance_mm": (5000, 1000),
        "usable_poly": Polygon([(0, 0), (10000, 0), (10000, 10000), (0, 10000)]),
        "reference_points": [
            # 1-3 #533 후속 동기화: ENTRANCE_FRONT_CLEAR_MM 1500→900 하향 반영.
            # wall_1 거리 1000 → 500 (AP-001 위반 유지).
            {"id": "wall_1", "coord": (5000, 1500), "label": "entrance_adjacent", "zone_label": "entrance_zone"},
            {"id": "wall_2", "coord": (5000, 5000), "label": "side_wall", "zone_label": "mid_zone"},
            {"id": "wall_3", "coord": (5000, 8000), "label": "deep_wall", "zone_label": "deep_zone"},
        ],
        "eligible_objects": [
            {"object_type": "partition_wall_I", "width_mm": 2000, "depth_mm": 150, "height_mm": 2400},
            {"object_type": "counter", "width_mm": 1500, "depth_mm": 600, "height_mm": 900},
            {"object_type": "display_table", "width_mm": 1200, "depth_mm": 800, "height_mm": 900},
        ],
        "brand_data": {"brand": {"brand_category": "기타"}, "placement_rules": []},
        "design_intents": [],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _disable_anthropic_key(monkeypatch):
    """모든 테스트에서 ANTHROPIC_API_KEY 제거 — LLM 호출 graceful skip 강제."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ── 기본 동작 ────────────────────────────────────────────────────────


def test_run_kill_switch_skipped(monkeypatch):
    """ANTI_PATTERN_REVIEWER_ENABLED=false → reviewer_status='skipped'."""
    monkeypatch.setenv("ANTI_PATTERN_REVIEWER_ENABLED", "false")
    state = _build_state()
    result = run(state)
    assert result["reviewer_status"] == "skipped"
    assert result["reviewer_violations"] == []
    assert result["reviewer_feedback"] == ""
    assert result["_review_similarity_converged"] is False


def test_run_normal_pass_no_intents():
    """빈 intents + 정상 state → reviewer_status='pass'."""
    state = _build_state()
    result = run(state)
    assert result["reviewer_status"] == "pass"
    assert result["reviewer_feedback"] == ""


def test_run_blocking_reject():
    """입구 정면 가벽 (AP-001 blocking) → reviewer_status='reject' + feedback."""
    state = _build_state(design_intents=[
        {"object_type": "partition_wall_I", "ref_point_id": "wall_1", "zone_label": "entrance_zone"},
    ])
    result = run(state)
    assert result["reviewer_status"] == "reject"
    assert any(v["rule_id"] == "AP-001" for v in result["reviewer_violations"])
    assert "AP-001" in result["reviewer_feedback"]


def test_run_warning_only_pass():
    """warning 만 (shelf_wall + 짝꿍 없음, AP-006) → reviewer_status='pass'."""
    state = _build_state(eligible_objects=[
        {"object_type": "shelf_wall", "width_mm": 1500, "depth_mm": 400, "height_mm": 2400},
    ])
    state["design_intents"] = [
        {"object_type": "shelf_wall", "ref_point_id": "wall_2", "zone_label": "mid_zone"},
    ]
    result = run(state)
    assert result["reviewer_status"] == "pass"
    # warning 은 violations 에 포함되나 reject 안 함
    assert any(v["severity"] == "warning" for v in result["reviewer_violations"])


# ── 유사도 수렴 검출 ────────────────────────────────────────────────


def test_run_similarity_converged():
    """iteration > 0 + prev_intents 동일 → similarity_converged=True."""
    intents = [{"object_type": "counter", "ref_point_id": "wall_2", "zone_label": "mid_zone", "direction": "wall_facing"}]
    state = _build_state(design_intents=intents, prev_design_intents=intents, _review_iteration=1)
    result = run(state)
    assert result["_review_similarity_converged"] is True


def test_run_similarity_not_converged_first_iteration():
    """iteration == 0 → 유사도 체크 X (첫 호출)."""
    intents = [{"object_type": "counter", "ref_point_id": "wall_2", "zone_label": "mid_zone"}]
    state = _build_state(design_intents=intents, prev_design_intents=intents, _review_iteration=0)
    result = run(state)
    assert result["_review_similarity_converged"] is False


def test_run_similarity_below_threshold():
    """iteration > 0 + prev 다른 intents → similarity_converged=False."""
    state = _build_state(
        design_intents=[{"object_type": "counter", "ref_point_id": "wall_2", "zone_label": "mid_zone", "direction": "wall_facing"}],
        prev_design_intents=[{"object_type": "photo_wall", "ref_point_id": "wall_3", "zone_label": "deep_zone", "direction": "wall_facing"}],
        _review_iteration=1,
    )
    result = run(state)
    assert result["_review_similarity_converged"] is False


# ── graceful fallback ──────────────────────────────────────────────


def test_run_graceful_validator_exception(monkeypatch):
    """python validator 전체가 exception 발생해도 graceful — skipped X, pass."""
    from app.nodes_small import design_reviewer

    def _broken_run_validators(intents, state):
        raise RuntimeError("intentional")

    monkeypatch.setattr(design_reviewer, "run_validators", _broken_run_validators)
    state = _build_state()
    result = run(state)
    # python 결과 0 + LLM 미호출 → pass
    assert result["reviewer_status"] == "pass"


def test_run_graceful_no_api_key():
    """ANTHROPIC_API_KEY 없음 → LLM 호출 skip, python 결과만."""
    # _disable_anthropic_key fixture 적용된 상태
    state = _build_state(design_intents=[
        {"object_type": "partition_wall_I", "ref_point_id": "wall_1", "zone_label": "entrance_zone"},
    ])
    result = run(state)
    # python AP-001 만 검출
    assert result["reviewer_status"] == "reject"
    assert any(v["rule_id"] == "AP-001" for v in result["reviewer_violations"])


# ── 헬퍼 함수 단위 ─────────────────────────────────────────────────


def test_merge_violations_python_only():
    py = [{"rule_id": "AP-001", "severity": "blocking", "violation_detail": "x"}]
    merged, fb = _merge_violations(py, None)
    assert len(merged) == 1
    assert fb == ""


def test_merge_violations_llm_added():
    py = []
    llm = {"violations": [{"rule_id": "AP-201", "severity": "warning", "detail": "zone 비현실"}], "feedback": "조정 필요"}
    merged, fb = _merge_violations(py, llm)
    assert len(merged) == 1
    assert merged[0]["rule_id"] == "AP-201"
    assert fb == "조정 필요"


def test_build_combined_feedback_blocking_only():
    blocking = [{"rule_id": "AP-001", "intent_object_type": "partition_wall_I", "intent_zone": "entrance_zone", "violation_detail": "입구 정면 가벽"}]
    text = _build_combined_feedback(blocking, "")
    assert "AP-001" in text


def test_build_combined_feedback_llm_only():
    text = _build_combined_feedback([], "동선 단조 — S자 우회 추가")
    assert "동선" in text
    assert "LLM" in text


def test_build_combined_feedback_both():
    blocking = [{"rule_id": "AP-001", "intent_object_type": "p", "intent_zone": "ez", "violation_detail": "x"}]
    text = _build_combined_feedback(blocking, "동선 단조")
    assert "AP-001" in text
    assert "동선" in text


# ── flag ────────────────────────────────────────────────────────────


def test_flag_enabled_default(monkeypatch):
    monkeypatch.delenv("ANTI_PATTERN_REVIEWER_ENABLED", raising=False)
    assert _flag_enabled() is True


def test_flag_disabled(monkeypatch):
    monkeypatch.setenv("ANTI_PATTERN_REVIEWER_ENABLED", "false")
    assert _flag_enabled() is False


def test_flag_various_truthy(monkeypatch):
    for val in ("true", "1", "yes", "on", "TRUE", "YES"):
        monkeypatch.setenv("ANTI_PATTERN_REVIEWER_ENABLED", val)
        assert _flag_enabled() is True, f"value={val}"


def test_flag_various_falsy(monkeypatch):
    for val in ("false", "0", "no", "off", "anything_else"):
        monkeypatch.setenv("ANTI_PATTERN_REVIEWER_ENABLED", val)
        assert _flag_enabled() is False, f"value={val}"


# ── 상수 검증 ──────────────────────────────────────────────────────


def test_constants():
    # 1-3 후속 (#535 후속 D): MAX 2→1 (retry 무용 fix)
    assert MAX_REVIEW_ITERATIONS == 1
    assert SIMILARITY_THRESHOLD == 0.95
