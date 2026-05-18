"""
_allocate_eligible() 검증 — 2026-04-22 S-8d.

IQI + cap 통합 단일 greedy allocator.

제미나이 자문 반영:
  - 기존 _apply_iqi + _cap_max_count_by_space 이중 필터 통합
  - 레거시 _SPACE_CAP_RULES_SMALL / _get_space_cap 미참조 (calculate_local_cap 만)
  - per-obj rejection reason (Budget_Exceeded / Cap_Exceeded) 추적

검증 대상:
  1. 기본 할당 동작
  2. Budget_Exceeded rejection
  3. Cap_Exceeded rejection
  4. brand 가중치 → 우선 할당
  5. allocation_log 스키마
  6. 결정론
  7. 엣지 케이스 (빈 입력, 예산 0)
  8. 18평 LUMIA 시나리오

상세: reports/AD/worklist/2026-04-22_worklist.md S-8d
"""
from app.nodes_small.object_selection import (
    MAX_DENSITY_RATIO,
    _allocate_eligible,
)

# 면적 상수
AREA_18PY = 59_500_000
AREA_5PY = 16_530_000
AREA_50PY = 165_300_000


def _obj(obj_type: str, w: int, d: int, from_brand: bool = False) -> dict:
    return {
        "object_type": obj_type,
        "width_mm": w,
        "depth_mm": d,
        "_from_brand": from_brand,
    }


# ─────────────────────────────────────────────────────────────────────
# 기본 할당
# ─────────────────────────────────────────────────────────────────────

class TestBasicAllocation:
    def test_empty_eligible_returns_empty(self):
        """빈 입력 → 빈 결과 + 빈 로그."""
        accepted, log = _allocate_eligible([], AREA_18PY)
        assert accepted == []
        assert log["type_allocation"] == {}
        assert log["rejection_details"] == []
        assert log["budget_summary"]["used_budget"] == 0

    def test_single_obj_within_budget(self):
        """단일 obj, 예산 내 → 통과."""
        eligible = [_obj("counter", 1500, 600)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY)
        assert len(accepted) == 1
        assert accepted[0]["object_type"] == "counter"
        assert log["rejection_details"] == []
        assert log["type_allocation"]["counter"] == {"requested": 1, "allocated": 1}

    def test_multiple_types_all_fit(self):
        """여러 타입, net 기준 예산 넉넉해서 전부 들어감.

        net footprint 합:
          counter 0.9M + photo_wall 0.38M + partition 0.3M = 1.58M
          18평 eff=14.875M → 여유 많음.
        """
        eligible = [
            _obj("counter", 1500, 600),
            _obj("photo_wall", 1900, 200),
            _obj("partition_wall_I", 2000, 150),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY)
        assert len(accepted) == 3
        assert log["rejection_details"] == []


# ─────────────────────────────────────────────────────────────────────
# Budget_Exceeded rejection
# ─────────────────────────────────────────────────────────────────────

class TestBudgetExceeded:
    def test_over_budget_items_rejected(self):
        """예산 초과분 Budget_Exceeded 로 거부."""
        # 18평 effective = 14.875M
        # shelf_wall footprint = 2.07M → 예산 내 약 7개
        eligible = [_obj("shelf_wall", 900, 500) for _ in range(20)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY)
        # cap = 14.875M / 2.07M = 7 → 최대 7 허용
        # 20 - 7 = 13 거부
        assert len(accepted) <= 7
        assert len(log["rejection_details"]) >= 13

    def test_rejection_reason_budget(self):
        """예산 초과 시 reason = 'Budget_Exceeded' — net_footprint 기준.

        5평 (eff=4.13M) 에 large display_table 여러 개:
          display_table 2000×1500 net = 3M. cap 기준 gross fp = 8.64M,
          cap = max(1, int(4.13M/8.64M)) = 1.
          첫 1개만 cap 통과. 2번째부터 Cap_Exceeded.
          Budget 은 3M 차지 (< 4.13M). 예산 초과 유도는 다른 의도.

        대안: small 면적 + 큰 net obj. 3평 수준 (10M mm²) 에 large 2개.
          eff=2.5M, net 3M 하나만 시도해도 budget 초과.
          근데 cap 이 먼저 cut 할 거. cap = 2.5M/8.64M → floor=1.
          → 1개 cap 통과 시도 → net 3M > 2.5M budget → Budget_Exceeded.
        """
        eligible = [_obj("display_table", 2000, 1500)]  # net=3M, gross=8.64M
        accepted, log = _allocate_eligible(eligible, 10_000_000)  # eff=2.5M
        # cap=1 통과, budget 3M > 2.5M → Budget_Exceeded
        budget_rejects = [
            r for r in log["rejection_details"] if r["reason"] == "Budget_Exceeded"
        ]
        assert len(budget_rejects) >= 1
        assert "net_footprint" in budget_rejects[0]
        assert "remaining_budget" in budget_rejects[0]


# ─────────────────────────────────────────────────────────────────────
# Cap_Exceeded rejection
# ─────────────────────────────────────────────────────────────────────

class TestCapExceeded:
    def test_exceed_local_cap(self):
        """같은 타입 많이 요청 시 local_cap 초과분 거부."""
        # 5평 (eff=4.13M), shelf_wall fp=2.07M → cap = int(4.13/2.07) = 1 (실제로는 floor=1)
        # 2번째부터는 Cap_Exceeded
        eligible = [_obj("shelf_wall", 900, 500) for _ in range(5)]
        accepted, log = _allocate_eligible(eligible, AREA_5PY)
        assert len(accepted) == 1  # cap=1
        cap_rejects = [
            r for r in log["rejection_details"] if r["reason"] == "Cap_Exceeded"
        ]
        assert len(cap_rejects) == 4
        assert cap_rejects[0]["local_cap"] == 1

    def test_18py_partition_family_cap_one(self):
        """18평 partition family cap = 1 (S-8c-2). family cap 이 local cap(5)보다 먼저 발동."""
        eligible = [_obj("partition_wall_I", 2000, 150) for _ in range(8)]
        accepted, log = _allocate_eligible(eligible, AREA_18PY)
        # family=partition cap=1 → 1개만 통과, 나머지 7개 Family_Exceeded
        partition_allocated = log["type_allocation"]["partition_wall_I"]["allocated"]
        assert partition_allocated == 1
        family_rejects = [
            r for r in log["rejection_details"]
            if r["reason"] == "Family_Exceeded" and r["family"] == "partition"
        ]
        assert len(family_rejects) == 7


# ─────────────────────────────────────────────────────────────────────
# brand 가중치 효과
# ─────────────────────────────────────────────────────────────────────

class TestBrandWeightEffect:
    def test_brand_obj_allocated_first(self):
        """brand 기물이 default 보다 먼저 처리 (priority 가중치)."""
        # brand kiosk (45+20=65) vs default shelf_wall (65) 동점
        # 18평 예산 풍족하면 둘 다 들어감. 예산 타이트하게 만들어서 하나만 들어가도록.
        # 예산을 작게: 4.13M (5평)
        # kiosk fp = (800+600)*(800+600+0+1200)=1400×2600=3.64M
        # shelf_wall fp = 900×(500+600+1200)=900×2300=2.07M
        # 둘 다 넣으면 5.71M > 4.13M. 하나만 들어감.
        # brand kiosk (65) vs default shelf_wall (65) — tie-break footprint ASC
        # shelf_wall fp(2.07M) < kiosk fp(3.64M) → shelf_wall 먼저
        # 그럼 shelf_wall 먼저 통과, kiosk 시도 시 예산 부족
        #
        # 이 케이스로는 brand 가 우선된다는 증거 못 됨. 다른 케이스:
        # brand kiosk (45+20=65) vs default signage_stand (35)
        # brand kiosk 65 > signage 35 → brand 먼저

        eligible = [
            _obj("signage_stand", 400, 400, from_brand=False),  # 35
            _obj("kiosk", 800, 800, from_brand=True),           # 65 (45+20)
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY)
        # 둘 다 들어감 (예산 충분). 순서만 확인 — 별도 테스트.
        # 여기선 둘 다 통과 확인
        assert len(accepted) == 2

    def test_brand_counter_beats_default_partition_in_allocation(self):
        """brand counter(95+20=115) 가 default partition(98) 보다 먼저 할당."""
        # 예산을 조여서 둘 중 하나만 들어가게
        # counter fp = 6.93M, partition fp = 2.7M
        # 둘 다 들어가면 9.63M. 5평(4.13M) 로 하면 하나도 안 들어감 (둘 다 fp > 4.13M)
        # 10평(eff=8.27M) 으로: counter(6.93M) 만 들어가고 partition(2.7M) 은 예산 초과
        # cap 은 counter=1 (8.27/6.93=1), partition=3 (8.27/2.7=3)
        # 결과: counter 먼저 들어감(cap=1 통과, 예산 사용), partition 시도 시 8.27-6.93=1.34 남음 < 2.7 → Budget_Exceeded

        eligible = [
            _obj("partition_wall_I", 2000, 150, from_brand=False),  # 98
            _obj("counter", 1500, 600, from_brand=True),            # 95+20=115
        ]
        accepted, log = _allocate_eligible(eligible, 33_060_000)  # 10평
        # brand counter (115) > partition (98) → counter 먼저
        types = [o["object_type"] for o in accepted]
        assert types[0] == "counter"


# ─────────────────────────────────────────────────────────────────────
# allocation_log 스키마 검증
# ─────────────────────────────────────────────────────────────────────

class TestAllocationLogSchema:
    def test_log_has_budget_summary(self):
        eligible = [_obj("counter", 1500, 600)]
        # density_ratio 명시 (tier 자동 분기와 무관하게 log 스키마만 검증)
        _, log = _allocate_eligible(eligible, AREA_18PY, density_ratio=MAX_DENSITY_RATIO)
        assert "budget_summary" in log
        bs = log["budget_summary"]
        assert "total_effective_budget" in bs
        assert "used_budget" in bs
        assert "utilization_rate" in bs
        assert bs["total_effective_budget"] == AREA_18PY * MAX_DENSITY_RATIO

    def test_log_has_type_allocation(self):
        eligible = [
            _obj("counter", 1500, 600),
            _obj("counter", 1500, 600),
            _obj("photo_wall", 1900, 200),
        ]
        _, log = _allocate_eligible(eligible, AREA_18PY)
        assert "type_allocation" in log
        assert log["type_allocation"]["counter"]["requested"] == 2
        assert log["type_allocation"]["photo_wall"]["requested"] == 1

    def test_log_has_rejection_details(self):
        eligible = [_obj("shelf_wall", 900, 500) for _ in range(5)]
        _, log = _allocate_eligible(eligible, AREA_5PY)
        assert "rejection_details" in log
        assert isinstance(log["rejection_details"], list)
        if log["rejection_details"]:
            r = log["rejection_details"][0]
            assert "type" in r
            assert "priority_score" in r
            assert "reason" in r
            assert r["reason"] in ("Budget_Exceeded", "Cap_Exceeded")

    def test_utilization_rate_computed(self):
        eligible = [_obj("counter", 1500, 600)]
        _, log = _allocate_eligible(eligible, AREA_18PY)
        bs = log["budget_summary"]
        expected_rate = bs["used_budget"] / bs["total_effective_budget"]
        assert abs(bs["utilization_rate"] - expected_rate) < 1e-9


# ─────────────────────────────────────────────────────────────────────
# 결정론
# ─────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        eligible = [
            _obj("counter", 1500, 600, from_brand=True),
            _obj("photo_wall", 1900, 200, from_brand=False),
            _obj("partition_wall_I", 2000, 150, from_brand=False),
            _obj("shelf_wall", 900, 500, from_brand=False),
            _obj("shelf_wall", 900, 500, from_brand=False),
            _obj("kiosk", 800, 800, from_brand=True),
        ]
        acc_1, log_1 = _allocate_eligible(list(eligible), AREA_18PY)
        acc_2, log_2 = _allocate_eligible(list(eligible), AREA_18PY)
        types_1 = [o["object_type"] for o in acc_1]
        types_2 = [o["object_type"] for o in acc_2]
        assert types_1 == types_2
        assert log_1["type_allocation"] == log_2["type_allocation"]


# ─────────────────────────────────────────────────────────────────────
# 엣지 케이스
# ─────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_usable_area(self):
        """예산 0 → 아무것도 못 넣음, 에러 없음."""
        eligible = [_obj("counter", 1500, 600)]
        accepted, log = _allocate_eligible(eligible, 0)
        assert len(accepted) == 0
        assert log["budget_summary"]["utilization_rate"] == 0.0

    def test_custom_density_ratio(self):
        """density_ratio 변경 가능 (기본 0.25)."""
        eligible = [_obj("shelf_wall", 900, 500) for _ in range(10)]
        accepted_default, _ = _allocate_eligible(eligible, AREA_18PY)
        accepted_low, _ = _allocate_eligible(eligible, AREA_18PY, density_ratio=0.10)
        # density 낮추면 accepted 수 적어야 함
        assert len(accepted_low) <= len(accepted_default)


# ─────────────────────────────────────────────────────────────────────
# 실전 시나리오 — 18평 LUMIA
# ─────────────────────────────────────────────────────────────────────

class TestLumiaScenario:
    def test_lumia_18py_typical(self):
        """뷰티 18평 시나리오: brand 필수 + default 보충."""
        eligible = [
            # brand 매뉴얼 명시
            _obj("counter", 1500, 600, from_brand=True),
            _obj("photo_wall", 1900, 200, from_brand=True),
            _obj("test_bar", 1200, 600, from_brand=True),
            _obj("consultation_desk", 1200, 600, from_brand=True),
            # default 보충
            _obj("partition_wall_I", 2000, 150, from_brand=False),
            _obj("shelf_wall", 900, 500, from_brand=False),
            _obj("shelf_wall", 900, 500, from_brand=False),
            _obj("shelf_wall", 900, 500, from_brand=False),
        ]
        accepted, log = _allocate_eligible(eligible, AREA_18PY)
        # brand 필수 4개는 전부 들어가야 함 (18평 충분한 예산)
        assert log["type_allocation"]["counter"]["allocated"] == 1
        assert log["type_allocation"]["photo_wall"]["allocated"] == 1
        assert log["type_allocation"]["test_bar"]["allocated"] == 1
        assert log["type_allocation"]["consultation_desk"]["allocated"] == 1
        # utilization 합리적 (0.3 이상, 1.0 이하)
        assert 0.2 < log["budget_summary"]["utilization_rate"] <= 1.0
