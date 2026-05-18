"""
B1 (1-3 후속) — ref_analysis 활용도 강화 contract 검증.

5-7 라이브에서 design intents 9개 중 ref 인용 1개만 — P 룰 / 카테고리 시퀀스 우선,
ref_analysis 거의 무시. fix:
  1. _build_ref_analysis_text 강화 — 모든 분석 필드 출력 (composition_principle / space_mood 추가)
     + 명령형 강화 ("적극 참고" → "직접 반영 + 인용 강제")
  2. DesignIntent.inspired_by_ref: str 필드 — ref 영감 자유 텍스트 인용
  3. DESIGN_PROMPT_TEMPLATE example JSON 에 inspired_by_ref 예시 + 룰 명시
  4. design_reviewer LLM_REVIEWER_SYSTEM 에 ref 활용도 검증 추가
"""
from app.nodes_small.design import DesignIntent, _build_ref_analysis_text
from app.nodes_small.prompts.design_reviewer import LLM_REVIEWER_SYSTEM


# ── DesignIntent.inspired_by_ref 필드 ──────────────────────────────


def test_design_intent_has_inspired_by_ref_field():
    """DesignIntent pydantic 에 inspired_by_ref: str 필드 추가."""
    fields = DesignIntent.model_fields
    assert "inspired_by_ref" in fields, "DesignIntent.inspired_by_ref 부재"


def test_design_intent_inspired_by_ref_default_empty():
    """default = 빈 문자열 (회귀 차단 — 기존 intent 깨짐 방지)."""
    intent = DesignIntent(object_type="counter")
    assert intent.inspired_by_ref == ""


def test_design_intent_accepts_inspired_text():
    """ref 인용 텍스트 정상 받음."""
    intent = DesignIntent(
        object_type="photo_wall",
        inspired_by_ref="레퍼런스의 'focal_points: 입구 정면 대형 캐릭터' 패턴 반영",
    )
    assert "focal_points" in intent.inspired_by_ref


# ── _build_ref_analysis_text 강화 ──────────────────────────────────


def test_ref_text_empty_when_dict_empty():
    """ref_analysis 비어있으면 빈 문자열 (회귀)."""
    assert _build_ref_analysis_text({}) == ""


def test_ref_text_includes_composition_principle():
    """B1 신규: composition_principle 필드 출력."""
    ref = {"composition_principle": "비대칭 분산 구성"}
    text = _build_ref_analysis_text(ref)
    assert "비대칭 분산 구성" in text
    assert "composition_principle" in text  # 키 명시 확인


def test_ref_text_includes_space_mood():
    """B1 신규: space_mood 필드 출력 (이전엔 누락)."""
    ref = {"space_mood": "클린하고 모던한 분위기"}
    text = _build_ref_analysis_text(ref)
    assert "클린하고 모던한 분위기" in text
    assert "space_mood" in text


def test_ref_text_command_strengthened():
    """B1: 명령형 강화 — 단순 '참고' 가 아닌 '직접 반영' / '인용 강제'."""
    ref = {"layout_patterns": ["패턴1"]}
    text = _build_ref_analysis_text(ref)
    # 명령형 marker
    assert "직접 반영" in text
    # 강제 룰 섹션
    assert "강제 룰" in text or "강제" in text
    # 인용 권장 / 강제
    assert "인용" in text


def test_ref_text_priority_over_p_rules():
    """B1: ref 가 P 룰과 동등 또는 더 높은 우선순위 명시."""
    ref = {"layout_patterns": ["패턴1"]}
    text = _build_ref_analysis_text(ref)
    # P 룰 또는 R 룰과의 우선순위 비교 명시
    assert "P1~P4" in text or "R 룰" in text or "우선순위" in text


def test_ref_text_inspired_by_ref_intent_link():
    """B1: 각 intent 의 placed_because 또는 inspired_by_ref 에 인용 강제 명시."""
    ref = {"focal_points": ["포컬1"]}
    text = _build_ref_analysis_text(ref)
    # placed_because / inspired_by_ref 와 ref_analysis 간 연결 명시
    assert "placed_because" in text or "inspired_by_ref" in text or "각 design intent" in text


def test_ref_text_includes_all_analysis_fields_when_provided():
    """모든 ref 분석 필드 (8 종) 출력 가능."""
    ref = {
        "layout_patterns": ["패턴1"],
        "partition_usage": ["가벽1"],
        "focal_points": ["포컬1"],
        "flow_description": "동선",
        "density_impression": "밀도",
        "composition_principle": "구성",
        "space_mood": "분위기",
        "design_highlights": ["하이라이트1"],
    }
    text = _build_ref_analysis_text(ref)
    for field_value in ["패턴1", "가벽1", "포컬1", "동선", "밀도", "구성", "분위기", "하이라이트1"]:
        assert field_value in text, f"ref text 에 '{field_value}' 누락"


# ── design_reviewer LLM_REVIEWER_SYSTEM ──────────────────────────


def test_reviewer_system_includes_ref_activation_check():
    """B1: LLM_REVIEWER_SYSTEM 에 ref 활용도 검증 룰 추가."""
    assert "inspired_by_ref" in LLM_REVIEWER_SYSTEM
    assert "ref 활용" in LLM_REVIEWER_SYSTEM or "ref_analysis" in LLM_REVIEWER_SYSTEM


def test_reviewer_system_warns_on_low_ref_usage():
    """절반 이상 intent 에 inspired_by_ref 빈 값 = warning 트리거 명시."""
    # "절반 이상" 또는 "대부분" 같은 임계 표현
    has_threshold = (
        "절반 이상" in LLM_REVIEWER_SYSTEM
        or "대부분" in LLM_REVIEWER_SYSTEM
        or "활용 부족" in LLM_REVIEWER_SYSTEM
    )
    assert has_threshold, "ref 활용 부족 임계 표현 부재"


def test_reviewer_system_skips_check_when_ref_empty():
    """ref_analysis 자체 empty (loader fail) 시 검증 스킵 — over-strict 회피."""
    assert "스킵" in LLM_REVIEWER_SYSTEM or "skip" in LLM_REVIEWER_SYSTEM.lower() or "empty" in LLM_REVIEWER_SYSTEM.lower()
