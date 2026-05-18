"""
calculate_footprint() 검증 — 2026-04-22 S-8a.

제미나이 자문 반영 (reports/AD/2026-04-22_cap_computing_design_question.md):
  - 기존 A안 공식 `(w + front + 1200) × (d + back + 1200)` 는 1200mm 이중 가산 버그.
  - VMD_WALL_ATTACHMENT 기반 벽부착 유형별 분기로 해결.
    - flush (벽밀착): width × (depth + front + BUFFER)
    - near  (벽근처): (width + NEAR_SIDE) × (depth + front + back + BUFFER)
    - free  (아일랜드): (width + BUFFER) × (depth + front + back + BUFFER)
    - either (가변): free 와 동일

검증 대상:
  1. 각 attachment 유형별 공식 계산 결과 회귀 방지
  2. 미등록 obj_type 은 free 로 처리
  3. 1200 이중 가산 버그 해결 확증 (flush 의 width 축엔 BUFFER 없음)
  4. 아일랜드(free) 는 양쪽 축 모두 BUFFER 가산 (사방 접근)

상세: reports/AD/worklist/2026-04-22_worklist.md S-8a
"""
from app.nodes_small.object_selection import (
    BUFFER_MM,
    NEAR_SIDE_BUFFER_MM,
    calculate_footprint,
)


# ─────────────────────────────────────────────────────────────────────
# 상수 회귀 방지
# ─────────────────────────────────────────────────────────────────────

class TestBufferConstants:
    def test_buffer_mm_is_1200(self):
        """메인 보행 동선 여유 폭. VMD 실무 기준."""
        assert BUFFER_MM == 1200

    def test_near_side_buffer_is_600(self):
        """벽근처 기물 좌/우 여유 폭."""
        assert NEAR_SIDE_BUFFER_MM == 600


# ─────────────────────────────────────────────────────────────────────
# flush (벽밀착): back 미가산, width 축 버퍼 없음
# ─────────────────────────────────────────────────────────────────────

class TestFootprintFlushAttachment:
    def test_shelf_wall_flush(self):
        """shelf_wall: DIRECTIONAL_CLEARANCE front=600, back=0, attachment=flush."""
        fp = calculate_footprint("shelf_wall", 900, 500)
        expected = 900 * (500 + 600 + BUFFER_MM)  # 900 × 2300 = 2,070,000
        assert fp == expected

    def test_photo_wall_flush(self):
        """photo_wall: front=2000, back=0, attachment=flush."""
        fp = calculate_footprint("photo_wall", 1900, 200)
        expected = 1900 * (200 + 2000 + BUFFER_MM)  # 1900 × 3400 = 6,460,000
        assert fp == expected

    def test_partition_wall_I_flush(self):
        """partition_wall_I: front=0, back=0, attachment=flush."""
        fp = calculate_footprint("partition_wall_I", 2000, 150)
        expected = 2000 * (150 + 0 + BUFFER_MM)  # 2000 × 1350 = 2,700,000
        assert fp == expected

    def test_partition_wall_L_flush(self):
        """partition_wall_L: front=0, back=0, attachment=flush."""
        fp = calculate_footprint("partition_wall_L", 2400, 150)
        expected = 2400 * (150 + 0 + BUFFER_MM)
        assert fp == expected

    def test_shelf_standard_flush(self):
        """shelf_standard: front=600, back=0, attachment=flush."""
        fp = calculate_footprint("shelf_standard", 800, 400)
        expected = 800 * (400 + 600 + BUFFER_MM)
        assert fp == expected

    def test_shelf_3tier_flush(self):
        """shelf_3tier: front=600, back=0, attachment=flush."""
        fp = calculate_footprint("shelf_3tier", 900, 500)
        expected = 900 * (500 + 600 + BUFFER_MM)
        assert fp == expected


# ─────────────────────────────────────────────────────────────────────
# near (벽근처): 좌/우 여유 + 앞/뒤 공간
# ─────────────────────────────────────────────────────────────────────

class TestFootprintNearAttachment:
    def test_counter_near(self):
        """counter: front=900, back=600, attachment=near."""
        fp = calculate_footprint("counter", 1500, 600)
        expected = (1500 + NEAR_SIDE_BUFFER_MM) * (600 + 900 + 600 + BUFFER_MM)
        # (1500+600) × (600+900+600+1200) = 2100 × 3300 = 6,930,000
        assert fp == expected

    def test_kiosk_near(self):
        """kiosk: front=600, back=0, attachment=near."""
        fp = calculate_footprint("kiosk", 800, 800)
        expected = (800 + NEAR_SIDE_BUFFER_MM) * (800 + 600 + 0 + BUFFER_MM)
        assert fp == expected


# ─────────────────────────────────────────────────────────────────────
# free (아일랜드): 사방 버퍼
# ─────────────────────────────────────────────────────────────────────

class TestFootprintFreeAttachment:
    def test_display_table_free(self):
        """display_table: front=0, back=0, attachment=free."""
        fp = calculate_footprint("display_table", 1200, 600)
        expected = (1200 + BUFFER_MM) * (600 + 0 + 0 + BUFFER_MM)
        # 2400 × 1800 = 4,320,000
        assert fp == expected

    def test_photo_island_free(self):
        """photo_island: front=1500, back=0, attachment=free."""
        fp = calculate_footprint("photo_island", 1500, 1000)
        expected = (1500 + BUFFER_MM) * (1000 + 1500 + 0 + BUFFER_MM)
        assert fp == expected

    def test_character_bbox_free(self):
        """character_bbox: front=0, back=0, attachment=free."""
        fp = calculate_footprint("character_bbox", 800, 800)
        expected = (800 + BUFFER_MM) * (800 + 0 + 0 + BUFFER_MM)
        assert fp == expected

    def test_signage_stand_free(self):
        """signage_stand: front=0, back=0, attachment=free."""
        fp = calculate_footprint("signage_stand", 400, 400)
        expected = (400 + BUFFER_MM) * (400 + 0 + 0 + BUFFER_MM)
        assert fp == expected


# ─────────────────────────────────────────────────────────────────────
# either (가변): free 와 동일 보수 계산
# ─────────────────────────────────────────────────────────────────────

class TestFootprintEitherAttachment:
    def test_banner_stand_either_equals_free(self):
        """banner_stand: front=0, back=0, attachment=either → free 공식 적용."""
        fp = calculate_footprint("banner_stand", 600, 600)
        expected = (600 + BUFFER_MM) * (600 + 0 + 0 + BUFFER_MM)
        assert fp == expected


# ─────────────────────────────────────────────────────────────────────
# 미등록 타입 처리 (방어 로직)
# ─────────────────────────────────────────────────────────────────────

class TestFootprintUnknownType:
    def test_unknown_type_defaults_to_free(self):
        """등록되지 않은 obj_type: VMD_WALL_ATTACHMENT 미매칭 → 'free' 로 처리."""
        fp = calculate_footprint("unknown_type_xyz", 1000, 1000)
        expected = (1000 + BUFFER_MM) * (1000 + 0 + 0 + BUFFER_MM)
        assert fp == expected

    def test_empty_obj_type_defaults_to_free(self):
        """빈 문자열 obj_type: 'free' 로 처리."""
        fp = calculate_footprint("", 500, 500)
        expected = (500 + BUFFER_MM) * (500 + 0 + 0 + BUFFER_MM)
        assert fp == expected


# ─────────────────────────────────────────────────────────────────────
# 1200 이중 가산 버그 해결 확증
# ─────────────────────────────────────────────────────────────────────

class TestFootprintBugFix:
    """제미나이 자문 (Q4): 기존 A안 공식의 1200 이중 가산 버그 해결 확증."""

    def test_flush_no_buffer_on_width_axis(self):
        """flush 기물의 width 축엔 BUFFER 가산 없음.

        벽부착 기물은 좌/우로 다른 flush 기물이 연속 붙을 수 있어 좌/우 통로 불필요.
        기존 A안 공식은 (w + front + 1200) 으로 width 에도 가산 → 면적 과대.
        """
        fp = calculate_footprint("shelf_wall", 1000, 500)
        # 새 공식: 1000 × (500 + 600 + 1200) = 1000 × 2300 = 2,300,000
        assert fp == 1000 * (500 + 600 + BUFFER_MM)
        # 비교 — 기존 A안 버그 공식 (참고용 계산, 코드엔 없음):
        # (1000 + 600 + 1200) × (500 + 0 + 1200) = 2800 × 1700 = 4,760,000
        # 버그 공식은 실제 footprint 의 약 2 배 과대 계상
        legacy_buggy = (1000 + 600 + 1200) * (500 + 0 + 1200)
        assert fp < legacy_buggy, (
            f"수정된 flush footprint({fp}) 는 버그 공식({legacy_buggy}) 보다 작아야 함"
        )

    def test_free_has_buffer_on_both_axes(self):
        """free (아일랜드) 는 width/depth 양쪽 모두 BUFFER 가산.

        사방 접근이 정당한 아일랜드 형태에선 양축 가산이 맞음.
        """
        fp = calculate_footprint("display_table", 1000, 500)
        # (1000+1200) × (500+1200) = 2200 × 1700 = 3,740,000
        assert fp == (1000 + BUFFER_MM) * (500 + 0 + 0 + BUFFER_MM)

    def test_flush_smaller_than_free_same_dimensions(self):
        """동일 w/d 에서 flush footprint 는 free 보다 작아야 함.

        flush 는 한 축만, free 는 두 축 모두 BUFFER 가산하므로.
        (flush 와 free 모두 front=0, back=0 인 타입 동원)
        """
        # partition_wall_I (flush, front=0, back=0)
        fp_flush = calculate_footprint("partition_wall_I", 1000, 500)
        # display_table (free, front=0, back=0) — 동일 front/back
        fp_free = calculate_footprint("display_table", 1000, 500)
        assert fp_flush < fp_free, (
            f"flush({fp_flush}) 가 free({fp_free}) 보다 작아야 함 — 벽부착 절약 효과"
        )


# ─────────────────────────────────────────────────────────────────────
# 최소값 보장 (0 division 방어)
# ─────────────────────────────────────────────────────────────────────

class TestFootprintMinimum:
    def test_zero_dimensions_returns_one(self):
        """width=0, depth=0 극단 케이스: max(1, ...) 로 0 방어."""
        # attachment="free", clearance front=0, back=0
        fp = calculate_footprint("unknown", 0, 0)
        # (0 + 1200) × (0 + 0 + 0 + 1200) = 1,440,000
        assert fp >= 1
