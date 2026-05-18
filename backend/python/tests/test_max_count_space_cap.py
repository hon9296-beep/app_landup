"""
[DEPRECATED 2026-04-22 S-8e] 레거시 _cap_max_count_by_space 검증.

_allocate_eligible() 통합 greedy 로 대체됨. 신규 검증: test_unified_allocator.py.
본 파일 전체 skip. 기능 완성 후 삭제 예정.

작업 계획: reports/AD/worklist/2026-04-22_worklist.md S-8e
"""
import pytest

pytestmark = pytest.mark.skip(reason="S-8e DEPRECATED: _allocate_eligible 로 대체 — test_unified_allocator.py 참조")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — 데이터 구조 (utils.py + state.py)
# ─────────────────────────────────────────────────────────────────────

class TestLayer1_DataStructure:
    """Foundation: SmallState cap_log 필드 + partition_wall에만 fixture_role 부여."""

    # fixture_role은 "여러 object_type이 한 cap 규칙을 공유"할 때만 추가.
    # 2026-04-20 이후 유일한 그룹: partition_wall_I/L = "partition" role.
    # 나머지 object_type은 _SPACE_CAP_RULES_SMALL에 object_type 직접 키로 등재.
    EXPECTED_FIXTURE_ROLE = {
        "partition_wall_I": "partition",
        "partition_wall_L": "partition",
    }

    def test_object_standards_imported(self):
        """utils.py import 가능."""
        from app.utils import OBJECT_STANDARDS
        assert isinstance(OBJECT_STANDARDS, dict)
        assert len(OBJECT_STANDARDS) > 0

    @pytest.mark.parametrize("obj_type,expected_role", EXPECTED_FIXTURE_ROLE.items())
    def test_fixture_role_only_on_grouped_types(self, obj_type, expected_role):
        """partition_wall_I/L에만 fixture_role 부여되었는지 확인."""
        from app.utils import OBJECT_STANDARDS
        assert obj_type in OBJECT_STANDARDS
        actual = OBJECT_STANDARDS[obj_type].get("fixture_role")
        assert actual == expected_role, f"{obj_type}: expected '{expected_role}', got '{actual}'"

    def test_non_grouped_types_have_no_fixture_role(self):
        """그룹 불필요한 타입은 fixture_role 미부여 (과공학 방지)."""
        from app.utils import OBJECT_STANDARDS
        grouped = set(self.EXPECTED_FIXTURE_ROLE.keys())
        for obj_type, std in OBJECT_STANDARDS.items():
            if obj_type in grouped:
                continue
            assert "fixture_role" not in std, (
                f"{obj_type}: fixture_role이 불필요하게 있음. "
                f"단일 타입 cap은 _SPACE_CAP_RULES_SMALL의 object_type 키로 직접 등재할 것."
            )

    def test_existing_fields_preserved(self):
        """기존 필드(name, priority, aliases) 유지."""
        from app.utils import OBJECT_STANDARDS
        for obj_type, std in OBJECT_STANDARDS.items():
            assert "name" in std, f"{obj_type} name 누락"
            assert "priority" in std, f"{obj_type} priority 누락"
            assert "aliases" in std, f"{obj_type} aliases 누락"

    def test_large_side_import_safe(self):
        """Large 측 OBJECT_STANDARDS 참조 코드 안 깨짐."""
        try:
            import app.nodes_large.design  # noqa: F401
            import app.nodes_large.placement  # noqa: F401
        except ImportError as e:
            pytest.fail(f"Large 측 import 실패: {e}")

    def test_small_state_has_cap_log(self):
        """SmallState TypedDict에 cap_log 필드 존재."""
        from app.state import SmallState
        assert "cap_log" in SmallState.__annotations__, "SmallState에 cap_log 필드 누락"


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — 로직 함수 (object_selection.py 내부)
# ─────────────────────────────────────────────────────────────────────

class TestLayer2_Logic:
    """Internal Logic: _SPACE_CAP_RULES_SMALL + 함수 3개."""

    # ── _SPACE_CAP_RULES_SMALL 상수 ──

    def test_space_cap_rules_constant_exists(self):
        """_SPACE_CAP_RULES_SMALL 상수 존재 + 내용 (object_type 직접 + fixture_role 혼용)."""
        from app.nodes_small.object_selection import _SPACE_CAP_RULES_SMALL
        assert _SPACE_CAP_RULES_SMALL == {
            "counter": 1,        # object_type 직접
            "photo_wall": 1,     # object_type 직접
            "partition": 1,      # fixture_role 그룹 (partition_wall_I/L)
        }

    # ── _get_space_cap() ──

    def test_get_space_cap_direct_object_type(self):
        """18평에서 object_type 직접 매칭."""
        from app.nodes_small.object_selection import _get_space_cap
        assert _get_space_cap("counter", 60_000_000) == 1
        assert _get_space_cap("photo_wall", 60_000_000) == 1

    def test_get_space_cap_fixture_role_group(self):
        """18평에서 fixture_role 그룹(partition) 조회 — I/L 양쪽 모두 해당."""
        from app.nodes_small.object_selection import _get_space_cap
        assert _get_space_cap("partition_wall_I", 60_000_000) == 1
        assert _get_space_cap("partition_wall_L", 60_000_000) == 1

    def test_get_space_cap_medium_store(self):
        """20평(≥66㎡)에서 cap 미적용 (None)."""
        from app.nodes_small.object_selection import _get_space_cap
        assert _get_space_cap("counter", 66_000_000) is None
        assert _get_space_cap("counter", 100_000_000) is None
        assert _get_space_cap("partition_wall_I", 100_000_000) is None

    def test_get_space_cap_unknown_type(self):
        """등록되지 않은 obj_type → None."""
        from app.nodes_small.object_selection import _get_space_cap
        assert _get_space_cap("unknown_type", 60_000_000) is None
        assert _get_space_cap("", 60_000_000) is None

    def test_get_space_cap_signature(self):
        """함수 시그니처 확인 (eligible 파라미터 선택적)."""
        from app.nodes_small.object_selection import _get_space_cap
        import inspect
        sig = inspect.signature(_get_space_cap)
        assert "obj_type" in sig.parameters
        assert "usable_area_mm2" in sig.parameters
        assert "eligible" in sig.parameters
        assert sig.parameters["eligible"].default is None

    # ── _compute_final_max() ──

    def test_compute_final_max_2layer(self):
        """2중 min 기본 동작."""
        from app.nodes_small.object_selection import _compute_final_max
        assert _compute_final_max(2, 1) == 1
        assert _compute_final_max(1, 2) == 1
        assert _compute_final_max(3, 3) == 3

    def test_compute_final_max_space_cap_none(self):
        """space_cap이 None이면 brand_max 그대로."""
        from app.nodes_small.object_selection import _compute_final_max
        assert _compute_final_max(5, None) == 5
        assert _compute_final_max(1, None) == 1

    def test_compute_final_max_minimum_one(self):
        """최소 1 보장."""
        from app.nodes_small.object_selection import _compute_final_max
        assert _compute_final_max(0, 1) == 1
        assert _compute_final_max(0, None) == 1

    def test_compute_final_max_category_cap_default(self):
        """category_cap 기본값 None (3중 확장 구멍)."""
        from app.nodes_small.object_selection import _compute_final_max
        import inspect
        sig = inspect.signature(_compute_final_max)
        assert "category_cap" in sig.parameters
        assert sig.parameters["category_cap"].default is None

    # ── _cap_max_count_by_space() ──

    def test_cap_max_count_reduces_counter(self):
        """counter 2개 → 1개로 축소 (object_type 직접 dimension)."""
        from app.nodes_small.object_selection import _cap_max_count_by_space
        eligible = [
            {"object_type": "counter"},
            {"object_type": "counter"},
        ]
        capped, cap_log = _cap_max_count_by_space(eligible, 60_000_000)
        assert len(capped) == 1
        assert capped[0]["object_type"] == "counter"
        assert "counter" in cap_log
        assert cap_log["counter"]["from_count"] == 2
        assert cap_log["counter"]["to_count"] == 1
        assert cap_log["counter"]["dimension"] == "object_type:counter"

    def test_cap_max_count_partition_group_shared(self):
        """partition_wall_I + partition_wall_L 합쳐서 1개 상한 (fixture_role 그룹 공유)."""
        from app.nodes_small.object_selection import _cap_max_count_by_space
        eligible = [
            {"object_type": "partition_wall_I"},
            {"object_type": "partition_wall_L"},
        ]
        capped, cap_log = _cap_max_count_by_space(eligible, 60_000_000)
        # 가벽 그룹 총 1개만 살아남아야 함 (I 1개 + L 0개, 또는 I 0개 + L 1개)
        total_partitions = sum(
            1 for o in capped if o["object_type"].startswith("partition_wall_")
        )
        assert total_partitions == 1, f"partition 그룹 합계 1개여야 함 (실제 {total_partitions})"
        # dimension 표기가 fixture_role 명시
        capped_type = next(
            (k for k in cap_log if k.startswith("partition_wall_")), None
        )
        assert capped_type is not None
        assert cap_log[capped_type]["dimension"] == "fixture_role:partition"

    def test_cap_max_count_mixed(self):
        """counter 2 + photo_wall 2 + shelf_wall 2 → counter 1 + photo_wall 1 + shelf_wall 2."""
        from app.nodes_small.object_selection import _cap_max_count_by_space
        eligible = [
            {"object_type": "counter"}, {"object_type": "counter"},
            {"object_type": "photo_wall"}, {"object_type": "photo_wall"},
            {"object_type": "shelf_wall"}, {"object_type": "shelf_wall"},
        ]
        capped, cap_log = _cap_max_count_by_space(eligible, 60_000_000)
        counts = {}
        for o in capped:
            counts[o["object_type"]] = counts.get(o["object_type"], 0) + 1
        assert counts == {"counter": 1, "photo_wall": 1, "shelf_wall": 2}
        assert "counter" in cap_log
        assert "photo_wall" in cap_log
        assert "shelf_wall" not in cap_log  # shelf_wall은 cap 규칙 없음

    def test_cap_max_count_medium_store_no_cap(self):
        """20평+ 매장에서는 cap 미적용."""
        from app.nodes_small.object_selection import _cap_max_count_by_space
        eligible = [
            {"object_type": "counter"}, {"object_type": "counter"},
            {"object_type": "photo_wall"}, {"object_type": "photo_wall"},
        ]
        capped, cap_log = _cap_max_count_by_space(eligible, 100_000_000)
        assert len(capped) == 4
        assert cap_log == {}

    def test_cap_max_count_preserves_order(self):
        """앞에서부터 cap 수만큼 보존 (뒤쪽 제거)."""
        from app.nodes_small.object_selection import _cap_max_count_by_space
        eligible = [
            {"object_type": "counter", "id": "A"},
            {"object_type": "counter", "id": "B"},
        ]
        capped, _ = _cap_max_count_by_space(eligible, 60_000_000)
        assert len(capped) == 1
        assert capped[0]["id"] == "A"  # 첫 번째 보존

    def test_cap_max_count_return_type(self):
        """반환 타입: tuple[list, dict]."""
        from app.nodes_small.object_selection import _cap_max_count_by_space
        result = _cap_max_count_by_space([], 60_000_000)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], dict)


# ─────────────────────────────────────────────────────────────────────
# Layer 3 — 통합 (object_selection.run())
# ─────────────────────────────────────────────────────────────────────

class TestLayer3_Integration:
    """Integration: run() 내부에서 _cap_max_count_by_space 호출 + state에 cap_log 저장."""

    def _mock_state(self, usable_area_mm2: float = 60_000_000) -> dict:
        """테스트용 mock state — 뷰티 브랜드, counter 2개 시나리오."""
        from shapely.geometry import box
        side = int(usable_area_mm2 ** 0.5)
        return {
            "usable_poly": box(0, 0, side, side),
            "brand_data": {
                "brand": {"brand_category": {"value": "뷰티·코스메틱"}},
                "placement_rules": [
                    {
                        "object_type": "counter",
                        "name": "계산대",
                        "width_mm": 1500, "depth_mm": 600, "height_mm": 900,
                        "max_count": 2,  # ← 18평에서 비현실
                    },
                ],
            },
            "density_ratio": 0.25,
            "resolved_intents": [],
            "design_concept": {},
        }

    def test_run_returns_cap_log(self):
        """run() 반환 dict에 cap_log 키 포함."""
        from app.nodes_small.object_selection import run
        state = self._mock_state(60_000_000)
        result = run(state)
        assert "cap_log" in result
        assert "eligible_objects" in result

    def test_run_caps_counter_in_small_store(self):
        """18평 brand_manual counter=2 → eligible counter 1개로 축소."""
        from app.nodes_small.object_selection import run
        state = self._mock_state(60_000_000)
        result = run(state)
        counter_count = sum(1 for o in result["eligible_objects"] if o["object_type"] == "counter")
        assert counter_count == 1, f"counter expected 1, got {counter_count}"
        assert "counter" in result["cap_log"]

    def test_run_no_cap_in_medium_store(self):
        """20평+ 매장에서는 brand_manual 값 그대로."""
        from app.nodes_small.object_selection import run
        state = self._mock_state(100_000_000)
        result = run(state)
        counter_count = sum(1 for o in result["eligible_objects"] if o["object_type"] == "counter")
        assert counter_count == 2, f"counter expected 2 (no cap), got {counter_count}"
        assert result["cap_log"] == {}


# ─────────────────────────────────────────────────────────────────────
# Layer 4 — E2E (실제 파이프라인에서 cap 동작 확인)
# ─────────────────────────────────────────────────────────────────────
# ※ Layer 4는 LLM/외부 의존 있어서 mock 어려움.
#   실측 파이프라인 돌린 후 debug_logs에서 확인하는 방식.
#   여기서는 최근 debug log에서 cap_log 존재 확인만 수행.

class TestLayer4_E2E:
    """E2E: 파이프라인 완료 후 debug_logs에 cap_log 기록 확인."""

    def test_run_returns_cap_log_for_dump(self):
        """run() 결과에 cap_log 존재 (api.py dump 전제)."""
        from app.nodes_small.object_selection import run
        from shapely.geometry import box

        state = {
            "usable_poly": box(0, 0, 7700, 7700),  # ~18평
            "brand_data": {
                "brand": {"brand_category": {"value": "뷰티·코스메틱"}},
                "placement_rules": [],
            },
            "density_ratio": 0.25,
            "resolved_intents": [],
            "design_concept": {},
        }
        result = run(state)
        assert "cap_log" in result

    def test_object_selection_debug_json_has_cap_log_section(self):
        """실제 파이프라인 돌린 후 debug JSON에 cap_log 섹션 포함 확인.

        수동 검증: 실제 파이프라인 1회 실행 후 backend/debug_logs/YYYY-MM-DD/object_selection_debug.json
        파일 내용 확인. 이 테스트는 최신 덤프 파일을 읽어서 검증.
        """
        import os
        import json
        import glob

        debug_root = os.path.join(
            os.path.dirname(__file__), "..", "debug_logs"
        )
        if not os.path.exists(debug_root):
            pytest.skip("debug_logs 디렉토리 없음 — 파이프라인 1회 실행 필요")

        # 가장 최신 date 폴더
        date_dirs = sorted([d for d in os.listdir(debug_root)
                           if os.path.isdir(os.path.join(debug_root, d))])
        if not date_dirs:
            pytest.skip("debug_logs에 date 폴더 없음")

        latest_dir = os.path.join(debug_root, date_dirs[-1])
        debug_file = os.path.join(latest_dir, "object_selection_debug.json")
        if not os.path.exists(debug_file):
            pytest.skip(f"{debug_file} 없음 — Layer 3 구현 후 파이프라인 실행 필요")

        with open(debug_file, encoding="utf-8") as f:
            data = json.load(f)

        # 필수 필드 검증
        assert "cap_log" in data, "object_selection_debug.json에 cap_log 섹션 누락"
        assert "eligible_after_cap" in data, "eligible_after_cap 섹션 누락"
        assert isinstance(data["cap_log"], dict), "cap_log는 dict 타입이어야 함"
        assert isinstance(data["eligible_after_cap"], list), "eligible_after_cap은 list 타입이어야 함"
