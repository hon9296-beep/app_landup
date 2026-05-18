"""
Reference Point 생성 노드 — Shin 방식.

벽 세그먼트별 기준점 + 의미 라벨 + interior grid 포인트.
walk_mm에서 zone_label을 입힌 뒤, design/placement가 소비.

벽 분할 전략:
  1. usable_poly 외벽 → 코너마다 세그먼트 분리
  2. 짧은 세그먼트 병합 (MIN_WALL_LEN 미만)
  3. 긴 세그먼트 분할 (SPLIT_THRESHOLD 초과 시 2~3등분)
  4. inner_wall도 동일하게 처리
  5. 각 세그먼트 대표점(중점 + 삼등분점) → reference_point
  6. 입구와의 관계로 의미 라벨 부여
  7. interior grid → 벽 근처 + 중앙 자유 공간 포인트 (slot_gen 흡수)
"""
import math
import logging

from shapely.geometry import LineString, Point

from app.state import SmallState
from app.utils import normal_label, frange, point_in_any_obstacle, point_near_any

logger = logging.getLogger(__name__)

# 벽 세그먼트 최소 길이 (mm) — 이보다 짧으면 이전 세그먼트에 병합
MIN_WALL_LEN = 600

# 분할 기준 (mm) — 이보다 길면 등분 (2026-04-20: 3000 → 2000, ref_point 밀도 상향)
SPLIT_THRESHOLD = 2000

# 대표점 생성 기준: 세그먼트 길이가 이 이상이면 삼등분점도 추가 (2026-04-20: 2000 → 1500)
THIRDS_THRESHOLD = 1500

# 입구 근접 판정 거리 (mm)
ENTRANCE_NEAR_MM = 3000


def run(state: SmallState) -> SmallState:
    """벽 기준점 + 의미 라벨 생성."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return {"reference_points": []}

    entrance_mm = state.get("entrance_mm")
    inner_walls = state.get("inner_wall_linestrings") or []
    dead_zones = state.get("dead_zones") or []

    # 1. 외벽 세그먼트 추출
    exterior_segments = _extract_exterior_segments(usable_poly)

    # 2. 짧은 세그먼트 병합
    merged = _merge_short_segments(exterior_segments)

    # 3. 긴 세그먼트 분할
    split = []
    for seg in merged:
        split.extend(_split_long_segment(seg))

    # 4. inner wall도 동일 처리
    inner_segments = []
    for iw in inner_walls:
        if iw.length >= MIN_WALL_LEN:
            inner_segments.extend(_split_long_segment(iw))

    # 5. 대표점 생성
    entrance_pt = Point(entrance_mm) if entrance_mm else None
    deepest_dist = _find_deepest_distance(split, entrance_pt) if entrance_pt else 0

    reference_points = []
    idx = 0

    for seg in split:
        points = _segment_to_ref_points(seg, idx, "exterior", usable_poly, entrance_pt, deepest_dist)
        reference_points.extend(points)
        idx += len(points)

    for seg in inner_segments:
        points = _segment_to_ref_points(seg, idx, "inner", usable_poly, entrance_pt, deepest_dist)
        reference_points.extend(points)
        idx += len(points)

    # 6. 중앙 자유 공간 ref_point 생성
    center_points = _generate_center_ref_points(usable_poly, dead_zones, entrance_pt, deepest_dist, idx)
    reference_points.extend(center_points)
    idx += len(center_points)

    # 7. Interior grid ref_point 생성 (slot_gen 흡수)
    all_entrances = state.get("all_entrances_mm") or []
    entrance_points_shapely = []
    if all_entrances:
        for ent in all_entrances:
            entrance_points_shapely.append(Point(ent["coord"][0], ent["coord"][1]))
    elif entrance_mm:
        entrance_points_shapely.append(Point(entrance_mm[0], entrance_mm[1]))

    # 1-3 (#533) C3: 면적별 감압존 분기 — slot_gen 이 박은 state 값 우선, 없으면 기본값.
    decomp_radius = state.get("decompression_radius_mm", DECOMPRESSION_RADIUS_MM)
    interior_points = _generate_interior_ref_points(
        usable_poly, dead_zones, inner_walls,
        entrance_points_shapely, entrance_pt, deepest_dist, idx,
        decomp_radius=decomp_radius,
    )
    reference_points.extend(interior_points)

    wall_count = idx - len(center_points) - len(interior_points)
    logger.info(
        "[ref_point_gen] %d exterior segs, %d inner segs, %d wall points, %d center points, %d interior points → %d total",
        len(split), len(inner_segments), wall_count, len(center_points), len(interior_points), len(reference_points),
    )

    # entrance_side 태깅 (입구에서 안으로 들어갈 때 기준 right/left/center)
    if entrance_mm and usable_poly:
        v_right = _compute_v_right(entrance_mm, usable_poly)
        _tag_entrance_side(reference_points, entrance_mm, v_right)
    else:
        for rp in reference_points:
            rp["entrance_side"] = None

    return {"reference_points": reference_points}


# ── 외벽 세그먼트 추출 ──────────────────────────────────────────────────────

def _extract_exterior_segments(usable_poly) -> list[LineString]:
    """외벽 좌표 → 꼭짓점마다 LineString 세그먼트 리스트."""
    coords = list(usable_poly.exterior.coords)
    segments = []
    for i in range(len(coords) - 1):
        seg = LineString([coords[i], coords[i + 1]])
        if seg.length > 0:
            segments.append(seg)
    return segments


# ── 병합 / 분할 ────────────────────────────────────────────────────────────

def _merge_short_segments(segments: list[LineString]) -> list[LineString]:
    """MIN_WALL_LEN 미만 세그먼트를 이전 세그먼트에 병합."""
    if not segments:
        return []

    merged = [segments[0]]
    for seg in segments[1:]:
        if seg.length < MIN_WALL_LEN:
            # 이전 세그먼트 끝 + 현재 세그먼트 끝 이어붙이기
            prev_coords = list(merged[-1].coords)
            new_end = seg.coords[-1]
            prev_coords.append(new_end)
            merged[-1] = LineString(prev_coords)
        else:
            merged.append(seg)

    # 첫 번째가 짧을 수 있으므로 다시 체크
    if len(merged) > 1 and merged[0].length < MIN_WALL_LEN:
        first_coords = list(merged[0].coords)
        second_coords = list(merged[1].coords)
        merged[1] = LineString(first_coords + second_coords[1:])
        merged.pop(0)

    return merged


def _split_long_segment(seg: LineString) -> list[LineString]:
    """SPLIT_THRESHOLD 초과 세그먼트를 2~3등분."""
    length = seg.length
    if length <= SPLIT_THRESHOLD:
        return [seg]

    n_parts = 2 if length <= SPLIT_THRESHOLD * 2 else 3
    result = []
    for i in range(n_parts):
        start_frac = i / n_parts
        end_frac = (i + 1) / n_parts
        p_start = seg.interpolate(start_frac, normalized=True)
        p_end = seg.interpolate(end_frac, normalized=True)
        result.append(LineString([(p_start.x, p_start.y), (p_end.x, p_end.y)]))
    return result


# ── 대표점 생성 + 라벨 ─────────────────────────────────────────────────────

def _segment_to_ref_points(
    seg: LineString,
    start_idx: int,
    wall_type: str,
    usable_poly,
    entrance_pt,
    deepest_dist: float,
) -> list[dict]:
    """세그먼트 → reference_point 딕셔너리 리스트."""
    length = seg.length
    if length < 1:
        return []

    # 법선 벡터 계산 (usable_poly 내부 방향)
    nx, ny = _inward_normal(seg, usable_poly)
    wall_angle = math.degrees(math.atan2(
        seg.coords[-1][1] - seg.coords[0][1],
        seg.coords[-1][0] - seg.coords[0][0],
    ))

    # 대표점 위치: 중점 항상 + 긴 벽이면 삼등분점 추가
    fractions = [0.5]
    if length >= THIRDS_THRESHOLD:
        fractions = [0.25, 0.5, 0.75]

    points = []
    for i, frac in enumerate(fractions):
        pt = seg.interpolate(frac, normalized=True)
        coord = (round(pt.x, 1), round(pt.y, 1))

        # 위치 접미사
        if len(fractions) == 1:
            suffix = "mid"
        else:
            suffix = ["left", "mid", "right"][i]

        point_id = f"{'wall' if wall_type == 'exterior' else 'iwall'}_{start_idx + i}_{suffix}"

        # 의미 라벨
        label = _assign_label(coord, wall_type, entrance_pt, deepest_dist, length)

        points.append({
            "id": point_id,
            "coord": coord,
            "wall_segment": seg,
            "wall_normal_vec": (round(nx, 4), round(ny, 4)),
            "wall_normal": normal_label(nx, ny),
            "wall_angle_deg": round(wall_angle, 2),
            "wall_length_mm": round(length),
            "label": label,
            "zone_label": None,  # walk_mm에서 채움
        })

    return points


def _inward_normal(seg: LineString, usable_poly) -> tuple[float, float]:
    """세그먼트의 usable_poly 내부 방향 법선 벡터."""
    dx = seg.coords[-1][0] - seg.coords[0][0]
    dy = seg.coords[-1][1] - seg.coords[0][1]
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 1.0)

    # 후보 법선 2개
    nx1, ny1 = -dy / length, dx / length
    nx2, ny2 = dy / length, -dx / length

    mid = seg.interpolate(0.5, normalized=True)
    test1 = Point(mid.x + nx1 * 100, mid.y + ny1 * 100)
    test2 = Point(mid.x + nx2 * 100, mid.y + ny2 * 100)

    if usable_poly.contains(test1):
        return (nx1, ny1)
    if usable_poly.contains(test2):
        return (nx2, ny2)
    return (nx1, ny1)


def _find_deepest_distance(segments: list[LineString], entrance_pt: Point) -> float:
    """모든 세그먼트 중점 중 입구에서 가장 먼 거리."""
    max_dist = 0
    for seg in segments:
        mid = seg.interpolate(0.5, normalized=True)
        d = entrance_pt.distance(mid)
        if d > max_dist:
            max_dist = d
    return max_dist


def _assign_label(
    coord: tuple,
    wall_type: str,
    entrance_pt,
    deepest_dist: float,
    wall_length: float,
) -> str:
    """reference_point 의미 라벨 결정."""
    if wall_type == "inner":
        return "inner_wall"

    if not entrance_pt or deepest_dist == 0:
        return "side_wall"

    dist = entrance_pt.distance(Point(coord))
    ratio = dist / deepest_dist  # 0=입구, 1=가장 깊은 곳

    if ratio < 0.25:
        return "entrance_adjacent"
    if ratio > 0.75:
        return "deep_wall"
    return "side_wall"


# ── 중앙 자유 공간 ref_point 생성 ──────────────────────────────────────

# 벽에서 이 거리 이상 떨어진 곳만 중앙으로 인정
CENTER_MIN_WALL_DIST = 1200

def _generate_center_ref_points(
    usable_poly,
    dead_zones: list,
    entrance_pt,
    deepest_dist: float,
    start_idx: int,
) -> list[dict]:
    """공간 중앙부에 freestanding/island 배치용 ref_point 생성.

    전략: usable_poly를 격자 샘플링 → 벽에서 충분히 먼 점 → dead_zone 아닌 점 선별.
    """
    if not usable_poly:
        return []

    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    step = max(1500, short_side * 0.2)  # 짧은 변의 20% 또는 최소 1500mm 간격

    candidates = []
    from app.utils import frange
    for gx in frange(minx + step, maxx - step, step):
        for gy in frange(miny + step, maxy - step, step):
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            # 외벽에서 충분히 먼지
            wall_dist = usable_poly.exterior.distance(pt)
            if wall_dist < CENTER_MIN_WALL_DIST:
                continue
            # dead_zone 안에 있으면 제외
            in_dead = any(dz.contains(pt) for dz in dead_zones if hasattr(dz, "contains"))
            if in_dead:
                continue
            candidates.append((gx, gy, wall_dist))

    if not candidates:
        # 후보가 없으면 중심점 하나라도
        cx, cy = usable_poly.centroid.x, usable_poly.centroid.y
        if usable_poly.contains(Point(cx, cy)):
            candidates.append((cx, cy, usable_poly.exterior.distance(Point(cx, cy))))

    # 입구 거리 기준 정렬 (가까운 것부터)
    if entrance_pt:
        candidates.sort(key=lambda c: entrance_pt.distance(Point(c[0], c[1])))

    points = []
    for i, (gx, gy, wall_dist) in enumerate(candidates):
        coord = (round(gx, 1), round(gy, 1))

        # 입구 거리 비율로 라벨 결정
        if entrance_pt and deepest_dist > 0:
            ratio = entrance_pt.distance(Point(coord)) / deepest_dist
            if ratio < 0.4:
                label = "center_entrance_area"
            elif ratio > 0.7:
                label = "center_deep_area"
            else:
                label = "center_freestanding"
        else:
            label = "center_freestanding"

        points.append({
            "id": f"center_{start_idx + i}",
            "coord": coord,
            "wall_segment": None,
            "wall_normal_vec": (0.0, 0.0),
            "wall_normal": "none",
            "wall_angle_deg": 0.0,
            "wall_length_mm": 0,
            "label": label,
            "zone_label": None,  # walk_mm에서 채움
        })

    return points


# ── 입구 기준 방위 (entrance_side) ────────────────────────────────────────

def _compute_v_right(entrance_mm: tuple, usable_poly) -> tuple[float, float]:
    """입구→매장중심 벡터를 시계방향 90° 회전한 단위벡터 (입구에서 봤을 때 오른쪽 방향)."""
    centroid = usable_poly.centroid
    dx = centroid.x - entrance_mm[0]
    dy = centroid.y - entrance_mm[1]
    length = math.hypot(dx, dy)
    if length < 1:
        return (1.0, 0.0)
    v_in = (dx / length, dy / length)
    return (v_in[1], -v_in[0])  # 시계방향 90°: (x,y) → (y,-x)


def _tag_entrance_side(ref_points: list, entrance_mm: tuple, v_right: tuple[float, float], threshold: float = 0.25) -> None:
    """모든 ref_point에 entrance_side 태깅 (in-place).

    dot(ref_point - entrance, v_right) / dist 의 부호로 판정:
      > threshold  → "right"
      < -threshold → "left"
      그 외         → "center"
    """
    ex, ey = entrance_mm
    vrx, vry = v_right
    for rp in ref_points:
        coord = rp.get("coord")
        if not coord:
            rp["entrance_side"] = None
            continue
        dx, dy = coord[0] - ex, coord[1] - ey
        dist = math.hypot(dx, dy)
        if dist < 1:
            rp["entrance_side"] = "center"
            continue
        dot = (dx * vrx + dy * vry) / dist  # -1 ~ 1
        if dot > threshold:
            rp["entrance_side"] = "right"
        elif dot < -threshold:
            rp["entrance_side"] = "left"
        else:
            rp["entrance_side"] = "center"


# ── Interior Grid ref_point (slot_gen 흡수) ───────────────────────────────

# 1-3 (#533) 후속 동기화: slot_gen.DECOMPRESSION_RADIUS_MM single source 사용.
# 기존 1500 → slot_gen 의 900 따라가도록 변경 (진규님 2026-04-22 소형 18평 하향 반영).
# 회귀: slot 영역과 interior ref_point 영역이 다른 감압존 반경을 쓰면 ref_point 누락 / floating.
from app.nodes_small.slot_gen import DECOMPRESSION_RADIUS_MM


def _generate_interior_ref_points(
    usable_poly,
    dead_zones: list,
    inner_walls: list,
    entrance_points_shapely: list,
    entrance_pt,
    deepest_dist: float,
    start_idx: int,
    decomp_radius: int = DECOMPRESSION_RADIUS_MM,
) -> list[dict]:
    """벽 근처 interior grid 포인트 생성 (slot_gen._generate_interior_slots 흡수).

    center_ref_points와 달리 벽에서 가까운 영역도 포함.
    벽에서 CENTER_MIN_WALL_DIST 이내 ~ 외벽 바로 옆 제외.
    """
    if not usable_poly:
        return []

    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    step = max(500, min(2000, int(math.sqrt(short_side ** 2 * 0.5) * 0.7)))
    min_wall_dist = step * 0.8

    inner_wall_buffers = [w.buffer(150) for w in inner_walls if hasattr(w, "length") and w.length > 0]

    # 외벽 + 내벽 세그먼트 (가장 가까운 벽 찾기용)
    exterior_coords = list(usable_poly.exterior.coords)
    all_segments = []
    for i in range(len(exterior_coords) - 1):
        seg = LineString([exterior_coords[i], exterior_coords[i + 1]])
        if seg.length > 0:
            all_segments.append(seg)
    all_segments.extend(w for w in inner_walls if hasattr(w, "length") and w.length > 0)

    points = []
    ix = 0
    for gx in frange(minx + step, maxx - step, step):
        for gy in frange(miny + step, maxy - step, step):
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue

            wall_dist = usable_poly.exterior.distance(pt)
            # 벽에 너무 가까우면 스킵 (외벽 ref_point가 이미 커버)
            if wall_dist < min_wall_dist:
                continue
            # 중앙 ref_point 영역이면 스킵 (center_ref_points가 이미 커버)
            if wall_dist >= CENTER_MIN_WALL_DIST:
                continue

            if point_near_any(pt, entrance_points_shapely, decomp_radius):
                continue
            if point_in_any_obstacle(pt, dead_zones):
                continue
            if point_in_any_obstacle(pt, inner_wall_buffers):
                continue

            # 가장 가까운 벽 세그먼트 기반 법선
            nearest_seg = None
            nearest_dist = float("inf")
            for seg in all_segments:
                d = seg.distance(pt)
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_seg = seg

            nx_dir, ny_dir = 0.0, 1.0
            wall_angle = 0.0
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
                wall_angle = math.degrees(math.atan2(dy, dx))

            # 의미 라벨: 벽과 중앙 사이 영역
            label = "interior_area"
            if entrance_pt and deepest_dist > 0:
                ratio = entrance_pt.distance(pt) / deepest_dist
                if ratio < 0.25:
                    label = "interior_entrance"
                elif ratio > 0.75:
                    label = "interior_deep"

            points.append({
                "id": f"interior_{start_idx + ix}",
                "coord": (round(gx, 1), round(gy, 1)),
                "wall_segment": nearest_seg,
                "wall_normal_vec": (round(nx_dir, 4), round(ny_dir, 4)),
                "wall_normal": normal_label(nx_dir, ny_dir),
                "wall_angle_deg": round(wall_angle, 2),
                "wall_length_mm": 0,
                "label": label,
                "zone_label": None,  # walk_mm에서 채움
            })
            ix += 1

    logger.info("[ref_point_gen] interior grid: %d points (step=%dmm, wall_dist=%.0f~%.0fmm)",
                len(points), step, min_wall_dist, CENTER_MIN_WALL_DIST)
    return points
