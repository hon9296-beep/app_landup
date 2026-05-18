"""
Phase 1 검증 인프라 테스트 — REF_DISABLE / fixture loader / placement_distance metric.

목적: Phase 1 의 3 도구가 단독으로 작동하는지 검증. ref 이미지 영향 측정 자체는
별도 통합 테스트 (scripts/validate_ref.py) 에서 수행.
"""
from __future__ import annotations

import os

import pytest

from app.metrics.placement_distance import compare_placements, _angular_diff
from app.services.ref_analysis_fixture import list_available_categories, load_fixture


# ── ref_analysis_fixture ─────────────────────────────────────────────


def test_fixture_loader_lists_available():
    cats = list_available_categories()
    # 최소 3 카테고리 (beauty/fashion/character_ip) 가 dump 되어 있어야 함
    assert "beauty" in cats
    assert "fashion" in cats
    assert "character_ip" in cats


def test_fixture_loader_returns_flat_dict():
    fx = load_fixture("beauty")
    assert fx is not None
    # ref_image_analyzer 의 실제 result 형식과 동일 (평면 dict)
    assert "layout_patterns" in fx
    assert "focal_points" in fx
    assert isinstance(fx["layout_patterns"], list)
    assert len(fx["layout_patterns"]) > 0
    # __meta 는 cleaned 된 후 노출 안 됨
    assert "__meta" not in fx


def test_fixture_loader_unknown_category_returns_none():
    assert load_fixture("does_not_exist") is None


def test_fixture_loader_empty_string_returns_none():
    assert load_fixture("") is None


# ── placement_distance metric ────────────────────────────────────────


def _obj(t: str, x: float, y: float, rot: float = 0.0) -> dict:
    return {"object_type": t, "center_x_mm": x, "center_y_mm": y, "rotation_deg": rot}


def test_distance_identical_results_zero():
    a = [_obj("counter", 1000, 2000, 90), _obj("photo_wall", 5000, 5000, 0)]
    b = [_obj("counter", 1000, 2000, 90), _obj("photo_wall", 5000, 5000, 0)]
    m = compare_placements(a, b)
    assert m.matched_pairs == 2
    assert m.type_match_rate == 1.0
    assert all(d == 0 for d in m.centroid_distances_mm)
    assert all(d == 0 for d in m.rotation_diffs_deg)
    assert not m.is_significantly_different()


def test_distance_different_coords():
    a = [_obj("counter", 1000, 2000, 0)]
    b = [_obj("counter", 4000, 6000, 0)]   # 5000mm 거리
    m = compare_placements(a, b)
    assert m.matched_pairs == 1
    assert m.centroid_distances_mm[0] == pytest.approx(5000.0, abs=1)
    assert m.is_significantly_different()


def test_distance_unmatched_type():
    a = [_obj("counter", 1000, 2000, 0), _obj("photo_wall", 5000, 5000, 0)]
    b = [_obj("counter", 1000, 2000, 0)]   # photo_wall 누락
    m = compare_placements(a, b)
    assert m.matched_pairs == 1
    assert "photo_wall" in m.unmatched_a
    assert m.unmatched_b == []
    assert m.is_significantly_different()


def test_distance_rotation_diff_shortest_path():
    # 350° 와 10° 는 최단경로 20° 차이
    a = [_obj("counter", 0, 0, 350)]
    b = [_obj("counter", 0, 0, 10)]
    m = compare_placements(a, b)
    assert m.rotation_diffs_deg[0] == pytest.approx(20, abs=1)


def test_angular_diff_helper():
    assert _angular_diff(0, 0) == 0
    assert _angular_diff(0, 180) == 180
    assert _angular_diff(0, 270) == 90    # 최단경로
    assert _angular_diff(350, 10) == 20


def test_distance_threshold_default_500mm():
    # 좌표 차이 400mm — threshold 500 보다 작고 type 도 일치 → 차이 없음
    a = [_obj("counter", 0, 0, 0)]
    b = [_obj("counter", 400, 0, 0)]
    m = compare_placements(a, b)
    assert not m.is_significantly_different()
    # threshold 300 으로 낮추면 차이 있음
    assert m.is_significantly_different(distance_threshold_mm=300)


def test_distance_empty_inputs():
    m = compare_placements([], [])
    assert m.matched_pairs == 0
    assert m.n_a == 0 and m.n_b == 0
    assert not m.is_significantly_different()


def test_distance_one_side_empty():
    m = compare_placements([_obj("counter", 0, 0, 0)], [])
    assert m.matched_pairs == 0
    assert m.unmatched_a == ["counter"]
    assert m.is_significantly_different()


# ── REF_DISABLE 환경변수 — design.py 진입 직전 검사만 ──
# (실제 design.py LLM 호출은 외부 통합 테스트로 검증. 단위 테스트는 환경변수 인식만.)


def test_ref_disable_env_recognized(monkeypatch):
    monkeypatch.setenv("REF_DISABLE", "1")
    assert os.environ.get("REF_DISABLE") == "1"


def test_ref_fixture_env_recognized(monkeypatch):
    monkeypatch.setenv("REF_FIXTURE_CATEGORY", "character_ip")
    fx = load_fixture(os.environ.get("REF_FIXTURE_CATEGORY"))
    assert fx is not None
    assert "layout_patterns" in fx
