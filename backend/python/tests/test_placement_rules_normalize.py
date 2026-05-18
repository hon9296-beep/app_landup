"""
#472 b-3 + e — placement_rules 정규화 (label 보존 + 합산 → max) 단위 테스트.

이슈: PR #376 머지 후 5-1 라이브 dump 두 비대화:
- 13:39 캐릭터 IP — 자유 명명 (mooni_figure 등 6종) 매뉴얼 → 합산 로직으로 1 record
  max_count=6 → 캐릭터 명명 정보 손실 + figures 보정 중복.
- 13:35 뷰티 — consultation_desk(2) + consultation_table(1) 변형 명명 → 합산 max_count=3 폭증.

설계 원칙 (5-1 사용자 인사이트 후 정정):
- 매뉴얼 자유 명명 → std_id 매핑 책임은 LLM (BRAND_TOOL.object_type description 강화).
  코드 alias 누적 / 패턴 매칭 폐기 — OBJECT_STANDARDS SSOT 유지.
- 본 테스트는 LLM 이 정상 매핑한 후 input (object_type=std_id, name=raw 명명) 가정.

해결 (b-3 + e):
- raw 명명 → label 필드 보존 (frontend 표시 + 개체 분리 키)
- 같은 (std_id, label) 충돌 시 합산 → max
- 다른 label 은 별도 record 유지 (mooni / stella / ... 6종 보존)
"""
from app.nodes_small.reference import _normalize_placement_rules, BrandRulesResult


# ── b-3: raw 명명 → label 보존 ──────────────────────────────────────


def test_b3_raw_name_preserved_in_label():
    """LLM 이 mooni_figure → object_type=character_bbox + name=mooni_figure 로 매핑한 input.
    label = name (raw 명명) 보존."""
    rules = [{"object_type": "character_bbox", "name": "mooni_figure"}]
    norm = _normalize_placement_rules(rules)
    assert len(norm) == 1
    assert norm[0]["object_type"] == "character_bbox"
    assert norm[0]["label"] == "mooni_figure"


def test_b3_label_falls_back_to_object_type_when_name_missing():
    """LLM 이 name 안 넘기면 label = object_type (std_id) — frontend fallback."""
    rules = [{"object_type": "counter"}]
    norm = _normalize_placement_rules(rules)
    assert norm[0]["label"] == "counter"


def test_b3_free_naming_six_characters_preserved():
    """캐릭터 IP 6종 자유 명명 — LLM 이 std_id=character_bbox + name 다르게 매핑.
    label 다름 → 6 record 별도 유지."""
    rules = [
        {"object_type": "character_bbox", "name": "mooni_figure"},
        {"object_type": "character_bbox", "name": "stella_figure"},
        {"object_type": "character_bbox", "name": "popo_figure"},
        {"object_type": "character_bbox", "name": "kiro_figure"},
        {"object_type": "character_bbox", "name": "nox_figure"},
        {"object_type": "character_bbox", "name": "mooni_figure_photo"},
    ]
    norm = _normalize_placement_rules(rules, brand_category="캐릭터 IP")
    assert len(norm) == 6
    labels = {r["label"] for r in norm}
    assert labels == {
        "mooni_figure",
        "stella_figure",
        "popo_figure",
        "kiro_figure",
        "nox_figure",
        "mooni_figure_photo",
    }
    # 모두 std_id 동일
    assert all(r["object_type"] == "character_bbox" for r in norm)


# ── e: max_count 정책 (합산 → max) ──────────────────────────────────


def test_e_same_label_uses_max_not_sum():
    """동일 (std_id, label) 두 번 → max_count 합산 X, max 적용."""
    rules = [
        {"object_type": "consultation_desk", "max_count": 2},
        {"object_type": "consultation_desk", "max_count": 1},
    ]
    norm = _normalize_placement_rules(rules)
    assert len(norm) == 1
    assert norm[0]["max_count"] == 2


def test_e_variant_naming_kept_as_separate_records():
    """LLM 이 consultation_desk + consultation_table → 둘 다 std_id=consultation_desk 매핑,
    name 다름 (변형 명명) → label 다름 → 별도 record 유지 (합산 X)."""
    rules = [
        {"object_type": "consultation_desk", "name": "consultation_desk", "max_count": 2},
        {"object_type": "consultation_desk", "name": "consultation_table", "max_count": 1},
    ]
    norm = _normalize_placement_rules(rules)
    assert len(norm) == 2
    labels = {r["label"] for r in norm}
    assert labels == {"consultation_desk", "consultation_table"}
    # 합산 X (max_count 둘 다 그대로 유지)
    counts = sorted(r["max_count"] for r in norm)
    assert counts == [1, 2]


def test_e_no_summation_for_three_duplicates():
    """동일 label 3회 — max_count 1, 3, 2 → 결과 max=3, 합산 6 X."""
    rules = [
        {"object_type": "counter", "max_count": 1},
        {"object_type": "counter", "max_count": 3},
        {"object_type": "counter", "max_count": 2},
    ]
    norm = _normalize_placement_rules(rules)
    assert len(norm) == 1
    assert norm[0]["max_count"] == 3


# ── character_bbox figures 보정 — label 분리 정합성 ────────────────────


def test_character_bbox_correction_skipped_for_named_figures():
    """6 자유 명명 (label 분리됨) → figures 보정 skip 정합성 검증.

    합산 로직 시절: 1 record max_count=6.
    b-3 후: 6 record 각 max_count=1, figures 보정은 label 미명시일 때만 작동 (reference.py 후처리).
    여기서는 normalize 후 label 이 std_id 와 다른지만 검증 (보정 대상 X 의 전제 조건)."""
    rules = [
        {"object_type": "character_bbox", "name": "mooni_figure"},
        {"object_type": "character_bbox", "name": "stella_figure"},
        {"object_type": "character_bbox", "name": "popo_figure"},
        {"object_type": "character_bbox", "name": "kiro_figure"},
        {"object_type": "character_bbox", "name": "nox_figure"},
        {"object_type": "character_bbox", "name": "mooni_figure_photo"},
    ]
    norm = _normalize_placement_rules(rules, brand_category="캐릭터 IP")
    assert len(norm) == 6
    for r in norm:
        # label 이 std_id ("character_bbox") 와 다른 자유 명명 → figures 보정 대상 X
        assert r["label"] != "character_bbox"


def test_character_bbox_correction_applied_for_generic_label():
    """매뉴얼이 character_bbox 1개만 명시 — 자유 명명 없음 → figures 보정 작동 가정.

    normalize 만 검증: label = "character_bbox" 으로 떨어져야 후속 보정 진입."""
    rules = [{"object_type": "character_bbox"}]
    norm = _normalize_placement_rules(rules, brand_category="캐릭터 IP")
    assert len(norm) == 1
    assert norm[0]["label"] == "character_bbox"


# ── 5-1 라이브 케이스 시뮬레이션 ─────────────────────────────────────


def test_live_2026_05_01_13_35_beauty_consultation_no_inflation():
    """5-1 13:35 뷰티 라이브 케이스 — LLM 이 std_id 매핑 + name 분리 후 의도 보존."""
    rules = [
        {"object_type": "consultation_desk", "name": "consultation_desk", "max_count": 2},
        {"object_type": "consultation_desk", "name": "consultation_table", "max_count": 1},
    ]
    norm = _normalize_placement_rules(rules, brand_category="뷰티·코스메틱")
    # 합산 로직이었다면 1 record max_count=3 폭증. b-3 + e 적용 후 2 record 별도 유지.
    total_eligible = sum(r["max_count"] for r in norm)
    assert total_eligible == 3  # 매뉴얼 의도 그대로 (2 + 1, 합산 X)
    assert len(norm) == 2  # 별도 record


def test_live_2026_05_01_13_39_character_six_preserved():
    """5-1 13:39 캐릭터 IP 라이브 — LLM 이 6 자유 명명 → std_id=character_bbox + name 분리 후 보존."""
    rules = [
        {"object_type": "character_bbox", "name": f"{name}_figure", "max_count": 1}
        for name in ("mooni", "stella", "popo", "kiro", "nox")
    ] + [{"object_type": "character_bbox", "name": "mooni_figure_photo", "max_count": 1}]
    norm = _normalize_placement_rules(rules, brand_category="캐릭터 IP")
    assert len(norm) == 6
    labels = {r["label"] for r in norm}
    assert labels == {
        "mooni_figure",
        "stella_figure",
        "popo_figure",
        "kiro_figure",
        "nox_figure",
        "mooni_figure_photo",
    }
    # 합산 로직이었다면 1 record max_count=6 → label 정보 손실. b-3 후 각 1개씩 보존.
    for r in norm:
        assert r["max_count"] == 1


# ── BrandRulesResult 통과 검증 (label 추가가 schema 깨지 않음) ──────────


def test_brand_rules_result_accepts_label_field():
    """기존 BrandRulesResult 가 label 추가된 rule 도 통과."""
    rules = [
        {"object_type": "character_bbox", "name": "mooni_figure", "label": "mooni_figure"},
        {"object_type": "character_bbox", "name": "stella_figure", "label": "stella_figure"},
    ]
    res = BrandRulesResult(brand_category="캐릭터 IP", placement_rules=rules)
    assert res.brand_category == "캐릭터 IP"
    assert len(res.placement_rules) == 2
