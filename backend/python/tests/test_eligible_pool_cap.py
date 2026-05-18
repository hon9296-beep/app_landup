"""
#377 eligible 풀 cap (J + M) 단위 테스트.

J: brand 매뉴얼 우선 + 카테고리별 essential_supplement 만 보충 (이전 generic 7개 전체 대체)
M: 면적별 hard cap — 18평 7 / 30평 10 / 50평 14, brand 항목 우선 보존

도입 배경 (5-1 라이브 13:36):
- 18평 뷰티 매뉴얼 → placed=11 비대화 관찰
- brand placement_rules + MAX_COUNT_GENERIC 합집합 메커니즘 (~14-15개) → IQI cap 후 11
- 본 작업으로 brand + essential 1-3개 = 6-9개 → cap 7-8 목표

Graceful fallback (도박수 #474 망할 때 backstop):
- essential 빈 카테고리 → DEFAULT_CATEGORY essential 사용 + logger.warning
- 면적 0/음수 → 가장 작은 cap (7) + logger.error
- 면적 165㎡ 초과 → 가장 큰 cap (14) + logger.warning
"""
import logging

import pytest
from shapely.geometry import Polygon

from app.nodes_small.object_selection import (
    AREA_HARD_CAP_MM2,
    _apply_area_hard_cap,
    _default_placement_rules,
    _resolve_hard_cap,
)


def _mock_polygon(area_sqm: float) -> Polygon:
    side = (area_sqm * 1_000_000) ** 0.5
    return Polygon([(0, 0), (side, 0), (side, side), (0, side)])


def _mk_obj(object_type: str, brand: bool = False, w: int = 1500, d: int = 600) -> dict:
    return {
        "object_type": object_type,
        "_from_brand": brand,
        "width_mm": w,
        "depth_mm": d,
        "name": object_type,
    }


# ═══════════════════════════════════════════════════════════════════════
# J — brand 우선 + essential supplement
# ═══════════════════════════════════════════════════════════════════════


def test_J_brand_present_uses_essential_supplement_only():
    """brand 매뉴얼 있으면 essential 만 보충. generic 전체 사용 X."""
    poly = _mock_polygon(60)  # 18평
    rules = _default_placement_rules(poly, brand_category="뷰티·코스메틱", has_brand_manual=True)
    rule_types = {r["object_type"] for r in rules}

    # 뷰티 essential = counter, display_table 만 — 모두 포함
    assert "counter" in rule_types
    assert "display_table" in rule_types

    # 뷰티 extras (test_bar, consultation_desk 등) 는 보존 (extras override 정책)
    assert "test_bar" in rule_types
    assert "consultation_desk" in rule_types

    # generic 의 다른 기물 중 뷰티 extras 외 (photo_island, banner_stand 등) 은 보충 X
    # (essential 에도 없고 extras 에도 없음)
    assert "photo_island" not in rule_types, (
        f"essential 만 보충하는데 photo_island 포함됨 — generic 전체 사용 흔적: {rule_types}"
    )
    # banner_stand 도 보충 X
    assert "banner_stand" not in rule_types


def test_J_brand_empty_uses_generic_fallback():
    """brand 매뉴얼 부재 시 generic 전체 사용 (기존 동작 보존, fallback path)."""
    poly = _mock_polygon(60)
    rules = _default_placement_rules(poly, brand_category="뷰티·코스메틱", has_brand_manual=False)
    rule_types = {r["object_type"] for r in rules}

    # generic 7개 + 뷰티 extras → 풀 풍부 (10+ 개)
    assert len(rules) >= 7, f"generic fallback 인데 풀 너무 작음: {len(rules)}"
    assert "counter" in rule_types
    assert "display_table" in rule_types
    # generic 의 photo_island 포함 (fallback path 의 핵심)
    assert "photo_island" in rule_types or "photo_wall" in rule_types


def test_J_essential_missing_falls_back_to_default(caplog):
    """essential_supplement 빈 카테고리 (테크) → DEFAULT_CATEGORY essential + logger.warning."""
    poly = _mock_polygon(60)
    with caplog.at_level(logging.WARNING, logger="app.nodes_small.object_selection"):
        rules = _default_placement_rules(poly, brand_category="테크·전자제품", has_brand_manual=True)

    rule_types = {r["object_type"] for r in rules}
    # DEFAULT (기타) essential = counter, display_table → 두 개 다 포함
    assert "counter" in rule_types
    assert "display_table" in rule_types

    # logger.warning 발생 검증
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("essential_supplement" in r.message for r in warnings), (
        "essential 빈 카테고리 fallback warning 누락"
    )


def test_J_unknown_category_uses_default():
    """미등록 카테고리 → '기타' 의 essential 사용 (graceful fallback)."""
    poly = _mock_polygon(60)
    rules = _default_placement_rules(poly, brand_category="존재하지않는카테고리", has_brand_manual=True)
    rule_types = {r["object_type"] for r in rules}
    # 기타 essential = counter, display_table
    assert "counter" in rule_types
    assert "display_table" in rule_types


# ═══════════════════════════════════════════════════════════════════════
# M — 면적별 hard cap
# ═══════════════════════════════════════════════════════════════════════


def test_M_resolve_cap_18py():
    """18평 (60㎡) 이하 → cap 7."""
    assert _resolve_hard_cap(60_000_000) == 7
    assert _resolve_hard_cap(50_000_000) == 7  # 15평 도 가장 작은 tier


def test_M_resolve_cap_30py():
    """20평~30평 (66~99㎡) → cap 10."""
    assert _resolve_hard_cap(70_000_000) == 10
    assert _resolve_hard_cap(99_000_000) == 10


def test_M_resolve_cap_50py():
    """30평~50평 (99~165㎡) → cap 14."""
    assert _resolve_hard_cap(130_000_000) == 14
    assert _resolve_hard_cap(165_000_000) == 14


def test_M_resolve_cap_above_50py_fallback(caplog):
    """50평 초과 (대형 진입) → 가장 큰 tier cap (14) + logger.warning."""
    with caplog.at_level(logging.WARNING, logger="app.nodes_small.object_selection"):
        cap = _resolve_hard_cap(200_000_000)  # 60평
    assert cap == 14
    assert any("초과" in r.message or "tier" in r.message for r in caplog.records)


def test_M_resolve_cap_invalid_area_fallback(caplog):
    """면적 0 / 음수 → 가장 작은 cap (7) + logger.error."""
    with caplog.at_level(logging.ERROR, logger="app.nodes_small.object_selection"):
        cap_zero = _resolve_hard_cap(0)
        cap_neg = _resolve_hard_cap(-100)
    assert cap_zero == 7
    assert cap_neg == 7
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) >= 2  # 0 + 음수 두 번


def test_M_no_cap_when_under_threshold():
    """eligible 풀 ≤ cap 이면 변경 없음."""
    eligible = [_mk_obj(t) for t in ["counter", "display_table", "shelf_wall"]]
    capped, info = _apply_area_hard_cap(eligible, 60_000_000)
    assert len(capped) == 3
    assert info["applied"] is False
    assert info["dropped_count"] == 0


def test_M_caps_at_18py_threshold():
    """18평 → 9개 eligible → cap 7. 2개 drop."""
    eligible = [_mk_obj(t) for t in [
        "counter", "display_table", "shelf_wall", "shelf_3tier",
        "photo_wall", "photo_island", "test_bar", "kiosk", "banner_stand",
    ]]
    capped, info = _apply_area_hard_cap(eligible, 60_000_000)
    assert len(capped) == 7
    assert info["applied"] is True
    assert info["cap"] == 7
    assert info["dropped_count"] == 2


def test_M_brand_priority_preserved_in_drop():
    """cap 초과 시 brand 매뉴얼 항목 우선 보존. brand 4개 + non-brand 5개 = 9개 → cap 7.
    drop 되는 2개는 모두 non-brand.
    """
    eligible = [
        _mk_obj("counter", brand=True),
        _mk_obj("test_bar", brand=True),
        _mk_obj("consultation_desk", brand=True),
        _mk_obj("shelf_wall", brand=True),
        _mk_obj("display_table", brand=False),
        _mk_obj("photo_wall", brand=False),
        _mk_obj("photo_island", brand=False),
        _mk_obj("shelf_3tier", brand=False),
        _mk_obj("banner_stand", brand=False),
    ]
    capped, info = _apply_area_hard_cap(eligible, 60_000_000)
    assert len(capped) == 7

    brand_in_capped = [o for o in capped if o["_from_brand"]]
    assert len(brand_in_capped) == 4, "brand 항목 4개 모두 보존되어야 함"

    dropped_types = info["dropped_types"]
    # drop 된 건 non-brand 만
    dropped_brand = [t for t in dropped_types
                     if any(o["object_type"] == t and o["_from_brand"] for o in eligible)]
    assert len(dropped_brand) == 0, f"brand 항목이 drop 됨: {dropped_brand}"


# ═══════════════════════════════════════════════════════════════════════
# 5-1 라이브 케이스 시뮬레이션 (회귀 fix 검증)
# ═══════════════════════════════════════════════════════════════════════


def test_5_1_live_case_18py_beauty_J_supplement_only():
    """5-1 13:36 뷰티 매뉴얼 18평 케이스 — _default_placement_rules 가 J 적용 시
    이전 generic 전체 (~10개) 대신 essential 만 보충 (~8개) 해야 함.

    이전: generic(7) + 뷰티 extras(8, override 일부) - 겹침 ≈ 10-11
    현재 J: 뷰티 essential(2) + 뷰티 extras(8) - 겹침 ≈ 8-9
    """
    poly = _mock_polygon(60)
    rules_old = _default_placement_rules(poly, "뷰티·코스메틱", has_brand_manual=False)
    rules_new = _default_placement_rules(poly, "뷰티·코스메틱", has_brand_manual=True)

    # J 적용 후 풀 크기 ↓ (generic 전체 → essential 만)
    assert len(rules_new) <= len(rules_old)
    assert len(rules_new) <= 10, f"J 적용 후 풀 너무 큼: {len(rules_new)}"


def test_5_1_live_case_hard_cap_at_18py():
    """5-1 13:36 시나리오 — eligible 11개 (brand 8 + non-brand 3).

    1-2 #527 후속: area_hard_cap 도 brand 매뉴얼 명시 횟수와 max 처리 (cap = max(default 7, brand 8) = 8).
    이전 cap=7 강제 (#527 전) → cap=8 raise (brand 8 보존). non-brand 3개 중 일부 drop.
    """
    # 실제 13:36 placed 11개 그대로 시뮬레이션 (brand 8 + non-brand 3)
    eligible = [
        _mk_obj("partition_wall_I", brand=True),
        _mk_obj("counter", brand=True),
        _mk_obj("photo_wall", brand=True),
        _mk_obj("test_bar", brand=True),
        _mk_obj("consultation_desk", brand=True),
        _mk_obj("display_table", brand=False),
        _mk_obj("shelf_wall", brand=True),
        _mk_obj("aux_table", brand=True),
        _mk_obj("signage_stand", brand=False),
        _mk_obj("consultation_desk", brand=True),  # 2번째
        _mk_obj("kiosk", brand=False),
    ]
    capped, info = _apply_area_hard_cap(eligible, 60_000_000)
    # 1-2 #527 후: cap = max(7, brand 8) = 8. 11 → 8, drop 3.
    assert len(capped) == 8, f"cap raise = max(7, 8) = 8 기대 (실제 {len(capped)})"
    assert info["dropped_count"] == 3
    assert info["default_cap"] == 7
    assert info["brand_count"] == 8

    # brand 항목 8개 모두 보존 (cap=8 = brand 수). non-brand 3 모두 drop.
    brand_in_capped = sum(1 for o in capped if o["_from_brand"])
    assert brand_in_capped == 8, f"brand 항목 8개 모두 보존 기대 (실제 {brand_in_capped})"


# ═══════════════════════════════════════════════════════════════════════
# AREA_HARD_CAP_MM2 정합성
# ═══════════════════════════════════════════════════════════════════════


def test_AREA_HARD_CAP_tiers_monotonic():
    """tier 가 면적/cap 모두 오름차순 (매장 클수록 cap 큼)."""
    for i in range(len(AREA_HARD_CAP_MM2) - 1):
        a_area, a_cap = AREA_HARD_CAP_MM2[i]
        b_area, b_cap = AREA_HARD_CAP_MM2[i + 1]
        assert a_area < b_area, f"area 비단조: {a_area} < {b_area} 위배"
        assert a_cap < b_cap, f"cap 비단조: {a_cap} < {b_cap} 위배"


def test_AREA_HARD_CAP_3_tiers():
    """현재 3개 tier (18평/30평/50평) 정의."""
    assert len(AREA_HARD_CAP_MM2) == 3
    expected = [(60_000_000, 7), (99_000_000, 10), (165_000_000, 14)]
    assert AREA_HARD_CAP_MM2 == expected
