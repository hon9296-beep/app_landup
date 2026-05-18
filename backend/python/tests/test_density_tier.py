"""
density_ratio 면적대별 동적 분기 검증 — 2026-04-22 S-8g-1.

제미나이 자문 Q1 판정 (reports/to_gemini/2026-04-22_18py_measurement_feedback.md):
  - NEW 11:27 테스트 utilization 46% 폭증 → 0.25 일괄 적용이 소형 공간 특성 무시
  - 3단 분기: small 0.15 / medium 0.20 / large 0.25
  - 경계값: app.constants 의 SMALL/MEDIUM_AREA_THRESHOLD_MM2 재활용

검증 대상:
  1. DENSITY_RATIO_BY_TIER 상수 값 회귀 방지
  2. _get_density_ratio() 면적 분기 동작
  3. _allocate_eligible 에서 density_ratio=None 시 자동 조회
  4. 사용자 state 의 density_ratio override 존중

상세: reports/AD/worklist/2026-04-22_worklist.md S-8g-1
"""
from app.constants import MEDIUM_AREA_THRESHOLD_MM2, SMALL_AREA_THRESHOLD_MM2
from app.nodes_small.object_selection import (
    DENSITY_RATIO_BY_TIER,
    _allocate_eligible,
    _get_density_ratio,
)


# ─────────────────────────────────────────────────────────────────────
# 상수 회귀 방지
# ─────────────────────────────────────────────────────────────────────

class TestDensityRatioConstants:
    def test_small_tier_is_0_15(self):
        """소형 (< 20평): 18평 실측 utilization 46% 폭증 대응."""
        assert DENSITY_RATIO_BY_TIER["small"] == 0.15

    def test_medium_tier_is_0_20(self):
        """중형 (20~50평): 보수적 추정. M-7 에서 실측 튜닝."""
        assert DENSITY_RATIO_BY_TIER["medium"] == 0.20

    def test_large_tier_is_0_25(self):
        """대형 (≥50평): Shin 영역 fallback."""
        assert DENSITY_RATIO_BY_TIER["large"] == 0.25


# ─────────────────────────────────────────────────────────────────────
# _get_density_ratio() 경계 검증
# ─────────────────────────────────────────────────────────────────────

class TestGetDensityRatio:
    def test_small_area(self):
        """5평/10평/15평/18평 전부 small tier."""
        assert _get_density_ratio(16_530_000) == 0.15   # 5평
        assert _get_density_ratio(33_060_000) == 0.15   # 10평
        assert _get_density_ratio(49_590_000) == 0.15   # 15평
        assert _get_density_ratio(59_500_000) == 0.15   # 18평

    def test_medium_area(self):
        """20평~50평 medium tier."""
        assert _get_density_ratio(66_000_000) == 0.20   # 20평 경계
        assert _get_density_ratio(99_180_000) == 0.20   # 30평
        assert _get_density_ratio(132_240_000) == 0.20  # 40평
        assert _get_density_ratio(165_000_000 - 1) == 0.20  # 50평 직전

    def test_large_area(self):
        """50평+ large tier (Shin 영역 fallback)."""
        assert _get_density_ratio(165_000_000) == 0.25  # 50평 경계
        assert _get_density_ratio(200_000_000) == 0.25

    def test_boundary_small_medium(self):
        """20평 경계 (66M) — small/medium 분기 정확성."""
        assert _get_density_ratio(SMALL_AREA_THRESHOLD_MM2 - 1) == 0.15
        assert _get_density_ratio(SMALL_AREA_THRESHOLD_MM2) == 0.20

    def test_boundary_medium_large(self):
        """50평 경계 (165M) — medium/large 분기 정확성."""
        assert _get_density_ratio(MEDIUM_AREA_THRESHOLD_MM2 - 1) == 0.20
        assert _get_density_ratio(MEDIUM_AREA_THRESHOLD_MM2) == 0.25


# ─────────────────────────────────────────────────────────────────────
# _allocate_eligible() 의 density_ratio 자동 조회
# ─────────────────────────────────────────────────────────────────────

class TestAllocatorAutoTier:
    def _obj(self, obj_type: str, w: int, d: int) -> dict:
        return {
            "object_type": obj_type,
            "width_mm": w,
            "depth_mm": d,
            "_from_brand": False,
        }

    def test_none_density_uses_auto_tier_small(self):
        """density_ratio=None 시 18평 → 자동 0.15 적용."""
        eligible = [self._obj("counter", 1500, 600)]
        _, log = _allocate_eligible(eligible, 59_500_000)
        expected = 59_500_000 * 0.15
        assert log["budget_summary"]["total_effective_budget"] == expected

    def test_none_density_uses_auto_tier_medium(self):
        """density_ratio=None 시 30평 → 자동 0.20."""
        eligible = [self._obj("counter", 1500, 600)]
        _, log = _allocate_eligible(eligible, 99_180_000)
        expected = 99_180_000 * 0.20
        assert log["budget_summary"]["total_effective_budget"] == expected

    def test_explicit_override_respected(self):
        """사용자가 density_ratio 명시하면 그 값 존중 (tier 덮어쓰기)."""
        eligible = [self._obj("counter", 1500, 600)]
        _, log = _allocate_eligible(eligible, 59_500_000, density_ratio=0.30)
        expected = 59_500_000 * 0.30
        assert log["budget_summary"]["total_effective_budget"] == expected


# ─────────────────────────────────────────────────────────────────────
# 회귀 — 18평에서 새 density=0.15 적용 시 예산 변화 확인
# ─────────────────────────────────────────────────────────────────────

class TestDensityRegression18py:
    def test_18py_effective_budget_reduced(self):
        """18평 eff = 59.5M × 0.15 = 8.925M (기존 14.875M 의 60%)."""
        eligible = [{"object_type": "counter", "width_mm": 1500, "depth_mm": 600,
                     "_from_brand": False}]
        _, log = _allocate_eligible(eligible, 59_500_000)
        assert log["budget_summary"]["total_effective_budget"] == 8_925_000.0
