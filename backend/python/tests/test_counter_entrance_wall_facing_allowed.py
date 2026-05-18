"""
B-3 후속 후속 (#535 후속, 5-8 13:22 라이브 회귀 fix) — counter entrance + wall_facing 허용.

진규님 5-8 진단:
  "룰에 따라 deep, mid zone 강제하다 drop 당한거면 entrance 까지 허용"

회귀 시점: 5-8 13:22 라이브 — 증정품 counter drop. 사유 "VMD 무관용 차단: 계산대 436회".
원인: design 의도 = mid_zone wall_10_mid (LLM 이 cluster 우선해서 mid 박음).
  placement step-down 시 entrance_zone ref 후보 시도 → R2 룰 (entrance 차단) → 누적 reject → drop.

fix: _vmd_blocking_check 의 R2 룰 완화.
  - entrance + center/inward counter = 차단 유지 (입구 중앙 차단 방지)
  - entrance + wall_facing counter = 허용 (drop 회피)
  - deep / mid 는 그대로 허용
"""
from app.nodes_small.placement import _vmd_blocking_check


# ── entrance + wall_facing 허용 ───────────────────────────


def test_counter_entrance_wall_facing_allowed():
    """counter entrance_zone + wall_facing = 허용 (drop 회피)."""
    result = _vmd_blocking_check(
        obj_type="counter", zone_label="entrance_zone",
        height_mm=900, direction="wall_facing", rp_label="",
    )
    assert result is None, (
        f"counter entrance + wall_facing 차단됨 — drop 회피 fix 무효: {result}"
    )


def test_counter_entrance_center_blocked():
    """counter entrance_zone + center = 차단 유지 (입구 중앙 차단 방지)."""
    result = _vmd_blocking_check(
        obj_type="counter", zone_label="entrance_zone",
        height_mm=900, direction="center", rp_label="",
    )
    assert result is not None
    assert "중앙" in result or "차단" in result


def test_counter_entrance_inward_blocked():
    """counter entrance_zone + inward (벽 안쪽) = 차단 유지."""
    result = _vmd_blocking_check(
        obj_type="counter", zone_label="entrance_zone",
        height_mm=900, direction="inward", rp_label="",
    )
    assert result is not None


# ── deep / mid 그대로 허용 ────────────────────────────────


def test_counter_deep_zone_allowed():
    """counter deep_zone = 그대로 허용 (회귀 차단)."""
    for direction in ("wall_facing", "center"):
        result = _vmd_blocking_check(
            obj_type="counter", zone_label="deep_zone",
            height_mm=900, direction=direction, rp_label="",
        )
        assert result is None, f"counter deep_zone {direction} 차단 회귀: {result}"


def test_counter_mid_zone_allowed():
    """counter mid_zone = 그대로 허용 (5-8 13:22 LLM 의도 mid 박음 — 통과해야)."""
    for direction in ("wall_facing", "center"):
        result = _vmd_blocking_check(
            obj_type="counter", zone_label="mid_zone",
            height_mm=900, direction=direction, rp_label="",
        )
        assert result is None, f"counter mid_zone {direction} 차단 회귀: {result}"


# ── 다른 zone 차단 ────────────────────────────────────────


def test_counter_other_zone_blocked():
    """counter 가 deep/mid/entrance 외 zone 박힐 시 차단."""
    result = _vmd_blocking_check(
        obj_type="counter", zone_label="staff_zone",
        height_mm=900, direction="wall_facing", rp_label="",
    )
    assert result is not None
    assert "R2" in result


# ── pos_counter 도 동일 룰 (alias) ────────────────────────


def test_pos_counter_entrance_wall_facing_allowed():
    """pos_counter alias 도 entrance + wall_facing 허용."""
    result = _vmd_blocking_check(
        obj_type="pos_counter", zone_label="entrance_zone",
        height_mm=900, direction="wall_facing", rp_label="",
    )
    assert result is None


def test_pos_counter_entrance_center_blocked():
    """pos_counter alias 도 entrance + center 차단."""
    result = _vmd_blocking_check(
        obj_type="pos_counter", zone_label="entrance_zone",
        height_mm=900, direction="center", rp_label="",
    )
    assert result is not None


# ── 다른 obj 영향 X ────────────────────────────────────────


def test_other_obj_unaffected():
    """counter 외 obj (shelf_wall 등) 는 본 룰 영향 X."""
    result = _vmd_blocking_check(
        obj_type="display_table", zone_label="entrance_zone",
        height_mm=900, direction="wall_facing", rp_label="",
    )
    # display_table 은 R2 룰 무관
    assert result is None or "R2" not in (result or "")
