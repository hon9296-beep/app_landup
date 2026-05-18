"""
방문자 동선 검증 노드 — yeonhwa/agent3/pathing_validator.py 기반.

Dijkstra 최단경로로 입구 → 각 오브젝트 접근 가능 여부 검증.
viewing zone (600~2500mm) 기반 관람 위치 탐색.
"""
import math
import logging

import networkx as nx
from shapely.geometry import Point, box as shapely_box

from app.state import LargeState

logger = logging.getLogger(__name__)

PATH_GRID_STEP_MM = 1000  # 1m 해상도 (yeonhwa 원본)
HUMAN_BUFFER_MM = 600  # 인간 통과 최소 보장 폭의 절반
VIEW_MIN_MM = 600
VIEW_MAX_MM = 2500


def run(state: LargeState) -> LargeState:
    """입구 → 각 오브젝트 Dijkstra 동선 검증."""
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    entrance_mm = state.get("entrance_mm")

    if not placed or not usable_poly or not entrance_mm:
        return {"pathways": [], "trapped_objects": []}

    # 1. 장애물 bbox 생성 (600mm 버퍼)
    obstacle_boxes = []
    for obj in placed:
        cx, cy = obj["center_x_mm"], obj["center_y_mm"]
        w_h = obj.get("width_mm", 600) / 2
        d_h = obj.get("depth_mm", 400) / 2
        obstacle_boxes.append(
            shapely_box(
                cx - w_h - HUMAN_BUFFER_MM,
                cy - d_h - HUMAN_BUFFER_MM,
                cx + w_h + HUMAN_BUFFER_MM,
                cy + d_h + HUMAN_BUFFER_MM,
            )
        )

    # 2. 그리드 그래프 구축
    minx, miny, maxx, maxy = usable_poly.bounds
    G = nx.Graph()
    grid_nodes = []

    for gx in range(int(minx), int(maxx) + PATH_GRID_STEP_MM, PATH_GRID_STEP_MM):
        for gy in range(int(miny), int(maxy) + PATH_GRID_STEP_MM, PATH_GRID_STEP_MM):
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            blocked = any(obs.contains(pt) for obs in obstacle_boxes)
            if blocked:
                continue
            G.add_node((gx, gy))
            grid_nodes.append((gx, gy))

    # 인접 노드 연결 (대각선 포함)
    for i, n1 in enumerate(grid_nodes):
        for n2 in grid_nodes[i + 1:]:
            dist = math.hypot(n1[0] - n2[0], n1[1] - n2[1])
            if dist <= PATH_GRID_STEP_MM * 1.5:
                G.add_edge(n1, n2, weight=dist)

    if not grid_nodes:
        logger.warning("[pathing] 가동 노드 없음 — 공간 부족")
        return {"pathways": [], "trapped_objects": [obj["object_type"] for obj in placed]}

    # 입구 노드
    ex, ey = entrance_mm
    start_node = min(grid_nodes, key=lambda p: math.hypot(ex - p[0], ey - p[1]))

    # 3. 각 오브젝트에 대해 Dijkstra
    pathways = []
    trapped = []

    for obj in placed:
        ox, oy = obj["center_x_mm"], obj["center_y_mm"]

        # viewing zone: 오브젝트에서 600~2500mm 거리의 노드
        candidates = [
            n for n in grid_nodes
            if VIEW_MIN_MM < math.hypot(ox - n[0], oy - n[1]) < VIEW_MAX_MM
        ]
        if not candidates:
            trapped.append(obj["object_type"])
            continue

        target = min(candidates, key=lambda p: math.hypot(ox - p[0], oy - p[1]))

        try:
            path = nx.shortest_path(G, source=start_node, target=target, weight="weight")
            pathways.append({
                "path_id": f"route_to_{obj['object_type']}",
                "object_type": obj["object_type"],
                "nodes": [{"x": p[0], "y": p[1]} for p in path],
                "distance_mm": round(nx.shortest_path_length(G, start_node, target, weight="weight")),
            })
        except nx.NetworkXNoPath:
            trapped.append(obj["object_type"])
            logger.warning(f"[pathing] {obj['object_type']} 접근 불가")

    logger.info(f"[pathing] {len(pathways)} paths, {len(trapped)} trapped")

    return {
        "pathways": pathways,
        "trapped_objects": trapped,
    }
