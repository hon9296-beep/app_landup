"""
A1 (1-3 후속, AP-303 prompt 예시 약화) contract 검증.

5-7 12:46 dump 에서 LLM 이 prompt 의 구체 예시 ('POS 카운터' / '1차 상담' / '메인 진열' /
'공간 분할 (zoning)') 를 그대로 복사해 매뉴얼 실제 라벨 무시. 예시가 너무 강하게 inject
되어 LLM 이 매뉴얼 정보보다 prompt 예시를 우선 따르는 회귀.

Fix:
  - 구체 예시 (특정 라벨 / zone 가이드) 제거
  - "매뉴얼 라벨 그대로 복사" / "임의로 새 라벨 만들지 말 것" 가이드 추가
  - 일반론 추측 ('결제용 → deep_zone' 같은) 위반 명시

본 테스트는 prompt 텍스트 contract 만 검증 (LLM 호출 비용 0).
"""
from app.nodes_small.prompts.design import DESIGN_SYSTEM_TEMPLATE


# ── 구체 예시 단어 부재 (A1 핵심 회귀 차단) ──────────────────────────


def test_system_prompt_no_specific_label_examples():
    """A1: DESIGN_SYSTEM_TEMPLATE 에 manual_label 영역 구체 라벨 예시 부재.

    note: '메인 진열대' / '메인 매대' 는 P1/P4 일반 룰 설명에 합법 사용 (manual_label 예시 X).
    여기서는 manual_label 영역에 **잠겨있던 구체 예시 phrase** 만 catch.
    """
    # manual_label 예시로 LLM 이 복사할 위험 있던 phrase (이전 prompt 에 박혀있던 것)
    forbidden_phrases = [
        "POS 카운터",  # counter manual_label 예시
        "증정품 카운터",  # counter manual_label 예시
        "1차 상담",  # consultation manual_label 예시
        "2차 시연",  # consultation manual_label 예시
        "신상 진열",  # shelf manual_label 예시 (메인 진열대는 P1 룰 설명이라 OK)
        "체험용",  # display manual_label 예시
    ]
    for phrase in forbidden_phrases:
        assert phrase not in DESIGN_SYSTEM_TEMPLATE, (
            f"DESIGN_SYSTEM_TEMPLATE 에 manual_label 예시 phrase '{phrase}' 잔존 — "
            f"A1 회귀: LLM 이 prompt 예시 그대로 복사 가능"
        )


def test_system_prompt_has_copy_literal_guidance():
    """A1: '매뉴얼 라벨 그대로 복사' 가이드 존재. AI 가 임의로 새 라벨 만드는 패턴 차단."""
    assert "그대로 복사" in DESIGN_SYSTEM_TEMPLATE
    assert "임의로" in DESIGN_SYSTEM_TEMPLATE
    # "임의로 매뉴얼에 없는 라벨" 또는 "임의로 새 라벨 만들지" 류 표현 존재
    has_literal_warning = (
        "임의로 매뉴얼에 없는" in DESIGN_SYSTEM_TEMPLATE
        or "AI 가 임의로" in DESIGN_SYSTEM_TEMPLATE
        or "임의로 새 라벨" in DESIGN_SYSTEM_TEMPLATE
    )
    assert has_literal_warning, "임의 라벨 생성 차단 가이드 부재"


def test_system_prompt_has_manual_intent_priority():
    """A1: 매뉴얼 작성자 의도 우선 명시 ('일반론 추측 금지' 또는 '매뉴얼 작성자 의도 우선')."""
    has_priority_guidance = (
        "매뉴얼 작성자 의도" in DESIGN_SYSTEM_TEMPLATE
        or "매뉴얼" in DESIGN_SYSTEM_TEMPLATE and "우선" in DESIGN_SYSTEM_TEMPLATE
    )
    assert has_priority_guidance, "매뉴얼 의도 우선 가이드 부재"


# ── _build_manual_label_section contract ──────────────────────────


def test_manual_label_section_no_specific_examples():
    """A1: _build_manual_label_section output 에 구체 예시 (POS 카운터 / 1차 상담 / 메인 진열 등) 부재."""
    from app.nodes_small.design import _build_manual_label_section
    eligible = [
        {"object_type": "counter", "manual_label": "본 매뉴얼 라벨 A", "_from_brand": True},
        {"object_type": "counter", "manual_label": "본 매뉴얼 라벨 B", "_from_brand": True},
    ]
    section = _build_manual_label_section(eligible)
    forbidden = [
        "POS 카운터",
        "증정품 카운터",
        "1차 상담",
        "2차 시연",
        "메인 진열",
        "신상 진열",
        "체험용",
    ]
    for f in forbidden:
        assert f not in section, f"_build_manual_label_section 에 구체 예시 '{f}' 잔존"


def test_manual_label_section_has_copy_literal_principle():
    """_build_manual_label_section 에 '매뉴얼 라벨 그대로 복사' 원칙 존재."""
    from app.nodes_small.design import _build_manual_label_section
    eligible = [
        {"object_type": "counter", "manual_label": "라벨 X", "_from_brand": True},
        {"object_type": "counter", "manual_label": "라벨 Y", "_from_brand": True},
    ]
    section = _build_manual_label_section(eligible)
    assert "그대로" in section
    assert "복사" in section


def test_manual_label_section_warns_against_generic_inference():
    """_build_manual_label_section 에 '일반론 추측 금지' 가이드 존재."""
    from app.nodes_small.design import _build_manual_label_section
    eligible = [
        {"object_type": "counter", "manual_label": "라벨 X", "_from_brand": True},
        {"object_type": "counter", "manual_label": "라벨 Y", "_from_brand": True},
    ]
    section = _build_manual_label_section(eligible)
    has_warning = (
        "일반론" in section
        or "추측하지 말고" in section
        or "추측 금지" in section
    )
    assert has_warning, "일반론 추측 금지 가이드 부재"


def test_manual_label_section_empty_when_single_label():
    """multi-label 아니면 빈 문자열 반환 (회귀 차단 — 사전 동작 유지)."""
    from app.nodes_small.design import _build_manual_label_section
    eligible = [{"object_type": "counter", "manual_label": "라벨 X", "_from_brand": True}]
    assert _build_manual_label_section(eligible) == ""


# ── design_reviewer 의 review section contract ─────────────────────


def test_reviewer_section_no_specific_examples():
    """A1: design_reviewer 의 _build_manual_labels_review_section 도 구체 예시 부재."""
    from app.nodes_small.prompts.design_reviewer import _build_manual_labels_review_section
    state = {
        "brand_data": {
            "placement_rules": [
                {"object_type": "counter", "name": "라벨 A"},
                {"object_type": "counter", "name": "라벨 B"},
            ]
        }
    }
    section = _build_manual_labels_review_section(state)
    forbidden = [
        "POS 카운터",
        "증정품 카운터",
        "1차 상담",
        "2차 시연",
        "메인 진열",
        "신상 진열",
        "체험용",
    ]
    for f in forbidden:
        assert f not in section, f"reviewer section 에 구체 예시 '{f}' 잔존"


def test_reviewer_section_has_4_judgment_criteria():
    """reviewer section 에 4 판정 기준 (분리 / 라벨 글자 그대로 / zone 부합 / 중복 배치) 명시."""
    from app.nodes_small.prompts.design_reviewer import _build_manual_labels_review_section
    state = {
        "brand_data": {
            "placement_rules": [
                {"object_type": "counter", "name": "라벨 A"},
                {"object_type": "counter", "name": "라벨 B"},
            ]
        }
    }
    section = _build_manual_labels_review_section(state)
    # 4 판정 기준 핵심 문구 존재
    assert "별도 intent" in section  # 1. 분리
    assert "글자 그대로" in section or "그대로 일치" in section  # 2. 라벨 일치
    assert "단순 중복 배치" in section or "중복 배치" in section  # 4. 중복 X


def test_reviewer_section_warns_against_generic_inference():
    """reviewer section 에 'generic 추측만으로 분리 = 의도 손실 가능' 명시."""
    from app.nodes_small.prompts.design_reviewer import _build_manual_labels_review_section
    state = {
        "brand_data": {
            "placement_rules": [
                {"object_type": "counter", "name": "라벨 A"},
                {"object_type": "counter", "name": "라벨 B"},
            ]
        }
    }
    section = _build_manual_labels_review_section(state)
    has_warning = (
        "일반론" in section
        or "generic" in section
        or "추측" in section
    )
    assert has_warning, "reviewer section 에 generic 추측 위반 가이드 부재"


def test_reviewer_section_empty_when_no_multi_label():
    """multi-label 부재 시 빈 문자열 (회귀 차단)."""
    from app.nodes_small.prompts.design_reviewer import _build_manual_labels_review_section
    # placement_rules 없음
    assert _build_manual_labels_review_section({}) == ""
    # 라벨 1개만 (multi 아님)
    state = {"brand_data": {"placement_rules": [{"object_type": "counter", "name": "단일 라벨"}]}}
    assert _build_manual_labels_review_section(state) == ""
