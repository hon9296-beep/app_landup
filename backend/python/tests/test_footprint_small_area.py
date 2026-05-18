"""
calculate_local_cap() 검증 — 2026-04-22 S-8b.

극소형(5평) ~ 중형(50평) 면적대에서 cap 공식이 안전하게 동작하는지 확증.

설계 원칙 (제미나이 자문 Q2):
  - cap 단계는 "허수 사전 차단" 역할만.
  - trade-off (어떤 기물 drop 할지) 는 placement 단계에서 자연 해결.
  - 따라서 footprint > effective_area 케이스도 floor=1 로 일단 통과시킴.

검증 대상:
  1. 5평 ~ 50평 면적대 전반에서 cap ≥ 1 보장 (수식 붕괴 방지)
  2. 0 division / negative 방어
  3. 면적 증가 → cap 단조 증가 (or 동일) — 면적 비례 정합성
  4. footprint 초과 케이스도 cap=1 (drop 은 placement 영역)

상세: reports/AD/worklist/2026-04-22_worklist.md S-8b
"""
import pytest

from app.nodes_small.object_selection import (
    BUFFER_MM,
    calculate_footprint,
    calculate_local_cap,
)

# 면적대 — 평수 × 3.3058 ≈ ㎡, ×1_000_000 = mm²
AREA_5PY = 16_530_000     # 5평 (≈ 16.5㎡)
AREA_10PY = 33_060_000    # 10평
AREA_15PY = 49_590_000    # 15평
AREA_18PY = 59_500_000    # 18평
AREA_20PY = 66_120_000    # 20평
AREA_30PY = 99_180_000    # 30평
AREA_50PY = 165_300_000   # 50평

DENSITY = 0.25


def _eff(area_mm2: float) -> float:
    """effective_area = area × density_ratio (0.25)."""
    return area_mm2 * DENSITY


# ─────────────────────────────────────────────────────────────────────
# floor=1 보장 — 모든 면적대에서 cap ≥ 1
# ─────────────────────────────────────────────────────────────────────

class TestLocalCapFloor:
    """공간이 좁아도 최소 1개 시도 보장 (placement drop 영역에 위임)."""

    @pytest.mark.parametrize("area", [AREA_5PY, AREA_10PY, AREA_15PY, AREA_18PY])
    def test_counter_floor_at_small_areas(self, area):
        """counter (footprint ≈ 6.93M): 5~18평에서 cap=1 보장."""
        cap = calculate_local_cap("counter", 1500, 600, _eff(area))
        assert cap >= 1, f"counter at area {area}: cap={cap} (floor 위반)"

    @pytest.mark.parametrize("area", [AREA_5PY, AREA_10PY])
    def test_photo_wall_floor_at_tiny_areas(self, area):
        """photo_wall (footprint ≈ 6.46M): 5~10평 effective 보다 footprint 큼 → cap=1."""
        cap = calculate_local_cap("photo_wall", 1900, 200, _eff(area))
        assert cap >= 1, (
            f"photo_wall at {area}mm²: footprint > effective 여도 floor=1 보장 필요"
        )

    def test_zero_effective_area_returns_one(self):
        """effective_area = 0 극단: 0 division 없이 cap=1."""
        cap = calculate_local_cap("counter", 1500, 600, 0)
        assert cap == 1


# ─────────────────────────────────────────────────────────────────────
# 면적 증가 → cap 단조 증가 (or 동일) — 면적 비례 정합성
# ─────────────────────────────────────────────────────────────────────

class TestLocalCapMonotonic:
    """면적이 커지면 cap 도 같거나 증가해야 함 (면적 비례)."""

    def test_counter_cap_increases_with_area(self):
        """counter: 5평 → 50평 면적 증가에 cap 단조 증가."""
        areas = [AREA_5PY, AREA_10PY, AREA_18PY, AREA_30PY, AREA_50PY]
        caps = [calculate_local_cap("counter", 1500, 600, _eff(a)) for a in areas]
        for i in range(len(caps) - 1):
            assert caps[i] <= caps[i + 1], (
                f"counter cap 단조성 위반: {areas[i]}({caps[i]}) > {areas[i+1]}({caps[i+1]})"
            )

    def test_photo_wall_cap_increases_with_area(self):
        """photo_wall: 면적 증가에 cap 단조 증가."""
        areas = [AREA_5PY, AREA_10PY, AREA_18PY, AREA_30PY, AREA_50PY]
        caps = [calculate_local_cap("photo_wall", 1900, 200, _eff(a)) for a in areas]
        for i in range(len(caps) - 1):
            assert caps[i] <= caps[i + 1]

    def test_shelf_wall_cap_increases_with_area(self):
        """shelf_wall: 면적 증가에 cap 단조 증가."""
        areas = [AREA_5PY, AREA_10PY, AREA_18PY, AREA_30PY, AREA_50PY]
        caps = [calculate_local_cap("shelf_wall", 900, 500, _eff(a)) for a in areas]
        for i in range(len(caps) - 1):
            assert caps[i] <= caps[i + 1]


# ─────────────────────────────────────────────────────────────────────
# 18평 기준 cap 값 회귀 방지 (S-8a footprint 변경 영향)
# ─────────────────────────────────────────────────────────────────────

class TestLocalCap18py:
    """18평 (effective ≈ 14.875M) 에서 주요 기물 cap 값 회귀 방지."""

    def test_counter_at_18py(self):
        """counter footprint = 6.93M, eff = 14.875M → cap = 2."""
        cap = calculate_local_cap("counter", 1500, 600, _eff(AREA_18PY))
        # 14.875M / 6.93M = 2.14 → 2
        assert cap == 2, f"counter 18평: expected cap=2, got {cap}"

    def test_photo_wall_at_18py(self):
        """photo_wall footprint = 6.46M (1900×3400), eff = 14.875M → cap = 2."""
        cap = calculate_local_cap("photo_wall", 1900, 200, _eff(AREA_18PY))
        # 14.875M / 6.46M = 2.30 → 2
        assert cap == 2, f"photo_wall 18평: expected cap=2, got {cap}"

    def test_partition_wall_I_at_18py(self):
        """partition_wall_I footprint = 2.7M (2000×1350), eff = 14.875M → cap = 5."""
        cap = calculate_local_cap("partition_wall_I", 2000, 150, _eff(AREA_18PY))
        # 14.875M / 2.7M = 5.51 → 5
        assert cap == 5, f"partition_wall_I 18평: expected cap=5, got {cap}"


# ─────────────────────────────────────────────────────────────────────
# 5평 극소형 — footprint > effective 케이스 (floor=1 발동)
# ─────────────────────────────────────────────────────────────────────

class TestLocalCap5py:
    """5평 (effective ≈ 4.13M) — 거의 모든 기물이 floor=1 발동."""

    def test_counter_at_5py_floor(self):
        """counter footprint 6.93M > eff 4.13M → cap=1 (floor)."""
        cap = calculate_local_cap("counter", 1500, 600, _eff(AREA_5PY))
        assert cap == 1

    def test_photo_wall_at_5py_floor(self):
        """photo_wall footprint 6.46M > eff 4.13M → cap=1 (floor)."""
        cap = calculate_local_cap("photo_wall", 1900, 200, _eff(AREA_5PY))
        assert cap == 1

    def test_partition_wall_I_at_5py_normal(self):
        """partition_wall_I footprint 2.7M < eff 4.13M → cap=1 정상 산출."""
        cap = calculate_local_cap("partition_wall_I", 2000, 150, _eff(AREA_5PY))
        # 4.13M / 2.7M = 1.53 → 1
        assert cap == 1


# ─────────────────────────────────────────────────────────────────────
# 50평 중형+ 면적에서 cap 충분히 증가
# ─────────────────────────────────────────────────────────────────────

class TestLocalCap50py:
    """50평 (effective ≈ 41.3M) — cap 이 면적 비례로 충분히 증가."""

    def test_counter_at_50py(self):
        """counter footprint 6.93M, eff 41.3M → cap = 5."""
        cap = calculate_local_cap("counter", 1500, 600, _eff(AREA_50PY))
        # 41.325M / 6.93M = 5.96 → 5
        assert cap == 5

    def test_partition_wall_I_at_50py(self):
        """partition_wall_I footprint 2.7M, eff 41.3M → cap = 15."""
        cap = calculate_local_cap("partition_wall_I", 2000, 150, _eff(AREA_50PY))
        # 41.325M / 2.7M = 15.30 → 15
        assert cap == 15
