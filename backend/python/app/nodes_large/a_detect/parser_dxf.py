"""
DXF 파서 노드 — ezdxf 기반 정밀 추출.

mm 단위 직접 추출 → scale_mm_per_px = 1.0.
안전장치: 좌표 정규화, snap tolerance 5mm, ARC tessellation.
"""
import math
import re
import logging
from typing import Optional

from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import polygonize, snap, unary_union

from app.dxf_utils import convert_dwg_to_dxf, read_dxf_bytes
from app.utils import calculate_parse_confidence
from app.state import LargeState

logger = logging.getLogger(__name__)

SNAP_TOLERANCE_MM = 5.0
CHORD_TOLERANCE_MM = 50.0
ARC_MIN_SEGMENTS = 8
ARC_MAX_SEGMENTS = 128
INACCESSIBLE_FALLBACK_SIZE_MM = 2000.0
INACCESSIBLE_SEARCH_RADIUS_MM = 5000.0

SECTION_LAYOUT_KEYWORDS = re.compile(r"단면|section|s-\d", re.IGNORECASE)
ENTRANCE_KEYWORDS = re.compile(r"entrance|입구|main\s*door|출입구", re.IGNORECASE)
EMERGENCY_KEYWORDS = re.compile(r"emergency|비상구|비상\s*출구|fire\s*exit", re.IGNORECASE)
INACCESSIBLE_KEYWORDS = re.compile(
    r"staff\s*only|사무실|창고|화장실|기계실|전기실|계단실|"
    r"storage|restroom|toilet|utility|mechanical|stairwell", re.IGNORECASE
)
DOOR_KEYWORDS = re.compile(r"door|문|entrance|입구", re.IGNORECASE)
# dead_zone 세분류: core(화장실/계단 — 진입로 확보 필요) vs pillar(기둥). 2026-05-02 small mirror.
DEAD_ZONE_CORE_KEYWORDS = re.compile(
    r"화장실|계단실|계단|restroom|toilet|stairwell|stair|"
    r"staff\s*only|사무실|창고|storage|utility|mechanical|기계실|전기실", re.IGNORECASE
)
DEAD_ZONE_PILLAR_KEYWORDS = re.compile(
    r"pillar|기둥|column|col\b|pier|구조체", re.IGNORECASE
)
SPRINKLER_PATTERN = re.compile(r"sprinkler|sp\b|spk|스프링클러|mep.sprinkler", re.IGNORECASE)
HYDRANT_PATTERN = re.compile(r"hydrant|fh\b|소화전|fire\s*hose", re.IGNORECASE)
ELEC_PANEL_PATTERN = re.compile(r"elec|mdp|분전반|eps|panel\b|mep.power", re.IGNORECASE)
WALL_LAYER_KEYWORDS = ("WALL", "벽", "PARTITION", "내벽", "INTERIOR")


# ── 레이어명 별칭 사전 (Alias) — 2026-05-04 small mirror ──────────────────
# DXF 레이어명이 정확히 일치하지 않아도 표준 이름으로 변환.
# 우리(large) 도면이 표준 레이어명 (usable_poly / entrance_zone / dead_zone_* / mep_*) 으로
# 그려졌을 때 _parse_by_layer 가 직접 추출 (fallback 보다 정확).
LAYER_ALIASES = {
    'usable_poly': {'usable_poly', 'usable poly', '외곽선', '바닥', 'floor', 'boundary', 'poly'},
    'entrance_zone': {'entrance_zone', 'entrance', '입구', '출입구', 'main_door', 'main door'},
    'core_stair': {'core_stair', 'a-core-stair', 'stair', 'stairwell', '계단', '계단실'},
    'core_toilet': {'core_toilet', 'a-core-toilet', 'toilet', 'restroom', '화장실', '화장실/계단'},
    'dead_zone_core': {'dead_zone_core', 'core', '창고', '사무실', '기계실', '전기실',
                        'storage', 'utility', 'mechanical', 'staff_only', 'staff only'},
    'dead_zone_pillar': {'dead_zone_pillar', 'pillar', '기둥', 'column', 'col', 'pier', '구조체'},
    'mep_sprinkler': {'mep_sprinkler', 'sprinkler', '스프링클러', 'sp', 'spk', '살수'},
    'mep_power': {'mep_power', 'power', '분전반', '전기', '콘센트', 'elec', 'mdp', 'eps', 'panel'},
}


def _standardize_layer(raw_name: str) -> Optional[str]:
    """레이어명을 표준 이름으로 변환. 매칭 안 되면 None."""
    clean = raw_name.strip().lower()
    for standard, aliases in LAYER_ALIASES.items():
        if clean in aliases:
            return standard
    return None


# ── LangGraph 노드 함수 ───────────────────────────────────────────────────

def run(state: LargeState) -> LargeState:
    """DXF/DWG 파일 파싱 → floor_polygon_px + 설비 + 입구.

    레이어명 규칙이 있으면 레이어 기반 직접 추출.
    없으면 닫힌 폴리라인 자동 추출(Tier 1) → 실패 시 레이어 선택 요청(Tier 2).
    force_layer 지정 시 해당 레이어를 usable_poly로 강제 할당.
    """
    file_bytes = state["file_bytes"]
    file_type = state.get("file_type", "dxf")
    force_layer = state.get("force_layer")

    if file_type == "dwg":
        dxf_bytes = convert_dwg_to_dxf(file_bytes)
    else:
        dxf_bytes = file_bytes

    doc = read_dxf_bytes(dxf_bytes)

    floor_layout, _ = _split_layouts(doc)
    msp = floor_layout or doc.modelspace()

    # ── force_layer: 사용자가 직접 지정한 레이어로 강제 추출 ──
    if force_layer:
        logger.info(f"[parser_dxf] force_layer={force_layer!r} — 강제 레이어 추출")
        raw_segments = _collect_all_segments(msp)
        all_points = [pt for seg in raw_segments for pt in seg]
        offset_x, offset_y = _compute_origin_offset(all_points)
        result = _parse_by_forced_layer(msp, force_layer, offset_x, offset_y)
        result["ceiling_height_mm"] = None
        return result

    # ── 레이어 규칙 판별: 우리 표준 레이어명 (usable_poly 등) 박힌 도면이면 직접 추출 ──
    layer_names = set(e.dxf.layer for e in msp)
    has_layer_rules = any(_standardize_layer(ln) == "usable_poly" for ln in layer_names)
    if has_layer_rules:
        logger.info("[parser_dxf] 레이어 규칙 감지 — 레이어 기반 추출")
        result = _parse_by_layer(msp)
        result["ceiling_height_mm"] = None
        return result

    # ── Tier 1: 세그먼트/키워드 기반 추출 ──
    logger.info("[parser_dxf] 레이어 규칙 없음 — Tier 1 자동 추출")
    raw_segments = _collect_all_segments(msp)

    all_points = []
    for seg in raw_segments:
        all_points.extend(seg)
    offset_x, offset_y = _compute_origin_offset(all_points)

    normalized = [
        [(x - offset_x, y - offset_y) for x, y in seg]
        for seg in raw_segments
    ]
    snapped = _snap_endpoints(normalized, SNAP_TOLERANCE_MM)

    # 가장 큰 닫힌 폴리라인 자동 추출 (레이어명 무관)
    floor_polygon = _extract_lwpolyline_polygon(msp, offset_x, offset_y)
    if not floor_polygon:
        # ── Tier 2: 자동 추출 실패 → 사용자 레이어 선택 요청 ──
        available_layers = sorted({e.dxf.layer for e in msp if e.dxf.layer.strip()})
        logger.info(f"[parser_dxf] 닫힌 폴리라인 없음 → layer_select_needed ({len(available_layers)}개 레이어)")
        return {
            "parse_status": "layer_select_needed",
            "available_layers": available_layers,
        }

    inner_walls = _extract_inner_walls(msp, offset_x, offset_y)
    entrances = _extract_entrances_text(msp, offset_x, offset_y)
    insert_entrances = _extract_entrances_inserts(msp, offset_x, offset_y)
    if not entrances and insert_entrances:
        entrances = insert_entrances
    elif insert_entrances:
        for ie in insert_entrances:
            is_dup = any(
                math.hypot(ie["x_px"] - e["x_px"], ie["y_px"] - e["y_px"]) < 500
                for e in entrances
            )
            if not is_dup:
                entrances.append(ie)

    inaccessible = _extract_inaccessible(msp, offset_x, offset_y, snapped)
    # 기하학적 기둥 감지 — 레이어명 무관, 형태 기반
    geometric_pillars = _detect_pillars_geometric(msp, offset_x, offset_y)
    inaccessible.extend(geometric_pillars)
    sprinklers = _extract_equipment(msp, SPRINKLER_PATTERN, offset_x, offset_y)
    hydrants = _extract_equipment(msp, HYDRANT_PATTERN, offset_x, offset_y)
    panels = _extract_equipment(msp, ELEC_PANEL_PATTERN, offset_x, offset_y)

    xs = [p[0] for p in floor_polygon]
    ys = [p[1] for p in floor_polygon]

    # DXF Y-up → 화면 Y-down 변환
    # DXF는 수학 좌표계(Y 위로 증가), SVG/화면은 Y 아래로 증가 → maxY - y 로 뒤집음
    max_y = max(ys)
    def _fy(y: float) -> float:
        return round(max_y - y, 1)

    floor_polygon  = [(p[0], _fy(p[1])) for p in floor_polygon]
    entrances      = [{**e, "y_px": _fy(e["y_px"])} for e in entrances]
    sprinklers     = [{**s, "y_px": _fy(s["y_px"])} for s in sprinklers]
    hydrants       = [{**h, "y_px": _fy(h["y_px"])} for h in hydrants]
    panels         = [{**p, "y_px": _fy(p["y_px"])} for p in panels]
    inner_walls    = [{"start_px": (w["start_px"][0], _fy(w["start_px"][1])),
                       "end_px":   (w["end_px"][0],   _fy(w["end_px"][1]))} for w in inner_walls]
    inaccessible   = [{"polygon_px": [(x, _fy(y)) for x, y in room["polygon_px"]],
                       "type": room.get("type", "unknown"),
                       "confidence": room["confidence"]} for room in inaccessible]

    # 2026-05-06: DXF 분기에서 vision 노드 미실행 → inaccessible_polys 변환 누락 fix.
    # dead_zone 노드가 inaccessible_polys / inaccessible_types 받아 데드존 처리.
    # 첫 번째 분기 = type 정보 없음 → "core" default.
    from shapely.geometry import Polygon as _ShpPoly
    inaccessible_polys_out = []
    inaccessible_types_out = []
    for room in inaccessible:
        poly_px = room.get("polygon_px")
        if poly_px and len(poly_px) >= 3:
            try:
                _poly = _ShpPoly(poly_px)
                if _poly.is_valid and _poly.area > 0:
                    inaccessible_polys_out.append(_poly)
                    inaccessible_types_out.append(room.get("type", "core"))
            except Exception as _e:
                logger.warning(f"[parser_dxf] inaccessible polygon 변환 실패: {_e}")

    logger.info(f"[parser_dxf] polygon={len(floor_polygon)}pts, "
                f"entrances={len(entrances)}, equipment={len(sprinklers)}sp+{len(hydrants)}fh+{len(panels)}ep, "
                f"inaccessible_polys={len(inaccessible_polys_out)}")

    return {
        "floor_polygon_px": floor_polygon,
        "scale_mm_per_px": 1.0,
        "scale_confirmed": True,
        "parse_confidence": calculate_parse_confidence("vector"),
        "detected_width_mm": round(max(xs) - min(xs), 1),
        "detected_height_mm": round(max(ys) - min(ys), 1),
        "ceiling_height_mm": None,
        "is_vector": True,
        "entrance": entrances[0] if entrances else None,
        "entrances": entrances,
        "entrance_width_mm": _extract_entrance_width(msp),
        "inner_walls": [{"start_px": w["start_px"], "end_px": w["end_px"]} for w in inner_walls],
        "inaccessible_rooms": inaccessible,
        "inaccessible_polys": inaccessible_polys_out,
        "inaccessible_types": inaccessible_types_out,
        "sprinklers": sprinklers,
        "fire_hydrants": hydrants,
        "electrical_panels": panels,
        "image_bytes": None,
        "vision_transform": None,
    }


# ── 기하학적 기둥 감지 ───────────────────────────────────────────────────

def _detect_pillars_geometric(msp, offset_x: float, offset_y: float) -> list:
    """레이어명 무관, 형태 기반으로 기둥(pillar) 후보 LWPOLYLINE 감지.

    조건:
      - 가로/세로 비율 0.7 ~ 1.3 (거의 정사각형)
      - 짧은 변 길이 300 ~ 900mm (기둥 규격 범위)
    """
    pillars = []
    for entity in msp:
        if entity.dxftype() != "LWPOLYLINE":
            continue
        pts_raw = list(entity.get_points(format="xy"))
        if len(pts_raw) < 3:
            continue
        pts = [(round(x - offset_x, 1), round(y - offset_y, 1)) for x, y in pts_raw]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if w <= 0 or h <= 0:
            continue
        ratio = max(w, h) / min(w, h)
        short = min(w, h)
        if ratio > 1.3 or not (300 <= short <= 900):
            continue
        poly = pts[:]
        if poly[0] != poly[-1]:
            poly.append(poly[0])
        pillars.append({
            "polygon_px": poly,
            "type": "pillar",
            "confidence": "medium",
        })
    return pillars


# ── 강제 레이어 추출 ─────────────────────────────────────────────────────

def _parse_by_forced_layer(msp, layer_name: str, offset_x: float, offset_y: float) -> dict:
    """사용자가 지정한 레이어의 가장 큰 LWPOLYLINE을 usable_poly로 강제 할당."""
    floor_polygon = None
    best_area = 0.0

    for entity in msp:
        if entity.dxf.layer != layer_name or entity.dxftype() != "LWPOLYLINE":
            continue
        pts_raw = list(entity.get_points(format="xy"))
        if len(pts_raw) < 3:
            continue
        pts = [(round(x - offset_x, 1), round(y - offset_y, 1)) for x, y in pts_raw]
        n = len(pts)
        area = abs(sum(pts[i][0]*pts[(i+1)%n][1] - pts[(i+1)%n][0]*pts[i][1] for i in range(n))) / 2
        if area > best_area:
            best_area = area
            floor_polygon = pts

    if not floor_polygon:
        raise ValueError(f"레이어 '{layer_name}'에서 폴리라인을 찾을 수 없습니다")

    xs = [p[0] for p in floor_polygon]
    ys = [p[1] for p in floor_polygon]
    max_y = max(ys)

    def _fy(y: float) -> float:
        return round(max_y - y, 1)

    floor_polygon = [(p[0], _fy(p[1])) for p in floor_polygon]

    logger.info(f"[parser_dxf:forced] layer={layer_name!r}, polygon={len(floor_polygon)}pts, "
                f"W={round(max(xs)-min(xs),1)}mm H={round(max(ys)-min(ys),1)}mm")

    return {
        "floor_polygon_px": floor_polygon,
        "scale_mm_per_px": 1.0,
        "scale_confirmed": True,
        "parse_confidence": calculate_parse_confidence("vector"),
        "detected_width_mm": round(max(xs) - min(xs), 1),
        "detected_height_mm": round(max(ys) - min(ys), 1),
        "is_vector": True,
        "entrance": None,
        "entrances": [],
        "entrance_width_mm": None,
        "inner_walls": [],
        "inaccessible_rooms": [],
        "sprinklers": [],
        "fire_hydrants": [],
        "electrical_panels": [],
        "image_bytes": None,
        "vision_transform": None,
    }


# ── 좌표 정규화 ───────────────────────────────────────────────────────────

def _compute_origin_offset(points):
    if not points:
        return 0.0, 0.0
    return min(p[0] for p in points), min(p[1] for p in points)


# ── snap tolerance ─────────────────────────────────────────────────────────

def _snap_endpoints(segments, tolerance):
    all_endpoints = []
    for seg in segments:
        if len(seg) >= 2:
            all_endpoints.append(list(seg[0]))
            all_endpoints.append(list(seg[-1]))

    merged_map = {}
    n = len(all_endpoints)
    visited = [False] * n

    for i in range(n):
        if visited[i]:
            continue
        cluster = [i]
        visited[i] = True
        for j in range(i + 1, n):
            if visited[j]:
                continue
            dx = all_endpoints[i][0] - all_endpoints[j][0]
            dy = all_endpoints[i][1] - all_endpoints[j][1]
            if math.hypot(dx, dy) <= tolerance:
                cluster.append(j)
                visited[j] = True
        avg_x = sum(all_endpoints[k][0] for k in cluster) / len(cluster)
        avg_y = sum(all_endpoints[k][1] for k in cluster) / len(cluster)
        rep = (round(avg_x, 1), round(avg_y, 1))
        for k in cluster:
            merged_map[k] = rep

    endpoint_idx = 0
    result = []
    for seg in segments:
        if len(seg) < 2:
            continue
        new_seg = list(seg)
        if endpoint_idx in merged_map:
            new_seg[0] = merged_map[endpoint_idx]
        endpoint_idx += 1
        if endpoint_idx in merged_map:
            new_seg[-1] = merged_map[endpoint_idx]
        endpoint_idx += 1
        if len(new_seg) == 2 and new_seg[0] == new_seg[-1]:
            continue
        result.append(new_seg)
    return result


# ── ARC/CIRCLE tessellation ────────────────────────────────────────────────

def _tessellate_arc(cx, cy, radius, start_deg, end_deg):
    start_rad = math.radians(start_deg)
    end_rad = math.radians(end_deg)
    if end_rad < start_rad:
        end_rad += 2 * math.pi
    delta = end_rad - start_rad
    arc_length = radius * abs(delta)
    n = max(ARC_MIN_SEGMENTS, int(arc_length / CHORD_TOLERANCE_MM))
    n = min(n, ARC_MAX_SEGMENTS)
    points = []
    for i in range(n + 1):
        theta = start_rad + delta * i / n
        points.append((round(cx + radius * math.cos(theta), 1),
                        round(cy + radius * math.sin(theta), 1)))
    return points


def _bulge_to_arc_points(x1, y1, x2, y2, bulge):
    dx, dy = x2 - x1, y2 - y1
    chord = math.hypot(dx, dy)
    if chord < 0.01:
        return [(x1, y1), (x2, y2)]
    sagitta = abs(bulge) * chord / 2
    radius = (chord**2 / 4 + sagitta**2) / (2 * sagitta)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    nx, ny = -dy / chord, dx / chord
    d = radius - sagitta
    if bulge > 0:
        cx, cy = mx - d * nx, my - d * ny
    else:
        cx, cy = mx + d * nx, my + d * ny
    sa = math.atan2(y1 - cy, x1 - cx)
    ea = math.atan2(y2 - cy, x2 - cx)
    if bulge > 0:
        if ea > sa:
            ea -= 2 * math.pi
    else:
        if ea < sa:
            ea += 2 * math.pi
    arc_length = abs(radius * (ea - sa))
    n = max(ARC_MIN_SEGMENTS, int(arc_length / CHORD_TOLERANCE_MM))
    n = min(n, ARC_MAX_SEGMENTS)
    points = []
    for i in range(n + 1):
        t = sa + (ea - sa) * i / n
        points.append((round(cx + radius * math.cos(t), 1),
                        round(cy + radius * math.sin(t), 1)))
    return points


# ── 선분 수집 ─────────────────────────────────────────────────────────────

def _collect_all_segments(msp):
    segments = []
    for entity in msp:
        dt = entity.dxftype()
        if dt == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            segments.append([(round(s.x, 1), round(s.y, 1)), (round(e.x, 1), round(e.y, 1))])
        elif dt == "LWPOLYLINE":
            pts = list(entity.get_points(format="xyseb"))
            if len(pts) < 2:
                continue
            poly_pts = []
            for i in range(len(pts)):
                x1, y1 = pts[i][0], pts[i][1]
                bulge = pts[i][4] if len(pts[i]) > 4 else 0.0
                poly_pts.append((round(x1, 1), round(y1, 1)))
                if bulge != 0 and i < len(pts) - 1:
                    arc_pts = _bulge_to_arc_points(x1, y1, pts[i+1][0], pts[i+1][1], bulge)
                    if len(arc_pts) > 2:
                        poly_pts.extend(arc_pts[1:-1])
            if entity.closed and len(poly_pts) >= 3:
                poly_pts.append(poly_pts[0])
            if len(poly_pts) >= 2:
                segments.append(poly_pts)
        elif dt == "ARC":
            segments.append(_tessellate_arc(
                entity.dxf.center.x, entity.dxf.center.y,
                entity.dxf.radius, entity.dxf.start_angle, entity.dxf.end_angle))
        elif dt == "CIRCLE":
            segments.append(_tessellate_arc(
                entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius, 0, 360))
    return segments


# ── polygon 구축 ──────────────────────────────────────────────────────────

def _build_outer_polygon(segments):
    lines = []
    for seg in segments:
        if len(seg) >= 2:
            try:
                ls = LineString(seg)
                if ls.is_valid and ls.length > 0:
                    lines.append(ls)
            except Exception:
                continue
    if not lines:
        return None
    merged = unary_union(lines)
    if isinstance(merged, MultiLineString):
        merged = snap(merged, merged, SNAP_TOLERANCE_MM)
    polygons = list(polygonize(merged))
    if not polygons:
        all_coords = [pt for seg in segments for pt in seg]
        if len(all_coords) < 3:
            return None
        from shapely.geometry import MultiPoint
        hull = MultiPoint(all_coords).convex_hull
        if isinstance(hull, Polygon) and hull.area > 0:
            return [(round(x, 1), round(y, 1)) for x, y in hull.exterior.coords]
        return None
    best = max(polygons, key=lambda p: p.area)
    return [(round(x, 1), round(y, 1)) for x, y in best.exterior.coords]


def _extract_lwpolyline_polygon(msp, offset_x, offset_y):
    best, best_area = None, 0.0
    for entity in msp.query("LWPOLYLINE"):
        pts_raw = list(entity.get_points(format="xyseb"))
        if len(pts_raw) < 3:
            continue
        pts = []
        for i in range(len(pts_raw)):
            x1, y1 = pts_raw[i][0], pts_raw[i][1]
            bulge = pts_raw[i][4] if len(pts_raw[i]) > 4 else 0.0
            pts.append((round(x1 - offset_x, 1), round(y1 - offset_y, 1)))
            if bulge != 0 and i < len(pts_raw) - 1:
                arc_pts = _bulge_to_arc_points(x1, y1, pts_raw[i+1][0], pts_raw[i+1][1], bulge)
                for ap in arc_pts[1:-1]:
                    pts.append((round(ap[0] - offset_x, 1), round(ap[1] - offset_y, 1)))
        n = len(pts)
        area = abs(sum(pts[i][0]*pts[(i+1)%n][1] - pts[(i+1)%n][0]*pts[i][1] for i in range(n))) / 2
        if area > best_area:
            best_area = area
            best = pts
    return best


# ── 입구/설비/내벽 추출 ───────────────────────────────────────────────────

def _get_text(entity):
    if entity.dxftype() == "MTEXT":
        try:
            return entity.plain_text()
        except Exception:
            return getattr(entity.dxf, "text", "") or ""
    return getattr(entity.dxf, "text", "") or ""


def _get_insert(entity):
    try:
        ins = entity.dxf.insert
        return (ins.x, ins.y)
    except AttributeError:
        return None


def _extract_entrances_text(msp, ox, oy):
    entrances = []
    for entity in msp.query("TEXT MTEXT"):
        text = _get_text(entity)
        if not text:
            continue
        ins = _get_insert(entity)
        if ins is None:
            continue
        x, y = round(ins[0] - ox, 1), round(ins[1] - oy, 1)
        if EMERGENCY_KEYWORDS.search(text):
            entrances.append({"x_px": x, "y_px": y, "confidence": "high", "is_main": False, "type": "EMERGENCY_EXIT"})
        elif ENTRANCE_KEYWORDS.search(text):
            entrances.append({"x_px": x, "y_px": y, "confidence": "high", "is_main": True, "type": "MAIN_DOOR"})
    return entrances


def _extract_entrances_inserts(msp, ox, oy):
    entrances = []
    for entity in msp.query("INSERT"):
        name = (entity.dxf.name or "").upper()
        layer = entity.dxf.layer.upper()
        if not DOOR_KEYWORDS.search(f"{name} {layer}"):
            continue
        pt = entity.dxf.insert
        is_emergency = EMERGENCY_KEYWORDS.search(f"{name} {layer}")
        entrances.append({
            "x_px": round(pt.x - ox, 1), "y_px": round(pt.y - oy, 1),
            "confidence": "high",
            "is_main": not is_emergency,
            "type": "EMERGENCY_EXIT" if is_emergency else "MAIN_DOOR",
        })
    return entrances


def _extract_entrance_width(msp):
    for entity in msp.query("INSERT"):
        name = (entity.dxf.name or "").upper()
        layer = entity.dxf.layer.upper()
        if DOOR_KEYWORDS.search(f"{name} {layer}"):
            x_scale = getattr(entity.dxf, "xscale", 1.0)
            if x_scale and x_scale > 100:
                return float(x_scale)
    return None


def _extract_inner_walls(msp, ox, oy):
    walls = []
    for entity in msp.query("LINE LWPOLYLINE"):
        layer = entity.dxf.layer.upper()
        if not any(kw in layer for kw in WALL_LAYER_KEYWORDS):
            continue
        if entity.dxftype() == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            walls.append({"start_px": (round(s.x-ox,1), round(s.y-oy,1)),
                          "end_px": (round(e.x-ox,1), round(e.y-oy,1))})
        elif entity.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in entity.get_points()]
            for i in range(len(pts)-1):
                walls.append({"start_px": (round(pts[i][0]-ox,1), round(pts[i][1]-oy,1)),
                              "end_px": (round(pts[i+1][0]-ox,1), round(pts[i+1][1]-oy,1))})
    return walls


def _extract_inaccessible(msp, ox, oy, segments):
    from shapely.geometry import Point

    STAIR_KEYWORDS = re.compile(r"계단실|계단|stairwell|stair", re.IGNORECASE)
    TOILET_KEYWORDS = re.compile(r"화장실|restroom|toilet", re.IGNORECASE)

    def _classify_type(text: str) -> str:
        if DEAD_ZONE_PILLAR_KEYWORDS.search(text):
            return "pillar"
        if STAIR_KEYWORDS.search(text):
            return "stair"
        if TOILET_KEYWORDS.search(text):
            return "toilet"
        if DEAD_ZONE_CORE_KEYWORDS.search(text):
            return "core"
        return "core"

    results = []
    for entity in msp.query("TEXT MTEXT"):
        text = _get_text(entity)
        if not text or not INACCESSIBLE_KEYWORDS.search(text):
            continue
        ins = _get_insert(entity)
        if ins is None:
            continue
        tx, ty = round(ins[0]-ox, 1), round(ins[1]-oy, 1)
        room_type = _classify_type(text)

        # 주변 폐합 polygon 탐색
        lines = []
        for seg in segments:
            if len(seg) >= 2:
                try:
                    ls = LineString(seg)
                    if ls.is_valid and ls.length > 0:
                        lines.append(ls)
                except Exception:
                    continue
        enclosing = None
        if lines:
            merged = unary_union(lines)
            polys = list(polygonize(merged))
            point = Point(tx, ty)
            candidates = [p for p in polys if p.contains(point)]
            if not candidates:
                candidates = [p for p in polys if p.distance(point) < INACCESSIBLE_SEARCH_RADIUS_MM and p.area < 50_000_000]
            if candidates:
                best = min(candidates, key=lambda p: p.area)
                enclosing = [(round(x,1), round(y,1)) for x, y in best.exterior.coords]

        if enclosing:
            results.append({"polygon_px": enclosing, "type": room_type, "confidence": "high"})
        else:
            half = INACCESSIBLE_FALLBACK_SIZE_MM / 2
            results.append({"polygon_px": [
                (tx-half, ty-half), (tx+half, ty-half), (tx+half, ty+half), (tx-half, ty+half), (tx-half, ty-half)
            ], "type": room_type, "confidence": "medium"})
    return results


def _extract_equipment(msp, pattern, ox, oy):
    points = []
    for entity in msp.query("INSERT"):
        combined = f"{entity.dxf.name or ''} {entity.dxf.layer or ''}"
        if not pattern.search(combined):
            continue
        pt = entity.dxf.insert
        points.append({"x_px": round(pt.x-ox,1), "y_px": round(pt.y-oy,1), "confidence": "high"})
    return points


# ── 레이아웃 분리 ─────────────────────────────────────────────────────────

def _split_layouts(doc):
    floor, section = None, None
    for layout in doc.layouts:
        if layout.name == "Model":
            continue
        if len(list(layout)) == 0:
            continue
        if SECTION_LAYOUT_KEYWORDS.search(layout.name):
            section = layout
        elif floor is None:
            floor = layout
    return floor, section


def _extract_ceiling_height_from_section(section_layout) -> Optional[float]:
    """단면도 레이아웃에서 층고(2100~6000mm) 추출.

    TEXT/MTEXT/DIMENSION 엔티티에서 4자리 숫자를 찾고,
    2100~6000mm 범위 중 가장 많이 등장하는 값을 반환.
    2100mm 하한은 상업공간 건축법 최소 층고 기준 (이하는 가구 치수 오탐 가능성).
    감지 실패 시 None 반환 (에러 없음).
    """
    if section_layout is None:
        return None

    from collections import Counter
    import re as _re
    HEIGHT_PATTERN = _re.compile(r'\b(\d{4})\b')
    candidates = []

    for entity in section_layout.query("TEXT MTEXT"):
        text = _get_text(entity)
        for m in HEIGHT_PATTERN.findall(text):
            val = float(m)
            if 2100 <= val <= 6000:  # 상업공간 건축법 최소 층고 2100mm 기준
                candidates.append(val)

    for entity in section_layout.query("DIMENSION"):
        val = getattr(entity.dxf, 'actual_measurement', None)
        if val and 2100 <= val <= 6000:  # 상업공간 건축법 최소 층고 2100mm 기준
            candidates.append(float(round(val)))

    if not candidates:
        logger.info("[parser_dxf] 단면도에서 층고 감지 실패 (후보 없음)")
        return None

    result = Counter(candidates).most_common(1)[0][0]
    logger.info(f"[parser_dxf] 층고 감지: {result}mm (후보={candidates})")
    return result


# ── 레이어 기반 추출 (small mirror, 2026-05-04) ─────────────────────────
# 우리 표준 레이어명 박힌 DXF 도면 직접 추출. fallback (세그먼트 기반) 보다 정확.
# 박는 state 키 = LargeState 정의 그대로 (별도 매핑 없음 — 검증 완료).

def _parse_by_layer(msp) -> dict:
    """레이어명 규칙 기반 직접 추출.

    레이어 규칙 (별칭 포함, LAYER_ALIASES 참조):
      usable_poly       → 바닥 외곽선 (LWPOLYLINE)
      entrance_zone     → 입구 영역 (LINE → 중점 계산)
      core_stair        → 계단 (LWPOLYLINE)
      core_toilet       → 화장실 (LWPOLYLINE)
      dead_zone_core    → 기타 코어 (창고/사무실 등, LWPOLYLINE)
      dead_zone_pillar  → 기둥 (LWPOLYLINE)
      mep_sprinkler     → 스프링클러 (CIRCLE → 중심점)
      mep_power         → 분전반 (POINT)
    """
    floor_polygon = None
    entrances = []
    inaccessible = []
    sprinklers = []
    hydrants = []
    panels = []

    for entity in msp:
        layer = _standardize_layer(entity.dxf.layer)
        if layer is None:
            continue
        etype = entity.dxftype()

        # ── usable_poly: 바닥 외곽선 ──
        if layer == "usable_poly" and etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            floor_polygon = [(round(x, 1), round(y, 1)) for x, y in pts]

        # ── entrance_zone: 입구 (LINE → 중점 계산) ──
        elif layer == "entrance_zone" and etype == "LINE":
            sx, sy = entity.dxf.start.x, entity.dxf.start.y
            ex, ey = entity.dxf.end.x, entity.dxf.end.y
            mid_x = round((sx + ex) / 2, 1)
            mid_y = round((sy + ey) / 2, 1)
            is_dup = any(
                math.hypot(mid_x - e["x_px"], mid_y - e["y_px"]) < 500
                for e in entrances
            )
            if not is_dup:
                entrances.append({"x_px": mid_x, "y_px": mid_y, "type": "MAIN_DOOR", "confidence": "high"})

        # ── core_stair: 계단 ──
        elif layer == "core_stair" and etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            poly = [(round(x, 1), round(y, 1)) for x, y in pts]
            if poly[0] != poly[-1]:
                poly.append(poly[0])
            from app.vmd_constants import ROOM_TYPE_STAIR
            inaccessible.append({"polygon_px": poly, "type": ROOM_TYPE_STAIR, "confidence": "high"})

        # ── core_toilet: 화장실 ──
        elif layer == "core_toilet" and etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            poly = [(round(x, 1), round(y, 1)) for x, y in pts]
            if poly[0] != poly[-1]:
                poly.append(poly[0])
            from app.vmd_constants import ROOM_TYPE_TOILET
            inaccessible.append({"polygon_px": poly, "type": ROOM_TYPE_TOILET, "confidence": "high"})

        # ── dead_zone_core: 기타 코어 (하위 호환) ──
        elif layer == "dead_zone_core" and etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            poly = [(round(x, 1), round(y, 1)) for x, y in pts]
            if poly[0] != poly[-1]:
                poly.append(poly[0])
            from app.vmd_constants import ROOM_TYPE_CORE
            inaccessible.append({"polygon_px": poly, "type": ROOM_TYPE_CORE, "confidence": "high"})

        # ── dead_zone_pillar: 기둥 ──
        elif layer == "dead_zone_pillar" and etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            poly = [(round(x, 1), round(y, 1)) for x, y in pts]
            if poly[0] != poly[-1]:
                poly.append(poly[0])
            from app.vmd_constants import ROOM_TYPE_PILLAR
            inaccessible.append({"polygon_px": poly, "type": ROOM_TYPE_PILLAR, "confidence": "high"})

        # ── mep_sprinkler: 스프링클러 (CIRCLE → 중심점) ──
        elif layer == "mep_sprinkler" and etype == "CIRCLE":
            c = entity.dxf.center
            r = entity.dxf.radius
            sprinklers.append({
                "x_px": round(c.x, 1), "y_px": round(c.y, 1),
                "radius_mm": round(r, 1),
                "confidence": "high",
            })

        # ── mep_power: 분전반 (POINT) ──
        elif layer == "mep_power" and etype == "POINT":
            p = entity.dxf.location
            panels.append({"x_px": round(p.x, 1), "y_px": round(p.y, 1), "confidence": "high"})
            logger.info(f"[parser_dxf:layer] panel POINT at ({p.x:.0f}, {p.y:.0f}), layer={entity.dxf.layer}")
        elif layer == "mep_power":
            logger.info(f"[parser_dxf:layer] mep_power 미처리: type={etype}, layer={entity.dxf.layer}")

    if not floor_polygon:
        raise ValueError("usable_poly 레이어에서 바닥 polygon 을 찾을 수 없습니다")

    xs = [p[0] for p in floor_polygon]
    ys = [p[1] for p in floor_polygon]

    # DXF Y-up → 화면 Y-down 변환
    max_y = max(ys)
    def _fy(y: float) -> float:
        return round(max_y - y, 1)

    floor_polygon = [(p[0], _fy(p[1])) for p in floor_polygon]
    entrances     = [{**e, "y_px": _fy(e["y_px"])} for e in entrances]
    sprinklers    = [{**s, "y_px": _fy(s["y_px"])} for s in sprinklers]
    hydrants      = [{**h, "y_px": _fy(h["y_px"])} for h in hydrants]
    panels        = [{**p, "y_px": _fy(p["y_px"])} for p in panels]
    inaccessible  = [
        {**room, "polygon_px": [(p[0], _fy(p[1])) for p in room["polygon_px"]]}
        for room in inaccessible
    ]

    # 2026-05-06: DXF 분기에서 vision 미실행 → inaccessible_polys 변환 누락 fix.
    # type 정보 살아있음 (ROOM_TYPE_TOILET / ROOM_TYPE_PILLAR / ROOM_TYPE_CORE / ROOM_TYPE_STAIR).
    from shapely.geometry import Polygon as _ShpPoly
    inaccessible_polys_out = []
    inaccessible_types_out = []
    for room in inaccessible:
        poly_px = room.get("polygon_px")
        if poly_px and len(poly_px) >= 3:
            try:
                _poly = _ShpPoly(poly_px)
                if _poly.is_valid and _poly.area > 0:
                    inaccessible_polys_out.append(_poly)
                    inaccessible_types_out.append(room.get("type", "unknown"))
            except Exception as _e:
                logger.warning(f"[parser_dxf:layer] inaccessible polygon 변환 실패: {_e}")

    logger.info(f"[parser_dxf:layer] polygon={len(floor_polygon)}pts, "
                f"entrances={len(entrances)}, dead_zones={len(inaccessible)}, "
                f"sprinklers={len(sprinklers)}, panels={len(panels)}, "
                f"inaccessible_polys={len(inaccessible_polys_out)} (types={inaccessible_types_out})")

    return {
        "floor_polygon_px": floor_polygon,
        "scale_mm_per_px": 1.0,
        "scale_confirmed": True,
        "parse_confidence": calculate_parse_confidence("vector"),
        "detected_width_mm": round(max(xs) - min(xs), 1),
        "detected_height_mm": round(max(ys) - min(ys), 1),
        "is_vector": True,
        "entrance": entrances[0] if entrances else None,
        "entrances": entrances,
        "entrance_width_mm": None,
        "inner_walls": [],
        "inaccessible_rooms": inaccessible,
        "inaccessible_polys": inaccessible_polys_out,
        "inaccessible_types": inaccessible_types_out,
        "sprinklers": sprinklers,
        "fire_hydrants": hydrants,
        "electrical_panels": panels,
        "image_bytes": None,
        "vision_transform": None,
    }

