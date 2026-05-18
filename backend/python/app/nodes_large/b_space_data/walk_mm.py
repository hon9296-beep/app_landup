"""
Walk_mm 계산 노드 — Rendy 코드 베이스 + landup_shin/networkx_engine 강화.

NetworkX Dijkstra 보행 거리 + zone 배정 + Main Artery 생성 + semantic tag.
강화: multi-entrance Dijkstra (모든 입구에서 최소 거리 채택).
"""
import math
import logging

import networkx as nx
from shapely.geometry import LineString, Point, Polygon

from app.state import LargeState
from app.utils import frange

logger = logging.getLogger(__name__)

WALK_GRID_STEP_MM = 500


def run(state: LargeState) -> LargeState:
    """Walk_mm + zone_label + Main Artery + virtual entrance."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return {}

    dead_zones = state.get("dead_zones") or []
    slots = state.get("slots") or {}
    entrance_mm = state.get("entrance_mm")
    all_entrances = state.get("all_entrances_mm") or []
    entrance_width = state.get("entrance_width_mm") or 1200
    # 2026-05-04: 배치된 가구도 obstacle 로 처리 (walk_mm 이 placement 다음으로 이동됨).
    # placed_raw 에 bbox_polygon Shapely 객체 박혀있음 (placement.py 결과).
    # b_space_data sub-graph 진입 시점 (사이클 시작 전) = placed_raw 비어있음 → 영향 X.
    placed_polygons = state.get("placed_raw") or []

    if not entrance_mm:
        return {}

    # Corridor graph 구축 — 배치된 가구도 obstacle (가구 사이 통로 따라 동선 그리기).
    G, nodes = _build_corridor_graph(usable_poly, dead_zones, placed_polygons)
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

    # 입구 거리 기준값
    minx, miny, maxx, maxy = usable_poly.bounds
    max_walk = max(maxx - minx, maxy - miny)

    # MAIN_DOOR 기준 Dijkstra
    main_idx = 0
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR":
            main_idx = i
            break
    main_lengths = all_lengths[main_idx] if main_idx < len(all_lengths) else {}

    # Slot walk_mm 부여 (zone_label은 concept_area에서 할당)
    for slot in slots.values():
        slot_node = _nearest_node(nodes, (slot["x_mm"], slot["y_mm"]))
        min_walk = min((l.get(slot_node, float("inf")) for l in all_lengths), default=max_walk * 2)
        if min_walk == float("inf"):
            min_walk = max_walk * 2
        slot["walk_mm"] = round(min_walk)

    # Reference points walk_mm 부여 (zone_label은 concept_area에서 할당)
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

    # Semantic tags — slot + ref_point 둘 다
    _assign_semantic_tags(slots, usable_poly, entrance_mm)
    _assign_semantic_tags_rp(reference_points, usable_poly, entrance_mm)

    # Main Artery
    # 2026-05-04: placed_polygons 전달 — _build_loop_spine 이 가구 영역 빼고 동선 그림.
    main_artery = _compute_main_artery(G, nodes, entrance_coords, entrance_types, usable_poly, placed_polygons)

    # Virtual entrance
    entrance_line, entrance_buffer = _build_virtual_entrance(entrance_mm, usable_poly, entrance_width)

    # Spine rank 부여 (주동선으로부터의 거리)
    _assign_spine_rank(slots, main_artery)
    _assign_spine_rank_to_ref_points(reference_points, main_artery)

    logger.info(f"[walk_mm] artery={main_artery.length:.0f}mm" if main_artery else "[walk_mm] no artery")

    return {
        "slots": slots,
        "reference_points": reference_points,
        "main_artery": main_artery,
        "entrance_line": entrance_line,
        "entrance_buffer": entrance_buffer,
    }


# ── Corridor Graph ────────────────────────────────────────────────────────

def _build_corridor_graph(usable_poly, dead_zones=None, placed_polygons=None, step_mm=WALK_GRID_STEP_MM):
    """corridor 그래프 생성 — main_artery 계산 기반.

    2026-05-04: placed_polygons 파라미터 추가.
    walk_mm 이 placement 다음으로 이동되며 배치된 가구도 obstacle 로 인식해야 동선이 가구 피해서 그려짐.
    각 placed bbox + buffer (양측 450mm = 폭 900mm 통로 확보, MIN_FURNITURE_GAP_MM 정합) 를 그래프 노드 차단 영역으로 처리.

    placed_polygons=None / 빈 list 면 기본 동작 (dead_zones 만) — placement 단계 _init_corridor_graph 호출 호환.
    """
    minx, miny, maxx, maxy = usable_poly.bounds
    obstacles = list(dead_zones or [])

    # 2026-05-04 신설: 배치된 가구 bbox + 통로 buffer 도 obstacle 처리.
    # bbox.buffer(450) = 양측 450mm 확장 = 가구 사이 통로 폭 900mm 확보.
    # 이 영역을 그래프 노드 X 처리하면 main_artery 가 가구 사이 통로 따라 그려짐.
    if placed_polygons:
        FURNITURE_BUFFER_MM = 450  # 양측 buffer (합 = 900mm 통로). MIN_FURNITURE_GAP_MM 정합.
        for p in placed_polygons:
            bbox = p.get("bbox_polygon") if isinstance(p, dict) else None
            if bbox is not None and not bbox.is_empty:
                obstacles.append(bbox.buffer(FURNITURE_BUFFER_MM))

    G = nx.Graph()
    nodes = {}
    xs = frange(minx, maxx, step_mm)
    ys = frange(miny, maxy, step_mm)
    for gx in xs:
        for gy in ys:
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            if any(dz.contains(pt) for dz in obstacles if hasattr(dz, "contains")):
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

def _compute_main_artery(G, nodes, entrance_coords, entrance_types, usable_poly, placed_polygons=None):
    """주동선 계산.

    2026-05-04: 사용자 의도 = 순환 동선 우선 (매장 중앙 도는 루프).
    같은 날 placed_polygons 인자 추가 — _build_loop_spine 이 가구 영역 피해서 동선 그리도록.

    비상구 (EMERGENCY_EXIT) 가 별도면 일자 through spine 사용 (입구 ≠ 출구 흐름).
    비상구 X 또는 입구 = 출구면 순환 동선 우선.
    """
    main_idx, emergency_idx = None, None
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR" and main_idx is None:
            main_idx = i
        if t == "EMERGENCY_EXIT" and emergency_idx is None:
            emergency_idx = i
    if main_idx is None:
        main_idx = 0
    entrance = entrance_coords[main_idx]

    # 비상구 별도면 일자 through spine (입구 → 깊은 곳 → 비상구)
    if emergency_idx is not None and emergency_idx != main_idx:
        exit_coord = entrance_coords[emergency_idx]
        spine = _build_through_spine(entrance, exit_coord, usable_poly, G, nodes)
        if spine:
            return spine

    # 비상구 X 또는 입구 = 출구 → 순환 동선 우선 (`_build_loop_spine`).
    # placed_polygons 도 같이 전달 — 가구 사이 통로 따라 동선 그리기 위함.
    return _build_loop_spine(entrance, usable_poly, G, nodes, placed_polygons=placed_polygons)


def _build_main_spine(entrance, usable_poly, G, nodes):
    """일자 spine — 입구에서 가장 깊은 벽 중앙까지 직각 경로 (fallback 용).

    2026-05-04: 사용자 의도 = 순환 동선 우선. 일자는 fallback (좁은 영역, 순환 불가 시).
    1차 시도 = `_build_loop_spine` (순환). 실패 시 본 함수 호출.
    """
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


def _build_loop_spine(entrance, usable_poly, G, nodes, placed_polygons=None, wall_offset_mm: float = 1500):
    """순환 동선 — 공간 중앙 polygon 의 외곽선 따라가는 루프 (입구 → 한 바퀴 → 입구).

    2026-05-04 신설 + 같은 날 placed_polygons 입력 추가 — 가구 사이 통로 따라 그리도록.

    fallback 케이스 (사용자 결정):
    - 케이스 1 (좁은 영역, buffer 결과 빈 polygon) → 일자 spine 으로 fallback
    - 케이스 2 (MultiPolygon 분리) → 가장 큰 polygon 만 사용 (사용자: "옵션 b")
    - 케이스 3 (좁은 가지 사라짐) → 넓은 부분만 순환, 좁은 곳은 일자 fallback (사용자 명시)

    알고리즘:
    1. usable_poly.buffer(-wall_offset_mm) = 외벽에서 wall_offset_mm 안쪽으로 들여박은 polygon
    2. **각 placed bbox + buffer (양측 450mm) 영역 빼기 (difference)** = 가구 사이 통로만 남음
    3. 빈 polygon 또는 MultiPolygon 처리
    4. 안쪽 polygon 외곽선 (loop_line) = 순환 동선 라인
    5. 입구 좌표에서 가장 가까운 loop_line 점 = 시작/끝점
    6. 시계방향으로 한 바퀴 → 시작점 = 입구 가까운 점
    """
    from shapely.geometry import MultiPolygon as ShpMulti

    minx, miny, maxx, maxy = usable_poly.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    # 케이스 1 처리 — buffer 너무 크면 빈 polygon. 일자 fallback.
    inner = usable_poly.buffer(-wall_offset_mm)
    if inner.is_empty or inner.area < 1_000_000:  # 1m² 미만이면 의미 없음
        logger.info(f"[walk_mm] loop spine fallback (좁은 공간, buffer={wall_offset_mm}mm 결과 면적 부족)")
        return _build_main_spine(entrance, usable_poly, G, nodes)

    # 2026-05-04: 배치된 가구 영역 빼기 — 가구 사이 통로 따라 동선 그려지게.
    # bbox.buffer(450) = 양측 통로 buffer. 동선이 가구에서 450mm 떨어진 영역 따라감.
    if placed_polygons:
        FURNITURE_BUFFER_MM = 450
        for p in placed_polygons:
            bbox = p.get("bbox_polygon") if isinstance(p, dict) else None
            if bbox is not None and not bbox.is_empty:
                inner = inner.difference(bbox.buffer(FURNITURE_BUFFER_MM))
        if inner.is_empty or inner.area < 1_000_000:
            logger.info("[walk_mm] loop spine fallback (가구 영역 빼니 면적 부족)")
            return _build_main_spine(entrance, usable_poly, G, nodes)

    # 2026-05-06: 좁은 통로 (700mm 이하 폭) 회피 — closing operation.
    # buffer(-350) 으로 좁은 corridor 사라지고 buffer(+350) 으로 안 돌아옴 (= 좁은 부분 제거).
    # 가구 buffer (450mm) 그대로 — 동선 위해 오브젝트 변경 X (사용자 결정 2026-05-06).
    # 좁으면 동선 안 만들어짐 (작은 부지/빽빽 케이스 = fallback 발동, 정상).
    NARROW_CORRIDOR_R = 350  # 통로 폭 700mm 회피 (반지름 r 의 2배가 통로 폭).
    inner = inner.buffer(-NARROW_CORRIDOR_R).buffer(NARROW_CORRIDOR_R)
    if inner.is_empty or inner.area < 1_000_000:
        logger.info(f"[walk_mm] loop spine fallback (좁은 통로 제거 후 면적 부족, r={NARROW_CORRIDOR_R}mm)")
        return _build_main_spine(entrance, usable_poly, G, nodes)

    # 케이스 2 처리 — MultiPolygon 분리. 가장 큰 polygon 만 사용.
    if isinstance(inner, ShpMulti):
        inner = max(inner.geoms, key=lambda p: p.area)
        logger.info(f"[walk_mm] loop spine MultiPolygon 분리 — 가장 큰 polygon (면적 {inner.area:.0f}mm²) 만 사용")
        # 케이스 3 — 좁은 가지 사라진 경우 자동으로 큰 부분만 남음

    # 안쪽 polygon 외곽선 = 순환 동선 라인
    loop_line = inner.exterior

    # 입구 좌표에서 loop_line 가장 가까운 점 = 시작점
    entrance_pt = Point(entrance)
    start_dist = loop_line.project(entrance_pt)  # loop_line 시작점에서의 거리

    # 시계방향 한 바퀴 좌표 추출 (start_dist → loop_line.length → 다시 start_dist).
    # interpolate 로 입구 가까운 점부터 도는 좌표 생성. 1m 마다 한 점.
    samples = []
    n_samples = max(8, int(loop_line.length / 1000))  # 1m 마다 한 점, 최소 8 점
    for i in range(n_samples + 1):
        d = (start_dist + loop_line.length * i / n_samples) % loop_line.length
        pt = loop_line.interpolate(d)
        samples.append((pt.x, pt.y))

    # 입구 위치 → loop_line 시작점 까지 잇는 진입 라인 추가 (입구가 외곽 안쪽이라 짧은 직선)
    entry_to_loop = [entrance, samples[0]]

    # 전체 동선 = 진입 + 루프 + 진입 (입구 → 시작 → 한 바퀴 → 시작 → 입구)
    full_coords = entry_to_loop + samples + [entry_to_loop[0]]

    # 중복 점 제거
    deduped = [full_coords[0]]
    for c in full_coords[1:]:
        if math.hypot(c[0] - deduped[-1][0], c[1] - deduped[-1][1]) > 50:  # 50mm 이상 떨어진 점만
            deduped.append(c)

    if len(deduped) >= 3:
        return LineString(deduped)

    # 안전망 — 순환 좌표 부족하면 일자 fallback
    logger.info(f"[walk_mm] loop spine 좌표 부족 ({len(deduped)} 점) — 일자 fallback")
    return _build_main_spine(entrance, usable_poly, G, nodes)


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


