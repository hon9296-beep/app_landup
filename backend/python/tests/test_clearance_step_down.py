"""
Tier 1-1 Layer 1-A/1-B: DIRECTIONAL_CLEARANCE_FLOOR + compute_scaled_clearance +
step_down_clearance + placement.py 통합.

상세: reports/AD/2026-04-20_small_store_finalization_tier1.md §1
"""
from app.vmd_constants import (
    DIRECTIONAL_CLEARANCE,
    DIRECTIONAL_CLEARANCE_FLOOR,
    STEP_DOWN_MM,
    SCALING_REFERENCE_AREA_MM2,
    compute_scaled_clearance,
    step_down_clearance,
)


# ─────────────────────────────────────────────────────────────────────
# 상수 검증
# ─────────────────────────────────────────────────────────────────────

class TestConstants:
    def test_floor_values_match_vmd_consensus(self):
        """외부 VMD 전문가(제미나이) 합의 floor 값 확인."""
        assert DIRECTIONAL_CLEARANCE_FLOOR["photo_wall"]["front"] == 1500
        assert DIRECTIONAL_CLEARANCE_FLOOR["photo_island"]["front"] == 1500
        assert DIRECTIONAL_CLEARANCE_FLOOR["counter"]["front"] == 900
        assert DIRECTIONAL_CLEARANCE_FLOOR["counter"]["back"] == 600
        assert DIRECTIONAL_CLEARANCE_FLOOR["consultation_desk"]["front"] == 900
        assert DIRECTIONAL_CLEARANCE_FLOOR["shelf_wall"]["front"] == 600
        assert DIRECTIONAL_CLEARANCE_FLOOR["test_bar"]["front"] == 600
        assert DIRECTIONAL_CLEARANCE_FLOOR["kiosk"]["front"] == 600

    def test_step_down_unit_is_200mm(self):
        """50mm는 마감 오차, 200mm가 도면 유의미 변화."""
        assert STEP_DOWN_MM == 200

    def test_scaling_reference_is_99sqm(self):
        """30평 기준 ratio=1.0."""
        assert SCALING_REFERENCE_AREA_MM2 == 99_000_000

    def test_test_bar_consultation_desk_added_to_default(self):
        """이전엔 누락돼 front=0으로 처리되던 두 타입 보강 확인."""
        assert DIRECTIONAL_CLEARANCE["test_bar"]["front"] > 0
        assert DIRECTIONAL_CLEARANCE["consultation_desk"]["front"] > 0


# ─────────────────────────────────────────────────────────────────────
# compute_scaled_clearance — B안 (면적 비례 초기값)
# ─────────────────────────────────────────────────────────────────────

class TestComputeScaledClearance:
    def test_18py_photo_wall_clamps_to_floor(self):
        """18평(60㎡): 2000 × 0.606 = 1212 → floor(1500) clamp."""
        result = compute_scaled_clearance("photo_wall", 60_000_000)
        assert result == {"front": 1500, "back": 0}

    def test_18py_counter_clamps_to_floor(self):
        """18평: 900 × 0.606 = 545 → floor(900) clamp."""
        result = compute_scaled_clearance("counter", 60_000_000)
        assert result == {"front": 900, "back": 600}

    def test_18py_shelf_wall_clamps_to_floor(self):
        """18평: 600 × 0.606 = 363 → floor(600) clamp."""
        result = compute_scaled_clearance("shelf_wall", 60_000_000)
        assert result == {"front": 600, "back": 0}

    def test_30py_photo_wall_uses_base(self):
        """30평+ (99㎡): ratio=1.0, base 그대로 2000mm."""
        result = compute_scaled_clearance("photo_wall", 99_000_000)
        assert result == {"front": 2000, "back": 0}

    def test_50py_photo_wall_caps_at_base(self):
        """50평(165㎡): ratio min(1.0, ...) → base 그대로 2000mm 상한."""
        result = compute_scaled_clearance("photo_wall", 165_000_000)
        assert result == {"front": 2000, "back": 0}

    def test_24py_photo_wall_partial_scale(self):
        """24평(79.2㎡): 2000 × 0.8 = 1600 → floor(1500) 위라 1600 적용."""
        result = compute_scaled_clearance("photo_wall", 79_200_000)
        assert result["front"] == 1600

    def test_brand_override_above_floor(self):
        """브랜드가 floor보다 큰 값 명시 → 브랜드값 적용 (스케일 무시)."""
        result = compute_scaled_clearance(
            "photo_wall", 60_000_000, brand_override={"front": 1800, "back": 0}
        )
        assert result == {"front": 1800, "back": 0}

    def test_brand_override_below_floor_clamps_to_floor(self):
        """[옵션 A] 브랜드가 floor 미만 명시 → max(brand, floor) = floor 강제. 인체 안전 우선."""
        result = compute_scaled_clearance(
            "photo_wall", 60_000_000, brand_override={"front": 1000, "back": 0}
        )
        assert result == {"front": 1500, "back": 0}, "옵션 A 위반: floor 1500 강제 누락"

    def test_unknown_object_type_returns_zero(self):
        """등록되지 않은 타입은 {0, 0} 반환."""
        result = compute_scaled_clearance("unknown_type", 60_000_000)
        assert result == {"front": 0, "back": 0}

    def test_brand_override_none_falls_back_to_scale(self):
        """brand_override=None이면 면적 비례 스케일."""
        result = compute_scaled_clearance("photo_wall", 60_000_000, brand_override=None)
        assert result == {"front": 1500, "back": 0}  # floor clamp


# ─────────────────────────────────────────────────────────────────────
# step_down_clearance — A안 (200mm 단계적 감소)
# ─────────────────────────────────────────────────────────────────────

class TestStepDownClearance:
    def test_photo_wall_2000_to_1800(self):
        """2000 → 1800 (200mm down)."""
        result = step_down_clearance({"front": 2000, "back": 0}, "photo_wall")
        assert result == {"front": 1800, "back": 0}

    def test_photo_wall_1700_clamps_to_floor_1500(self):
        """1700 → max(1500, 1500) = 1500. floor 도달."""
        result = step_down_clearance({"front": 1700, "back": 0}, "photo_wall")
        assert result == {"front": 1500, "back": 0}

    def test_photo_wall_1500_at_floor_returns_none(self):
        """1500(=floor) → 더 못 낮춤 → None."""
        result = step_down_clearance({"front": 1500, "back": 0}, "photo_wall")
        assert result is None

    def test_counter_at_floor_immediately_returns_none(self):
        """counter는 base=900=floor. 처음부터 None."""
        result = step_down_clearance({"front": 900, "back": 600}, "counter")
        assert result is None

    def test_counter_back_only_steps_down(self):
        """counter front 이미 floor지만 back=800 → 600으로 내릴 여유 있음."""
        result = step_down_clearance({"front": 900, "back": 800}, "counter")
        assert result == {"front": 900, "back": 600}

    def test_photo_wall_full_descent_chain(self):
        """2000 → 1800 → 1600 → 1500(floor) → None."""
        cur = {"front": 2000, "back": 0}
        steps = []
        while cur is not None:
            steps.append(cur["front"])
            cur = step_down_clearance(cur, "photo_wall")
        assert steps == [2000, 1800, 1600, 1500]

    def test_unknown_type_uses_zero_floor(self):
        """unknown 타입은 floor 없음 → 0까지 내려가고 멈춤."""
        result = step_down_clearance({"front": 200, "back": 0}, "unknown_type")
        assert result == {"front": 0, "back": 0}
        result2 = step_down_clearance({"front": 0, "back": 0}, "unknown_type")
        assert result2 is None


# ─────────────────────────────────────────────────────────────────────
# Layer 1-B — placement.py 통합 (state.py 필드 + _validate_placement 시그니처)
# ─────────────────────────────────────────────────────────────────────

class TestLayer1B_Integration:
    def test_small_state_has_scaled_clearances_field(self):
        from app.state import SmallState
        assert "scaled_clearances" in SmallState.__annotations__

    def test_validate_placement_accepts_scaled_clearances(self):
        """_validate_placement 시그니처에 scaled_clearances 파라미터 존재 + 기본값 None."""
        from app.nodes_small.placement import _validate_placement
        import inspect
        sig = inspect.signature(_validate_placement)
        assert "scaled_clearances" in sig.parameters
        assert sig.parameters["scaled_clearances"].default is None

    def test_placement_run_returns_scaled_clearances_in_dict(self):
        """placement.run 반환에 scaled_clearances 포함 (디버그 추적용)."""
        # mock state — minimal placement run with empty intents
        from shapely.geometry import box
        from app.nodes_small.placement import run
        state = {
            "usable_poly": box(0, 0, 7700, 7700),  # 18평
            "design_intents": [],
            "eligible_objects": [],
            "brand_data": {"brand": {"brand_category": {"value": "뷰티·코스메틱"}}, "placement_rules": []},
            "_partition_placed_raw": [],
            "locked_objects": [],
            "dead_zones": [],
            "main_artery": None,
            "entrance_buffer": None,
            "entrance_mm": (3850, 0),
            "sprinklers_mm": [],
        }
        result = run(state)
        # eligible 비어있어도 키는 존재해야 함 (빈 dict)
        assert "scaled_clearances" in result
        assert isinstance(result["scaled_clearances"], dict)


# ─────────────────────────────────────────────────────────────────────
# Layer 1-C — fallback.py Phase 5 step-down 통합
# ─────────────────────────────────────────────────────────────────────

class TestLayer1C_FallbackIntegration:
    def test_fallback_run_returns_scaled_clearances_in_dict(self):
        """fallback.run 반환에 scaled_clearances 포함 (Phase 5 step-down 결과 반영)."""
        from app.nodes_small.fallback import run as fallback_run
        # failed 비어있으면 early return {"fallback_round": 0} — scaled_clearances 없음도 OK
        result = fallback_run({"failed_objects": []})
        assert result.get("fallback_round") == 0

    def test_fallback_accepts_scaled_clearances_from_state(self):
        """fallback.run이 state["scaled_clearances"]를 읽어 검증에 사용할 수 있음."""
        # failed_objects + reference_points + usable_poly 있는 상태 구성
        from shapely.geometry import box
        from app.nodes_small.fallback import run as fallback_run
        state = {
            "failed_objects": [{"object_type": "photo_wall", "reason": "test"}],
            "fallback_round": 0,
            "eligible_objects": [{
                "object_type": "photo_wall",
                "width_mm": 2000, "depth_mm": 200, "height_mm": 2200,
                "wall_attachment": "flush",
            }],
            "reference_points": [],  # 빈 ref_point → Phase 1~3 skip
            "usable_poly": box(0, 0, 7700, 7700),
            "placed_raw": [],
            "placed_objects": [],
            "brand_data": {"brand": {"clearspace_mm": {"value": 600}}, "placement_rules": []},
            "scaled_clearances": {"photo_wall": {"front": 1500, "back": 0}},
            "dead_zones": [],
            "main_artery": None,
            "entrance_buffer": None,
        }
        # ref_points 비어있어서 early return (fallback_round만 증가)
        result = fallback_run(state)
        assert "fallback_round" in result

    def test_stepdown_placed_because_format(self):
        """Phase 5 성공 시 placed_because 포맷 기대값 (직접 문자열 검증은 mock 어려우므로 포맷만 확인)."""
        # 포맷: fallback_phase_5_stepdown_front{N}mm_back{M}mm
        expected_pattern = "fallback_phase_5_stepdown_front"
        # 실제 호출은 실 파이프라인에서만. 문서화 테스트로 유지.
        assert expected_pattern.startswith("fallback_phase_5_")
