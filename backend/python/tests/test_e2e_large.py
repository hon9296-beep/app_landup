"""
End-to-end 파이프라인 테스트.

간단한 사각형 도면(mock state)으로 파서/vision 건너뛰고
dead_zone → slot_gen → ref_point_gen → walk_mm → 합류 후 배치 파이프라인 전체 검증.
"""
import sys
sys.path.insert(0, ".")

from shapely.geometry import Polygon, Point, LineString

# ── mock state: 10m x 8m 사각형 도면 ────────────────────────
def make_mock_state():
    """파서+vision 결과를 흉내내는 mock state."""
    # 10000mm x 8000mm 사각형
    poly = Polygon([(0, 0), (10000, 0), (10000, 8000), (0, 8000)])
    entrance = (5000, 0)  # 하단 중앙

    return {
        "file_bytes": b"mock",
        "file_type": "pdf",
        "brand_bytes": None,
        "density_ratio": 0.25,
        "fallback_round": 0,
        # 파서 결과
        "floor_polygon_px": [[0,0],[1200,0],[1200,900],[0,900]],
        "scale_mm_per_px": 10.0,
        "scale_confirmed": True,
        "image_bytes": None,
        "is_vector": True,
        # vision 결과
        "usable_poly": poly,
        "entrance_mm": entrance,
        "all_entrances_mm": [{"coord": entrance, "type": "MAIN_DOOR"}],
        "entrance_width_mm": 1200,
        "sprinklers_mm": [(2000, 2000)],
        "hydrants_mm": [],
        "panels_mm": [(500, 500)],
        "inaccessible_polys": [],
        "inner_walls": [],
        "inner_wall_linestrings": [],
        "floor_px_min_x": 0.0,
        "floor_px_min_y": 0.0,
        # 브랜드 (없으면 fallback)
        "brand_data": {
            "brand": {
                "brand_category": "기타",
                "clearspace_mm": {"value": 1000, "confidence": "low", "source": "default"},
                "logo_clearspace_mm": {"value": 500, "confidence": "low", "source": "default"},
                "character_orientation": {"value": "자유", "confidence": "low", "source": "default"},
                "prohibited_material": {"value": None, "confidence": "low", "source": "default"},
                "relationships": [],
            },
            "fire": {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200},
            "construction": {"wall_clearance_mm": 300, "object_gap_mm": 300},
            "placement_rules": [
                {"object_type": "counter", "name": "계산대", "width_mm": 1500, "depth_mm": 600, "height_mm": 900, "max_count": 1},
                {"object_type": "display_table", "name": "진열대", "width_mm": 1200, "depth_mm": 800, "height_mm": 1200, "max_count": 3},
                {"object_type": "photo_wall", "name": "포토월", "width_mm": 2400, "depth_mm": 300, "height_mm": 2200, "max_count": 1},
            ],
        },
    }


def test_individual_nodes():
    """각 노드를 순서대로 실행하며 데이터 흐름 확인."""
    state = make_mock_state()

    # 1. dead_zone
    from app.nodes_large.b_space_data.dead_zone import run as dead_zone_run
    result = dead_zone_run(state)
    state.update(result)
    print(f"[dead_zone] dead_zones={len(state.get('dead_zones', []))}")

    # 2. slot_gen — 폐기 (2026-05-04). nodes_large/slot_gen 은 _archive/ 로 이동된 데드 코드.
    #    large 분기는 BSP split_tree 기반 concept_area 사용. slot 개념 자체 사용 X.

    # 3. ref_point_gen
    from app.nodes_large.b_space_data.ref_point_gen import run as ref_point_gen_run
    result = ref_point_gen_run(state)
    state.update(result)
    rps = state.get("reference_points", [])
    print(f"[ref_point_gen] reference_points={len(rps)}")
    assert len(rps) > 0, "ref_point_gen이 기준점을 생성하지 않음"

    # reference_point 구조 검증
    rp0 = rps[0]
    required_keys = {"id", "coord", "wall_segment", "wall_normal_vec", "wall_normal", "wall_angle_deg", "wall_length_mm", "label", "zone_label"}
    missing = required_keys - set(rp0.keys())
    assert not missing, f"reference_point에 키 누락: {missing}"
    assert rp0["zone_label"] is None, "zone_label은 walk_mm 전에 None이어야 함"
    print(f"  첫 번째: id={rp0['id']}, label={rp0['label']}, coord={rp0['coord']}")

    # 4. walk_mm
    from app.nodes_large.b_space_data.walk_mm import run as walk_mm_run
    result = walk_mm_run(state)
    state.update(result)
    zone_map = state.get("zone_map", {})
    print(f"[walk_mm] zone_map={zone_map}")
    assert zone_map, "walk_mm가 zone_map을 생성하지 않음"

    # zone_label이 채워졌는지 확인
    rps_after = state.get("reference_points", [])
    filled = sum(1 for rp in rps_after if rp.get("zone_label") is not None)
    print(f"  reference_points zone_label 채워짐: {filled}/{len(rps_after)}")
    assert filled > 0, "walk_mm가 reference_points에 zone_label을 부여하지 않음"

    # 5. object_selection
    from app.nodes_large.f_placement.object_selection import run as object_selection_run
    result = object_selection_run(state)
    state.update(result)
    eligible = state.get("eligible_objects", [])
    print(f"[object_selection] eligible={len(eligible)}: {[o['object_type'] for o in eligible]}")
    assert len(eligible) > 0, "object_selection이 오브젝트를 선정하지 않음"

    # 6. ref_image_loader
    from app.nodes_large.e_reference_pool.ref_image_loader import run as ref_image_loader_run
    result = ref_image_loader_run(state)
    state.update(result)
    print(f"[ref_image_loader] images={len(state.get('reference_images', []))}, layouts={len(state.get('layout_examples', []))}")

    # 7. design (API 없이 fallback)
    from app.nodes_large.f_placement.design import run as design_run
    result = design_run(state)
    state.update(result)
    intents = state.get("design_intents", [])
    print(f"[design] intents={len(intents)}")
    assert len(intents) > 0, "design이 의도를 생성하지 않음"
    # ref_point_id 필드 존재 확인
    has_ref_field = any("ref_point_id" in i for i in intents)
    print(f"  ref_point_id 필드 포함: {has_ref_field}")

    # 8. placement
    from app.nodes_large.f_placement.placement import run as placement_run
    result = placement_run(state)
    state.update(result)
    placed = state.get("placed_objects", [])
    failed = state.get("failed_objects", [])
    print(f"[placement] placed={len(placed)}, failed={len(failed)}")

    # 9. verify
    from app.nodes_large.f_placement.verify import run as verify_run
    result = verify_run(state)
    state.update(result)
    verification = state.get("verification", {})
    print(f"[verify] {verification}")

    # 10. pathing_validator
    from app.nodes_large.h_output.pathing_validator import run as pathing_validator_run
    result = pathing_validator_run(state)
    state.update(result)
    print(f"[pathing_validator] pathways={len(state.get('pathways', []))}, trapped={len(state.get('trapped_objects', []))}")

    # 11. glb_exporter
    from app.nodes_large.h_output.glb_exporter import run as glb_exporter_run
    result = glb_exporter_run(state)
    state.update(result)
    has_glb = state.get("glb_bytes") is not None
    print(f"[glb_exporter] has_glb={has_glb}")

    # 12. report_gen
    from app.nodes_large.h_output.report_gen import run as report_gen_run
    result = report_gen_run(state)
    state.update(result)
    report = state.get("report_text", "")
    print(f"[report_gen] report_len={len(report)}")

    print("\n=== ALL NODES PASSED ===")


if __name__ == "__main__":
    test_individual_nodes()
