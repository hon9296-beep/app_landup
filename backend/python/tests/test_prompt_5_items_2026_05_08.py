"""
2026-05-08 진규님 명시 5개 항목 prompt 추가 검증.

1. 가벽 자율 drop 허용 + 분리 의도 + obj 가벽 부착 (코드 준비됨 명시)
2. 그래픽 월 = 가벽+포토존 / 판넬 포토존 분리 / drop 방지
3. 면적 3-tier (0-20평 벽 위주 / 20-40평 ref+아일랜드 / 40-50평 조화)
4. 화장실 근처 고객 체류 obj 기피 (AP-003 별도 코드 — 본 파일은 prompt 만)
5. 의미 유사 cluster LLM 자율 판단

회귀 차단 (AP-303 manual_label phrase 잔존) 동시 검증.
"""
from app.nodes_small.prompts.design import DESIGN_SYSTEM_TEMPLATE


# ── 1번: 가벽 자율 drop / 부착 코드 준비됨 ────────────────────


def test_prompt_partition_autonomous_drop():
    """가벽 자율 drop 허용 명시 — 매뉴얼 강제 X."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "가벽 자율 운영 원칙" in template or "자율 제거 허용" in template
    assert "passive omit" in template


def test_prompt_partition_separation_intent():
    """가벽 분리 의도 명시 필수."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "분리 의도" in template
    assert "어떤 zone 과 어떤 zone" in template or "상담석 zone" in template


def test_prompt_partition_attachment_code_ready():
    """obj 가벽 부착 코드 준비됨 명시 (pair_rules join)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "코드 준비됨" in template
    assert "pair_rules" in template
    assert "edge-to-edge" in template


def test_prompt_wall_attachment_priority():
    """외벽 1순위 / 가벽 2순위 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "외벽 부착이 default" in template or "1순위 — 도면의 외벽" in template


# ── 2번: 그래픽 월 + 판넬 포토존 분리 ──────────────────────────


def test_prompt_graphic_wall_concept():
    """그래픽 월 = 가벽+포토존 동시 역할 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "그래픽 월" in template
    assert "공간 분리 역할 + 포토존" in template or "포토존의 시각 앵커 역할을 동시" in template


def test_prompt_no_force_photo_wall_when_graphic():
    """그래픽 월 의도면 photo_wall 강제 배치 X."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "photo_wall 강제 배치 X" in template
    assert "graphic_face" in template


def test_prompt_panel_photo_separation():
    """판넬 조립 포토존은 photo_wall obj 별도 분리."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "판넬 조립 포토존" in template
    assert "photo_wall obj 별도" in template


def test_prompt_photo_wall_drop_prevention():
    """photo_wall drop 방지 룰 — partition 양보."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "photo_wall drop 방지 룰" in template
    assert "양보" in template


# ── 3번: 면적 3-tier ────────────────────────────────────────


def test_prompt_area_tier_small():
    """0~20평 벽 위주 (기존)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "소형 < 20평" in template
    assert "벽 위주 배치 절대 우선" in template


def test_prompt_area_tier_medium_1():
    """20~40평 ref + 아일랜드 시작."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "20~40평" in template
    assert "ref 이미지 적극" in template or "ref 이미지" in template
    assert "아일랜드" in template


def test_prompt_area_tier_medium_2():
    """40~50평 벽 + 아일랜드 조화."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "40~50평" in template
    assert "조화" in template or "균형" in template


# ── 4번: 화장실 근처 prompt ──────────────────────────────


def test_prompt_toilet_proximity_rule():
    """화장실 근처 고객 체류 obj 기피."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "화장실 근처 배치 원칙" in template
    assert "고객 체류 시간" in template or "체류 시간 긴 obj" in template


def test_prompt_toilet_forbidden_targets():
    """화장실 근처 금지 대상 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "AP-003" in template
    # 4 targets
    assert "counter" in template
    assert "kiosk" in template
    assert "consultation_desk" in template
    assert "test_bar" in template


def test_prompt_toilet_allowed_targets():
    """화장실 근처 허용 obj (저 value)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "허용 대상" in template
    assert "display_table" in template or "보조 테이블" in template


# ── 5번: cluster LLM 자율 판단 ─────────────────────────


def test_prompt_cluster_autonomous_judgment():
    """LLM 자율 cluster 판단 (의미 유사성 기반)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "LLM 자율 판단 cluster" in template
    assert "의미가 매우 유사" in template or "의미 유사성" in template


def test_prompt_cluster_examples():
    """cluster 예시 (응대 라인업 / 진열 시퀀스 / 결제+포장 / 체험+진열)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "응대 라인업" in template or "응대 기물" in template
    assert "결제 + 포장" in template or "결제 후 포장" in template


def test_prompt_cluster_avoidance():
    """cluster 회피 케이스 (의미 분리)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "의미 분리" in template
    assert "shelf_wall + counter" in template


# ── 회귀 차단: AP-303 manual_label phrase 잔존 X ─────────


def test_no_specific_manual_label_phrase_in_prompt():
    """AP-303 회귀 차단 — 구체 매뉴얼 라벨 phrase 가 prompt 에 잔존하면 안 됨."""
    template = DESIGN_SYSTEM_TEMPLATE
    forbidden = ["POS 카운터", "증정품 카운터", "1차 상담", "2차 시연", "신상 진열", "체험용"]
    for phrase in forbidden:
        assert phrase not in template, (
            f"prompt 에 '{phrase}' 잔존 — AP-303 회귀"
        )
