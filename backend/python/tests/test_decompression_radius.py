"""
감압존 상수 검증.

히스토리:
  - 2026-04-22 (S-1): 1500 → 900 — 18평 photo_wall drop 3/3 해소 (커밋 ff64521)
  - 2026-05-07 (1-3 #533): 900 → 1200 라이브 테스트 — 외부 자문 (심리적 정지선)
    회귀 시 fallback: 900 으로 revert.

검증 대상:
  1. 상수 값이 현재 baseline (1200) 일치
  2. 1500 회귀 차단 (legacy 가드)
  3. 입구 반경 내 slot 미생성 (감압존 기능)

상세: reports/AD/worklist/2026-04-22_worklist.md S-1 + 5-7 라이브 테스트
"""
from shapely.geometry import Point, Polygon

from app.nodes_small.slot_gen import (
    DECOMPRESSION_RADIUS_MM,
    _generate_edge_slots,
    _generate_interior_slots,
)


# ─────────────────────────────────────────────────────────────────────
# 상수 검증 (회귀 방지)
# ─────────────────────────────────────────────────────────────────────

class TestDecompressionConstant:
    def test_constant_is_current_baseline(self):
        """현재 baseline 일치 검증.

        2026-04-22 Phase 0: 1500 → 900 (18평 photo_wall drop 3/3 해소).
        2026-05-07 라이브 비교: 1200 (photo_wall 1개 박힘) > 900 (drop). 1200 채택.
        photo_wall wall 부착 회귀는 AP-405-b / design retry 영역으로 별도 이슈.
        """
        assert DECOMPRESSION_RADIUS_MM == 1200

    def test_constant_not_legacy_1500(self):
        """1500 회귀 차단 — 18평 deep_zone 절반 잠식 회귀 방지."""
        assert DECOMPRESSION_RADIUS_MM != 1500


# ─────────────────────────────────────────────────────────────────────
# Edge slot 감압존 적용 검증 — 18평 도면 시뮬레이션
# ─────────────────────────────────────────────────────────────────────

def _make_18pyeong_rectangle() -> Polygon:
    """18평 ≈ 60㎡ 근사 직사각형: 6000×10000 mm = 60M mm²."""
    return Polygon([(0, 0), (6000, 0), (6000, 10000), (0, 10000)])


def _slot_coord(slot: dict) -> tuple:
    return (slot["x_mm"], slot["y_mm"])


class TestEdgeSlotDecompression:
    def test_entrance_vicinity_no_slot_within_900mm(self):
        """입구 반경 900mm 이내에 edge slot 생성 안 됨 (감압존 기능)."""
        usable_poly = _make_18pyeong_rectangle()
        entrance = Point(3000, 0)  # 바닥 중앙

        slots = _generate_edge_slots(usable_poly, dead_zones=[], entrance_points=[entrance])

        for key, slot in slots.items():
            pt = Point(*_slot_coord(slot))
            distance = entrance.distance(pt)
            assert distance >= DECOMPRESSION_RADIUS_MM, (
                f"Slot '{key}' at ({slot['x_mm']}, {slot['y_mm']}) is within "
                f"decompression radius {DECOMPRESSION_RADIUS_MM}mm "
                f"(distance: {distance:.0f}mm) — 감압존 미적용"
            )

    def test_slots_generated_outside_decompression(self):
        """감압존 밖 edge slot 이 충분히 생성돼야 함."""
        usable_poly = _make_18pyeong_rectangle()
        entrance = Point(3000, 0)

        slots = _generate_edge_slots(usable_poly, dead_zones=[], entrance_points=[entrance])

        assert len(slots) >= 10, (
            f"감압존 밖 edge slot 수 {len(slots)} 개. 너무 적음 — 18평 도면에서 "
            f"배치 공간 부족 가능성. 1500mm 체제 대비 증가해야 정상."
        )

    def test_multiple_entrances_all_respected(self):
        """입구 여러 개일 때 각 입구 모두 감압존 적용."""
        usable_poly = _make_18pyeong_rectangle()
        entrances = [Point(1500, 0), Point(4500, 0)]  # 하단 2개 입구

        slots = _generate_edge_slots(usable_poly, dead_zones=[], entrance_points=entrances)

        for key, slot in slots.items():
            pt = Point(*_slot_coord(slot))
            for i, ent in enumerate(entrances):
                distance = ent.distance(pt)
                assert distance >= DECOMPRESSION_RADIUS_MM, (
                    f"Slot '{key}' within decompression of entrance #{i} "
                    f"(distance: {distance:.0f}mm)"
                )


# ─────────────────────────────────────────────────────────────────────
# Interior slot 감압존 적용 검증
# ─────────────────────────────────────────────────────────────────────

class TestInteriorSlotDecompression:
    def test_interior_slots_exclude_decompression_zone(self):
        """interior slot 도 감압존 반경 내엔 생성 안 됨."""
        usable_poly = _make_18pyeong_rectangle()
        entrance = Point(3000, 0)

        slots = _generate_interior_slots(
            usable_poly, dead_zones=[], inner_walls=[], entrance_points=[entrance]
        )

        for key, slot in slots.items():
            pt = Point(*_slot_coord(slot))
            distance = entrance.distance(pt)
            assert distance >= DECOMPRESSION_RADIUS_MM, (
                f"Interior slot '{key}' at ({slot['x_mm']}, {slot['y_mm']}) "
                f"within decompression (distance: {distance:.0f}mm)"
            )


# ─────────────────────────────────────────────────────────────────────
# 회귀 방지 — 1500 체제와 slot 수 증가 비교 (참고)
# ─────────────────────────────────────────────────────────────────────

class TestSlotCountIncrease:
    def test_not_fewer_slots_than_with_1500_radius(self, monkeypatch):
        """현재 baseline 의 edge slot 수가 1500 체제보다 적지 않아야 함.

        증명: 감압존 1500 → 현재 (1200) 축소 = 입구 주변 유효 배치 공간 확대 또는 동등.
        18평 도면 + step 2000mm 단위라 1200 vs 1500 차이가 작을 수 있어 ≥ 비교.
        """
        usable_poly = _make_18pyeong_rectangle()
        entrance = Point(3000, 0)

        # 현재 baseline
        current_slots = _generate_edge_slots(
            usable_poly, dead_zones=[], entrance_points=[entrance]
        )
        current_count = len(current_slots)

        # 1500 으로 monkeypatch
        import app.nodes_small.slot_gen as slot_gen_module
        monkeypatch.setattr(slot_gen_module, "DECOMPRESSION_RADIUS_MM", 1500)
        legacy_slots = _generate_edge_slots(
            usable_poly, dead_zones=[], entrance_points=[entrance]
        )
        legacy_count = len(legacy_slots)

        assert current_count >= legacy_count, (
            f"현재 baseline slot 수({current_count}) 가 1500 체제({legacy_count}) "
            f"보다 적음 — 회귀 의심."
        )
