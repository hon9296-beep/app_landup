"""
공간 데이터 계산 서비스 — /api/space-data 엔드포인트의 핵심 로직.

파서가 넘긴 auto_detected(px 좌표 + 스케일) 를 mm 좌표 + Shapely 객체 상태로 변환하고,
면적 분기로 대형 or 소·중형 노드군 (dead_zone → [slot_gen] → ref_point_gen → walk_mm) 실행.
"""
import logging
import uuid

from fastapi import HTTPException
from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box

from app.facade_rules import DEFAULT_FACADE_TYPE as _DEFAULT_FACADE_TYPE
from app.serializers.space_serializer import serialize_space_data
from app.services.state_builder import (
    SCALE_THRESHOLD_M2,
    build_entrances_mm,
    is_large,
)
from app.venue_rules import DEFAULT_VENUE_TYPE as _DEFAULT_VENUE_TYPE

logger = logging.getLogger(__name__)


def build_space_data(body: dict) -> dict:
    """공간 데이터 계산. 면적에 따라 대형/소중형 노드 분기.

    body 예상 키:
      - auto_detected: 파서 결과 (floor_polygon_px, scale_mm_per_px, entrance, sprinklers, ...)
      - brand_dict, brand_category
      - venue_type, facade_type
      - manual_dead_zones_px (선택)
    반환: {"space_data": <serialized dict>}
    """
    ad = body.get("auto_detected", {})
    brand_dict = body.get("brand_dict", {})
    brand_category = body.get("brand_category", "기타")
    venue_type = body.get("venue_type", _DEFAULT_VENUE_TYPE)  # 기본값: venue_rules.py 관리
    facade_type = body.get("facade_type", _DEFAULT_FACADE_TYPE)  # 기본값: facade_rules.py 관리

    # polygon + scale → usable_poly
    poly_px = ad.get("floor_polygon_px", [])
    scale = ad.get("scale_mm_per_px", 10)
    poly_mm = [(p[0] * scale, p[1] * scale) for p in poly_px]
    if len(poly_mm) < 3:
        raise HTTPException(status_code=400, detail="polygon too small")
    usable_poly = Polygon(poly_mm)

    # clearspace_mm 기본값 보정 — 브랜드 매뉴얼에 수치 없을 때 면적 기준 적용
    # nodes_large 기본값(1000) vs nodes_small 기본값(600) 차이를 여기서 해소
    area_m2 = usable_poly.area / 1_000_000
    brand_info = brand_dict.get("brand", {})
    clearspace = brand_info.get("clearspace_mm", {})
    if isinstance(clearspace, dict) and clearspace.get("value") is None:
        clearspace["value"] = 600 if area_m2 < SCALE_THRESHOLD_M2 else 1000
        clearspace["source"] = "default_by_area"
        logger.info(f"[space-data] clearspace_mm 기본값 적용: {clearspace['value']}mm (면적 {area_m2:.1f}m²)")

    # entrance
    ent = ad.get("entrance")
    if isinstance(ent, dict) and "x_px" in ent:
        entrance_mm = (ent["x_px"] * scale, ent["y_px"] * scale)
    elif isinstance(ent, dict) and "points" in ent:
        pts = ent["points"]
        if pts:
            entrance_mm = (pts[0]["x_px"] * scale, pts[0]["y_px"] * scale)
        else:
            entrance_mm = None
    else:
        entrance_mm = None

    # 시설물 → mm
    sprinklers_mm = [(s["x_px"] * scale, s["y_px"] * scale) for s in ad.get("sprinklers", []) if isinstance(s, dict)]
    hydrants_mm = [(s["x_px"] * scale, s["y_px"] * scale) for s in ad.get("fire_hydrants", []) if isinstance(s, dict)]
    electric_panels_mm = [(s["x_px"] * scale, s["y_px"] * scale) for s in ad.get("electrical_panels", []) if isinstance(s, dict)]

    # brand_data 구성
    brand_data = brand_dict if "brand" in brand_dict else {
        "brand": {**brand_dict, "brand_category": brand_category},
        "fire": {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200},
        "construction": {"wall_clearance_mm": 300, "object_gap_mm": 300},
        "placement_rules": brand_dict.get("placement_rules", []),
    }
    # [2026-04-22 S-8f] 프론트 선택 brand_category 우선 override.
    # LLM 매뉴얼 파싱이 "기타" 로 회귀하는 경우 (LUMIA PDF → 기타 관측) 방지.
    # MAX_COUNT_BY_CATEGORY["기타"] → CHARACTER_IP fallback 으로 뷰티 매장에
    # 캐릭터 IP 배치룰 적용되던 버그.
    if brand_category and brand_category != "기타":
        brand_data = dict(brand_data)
        brand_data["brand"] = {**brand_data.get("brand", {}), "brand_category": brand_category}

    # inaccessible_rooms → Polygon 변환 (파서가 반환한 dead_zone 폴리곤)
    inaccessible_polys = []
    inaccessible_types = []  # core/pillar 타입 매칭
    for room in ad.get("inaccessible_rooms", []):
        pts = room.get("polygon_px", [])
        if len(pts) >= 3:
            mm_pts = [(p[0] * scale, p[1] * scale) for p in pts]
            poly = Polygon(mm_pts)
            if poly.is_valid and poly.area > 0:
                inaccessible_polys.append(poly)
                inaccessible_types.append(room.get("type", "unknown"))

    state = {
        "usable_poly": usable_poly,
        "entrance_mm": entrance_mm,
        "all_entrances_mm": build_entrances_mm(ad.get("entrances", []), entrance_mm, scale),
        "entrance_width_mm": 1200,
        "sprinklers_mm": sprinklers_mm,
        "hydrants_mm": hydrants_mm,
        "electric_panels_mm": electric_panels_mm,
        "inner_wall_linestrings": [],
        "inaccessible_polys": inaccessible_polys,
        "inaccessible_types": inaccessible_types,
        "dead_zones": [],
        "floor_polygon_px": poly_px,
        "scale_mm_per_px": scale,
        "ceiling_height_mm": ad.get("ceiling_height_mm"),
        "brand_data": brand_data,
        "fallback_round": 0,
    }

    # 면적 기준 분기
    large = is_large(state)

    if large:
        from app.nodes_large.b_space_data import dead_zone, ref_point_gen, walk_mm
        state.update(dead_zone.run(state))
        state.update(ref_point_gen.run(state))
        state.update(walk_mm.run(state))
        state["_scale_type"] = "large"
    else:
        from app.nodes_small import dead_zone, ref_point_gen, slot_gen, walk_mm
        state["venue_type"] = venue_type  # 소형만 venue_type 적용
        state["facade_type"] = facade_type  # 파사드 타입 (facade_rules.py)
        state.update(dead_zone.run(state))
        state.update(slot_gen.run(state))
        state.update(ref_point_gen.run(state))
        state.update(walk_mm.run(state))
        state["_scale_type"] = "small"

    # ── 수동 데드존 추가 (원형 or 사각형) ──
    manual_dzs = body.get("manual_dead_zones_px", [])
    if manual_dzs:
        existing = state.get("dead_zones") or []
        for dz in manual_dzs:
            x_mm = dz["x_px"] * scale
            y_mm = dz["y_px"] * scale
            if dz.get("shape") == "rect":
                w_mm = dz["w_px"] * scale
                h_mm = dz["h_px"] * scale
                existing.append(shapely_box(x_mm, y_mm, x_mm + w_mm, y_mm + h_mm))
            else:
                r_mm = dz["radius_px"] * scale
                existing.append(Point(x_mm, y_mm).buffer(r_mm))
        state["dead_zones"] = existing
        logger.info(f"[space-data] 수동 데드존 {len(manual_dzs)}개 추가")

    # ── 세션 캐시 비활성화 (개발 중) ──
    session_id = str(uuid.uuid4())[:8]
    # _state_cache[session_id] = state

    area_m2 = round(usable_poly.area / 1_000_000, 2)
    logger.info(f"[space-data] session={session_id}, area={area_m2}m², "
                f"scale_type={'large' if large else 'small'}, "
                f"ref_points={len(state.get('reference_points', []))}, "
                f"slots={len(state.get('slots', {}))}")

    sd = serialize_space_data(state, session_id)

    # [2026-04-22 S-1] 감압존 적용값 JSON 에 명시 (로그 휘발성 회피)
    # 1-3 (#533) C3: slot_gen.run() 이 박은 면적별 동적 값 우선, 없으면 module 상수.
    if not large:
        from app.nodes_small.slot_gen import DECOMPRESSION_RADIUS_MM as _SM_DECOMP
        sd["decompression_radius_mm"] = state.get("decompression_radius_mm", _SM_DECOMP)

    return {"space_data": sd}
