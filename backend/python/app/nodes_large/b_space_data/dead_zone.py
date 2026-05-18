"""
Dead Zone 생성 노드 — Rendy 코드 베이스.

설비 buffer (300/500/600mm) + inaccessible rooms + inner walls 150mm buffer.
"""
import logging

from shapely.geometry import LineString, Point, box as shapely_box

from app.state import LargeState

logger = logging.getLogger(__name__)

DEAD_ZONE_BUFFER = {
    "sprinkler": 900,
    "fire_hydrant": 500,
    "electrical_panel": 600,
    # 2026-05-05 burning_task 1단계 — pillar/toilet 흡수.
    "pillar": 100,   # 기둥 자체 크기 + 100mm 여유 (가구 밀착 회피)
    "toilet": 0,     # 화장실 영역 자체가 buffer (추가 X)
}
INNER_WALL_BUFFER_MM = 150


def run(state: LargeState) -> LargeState:
    """Dead Zone + inner wall LineString 생성. dead_zone_types는 dead_zones와 인덱스 1:1 매칭 (small 정합)."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return {"dead_zones": [], "dead_zone_types": [], "inner_wall_linestrings": []}

    scale = state.get("scale_mm_per_px") or 1.0
    sprinklers_mm = state.get("sprinklers_mm") or []
    hydrants_mm = state.get("hydrants_mm") or []
    panels_mm = state.get("electric_panels_mm") or []
    # 2026-05-05 burning_task 1단계 — pillar_toilet_detect 노드 출력.
    pillars_mm = state.get("pillars_mm") or []
    toilets_mm = state.get("toilets_mm") or []
    inaccessible_polys = state.get("inaccessible_polys") or []
    inaccessible_types = state.get("inaccessible_types") or []
    inner_walls_raw = state.get("inner_walls") or []
    floor_px_min_x = state.get("floor_px_min_x", 0)
    floor_px_min_y = state.get("floor_px_min_y", 0)

    dead_zones = []
    dead_zone_types = []  # 각 dead_zone의 출처 라벨 — small 정합

    # 설비 buffer
    # 2026-05-04 - 스프링클러는 데드존에서 사전 제외 (small mirror).
    #   small 은 placement 높이 필터로 처리 (천장 ≥ 2550mm 면 차단 X).
    #   large 는 placement 필터 추가 X (사용자 결정 - 큰 부지에 의도적으로 안 넣음).
    #   위치 마커는 spaceData.sprinklers 별도 필드로 표시되니 dead_zones 에서만 빼면 시각화도 깨끗.
    for i, pt in enumerate(sprinklers_mm):
        logger.info(f"[dead_zone] sprinkler #{i}: ({pt[0]:.0f}, {pt[1]:.0f}), 데드존 생략 (large 정책)")
    for pt in hydrants_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["fire_hydrant"]))
        dead_zone_types.append("fire_hydrant")
    for pt in panels_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["electrical_panel"]))
        dead_zone_types.append("electrical_panel")

    # 2026-05-05 burning_task 1단계 — 기둥 (사각형 + 100mm buffer)
    for i, p in enumerate(pillars_mm):
        try:
            x, y, w, h = p["x_mm"], p["y_mm"], p["w_mm"], p["h_mm"]
        except (KeyError, TypeError):
            continue
        poly = shapely_box(x, y, x + w, y + h).buffer(DEAD_ZONE_BUFFER["pillar"])
        if usable_poly:
            poly = poly.intersection(usable_poly)
        if not poly.is_empty:
            dead_zones.append(poly)
            dead_zone_types.append("pillar")
            logger.info(f"[dead_zone] pillar #{i}: ({x:.0f}, {y:.0f}, {w:.0f}x{h:.0f}mm)")

    # 2026-05-05 burning_task 1단계 — 화장실 (사각형, buffer 0 = 영역 자체가 dead)
    for i, t in enumerate(toilets_mm):
        try:
            x, y, w, h = t["x_mm"], t["y_mm"], t["w_mm"], t["h_mm"]
        except (KeyError, TypeError):
            continue
        poly = shapely_box(x, y, x + w, y + h)
        if usable_poly:
            poly = poly.intersection(usable_poly)
        if not poly.is_empty:
            dead_zones.append(poly)
            dead_zone_types.append("toilet")
            logger.info(f"[dead_zone] toilet #{i}: ({x:.0f}, {y:.0f}, {w:.0f}x{h:.0f}mm) {t.get('label', '')}")

    # 비상구 2-zone 시스템 (buildup/agent2_floor.py)
    #   Zone 1: 방사형 1200mm 원형 버퍼
    #   Zone 2: 복도 확장 1200×2400mm 사각형
    all_entrances = state.get("all_entrances_mm") or []
    for ent in all_entrances:
        if ent.get("type") != "EMERGENCY_EXIT":
            continue
        ex, ey = ent["coord"]
        # Zone 1: 방사형
        dead_zones.append(Point(ex, ey).buffer(1200))
        dead_zone_types.append("emergency_exit")
        # Zone 2: 복도 확장 (전면 2400mm 깊이)
        dead_zones.append(shapely_box(ex - 1200, ey - 600, ex + 1200, ey + 600))
        dead_zone_types.append("emergency_exit")

    # inaccessible rooms
    for i, room_poly in enumerate(inaccessible_polys):
        if room_poly.is_valid and room_poly.area > 0:
            dead_zones.append(room_poly)
            room_type = inaccessible_types[i] if i < len(inaccessible_types) else "unknown"
            dead_zone_types.append(room_type)

    # inner walls → LineString + dead zone
    inner_wall_linestrings = []
    for wall in inner_walls_raw:
        start_px = wall.get("start_px") or wall.get("start_px", (0, 0))
        end_px = wall.get("end_px") or wall.get("end_px", (0, 0))
        wx0, wy0 = start_px
        wx1, wy1 = end_px

        # 좌표 보정 (floor bbox 밖이면 오프셋 추가)
        if wx0 < floor_px_min_x * 0.8 or wy0 < floor_px_min_y * 0.8:
            wx0 += floor_px_min_x
            wy0 += floor_px_min_y
            wx1 += floor_px_min_x
            wy1 += floor_px_min_y

        wall_ls = LineString([
            (wx0 * scale, wy0 * scale),
            (wx1 * scale, wy1 * scale),
        ])
        if wall_ls.length > 0:
            clipped = usable_poly.intersection(wall_ls)
            if not clipped.is_empty and clipped.length > 0:
                if clipped.geom_type == "MultiLineString":
                    clipped = max(clipped.geoms, key=lambda g: g.length)
                if clipped.geom_type == "LineString" and clipped.length > 10:
                    inner_wall_linestrings.append(clipped)
                    dead_zones.append(clipped.buffer(INNER_WALL_BUFFER_MM))
                    dead_zone_types.append("inner_wall")

    from collections import Counter
    type_counts = dict(Counter(dead_zone_types))
    logger.info(f"[dead_zone] {len(dead_zones)} dead zones (types={type_counts}), "
                f"{len(inner_wall_linestrings)} inner wall linestrings")

    return {
        "dead_zones": dead_zones,
        "dead_zone_types": dead_zone_types,
        "inner_wall_linestrings": inner_wall_linestrings,
    }
