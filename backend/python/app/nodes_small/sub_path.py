"""
부동선(Sub-path) — 외곽 복귀 루프 계산 노드. (#116, F-8 복원)

주동선(Spine) 종점에서 출발하여 Spine 반대편 외곽을 의무 우회한 뒤 입구로 복귀하는
경로. 배치된 기물이 모두 Spine 근처여도 반드시 생성 (100% 생성 보장).

원본: code_book/rendy/backend/app/api/pipeline.py L289-411 `_build_sub_path()`
포팅: nodes_small/walk_mm 의 `_build_corridor_graph` + `_connect_waypoints` + `_nearest_node` 사용.

알고리즘:
  1. Spine 이 지나지 않는 반대편 외곽에 최소 경유점(Mandatory Waypoints) 산출
  2. 배치된 기물 중 Spine 에서 먼 것을 추가 경유점으로 병합
  3. Spine 종점 → 외곽/기물 경유점 → 입구, nearest-neighbor 순회
  4. 각 구간을 Dijkstra (corridor_graph) 로 연결 (오브젝트 footprint 회피)

배치 결과 UX 가시성 — 프론트가 sub_path 좌표를 받아 시각화.

호출: place_service.py 가 placement 완료 후 호출 (가벽 전처리 + 일반 배치 + fallback 후).
"""
from __future__ import annotations

import logging
from typing import Optional

from shapely.geometry import LineString, Point, Polygon

from app.state import SmallState

logger = logging.getLogger(__name__)


def run(state: SmallState) -> SmallState:
    """배치 결과 기반 부동선 좌표 계산. state["sub_path"] 에 list[list[float]] 저장.

    실패 / 입력 부재 시 빈 list 반환 (graceful — placement 결과 영향 X).
    """
    main_artery = state.get("main_artery")
    placed_objects = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    dead_zones = list(state.get("dead_zones") or [])
    entrance_mm = state.get("entrance_mm")
    all_entrances = state.get("all_entrances_mm") or []

    if not main_artery or not usable_poly:
        logger.info("[sub_path] main_artery 또는 usable_poly 부재 → sub_path 미생성")
        return {"sub_path": []}

    coords = _build_sub_path(
        usable_poly=usable_poly,
        main_artery=main_artery,
        placed_objects=placed_objects,
        dead_zones=dead_zones,
        entrance_mm=entrance_mm,
        all_entrances=all_entrances,
    )

    return {"sub_path": coords}


def _build_sub_path(
    usable_poly: Polygon,
    main_artery: LineString,
    placed_objects: list[dict],
    dead_zones: list,
    entrance_mm: Optional[tuple],
    all_entrances: list,
) -> list[list[float]]:
    """부동선 좌표 산출 (Rendy 원본 포팅).

    return: [[x, y], [x, y], ...] mm 단위 좌표 list. 실패 시 [].
    """
    spine_coords = list(main_artery.coords)
    if len(spine_coords) < 2:
        logger.info("[sub_path] main_artery 좌표 부족 (<2) → 미생성")
        return []

    spine_start = spine_coords[0]
    spine_end = spine_coords[-1]
    minx, miny, maxx, maxy = usable_poly.bounds
    cx_floor = (minx + maxx) / 2
    cy_floor = (miny + maxy) / 2

    # ── 1) 배치된 기물 중 Spine 에서 먼 것을 경유점으로 수집 ──
    far_object_coords: list[tuple[float, float]] = []
    far_object_types: list[str] = []
    for obj in placed_objects:
        ox = obj.get("center_x_mm", 0)
        oy = obj.get("center_y_mm", 0)
        dist = main_artery.distance(Point(ox, oy))
        if dist > 2000:  # adjacent (2m) 밖
            far_object_coords.append((ox, oy))
            far_object_types.append(obj.get("object_type", ""))

    # ── 2) Fallback: 기물이 모두 Spine 근처면 반대편 외곽 의무 경유 ──
    spine_avg_x = sum(c[0] for c in spine_coords) / len(spine_coords)
    spine_on_left = spine_avg_x < cx_floor
    margin = min(maxx - minx, maxy - miny) * 0.1

    if not far_object_coords:
        if spine_on_left:
            far_x = maxx - margin
            fallback_pts = [(far_x, maxy - margin), (far_x, cy_floor), (far_x, miny + margin)]
            side = "우측(fallback)"
        else:
            far_x = minx + margin
            fallback_pts = [(far_x, maxy - margin), (far_x, cy_floor), (far_x, miny + margin)]
            side = "좌측(fallback)"
        merged: list[tuple[float, float]] = [
            (x, y) for x, y in fallback_pts if usable_poly.contains(Point(x, y))
        ]
        if not merged:
            merged = [fallback_pts[1]]  # 최소 중앙 1점 fallback
    else:
        # 기물 기반 경유점 — 2m 이내 중복 제거
        merged = []
        for wp in far_object_coords:
            too_close = any(Point(wp).distance(Point(e)) < 2000 for e in merged)
            if not too_close:
                merged.append(wp)
        side = f"기물 {len(merged)}개"

    # ── 3) nearest-neighbor 순회: Spine 종점 → 경유점 → Spine 시작점 (입구) ──
    ordered: list[tuple[float, float]] = []
    remaining = list(merged)
    current = spine_end
    while remaining:
        nearest_wp = min(remaining, key=lambda v: Point(current).distance(Point(v)))
        ordered.append(nearest_wp)
        current = nearest_wp
        remaining.remove(nearest_wp)

    waypoints = [spine_end] + ordered + [spine_start]

    # ── 4) 오브젝트 footprint 장애물 추가 → corridor_graph → Dijkstra ──
    obstacles = list(dead_zones)
    for obj in placed_objects:
        bx = obj.get("bbox_bounds")
        if isinstance(bx, (list, tuple)) and len(bx) == 4:
            obj_poly = Polygon([
                (bx[0], bx[1]), (bx[2], bx[1]),
                (bx[2], bx[3]), (bx[0], bx[3]),
            ])
            if obj_poly.is_valid and obj_poly.area > 0:
                obstacles.append(obj_poly.buffer(300))

    # nodes_small 의 walk_mm._build_corridor_graph + _connect_waypoints 재사용
    from app.nodes_small.walk_mm import _build_corridor_graph, _connect_waypoints
    G, nodes = _build_corridor_graph(usable_poly, dead_zones=obstacles)

    # 입구 좌표 — corridor graph 실패 시 perimeter fallback 에서도 사용.
    entrance_pts: list[tuple[float, float]] = []
    for ent in (all_entrances or []):
        coord = ent.get("coord") if isinstance(ent, dict) else None
        if coord and len(coord) >= 2:
            entrance_pts.append((coord[0], coord[1]))
    if not entrance_pts and entrance_mm:
        entrance_pts = [(entrance_mm[0], entrance_mm[1])]

    if not nodes:
        # #494: corridor graph 노드 0 — placed_objects 가 매장 도배해 통로 형성 불가.
        # 이전에는 빈 list 반환 → 부동선 미생성. 시각화 목적이라 외곽 좌표만 잇는 단순
        # perimeter 경로라도 반환하는 게 정상. obstacle 회피는 포기 (corridor 가 이미 실패).
        logger.warning(
            "[sub_path] corridor graph 노드 0 — perimeter fallback 활성화 "
            "(placed=%d, obstacles=%d, usable_area=%.1fm²)",
            len(placed_objects), len(obstacles), usable_poly.area / 1_000_000,
        )
        return _build_perimeter_fallback(
            usable_poly=usable_poly,
            spine_end=spine_end,
            spine_start=spine_start,
            entrance_pts=entrance_pts,
        )

    all_coords = _connect_waypoints(waypoints, G, nodes)

    # ── 5) 시작/끝점을 실제 입구 좌표로 치환 (그리드 스냅 오차 제거) ──
    if all_coords and entrance_pts:
        # 끝점 = MAIN 입구 (첫 번째)
        all_coords[-1] = entrance_pts[0]
        # 시작점 = 2번째 입구 있으면 그걸로 (비상구 등) / 없으면 spine_end 유지
        if len(entrance_pts) >= 2:
            all_coords[0] = entrance_pts[-1]
        else:
            all_coords[0] = spine_end

    result = [[round(x, 1), round(y, 1)] for x, y in all_coords]
    logger.info(
        f"[sub_path] {side}, far_objects={len(far_object_coords)}, "
        f"merged={len(merged)}, {len(result)} grid nodes"
    )
    if far_object_types:
        logger.info(f"[sub_path] 경유 기물: {far_object_types}")
    return result


def _build_perimeter_fallback(
    usable_poly: Polygon,
    spine_end: tuple,
    spine_start: tuple,
    entrance_pts: list[tuple[float, float]],
) -> list[list[float]]:
    """corridor graph 형성 실패 (placed_objects 가 매장 도배) 시 단순 외곽 경로 fallback.

    Spine 반대편 외곽 좌표를 따라 spine_end → 반대편 상단 → 반대편 하단 → 입구 로 잇는
    4-점 LineString. Dijkstra 미사용 (corridor graph 가 이미 실패) — obstacle 회피는 포기.
    시각화 목적상 부동선이 '있다는 것' 자체를 보장.

    매장 외부로 벗어나는 점은 nearest_points 로 매장 안쪽으로 끌어당김.
    """
    from shapely.ops import nearest_points

    minx, miny, maxx, maxy = usable_poly.bounds
    cx_floor = (minx + maxx) / 2
    margin = min(maxx - minx, maxy - miny) * 0.1

    # spine 이 매장 좌/우 어느 쪽에 있는지 → 반대편 외곽 X 좌표 결정
    spine_avg_x = (spine_start[0] + spine_end[0]) / 2
    spine_on_left = spine_avg_x < cx_floor
    far_x = (maxx - margin) if spine_on_left else (minx + margin)

    # 입구 좌표 (entrance_pts 비어 있으면 spine_start 로 fallback)
    end_pt = entrance_pts[0] if entrance_pts else spine_start

    # 4-점 외곽 우회 경로
    raw_waypoints = [
        spine_end,
        (far_x, maxy - margin),
        (far_x, miny + margin),
        end_pt,
    ]

    # 매장 외부로 벗어난 점은 매장 안쪽으로 snap
    safe_coords = []
    for wx, wy in raw_waypoints:
        pt = Point(wx, wy)
        if usable_poly.contains(pt):
            safe_coords.append((wx, wy))
        else:
            inside, _ = nearest_points(usable_poly, pt)
            safe_coords.append((inside.x, inside.y))

    result = [[round(x, 1), round(y, 1)] for x, y in safe_coords]
    logger.info(
        f"[sub_path] perimeter fallback {len(result)} 점 — "
        f"side={'좌측' if spine_on_left else '우측'} 반대편 외곽 우회"
    )
    return result
