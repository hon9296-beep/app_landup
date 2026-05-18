"""
C4 (5-7 21:36 + 5-8 13:30 라이브 회귀 fix) — partition_wall_I 가벽 시위 차단.

진규님 라이브 진단:
  - 5-7 21:36: "개박살인데? 시위하는것도 아니고" — 가벽이 매장 한복판 가로 박힘
  - 5-8 13:30: partition_wall_I @ (5000, 8250) anchor=wall_9_left mid_zone — 다시 시위
  - 본질: mid_zone wall ref 에 가벽 매핑 시 placement 가 매장 중앙 향해 수직 돌출 →
    매장 한복판 가로 시위 형태. 양옆 통로 폭 잠식 + 동선 차단 + VMD 부적절.

3중 방어 검증:
  1. prompts/design.py: partition_wall_I deep_zone 만 허용 가이드 명시 (LLM source)
  2. anti_patterns.py AP-010: design_intents 단계 mid/entrance_zone 매핑 reject (reviewer)
  3. partition_placement.py: mid_zone rp 후보 reject (코드층 안전망)

L 은 별도 — staff_zone (deep_zone 코너) 정공이라 본 룰 미적용.
"""
import pytest
from shapely.geometry import Polygon

from app.nodes_small.anti_patterns import (
    ANTI_PATTERNS,
    _validate_AP_010,
)
from app.nodes_small.prompts.design import DESIGN_SYSTEM_TEMPLATE


# ── 1. prompt 룰 — partition_wall_I deep_zone 강제 명시 ─────────────


def test_prompt_says_partition_wall_I_deep_zone_only():
    """partition_wall_I zone_label = deep_zone 만 허용 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "partition_wall_I" in template
    # deep_zone 만 허용 + mid_zone 절대 금지 phrase
    assert "deep_zone" in template
    assert "mid_zone" in template and "절대 금지" in template


def test_prompt_explains_protest_regression():
    """5-7 21:36 + 5-8 13:30 시위 회귀 사례 명시 (LLM 학습 유도)."""
    template = DESIGN_SYSTEM_TEMPLATE
    # 회귀 사례 또는 시위 형태 phrase
    assert "시위" in template
    # 라이브 날짜 또는 회귀 사례 컨텍스트
    assert "5-7 21:36" in template or "5-8 13:30" in template


def test_prompt_partition_direction_wall_facing_only():
    """partition_wall_I direction = wall_facing 만 (LLM intent)."""
    template = DESIGN_SYSTEM_TEMPLATE
    # direction = wall_facing 강제 phrase
    assert "wall_facing" in template
    # center / focal / inward 금지 phrase
    assert "center" in template


# ── 2. AP-010 validator — design_intents reject ────────────────────


def _make_state_with_rp(rp_id: str, rp_zone: str) -> dict:
    """test 용 minimal state — ref_point 1개 등록."""
    return {
        "reference_points": [{"id": rp_id, "zone_label": rp_zone, "coord": (5000, 8250)}],
        "eligible_objects": [
            {"object_type": "partition_wall_I", "width_mm": 2000, "depth_mm": 150, "height_mm": 2400},
            {"object_type": "partition_wall_L", "width_mm": 2000, "depth_mm": 150, "height_mm": 2400},
        ],
    }


def test_AP_010_violation_mid_zone():
    """partition_wall_I + mid_zone ref → blocking violation."""
    state = _make_state_with_rp("wall_9_left", "mid_zone")
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_9_left", "zone_label": "mid_zone"}]
    v = _validate_AP_010(intents, state)
    assert len(v) == 1
    assert v[0]["rule_id"] == "AP-010"
    assert v[0]["severity"] == "blocking"
    assert "mid_zone" in v[0]["violation_detail"]


def test_AP_010_violation_entrance_zone():
    """partition_wall_I + entrance_zone ref → blocking violation."""
    state = _make_state_with_rp("wall_1_mid", "entrance_zone")
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_1_mid", "zone_label": "entrance_zone"}]
    v = _validate_AP_010(intents, state)
    assert len(v) == 1
    assert v[0]["rule_id"] == "AP-010"


def test_AP_010_pass_deep_zone():
    """partition_wall_I + deep_zone ref → 통과 (정상)."""
    state = _make_state_with_rp("wall_15_corner", "deep_zone")
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_15_corner", "zone_label": "deep_zone"}]
    v = _validate_AP_010(intents, state)
    assert v == []


def test_AP_010_partition_L_exempted_from_mid_zone():
    """partition_wall_L 은 mid_zone 매핑돼도 본 룰 미적용 (staff_zone 정공 케이스)."""
    state = _make_state_with_rp("wall_5_mid", "mid_zone")
    intents = [{"object_type": "partition_wall_L", "ref_point_id": "wall_5_mid", "zone_label": "mid_zone"}]
    v = _validate_AP_010(intents, state)
    assert v == [], "partition_wall_L 은 본 룰 미적용 — L 은 별도 staff_zone 정공"


def test_AP_010_violation_intent_zone_only():
    """intent.zone_label 만 mid_zone, ref 미상 — 그래도 위반 검출."""
    state = {
        "reference_points": [],
        "eligible_objects": [
            {"object_type": "partition_wall_I", "width_mm": 2000, "depth_mm": 150, "height_mm": 2400},
        ],
    }
    intents = [{"object_type": "partition_wall_I", "ref_point_id": None, "zone_label": "mid_zone"}]
    v = _validate_AP_010(intents, state)
    assert len(v) == 1


def test_AP_010_violation_rp_zone_only():
    """intent.zone_label 누락, ref.zone_label = mid_zone → 위반 검출 (LLM zone 누락 회귀 차단)."""
    state = _make_state_with_rp("wall_9_left", "mid_zone")
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_9_left", "zone_label": ""}]
    v = _validate_AP_010(intents, state)
    assert len(v) == 1


def test_AP_010_empty_intents():
    """빈 intents → graceful (위반 0)."""
    state = _make_state_with_rp("wall_15_corner", "deep_zone")
    assert _validate_AP_010([], state) == []


# ── 3. AP-010 catalog 등록 + count ─────────────────────────────────


def test_AP_010_in_catalog():
    """AP-010 catalog 등록 + python validator + blocking."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-010"), None)
    assert found is not None, "AP-010 catalog 미등록"
    assert found["validator_type"] == "python"
    assert found["severity"] == "blocking"
    assert found["enabled"] is True


def test_AP_010_description_mentions_mid_zone_and_protest():
    """AP-010 description 에 mid_zone + 시위 회귀 명시 (LLM feedback / debug 가시성)."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-010"), None)
    assert found is not None
    desc = found["description"]
    assert "mid_zone" in desc
    assert "시위" in desc or "수직 돌출" in desc


# ── 4. partition_placement.py 코드층 안전망 ──────────────────────


def test_partition_placement_rejects_mid_zone_wall_I():
    """partition_placement.py 가 mid_zone rp 후보 reject 박는지 source 검사.

    inline 실 실행은 SmallState + usable_poly + structural_dz 등 의존 큼 — source 패턴 검사로 대체.
    """
    import inspect
    from app.nodes_small import partition_placement
    src = inspect.getsource(partition_placement)
    # C4 reject 분기 박혔는지
    assert "partition_wall_I" in src
    assert "mid_zone" in src
    assert 'reason": "partition_wall_I mid_zone 차단' in src or "C4" in src


def test_partition_placement_preserves_entrance_zone_reject():
    """기존 entrance_zone reject (Layer 1b) 유지 — 회귀 차단."""
    import inspect
    from app.nodes_small import partition_placement
    src = inspect.getsource(partition_placement)
    assert "entrance_zone 차단" in src
    assert "Layer 1b" in src


def test_partition_placement_L_not_affected():
    """partition_wall_L 은 mid_zone 차단 분기 미적용 (source 에서 obj_type == partition_wall_I 만 체크).

    L 차단 분기가 'startswith(partition_wall)' 식으로 박히면 staff_zone L 회귀 — 차단.
    """
    import inspect
    from app.nodes_small import partition_placement
    src = inspect.getsource(partition_placement)
    # mid_zone 차단 분기는 obj_type == "partition_wall_I" 만 (startswith 아님)
    # 정확한 phrase 검사
    mid_zone_block_line = 'if obj_type == "partition_wall_I" and rp_zone == "mid_zone":'
    assert mid_zone_block_line in src, (
        "partition_wall_I 만 차단해야 함. startswith(partition_wall) 식이면 L 도 차단되는 회귀."
    )
