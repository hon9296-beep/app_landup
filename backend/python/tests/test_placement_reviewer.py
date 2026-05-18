"""placement_reviewer #490 — placement 후 anti-pattern 룰 + 노드 동작 검증.

5-4 박살 케이스 (photo_wall fail 매뉴얼 명시) 시 reject 발생 + slot 양보 hint inject 검증.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from shapely.geometry import Polygon

from app.nodes_small.anti_patterns import (
    PLACEMENT_ANTI_PATTERNS,
    run_placement_validators,
    get_placement_llm_anti_patterns,
    build_placement_designer_feedback,
)
from app.nodes_small.placement_reviewer import (
    MAX_PLACEMENT_REVIEW_ITERATIONS,
    run as placement_reviewer_run,
    _flag_enabled,
)


# ── PLACEMENT_ANTI_PATTERNS catalog 검증 ────────────────────────────


def test_catalog_has_7_rules():
    """AP-401 ~ AP-407 등록 (AP-406/407 = verify.py 폐기 시 이전된 보완 룰)."""
    rule_ids = [ap["id"] for ap in PLACEMENT_ANTI_PATTERNS]
    for rid in ("AP-401", "AP-402", "AP-403", "AP-404", "AP-405", "AP-406", "AP-407"):
        assert rid in rule_ids
    assert len(rule_ids) == 7


def test_catalog_severity_distribution():
    """blocking 2개 (AP-401, AP-402) / warning 5개 (AP-403~407)."""
    blocking = [ap for ap in PLACEMENT_ANTI_PATTERNS if ap["severity"] == "blocking"]
    warning = [ap for ap in PLACEMENT_ANTI_PATTERNS if ap["severity"] == "warning"]
    assert len(blocking) == 2
    assert len(warning) == 5


def test_catalog_validator_type_split():
    """python 6개 + llm 1개 (AP-405)."""
    py_rules = [ap for ap in PLACEMENT_ANTI_PATTERNS if ap["validator_type"] == "python"]
    llm_rules = get_placement_llm_anti_patterns()
    assert len(py_rules) == 6
    assert len(llm_rules) == 1
    assert llm_rules[0]["id"] == "AP-405"


# ── AP-401 brand 매뉴얼 명시 obj drop ─────────────────────────────


def test_ap401_detects_manual_obj_dropped():
    """매뉴얼 명시 photo_wall 이 fail → AP-401 blocking."""
    state = {
        "brand_data": {"placement_rules": [{"object_type": "photo_wall"}, {"object_type": "counter"}]},
        "placed_objects": [{"object_type": "counter"}],
        "failed_objects": [{"object_type": "photo_wall", "reason": "slot 충돌"}],
    }
    violations = run_placement_validators(state)
    rule_ids = [v["rule_id"] for v in violations]
    assert "AP-401" in rule_ids
    ap401 = next(v for v in violations if v["rule_id"] == "AP-401")
    assert ap401["severity"] == "blocking"
    assert "photo_wall" in ap401["violation_detail"]


def test_ap401_skips_non_manual_obj():
    """매뉴얼에 없는 obj 가 fail 해도 AP-401 발동 안 함."""
    state = {
        "brand_data": {"placement_rules": [{"object_type": "counter"}]},
        "placed_objects": [{"object_type": "counter"}],
        "failed_objects": [{"object_type": "banner_stand", "reason": "slot 충돌"}],
    }
    violations = run_placement_validators(state)
    ap401 = [v for v in violations if v["rule_id"] == "AP-401"]
    assert ap401 == []


def test_ap401_skips_when_obj_placed():
    """매뉴얼 obj 가 placed 에 있으면 AP-401 발동 안 함 (drop 아님)."""
    state = {
        "brand_data": {"placement_rules": [{"object_type": "photo_wall"}]},
        "placed_objects": [{"object_type": "photo_wall"}],
        "failed_objects": [{"object_type": "photo_wall", "reason": "slot 충돌"}],
    }
    violations = run_placement_validators(state)
    ap401 = [v for v in violations if v["rule_id"] == "AP-401"]
    assert ap401 == []


# ── AP-402 structural anchor fail ───────────────────────────────


def test_ap402_detects_photo_wall_fail():
    """photo_wall fail → AP-402 blocking (5-4 박살 케이스)."""
    state = {
        "brand_data": {"placement_rules": []},
        "placed_objects": [{"object_type": "consultation_desk"}],
        "failed_objects": [{"object_type": "photo_wall", "reason": "slot 점유됨"}],
    }
    violations = run_placement_validators(state)
    ap402 = [v for v in violations if v["rule_id"] == "AP-402"]
    assert len(ap402) == 1
    assert ap402[0]["severity"] == "blocking"


def test_ap402_skips_non_anchor():
    """non-structural obj 가 fail 해도 AP-402 발동 안 함."""
    state = {
        "brand_data": {"placement_rules": []},
        "placed_objects": [],
        "failed_objects": [{"object_type": "banner_stand", "reason": "x"}],
    }
    violations = run_placement_validators(state)
    ap402 = [v for v in violations if v["rule_id"] == "AP-402"]
    assert ap402 == []


# ── AP-403 entrance_width 통과 ──────────────────────────────────


def test_ap403_detects_oversized_obj():
    """짧은 변 > entrance_width → AP-403 warning."""
    state = {
        "entrance_width_mm": 1000,
        "placed_objects": [
            {"object_type": "shelf_wall", "width_mm": 1500, "depth_mm": 1200},  # short=1200 > 1000
            {"object_type": "counter", "width_mm": 800, "depth_mm": 600},  # short=600 < 1000 OK
        ],
    }
    violations = run_placement_validators(state)
    ap403 = [v for v in violations if v["rule_id"] == "AP-403"]
    assert len(ap403) == 1
    assert ap403[0]["intent_object_type"] == "shelf_wall"


def test_ap403_skips_when_no_entrance_width():
    """entrance_width 미상 시 검증 skip."""
    state = {
        "entrance_width_mm": None,
        "placed_objects": [{"object_type": "shelf_wall", "width_mm": 9999, "depth_mm": 9999}],
    }
    violations = run_placement_validators(state)
    ap403 = [v for v in violations if v["rule_id"] == "AP-403"]
    assert ap403 == []


# ── AP-404 placed 면적 비율 ──────────────────────────────────────


def test_ap404_detects_under_packed():
    """placed bbox 비율 < 5% → warning."""
    poly = Polygon([(0, 0), (10000, 0), (10000, 10000), (0, 10000)])  # 100 m²
    state = {
        "usable_poly": poly,
        "placed_objects": [{"object_type": "tiny", "width_mm": 100, "depth_mm": 100}],  # 0.01 m²
    }
    violations = run_placement_validators(state)
    ap404 = [v for v in violations if v["rule_id"] == "AP-404"]
    assert len(ap404) == 1
    assert "부실" in ap404[0]["violation_detail"]


def test_ap404_detects_over_packed():
    """placed bbox 비율 > 70% → warning."""
    poly = Polygon([(0, 0), (3000, 0), (3000, 3000), (0, 3000)])  # 9 m²
    state = {
        "usable_poly": poly,
        "placed_objects": [
            {"object_type": "big1", "width_mm": 2500, "depth_mm": 2500},  # 6.25 m²
            {"object_type": "big2", "width_mm": 2000, "depth_mm": 1000},  # 2 m²
        ],  # 합 8.25 m² / 9 m² = 91.7%
    }
    violations = run_placement_validators(state)
    ap404 = [v for v in violations if v["rule_id"] == "AP-404"]
    assert len(ap404) == 1
    assert "over-pack" in ap404[0]["violation_detail"]


def test_ap404_passes_normal_ratio():
    """5%~70% 정상 범위 → AP-404 미발동."""
    poly = Polygon([(0, 0), (5000, 0), (5000, 5000), (0, 5000)])  # 25 m²
    state = {
        "usable_poly": poly,
        "placed_objects": [{"object_type": "x", "width_mm": 1500, "depth_mm": 1000}],  # 1.5 m² = 6%
    }
    violations = run_placement_validators(state)
    ap404 = [v for v in violations if v["rule_id"] == "AP-404"]
    assert ap404 == []


# ── reviewer node 동작 ──────────────────────────────────────────


def test_run_skipped_when_flag_off(monkeypatch):
    """PLACEMENT_REVIEWER_ENABLED=false → skipped."""
    monkeypatch.setenv("PLACEMENT_REVIEWER_ENABLED", "false")
    result = placement_reviewer_run({})
    assert result["placement_reviewer_status"] == "skipped"


def test_run_pass_when_no_violations(monkeypatch):
    """위반 0건 → status=pass."""
    monkeypatch.setenv("PLACEMENT_REVIEWER_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # LLM skip
    state = {
        "brand_data": {"placement_rules": []},
        "placed_objects": [],
        "failed_objects": [],
    }
    result = placement_reviewer_run(state)
    assert result["placement_reviewer_status"] == "pass"
    assert result["placement_reviewer_feedback"] == ""


def test_run_reject_with_blocking_and_feedback(monkeypatch):
    """blocking 위반 → status=reject + feedback 자연어 inject 준비."""
    monkeypatch.setenv("PLACEMENT_REVIEWER_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # LLM skip
    state = {
        "brand_data": {"placement_rules": [{"object_type": "photo_wall"}]},
        "placed_objects": [{"object_type": "consultation_desk"}],
        "failed_objects": [{"object_type": "photo_wall", "reason": "slot 충돌"}],
    }
    result = placement_reviewer_run(state)
    assert result["placement_reviewer_status"] == "reject"
    assert "AP-401" in result["placement_reviewer_feedback"] or "AP-402" in result["placement_reviewer_feedback"]
    assert "slot 양보" in result["placement_reviewer_feedback"]
    # state inject 용 _placement_reviewer_feedback 도 동일
    assert result["_placement_reviewer_feedback"] == result["placement_reviewer_feedback"]


# ── feedback 함수 ─────────────────────────────────────────────


def test_build_placement_designer_feedback_includes_slot_yield_hint():
    """blocking violations 가 있으면 'slot 양보 hint' 라인 포함."""
    blocking = [{
        "rule_id": "AP-401",
        "severity": "blocking",
        "intent_object_type": "photo_wall",
        "intent_zone": "?",
        "intent_ref_point_id": "?",
        "violation_detail": "매뉴얼 명시 photo_wall drop",
    }]
    feedback = build_placement_designer_feedback(blocking)
    assert "AP-401" in feedback
    assert "slot 양보" in feedback


def test_build_placement_designer_feedback_empty_for_no_blocking():
    """blocking 0건 → 빈 string."""
    assert build_placement_designer_feedback([]) == ""
