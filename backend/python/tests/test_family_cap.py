"""
Family cap 검증 — 2026-04-22 S-8c-2.

제미나이 자문 Q3/Q5 재진단 (reports/to_gemini/2026-04-22_18py_measurement_feedback.md):
  - brand 필수 기물 drop 방지 위해 cap 단계에 family 합산 한도 추가
  - "placement drop = trade-off 자연 해결" 원칙 일부 수정
  - FAMILY_CAPS_SMALL (소형 기준, OLD 실측 역산):
      consultation=2, display=2, photo=1, shelf=3, partition=1

검증 대상:
  1. FAMILY_CAPS_SMALL 상수 값 회귀 방지
  2. _get_family() helper — OBJECT_STANDARDS 조회 + prefix fallback
  3. _allocate_eligible() family 합산 한도 적용 → Family_Exceeded rejection
  4. consultation_desk + consultation_table 합산 2개 초과 차단
  5. photo_wall + photo_island 합산 1개 초과 차단
  6. family 미매칭 기물 (counter/kiosk 등) 은 family cap 영향 없음
  7. family cap < individual local cap 일 때 family 우선 발동

상세: reports/AD/worklist/2026-04-22_worklist.md S-8c-2
"""
from app.nodes_small.object_selection import (
    FAMILY_CAPS_SMALL,
    _allocate_eligible,
    _get_family,
)

AREA_18PY = 59_500_000


def _obj(obj_type: str, w: int = 1000, d: int = 500, from_brand: bool = False) -> dict:
    return {
        "object_type": obj_type,
        "width_mm": w,
        "depth_mm": d,
        "_from_brand": from_brand,
    }


# ─────────────────────────────────────────────────────────────────────
# FAMILY_CAPS_SMALL 상수 회귀 방지
# ─────────────────────────────────────────────────────────────────────

class TestFamilyCapsConstant:
    def test_consultation_cap_is_2(self):
        assert FAMILY_CAPS_SMALL["consultation"] == 2

    def test_display_cap_is_2(self):
        assert FAMILY_CAPS_SMALL["display"] == 2

    def test_photo_cap_is_1(self):
        """photo 앵커 역할, 중복 금지. OLD 실측 1개 기준."""
        assert FAMILY_CAPS_SMALL["photo"] == 1

    def test_shelf_cap_is_1(self):
        """[S-8f v2 튜닝, 2026-04-22 제미나이 Q1] shelf family cap 3→1 축소.
        18평 유효 벽면(~15m)에 photo/partition/counter/consultation 이미 ~7m 점유.
        shelf 2+ 는 벽 slot 초과 → drop 변동. OLD 실측도 shelf×1 성공.
        """
        assert FAMILY_CAPS_SMALL["shelf"] == 1

    def test_partition_cap_is_1(self):
        """18평 소형에 가벽 1개 충분 — OLD 실측 증명. 중형 이상은 M-7 에서 확장."""
        assert FAMILY_CAPS_SMALL["partition"] == 1

    def test_counter_cap_is_1(self):
        """[S-8f 튜닝, 2026-04-22 제미나이 재자문] counter single-type family cap.
        18평 counter 2개는 물리적 허수 (separate 1200 + clearance 900/600).
        이전 3회 실측 (18:43/44/46) 에서 counter_2 가 photo_wall drop 유발 → 1 강제 차단.
        """
        assert FAMILY_CAPS_SMALL["counter"] == 1


# ─────────────────────────────────────────────────────────────────────
# _get_family() helper
# ─────────────────────────────────────────────────────────────────────

class TestGetFamily:
    def test_object_standards_registered(self):
        """OBJECT_STANDARDS 에 family 필드 있는 기물은 그 값 반환."""
        assert _get_family("consultation_desk") == "consultation"
        assert _get_family("display_table") == "display"
        assert _get_family("display_table_standard") == "display"
        assert _get_family("photo_wall") == "photo"
        assert _get_family("photo_island") == "photo"
        assert _get_family("shelf_wall") == "shelf"
        assert _get_family("shelf_standard") == "shelf"
        assert _get_family("shelf_3tier") == "shelf"
        assert _get_family("partition_wall_I") == "partition"
        assert _get_family("partition_wall_L") == "partition"

    def test_counter_family_self(self):
        """[S-8f 튜닝] counter 는 self-family (single-type cap). OBJECT_STANDARDS 에 family='counter' 명시."""
        assert _get_family("counter") == "counter"

    def test_no_family_types(self):
        """test_bar / kiosk / signage_stand / banner_stand / character_bbox 는 family 없음 (cap 미적용)."""
        assert _get_family("test_bar") == ""
        assert _get_family("kiosk") == ""
        assert _get_family("signage_stand") == ""
        assert _get_family("banner_stand") == ""
        assert _get_family("character_bbox") == ""

    def test_prefix_fallback_consultation_table(self):
        """consultation_table 은 OBJECT_STANDARDS 미등록 — prefix fallback 동작."""
        assert _get_family("consultation_table") == "consultation"

    def test_prefix_fallback_various(self):
        """LUMIA 등 brand 매뉴얼이 미등록 obj_type 제공 시 prefix 매칭."""
        assert _get_family("consultation_custom") == "consultation"
        assert _get_family("display_island") == "display"
        assert _get_family("shelf_rotating") == "shelf"
        assert _get_family("photo_cube") == "photo"
        assert _get_family("partition_wall_T") == "partition"

    def test_unknown_type_empty(self):
        """완전 미매칭 타입 — family 없음 (cap 미적용)."""
        assert _get_family("unknown_xyz") == ""
        assert _get_family("") == ""


# ─────────────────────────────────────────────────────────────────────
# _allocate_eligible family cap 적용
# ─────────────────────────────────────────────────────────────────────

class TestAllocatorFamilyCap:
    # density_ratio=0.25 명시 — family cap 발동 검증 목적.
    # tier 자동화(소형 0.15)로는 local cap 이 먼저 발동해 family cap 검증 불가.
    _DENSITY_OVERRIDE = 0.25

    def test_consultation_family_cap_2(self):
        """consultation_desk ×2 + consultation_table ×1 = 3 투입 → 2개만 통과, 1개 Family_Exceeded."""
        eligible = [
            _obj("consultation_desk", 700, 600),
            _obj("consultation_desk", 700, 600),
            _obj("consultation_table", 500, 700),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=self._DENSITY_OVERRIDE)
        # family=consultation 총 2개 허용
        family_accepted = sum(
            1 for o in accepted
            if _get_family(o["object_type"]) == "consultation"
        )
        assert family_accepted == 2

        family_rejects = [
            r for r in log["rejection_details"]
            if r["reason"] == "Family_Exceeded"
        ]
        assert len(family_rejects) == 1
        assert family_rejects[0]["family"] == "consultation"
        assert family_rejects[0]["family_cap"] == 2

    def test_photo_family_cap_1(self):
        """photo_wall + photo_island = 2 투입 → 1개만 통과."""
        eligible = [
            _obj("photo_wall", 1900, 200),
            _obj("photo_island", 1500, 1000),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        photo_accepted = sum(
            1 for o in accepted
            if _get_family(o["object_type"]) == "photo"
        )
        assert photo_accepted == 1

        family_rejects = [
            r for r in log["rejection_details"]
            if r["reason"] == "Family_Exceeded" and r["family"] == "photo"
        ]
        assert len(family_rejects) == 1

    def test_shelf_family_cap_1(self):
        """[S-8f v2] shelf_wall×2 + shelf_standard×1 + shelf_3tier×1 = 4 → 1 통과, 3 Family_Exceeded."""
        eligible = [
            _obj("shelf_wall", 900, 500),
            _obj("shelf_wall", 900, 500),
            _obj("shelf_standard", 800, 400),
            _obj("shelf_3tier", 900, 500),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        shelf_accepted = sum(
            1 for o in accepted
            if _get_family(o["object_type"]) == "shelf"
        )
        assert shelf_accepted == 1
        assert sum(1 for r in log["rejection_details"]
                   if r["reason"] == "Family_Exceeded" and r["family"] == "shelf") == 3

    def test_partition_family_cap_1(self):
        """partition_wall_I + partition_wall_L = 2 → 1 통과. 18평 소형 기준."""
        eligible = [
            _obj("partition_wall_I", 2000, 150),
            _obj("partition_wall_L", 2000, 150),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        partition_accepted = sum(
            1 for o in accepted
            if _get_family(o["object_type"]) == "partition"
        )
        assert partition_accepted == 1

    def test_display_family_cap_2(self):
        """display_table ×2 + display_table_standard ×1 = 3 → 2 통과."""
        eligible = [
            _obj("display_table", 1200, 600),
            _obj("display_table", 1200, 600),
            _obj("display_table_standard", 1200, 600),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        display_accepted = sum(
            1 for o in accepted
            if _get_family(o["object_type"]) == "display"
        )
        assert display_accepted == 2


# ─────────────────────────────────────────────────────────────────────
# counter self-family cap (2026-04-22 S-8f 튜닝)
# ─────────────────────────────────────────────────────────────────────

class TestCounterSelfFamily:
    def test_counter_2_brand_both_pass_after_brand_max(self):
        """1-2 #527 후속: brand counter 2 → 둘 다 통과 (cap raise = max(default 1, brand 2) = 2).

        매뉴얼 작성자 의도 보존 (POS / 증정품 같이 의미적으로 다른 인스턴스). 이전 cap=1 강제는
        매뉴얼 의도 무시 → 5-7 trigger 케이스 발생 → #527 에서 brand max 처리로 수정.
        """
        eligible = [_obj("counter", 1500, 600, from_brand=True) for _ in range(2)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        counter_accepted = sum(1 for o in accepted if o["object_type"] == "counter")
        # 1-2 #527 후: brand 2 → max(1, 2) = 2 둘 다 통과
        assert counter_accepted == 2

        # Family_Exceeded reject 0건 (cap raise 로 둘 다 수용)
        family_rejects = [
            r for r in log["rejection_details"]
            if r["reason"] == "Family_Exceeded" and r["family"] == "counter"
        ]
        assert len(family_rejects) == 0

    def test_counter_2_non_brand_capped_to_1(self):
        """non-brand counter 2 → 1개만 (default cap 보호 — brand max 무관).

        default 풀에서 자동 보충된 obj 는 brand 매뉴얼 의도 X → cap=1 그대로.
        """
        eligible = [_obj("counter", 1500, 600, from_brand=False) for _ in range(2)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        counter_accepted = sum(1 for o in accepted if o["object_type"] == "counter")
        assert counter_accepted == 1
        family_rejects = [
            r for r in log["rejection_details"]
            if r["reason"] == "Family_Exceeded" and r["family"] == "counter"
        ]
        assert len(family_rejects) == 1
        assert family_rejects[0]["family_cap"] == 1

    def test_counter_1_passes(self):
        """counter 1개는 family cap 안 걸림."""
        eligible = [_obj("counter", 1500, 600)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        assert sum(1 for o in accepted if o["object_type"] == "counter") == 1


# ─────────────────────────────────────────────────────────────────────
# family 없는 기물은 family cap 영향 없음
# ─────────────────────────────────────────────────────────────────────

class TestNoFamilyTypes:
    def test_kiosk_not_affected_by_family(self):
        """kiosk 는 family 없음. local cap 만 적용 — single-type FAMILY_CAPS 미등록."""
        eligible = [_obj("kiosk", 800, 800) for _ in range(2)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)
        kiosk_accepted = sum(1 for o in accepted if o["object_type"] == "kiosk")
        # kiosk family 미등록 → cap 안 걸리므로 둘 다 통과 (local cap 에만 의존)
        assert kiosk_accepted == 2

        # Family_Exceeded 없음
        family_rejects = [
            r for r in log["rejection_details"]
            if r["reason"] == "Family_Exceeded"
        ]
        assert len(family_rejects) == 0


# ─────────────────────────────────────────────────────────────────────
# 통합 시나리오 — brand 필수 기물 보호 확증
# ─────────────────────────────────────────────────────────────────────

class TestBrandProtectionScenario:
    def test_lumia_brand_protection_after_brand_max(self):
        """1-2 #527 후속: LUMIA 시나리오. brand consultation 3 → cap raise = max(2, 3) = 3 → 셋 다 통과.

        이전 (#527 전): family cap 2 강제 → consultation_table drop. test 의도 = "consultation 2 제한 + photo_wall 보호".
        이후 (#527): brand 매뉴얼이 명시한 3개 의도 보존 → cap raise → 셋 다 통과. photo_wall / counter 도 모두 통과.

        photo_wall 보호 메커니즘 = brand_count 우선 정렬 + cap_raise. drop 없음.
        """
        eligible = [
            # consultation family 3개 (brand max 후 cap=3)
            _obj("consultation_desk", 700, 600, from_brand=True),
            _obj("consultation_desk", 700, 600, from_brand=True),
            _obj("consultation_table", 500, 700, from_brand=True),
            # photo (brand 필수)
            _obj("photo_wall", 1900, 200, from_brand=True),
            # counter
            _obj("counter", 1500, 600, from_brand=True),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.25)

        # photo_wall 반드시 통과 (brand 우선 보호)
        assert any(o["object_type"] == "photo_wall" for o in accepted)
        # counter 통과
        assert any(o["object_type"] == "counter" for o in accepted)
        # consultation 은 brand 3 명시 → cap raise → 3 통과
        consultation_count = sum(
            1 for o in accepted if _get_family(o["object_type"]) == "consultation"
        )
        assert consultation_count == 3, (
            f"#527 brand max 패턴: brand 3 명시 → cap=3 raise → 3 통과 기대 (실제 {consultation_count})"
        )
