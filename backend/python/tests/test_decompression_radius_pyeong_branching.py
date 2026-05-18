"""
1-3 (#533) C3 — 면적별 감압존 동적 분기 검증.

외부 자문 (리테일 표준) 기반 3단 분기:
  Small (< 20평): 1200mm (최소 기능형 — 18평 LUMIA baseline)
  Medium (20~40평): 1800mm (표준 감압형 — 2~3인 동시 머무름 폭)
  Large-Medium (40~50평): 2400mm (공간 경험형 — 브랜드 톤앤매너 전이)
  50평 이상: nodes_large 영역 (Shin, 별도 시스템)

회귀 차단:
- 함수 자체 분기 정확성 (5 case)
- state-driven 흐름: slot_gen.run() 이 박은 값을 ref_point_gen / anti_patterns 가 받음
"""
from shapely.geometry import Polygon

from app.nodes_small.slot_gen import (
    DECOMPRESSION_RADIUS_MM,
    compute_decompression_radius_mm,
    run as slot_gen_run,
)


# ── 함수 단위 분기 검증 ─────────────────────────────────────


def test_micro_5pyeong_returns_1200():
    """5평 (~16.5m²) → Small 구간 (1200)."""
    area = 16_500_000  # 5평 ≈ 16.5M mm²
    assert compute_decompression_radius_mm(area) == 1200


def test_small_18pyeong_returns_1200():
    """18평 (~60m²) → Small 구간 (1200) — LUMIA baseline."""
    area = 60_000_000
    assert compute_decompression_radius_mm(area) == 1200


def test_boundary_19pyeong_returns_1200():
    """19평 → Small 구간 끝 (1200, 20평 미만)."""
    area = 19 * 3_305_785  # 62.8M
    assert compute_decompression_radius_mm(area) == 1200


def test_medium_25pyeong_returns_1800():
    """25평 → Medium 구간 (1800)."""
    area = 25 * 3_305_785  # 82.6M
    assert compute_decompression_radius_mm(area) == 1800


def test_medium_35pyeong_returns_1800():
    """35평 → Medium 구간 (1800)."""
    area = 35 * 3_305_785  # 115.7M
    assert compute_decompression_radius_mm(area) == 1800


def test_boundary_40pyeong_returns_2400():
    """40평 → Large-Medium 구간 (2400, 경계 값).

    20*PYEONG ≤ 40*PYEONG 이지만 함수는 < 비교 → 40 정각은 2400 포함.
    """
    area = 40 * 3_305_785
    assert compute_decompression_radius_mm(area) == 2400


def test_large_medium_45pyeong_returns_2400():
    """45평 → Large-Medium 구간 (2400)."""
    area = 45 * 3_305_785  # 148.7M
    assert compute_decompression_radius_mm(area) == 2400


def test_above_50pyeong_returns_2400():
    """50평 이상 → 함수는 2400 반환 (단 실제로는 nodes_large 분기로 감)."""
    area = 60 * 3_305_785
    assert compute_decompression_radius_mm(area) == 2400


# ── state-driven 흐름 검증 ──────────────────────────────────


def _build_min_state(area_m2: float) -> dict:
    """면적별 최소 state."""
    side_mm = (area_m2 * 1_000_000) ** 0.5
    poly = Polygon([(0, 0), (side_mm, 0), (side_mm, side_mm), (0, side_mm)])
    return {
        "usable_poly": poly,
        "entrance_mm": (side_mm / 2, 0),
        "all_entrances_mm": [{"coord": (side_mm / 2, 0), "type": "MAIN_DOOR"}],
        "dead_zones": [],
        "inner_wall_linestrings": [],
    }


def test_slot_gen_run_writes_state_18pyeong():
    """slot_gen.run() 이 18평 (60m²) 에서 1200 박음."""
    state = _build_min_state(60.0)
    result = slot_gen_run(state)
    assert result["decompression_radius_mm"] == 1200


def test_slot_gen_run_writes_state_25pyeong():
    """slot_gen.run() 이 25평 (82.6m²) 에서 1800 박음."""
    state = _build_min_state(82.6)
    result = slot_gen_run(state)
    assert result["decompression_radius_mm"] == 1800


def test_slot_gen_run_writes_state_45pyeong():
    """slot_gen.run() 이 45평 (148.7m²) 에서 2400 박음."""
    state = _build_min_state(148.7)
    result = slot_gen_run(state)
    assert result["decompression_radius_mm"] == 2400


# ── default fallback 검증 ───────────────────────────────────


def test_module_default_is_1200():
    """state 없을 때 fallback default = 1200 (Small baseline)."""
    assert DECOMPRESSION_RADIUS_MM == 1200


def test_anti_patterns_state_aware():
    """anti_patterns 의 AP-001 이 state 의 decompression_radius_mm 우선 참조."""
    from app.nodes_small.anti_patterns import _validate_AP_001

    state = {
        "entrance_mm": (5000, 1000),
        "decompression_radius_mm": 1800,  # state 박음 (Medium 구간 가정)
        "reference_points": [
            {"id": "wall_close", "coord": (5000, 2500), "label": "x"},  # 거리 1500mm
        ],
        "eligible_objects": [
            {"object_type": "partition_wall_I", "width_mm": 2000, "depth_mm": 150, "height_mm": 2400},
        ],
    }
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_close", "zone_label": "entrance_zone"}]
    # 거리 1500 < state 1800 → 위반 발화 (default 1200 이었으면 통과)
    v = _validate_AP_001(intents, state)
    assert len(v) == 1, f"state 1800 우선 참조 실패 — default 1200 으로 작동 중"
    assert v[0]["rule_id"] == "AP-001"
    assert "1800mm" in v[0]["violation_detail"], f"detail 에 동적 값 미반영: {v[0]['violation_detail']}"
