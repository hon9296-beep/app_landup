"""
B-1 (1-3 후속 #535 후속) — design prompt 에 placement 알고리즘 흐름 인지 추가.

진규님 5-7 진단:
  "design LLM 이 좋은 위치 잡아도 ref_point 한번 거치고 slot 순회 당하잖아. 알려주던가 해야지."

회귀: design LLM 이 placement 흐름 모름 → ref_point_id 박으면 그대로 박히는 줄 앎 →
  AP-009 reject 시 photo_wall 옮김 (반대로 priority 낮은 obj 양보해야 함) → 매번 다른 wall 시도 → drop.

fix:
  - DESIGN_SYSTEM_TEMPLATE 에 [placement 알고리즘 흐름 인지] 섹션 추가 (system prompt — 매번 inject)
  - design.py retry_authority 의 [재기획 시 고려] 강화 (재호출 시점만 inject)
  - "fresh 하게" → "처음부터 다시" 한국어 정정
"""
import inspect

from app.nodes_small import design
from app.nodes_small.prompts.design import DESIGN_SYSTEM_TEMPLATE


# ── DESIGN_SYSTEM_TEMPLATE: placement 흐름 인지 섹션 ──────────


def test_system_prompt_has_placement_flow_section():
    """system prompt 에 placement 알고리즘 흐름 인지 섹션 존재."""
    assert "placement 알고리즘 흐름 인지" in DESIGN_SYSTEM_TEMPLATE


def test_system_prompt_explains_ref_point_is_starting_candidate():
    """ref_point_id 가 정답 X 시작 후보임 명시."""
    assert "시작 후보" in DESIGN_SYSTEM_TEMPLATE
    # 정확히 박되 + 자동 탐색 흐름 명시
    assert "자동 탐색" in DESIGN_SYSTEM_TEMPLATE


def test_system_prompt_explains_slot_iteration():
    """slot 순회 → fallback step-down 흐름 명시."""
    assert "slot 후보" in DESIGN_SYSTEM_TEMPLATE
    assert "순회" in DESIGN_SYSTEM_TEMPLATE
    assert "fallback step-down" in DESIGN_SYSTEM_TEMPLATE


def test_system_prompt_explains_priority_order():
    """결정 우선순위 (zone+direction 1순위, ref_point_id 2순위) 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "1순위" in template and "2순위" in template
    # zone / direction 이 의도, ref_point_id 가 시작 후보
    assert "`zone_label` + `direction`" in template


def test_system_prompt_mentions_structural_anchor_boost():
    """structural anchor +1000 가중 명시 — LLM 이 priority 흐름 인지."""
    assert "+1000" in DESIGN_SYSTEM_TEMPLATE
    assert "structural anchor" in DESIGN_SYSTEM_TEMPLATE


def test_system_prompt_mentions_zone_balance_for_fallback_avoidance():
    """좁은 zone 에 obj 폭증 시 fallback step-down 빈발 — zone 분배 균형 강조."""
    assert "zone 분배 균형" in DESIGN_SYSTEM_TEMPLATE


# ── retry_authority 의 [재기획 시 placement 흐름 인지] ─────────


def test_design_py_retry_authority_has_flow_awareness():
    """design.py retry_authority section 에 placement 흐름 인지 강조."""
    src = inspect.getsource(design)
    assert "[재기획 시 placement 흐름 인지]" in src


def test_design_py_retry_explains_step_down_slot_iteration():
    """재기획 시 직전 placed_objects 가 step-down / slot 순회 결과임 명시."""
    src = inspect.getsource(design)
    assert "step-down" in src
    assert "slot 순회" in src


def test_design_py_no_legacy_fresh_phrase():
    """'fresh 하게' 표현 제거 (한국어 prompt 안 영어 단어 회귀 차단)."""
    src = inspect.getsource(design)
    assert "fresh 하게" not in src, (
        "'fresh 하게' 표현 잔존 — 한국어 prompt 안에서 모호. '처음부터' 로 정정 필요."
    )


def test_design_py_uses_korean_chumeobuteo():
    """'처음부터 다시' 한국어 표현 사용."""
    src = inspect.getsource(design)
    assert "처음부터 다시" in src


# ── 룰 충돌 회피 검증 ──────────────────────────────────────


def test_no_conflict_with_ref_point_1to1_rule():
    """기존 'ref_point_id 1개 obj 만 매핑' 룰과 신규 placement 흐름 룰 양립.

    기존 룰 (line 75): "각 ref_point_id 는 1개 obj 만 매핑"
    신규 룰: "ref_point_id 는 시작 후보 — 정확히 박되 placement 가 자동 탐색"

    충돌 X = 둘 다 "ref_point_id 정확히 박는다" 전제 + 신규는 placement 흐름 추가 설명.
    """
    template = DESIGN_SYSTEM_TEMPLATE
    # 기존 룰 잔존
    assert "각 ref_point_id 는 1개 obj 만 매핑" in template
    # 신규 룰 추가
    assert "정확히 박되" in template


def test_system_prompt_mentions_AP_009_in_flow_section():
    """AP-009 reject 와 후보 풀 감소 연결 — drop 위험 강조."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "AP-009" in template
    assert "후보 풀" in template
