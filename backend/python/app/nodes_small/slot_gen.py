"""
Slot 생성 노드 — Rendy 코드 베이스.

외벽 edge slot (perimeter interpolate) + 내부 격자 interior slot.
감압존 900mm (소형 main_artery 900mm 와 폭 동기화), 적응적 step.
"""
import math
import logging

from shapely.geometry import LineString, Point, Polygon

from app.state import SmallState
from app.utils import frange, normal_label, wall_direction_name, point_in_any_obstacle, point_near_any, angle_diff

logger = logging.getLogger(__name__)

# [중요/회귀방지] 2026-04-22 Phase 0: 1500 → 900 (18평 photo_wall drop 3/3 해소).
# 1-3 (#533) 후속 (2026-05-07) 라이브 비교:
#   - 900 (19:45 라이브): photo_wall drop. design 3회 retry 누적 후 fail.
#   - 1200 (19:34 라이브): photo_wall 1개 배치 (단 center_46 standalone fallback).
#   → 1200 이 900 보다 결과 우수. 1200 채택.
#   ※ photo_wall 의 wall_facing 정상 부착은 둘 다 안 됨 — AP-405-b / design retry
#     상호작용 회귀로 본 PR 범위 외 별도 이슈로 분리.
# 면적별 5단 계층 동적화는 Phase 3-C 백로그 (1200/1800/2400 자문 수치).
DECOMPRESSION_RADIUS_MM = 1200  # default fallback (state 없을 때 / 면적 미정)


# 1-3 (#533) 후속: 면적별 감압존 분기 (외부 자문 — 리테일 표준).
#   Small (< 20평): 1200mm (최소 기능형 — 18평 LUMIA baseline)
#   Medium (20~40평): 1800mm (표준 감압형 — 2~3인 동시 머무름 폭)
#   Large-Medium (40~50평): 2400mm (공간 경험형 — 브랜드 톤앤매너 전이 지대)
#   50평 이상: nodes_large 영역 (Shin, 별도 시스템)
_PYEONG_MM2 = 3_305_785  # 1평 ≈ 3.3m² ≈ 3.305M mm² (정확: 1/0.3025)


def compute_decompression_radius_mm(usable_area_mm2: float) -> int:
    """면적별 감압존 반경 반환 (mm).

    Args:
        usable_area_mm2: usable_poly.area (mm²)

    Returns:
        감압존 반경 (mm) — 1200 / 1800 / 2400 중 1
    """
    if usable_area_mm2 < 20 * _PYEONG_MM2:
        return 1200
    if usable_area_mm2 < 40 * _PYEONG_MM2:
        return 1800
    return 2400  # 40~50평. 50평 이상은 nodes_large 분기로 빠짐


def run(state: SmallState) -> SmallState:
    """Edge + Interior slot 생성."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return {"slots": {}}

    # 면적 기반 감압존 반경 결정 — state 에 박아 다른 노드 (ref_point_gen / anti_patterns) 공유
    decomp_radius = compute_decompression_radius_mm(usable_poly.area)

    dead_zones = state.get("dead_zones") or []
    inner_walls = state.get("inner_wall_linestrings") or []
    entrance_mm = state.get("entrance_mm")
    all_entrances = state.get("all_entrances_mm") or []

    # 입구 좌표 수집
    entrance_points = []
    if all_entrances:
        for ent in all_entrances:
            entrance_points.append(Point(ent["coord"][0], ent["coord"][1]))
    elif entrance_mm:
        entrance_points.append(Point(entrance_mm[0], entrance_mm[1]))

    edge_slots = _generate_edge_slots(usable_poly, dead_zones, entrance_points, decomp_radius)
    interior_slots = _generate_interior_slots(usable_poly, dead_zones, inner_walls, entrance_points, decomp_radius)

    slots = {**edge_slots, **interior_slots}
    logger.info(
        f"[slot_gen] {len(edge_slots)} edge + {len(interior_slots)} interior = {len(slots)} total "
        f"(decomp_radius={decomp_radius}mm, area={usable_poly.area/1_000_000:.1f}m²)"
    )

    return {"slots": slots, "decompression_radius_mm": decomp_radius}


def _max_object_width(poly: Polygon) -> float:
    minx, miny, maxx, maxy = poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    return round(short_side * 0.4)


def _generate_edge_slots(usable_poly, dead_zones, entrance_points, decomp_radius=DECOMPRESSION_RADIUS_MM):
    coords = list(usable_poly.exterior.coords)
    slots = {}
    max_w = _max_object_width(usable_poly)
    step_mm = max(500, min(500, int(math.sqrt(max_w**2 + max_w**2) * 0.7)))
    exterior = usable_poly.exterior
    total_len = exterior.length

    slot_idx = 0
    dist_along = step_mm

    while dist_along < total_len - step_mm * 0.5:
        pt_on_wall = exterior.interpolate(dist_along)
        x, y = pt_on_wall.x, pt_on_wall.y

        if point_in_any_obstacle(pt_on_wall, dead_zones):
            dist_along += step_mm
            continue

        if point_near_any(pt_on_wall, entrance_points, decomp_radius):
            dist_along += step_mm
            continue

        seg, seg_dx, seg_dy, seg_len = _find_segment_at(coords, dist_along)

        if seg_len > 0:
            nx_dir = -seg_dy / seg_len
            ny_dir = seg_dx / seg_len
            test_pt = Point(x + nx_dir * 100, y + ny_dir * 100)
            if not usable_poly.contains(test_pt):
                nx_dir, ny_dir = -nx_dir, -ny_dir
            wall_angle = math.degrees(math.atan2(seg_dy, seg_dx))
        else:
            nx_dir, ny_dir = 0.0, 1.0
            wall_angle = 0.0

        wall_name = wall_direction_name(seg_dx, seg_dy)

        actual_step = step_mm
        if slot_idx > 0:
            angle_change = _angle_change_at(coords, dist_along)
            if angle_change > 15:
                factor = min(2.0, 1.0 + angle_change / 90.0)
                actual_step = step_mm * factor

        slot_key = f"{wall_name}_slot_{slot_idx}"
        slots[slot_key] = {
            "x_mm": round(x),
            "y_mm": round(y),
            "wall_linestring": seg if seg else LineString([(x, y), (x + 1, y)]),
            "wall_normal": normal_label(nx_dir, ny_dir),
            "wall_normal_vec": (round(nx_dir, 4), round(ny_dir, 4)),
            "wall_angle_deg": round(wall_angle, 2),
            "zone_label": "entrance_zone",
            "shelf_capacity": max(1, int(total_len / max(1, int(total_len / step_mm)) / 1200)),
            "walk_mm": 0.0,
        }
        slot_idx += 1
        dist_along += actual_step

    return slots


def _generate_interior_slots(usable_poly, dead_zones, inner_walls, entrance_points, decomp_radius=DECOMPRESSION_RADIUS_MM):
    max_w = _max_object_width(usable_poly)
    step_mm = max(500, min(500, int(math.sqrt(max_w**2 + max_w**2) * 0.7)))
    min_wall_dist = 400  # 벽에서 400mm 이상 떨어진 곳에 interior slot 생성

    minx, miny, maxx, maxy = usable_poly.bounds
    slots = {}
    inner_wall_buffers = [w.buffer(150) for w in inner_walls if w.length > 0]

    exterior_coords = list(usable_poly.exterior.coords)
    all_segments = []
    for i in range(len(exterior_coords) - 1):
        seg = LineString([exterior_coords[i], exterior_coords[i + 1]])
        if seg.length > 0:
            all_segments.append(seg)
    all_segments.extend(inner_walls)

    ix = 0
    for gx in frange(minx + step_mm, maxx - step_mm, step_mm):
        for gy in frange(miny + step_mm, maxy - step_mm, step_mm):
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            if usable_poly.exterior.distance(pt) < min_wall_dist:
                continue
            if point_near_any(pt, entrance_points, decomp_radius):
                continue
            if point_in_any_obstacle(pt, dead_zones):
                continue
            if point_in_any_obstacle(pt, inner_wall_buffers):
                continue

            nearest_seg, nx_dir, ny_dir = None, 0.0, 1.0
            nearest_dist = float("inf")
            for seg in all_segments:
                d = seg.distance(pt)
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_seg = seg

            if nearest_seg:
                c0, c1 = nearest_seg.coords[0], nearest_seg.coords[1]
                dx = c1[0] - c0[0]
                dy = c1[1] - c0[1]
                seg_len = math.hypot(dx, dy)
                if seg_len > 0:
                    nx_dir = -dy / seg_len
                    ny_dir = dx / seg_len
                    test = Point(gx + nx_dir * 100, gy + ny_dir * 100)
                    if not usable_poly.contains(test):
                        nx_dir, ny_dir = -nx_dir, -ny_dir

            wall_angle = 0.0
            if nearest_seg:
                c0, c1 = nearest_seg.coords[0], nearest_seg.coords[1]
                wall_angle = math.degrees(math.atan2(c1[1]-c0[1], c1[0]-c0[0]))

            slots[f"interior_slot_{ix}"] = {
                "x_mm": round(gx),
                "y_mm": round(gy),
                "wall_linestring": nearest_seg or LineString([(gx, gy), (gx+1, gy)]),
                "wall_normal": normal_label(nx_dir, ny_dir),
                "wall_normal_vec": (round(nx_dir, 4), round(ny_dir, 4)),
                "wall_angle_deg": round(wall_angle, 2),
                "zone_label": "entrance_zone",
                "shelf_capacity": 1,
                "walk_mm": 0.0,
            }
            ix += 1

    return slots


# ── 이 노드 전용 헬퍼 (다른 노드에서 안 쓰임) ─────────────────────────────

def _find_segment_at(coords, dist_along):
    """경로 위 거리에서 해당 세그먼트와 방향 벡터 반환."""
    cumulative = 0.0
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        seg_len = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        if cumulative + seg_len >= dist_along:
            dx, dy = p2[0]-p1[0], p2[1]-p1[1]
            return LineString([p1, p2]), dx, dy, seg_len
        cumulative += seg_len
    p1, p2 = coords[-2], coords[-1]
    dx, dy = p2[0]-p1[0], p2[1]-p1[1]
    return LineString([p1, p2]), dx, dy, math.hypot(dx, dy)


def _angle_change_at(coords, dist_along):
    """경로 위 거리에서 인접 세그먼트 간 각도 변화량."""
    cumulative = 0.0
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        seg_len = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        if cumulative + seg_len >= dist_along and i > 0:
            prev_p1, prev_p2 = coords[i-1], coords[i]
            prev_angle = math.degrees(math.atan2(prev_p2[1]-prev_p1[1], prev_p2[0]-prev_p1[0]))
            curr_angle = math.degrees(math.atan2(p2[1]-p1[1], p2[0]-p1[0]))
            return angle_diff(curr_angle, prev_angle)
        cumulative += seg_len
    return 0.0
