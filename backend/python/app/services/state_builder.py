"""
state 생성/재구성 서비스.

- is_large: 면적 분기 판단
- build_entrances_mm: 파서 entrance 목록 → all_entrances_mm 포맷
- rebuild_state_from_body: /place 요청 body → state(Shapely 복원 + 노드 전처리 실행)
"""
import logging

from shapely.geometry import Polygon

from app.facade_rules import DEFAULT_FACADE_TYPE as _DEFAULT_FACADE_TYPE
from app.venue_rules import DEFAULT_VENUE_TYPE as _DEFAULT_VENUE_TYPE

logger = logging.getLogger(__name__)

# 면적 분기 기준 (m²). 50평 ~= 165m²
SCALE_THRESHOLD_M2 = 165


def is_large(state: dict) -> bool:
    """면적 기준으로 대형·야외 여부 판단."""
    usable_poly = state.get("usable_poly")
    if usable_poly:
        area_m2 = usable_poly.area / 1_000_000
        return area_m2 >= SCALE_THRESHOLD_M2
    return True  # 면적 없으면 대형 기본


def build_entrances_mm(entrances_raw: list, entrance_mm, scale: float) -> list:
    """파서가 반환한 entrances 목록을 all_entrances_mm 형식으로 변환.

    파서가 type(MAIN_DOOR/EMERGENCY_EXIT)을 반환하면 그대로 사용.
    없으면 MAIN_DOOR 기본값.
    """
    if not entrances_raw:
        if entrance_mm:
            return [{"coord": entrance_mm, "type": "MAIN_DOOR"}]
        return []

    result = []
    for ent in entrances_raw:
        if not isinstance(ent, dict):
            continue
        x = ent.get("x_px", 0) * scale
        y = ent.get("y_px", 0) * scale
        ent_type = ent.get("type", "MAIN_DOOR")
        result.append({"coord": (x, y), "type": ent_type})
    return result


def rebuild_state_from_body(body: dict) -> dict:
    """캐시 miss 시 body에서 state 재구성 (Shapely 재생성)."""
    floor = body.get("floor", {})
    poly_mm = floor.get("polygon_mm", [])
    usable_poly = Polygon(poly_mm) if len(poly_mm) >= 3 else None

    entrance = body.get("entrance", {})
    entrance_mm = (entrance.get("x_mm", 0), entrance.get("y_mm", 0))

    brand_dict = body.get("brand_dict", {})
    brand_data = brand_dict if "brand" in brand_dict else {
        "brand": {**brand_dict, "brand_category": body.get("brand_category", "기타")},
        "fire": {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200},
        "construction": {"wall_clearance_mm": 300, "object_gap_mm": 300},
        "placement_rules": brand_dict.get("placement_rules", []),
    }
    # [2026-04-22 S-8f] 프론트 선택 brand_category 우선 override.
    # reference.py LLM variance 로 "뷰티" → "기타" 로 뒤집히는 케이스 방지.
    # "기타" 면 MAX_COUNT_BY_CATEGORY 가 CHARACTER_IP fallback → 뷰티 매장에
    # 캐릭터 IP 룰 적용되는 증상 차단.
    user_cat = body.get("brand_category")
    if user_cat and user_cat != "기타":
        brand_data = dict(brand_data)
        brand_data["brand"] = {**brand_data.get("brand", {}), "brand_category": user_cat}

    # space-data 응답에 포함된 설비/inaccessible 좌표 복원
    sprinklers_mm = [tuple(s) for s in body.get("sprinklers_mm", [])]
    hydrants_mm = [tuple(h) for h in body.get("hydrants_mm", [])]
    electric_panels_mm = [tuple(e) for e in body.get("electric_panels_mm", [])]

    # inaccessible_rooms → Polygon 복원
    inaccessible_polys = []
    inaccessible_types = []
    for dz in body.get("dead_zones", []):
        dz_type = dz.get("type", "unknown")
        poly_coords = dz.get("polygon_mm", [])
        if dz_type in ("core", "toilet", "stair", "pillar") and len(poly_coords) >= 3:
            inaccessible_polys.append(Polygon(poly_coords))
            inaccessible_types.append(dz_type)

    # all_entrances 복원
    all_entrances = [{"coord": entrance_mm, "type": "MAIN_DOOR"}]
    for dz in body.get("dead_zones", []):
        if dz.get("type") == "emergency_exit":
            all_entrances.append({"coord": tuple(dz["center_mm"]), "type": "EMERGENCY_EXIT"})

    state = {
        "usable_poly": usable_poly,
        "entrance_mm": entrance_mm,
        "all_entrances_mm": all_entrances,
        "entrance_width_mm": 1200,
        "sprinklers_mm": sprinklers_mm,
        "hydrants_mm": hydrants_mm,
        "electric_panels_mm": electric_panels_mm,
        "inner_wall_linestrings": [],
        "inaccessible_polys": inaccessible_polys,
        "inaccessible_types": inaccessible_types,
        "dead_zones": [],
        "brand_data": brand_data,
        "venue_type": body.get("venue_type") or _DEFAULT_VENUE_TYPE,
        "facade_type": body.get("facade_type") or _DEFAULT_FACADE_TYPE,
        "ceiling_height_mm": body.get("ceiling_height_mm"),
        "fallback_round": 0,
    }

    # 면적 분기
    large = is_large(state)
    if large:
        from app.nodes_large.b_space_data import dead_zone, ref_point_gen, walk_mm
        state.update(dead_zone.run(state))
        state.update(ref_point_gen.run(state))
        state.update(walk_mm.run(state))
        state["_scale_type"] = "large"
    else:
        from app.nodes_small import dead_zone, slot_gen, ref_point_gen, walk_mm
        from app.nodes_small import ref_point_clearance  # raycasting wrapper (Shadow Mode)
        state.update(dead_zone.run(state))
        state.update(slot_gen.run(state))
        state.update(ref_point_gen.run(state))
        # 2026-04-29: ref_point 마다 max_front_clearance_mm 부여 (raycasting Shadow Mode).
        # placement.py 가 정렬 key 로 사용 — 큰 max_clearance ref_point 우선 시도.
        state.update(ref_point_clearance.run(state))
        state.update(walk_mm.run(state))
        state["_scale_type"] = "small"

    return state
