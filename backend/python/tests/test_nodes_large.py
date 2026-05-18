"""
노드 단위 테스트 — pytest.

실행: cd landup_team/backend && python -m pytest tests/test_nodes.py -v
"""
import sys
sys.path.insert(0, ".")

import pytest
from shapely.geometry import Polygon, LineString


# ── 공용 fixture ─────────────────────────────────────────────

@pytest.fixture
def square_poly():
    """10m x 8m 사각형."""
    return Polygon([(0, 0), (10000, 0), (10000, 8000), (0, 8000)])


@pytest.fixture
def base_state(square_poly):
    """dead_zone 이후 state mock."""
    return {
        "usable_poly": square_poly,
        "entrance_mm": (5000, 0),
        "all_entrances_mm": [{"coord": (5000, 0), "type": "MAIN_DOOR"}],
        "entrance_width_mm": 1200,
        "dead_zones": [],
        "inner_wall_linestrings": [],
        "sprinklers_mm": [(2000, 2000)],
        "hydrants_mm": [],
        "panels_mm": [(500, 500)],
        "inaccessible_polys": [],
        "slots": {},
        "brand_data": {
            "brand": {"brand_category": "기타", "clearspace_mm": {"value": 1000}},
            "fire": {"main_corridor_min_mm": 900},
            "construction": {"wall_clearance_mm": 300},
            "placement_rules": [
                {"object_type": "counter", "width_mm": 1500, "depth_mm": 600, "height_mm": 900, "max_count": 1},
                {"object_type": "display_table", "width_mm": 1200, "depth_mm": 800, "height_mm": 1200, "max_count": 2},
            ],
        },
        "fallback_round": 0,
    }


# ── graph compile ────────────────────────────────────────────

def test_graph_compiles():
    from app.graph import compile_large_graph
    g = compile_large_graph()
    nodes = list(g.get_graph().nodes)
    assert "__start__" in nodes
    assert "__end__" in nodes
    # 19 노드 + join + output_join + __start__ + __end__ = 23
    assert len(nodes) == 23


# ── ref_point_gen ────────────────────────────────────────────

class TestRefPointGen:
    def test_generates_points(self, base_state):
        from app.nodes_large.b_space_data.ref_point_gen import run
        result = run(base_state)
        rps = result["reference_points"]
        assert len(rps) > 0

    def test_point_structure(self, base_state):
        from app.nodes_large.b_space_data.ref_point_gen import run
        rps = run(base_state)["reference_points"]
        rp = rps[0]
        assert "id" in rp
        assert "coord" in rp
        assert isinstance(rp["coord"], tuple)
        assert "wall_segment" in rp
        assert "label" in rp
        assert rp["zone_label"] is None  # walk_mm 전

    def test_labels_include_deep_wall(self, base_state):
        from app.nodes_large.b_space_data.ref_point_gen import run
        rps = run(base_state)["reference_points"]
        labels = {rp["label"] for rp in rps}
        # 사각형이면 입구 반대편 벽에 deep_wall 있어야 함
        assert "deep_wall" in labels, f"labels: {labels}"

    def test_empty_poly(self):
        from app.nodes_large.b_space_data.ref_point_gen import run
        result = run({})
        assert result["reference_points"] == []

    def test_inner_walls(self, base_state):
        """내벽이 있으면 inner_wall 라벨 생성."""
        base_state["inner_wall_linestrings"] = [
            LineString([(3000, 2000), (3000, 6000)])
        ]
        from app.nodes_large.b_space_data.ref_point_gen import run
        rps = run(base_state)["reference_points"]
        inner_labels = [rp for rp in rps if rp["label"] == "inner_wall"]
        assert len(inner_labels) > 0


# ── walk_mm ──────────────────────────────────────────────────
# 2026-05-04: TestWalkMm 클래스 폐기 — 두 테스트 (test_zone_label_on_ref_points,
# test_zone_map_keys) 모두 nodes_large.slot_gen (현재 _archive/ 안 데드 노드) 의존.
# large 분기는 BSP split_tree 기반 concept_area 사용 = slot 개념 사용 X.


# ── object_selection ─────────────────────────────────────────

class TestObjectSelection:
    def test_density_ratio_default(self, base_state):
        from app.nodes_large.f_placement.object_selection import run
        result = run(base_state)
        assert len(result["eligible_objects"]) > 0

    def test_density_ratio_high(self, base_state):
        """밀도 비율 높이면 더 많은 오브젝트 통과."""
        from app.nodes_large.f_placement.object_selection import run
        base_state["density_ratio"] = 0.7
        high = run(base_state)["eligible_objects"]
        base_state["density_ratio"] = 0.05
        low = run(base_state)["eligible_objects"]
        assert len(high) >= len(low)

    def test_empty_rules_gets_defaults(self, base_state):
        """placement_rules가 비어있으면 기본 세트로 보충."""
        from app.nodes_large.f_placement.object_selection import run
        base_state["brand_data"]["placement_rules"] = []
        result = run(base_state)
        assert len(result["eligible_objects"]) > 0  # 기본 세트가 채워짐


# ── placement ────────────────────────────────────────────────
# 2026-05-04: TestPlacement 클래스 폐기 — _get_placement_state 헬퍼가
# nodes_large.slot_gen 의존. 의존 함수 폐기 = 클래스 전체 폐기 (옵션 다 정합).
# placement 검증은 통합 E2E 흐름 (graph.py) 에서 별도로 수행.


# ── reference (브랜드만) ─────────────────────────────────────

class TestReference:
    def test_no_brand_returns_defaults(self):
        from app.nodes_large.c_brand_area.reference import run
        result = run({"brand_bytes": None})
        assert "brand_data" in result
        assert result["brand_data"]["brand"]["brand_category"] == "기타"

    def test_no_images_in_output(self):
        """reference.py는 이미지를 반환하지 않아야 함."""
        from app.nodes_large.c_brand_area.reference import run
        result = run({"brand_bytes": None})
        assert "reference_images" not in result
        assert "layout_examples" not in result
