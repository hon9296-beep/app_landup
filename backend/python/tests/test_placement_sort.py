"""
placement.py 정렬 키 검증 — 2026-04-22 S-8g-2.

제미나이 자문 Q2:
  - allocator 단계(S-8c)에서 brand 가중치 적용 = priority + BRAND_BONUS
  - placement 단계에서도 동일 원칙 적용 필요 (이전 is_mandatory 이분법은 위계 파괴)

검증 대상:
  1. _PRIORITY_SCORE + BRAND_BONUS 가중 정렬
  2. brand kiosk(45+20=65) 가 default partition(98) 자리 못 뺏음
  3. brand counter(95+20=115) 는 default partition(98) 추월
  4. tie-break: LLM priority 작은 값 우선

접근: placement.py 의 정렬 로직이 내부 블록이라 단위 테스트 어려움.
대신 정렬 공식 자체를 재현하여 검증. 실제 placement.run() 통합 검증은 E2E.

상세: reports/AD/worklist/2026-04-22_worklist.md S-8g-2
"""
from app.nodes_small.object_selection import BRAND_BONUS, _PRIORITY_SCORE


# [2026-04-22 S-8f v2] structural anchor boost — partition + photo 는 +1000.
STRUCTURAL_ANCHOR_BOOST = 1000
_STRUCTURAL_ANCHORS = {"partition_wall_I", "partition_wall_L", "photo_wall", "photo_island"}


def _sort_intents(intents: list[dict], mandatory_types: set[str]) -> list[dict]:
    """placement.py 의 정렬 키 재현 (테스트용).

    실제 구현: backend/app/nodes_small/placement.py L281~
    """
    return sorted(
        intents,
        key=lambda x: (
            _PRIORITY_SCORE.get(x["object_type"], 40)
                + (STRUCTURAL_ANCHOR_BOOST if x["object_type"] in _STRUCTURAL_ANCHORS else 0)
                + (BRAND_BONUS if x["object_type"] in mandatory_types else 0),
            -x.get("priority", 99),
        ),
        reverse=True,
    )


# ─────────────────────────────────────────────────────────────────────
# 위계 보존 — brand 가중 후에도 default 우월 기물 자리 지킴
# ─────────────────────────────────────────────────────────────────────

class TestHierarchyPreservation:
    def test_brand_kiosk_below_default_partition(self):
        """brand kiosk(45+20=65) < default partition(98) — 위계 보존."""
        intents = [
            {"object_type": "kiosk", "priority": 5},
            {"object_type": "partition_wall_I", "priority": 5},
        ]
        mandatory = {"kiosk"}  # brand 명시
        sorted_order = _sort_intents(intents, mandatory)
        assert [o["object_type"] for o in sorted_order] == [
            "partition_wall_I", "kiosk"
        ], "brand kiosk 가 default partition 자리 뺏으면 안 됨"

    def test_brand_signage_below_default_partition(self):
        """brand signage_stand(35+20=55) < default partition(98)."""
        intents = [
            {"object_type": "signage_stand", "priority": 1},
            {"object_type": "partition_wall_I", "priority": 9},
        ]
        mandatory = {"signage_stand"}
        sorted_order = _sort_intents(intents, mandatory)
        assert sorted_order[0]["object_type"] == "partition_wall_I"


# ─────────────────────────────────────────────────────────────────────
# 위계 추월 — brand 가중으로 정당하게 default 추월
# ─────────────────────────────────────────────────────────────────────

class TestHierarchyOvertake:
    def test_structural_anchors_beat_brand_counter(self):
        """[S-8f v2] partition + photo 에 +1000 boost 적용 후 counter brand(115) 도 못 뺏음.
        이전 S-8g-2 (brand counter > default partition) 는 무효 — structural anchor 최우선.
        """
        intents = [
            {"object_type": "partition_wall_I", "priority": 5},  # 98+1000=1098
            {"object_type": "counter", "priority": 5},           # 95+20=115
        ]
        mandatory = {"counter"}
        sorted_order = _sort_intents(intents, mandatory)
        assert sorted_order[0]["object_type"] == "partition_wall_I"

    def test_photo_wall_structural_beats_all_brand(self):
        """[S-8f v2] photo_wall(85+20+1000=1105) 이 모든 brand 기물 위."""
        intents = [
            {"object_type": "partition_wall_I", "priority": 5},
            {"object_type": "photo_wall", "priority": 5},
        ]
        mandatory = {"photo_wall"}
        sorted_order = _sort_intents(intents, mandatory)
        assert sorted_order[0]["object_type"] == "photo_wall"


# ─────────────────────────────────────────────────────────────────────
# tie-break — LLM priority
# ─────────────────────────────────────────────────────────────────────

class TestTieBreakByPriority:
    def test_same_score_smaller_priority_first(self):
        """priority+bonus 동점일 때 LLM priority 작은 값 먼저."""
        # 둘 다 partition_wall_I (98). priority 만 다름.
        intents = [
            {"object_type": "partition_wall_I", "priority": 9},
            {"object_type": "partition_wall_I", "priority": 1},
        ]
        sorted_order = _sort_intents(intents, set())
        # priority=1 (강한 의도) 이 먼저
        assert sorted_order[0]["priority"] == 1
        assert sorted_order[1]["priority"] == 9


# ─────────────────────────────────────────────────────────────────────
# 종합 시나리오 — LUMIA 18평 유사 intent 셋
# ─────────────────────────────────────────────────────────────────────

class TestLumiaScenario:
    def test_lumia_18py_intent_order(self):
        """LUMIA 18평 유사 intent 셋의 정렬 결과.

        [S-8f v2] structural anchor boost (+1000) 적용:
          partition_wall_I(98+1000=1098) > photo_wall(85+20+1000=1105) >
          counter(95+20=115) > display_table(90+20=110) > test_bar(75+20=95) >
          shelf_wall(65) > kiosk(45)
        """
        intents = [
            {"object_type": "kiosk", "priority": 5},                 # default 45
            {"object_type": "counter", "priority": 3},               # brand 95+20=115
            {"object_type": "photo_wall", "priority": 2},            # brand 85+20+1000=1105
            {"object_type": "partition_wall_I", "priority": 4},      # default 98+1000=1098
            {"object_type": "test_bar", "priority": 5},              # brand 75+20=95
            {"object_type": "shelf_wall", "priority": 6},            # default 65
        ]
        mandatory = {"counter", "photo_wall", "test_bar"}
        sorted_order = _sort_intents(intents, mandatory)
        types = [o["object_type"] for o in sorted_order]
        # structural anchor 두 개가 최상위 (photo 1105 > partition 1098)
        assert types[:2] == ["photo_wall", "partition_wall_I"]
        # counter → test_bar → shelf_wall → kiosk
        assert types[2:] == ["counter", "test_bar", "shelf_wall", "kiosk"]

    def test_photo_wall_beats_display_table(self):
        """[S-8f v2 Q5 핵심] photo_wall + structural boost > display_table brand.
        이전 맹점: display_table brand (110) > photo_wall brand (105) 역전으로
        photo_wall 이 중앙 아일랜드 기물에 밀려 drop 하던 현상 해결.
        """
        intents = [
            {"object_type": "display_table", "priority": 1},     # 90+20=110
            {"object_type": "photo_wall", "priority": 1},        # 85+20+1000=1105
        ]
        mandatory = {"display_table", "photo_wall"}
        sorted_order = _sort_intents(intents, mandatory)
        assert sorted_order[0]["object_type"] == "photo_wall", (
            "photo_wall(structural anchor) 이 display_table 먼저 배치돼야 함"
        )

    def test_partition_beats_counter(self):
        """partition(98+1000=1098) > counter brand(95+20=115). 공간 뼈대 우선."""
        intents = [
            {"object_type": "counter", "priority": 1},           # 95+20=115
            {"object_type": "partition_wall_I", "priority": 1},  # 98+1000=1098
        ]
        mandatory = {"counter"}
        sorted_order = _sort_intents(intents, mandatory)
        assert sorted_order[0]["object_type"] == "partition_wall_I"


# ─────────────────────────────────────────────────────────────────────
# placement.py 에서 실제 로직 사용 확인 (import check)
# ─────────────────────────────────────────────────────────────────────

class TestPlacementIntegration:
    def test_brand_bonus_imported_in_placement(self):
        """placement.py 가 BRAND_BONUS 를 import 하는지 소스 확인."""
        import app.nodes_small.placement as placement_module
        import inspect
        source = inspect.getsource(placement_module.run)
        assert "BRAND_BONUS" in source, (
            "placement.run() 이 BRAND_BONUS 를 사용하지 않음 — S-8g-2 미적용"
        )
