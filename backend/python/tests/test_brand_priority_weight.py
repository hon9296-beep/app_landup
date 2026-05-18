"""
sort_eligible_with_brand_weight() 검증 — 2026-04-22 S-8c.

제미나이 자문 (reports/to_gemini/2026-04-22_brand_max_priority_weighting.md):
  - BRAND_BONUS = +20 — 같은 등급 내 우선, 위계 파괴 안 함
  - 첫 1개만 가중 — counter ×5 같은 스팸 방어
  - tie-break = footprint ASC — 결정론 + 예산 효율

검증 대상:
  1. 상수 BRAND_BONUS = 20 회귀 방지
  2. brand 첫 1개만 +20 가중 (같은 obj_type 2번째부터는 default 점수)
  3. 위계 보존 — brand kiosk(45+20=65) 가 default counter(95) 자리 못 뺏음
  4. 위계 추월 — brand counter(95+20=115) 가 default partition(98) 추월
  5. tie-break footprint ASC — 같은 priority 면 작은 footprint 먼저
  6. 결정론 — 같은 입력 → 같은 출력
  7. 입력 mutate 안 함

상세: reports/AD/worklist/2026-04-22_worklist.md S-8c
"""
from app.nodes_small.object_selection import (
    BRAND_BONUS,
    calculate_footprint,
    sort_eligible_with_brand_weight,
)


def _obj(obj_type: str, w: int = 1000, d: int = 500, from_brand: bool = False) -> dict:
    """테스트 obj factory."""
    return {
        "object_type": obj_type,
        "width_mm": w,
        "depth_mm": d,
        "_from_brand": from_brand,
    }


# ─────────────────────────────────────────────────────────────────────
# 상수 회귀 방지
# ─────────────────────────────────────────────────────────────────────

class TestBrandBonusConstant:
    def test_brand_bonus_is_20(self):
        """제미나이 자문 결정값. +50/+100 은 위계 파괴 위험."""
        assert BRAND_BONUS == 20


# ─────────────────────────────────────────────────────────────────────
# brand 가중치 — 첫 1개만 적용
# ─────────────────────────────────────────────────────────────────────

class TestBrandFirstOnly:
    def test_single_brand_obj_gets_bonus(self):
        """단일 brand obj: priority=45 → 65 로 추월 가능."""
        eligible = [
            _obj("kiosk", from_brand=True),     # 45 + 20 = 65
            _obj("shelf_wall", from_brand=False),  # 65
        ]
        result = sort_eligible_with_brand_weight(eligible)
        # tie-break (둘 다 65) 후 footprint 작은 것 먼저
        types = [o["object_type"] for o in result]
        # kiosk 65 vs shelf_wall 65 → footprint 비교
        # kiosk: (800+600)×(800+600+0+1200) = 1400×2600 = 3.64M (default obj 1000×500 wrong, 다시 계산)
        # 위 _obj() 기본 1000×500 으로 계산:
        # kiosk (near): (1000+600)×(500+600+0+1200) = 1600×2300 = 3.68M
        # shelf_wall (flush): 1000×(500+600+1200) = 1000×2300 = 2.30M
        # → shelf_wall 작음, footprint ASC tie-break 으로 shelf_wall 먼저
        assert types == ["shelf_wall", "kiosk"]

    def test_brand_counter_x5_only_first_bonus(self):
        """counter ×5 brand 요청: 첫 1개만 +20, 나머지 4개는 95 그대로."""
        eligible = [
            _obj("counter", w=1500, d=600, from_brand=True),  # 1번째: 95+20=115
            _obj("counter", w=1500, d=600, from_brand=True),  # 2번째: 95
            _obj("counter", w=1500, d=600, from_brand=True),  # 3번째: 95
            _obj("counter", w=1500, d=600, from_brand=True),  # 4번째: 95
            _obj("counter", w=1500, d=600, from_brand=True),  # 5번째: 95
            _obj("partition_wall_I", w=2000, d=150, from_brand=False),  # 98
        ]
        result = sort_eligible_with_brand_weight(eligible)
        types = [o["object_type"] for o in result]
        # 1번째 counter (115) > partition (98) > 나머지 counter 4개 (95)
        assert types[0] == "counter"
        assert types[1] == "partition_wall_I"
        assert types[2:] == ["counter"] * 4

    def test_brand_bonus_per_obj_type_independent(self):
        """obj_type 별 첫 등장 brand 만 가중. counter/photo_wall 따로 카운트."""
        eligible = [
            _obj("counter", from_brand=True),
            _obj("counter", from_brand=True),
            _obj("photo_wall", from_brand=True),
            _obj("photo_wall", from_brand=True),
        ]
        result = sort_eligible_with_brand_weight(eligible)
        # counter 1번째: 95+20=115, photo_wall 1번째: 85+20=105
        # counter 2번째: 95, photo_wall 2번째: 85
        # 결과: counter(115), photo_wall(105), counter(95), photo_wall(85)
        types = [o["object_type"] for o in result]
        assert types[0] == "counter"
        assert types[1] == "photo_wall"
        assert types[2] == "counter"
        assert types[3] == "photo_wall"


# ─────────────────────────────────────────────────────────────────────
# 위계 보존 — brand 가중치가 공간 위계 파괴 안 함
# ─────────────────────────────────────────────────────────────────────

class TestHierarchyPreservation:
    def test_brand_kiosk_cannot_beat_default_counter(self):
        """brand kiosk(45+20=65) 는 default counter(95) 보다 뒤."""
        eligible = [
            _obj("kiosk", from_brand=True),       # 65
            _obj("counter", from_brand=False),    # 95
        ]
        result = sort_eligible_with_brand_weight(eligible)
        types = [o["object_type"] for o in result]
        assert types == ["counter", "kiosk"], (
            f"위계 파괴: brand kiosk 가 default counter 자리 뺏음. 결과: {types}"
        )

    def test_brand_signage_cannot_beat_default_partition(self):
        """brand signage_stand(35+20=55) 는 default partition(98) 보다 한참 뒤."""
        eligible = [
            _obj("signage_stand", from_brand=True),     # 55
            _obj("partition_wall_I", from_brand=False), # 98
        ]
        result = sort_eligible_with_brand_weight(eligible)
        types = [o["object_type"] for o in result]
        assert types == ["partition_wall_I", "signage_stand"]


# ─────────────────────────────────────────────────────────────────────
# 위계 추월 — brand 가 같은/낮은 등급 default 추월
# ─────────────────────────────────────────────────────────────────────

class TestHierarchyOvertake:
    def test_brand_counter_beats_default_partition(self):
        """brand counter(95+20=115) > default partition(98)."""
        eligible = [
            _obj("partition_wall_I", from_brand=False),  # 98
            _obj("counter", from_brand=True),            # 115
        ]
        result = sort_eligible_with_brand_weight(eligible)
        types = [o["object_type"] for o in result]
        assert types == ["counter", "partition_wall_I"]

    def test_brand_shelf_wall_beats_default_shelf_wall(self):
        """brand shelf_wall(65+20=85) > default shelf_wall(65). 첫 brand 만 가중."""
        eligible = [
            _obj("shelf_wall", from_brand=False),  # 65
            _obj("shelf_wall", from_brand=True),   # 85
            _obj("shelf_wall", from_brand=False),  # 65
        ]
        result = sort_eligible_with_brand_weight(eligible)
        # brand 가 1번째 위치 → 가중 → 85
        # default 둘은 65, 같은 footprint → 입력 순서 유지
        # 결과: brand_shelf(85), default(65)1, default(65)2
        assert result[0].get("_from_brand") is True
        assert result[1].get("_from_brand") is False
        assert result[2].get("_from_brand") is False


# ─────────────────────────────────────────────────────────────────────
# tie-break — footprint ASC
# ─────────────────────────────────────────────────────────────────────

class TestFootprintTieBreak:
    def test_same_priority_smaller_footprint_first(self):
        """priority 동일 (display_table 90, display_table_standard 90):
        footprint 작은 것 먼저."""
        # display_table 큰 사이즈 vs 작은 사이즈
        big = _obj("display_table", w=2000, d=1000)   # footprint 큼
        small = _obj("display_table", w=600, d=400)    # footprint 작음
        eligible = [big, small]  # 입력은 큰 것 먼저
        result = sort_eligible_with_brand_weight(eligible)
        assert result[0]["width_mm"] == 600, "작은 footprint 가 먼저 와야 함"
        assert result[1]["width_mm"] == 2000

    def test_same_priority_same_footprint_input_order(self):
        """priority + footprint 모두 동일 시 입력 순서 (3차 tie-break) 유지."""
        a = _obj("display_table", w=1000, d=500)
        a["id"] = "A"
        b = _obj("display_table", w=1000, d=500)
        b["id"] = "B"
        eligible = [a, b]
        result = sort_eligible_with_brand_weight(eligible)
        assert result[0]["id"] == "A"
        assert result[1]["id"] == "B"


# ─────────────────────────────────────────────────────────────────────
# 결정론 (Determinism)
# ─────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        """같은 입력 → 항상 같은 출력 순서."""
        eligible = [
            _obj("counter", from_brand=True),
            _obj("photo_wall", from_brand=False),
            _obj("partition_wall_I", from_brand=False),
            _obj("shelf_wall", from_brand=False),
            _obj("kiosk", from_brand=True),
            _obj("display_table", from_brand=False),
        ]
        result_1 = sort_eligible_with_brand_weight(list(eligible))
        result_2 = sort_eligible_with_brand_weight(list(eligible))
        result_3 = sort_eligible_with_brand_weight(list(eligible))
        types_1 = [o["object_type"] for o in result_1]
        types_2 = [o["object_type"] for o in result_2]
        types_3 = [o["object_type"] for o in result_3]
        assert types_1 == types_2 == types_3, (
            f"결정론 위반: {types_1} != {types_2} != {types_3}"
        )


# ─────────────────────────────────────────────────────────────────────
# 입력 불변 (Immutability of input)
# ─────────────────────────────────────────────────────────────────────

class TestInputImmutability:
    def test_input_list_not_mutated(self):
        """함수 호출 후 입력 리스트 순서/내용 보존."""
        eligible = [
            _obj("counter", from_brand=True),
            _obj("photo_wall", from_brand=False),
            _obj("partition_wall_I", from_brand=False),
        ]
        snapshot_types = [o["object_type"] for o in eligible]
        snapshot_ids = [id(o) for o in eligible]

        sort_eligible_with_brand_weight(eligible)

        post_types = [o["object_type"] for o in eligible]
        post_ids = [id(o) for o in eligible]
        assert snapshot_types == post_types, "입력 순서 변경됨 (mutate)"
        assert snapshot_ids == post_ids, "입력 obj id 변경됨"

    def test_obj_dicts_not_mutated(self):
        """obj dict 자체 수정 안 함 (e.g. _brand_bonus_applied 같은 키 추가 안 함)."""
        eligible = [_obj("counter", from_brand=True)]
        before_keys = set(eligible[0].keys())
        sort_eligible_with_brand_weight(eligible)
        after_keys = set(eligible[0].keys())
        assert before_keys == after_keys, f"obj 키 변경: {after_keys - before_keys}"


# ─────────────────────────────────────────────────────────────────────
# 종합 시나리오 — LUMIA 18평 가상 케이스
# ─────────────────────────────────────────────────────────────────────

class TestRealisticScenario:
    def test_lumia_18py_typical_eligible(self):
        """뷰티 매장 18평 가상: brand counter/photo_wall + default 보충."""
        eligible = [
            # brand 매뉴얼 명시
            _obj("counter", w=1500, d=600, from_brand=True),
            _obj("photo_wall", w=1900, d=200, from_brand=True),
            _obj("test_bar", w=1200, d=600, from_brand=True),
            # default 보충
            _obj("partition_wall_I", w=2000, d=150, from_brand=False),
            _obj("shelf_wall", w=900, d=500, from_brand=False),
            _obj("shelf_wall", w=900, d=500, from_brand=False),
        ]
        result = sort_eligible_with_brand_weight(eligible)
        types = [o["object_type"] for o in result]
        # 점수 정리:
        #   counter(brand) 95+20=115 ← 1위
        #   photo_wall(brand) 85+20=105 ← 2위
        #   partition_wall_I 98 ← 3위
        #   test_bar(brand) 75+20=95 ← 4위
        #   shelf_wall × 2 (65) ← 5,6위
        assert types[0] == "counter"
        assert types[1] == "photo_wall"
        assert types[2] == "partition_wall_I"
        assert types[3] == "test_bar"
        assert types[4] == "shelf_wall"
        assert types[5] == "shelf_wall"
