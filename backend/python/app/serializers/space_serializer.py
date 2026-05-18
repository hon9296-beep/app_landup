"""
공간 데이터 직렬화 — state(Shapely) → 프론트용 dict / Java 정규화 payload.

프론트용 (_serialize_space_data) : 병합 dict 포맷. 3D 뷰어/오버레이가 직접 읽음.
Java용   (_space_data_to_java_payload) : DB 테이블 1:1 매핑되는 points/polygons/anchors/zones.
"""
import json


def _to_concept_area_en(name):
    """한국어 concept_area name → 영문 키 (Phase 4 응답/DB 정합).

    state 는 한국어 (LLM matching 일관), 응답/DB 시점에만 영문 변환.
    매핑 없으면 그대로 (커스텀 area).
    """
    if not name:
        return None
    from app.nodes_large.c_brand_area.concept_area import CONCEPT_AREA_LABEL_EN
    return CONCEPT_AREA_LABEL_EN.get(name, name)


def serialize_linestring(ls) -> list | None:
    """Shapely LineString → [[x, y], ...] 좌표 리스트."""
    if ls is None:
        return None
    return [[round(c[0], 1), round(c[1], 1)] for c in ls.coords]


def serialize_space_data(state: dict, session_id: str) -> dict:
    """state → 프론트용 SpaceData JSON."""
    usable_poly = state.get("usable_poly")
    entrance_mm = state.get("entrance_mm")

    ref_points_dict = {}
    for rp in state.get("reference_points", []):
        ref_points_dict[rp["id"]] = {
            "x_mm": rp["coord"][0],
            "y_mm": rp["coord"][1],
            "zone_label": rp.get("zone_label"),
            "wall_size_label": "넓은 벽" if rp.get("wall_length_mm", 0) > 2000 else "보통 벽" if rp.get("wall_length_mm", 0) > 1000 else "좁은 벽",
            "facing_entrance": rp.get("label") == "deep_wall",
            "is_entrance_wall": rp.get("label") == "entrance_adjacent",
            "is_partition": rp.get("label") == "inner_wall",
            "walk_mm": 0,
        }

    zone_counts = state.get("zone_map", {})
    zone_polygons = state.get("zone_polygons", {})
    zone_map = {}
    for zname in ("entrance_zone", "mid_zone", "deep_zone"):
        zp = zone_polygons.get(zname, {})
        zone_map[zname] = {
            "polygon_mm": zp.get("polygon_mm", []),
            "slot_count": zone_counts.get(zname, 0),
            "reference_points": [rp["id"] for rp in state.get("reference_points", []) if rp.get("zone_label") == zname],
            "walk_mm_range": [],
        }

    dead_zones_serial = []
    dz_types = state.get("dead_zone_types") or []
    for i, dz in enumerate(state.get("dead_zones", [])):
        dz_type = dz_types[i] if i < len(dz_types) else "unknown"
        # polygon 좌표 그대로 전달 (원형 근사치 폐기)
        if hasattr(dz, "exterior"):
            coords = [[round(c[0], 1), round(c[1], 1)] for c in dz.exterior.coords[:-1]]
        else:
            cx, cy = dz.centroid.x, dz.centroid.y
            coords = [[round(cx), round(cy)]]
        cx, cy = dz.centroid.x, dz.centroid.y
        bounds = dz.bounds
        radius = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 2
        dead_zones_serial.append({
            "type": dz_type,
            "center_mm": [round(cx), round(cy)],
            "radius_mm": round(radius),
            "polygon_mm": coords,
        })

    poly_mm = [(p[0], p[1]) for p in usable_poly.exterior.coords[:-1]] if usable_poly else []

    # ── concept_areas (2026-05-01 Phase 4-2 갈래 3 — 폴리곤 채우기용) ──
    # state["concept_areas"]: [{"name": "맞이"(KO), "polygon_mm": Polygon, "area_ratio": float, ...}, ...]
    # 응답: [{"name": "welcome"(EN), "polygon_mm": [[x,y],...], "area_ratio": float}, ...]
    # 한국어 라벨은 프론트 CONCEPT_AREA_LABEL_KO 매핑 dict 로 변환 (응답 단순화).
    concept_areas_serial = []
    for area in state.get("concept_areas", []) or []:
        poly = area.get("polygon_mm")
        if poly is None or not hasattr(poly, "exterior"):
            continue
        coords = [[round(c[0], 1), round(c[1], 1)] for c in poly.exterior.coords[:-1]]
        name_ko = area.get("name") or ""
        concept_areas_serial.append({
            "name": _to_concept_area_en(name_ko),  # 영문 키 (Viewer3D 색 매핑 + 프론트 KO 라벨 lookup)
            "polygon_mm": coords,
            "area_ratio": round(area.get("area_ratio", 0.0), 4),
        })

    scale_type_val = state.get("_scale_type", "large")
    return {
        "_session_id": session_id,
        "_scale_type": scale_type_val,
        "scale_type": scale_type_val,       # Java FloorDetectionService 정본 키
        "scale_mm_per_px": state.get("scale_mm_per_px"),
        "detected_width_mm": state.get("detected_width_mm"),
        "detected_height_mm": state.get("detected_height_mm"),
        "ceiling_height_mm": state.get("ceiling_height_mm"),
        "venue_type": state.get("venue_type"),
        "floor": {
            "polygon_mm": [[round(p[0], 1), round(p[1], 1)] for p in poly_mm],
            "usable_area_sqm": round(usable_poly.area / 1_000_000, 2) if usable_poly else 0,
            "max_object_w_mm": round(min(usable_poly.bounds[2] - usable_poly.bounds[0],
                                          usable_poly.bounds[3] - usable_poly.bounds[1]) * 0.4) if usable_poly else 0,
        },
        "entrance": {"x_mm": round(entrance_mm[0]), "y_mm": round(entrance_mm[1])} if entrance_mm else {"x_mm": 0, "y_mm": 0},
        "reference_points": ref_points_dict,
        "zone_map": zone_map,
        "concept_areas": concept_areas_serial,  # 2026-05-01 Phase 4-2 갈래 3 — 영역별 폴리곤 채우기 + 레전드용
        "dead_zones": dead_zones_serial,
        # main_artery 제거 (2026-05-08) — walk_mm 이 b_space_data → place 단계로 이동 (5/4).
        # 이 시점 state 에는 main_artery 없음. placement 응답 (place_serializer) 에 박힘.
        # entrance_line: walk_mm 노드 내부 계산용 중간 객체라 응답에서 제외 (프론트 미사용).
        "sprinklers_mm": [[round(s[0]), round(s[1])] for s in (state.get("sprinklers_mm") or [])],
        "hydrants_mm": [[round(h[0]), round(h[1])] for h in (state.get("hydrants_mm") or [])],
        "electric_panels_mm": [[round(e[0]), round(e[1])] for e in (state.get("electric_panels_mm") or [])],
    }


def space_data_to_java_payload(state: dict) -> dict:
    """state → Java FloorDetectionService.applySpaceDataResult 가 기대하는 정규화 포맷.

    프론트 serialize_space_data (병합 dict 포맷) 과 달리 Java DB 테이블에 1:1 매핑되는
    정규화 배열 (points/polygons/anchors/zones/main_artery) 을 생성.

    Java 기대 구조:
      { scale_type, venue_type, scale_mm_per_px, scale_confirmed,
        detected_width_mm, detected_height_mm, ceiling_height_mm,
        usable_area_sqm, usable_poly_json,
        points: [{type, x_mm, y_mm, width_mm?, is_main?}],
        polygons: [{kind, source, polygon_json, center_x_mm, center_y_mm, radius_mm}],
        anchors: [{anchor_key, x_mm, y_mm, wall_normal, wall_angle_deg, ...}],
        zones: [{zone_label, polygon_json}],
        main_artery: {linestring_json} | None }
    """
    usable_poly = state.get("usable_poly")

    # ── points ──
    points: list = []
    entrance_mm = state.get("entrance_mm")
    if entrance_mm:
        points.append({
            "type": "main_door",
            "x_mm": round(entrance_mm[0]),
            "y_mm": round(entrance_mm[1]),
            "width_mm": state.get("entrance_width_mm"),
            "is_main": True,
        })
    for e in state.get("all_entrances_mm", []) or []:
        if isinstance(e, dict) and e.get("type") == "EMERGENCY_EXIT":
            coord = e.get("coord") or (0, 0)
            points.append({
                "type": "emergency_exit",
                "x_mm": round(coord[0]),
                "y_mm": round(coord[1]),
                "is_main": False,
            })
    for s in state.get("sprinklers_mm", []) or []:
        points.append({"type": "sprinkler", "x_mm": round(s[0]), "y_mm": round(s[1])})
    for h in state.get("hydrants_mm", []) or []:
        points.append({"type": "fire_hydrant", "x_mm": round(h[0]), "y_mm": round(h[1])})
    for ep in state.get("electric_panels_mm", []) or []:
        points.append({"type": "electrical_panel", "x_mm": round(ep[0]), "y_mm": round(ep[1])})

    # ── polygons (inaccessible + dead_zone) ──
    polygons: list = []
    inaccessible_types = state.get("inaccessible_types", []) or []
    for i, poly in enumerate(state.get("inaccessible_polys", []) or []):
        src_type = inaccessible_types[i] if i < len(inaccessible_types) else "unknown"
        if hasattr(poly, "exterior"):
            coords = [[round(c[0], 1), round(c[1], 1)] for c in poly.exterior.coords[:-1]]
            cx, cy = poly.centroid.x, poly.centroid.y
            bounds = poly.bounds
            radius = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 2
        else:
            coords, cx, cy, radius = [], 0.0, 0.0, 0.0
        polygons.append({
            "kind": "inaccessible",
            "source": src_type,
            "polygon_json": json.dumps(coords),
            "center_x_mm": round(cx),
            "center_y_mm": round(cy),
            "radius_mm": round(radius),
        })
    dz_types = state.get("dead_zone_types") or []
    for i, dz in enumerate(state.get("dead_zones", []) or []):
        dz_type = dz_types[i] if i < len(dz_types) else "unknown"
        if hasattr(dz, "exterior"):
            coords = [[round(c[0], 1), round(c[1], 1)] for c in dz.exterior.coords[:-1]]
            cx, cy = dz.centroid.x, dz.centroid.y
            bounds = dz.bounds
            radius = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 2
        else:
            coords, cx, cy, radius = [], 0.0, 0.0, 0.0
        polygons.append({
            "kind": "dead_zone",
            "source": dz_type,
            "polygon_json": json.dumps(coords),
            "center_x_mm": round(cx),
            "center_y_mm": round(cy),
            "radius_mm": round(radius),
        })

    # ── anchors ──
    anchors: list = []
    for rp in state.get("reference_points", []) or []:
        coord = rp.get("coord") or (0, 0)
        anchors.append({
            "anchor_key": rp.get("id"),
            "x_mm": round(coord[0]),
            "y_mm": round(coord[1]),
            "wall_normal": rp.get("wall_normal"),
            "wall_angle_deg": rp.get("wall_angle_deg"),
            "wall_length_mm": rp.get("wall_length_mm"),
            "label": rp.get("label"),
            "zone_label": rp.get("zone_label"),
            "concept_area_id": rp.get("concept_area_id"),  # 2026-05-01 Phase 2 — concept_areas FK
            "concept_area": _to_concept_area_en(rp.get("concept_area")),  # 2026-05-01 Phase 4 — 응답 시점 영문 변환
            "walk_mm": rp.get("walk_mm", 0),
            "shelf_capacity": rp.get("shelf_capacity"),
        })

    # ── zones ──
    zones: list = []
    zone_polygons = state.get("zone_polygons", {}) or {}
    for zname, zdata in zone_polygons.items():
        poly_mm = zdata.get("polygon_mm", []) if isinstance(zdata, dict) else []
        zones.append({
            "zone_label": zname,
            "polygon_json": json.dumps(poly_mm),
        })

    # main_artery 제거 (2026-05-08) — walk_mm 이 placement 단계로 이동 후 b_space_data state 에 없음.
    # Java 도 floor_main_artery 테이블 코드 제거 완료 (FloorDetectionService.java).

    # ── usable_poly_json ──
    usable_poly_json = None
    if usable_poly is not None and hasattr(usable_poly, "exterior"):
        upj = [[round(p[0], 1), round(p[1], 1)] for p in usable_poly.exterior.coords[:-1]]
        usable_poly_json = json.dumps(upj)

    return {
        "scale_type": state.get("_scale_type", "large"),
        "venue_type": state.get("venue_type"),
        "scale_mm_per_px": state.get("scale_mm_per_px"),
        "scale_confirmed": bool(state.get("scale_confirmed", False)),
        "detected_width_mm": state.get("detected_width_mm"),
        "detected_height_mm": state.get("detected_height_mm"),
        "ceiling_height_mm": state.get("ceiling_height_mm"),
        "usable_area_sqm": round(usable_poly.area / 1_000_000, 2) if usable_poly else 0,
        "usable_poly_json": usable_poly_json,
        "points": points,
        "polygons": polygons,
        "anchors": anchors,
        "zones": zones,
        # main_artery 키 제거 (2026-05-08) — placement_results 로 이동.
    }
