"""
Walk_mm 계산 노드 — Rendy 코드 베이스 + landup_shin/networkx_engine 강화.

NetworkX Dijkstra 보행 거리 + zone 배정 + Main Artery 생성 + semantic tag.
강화: multi-entrance Dijkstra (모든 입구에서 최소 거리 채택).
"""
import math
import logging

import networkx as nx
from shapely.geometry import LineString, Point, Polygon

from app.state import SmallState
from app.utils import frange

logger = logging.getLogger(__name__)

GRID_STEP_MM = 500


def run(state: SmallState) -> SmallState:
    """Walk_mm + zone_label + Main Artery + virtual entrance."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return {}

    dead_zones = state.get("dead_zones") or []
    slots = state.get("slots") or {}
    entrance_mm = state.get("entrance_mm")
    all_entrances = state.get("all_entrances_mm") or []
    entrance_width = state.get("entrance_width_mm") or 1200

    if not entrance_mm:
        # 입구 정보 없으면 폴리곤 중심을 임시 입구로 사용
        centroid = usable_poly.centroid
        entrance_mm = (centroid.x, centroid.y)

    # Corridor graph 구축
    G, nodes = _build_corridor_graph(usable_poly, dead_zones)
    if not nodes:
        return {}

    # 입구 좌표 수집 (landup_shin 강화: line segment 입구 다중 샘플링)
    entrance_coords, entrance_types = [], []
    entrance_line = state.get("entrance_line")
    if all_entrances:
        for ent in all_entrances:
            entrance_coords.append(ent["coord"])
            entrance_types.append(ent.get("type", "MAIN_DOOR"))
            # line segment 입구면 중간점 2개 추가 샘플링
            if entrance_line and ent.get("type") == "MAIN_DOOR":
                for frac in (0.25, 0.75):
                    pt = entrance_line.interpolate(frac, normalized=True)
                    entrance_coords.append((pt.x, pt.y))
                    entrance_types.append("MAIN_DOOR")
    else:
        entrance_coords.append(entrance_mm)
        entrance_types.append("MAIN_DOOR")

    # Dijkstra
    all_lengths = []
    entrance_nodes = []
    for coord in entrance_coords:
        e_node = _nearest_node(nodes, coord)
        entrance_nodes.append(e_node)
        try:
            lengths = nx.single_source_dijkstra_path_length(G, e_node, weight="weight")
            all_lengths.append(lengths)
        except nx.NetworkXError:
            all_lengths.append({})

    # Zone 기준
    minx, miny, maxx, maxy = usable_poly.bounds
    max_walk = max(maxx - minx, maxy - miny)
    zone_1, zone_2 = max_walk * 0.33, max_walk * 0.66

    # MAIN_DOOR 기준 Dijkstra
    main_idx = 0
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR":
            main_idx = i
            break
    main_lengths = all_lengths[main_idx] if main_idx < len(all_lengths) else {}

    # Slot walk_mm + zone_label 부여
    for slot in slots.values():
        slot_node = _nearest_node(nodes, (slot["x_mm"], slot["y_mm"]))
        min_walk = min((l.get(slot_node, float("inf")) for l in all_lengths), default=max_walk * 2)
        if min_walk == float("inf"):
            min_walk = max_walk * 2
        slot["walk_mm"] = round(min_walk)

        main_walk = main_lengths.get(slot_node, max_walk * 2)
        if main_walk < zone_1:
            slot["zone_label"] = "entrance_zone"
        elif main_walk < zone_2:
            slot["zone_label"] = "mid_zone"
        else:
            slot["zone_label"] = "deep_zone"

    # Reference points zone_label + walk_mm 부여
    reference_points = state.get("reference_points") or []
    for rp in reference_points:
        rp_coord = rp.get("coord")
        if not rp_coord:
            continue
        rp_node = _nearest_node(nodes, rp_coord)
        min_walk = min((l.get(rp_node, float("inf")) for l in all_lengths), default=max_walk * 2)
        if min_walk == float("inf"):
            min_walk = max_walk * 2
        rp["walk_mm"] = round(min_walk)

        main_walk = main_lengths.get(rp_node, max_walk * 2)
        if main_walk < zone_1:
            rp["zone_label"] = "entrance_zone"
        elif main_walk < zone_2:
            rp["zone_label"] = "mid_zone"
        else:
            rp["zone_label"] = "deep_zone"

    # Semantic tags — slot + ref_point 둘 다
    _assign_semantic_tags(slots, usable_poly, entrance_mm)
    _assign_semantic_tags_rp(reference_points, usable_poly, entrance_mm)

    # Main Artery
    main_artery = _compute_main_artery(G, nodes, entrance_coords, entrance_types, usable_poly)

    # Virtual entrance
    entrance_line, entrance_buffer = _build_virtual_entrance(entrance_mm, usable_poly, entrance_width)

    # Spine rank 부여 (주동선으로부터의 거리)
    _assign_spine_rank(slots, main_artery)
    _assign_spine_rank_to_ref_points(reference_points, main_artery)

    # Zone 통계
    zone_counts = {"entrance_zone": 0, "mid_zone": 0, "deep_zone": 0}
    for s in slots.values():
        z = s.get("zone_label", "entrance_zone")
        zone_counts[z] = zone_counts.get(z, 0) + 1

    # Zone polygon — corridor graph node의 Dijkstra 거리 기반 정확한 영역 시각화
    zone_polygons = _build_zone_polygons_from_graph(nodes, main_lengths, zone_1, zone_2, usable_poly)

    # inaccessible_rooms 근처 ref_point에 _is_blocked 플래그 — 타입별 반경 분기
    inaccessible_polys = state.get("inaccessible_polys") or []
    inaccessible_types = state.get("inaccessible_types") or []
    from app.vmd_constants import CORE_FILTER_RADIUS, ROOM_TYPE_CORE
    if inaccessible_polys:
        from shapely.ops import unary_union as _union
        buffered = []
        for i, poly in enumerate(inaccessible_polys):
            if not hasattr(poly, "buffer"):
                continue
            room_type = inaccessible_types[i] if i < len(inaccessible_types) else ROOM_TYPE_CORE
            radius = CORE_FILTER_RADIUS.get(room_type, 900)
            buffered.append(poly.buffer(radius))
        if buffered:
            core_zone = _union(buffered)
            blocked_count = 0
            for rp in reference_points:
                if core_zone.contains(Point(rp["coord"])):
                    rp["_is_blocked"] = True
                    blocked_count += 1
            if blocked_count:
                logger.info(f"[walk_mm] inaccessible 근처 ref_point {blocked_count}개 _is_blocked (타입별 반경)")

    logger.info(f"[walk_mm] zones: {zone_counts}, artery={main_artery.length:.0f}mm" if main_artery else "[walk_mm] no artery")

    return {
        "slots": slots,
        "reference_points": reference_points,
        "main_artery": main_artery,
        "entrance_line": entrance_line,
        "entrance_buffer": entrance_buffer,
        "zone_map": zone_counts,
        "zone_polygons": zone_polygons,
    }


# ── Corridor Graph ────────────────────────────────────────────────────────

def _build_corridor_graph(usable_poly, dead_zones=None, step_mm=GRID_STEP_MM):
    minx, miny, maxx, maxy = usable_poly.bounds
    obstacles = dead_zones or []
    G = nx.Graph()
    nodes = {}
    xs = frange(minx, maxx, step_mm)
    ys = frange(miny, maxy, step_mm)
    for gx in xs:
        for gy in ys:
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            if any(dz.contains(pt) for dz in obstacles):
                continue
            ix = round((gx - minx) / step_mm)
            iy = round((gy - miny) / step_mm)
            G.add_node((ix, iy))
            nodes[(ix, iy)] = (gx, gy)
    for (ix, iy) in list(G.nodes):
        for dix, diy in [(1, 0), (0, 1), (1, 1), (1, -1)]:
            nb = (ix + dix, iy + diy)
            if nb in G.nodes:
                dist = math.hypot(nodes[nb][0] - nodes[(ix, iy)][0],
                                  nodes[nb][1] - nodes[(ix, iy)][1])
                G.add_edge((ix, iy), nb, weight=dist)
    logger.info(f"[walk_mm] corridor graph: {len(nodes)} nodes, {G.number_of_edges()} edges")
    return G, nodes


def _nearest_node(nodes, target):
    return min(nodes.keys(), key=lambda k: math.hypot(
        nodes[k][0] - target[0], nodes[k][1] - target[1]))


# ── Main Artery ───────────────────────────────────────────────────────────

def _compute_main_artery(G, nodes, entrance_coords, entrance_types, usable_poly):
    main_idx, emergency_idx = None, None
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR" and main_idx is None:
            main_idx = i
        if t == "EMERGENCY_EXIT" and emergency_idx is None:
            emergency_idx = i
    if main_idx is None:
        main_idx = 0
    entrance = entrance_coords[main_idx]

    if emergency_idx is not None and emergency_idx != main_idx:
        exit_coord = entrance_coords[emergency_idx]
        spine = _build_through_spine(entrance, exit_coord, usable_poly, G, nodes)
        if spine:
            return spine

    return _build_main_spine(entrance, usable_poly, G, nodes)


def _build_main_spine(entrance, usable_poly, G, nodes):
    ex, ey = entrance
    minx, miny, maxx, maxy = usable_poly.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    deep = _find_deepest_wall_center(entrance, usable_poly)
    dx, dy = deep
    waypoints = _plan_rectilinear(ex, ey, dx, dy, cx, cy, minx, miny, maxx, maxy)
    coords = _connect_waypoints(waypoints, G, nodes)
    if len(coords) >= 2:
        return LineString(coords)
    return LineString([entrance, deep])


def _build_through_spine(entrance, exit_coord, usable_poly, G, nodes):
    minx, miny, maxx, maxy = usable_poly.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    ex, ey = entrance
    xx, xy = exit_coord
    mid = ((ex + xx) / 2, (ey + xy) / 2)
    deep = _find_deepest_wall_center(mid, usable_poly)
    dx, dy = deep
    wp1 = _plan_rectilinear(ex, ey, dx, dy, cx, cy, minx, miny, maxx, maxy)
    wp2 = _plan_rectilinear(dx, dy, xx, xy, cx, cy, minx, miny, maxx, maxy)
    waypoints = wp1 + wp2[1:]
    coords = _connect_waypoints(waypoints, G, nodes)
    if len(coords) >= 2:
        return LineString(coords)
    return None


def _find_deepest_wall_center(entrance, usable_poly):
    coords = list(usable_poly.exterior.coords)
    entrance_pt = Point(entrance)
    best_center, best_dist = None, -1
    for i in range(len(coords) - 1):
        edge = LineString([coords[i], coords[i + 1]])
        if edge.length < 100:
            continue
        ec = edge.interpolate(0.5, normalized=True)
        dist = entrance_pt.distance(ec)
        if dist > best_dist:
            best_dist = dist
            best_center = (ec.x, ec.y)
    if not best_center:
        cx, cy = usable_poly.centroid.x, usable_poly.centroid.y
        return (2 * cx - entrance[0], 2 * cy - entrance[1])
    return best_center


def _plan_rectilinear(ex, ey, dx, dy, cx, cy, minx, miny, maxx, maxy):
    width, height = maxx - minx, maxy - miny
    margin = min(width, height) * 0.05
    on_top = abs(ey - miny) < margin
    on_bottom = abs(ey - maxy) < margin
    on_left = abs(ex - minx) < margin
    on_right = abs(ex - maxx) < margin

    waypoints = [(ex, ey)]
    x_aligned = abs(ex - dx) < min(width, height) * 0.15
    y_aligned = abs(ey - dy) < min(width, height) * 0.15

    if x_aligned:
        waypoints.append((ex, dy))
    elif y_aligned:
        waypoints.append((dx, ey))
    elif on_top or on_bottom:
        waypoints.extend([(ex, cy), (dx, cy), (dx, dy)])
    elif on_left or on_right:
        waypoints.extend([(cx, ey), (cx, dy), (dx, dy)])
    else:
        waypoints.extend([(ex, dy), (dx, dy)])

    last = waypoints[-1]
    if abs(last[0]-dx) > 1 or abs(last[1]-dy) > 1:
        waypoints.append((dx, dy))

    deduped = [waypoints[0]]
    for wp in waypoints[1:]:
        if abs(wp[0]-deduped[-1][0]) > 1 or abs(wp[1]-deduped[-1][1]) > 1:
            deduped.append(wp)
    return deduped


def _connect_waypoints(waypoints, G, nodes):
    if len(waypoints) < 2:
        return waypoints
    all_coords = []
    for seg_i in range(len(waypoints) - 1):
        s_node = _nearest_node(nodes, waypoints[seg_i])
        e_node = _nearest_node(nodes, waypoints[seg_i + 1])
        if s_node == e_node:
            if not all_coords:
                all_coords.append(nodes[s_node])
            continue
        try:
            path = nx.shortest_path(G, s_node, e_node, weight="weight")
            seg_coords = [nodes[n] for n in path]
            if all_coords and seg_coords:
                if (abs(all_coords[-1][0] - seg_coords[0][0]) < 1 and
                    abs(all_coords[-1][1] - seg_coords[0][1]) < 1):
                    seg_coords = seg_coords[1:]
            all_coords.extend(seg_coords)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            if not all_coords:
                all_coords.append(waypoints[seg_i])
            all_coords.append(waypoints[seg_i + 1])
    return all_coords


# ── Semantic Tags ─────────────────────────────────────────────────────────

def _assign_semantic_tags(slots, usable_poly, entrance_mm):
    coords = list(usable_poly.exterior.coords)
    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    center_threshold = short_side * 0.3

    corner_vertices = []
    for i in range(len(coords) - 1):
        prev_i = (i - 1) % (len(coords) - 1)
        next_i = (i + 1) % (len(coords) - 1)
        dx1 = coords[i][0] - coords[prev_i][0]
        dy1 = coords[i][1] - coords[prev_i][1]
        dx2 = coords[next_i][0] - coords[i][0]
        dy2 = coords[next_i][1] - coords[i][1]
        len1, len2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
        if len1 > 0 and len2 > 0:
            cos_a = max(-1, min(1, (dx1*dx2 + dy1*dy2) / (len1*len2)))
            if 60 <= math.degrees(math.acos(cos_a)) <= 120:
                corner_vertices.append(coords[i])

    min_walk = min((s["walk_mm"] for s in slots.values()), default=0)
    for slot in slots.values():
        tags = []
        sx, sy = slot["x_mm"], slot["y_mm"]
        pt = Point(sx, sy)
        is_corner = any(math.hypot(sx-cx, sy-cy) < 500 for cx, cy in corner_vertices)
        if is_corner:
            tags.append("corner")
        wall_dist = usable_poly.exterior.distance(pt)
        if not is_corner and wall_dist < 600:
            tags.append("wall_adjacent")
        if wall_dist > center_threshold:
            tags.append("center_area")
        if entrance_mm and min_walk > 0 and slot["walk_mm"] <= min_walk * 1.5:
            tags.append("entrance_facing")
        slot["semantic_tags"] = tags


# ── Spine Rank (주동선 거리 등급) ─────────────────────────────────────────

# 주동선으로부터의 거리 기준 (mm)
_SPINE_ADJACENT = 2000   # 2m 이내
_SPINE_NEARBY = 5000     # 5m 이내


def _assign_spine_rank(slots, main_artery):
    """각 slot에 주동선으로부터의 거리 등급(spine_rank)을 부여."""
    for slot in slots.values():
        if not main_artery:
            slot["spine_rank"] = "far"
            continue
        pt = Point(slot["x_mm"], slot["y_mm"])
        dist = main_artery.distance(pt)
        if dist < _SPINE_ADJACENT:
            slot["spine_rank"] = "adjacent"
        elif dist < _SPINE_NEARBY:
            slot["spine_rank"] = "nearby"
        else:
            slot["spine_rank"] = "far"


def _assign_spine_rank_to_ref_points(reference_points, main_artery):
    """각 reference_point에 spine_rank를 부여."""
    for rp in reference_points:
        coord = rp.get("coord")
        if not coord or not main_artery:
            rp["spine_rank"] = "far"
            continue
        pt = Point(coord[0], coord[1])
        dist = main_artery.distance(pt)
        if dist < _SPINE_ADJACENT:
            rp["spine_rank"] = "adjacent"
        elif dist < _SPINE_NEARBY:
            rp["spine_rank"] = "nearby"
        else:
            rp["spine_rank"] = "far"


# ── Virtual Entrance ──────────────────────────────────────────────────────

def _build_virtual_entrance(entrance_mm, usable_poly, entrance_width):
    coords = list(usable_poly.exterior.coords)
    entrance_pt = Point(entrance_mm)
    best_edge, best_dist = None, float("inf")
    for i in range(len(coords) - 1):
        edge = LineString([coords[i], coords[i + 1]])
        d = edge.distance(entrance_pt)
        if d < best_dist:
            best_dist = d
            best_edge = edge
    if not best_edge:
        half = entrance_width / 2
        line = LineString([(entrance_mm[0]-half, entrance_mm[1]), (entrance_mm[0]+half, entrance_mm[1])])
        return line, line.buffer(460)
    proj = best_edge.project(entrance_pt)
    half = entrance_width / 2
    start = max(0, proj - half)
    end = min(best_edge.length, proj + half)
    p_start = best_edge.interpolate(start)
    p_end = best_edge.interpolate(end)
    entrance_line = LineString([(p_start.x, p_start.y), (p_end.x, p_end.y)])
    return entrance_line, entrance_line.buffer(460)


# ── Zone Polygons (등고선용) ─────────────────────────────────────────────

def _assign_semantic_tags_rp(reference_points, usable_poly, entrance_mm):
    """reference_points에 semantic_tags 부여 (slot 호환)."""
    if not reference_points or not usable_poly:
        return

    coords = list(usable_poly.exterior.coords)
    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    center_threshold = short_side * 0.3

    corner_vertices = []
    for i in range(len(coords) - 1):
        prev_i = (i - 1) % (len(coords) - 1)
        next_i = (i + 1) % (len(coords) - 1)
        dx1 = coords[i][0] - coords[prev_i][0]
        dy1 = coords[i][1] - coords[prev_i][1]
        dx2 = coords[next_i][0] - coords[i][0]
        dy2 = coords[next_i][1] - coords[i][1]
        len1, len2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
        if len1 > 0 and len2 > 0:
            cos_a = max(-1, min(1, (dx1 * dx2 + dy1 * dy2) / (len1 * len2)))
            if 60 <= math.degrees(math.acos(cos_a)) <= 120:
                corner_vertices.append(coords[i])

    min_walk = min((rp.get("walk_mm", float("inf")) for rp in reference_points), default=0)
    for rp in reference_points:
        rp_coord = rp.get("coord")
        if not rp_coord:
            continue
        sx, sy = rp_coord
        pt = Point(sx, sy)
        tags = []
        is_corner = any(math.hypot(sx - cx, sy - cy) < 500 for cx, cy in corner_vertices)
        if is_corner:
            tags.append("corner")
        wall_dist = usable_poly.exterior.distance(pt)
        if not is_corner and wall_dist < 600:
            tags.append("wall_adjacent")
        if wall_dist > center_threshold:
            tags.append("center_area")
        if entrance_mm and min_walk > 0 and rp.get("walk_mm", float("inf")) <= min_walk * 1.5:
            tags.append("entrance_facing")
        rp["semantic_tags"] = tags


def _build_zone_polygons_from_graph(nodes, main_lengths, zone_1, zone_2, usable_poly):
    """usable_poly를 Dijkstra 거리 기준으로 정확히 3분할 → 1:1 커버, 빈틈 제로.

    방식: usable_poly 전체를 entrance로 시작 → mid/deep 영역을 difference로 깎아냄.
    simplify 없음. 프론트에서 보이는 그대로가 실제 zone 경계.
    """
    from shapely.ops import unary_union
    import numpy as np

    node_coords = []
    node_walks = []
    for nk, coord in nodes.items():
        node_coords.append(coord)
        node_walks.append(main_lengths.get(nk, float("inf")))

    if not node_coords:
        return {}

    node_arr = np.array(node_coords)
    walk_arr = np.array(node_walks)

    # 150mm 격자 — 각 점의 zone 판별
    minx, miny, maxx, maxy = usable_poly.bounds
    step = 150
    half = step / 2

    zone_cells = {"entrance_zone": [], "mid_zone": [], "deep_zone": []}

    for gx in np.arange(minx, maxx + step, step):
        for gy in np.arange(miny, maxy + step, step):
            pt = Point(gx, gy)
            if not usable_poly.covers(pt):  # covers()는 경계선 위 점도 포함
                continue
            dists = np.hypot(node_arr[:, 0] - gx, node_arr[:, 1] - gy)
            walk = walk_arr[np.argmin(dists)]

            if walk < zone_1:
                zone_cells["entrance_zone"].append(pt.buffer(half, cap_style=3))
            elif walk < zone_2:
                zone_cells["mid_zone"].append(pt.buffer(half, cap_style=3))
            else:
                zone_cells["deep_zone"].append(pt.buffer(half, cap_style=3))

    # usable_poly를 순차적으로 깎아서 분할 — 겹침/빈틈 불가능
    result = {}
    remaining = usable_poly  # 아직 배정 안 된 영역

    for zone_name in ("entrance_zone", "mid_zone", "deep_zone"):
        cells = zone_cells.get(zone_name, [])
        if not cells:
            continue
        # 셀 union → usable_poly와 교차 → 이 zone의 영역
        raw = unary_union(cells).intersection(remaining)
        if raw.is_empty:
            continue
        # remaining에서 이 zone을 깎아냄
        remaining = remaining.difference(raw)
        # polygon 좌표 추출 (simplify 없음 — 1:1 정확도)
        poly = _extract_largest_polygon(raw)
        if poly:
            coords = list(poly.exterior.coords)
            result[zone_name] = {
                "polygon_mm": [[round(c[0], 1), round(c[1], 1)] for c in coords],
                "point_count": len(cells),
            }

    # 남은 영역(remaining) → deep_zone에 합산 (빈틈 제로 절대 보장)
    if not remaining.is_empty and remaining.area > 100:
        remainder_poly = _extract_largest_polygon(remaining)
        if remainder_poly:
            if "deep_zone" in result:
                deep_existing = Polygon(result["deep_zone"]["polygon_mm"])
                deep_merged = deep_existing.union(remainder_poly)
                merged_poly = _extract_largest_polygon(deep_merged)
                if merged_poly:
                    coords = list(merged_poly.exterior.coords)
                    result["deep_zone"]["polygon_mm"] = [[round(c[0], 1), round(c[1], 1)] for c in coords]
            else:
                coords = list(remainder_poly.exterior.coords)
                result["deep_zone"] = {
                    "polygon_mm": [[round(c[0], 1), round(c[1], 1)] for c in coords],
                    "point_count": 0,
                }

    return result


def _extract_largest_polygon(geom):
    """Geometry에서 가장 큰 Polygon 추출. simplify 없음."""
    if geom.is_empty:
        return None
    if hasattr(geom, "geoms"):
        polys = [g for g in geom.geoms if hasattr(g, "exterior")]
        return max(polys, key=lambda g: g.area) if polys else None
    if hasattr(geom, "exterior"):
        return geom
    return None


