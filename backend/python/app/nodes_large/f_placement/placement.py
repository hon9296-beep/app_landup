"""
배치 엔진 노드 — Rendy 코드 베이스.

Agent 3 design_intents → calculate_position + 8단계 검증 루프.
코드가 좌표 계산. LLM은 방향만.
가벽(partition_wall_I / partition_wall_L) 배치 시 양면 ref_point 자동 생성.
"""
import math
import logging
import networkx as nx
from shapely.geometry import Point
from shapely.geometry import box as shapely_box
from shapely.affinity import rotate as shapely_rotate
from shapely.ops import unary_union

from app.state import LargeState
from app.utils import calculate_position, serialize_placement

logger = logging.getLogger(__name__)

# ── 통로 버퍼 설정 ──────────────────────────────────────────────────────
# 보조동선 기본 간격: 900mm (버퍼 450mm)
# 장애인 편의 모드(1200mm)로 전환 시 아래 값을 600으로 변경
CORRIDOR_HALF_BUFFER_MM = 450  # 900mm ÷ 2. → 1200mm 모드: 600으로 변경
MAIN_ARTERY_HALF_BUFFER_MM = 600  # 주동선/비상대피로 양측 버퍼 (합 1200mm)
DEFAULT_CLEARSPACE_MM = 900       # 브랜드 미지정 시 기본 clearspace
DEFAULT_HEIGHT_MM = 1500          # 오브젝트 높이 fallback
# 2026-05-04 신설 — 사용자 의도 흐름 (배치 후 동선) 정합. 사용자 결정 = 옵션 a (빡세게).
# 공장형 large 매장 정합. 가구 사이 최소 통로 900mm 강제.
# 사람 통행 + 휠체어 부분 정합 (장애인 편의 1200mm 까지 가려면 추후 확대).
MIN_FURNITURE_GAP_MM = 900
FLOOR_OVERLAP_MIN = 0.995  # bbox가 바닥 안에 99.5% 이상 (부동소수점 오차 0.5%만 허용)
_ZONE_ADJACENCY = {
    "entrance_zone": ["mid_zone"],
    "mid_zone": ["entrance_zone", "deep_zone"],
    "deep_zone": ["mid_zone"],
}


def run(state: LargeState) -> LargeState:
    """배치 엔진 실행 — ref_point only (slot fallback 제거)."""
    intents = state.get("design_intents") or []
    eligible = state.get("eligible_objects") or []
    brand_data = state.get("brand_data") or {}
    usable_poly = state.get("usable_poly")
    dead_zones = state.get("dead_zones") or []
    # 2026-05-04: main_artery 변수 제거 — 배치 단계에서 사전 동선 차단 X (walk_mm 이 placement 다음으로 이동).
    entrance_buffer = state.get("entrance_buffer")

    reference_points = state.get("reference_points") or []
    ref_point_map = {rp["id"]: rp for rp in reference_points}

    if not intents or not eligible or not usable_poly:
        return {"placed_objects": [], "placed_raw": [], "failed_objects": [], "placement_log": []}

    obj_map = {o["object_type"]: o for o in eligible}

    # Static cache
    # 2026-04-28 fix (TR_D [데드존_위_설치]): dict 형태 dead_zone 도 Shapely 로 변환해서 포함.
    # 이전엔 hasattr(dz, "area") 만 체크 → dict 형태면 제외되어 collision 검사 무력화 가능성.
    static_obstacles = []
    for dz in dead_zones:
        if hasattr(dz, "area"):
            static_obstacles.append(dz)
        elif isinstance(dz, dict) and dz.get("center_mm") and dz.get("radius_mm") is not None:
            cx, cy = dz["center_mm"][:2]
            static_obstacles.append(Point(cx, cy).buffer(float(dz["radius_mm"])))
        # 형태 모름 → skip (로그만)
        else:
            logger.warning(f"[placement] dead_zone 형태 인식 불가 — skip: {type(dz).__name__}")
    # 2026-05-04: main_artery 빠짐 — 사용자 의도 흐름 정합 (배치 후 동선 계산).
    # walk_mm 이 placement 다음으로 이동됐으므로 배치 단계에서 main_artery 사전 차단 X.
    # 통로 확보는 별도 룰 (MIN_FURNITURE_GAP_MM = 가구 사이 900mm) 로 처리.
    # if main_artery:
    #     static_obstacles.append(main_artery.buffer(MAIN_ARTERY_HALF_BUFFER_MM))
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None

    # 대형: 브랜드 매뉴얼 명시(source="manual") pair만 적용, vmd_default는 무시
    all_pair_rules = brand_data.get("pair_rules") or []
    pair_rules = [r for r in all_pair_rules if r.get("source") == "manual"]

    # 2026-04-30: 소방법 무관 검증 (보조동선 / 접근성 / corridor connectivity / choke point) 호출 제거.
    # large 디자인 자유도 ↑ — 소방법 (MAIN_ARTERY 1200mm) + static cache + 기배치 충돌만 유지.
    # _init_corridor_graph / _get_clearspace 함수 정의는 보존 (다른 모듈 호환).

    # ── locked_objects: 기존 배치 유지 — 장애물로 선등록 ──
    locked_objects = state.get("locked_objects") or []
    placed_polygons = []
    cumulative_footprint = 0

    for lo in locked_objects:
        cx = lo.get("center_x_mm", 0)
        cy = lo.get("center_y_mm", 0)
        width_mm = lo.get("width_mm", 800)
        depth_mm = lo.get("depth_mm", 600)
        rotation_deg = lo.get("rotation_deg", 0)
        poly = shapely_box(cx - width_mm / 2, cy - depth_mm / 2, cx + width_mm / 2, cy + depth_mm / 2)
        if rotation_deg:
            poly = shapely_rotate(poly, -rotation_deg, origin=(cx, cy))
        placed_polygons.append({
            "object_type": lo.get("object_type", ""),
            "center_x_mm": cx,
            "center_y_mm": cy,
            "rotation_deg": rotation_deg,
            "width_mm": width_mm,
            "depth_mm": depth_mm,
            "height_mm": lo.get("height_mm", DEFAULT_HEIGHT_MM),
            "bbox_polygon": poly,
            "anchor_key": lo.get("anchor_key", "locked"),
            "zone_label": "",
            "direction": lo.get("direction", ""),
            "placed_because": lo.get("placed_because", "기존 배치 유지"),
            "category": "",
            "wall_attachment": "free",
        })
        cumulative_footprint += width_mm * depth_mm

    if locked_objects:
        logger.info(f"[placement] locked_objects {len(locked_objects)}개 선등록, footprint={cumulative_footprint:.0f}mm²")

    failed = []
    log = []

    usable_area = usable_poly.area if usable_poly else 1
    density_ratio = state.get("density_ratio") or 0.25
    max_footprint = usable_area * density_ratio

    # 정렬: priority 순
    sorted_intents = sorted(intents, key=lambda x: x.get("priority") or 99)

    logger.info(f"[placement] 시작: {len(sorted_intents)} intents, "
                f"{len(reference_points)} ref_points, max_footprint={max_footprint:.0f}mm²")

    for intent in sorted_intents:
        obj = obj_map.get(intent["object_type"])
        if not obj:
            failed.append({"object_type": intent["object_type"], "reason": "eligible에 없음"})
            logger.info(f"[placement] {intent['object_type']}: SKIP — eligible에 없음")
            continue

        # 2026-05-01 Phase 3-3 — zone_label 매칭 → concept_area 매칭 (large 자유 디자인)
        # zone_label 은 small 만 사용. large 는 LLM 이 concept_area (한국어 name) 출력.
        concept_area = intent.get("concept_area")
        zone_label = intent.get("zone_label", "mid_zone")  # 호환 fallback (LLM 옛 형식)
        direction = intent.get("direction", "wall_facing")
        alignment = intent.get("alignment", "parallel")
        ref_point_id = intent.get("ref_point_id")

        # ── ref_point 후보 구성: 지정 → 같은 concept_area → 다른 area ──
        rp_candidates = []
        if ref_point_id and ref_point_id in ref_point_map:
            rp_candidates.append(ref_point_map[ref_point_id])

        # 같은 concept_area 의 다른 ref_point (walk_mm 순 정렬)
        if concept_area:
            same_area = [rp for rp in reference_points
                         if rp.get("concept_area") == concept_area and rp["id"] != ref_point_id]
            same_area.sort(key=lambda rp: rp.get("walk_mm", 0))
            rp_candidates.extend(same_area)
        else:
            # 호환: concept_area 없으면 zone_label 매칭 (LLM 옛 형식 대응)
            same_zone = [rp for rp in reference_points
                         if rp.get("zone_label") == zone_label and rp["id"] != ref_point_id]
            same_zone.sort(key=lambda rp: rp.get("walk_mm", 0))
            rp_candidates.extend(same_zone)

        # 다른 모든 ref_point fallback (concept_area 매칭 실패 시)
        other_rps = [rp for rp in reference_points
                     if rp not in rp_candidates and rp["id"] != ref_point_id]
        other_rps.sort(key=lambda rp: rp.get("walk_mm", 0))
        rp_candidates.extend(other_rps)

        logger.info(f"[placement] {obj['object_type']} ({obj['width_mm']}x{obj['depth_mm']}mm) → "
                    f"ref={ref_point_id}, concept_area={concept_area or zone_label}, dir={direction}, candidates={len(rp_candidates)}")

        placed = False
        for rp in rp_candidates:
            rp_slot = _ref_point_to_slot(rp)
            rp_slot["_floor_poly"] = usable_poly
            result = calculate_position(rp_slot, obj, direction, alignment, usable_poly)
            reason = _try_place_verbose(result, usable_poly, static_cache, placed_polygons,
                                        obj_type=obj["object_type"], join_with=intent.get("join_with"),
                                        pair_rules=pair_rules)
            if reason == "ok":
                footprint = obj["width_mm"] * obj["depth_mm"]
                if cumulative_footprint + footprint <= max_footprint:
                    cumulative_footprint += footprint
                    entry = {
                        **result,
                        "anchor_key": rp["id"],
                        "zone_label": rp.get("zone_label") or zone_label,
                        "concept_area_id": rp.get("concept_area_id"),  # 2026-05-01 Phase 2 — ref_point 의 area FK 전파
                        "concept_area": rp.get("concept_area"),         # 2026-05-01 Phase 4 — 프론트 색칠용 한국어 라벨
                        "direction": direction,
                        "placed_because": intent.get("placed_because", ""),
                        "height_mm": obj.get("height_mm", DEFAULT_HEIGHT_MM),
                        "category": obj.get("category", ""),
                        "wall_attachment": obj.get("wall_attachment", "free"),
                    }
                    placed_polygons.append(entry)
                    log.append(f"{intent['object_type']} → {rp['id']} | reason={intent.get('placed_because', '')}")
                    placed = True

                    # 가벽 배치 후 양면 ref_point 생성 (I/L 둘 다)
                    if intent["object_type"] in ("partition_wall_I", "partition_wall_L"):
                        new_rps = _generate_partition_ref_points(entry, usable_poly, dead_zones)
                        reference_points.extend(new_rps)
                        for nrp in new_rps:
                            ref_point_map[nrp["id"]] = nrp

                    break
                else:
                    logger.info(f"  [reject] {rp['id']}: density limit")
            else:
                logger.info(f"  [reject] {rp['id']}: {reason}")

        if not placed:
            failed.append({"object_type": intent["object_type"], "reason": "모든 ref_point 실패"})

    logger.info(f"[placement] {len(placed_polygons)} placed, {len(failed)} failed")

    # 2026-05-06 안전망 (D + E + F) — LLM design 결과 룰 위반 시 코드 강제 fix.
    # D: 영역 부적합 가구 reject / E: 입구 부적합 가구 reject / F: wall_facing 비율 cap.
    from app.nodes_large.f_placement.placement_safety import apply_safety_nets as _apply_placement_safety
    entrance_mm = state.get("entrance_mm")
    placed_polygons = _apply_placement_safety(placed_polygons, entrance_mm)
    logger.info(f"[placement] {len(placed_polygons)} placed (안전망 적용 후)")

    # 디버그 (2026-05-01) — entry 의 concept_area_id 매핑 결과
    n_with_ca = sum(1 for p in placed_polygons if p.get("concept_area_id"))
    logger.info(
        "[placement] entry concept_area_id 매핑: %d/%d (rp 라벨이 entry 까지 전파됐는지 추적)",
        n_with_ca, len(placed_polygons),
    )

    return {
        "placed_objects": [serialize_placement(p) for p in placed_polygons],
        "placed_raw": placed_polygons,
        "failed_objects": failed,
        "placement_log": log,
    }






def _get_clearspace(brand_data):
    cs = brand_data.get("brand", {}).get("clearspace_mm", {})
    if isinstance(cs, dict):
        return cs.get("value", DEFAULT_CLEARSPACE_MM)
    return DEFAULT_CLEARSPACE_MM


def _generate_partition_ref_points(
    placed_entry: dict,
    usable_poly,
    dead_zones: list,
    offset_mm: float = 500,
) -> list[dict]:
    """가벽 배치 결과 → 양면 ref_point 2개 생성.

    가벽의 긴 면(width) 양쪽 법선 방향으로 offset_mm 떨어진 곳에 ref_point 배치.
    usable_poly 밖이거나 dead_zone 안이면 해당 면은 생성하지 않음.
    """
    cx = placed_entry["center_x_mm"]
    cy = placed_entry["center_y_mm"]
    angle_deg = placed_entry.get("rotation_deg", 0)
    angle_rad = math.radians(angle_deg)
    w = placed_entry["width_mm"]
    anchor_key = placed_entry["anchor_key"]

    # 법선 벡터 (width 방향에 수직 = depth 방향)
    nx = -math.sin(angle_rad) * offset_mm
    ny = math.cos(angle_rad) * offset_mm

    new_rps = []
    for side, sign, label in [("A", 1, "앞면"), ("B", -1, "뒷면")]:
        rx = cx + nx * sign
        ry = cy + ny * sign

        pt = Point(rx, ry)
        if usable_poly and not usable_poly.contains(pt):
            continue
        if any(dz.contains(pt) for dz in dead_zones if hasattr(dz, "contains")):
            continue

        rp_id = f"partition_{anchor_key}_{side}"
        new_rps.append({
            "id": rp_id,
            "coord": (round(rx), round(ry)),
            "wall_segment": None,
            "wall_normal": "none",
            "wall_normal_vec": (nx / offset_mm * sign, ny / offset_mm * sign),
            "wall_angle_deg": angle_deg,
            "wall_length_mm": round(w),
            "label": "partition_face",
            "zone_label": placed_entry.get("zone_label", "mid_zone"),
            "is_partition": True,
        })
        logger.info(f"[placement] 가벽 ref_point 생성: {rp_id} ({label})")

    return new_rps


def _is_accessible(bbox, clearspace_mm, usable_poly, static_cache, placed_polygons):
    """4방향 접근성 검사 (buildup/spatial.py).

    bbox의 상하좌우 4방향 중 최소 1방향에서
    clearspace_mm 만큼의 접근 통로가 확보되는지 확인.
    """
    minx, miny, maxx, maxy = bbox.bounds
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2

    # 4방향 검사 포인트 (clearspace 거리만큼 떨어진 점)
    probes = [
        Point(cx, maxy + clearspace_mm),  # 위
        Point(cx, miny - clearspace_mm),  # 아래
        Point(maxx + clearspace_mm, cy),  # 오른쪽
        Point(minx - clearspace_mm, cy),  # 왼쪽
    ]

    for pt in probes:
        if not usable_poly.contains(pt):
            continue
        if static_cache and static_cache.contains(pt):
            continue
        blocked = False
        for existing in placed_polygons:
            if existing["bbox_polygon"].contains(pt):
                blocked = True
                break
        if not blocked:
            return True

    return False


def _ref_point_to_slot(rp: dict) -> dict:
    """reference_point → slot 호환 딕셔너리 변환."""
    return {
        "x_mm": rp["coord"][0],
        "y_mm": rp["coord"][1],
        "wall_linestring": rp.get("wall_segment"),
        "wall_normal": rp.get("wall_normal", "north"),
        "wall_normal_vec": rp.get("wall_normal_vec", (0.0, 1.0)),
        "wall_angle_deg": rp.get("wall_angle_deg", 0.0),
        "zone_label": rp.get("zone_label", "mid_zone"),
    }


def _try_place_verbose(
    result, usable_poly, static_cache, placed_polygons,
    obj_type: str = "", join_with: str = None, pair_rules: list = None,
) -> str:
    """검증 + 실패 사유 반환. 'ok'면 성공.

    유지 (소방법 / 구조 안전):
    - floor 95% 이탈 검사
    - static cache 충돌 (dead_zone + main_artery 1200mm + entrance)
    - 기배치 충돌 (pair_rules 기반)

    폐기 (large 디자인 자유도 ↑, 2026-04-30):
    - 보조동선 450mm 간격 / 접근성 4방향 / corridor connectivity / choke point
    """
    bbox = result["bbox_polygon"]

    # 1. floor 95%
    if bbox.area > 0:
        overlap = usable_poly.intersection(bbox).area
        if overlap / bbox.area < FLOOR_OVERLAP_MIN:
            return f"floor 이탈 ({overlap/bbox.area*100:.0f}%)"

    # 2. static cache (dead_zone + main_artery 600mm + entrance)
    if static_cache and bbox.intersects(static_cache):
        return "static cache 충돌 (dead_zone/artery/entrance)"

    # 3. 기배치 충돌 + 4. 통로 간격 (pair_rules 기반)
    for existing in placed_polygons:
        existing_type = existing.get("object_type", "")
        pair = _find_pair_rule(obj_type, existing_type, join_with, pair_rules or [])
        intersection_area = bbox.intersection(existing["bbox_polygon"]).area

        if pair and pair["relation"] == "join":
            # join: 겹침 허용 (overlap_margin_mm 이내)
            if intersection_area > 0:
                margin = pair.get("overlap_margin_mm", 0)
                if margin > 0:
                    ix0, iy0, ix1, iy1 = bbox.intersection(existing["bbox_polygon"]).bounds
                    overlap_depth = min(ix1 - ix0, iy1 - iy0)
                    if overlap_depth > margin:
                        return f"join 겹침 초과 ({overlap_depth:.0f}mm > {margin}mm, {existing_type})"
                elif intersection_area / min(bbox.area, existing["bbox_polygon"].area) > 0.2:
                    return f"join 면적 겹침 초과 (20%↑, {existing_type})"
            # join이면 통로 검사 스킵
            continue

        elif pair and pair["relation"] == "separate":
            # separate: min_gap_mm 이상 간격 강제
            if intersection_area > 0:
                return f"separate 쌍 겹침 ({obj_type}↔{existing_type})"
            gap = bbox.distance(existing["bbox_polygon"])
            min_gap = pair["min_gap_mm"]
            if 0 < gap < min_gap:
                return f"separate 간격 부족 ({gap:.0f}mm < {min_gap}mm, {obj_type}↔{existing_type})"

        else:
            # 기본 겹침 검사
            if intersection_area > 0:
                return f"기배치 충돌 ({existing_type})"
            # 2026-05-04 신설 — 통로 확보 (가구 사이 MIN_FURNITURE_GAP_MM 이상 간격 강제).
            # 사용자 결정 (옵션 a 빡세게) — 공장형 large 정합. 사람 통행 가능한 폭.
            # walk_mm 이 placement 다음으로 이동되어 main_artery 사전 차단 X 인 만큼,
            # 배치 단계에서 가구 사이 통로 확보 룰 직접 검증해야 동선 자체 사라지는 케이스 방지.
            gap = bbox.distance(existing["bbox_polygon"])
            if 0 < gap < MIN_FURNITURE_GAP_MM:
                return f"통로 부족 ({gap:.0f}mm < {MIN_FURNITURE_GAP_MM}mm, {existing_type})"

    return "ok"


def _find_pair_rule(obj_type_a: str, obj_type_b: str, join_with: str, pair_rules: list) -> dict | None:
    """두 오브젝트 타입 간 pair rule 조회.

    1순위: join_with 직접 지정 (Agent 3 출력)
    2순위: pair_rules 테이블에서 매칭 (* 와일드카드 지원)
    """
    # join_with 직접 지정
    if join_with and join_with == obj_type_b:
        return {"relation": "join", "min_gap_mm": 0, "overlap_margin_mm": 50}

    # pair_rules 테이블 조회
    for rule in pair_rules:
        a, b = rule["object_a"], rule["object_b"]
        if (a == obj_type_a and (b == obj_type_b or b == "*")) or \
           (a == obj_type_b and (b == obj_type_a or b == "*")) or \
           (b == obj_type_a and (a == obj_type_b or a == "*")) or \
           (b == obj_type_b and (a == obj_type_a or a == "*")):
            return rule

    return None


def _try_place(result, usable_poly, static_cache, placed_polygons, **kwargs):
    """배치 결과가 유효한지 검증. _try_place_verbose의 boolean 래퍼."""
    return _try_place_verbose(result, usable_poly, static_cache, placed_polygons, **kwargs) == "ok"


# ── NetworkX 통로 검증 (Rendy corridor_graph + choke point 이식) ──────────

def _init_corridor_graph(usable_poly, dead_zones, entrance_mm):
    """배치 엔진 시작 시 corridor 그래프 초기화.

    walk_mm.py의 _build_corridor_graph와 동일한 500mm 그리드.
    Returns: (graph, nodes_dict, entrance_node) or (None, None, None)
    """
    if not usable_poly:
        return None, None, None

    try:
        from app.nodes_large.b_space_data.walk_mm import _build_corridor_graph, _nearest_node
        G, nodes = _build_corridor_graph(usable_poly, dead_zones or [])
        if not nodes:
            return None, None, None

        if not entrance_mm:
            return G, nodes, None

        entrance_node = _nearest_node(nodes, entrance_mm)
        return G, nodes, entrance_node
    except Exception as e:
        logger.warning(f"[placement] corridor graph init failed: {e}")
        return None, None, None


def _check_corridor_connectivity(
    base_graph, nodes, entrance_node,
    new_bbox, reference_points, placed_polygons,
) -> bool:
    """새 bbox 배치 시 entrance → 미배치 ref_point 경로가 유지되는지 확인.

    Returns: True=통로 유지, False=통로 차단
    """
    if not base_graph or not nodes or not entrance_node:
        return True  # 그래프 없으면 검사 스킵

    # 새 bbox + 기배치 bbox를 모두 buffer로 장애물화
    obstacle = new_bbox.buffer(CORRIDOR_HALF_BUFFER_MM)
    for existing in placed_polygons:
        ep = existing.get("bbox_polygon")
        if ep:
            obstacle = obstacle.union(ep.buffer(CORRIDOR_HALF_BUFFER_MM))

    # 그래프 복사 후 장애물 내 노드 제거
    G = base_graph.copy()
    removed = []
    for node_key, (gx, gy) in nodes.items():
        if obstacle.contains(Point(gx, gy)):
            removed.append(node_key)
    G.remove_nodes_from(removed)

    if entrance_node not in G:
        return False

    # 미배치 ref_point 중 하나라도 도달 가능한지 확인
    from app.nodes_large.b_space_data.walk_mm import _nearest_node
    placed_rp_ids = {p.get("anchor_key") for p in placed_polygons}
    for rp in reference_points:
        if rp["id"] in placed_rp_ids:
            continue
        coord = rp.get("coord")
        if not coord:
            continue
        rp_node = _nearest_node(nodes, coord)
        if rp_node in G and nx.has_path(G, entrance_node, rp_node):
            return True

    return False


def _check_choke_point(new_bbox, placed_polygons, usable_poly, main_artery, entrance_buffer):
    """새 bbox 배치 시 동선이 900mm 미만으로 좁아지는지 검사.

    Returns: True=병목 발생, False=안전
    """
    if not usable_poly:
        return False

    MIN_CORRIDOR_MM = CORRIDOR_HALF_BUFFER_MM * 2  # 900mm (또는 1200mm 모드)

    # 새 bbox ↔ 외벽 간 gap
    wall_gap = usable_poly.exterior.distance(new_bbox)
    if 0 < wall_gap < MIN_CORRIDOR_MM:
        if entrance_buffer and new_bbox.intersects(entrance_buffer.buffer(MIN_CORRIDOR_MM)):
            return True

    # 새 bbox ↔ 기배치 오브젝트 간 gap
    for existing in placed_polygons:
        ep = existing.get("bbox_polygon")
        if not ep:
            continue
        gap = new_bbox.distance(ep)
        if 0 < gap < MIN_CORRIDOR_MM:
            if main_artery:
                buf_new = new_bbox.buffer(CORRIDOR_HALF_BUFFER_MM)
                buf_old = ep.buffer(CORRIDOR_HALF_BUFFER_MM)
                choke_zone = buf_new.intersection(buf_old)
                if not choke_zone.is_empty and main_artery.intersects(choke_zone):
                    return True

    return False
