"""
Dead Zone 생성 노드 — Rendy 코드 베이스.

설비 buffer (300/500/600mm) + inaccessible rooms + inner walls 150mm buffer.
"""
import logging

from shapely.geometry import LineString, Point

from app.state import SmallState

logger = logging.getLogger(__name__)

DEAD_ZONE_BUFFER = {
    "fire_hydrant": 500,
    "electrical_panel": 600,
}
INNER_WALL_BUFFER_MM = 150


def run(state: SmallState) -> SmallState:
    """Dead Zone + inner wall LineString 생성."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return {"dead_zones": [], "inner_wall_linestrings": []}

    scale = state.get("scale_mm_per_px") or 1.0
    sprinklers_mm = state.get("sprinklers_mm") or []
    hydrants_mm = state.get("hydrants_mm") or []
    electric_panels_mm = state.get("electric_panels_mm") or []
    inaccessible_polys = state.get("inaccessible_polys") or []
    inner_walls_raw = state.get("inner_walls") or []
    floor_px_min_x = state.get("floor_px_min_x", 0)
    floor_px_min_y = state.get("floor_px_min_y", 0)

    dead_zones = []
    dead_zone_types = []  # 각 dead_zone의 타입 ("sprinkler", "fire_hydrant", "electrical_panel", "inaccessible", "emergency_exit")

    # 설비 buffer — 스프링클러는 높이 판별 룰(placement.py 0.5단계)이 처리. 바닥 dead zone 제거.
    for i, pt in enumerate(sprinklers_mm):
        logger.info(f"[dead_zone] sprinkler #{i}: ({pt[0]:.0f}, {pt[1]:.0f}), 바닥 dead zone 생략 → 높이 판별 룰로 위임")
    for i, pt in enumerate(hydrants_mm):
        dz = Point(pt).buffer(DEAD_ZONE_BUFFER["fire_hydrant"])
        if usable_poly:
            dz = dz.intersection(usable_poly)
        if not dz.is_empty:
            dead_zones.append(dz)
            dead_zone_types.append("fire_hydrant")
        logger.info(f"[dead_zone] hydrant #{i}: ({pt[0]:.0f}, {pt[1]:.0f}), buffer={DEAD_ZONE_BUFFER['fire_hydrant']}mm")
    # 분전반 — dot(벽 위)에서 벽 수직 법선 방향으로 800x900 박스
    import math
    EP_W = 800   # 작업 폭
    EP_D = 900   # 전면 작업 깊이
    for i, pt in enumerate(electric_panels_mm):
        px, py = pt[0], pt[1]
        if usable_poly:
            # 가장 가까운 벽 → 벽 수직 법선
            # EP dot은 외벽 또는 내벽(화장실/계단) 위에 있을 수 있음
            # → 외벽 + inaccessible_polys 경계 모두 검색
            from shapely.geometry import LineString as _LS
            EDGE_THRESHOLD = 50  # mm
            candidates = []
            # 1) 외벽 (usable_poly.exterior)
            ext = list(usable_poly.exterior.coords)
            for j in range(len(ext) - 1):
                e = _LS([ext[j], ext[j+1]])
                d = e.distance(Point(px, py))
                if d < EDGE_THRESHOLD:
                    candidates.append((e, d, e.length))
            # 2) 내벽 (inaccessible_polys 경계)
            for ipoly in inaccessible_polys:
                if not hasattr(ipoly, 'exterior'):
                    continue
                icoords = list(ipoly.exterior.coords)
                for j in range(len(icoords) - 1):
                    e = _LS([icoords[j], icoords[j+1]])
                    d = e.distance(Point(px, py))
                    if d < EDGE_THRESHOLD:
                        candidates.append((e, d, e.length))
            # 임계값 내 후보 중 가장 긴 edge (본벽)
            if candidates:
                candidates.sort(key=lambda c: c[2], reverse=True)
                best_edge = candidates[0][0]
                logger.info(f"[dead_zone] panel #{i}: 벽 edge 후보 {len(candidates)}개, 선택 길이={candidates[0][2]:.0f}mm, dist={candidates[0][1]:.1f}mm")
            else:
                # fallback: 최소 거리 (외벽만)
                best_edge, best_d = None, float("inf")
                for j in range(len(ext) - 1):
                    e = _LS([ext[j], ext[j+1]])
                    d = e.distance(Point(px, py))
                    if d < best_d:
                        best_d = d
                        best_edge = e
                logger.info(f"[dead_zone] panel #{i}: 임계값 내 edge 없음, fallback dist={best_d:.0f}mm")
            if best_edge:
                e0, e1 = best_edge.coords[0], best_edge.coords[1]
                dx, dy = e1[0]-e0[0], e1[1]-e0[1]
                el = math.hypot(dx, dy) or 1
                wx, wy = dx/el, dy/el  # 벽 방향 단위벡터
                # 벽 수직 법선 후보 2개
                n1x, n1y = -wy, wx
                n2x, n2y = wy, -wx
                # 안쪽 판별: centroid에 가까운 방향이 매장 안쪽
                ccx, ccy = usable_poly.centroid.x, usable_poly.centroid.y
                d1 = math.hypot(px + n1x * EP_D - ccx, py + n1y * EP_D - ccy)
                d2 = math.hypot(px + n2x * EP_D - ccx, py + n2y * EP_D - ccy)
                if d1 < d2:
                    nx, ny = n1x, n1y
                else:
                    nx, ny = n2x, n2y
                # 800x900 박스: dot에서 벽 수직 방향으로
                hw = EP_W / 2
                corners = [
                    (px - wx*hw, py - wy*hw),
                    (px + wx*hw, py + wy*hw),
                    (px + wx*hw + nx*EP_D, py + wy*hw + ny*EP_D),
                    (px - wx*hw + nx*EP_D, py - wy*hw + ny*EP_D),
                ]
                from shapely.geometry import Polygon as _Poly
                dz = _Poly(corners)
                if not dz.is_empty:
                    dead_zones.append(dz)
                    dead_zone_types.append("electrical_panel")
                logger.info(f"[dead_zone] panel #{i}: ({px:.0f}, {py:.0f}), box {EP_W}x{EP_D}mm, normal=({nx:.2f},{ny:.2f})")
                continue
        # fallback
        dz = Point(px, py).buffer(600, cap_style=3)
        if not dz.is_empty:
            dead_zones.append(dz)
            dead_zone_types.append("electrical_panel")
        logger.info(f"[dead_zone] panel #{i}: ({px:.0f}, {py:.0f}), fallback box 600mm")

    # 비상구 — 면적 분기: 소형 900mm 단일, 중형 1200mm+2400mm 2-zone
    from shapely.geometry import box as shapely_box
    from app.constants import SMALL_AREA_THRESHOLD_MM2
    floor_area = usable_poly.area if usable_poly else 0
    is_small = floor_area < SMALL_AREA_THRESHOLD_MM2  # 66M mm² = 20평
    all_entrances = state.get("all_entrances_mm") or []
    for ent in all_entrances:
        if ent.get("type") != "EMERGENCY_EXIT":
            continue
        ex, ey = ent["coord"]
        if is_small:
            dz = Point(ex, ey).buffer(900)
            if usable_poly:
                dz = dz.intersection(usable_poly)
            if not dz.is_empty:
                dead_zones.append(dz)
                dead_zone_types.append("emergency_exit")
        else:
            dz1 = Point(ex, ey).buffer(1200)
            dz2 = shapely_box(ex - 1200, ey - 600, ex + 1200, ey + 600)
            if usable_poly:
                dz1 = dz1.intersection(usable_poly)
                dz2 = dz2.intersection(usable_poly)
            if not dz1.is_empty:
                dead_zones.append(dz1)
                dead_zone_types.append("emergency_exit")
            if not dz2.is_empty:
                dead_zones.append(dz2)
                dead_zone_types.append("emergency_exit")

    # inaccessible rooms (화장실/계단) — polygon 자체만 dead zone
    # 버퍼 없음. 물리적 객체만 차단 원칙.
    inaccessible_types = state.get("inaccessible_types") or []
    for i, room_poly in enumerate(inaccessible_polys):
        if room_poly.is_valid and room_poly.area > 0:
            dead_zones.append(room_poly)
            room_type = inaccessible_types[i] if i < len(inaccessible_types) else "unknown"
            dead_zone_types.append(room_type)
            # core 진입로 버퍼 삭제 — 소형 매장에서 가상 dead zone이 배치 공간을 과도하게 잠식
            # core polygon 자체만 dead zone으로 유지. 물리적 객체만 차단.

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

    logger.info(f"[dead_zone] {len(dead_zones)} dead zones, "
                f"{len(inner_wall_linestrings)} inner wall linestrings")

    return {
        "dead_zones": dead_zones,
        "dead_zone_types": dead_zone_types,
        "inner_wall_linestrings": inner_wall_linestrings,
    }
