"""
nodes_small/reference.py BrandRulesResult — placement_rules 검증 단위 테스트.

[의미 변천]
- 4-30 (PR #366 c6f3dd9): BrandRulesResult.model_validator 가 minimal 풀 누락 시
  ValueError raise → harness retry → 모두 실패 시 _fallback_brand_defaults() 호출 →
  brand 전체 default 리셋. **잘못된 결합** — placement_rules 검증 실패가 brand_category
  등 다른 LLM 정상 추출분까지 폐기시킴.
- 5-1 (G 옵션): model_validator 제거. brand 응답 LLM 추출분 항상 보존.
  placement_rules 부실은 reference.py 후처리에서 logger.warning 만 발생.

본 테스트는 G 옵션 후의 동작 검증 — 어떤 placement_rules 입력이든 BrandRulesResult
인스턴스 생성 통과. 핵심 풀 누락 시 ValidationError raise 안 함.
"""
import logging

from app.nodes_small.reference import BrandRulesResult, _log_minimal_placement_rules_warning
from app.categories import CATEGORIES_BY_KEY


def _minimal_pool_by_category() -> dict[str, set[str]]:
    """SSOT 의 minimal_placement_rules — 모니터링 메타 (검증 트리거 X)."""
    return {
        cat.key: cat.minimal_placement_rules
        for cat in CATEGORIES_BY_KEY.values()
        if cat.minimal_placement_rules
    }


_MINIMAL_PLACEMENT_RULES_BY_CATEGORY = _minimal_pool_by_category()


# ── 정상 응답: 카테고리별 핵심 풀 충족 → 통과 ──────────────────────────


def test_valid_character_ip_rules_pass():
    """캐릭터 IP — character_bbox 포함 → 통과."""
    rules = [
        {"object_type": "photo_wall"},
        {"object_type": "character_bbox"},
        {"object_type": "display_table"},
    ]
    res = BrandRulesResult(brand_category="캐릭터 IP", placement_rules=rules)
    assert res.brand_category == "캐릭터 IP"
    assert len(res.placement_rules) == 3


def test_valid_fashion_rules_pass():
    """패션 브랜드 — counter 포함 → 통과."""
    rules = [
        {"object_type": "shelf_wall"},
        {"object_type": "display_table"},
        {"object_type": "counter"},
    ]
    res = BrandRulesResult(brand_category="패션 브랜드", placement_rules=rules)
    assert res.brand_category == "패션 브랜드"


def test_valid_fnb_rules_pass():
    rules = [
        {"object_type": "counter"},
        {"object_type": "display_table"},
    ]
    res = BrandRulesResult(brand_category="F&B", placement_rules=rules)
    assert res.brand_category == "F&B"


def test_valid_beauty_rules_pass():
    rules = [
        {"object_type": "shelf_wall"},
        {"object_type": "display_table"},
        {"object_type": "counter"},
    ]
    res = BrandRulesResult(brand_category="뷰티·코스메틱", placement_rules=rules)
    assert res.brand_category == "뷰티·코스메틱"


def test_valid_etc_rules_pass():
    rules = [
        {"object_type": "counter"},
        {"object_type": "display_table"},
    ]
    res = BrandRulesResult(brand_category="기타", placement_rules=rules)
    assert res.brand_category == "기타"


# ── G 옵션 핵심: 부실 응답도 BrandRulesResult 통과 (raise 안 함) ────────


def test_empty_placement_rules_passes_validation():
    """빈 placement_rules — Pydantic 검증 통과 (raise 안 함). 부실은 후처리 logger.warning.

    이전 (PR #366): ValidationError raise → retry → fallback (brand 전체 폐기)
    이후 (G):       Pydantic 통과 → brand_category 등 보존, placement_rules 만 빈 list 유지
    """
    res = BrandRulesResult(brand_category="캐릭터 IP", placement_rules=[])
    assert res.brand_category == "캐릭터 IP"
    assert res.placement_rules == []


def test_partial_placement_rules_passes_validation():
    """5-1 13:04 실제 케이스 — 뷰티 매뉴얼 6개 추출 (display_table 누락) 통과.

    이전 (PR #366): display_table 강제 → retry → fallback → brand_category="기타"
    이후 (G):       매뉴얼 특화 정보 (consultation_desk, test_bar 등) 그대로 보존
    """
    rules = [
        {"object_type": "consultation_desk"},
        {"object_type": "counter"},
        {"object_type": "partition_wall_I"},
        {"object_type": "photo_wall"},
        {"object_type": "shelf_wall"},
        {"object_type": "test_bar"},
    ]
    res = BrandRulesResult(brand_category="뷰티·코스메틱", placement_rules=rules)
    assert res.brand_category == "뷰티·코스메틱"
    assert len(res.placement_rules) == 6
    rule_types = {r["object_type"] for r in res.placement_rules}
    assert "consultation_desk" in rule_types  # 매뉴얼 특화 보존
    assert "test_bar" in rule_types
    assert "partition_wall_I" in rule_types


def test_minimal_pool_definition_consistency():
    """minimal_placement_rules 등록 카테고리 = BRAND_TOOL.brand_category enum 5개 + 등록 추가."""
    expected_categories = {"캐릭터 IP", "패션 브랜드", "F&B", "뷰티·코스메틱", "기타"}
    actual_categories = set(_MINIMAL_PLACEMENT_RULES_BY_CATEGORY.keys())
    assert expected_categories == actual_categories, (
        f"카테고리 불일치 — minimal_placement_rules 가 SSOT 5개 카테고리 모두 cover 필요. "
        f"누락: {expected_categories - actual_categories}, 잉여: {actual_categories - expected_categories}"
    )


# ── 정규화 동작: 자유 명명도 표준 ID 매핑 후 검증 (모니터링용) ──────────


def test_freeform_object_type_passes_through():
    """LLM 이 자유 명명한 object_type 도 BrandRulesResult 통과 (Pydantic 검증 X)."""
    rules = [
        {"object_type": "counter"},
        {"object_type": "display_table"},
        {"object_type": "임의의_이상한_이름"},  # 정규화 안 되는 raw type
    ]
    res = BrandRulesResult(brand_category="기타", placement_rules=rules)
    assert len(res.placement_rules) == 3


def test_invalid_rule_entry_passes_through():
    """placement_rules 항목이 dict 가 아니거나 object_type 누락이어도 통과."""
    rules = [
        {"object_type": "counter"},
        {"name": "anonymous"},
        "not a dict",
    ]
    res = BrandRulesResult(brand_category="기타", placement_rules=rules)
    assert len(res.placement_rules) == 3


# ── reference.py 후처리 logger.warning 검증 ────────────────────────────
# Pydantic 검증은 통과 — 부실 검사는 _run_brand_agent 의 후처리에서. 그 함수는 LLM
# 호출 의존이라 직접 테스트 어려움 → 간접: BrandRulesResult 객체가 minimal 누락 응답을
# raise 없이 받아들인다 + 카테고리별 minimal 정의 자체는 SSOT 에 보존된다 검증.


def test_minimal_pool_preserved_for_monitoring():
    """minimal_placement_rules 가 SSOT 에 보존되어 logger.warning 발생 기준으로 사용 가능."""
    for cat_key in ["캐릭터 IP", "패션 브랜드", "F&B", "뷰티·코스메틱", "기타"]:
        cat = CATEGORIES_BY_KEY[cat_key]
        # 각 카테고리에 1개씩 등록되어 있어야 후처리에서 logger.warning 발생 검사 가능
        assert cat.minimal_placement_rules, (
            f"{cat_key} minimal_placement_rules 비어 있음 — 모니터링 비활성. "
            f"SSOT 등록 필요 (검증 X, 부실 응답 패턴 추적용)."
        )


def test_partial_brand_response_preservation():
    """LLM 이 brand_category + clearspace_mm 만 정상 추출 + placement_rules 부실 시,
    BrandRulesResult 인스턴스에 다른 필드 (clearspace_mm 등) 가 보존됨.
    """
    res = BrandRulesResult(
        brand_category="뷰티·코스메틱",
        clearspace_mm={"value": 800, "confidence": "high"},
        character_orientation={"value": "벽면", "confidence": "high"},
        placement_rules=[],  # 빈 list (부실)
    )
    # raise 안 함 + 모든 필드 LLM 응답 그대로
    assert res.brand_category == "뷰티·코스메틱"
    assert res.clearspace_mm == {"value": 800, "confidence": "high"}
    assert res.character_orientation == {"value": "벽면", "confidence": "high"}
    assert res.placement_rules == []


def test_log_minimal_warning_emits_for_missing_required(caplog):
    """_log_minimal_placement_rules_warning — minimal 누락 시 logger.warning 발생.

    G 옵션 핵심: raise 안 함. logger.warning 만 발생. brand 응답은 보존.
    """
    placement_rules = [{"object_type": "shelf_wall"}]  # counter 누락 (뷰티 minimal)
    with caplog.at_level(logging.WARNING, logger="app.nodes_small.reference"):
        _log_minimal_placement_rules_warning(
            brand_category="뷰티·코스메틱",
            placement_rules=placement_rules,
        )
    # logger.warning 1회 발생 + 메시지에 누락 정보 포함
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 1
    msg = warning_records[0].message
    assert "핵심 풀 누락" in msg
    assert "뷰티·코스메틱" in msg
    assert "counter" in msg


def test_log_minimal_warning_silent_when_required_present(caplog):
    """minimal 충족 시 logger.warning 발생 안 함 (정상 흐름)."""
    placement_rules = [
        {"object_type": "counter"},
        {"object_type": "shelf_wall"},
    ]  # counter 있음 → 뷰티 minimal 충족
    with caplog.at_level(logging.WARNING, logger="app.nodes_small.reference"):
        _log_minimal_placement_rules_warning(
            brand_category="뷰티·코스메틱",
            placement_rules=placement_rules,
        )
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 0


def test_log_minimal_warning_silent_for_unregistered_category(caplog):
    """SSOT 미등록 카테고리 (테크/아트/엔터 등) 는 minimal 빈 set → 검사 skip."""
    with caplog.at_level(logging.WARNING, logger="app.nodes_small.reference"):
        _log_minimal_placement_rules_warning(
            brand_category="테크·전자제품",
            placement_rules=[],  # 빈 list 라도 minimal 빈 set 이면 skip
        )
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 0


def test_log_minimal_warning_handles_invalid_entries(caplog):
    """placement_rules 의 dict 아닌 항목 / object_type 누락 항목은 무시."""
    placement_rules = [
        {"object_type": "shelf_wall"},
        {"name": "anonymous"},  # object_type 누락
        "not a dict",
        {"object_type": ""},  # 빈 string
    ]
    with caplog.at_level(logging.WARNING, logger="app.nodes_small.reference"):
        _log_minimal_placement_rules_warning(
            brand_category="뷰티·코스메틱",
            placement_rules=placement_rules,
        )
    # counter 없음 → warning 발생, 단 잘못된 항목은 actual set 에서 무시
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 1
    assert "counter" in warning_records[0].message
