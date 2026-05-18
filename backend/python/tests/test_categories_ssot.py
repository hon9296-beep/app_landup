"""
app.categories SSOT 단위 테스트.

검증 항목:
1. 카테고리 lookup 의 정합성 (등록 카테고리 / 미등록 / None / 빈 문자열)
2. SSOT (categories.py) ↔ vmd_constants.CATEGORY_EXTRAS 1:1 일치 (drift 방지)
3. SSOT ↔ vmd_constants.VMD_BOUNDARIES_BY_CATEGORY 1:1 일치
4. SSOT ↔ design.py 의 (제거된) _CATEGORY_OVERRIDES 와 행위 등가
5. SSOT ↔ prompt_rules.PARTITION_PAIR_BY_CATEGORY (제거된 dict) 와 행위 등가
6. SSOT ↔ reference.py 의 (제거된) _MINIMAL_PLACEMENT_RULES_BY_CATEGORY 와 행위 등가
7. BRAND_TOOL.brand_category.enum 이 llm_extractable_keys() 와 일치

이 테스트는 SSOT 도입 전후의 행위 보존을 강제한다 (refactor 검증).
"""
from app.categories import (
    CATEGORIES_BY_KEY,
    DEFAULT_CATEGORY,
    get_category,
    llm_extractable_keys,
    all_keys,
)


# ── 1. lookup 정합성 ───────────────────────────────────────────────────


def test_get_category_known_keys():
    """등록된 카테고리 키 lookup → 해당 Category 반환."""
    for key in ["캐릭터 IP", "뷰티·코스메틱", "패션 브랜드", "F&B", "기타"]:
        cat = get_category(key)
        assert cat.key == key, f"{key} lookup 결과 불일치: {cat.key}"


def test_get_category_unknown_returns_default():
    """미등록 카테고리 → DEFAULT_CATEGORY ('기타')."""
    cat = get_category("존재하지않는카테고리")
    assert cat is DEFAULT_CATEGORY
    assert cat.key == "기타"


def test_get_category_none_returns_default():
    """None / 빈 문자열 → DEFAULT_CATEGORY."""
    assert get_category(None) is DEFAULT_CATEGORY
    assert get_category("") is DEFAULT_CATEGORY


def test_all_keys_includes_8_categories():
    """등록된 카테고리 8개 (캐릭터/뷰티/패션/F&B/테크/아트/엔터/기타)."""
    keys = all_keys()
    expected = {"캐릭터 IP", "뷰티·코스메틱", "패션 브랜드", "F&B", "테크·전자제품", "아트·전시", "엔터·팬미팅", "기타"}
    assert set(keys) == expected, f"카테고리 누락/잉여: {set(keys) ^ expected}"


def test_llm_extractable_keys_matches_brand_tool_enum():
    """llm_extractable_keys() → BRAND_TOOL.brand_category.enum 과 일치."""
    keys = llm_extractable_keys()
    expected = {"캐릭터 IP", "패션 브랜드", "F&B", "뷰티·코스메틱", "기타"}
    assert set(keys) == expected, f"LLM 추출 카테고리 불일치: {set(keys) ^ expected}"


def test_brand_tool_enum_is_ssot_generated():
    """reference.py 의 BRAND_TOOL.brand_category.enum 이 SSOT 와 일치 (런타임 자동 생성)."""
    from app.nodes_small.reference import BRAND_TOOL
    enum = BRAND_TOOL["input_schema"]["properties"]["brand_category"]["enum"]
    assert set(enum) == set(llm_extractable_keys())


# ── 2. SSOT ↔ vmd_constants.CATEGORY_EXTRAS 1:1 일치 ───────────────────


def test_ssot_extras_matches_vmd_constants():
    """SSOT 의 extras dict ↔ vmd_constants.CATEGORY_EXTRAS dict 1:1 일치."""
    from app.vmd_constants import CATEGORY_EXTRAS

    # SSOT 에 등록된 카테고리 중 extras 가 비어있지 않은 것들만 vmd_constants 에 있어야 함
    for cat in CATEGORIES_BY_KEY.values():
        if cat.extras:
            assert cat.key in CATEGORY_EXTRAS, f"vmd_constants 에 {cat.key} 누락"
            assert CATEGORY_EXTRAS[cat.key] == cat.extras, (
                f"{cat.key}: SSOT={cat.extras} vs vmd_constants={CATEGORY_EXTRAS[cat.key]}"
            )

    # vmd_constants 에 있는 키는 모두 SSOT 에 있어야 함
    for key, extras in CATEGORY_EXTRAS.items():
        assert key in CATEGORIES_BY_KEY, f"SSOT 에 {key} 누락 (vmd_constants 만 있음)"
        assert CATEGORIES_BY_KEY[key].extras == extras


# ── 3. SSOT ↔ vmd_constants.VMD_BOUNDARIES_BY_CATEGORY 1:1 일치 ────────


def test_ssot_boundaries_matches_vmd_constants():
    """SSOT 의 boundaries ↔ vmd_constants.VMD_BOUNDARIES_BY_CATEGORY 일치."""
    from app.vmd_constants import VMD_BOUNDARIES_BY_CATEGORY, VMD_BOUNDARIES, VMD_BOUNDARIES_BEAUTY

    # SSOT 에 boundaries 명시된 카테고리 (현재 뷰티만) 는 vmd_constants 에도 있어야 함
    for cat in CATEGORIES_BY_KEY.values():
        if cat.boundaries is not None:
            assert cat.key in VMD_BOUNDARIES_BY_CATEGORY, f"vmd_constants 에 {cat.key} boundaries 누락"
            assert VMD_BOUNDARIES_BY_CATEGORY[cat.key] is cat.boundaries

    # 뷰티는 BEAUTY 와 동일
    assert get_category("뷰티·코스메틱").boundaries is VMD_BOUNDARIES_BEAUTY


def test_get_vmd_boundaries_unchanged_behavior():
    """vmd_constants.get_vmd_boundaries 호출 시 SSOT 와 일치하는 결과."""
    from app.vmd_constants import get_vmd_boundaries, VMD_BOUNDARIES, VMD_BOUNDARIES_BEAUTY

    # 등록된 카테고리들
    assert get_vmd_boundaries("캐릭터 IP") is VMD_BOUNDARIES
    assert get_vmd_boundaries("뷰티·코스메틱") is VMD_BOUNDARIES_BEAUTY
    assert get_vmd_boundaries("기타") is VMD_BOUNDARIES
    # 미등록 → default (VMD_BOUNDARIES)
    assert get_vmd_boundaries("존재하지않는카테고리") is VMD_BOUNDARIES


# ── 4. SSOT ↔ design.py _CATEGORY_OVERRIDES 행위 등가 ──────────────────


def test_ssot_cat_overrides_matches_design_legacy():
    """SSOT 의 cat_overrides ↔ design.py 의 (제거된) _CATEGORY_OVERRIDES 행위 등가.

    design.py 가 SSOT 사용으로 전환된 후에도 lookup 결과가 변하지 않아야 함.
    refactor 전 _CATEGORY_OVERRIDES 의 핵심 데이터 hardcode → SSOT 결과와 비교.
    """
    # refactor 전 _CATEGORY_OVERRIDES 의 정확한 hardcode
    legacy = {
        "캐릭터 IP": {
            "character_bbox": {"labels": ["entrance_adjacent", "side_wall"], "allowed_directions": ["focal", "wall_facing"], "alignment": "parallel"},
            "photo_wall":     {"labels": ["side_wall"], "allowed_directions": ["wall_facing", "focal"], "alignment": "parallel"},
        },
        "F&B": {
            "counter":       {"labels": ["deep_wall", "side_wall"], "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
            "display_table": {"labels": ["center_freestanding"], "allowed_directions": ["center", "inward"], "alignment": "none"},
        },
        "패션 브랜드": {
            "shelf_wall":    {"labels": ["side_wall", "deep_wall"], "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
            "display_table": {"labels": ["center_freestanding"], "allowed_directions": ["center", "inward"], "alignment": "none"},
        },
    }
    for cat_key, expected in legacy.items():
        assert get_category(cat_key).cat_overrides == expected, (
            f"{cat_key} cat_overrides drift: SSOT={get_category(cat_key).cat_overrides} vs legacy={expected}"
        )

    # refactor 전에 등록 안 됐던 카테고리 (뷰티, 테크, 아트, 엔터, 기타) 는 빈 dict 보존
    for unregistered in ["뷰티·코스메틱", "테크·전자제품", "아트·전시", "엔터·팬미팅", "기타"]:
        assert get_category(unregistered).cat_overrides == {}


# ── 5. SSOT ↔ prompt_rules.PARTITION_PAIR_BY_CATEGORY 행위 등가 ────────


def test_ssot_partition_pair_matches_legacy():
    """SSOT 의 partition_pair ↔ refactor 전 PARTITION_PAIR_BY_CATEGORY 행위 등가."""
    # refactor 전 PARTITION_PAIR_BY_CATEGORY hardcode (5 카테고리)
    legacy = {
        "캐릭터 IP": {
            "partition_wall_I": {"shelf_wall", "shelf_3tier", "photo_wall", "display_table"},
            "partition_wall_L": {"shelf_wall"},
        },
        "뷰티·코스메틱": {
            "partition_wall_I": {"shelf_wall", "shelf_3tier", "consultation_desk", "test_bar", "display_table"},
            "partition_wall_L": {"shelf_wall", "shelf_3tier"},
        },
        "패션 브랜드": {
            "partition_wall_I": {"shelf_wall", "shelf_3tier", "display_table"},
            "partition_wall_L": {"shelf_wall", "shelf_3tier"},
        },
        "F&B": {
            "partition_wall_I": {"shelf_wall", "kiosk", "test_bar", "signage_stand"},
            "partition_wall_L": {"shelf_wall"},
        },
        "테크·전자제품": {
            "partition_wall_I": {"shelf_wall", "test_bar", "consultation_desk", "signage_stand", "display_table"},
            "partition_wall_L": {"shelf_wall"},
        },
    }
    for cat_key, expected in legacy.items():
        assert get_category(cat_key).partition_pair == expected, (
            f"{cat_key} partition_pair drift"
        )

    # 미등록 카테고리는 빈 dict
    assert get_category("아트·전시").partition_pair == {}
    assert get_category("엔터·팬미팅").partition_pair == {}
    assert get_category("기타").partition_pair == {}


def test_get_partition_pair_candidates_unchanged_behavior():
    """prompt_rules.get_partition_pair_candidates 의 동작 보존 (carry over)."""
    from app.nodes_small.prompt_rules import get_partition_pair_candidates

    # 뷰티 partition_wall_I → 5개 후보
    result = get_partition_pair_candidates("partition_wall_I", "뷰티·코스메틱")
    assert result == {"shelf_wall", "shelf_3tier", "consultation_desk", "test_bar", "display_table"}

    # 미등록 카테고리 → GENERIC fallback
    from app.nodes_small.prompt_rules import PARTITION_PAIR_GENERIC
    result_unknown = get_partition_pair_candidates("partition_wall_I", "존재하지않는카테고리")
    assert result_unknown == PARTITION_PAIR_GENERIC["partition_wall_I"]

    # partition_wall 외 → 빈 set
    assert get_partition_pair_candidates("counter", "뷰티·코스메틱") == set()


# ── 6. SSOT ↔ _MINIMAL_PLACEMENT_RULES_BY_CATEGORY 행위 등가 ───────────


def test_ssot_minimal_placement_rules_per_category():
    """SSOT 의 minimal_placement_rules — 5-1 약화 후 (옵션 C):
    카테고리별 absolute essential 1개만 강제. 나머지는 LLM/매뉴얼 재량.

    Why: 어제 (4-30 c6f3dd9) PR #366 의 strict 검증이 매뉴얼 현실과 안 맞음.
    뷰티 매뉴얼에 display_table 정보 없는데도 강제해서 retry 3회 모두 fail → fallback.
    매뉴얼 특화 정보(test_bar, consultation_desk 등)까지 같이 손실 → "기타" default.
    5-1 13:04 라이브 테스트에서 확정 후 minimal 1개로 약화.
    """
    expected_after_weakening = {
        "캐릭터 IP":      {"character_bbox"},  # 카테고리 정체성
        "패션 브랜드":    {"counter"},          # 운영 필수
        "F&B":            {"counter"},
        "뷰티·코스메틱":  {"counter"},
        "기타":           {"counter"},
    }
    for cat_key, expected in expected_after_weakening.items():
        assert get_category(cat_key).minimal_placement_rules == expected, (
            f"{cat_key} minimal_placement_rules drift"
        )


def test_brand_rules_validator_g_option_no_raise():
    """5-1 G 옵션: BrandRulesResult.model_validator 제거 — 어떤 placement_rules
    입력이든 raise 안 함 (raise → fallback 의 잘못된 결합 fix).

    [의미 변천]
    - 4-30 (PR #366): minimal 누락 시 ValidationError raise → harness retry → 모두 실패 시
      _fallback_brand_defaults() → brand 전체 default. 잘못된 결합.
    - 5-1 (G):       raise 안 함. brand 응답 LLM 추출분 항상 보존. 부실 응답 모니터링은
      reference.py 후처리 _log_minimal_placement_rules_warning 에서 logger.warning 만.
    """
    from app.nodes_small.reference import BrandRulesResult

    # 빈 placement_rules — 이전엔 캐릭터 IP minimal 누락 raise. G 옵션 후 통과.
    res_empty = BrandRulesResult(brand_category="캐릭터 IP", placement_rules=[])
    assert res_empty.brand_category == "캐릭터 IP"
    assert res_empty.placement_rules == []

    # minimal 충족 응답
    rules_full = [
        {"object_type": "shelf_wall"},
        {"object_type": "display_table"},
        {"object_type": "counter"},
    ]
    res_full = BrandRulesResult(brand_category="뷰티·코스메틱", placement_rules=rules_full)
    assert res_full.brand_category == "뷰티·코스메틱"
    assert len(res_full.placement_rules) == 3

    # SSOT 미등록 카테고리 (테크/아트/엔터) — minimal 빈 set, raise 안 함
    res_tech = BrandRulesResult(brand_category="테크·전자제품", placement_rules=[])
    assert res_tech.brand_category == "테크·전자제품"

    # 5-1 13:04 실제 fallback 케이스 — 뷰티 매뉴얼 6개 (display_table 누락) 통과 + 보존
    rules_partial = [
        {"object_type": "consultation_desk"},
        {"object_type": "counter"},
        {"object_type": "partition_wall_I"},
        {"object_type": "photo_wall"},
        {"object_type": "shelf_wall"},
        {"object_type": "test_bar"},
    ]
    res_partial = BrandRulesResult(brand_category="뷰티·코스메틱", placement_rules=rules_partial)
    assert res_partial.brand_category == "뷰티·코스메틱"  # 카테고리 보존
    assert len(res_partial.placement_rules) == 6        # 매뉴얼 특화 정보 보존


# ── 7. BRAND_TOOL.enum 자동 생성 검증 ──────────────────────────────────


def test_brand_tool_enum_synced_with_ssot():
    """BRAND_TOOL.brand_category.enum 이 SSOT 의 llm_extractable 카테고리만 포함."""
    from app.nodes_small.reference import BRAND_TOOL
    enum = BRAND_TOOL["input_schema"]["properties"]["brand_category"]["enum"]

    # llm_extractable=True 인 카테고리만 enum 에
    for cat in CATEGORIES_BY_KEY.values():
        if cat.is_llm_extractable:
            assert cat.key in enum, f"BRAND_TOOL enum 에 {cat.key} 누락"
        else:
            assert cat.key not in enum, f"BRAND_TOOL enum 에 {cat.key} 잉여 (is_llm_extractable=False 인데 포함됨)"


# ── 8. Category dataclass 구조 검증 ────────────────────────────────────


def test_category_dataclass_frozen():
    """Category dataclass 는 frozen — 외부에서 reassign 불가."""
    import pytest
    cat = get_category("뷰티·코스메틱")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        cat.key = "변경시도"


def test_category_required_fields_present():
    """모든 등록 카테고리가 필수 필드 (key, is_llm_extractable) 보유."""
    for cat in CATEGORIES_BY_KEY.values():
        assert hasattr(cat, "key") and isinstance(cat.key, str) and cat.key
        assert hasattr(cat, "is_llm_extractable") and isinstance(cat.is_llm_extractable, bool)
        assert hasattr(cat, "extras") and isinstance(cat.extras, dict)
        assert hasattr(cat, "cat_overrides") and isinstance(cat.cat_overrides, dict)
        assert hasattr(cat, "partition_pair") and isinstance(cat.partition_pair, dict)
        assert hasattr(cat, "minimal_placement_rules") and isinstance(cat.minimal_placement_rules, set)


def test_default_category_is_etc():
    """DEFAULT_CATEGORY 는 '기타' 인스턴스."""
    assert DEFAULT_CATEGORY.key == "기타"
    assert DEFAULT_CATEGORY is CATEGORIES_BY_KEY["기타"]


# ── 10. essential_supplement (#377 J) 검증 ────────────────────────────────


def test_essential_supplement_per_category():
    """카테고리별 essential_supplement 정의 검증.

    매뉴얼이 빠뜨려도 매장 운영 위해 반드시 추가될 기물 + 수량.
    "매뉴얼 우선 + 카테고리별 essential 만 보충" 정책의 SSOT.
    """
    expected = {
        "캐릭터 IP":      {"counter": 1, "photo_wall": 1},
        "뷰티·코스메틱":  {"counter": 1, "display_table": 1},
        "패션 브랜드":    {"counter": 1, "display_table": 1, "shelf_wall": 1},
        "F&B":            {"counter": 1, "display_table": 1},
        "기타":           {"counter": 1, "display_table": 1},
    }
    for cat_key, expected_essential in expected.items():
        actual = get_category(cat_key).essential_supplement
        assert actual == expected_essential, (
            f"{cat_key} essential_supplement drift: actual={actual} vs expected={expected_essential}"
        )


def test_essential_supplement_unregistered_categories_empty():
    """LLM 미추출 카테고리 (테크/아트/엔터) 는 essential 빈 dict.

    object_selection 에서 fallback 으로 DEFAULT_CATEGORY 의 essential 사용.
    """
    for cat_key in ["테크·전자제품", "아트·전시", "엔터·팬미팅"]:
        cat = get_category(cat_key)
        assert cat.essential_supplement == {}, (
            f"{cat_key} essential 빈 set 가 아님: {cat.essential_supplement}"
        )


def test_essential_supplement_default_category_fallback():
    """DEFAULT_CATEGORY (기타) 의 essential 이 정의되어 있어야 미등록 카테고리 fallback 가능."""
    assert DEFAULT_CATEGORY.essential_supplement == {"counter": 1, "display_table": 1}


def test_essential_supplement_size_constraint():
    """각 카테고리 essential 은 1-3개 범위 내 (보수적 supplement)."""
    for cat in CATEGORIES_BY_KEY.values():
        if cat.is_llm_extractable:  # LLM 추출 가능 카테고리만
            count = len(cat.essential_supplement)
            assert 0 <= count <= 3, (
                f"{cat.key} essential_supplement 크기 {count} — 1-3개 범위 권장"
            )


def test_essential_supplement_counter_universal():
    """LLM 추출 카테고리 중 운영 필수 = counter 모두 포함 (계산대 없는 매장 없음)."""
    for cat in CATEGORIES_BY_KEY.values():
        if cat.is_llm_extractable and cat.essential_supplement:
            assert "counter" in cat.essential_supplement, (
                f"{cat.key} essential 에 counter 누락 — 운영 필수 기물"
            )


# ── 9. dump_category_trace 자체 검증 ───────────────────────────────────


def _trace_file_path():
    from pathlib import Path
    from datetime import datetime
    # categories.py 의 dump 와 같은 경로 계산: app/categories.py.parent.parent = app/, 그 부모 = backend/python/
    # categories.py: _Path(__file__).parent.parent / "debug_logs" / YYYY-MM-DD
    # 즉 backend/python/app/categories.py 의 parent.parent = backend/python/
    return (
        Path(__file__).parent.parent / "debug_logs"
        / datetime.now().strftime("%Y-%m-%d") / "category_trace.json"
    )


def _strip_test_entries(trace: list) -> list:
    """테스트가 추가한 entry 제거 (test_marker 시작)."""
    return [
        e for e in trace
        if not (
            isinstance(e.get("extra"), dict)
            and str(e["extra"].get("test_marker", "")).startswith("UNIQUE_TEST_")
        )
    ]


def test_dump_category_trace_known_category():
    """등록 카테고리 dump → ssot_resolved_key 매칭, fell_back_to_default=False."""
    import json
    from app.categories import dump_category_trace

    trace_file = _trace_file_path()
    backup = None
    if trace_file.exists():
        backup = trace_file.read_text(encoding="utf-8")

    try:
        dump_category_trace(
            stage="test.known",
            raw_brand_category="뷰티·코스메틱",
            test_marker="UNIQUE_TEST_KNOWN",
        )
        assert trace_file.exists()
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        entry = next(e for e in trace if e.get("extra", {}).get("test_marker") == "UNIQUE_TEST_KNOWN")
        assert entry["normalized_input"] == "뷰티·코스메틱"
        assert entry["ssot_resolved_key"] == "뷰티·코스메틱"
        assert entry["is_known_category"] is True
        assert entry["fell_back_to_default"] is False
        assert entry["boundaries_source"] == "VMD_BOUNDARIES_BEAUTY"
        # 뷰티는 partition_pair 등록됨
        assert "partition_wall_I" in entry["partition_pair_keys"]
    finally:
        # 테스트 entry 제거 + 원본 복원
        if trace_file.exists():
            trace = json.loads(trace_file.read_text(encoding="utf-8"))
            cleaned = _strip_test_entries(trace)
            trace_file.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        if backup is not None:
            trace_file.write_text(backup, encoding="utf-8")


def test_dump_category_trace_unknown_falls_back():
    """미등록 카테고리 dump → fell_back_to_default=True, ssot_resolved_key='기타'."""
    import json
    from app.categories import dump_category_trace

    trace_file = _trace_file_path()
    backup = trace_file.read_text(encoding="utf-8") if trace_file.exists() else None

    try:
        dump_category_trace(
            stage="test.unknown",
            raw_brand_category="존재하지않는카테고리",
            test_marker="UNIQUE_TEST_UNKNOWN",
        )
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        entry = next(e for e in trace if e.get("extra", {}).get("test_marker") == "UNIQUE_TEST_UNKNOWN")
        assert entry["normalized_input"] == "존재하지않는카테고리"
        assert entry["ssot_resolved_key"] == "기타"
        assert entry["is_known_category"] is False
        assert entry["fell_back_to_default"] is True
    finally:
        if trace_file.exists():
            trace = json.loads(trace_file.read_text(encoding="utf-8"))
            cleaned = _strip_test_entries(trace)
            trace_file.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        if backup is not None:
            trace_file.write_text(backup, encoding="utf-8")


def test_dump_category_trace_dict_input():
    """dict 형식 입력 ({'value': 'xxx'}) 도 정상 처리."""
    import json
    from app.categories import dump_category_trace

    trace_file = _trace_file_path()
    backup = trace_file.read_text(encoding="utf-8") if trace_file.exists() else None

    try:
        dump_category_trace(
            stage="test.dict_input",
            raw_brand_category={"value": "패션 브랜드", "confidence": "high"},
            test_marker="UNIQUE_TEST_DICT",
        )
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        entry = next(e for e in trace if e.get("extra", {}).get("test_marker") == "UNIQUE_TEST_DICT")
        assert entry["normalized_input"] == "패션 브랜드"
        assert entry["ssot_resolved_key"] == "패션 브랜드"
    finally:
        if trace_file.exists():
            trace = json.loads(trace_file.read_text(encoding="utf-8"))
            cleaned = _strip_test_entries(trace)
            trace_file.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        if backup is not None:
            trace_file.write_text(backup, encoding="utf-8")


def test_dump_category_trace_disabled_env(monkeypatch):
    """DEBUG_LOG_DISABLED=1 시 dump skip (IO 비용 회피)."""
    import json
    from app.categories import dump_category_trace

    trace_file = _trace_file_path()
    backup = trace_file.read_text(encoding="utf-8") if trace_file.exists() else None

    try:
        monkeypatch.setenv("DEBUG_LOG_DISABLED", "1")
        dump_category_trace(
            stage="test.disabled",
            raw_brand_category="기타",
            test_marker="UNIQUE_TEST_DISABLED",
        )
        # disabled 라 entry 추가 안 됨
        if trace_file.exists():
            trace = json.loads(trace_file.read_text(encoding="utf-8"))
            assert not any(
                e.get("extra", {}).get("test_marker") == "UNIQUE_TEST_DISABLED" for e in trace
            )
    finally:
        # 백업 복원
        if backup is not None:
            trace_file.write_text(backup, encoding="utf-8")
