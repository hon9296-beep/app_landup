"""
배치 엔진 노드 — Rendy 코드 베이스.

Agent 3 design_intents → calculate_position + 8단계 검증 루프.
코드가 좌표 계산. LLM은 방향만.
가벽(partition_wall) 배치 시 양면 ref_point 자동 생성.
"""
import math
import logging
from typing import Optional

import networkx as nx
from shapely.geometry import Point
from shapely.geometry import box as shapely_box
from shapely.affinity import rotate as shapely_rotate
from shapely.ops import unary_union

from app.state import SmallState
from app.utils import calculate_position, serialize_placement, extract_structural_dead_zones

logger = logging.getLogger(__name__)

# ── 배치 엔진 상수 ──────────────────────────────────────────────────────

# 밀도
DEFAULT_DENSITY_RATIO = 0.25          # 유효 면적 대비 최대 기물 점유율
LOW_DENSITY_THRESHOLD = 0.15          # 이 이하면 분산 GAP 적용

# 중앙 배치 상한 — 소형 매장 통로 소멸 방지
MAX_CENTER_PLACEMENTS = 2             # center/freestanding 방향 배치 최대 개수

# 기물 간 간격 — 면적 분기 (66㎡ = 20평 기준)
DISPERSED_GAP_MM = 1500               # 저밀도 시 분산 GAP (블랙홀 방지)
# SMALL_AREA_THRESHOLD_MM2 는 app.constants 로 중앙화 (2026-04-22 S-8g-1)
from app.constants import SMALL_AREA_THRESHOLD_MM2  # noqa: E402,F401

# 소형/중형 파라미터 분기
_ENGINE_PARAMS = {
    "small": {  # < 66㎡ (20평 이하)
        "gap_mm": 600,                    # 기물 간 간격 (성인 1인 측면 통과)
        "corridor_half_buffer_mm": 300,   # 보조동선 반버퍼 (합 600mm)
        "main_artery_half_buffer_mm": 450,# 주동선 반버퍼 (합 900mm)
        "min_absolute_gap_mm": 600,       # 절대 최소 간격
    },
    "medium": {  # ≥ 66㎡ (20평 초과)
        "gap_mm": 900,                    # 기물 간 간격
        "corridor_half_buffer_mm": 450,   # 보조동선 반버퍼 (합 900mm)
        "main_artery_half_buffer_mm": 600,# 주동선 반버퍼 (합 1200mm)
        "min_absolute_gap_mm": 600,       # 절대 최소 간격 (중형도 동일)
    },
}

# 기본값 (소형 — 모듈 레벨 상수 참조하는 코드 호환)
DEFAULT_GAP_MM = 600
CORRIDOR_HALF_BUFFER_MM = 300
MAIN_ARTERY_HALF_BUFFER_MM = 450
MIN_ABSOLUTE_GAP_MM = 600

# 바닥/이격
FLOOR_OVERLAP_MIN = 0.999             # bbox의 99.9% 이상 바닥 안에 있어야 함 (부동소수점 오차 방어)
DEFAULT_CLEARSPACE_MM = 600           # 브랜드 미지정 시 기본 이격 (인간 실질 활동 반경)
SAFETY_MARGIN_MM = 50                 # 도면 외곽선 안전 마진 (소방 불시 검사 대비)

# 스프링클러 살수 차단
SPRINKLER_CLEARANCE_MM = 450          # 스프링클러 헤드 수평 이격 반경
DEFAULT_CEILING_HEIGHT_MM = 3000      # 기본 천장고 (스프링클러 높이 = 천장고)

# 분전반 이격
ELECTRICAL_PANEL_HEIGHT_MM = 1800     # 분전반 외함 상단 설치 높이
ELECTRICAL_PANEL_CLEARANCE_MM = 600   # 분전반 수평 이격 반경

# 분전반 근접성
MEP_POWER_PROXIMITY_MM = 3000         # counter를 분전반 이 거리 이내에 우선 배치

# ── venue_type별 분기 상수 — Single Source of Truth: app/venue_rules.py ──
# 규제/소방법 추가·제거는 app/venue_rules.py 수정. 여기선 import만.
from app.venue_rules import VENUE_RULES
# ※ A-1 스프링클러, #20 소화전/소화기 → 소방기본법, venue_type 무관 항상 BLOCKING

# VMD 차단 기준
ENTRANCE_MAX_HEIGHT_MM = 1200         # entrance_zone 배치 가능 최대 높이 (기본값, venue_rules로 오버라이드)
DEFAULT_HEIGHT_MM = 1500              # height_mm 누락 시 기본값

# 하이브리드 slot 탐색 반경
SEARCH_RADIUS_WIDE_MM = 3000          # wall_length > 3000mm (넓은 벽)
SEARCH_RADIUS_NORMAL_MM = 2000        # wall_length > 1500mm (보통 벽) 또는 중앙 ref_point
SEARCH_RADIUS_NARROW_MM = 1000        # wall_length > 0mm (좁은 벽)
WALL_WIDE_THRESHOLD_MM = 3000         # 넓은 벽 판정 기준
WALL_NORMAL_THRESHOLD_MM = 1500       # 보통 벽 판정 기준

# 가벽
PARTITION_OFFSET_MM = 650             # 가벽 양면 ref_point 생성 오프셋 (clearspace 600mm 확보)

# pair_rules
JOIN_WITH_OVERLAP_MARGIN_MM = 50      # join_with 직접 지정 시 기본 겹침 허용치

_ZONE_ADJACENCY = {
    "entrance_zone": ["mid_zone"],
    "mid_zone": ["entrance_zone", "deep_zone"],
    "deep_zone": ["mid_zone"],
}


def run(state: SmallState) -> SmallState:
    """배치 엔진 실행 — 하이브리드: ref_point 가이드 + 주변 slot 해상도."""
    intents = state.get("design_intents") or []
    eligible = state.get("eligible_objects") or []
    brand_data = state.get("brand_data") or {}
    usable_poly_raw = state.get("usable_poly")

    # venue_type 분기 — 기본값 street_complex (가장 엄격)
    venue_type = state.get("venue_type") or "street_complex"
    venue_rules = VENUE_RULES.get(venue_type, VENUE_RULES["street_complex"])
    logger.info(f"[placement] venue_type={venue_type}")
    # 도면 외곽선 그대로 사용 — buffer(-50) 안전 마진 제거 (FLOOR_OVERLAP 99.5%로 오차 허용)
    usable_poly = usable_poly_raw
    dead_zones = state.get("dead_zones") or []
    structural_dz = extract_structural_dead_zones(state)
    main_artery = state.get("main_artery")
    entrance_buffer = state.get("entrance_buffer")
    slots = state.get("slots") or {}

    reference_points = state.get("reference_points") or []
    ref_point_map = {rp["id"]: rp for rp in reference_points}

    if not intents or not eligible or not usable_poly:
        return {"placed_objects": [], "placed_raw": [], "failed_objects": [], "placement_log": [], "scaled_clearances": {}}

    # 1-2 (#520 후속): 같은 object_type 내 manual_label 별 인스턴스 보존.
    # 기존 obj_map = {object_type: ...} 은 dict 덮어씀으로 counter 2개 (POS + 증정품) 가
    # 1개로 collapse — 라벨 + 사이즈 모두 마지막 1개만 남음. eligible_pool 도입으로 intent
    # 마다 1:1 소비 매칭 (manual_label 우선, fallback object_type) → 라벨 / 사이즈 보존.
    obj_map = {o["object_type"]: dict(o) for o in eligible}  # backward-compat metadata fallback
    eligible_pool = [dict(o) for o in eligible]  # 소비형 pool

    # ── dimension_overrides: resize 요청 시 치수 덮어쓰기 ──
    dim_overrides = state.get("dimension_overrides") or {}
    for obj_type, dims in dim_overrides.items():
        if obj_type in obj_map:
            if "width_mm" in dims:
                obj_map[obj_type]["width_mm"] = dims["width_mm"]
            if "depth_mm" in dims:
                obj_map[obj_type]["depth_mm"] = dims["depth_mm"]
            if "height_mm" in dims:
                obj_map[obj_type]["height_mm"] = dims["height_mm"]
            log_dims = f"w={dims.get('width_mm','—')} d={dims.get('depth_mm','—')}" + (f" h={dims['height_mm']}" if "height_mm" in dims else "")
            logger.info(f"[placement] 치수 오버라이드: {obj_type} → {log_dims}mm")
        # eligible_pool 의 같은 object_type 모든 인스턴스에 동일 override 적용
        for o in eligible_pool:
            if o.get("object_type") == obj_type:
                if "width_mm" in dims:
                    o["width_mm"] = dims["width_mm"]
                if "depth_mm" in dims:
                    o["depth_mm"] = dims["depth_mm"]
                if "height_mm" in dims:
                    o["height_mm"] = dims["height_mm"]


    def _consume_eligible(ot: str, manual_label: Optional[str]) -> Optional[dict]:
        """intent 의 (object_type, manual_label) 매칭되는 eligible 를 pool 에서 1개 pop.

        매칭 우선순위:
          1. manual_label 일치 (intent.manual_label 가 None 이 아닐 때) — 같은 object_type +
             같은 manual_label
          2. 같은 object_type 만 매칭 (manual_label 무관) — fallback
          3. 매칭 없으면 None — 호출부가 obj_map 으로 backward-compat fallback
        """
        if manual_label:
            for i, o in enumerate(eligible_pool):
                if o.get("object_type") == ot and o.get("manual_label") == manual_label:
                    return eligible_pool.pop(i)
        for i, o in enumerate(eligible_pool):
            if o.get("object_type") == ot:
                return eligible_pool.pop(i)
        return None

    # 면적 기반 파라미터 분기
    floor_area_mm2 = usable_poly.area if usable_poly else 0
    engine_size = "small" if floor_area_mm2 < SMALL_AREA_THRESHOLD_MM2 else "medium"
    ep = _ENGINE_PARAMS[engine_size]
    gap_mm = ep["gap_mm"]
    corridor_half = ep["corridor_half_buffer_mm"]
    artery_half = ep["main_artery_half_buffer_mm"]
    abs_gap_mm = ep["min_absolute_gap_mm"]
    # 모듈 레벨 상수를 면적 기반으로 동적 갱신 (choke_point 등 외부 함수에서 참조)
    global DEFAULT_GAP_MM, CORRIDOR_HALF_BUFFER_MM, MAIN_ARTERY_HALF_BUFFER_MM, MIN_ABSOLUTE_GAP_MM
    DEFAULT_GAP_MM = gap_mm
    CORRIDOR_HALF_BUFFER_MM = corridor_half
    MAIN_ARTERY_HALF_BUFFER_MM = artery_half
    MIN_ABSOLUTE_GAP_MM = abs_gap_mm
    logger.info(f"[placement] engine_size={engine_size} ({floor_area_mm2/1e6:.1f}m2), gap={gap_mm}, artery={artery_half*2}")

    # Static cache
    static_obstacles = list(dz for dz in dead_zones if hasattr(dz, "area"))
    # 계단 입구 core_access 폴리곤도 물리적 장애물에 추가
    for dz_entry in structural_dz:
        if dz_entry["type"] == "core_access":
            static_obstacles.append(dz_entry["poly"])
            logger.info(f"[placement] core_access 추가: area={dz_entry['poly'].area:.0f}mm²")
    if main_artery:
        static_obstacles.append(main_artery.buffer(artery_half))
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None

    clearspace = _get_clearspace(brand_data)
    pair_rules = brand_data.get("pair_rules") or []

    # 브랜드 매뉴얼 기물별 전후 이격 오버라이드 (DIRECTIONAL_CLEARANCE 기본값보다 우선)
    brand_clearances = {}
    for rule in brand_data.get("placement_rules") or []:
        ot = rule.get("object_type")
        if ot and (rule.get("front_clearance_mm") is not None or rule.get("back_clearance_mm") is not None):
            brand_clearances[ot] = {
                "front": rule.get("front_clearance_mm", 0),
                "back": rule.get("back_clearance_mm", 0),
            }

    # ── Tier 1-1 Layer 1-B: 면적 비례 scaled clearance 산출 ──
    # 18평 같은 협소 공간에서 photo_wall front 2000mm 같은 기본 이격이 물리적으로 확보 불가.
    # compute_scaled_clearance가 면적 비례 + floor 하한선 강제로 적정 시도값 계산.
    # 브랜드 매뉴얼이 명시한 값은 max(brand, floor)로 인체 안전 floor 강제 (옵션 A).
    # 참고: reports/AD/2026-04-20_small_store_finalization_tier1.md §1
    from app.vmd_constants import compute_scaled_clearance
    floor_area_mm2 = usable_poly.area if usable_poly else 0
    scaled_clearances = {}
    for o in eligible:
        ot = o.get("object_type")
        if not ot or ot in scaled_clearances:
            continue
        scaled_clearances[ot] = compute_scaled_clearance(
            ot, floor_area_mm2, brand_override=brand_clearances.get(ot)
        )
    if scaled_clearances:
        logger.info(
            f"[placement] scaled_clearances 산출: {len(scaled_clearances)}종 "
            f"(area={floor_area_mm2/1_000_000:.1f}㎡)"
        )

    # Corridor graph 초기화 (nx 통로 연결성 + choke point 검증용)
    corridor_graph, corridor_nodes, entrance_node = _init_corridor_graph(
        usable_poly, dead_zones, state.get("entrance_mm")
    )

    # ── 가벽 전처리 결과 선등록 (partition_placement에서 배치된 가벽) ──
    # 1-3 후속 (가벽 응답 누락 회귀 fix): 5-5 sub-graph 도입 시 _partition_placed_raw 키가
    # SmallState 정의에 없어 LangGraph state reduce 시 누락 → 가벽 응답 사라짐.
    # 회귀 검증: 2026-05-04 dump 까지 placed_objects[0]=partition_wall_I 정상,
    # 2026-05-06 dump 부터 누락. fix = SmallState 정의된 placed_partitions 직접 읽기.
    partition_placed = state.get("placed_partitions") or state.get("_partition_placed_raw") or []
    placed_polygons = list(partition_placed)  # 가벽을 기배치로 선등록
    cumulative_footprint = 0  # 가벽은 IQI 밀도에서 제외 (구조물)

    if partition_placed:
        logger.info(f"[placement] 가벽 전처리 {len(partition_placed)}개 선등록")

    # ── locked_objects: 기존 배치 유지 — 장애물로 선등록 ──
    locked_objects = state.get("locked_objects") or []

    for lo in locked_objects:
        cx = lo.get("center_x_mm", 0)
        cy = lo.get("center_y_mm", 0)
        w = lo.get("width_mm", 800)
        d = lo.get("depth_mm", 600)
        angle = lo.get("rotation_deg", 0)
        poly = shapely_box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
        if angle:
            poly = shapely_rotate(poly, -angle, origin=(cx, cy))
        placed_polygons.append({
            "object_type": lo.get("object_type", ""),
            "center_x_mm": cx,
            "center_y_mm": cy,
            "rotation_deg": angle,
            "width_mm": w,
            "depth_mm": d,
            "height_mm": lo.get("height_mm", 1500),
            "bbox_polygon": poly,
            "anchor_key": lo.get("anchor_key", "locked"),
            "zone_label": "",
            "direction": lo.get("direction", ""),
            "placed_because": lo.get("placed_because", "기존 배치 유지"),
            "category": "",
            "wall_attachment": "free",
            "front_vec": lo.get("front_vec"),
            # 2026-05-09 진규님 명시: label / manual_label 누락 fix.
            "label": lo.get("label") or lo.get("name") or lo.get("object_type", ""),
            "manual_label": lo.get("manual_label"),
            "front_edge": lo.get("front_edge", "width"),
        })
        cumulative_footprint += w * d

    if locked_objects:
        logger.info(f"[placement] locked_objects {len(locked_objects)}개 선등록, footprint={cumulative_footprint:.0f}mm²")

    failed = []
    log = []

    # IQI 밀도: dead zone 면적을 차감한 유효 면적 기준
    usable_area = usable_poly.area if usable_poly else 1
    if static_cache:
        usable_area -= static_cache.intersection(usable_poly).area
    density_ratio = state.get("density_ratio") or DEFAULT_DENSITY_RATIO
    max_footprint = usable_area * density_ratio
    center_placement_count = 0  # center/freestanding 방향 배치 카운터

    # ── 동적 GAP (Dispersion) 로직 ──
    dynamic_gap_mm = DISPERSED_GAP_MM if density_ratio <= LOW_DENSITY_THRESHOLD else gap_mm

    # ── 도면 외곽선(usable_poly) 검증 로그 ──
    if usable_poly:
        exterior_coords = [f"({int(x)},{int(y)})" for x, y in usable_poly.exterior.coords]
        area_msg = f"[blueprint_check] 도면 면적(usable_poly): {usable_poly.area / 1_000_000:.1f}㎡, BBox: {[int(b) for b in usable_poly.bounds]}"
        coords_msg = f"[blueprint_check] 도면 외곽선 꼭짓점: {' -> '.join(exterior_coords)}"
        
        logger.info(area_msg)
        logger.info(coords_msg)
        log.append(area_msg)
        log.append(coords_msg)

    # ── eligible 수량 초과 intent 제거 ──
    # LLM이 R7(수량 준수)을 무시하고 초과 배치하는 것을 코드에서 강제 차단
    from collections import Counter
    eligible_counts = Counter(o["object_type"] for o in eligible)
    intent_counts: dict[str, int] = {}
    trimmed_intents = []
    for intent in intents:
        ot = intent["object_type"]
        intent_counts[ot] = intent_counts.get(ot, 0) + 1
        if intent_counts[ot] <= eligible_counts.get(ot, 0):
            trimmed_intents.append(intent)
        else:
            logger.info(f"[placement] {ot} intent 초과 제거 ({intent_counts[ot]}번째, eligible max={eligible_counts.get(ot, 0)})")
    if len(trimmed_intents) < len(intents):
        logger.info(f"[placement] intent 수량 트리밍: {len(intents)} → {len(trimmed_intents)}")
    intents = trimmed_intents

    # ── 정렬: _PRIORITY_SCORE + BRAND_BONUS + STRUCTURAL_ANCHOR_BOOST ──
    # S-8g-2: brand +20 가중 (공간 위계 파괴 안 함)
    # S-8f v2 (2026-04-22): 공간 뼈대(partition) + 앵커(photo) 는 절대 최상위 +1000 가중.
    #   문제: display_table(priority 90 + brand 20 = 110) 이 photo_wall(85+20=105) 을
    #   역전하는 맹점 → photo_wall 이 중앙 아일랜드 기물에 밀려 drop (19:01 실측 1회).
    #   해결: structural anchor 는 도면 뼈대 역할이라 반드시 먼저 안착해야.
    #   partition(98+1000=1098) ≫ photo(85+1000=1085) ≫ display(110) ≫ 기타.
    # 2026-04-28 fix: counter 추가. counter 는 상거래 공간의 존립 근거(POS infrastructure).
    #   counter 가 photo_wall 보다 먼저 배치돼야 빈 매장에서 자리 선점 → 60㎡ 도면에서
    #   다른 객체에 자리 뺏겨 drop 되는 회귀 차단. 평가 근거: reports/AD/2026-04-28_counter_drop_fix_options.md
    #   counter(95+1000=1095) > photo(85+1000=1085) > display(110) > 기타.
    from app.nodes_small.object_selection import BRAND_BONUS, _PRIORITY_SCORE
    STRUCTURAL_ANCHOR_BOOST = 1000
    _STRUCTURAL_ANCHORS = {"partition_wall_I", "partition_wall_L", "photo_wall", "photo_island", "counter"}
    mandatory_types = {o["object_type"] for o in eligible if o.get("is_mandatory")}
    sorted_intents = sorted(
        intents,
        key=lambda x: (
            _PRIORITY_SCORE.get(x["object_type"], 40)
                + (BRAND_BONUS if x["object_type"] in mandatory_types else 0)
                + (STRUCTURAL_ANCHOR_BOOST if x["object_type"] in _STRUCTURAL_ANCHORS else 0),
            -(x.get("priority") or 99),
        ),
        reverse=True
    )
    if mandatory_types:
        logger.info(f"[placement] 브랜드 필수 기물 (+{BRAND_BONUS} bonus): {mandatory_types}")

    logger.info(f"[placement] 시작: {len(sorted_intents)} intents, "
                f"{len(reference_points)} ref_points, max_footprint={max_footprint:.0f}mm², clearspace={clearspace}mm")

    # ── ref_point별 거부 사유 추적 (디버그 덤프용) ──
    # 구조: {rp_id: [{obj_type, reason, stage}]} — 한 ref_point가 여러 기물에 대해 거부될 수 있음
    rp_reject_tracker: dict[str, list[dict]] = {}
    # 성공 배치: {rp_id: obj_type}
    rp_success_tracker: dict[str, str] = {}

    for intent in sorted_intents:
        # 1-2 (#520 후속): manual_label 기반 1:1 매칭 우선. pool 소진 시 obj_map 으로 fallback.
        # pool 매칭 = 같은 object_type 안 manual_label 보존. fallback = backward-compat (단일 인스턴스 / 보충 obj 등).
        obj = _consume_eligible(intent["object_type"], intent.get("manual_label"))
        if not obj:
            obj = obj_map.get(intent["object_type"])
        if not obj:
            failed.append({"object_type": intent["object_type"], "reason": "eligible에 없음"})
            logger.info(f"[placement] {intent['object_type']}: SKIP — eligible에 없음")
            continue

        zone_label = intent.get("zone_label", "mid_zone")
        direction = intent.get("direction", "wall_facing")
        # flush 기물은 LLM이 뭐라 하든 wall_facing 강제 — 벽에 붙는 기물이 중앙에 올 수 없음
        if obj.get("wall_attachment") == "flush" and direction != "wall_facing":
            logger.info(f"[placement] {obj['object_type']}: wall_attachment=flush → direction '{direction}' → 'wall_facing' 강제")
            direction = "wall_facing"
        alignment = intent.get("alignment", "parallel")
        ref_point_id = intent.get("ref_point_id")

        # ── ref_point 후보 구성: join 대상 면 → 지정 → 같은 zone → 인접 zone ──
        rp_candidates = []

        # join 대상(가벽 등)이 이미 배치되어 있으면, 그 면 ref_point를 최우선 탐색
        # join_with 직접 지정 또는 pair_rules에서 가벽과 join 관계인 기물
        join_with = intent.get("join_with")
        has_partition_join = any(
            (r["object_a"].startswith("partition_wall") and r["object_b"] == obj["object_type"] and r["relation"] == "join")
            or (r["object_b"].startswith("partition_wall") and r["object_a"] == obj["object_type"] and r["relation"] == "join")
            for r in pair_rules
        )
        if join_with or has_partition_join:
            partition_face_rps = [rp for rp in reference_points
                                 if rp.get("is_partition") and not rp.get("_is_blocked")]
            if partition_face_rps:
                rp_candidates.extend(partition_face_rps)
                logger.info(f"[placement] {obj['object_type']}: 가벽 면 ref_point {len(partition_face_rps)}개 우선 탐색 (join_with={join_with}, pair_join={has_partition_join})")

        if ref_point_id and ref_point_id in ref_point_map:
            rp = ref_point_map[ref_point_id]
            if not rp.get("_is_blocked") and rp not in rp_candidates:
                rp_candidates.append(rp)

        # 같은 zone의 다른 ref_point (walk_mm 순 정렬) — _is_blocked 제외
        same_zone = [rp for rp in reference_points
                     if rp.get("zone_label") == zone_label and rp["id"] != ref_point_id
                     and not rp.get("_is_blocked") and rp not in rp_candidates]
        same_zone.sort(key=lambda rp: rp.get("walk_mm", 0))
        rp_candidates.extend(same_zone)

        # 인접 zone까지 확대 — _is_blocked 제외
        for adj_zone in _ZONE_ADJACENCY.get(zone_label, []):
            adj_rps = [rp for rp in reference_points
                       if rp.get("zone_label") == adj_zone and rp not in rp_candidates
                       and not rp.get("_is_blocked")]
            adj_rps.sort(key=lambda rp: rp.get("walk_mm", 0))
            rp_candidates.extend(adj_rps)

        # ── counter/pos_counter: 벽 끝(코너) 우선 + 분전반 근접 정렬 ──
        if obj["object_type"] in ("counter", "pos_counter"):
            # 벽 끝 우선: wall_length_mm 대비 벽 중심에서 먼 ref_point 우선
            # → 동선 끝에서 자연스럽게 결제하는 배치
            rp_candidates.sort(
                key=lambda rp: abs(rp.get("wall_length_mm", 0) / 2) if rp.get("wall_length_mm") else 0,
                reverse=False,  # wall_length 짧은 벽(코너) 우선
            )

        # ── 2026-04-29 raycasting Shadow Mode: max_front_clearance_mm 큰 ref_point 우선 ──
        # 객체 의 총 inward 점유 = depth + front_clearance. 이 값 이상의 max_clearance
        # ref_point 가 fit 잘 됨. hard reject 안 함 (fallback step-down 호환) — 정렬 key 만.
        # ref_point 에 max_front_clearance_mm 없으면 (Phase 2 가벽 face / 누락) 큰 값 (5000) 으로 처리.
        _obj_extent = obj.get("depth_mm", 0) + (
            (scaled_clearances or {}).get(obj["object_type"], {}).get("front", 0)
        )
        if _obj_extent > 0 and rp_candidates:
            rp_candidates.sort(
                key=lambda rp: -(rp.get("max_front_clearance_mm", 5000)),  # 큰 값 먼저 (sort 는 작은 게 앞)
            )

        electric_panels_mm = state.get("electric_panels_mm") or []
        if obj["object_type"] in ("counter", "pos_counter", "kiosk") and electric_panels_mm and venue_rules["mep_power_constraint"]:
            def _panel_distance(rp):
                rx, ry = rp["coord"]
                return min(math.hypot(rx - px, ry - py) for px, py in electric_panels_mm)
            # 분전반 3000mm 이내 → 최우선, 나머지는 기존 순서 유지
            near = [rp for rp in rp_candidates if _panel_distance(rp) <= MEP_POWER_PROXIMITY_MM]
            far = [rp for rp in rp_candidates if _panel_distance(rp) > MEP_POWER_PROXIMITY_MM]
            near.sort(key=_panel_distance)
            rp_candidates = near + far

        logger.info(f"[placement] {obj['object_type']} ({obj['width_mm']}x{obj['depth_mm']}mm) → "
                    f"ref={ref_point_id}, zone={zone_label}, dir={direction}, candidates={len(rp_candidates)}")

        # center/freestanding 상한 체크 — 소형 매장 통로 소멸 방지
        is_center_dir = direction in ("center", "freestanding")
        if is_center_dir and center_placement_count >= MAX_CENTER_PLACEMENTS:
            logger.info(f"[placement] {obj['object_type']}: center 상한 도달 ({MAX_CENTER_PLACEMENTS}개), 스킵")
            failed.append({"object_type": obj["object_type"], "reason": f"center 상한 {MAX_CENTER_PLACEMENTS}개 초과"})
            continue

        placed = False
        reject_reasons = {}  # 사유별 카운트
        for rp in rp_candidates:
            # flush 기물은 벽 ref_point만 허용 — center/interior에서 1단계 시도 차단
            if obj.get("wall_attachment") == "flush":
                rp_id = rp.get("id", "")
                if "center" in rp_id or "interior" in rp_id:
                    continue
            # ── 1단계: ref_point 좌표 직접 시도 ──
            rp_slot = _ref_point_to_slot(rp)
            rp_slot["_floor_poly"] = usable_poly
            rp_slot["_entrance_mm"] = state.get("entrance_mm")
            result = calculate_position(rp_slot, obj, direction, alignment, usable_poly, structural_dead_zones=structural_dz)
            reason = _validate_placement(result, usable_poly, static_cache, placed_polygons, clearspace,
                                        obj_type=obj["object_type"], join_with=intent.get("join_with"),
                                        pair_rules=pair_rules,
                                        corridor_graph=corridor_graph, corridor_nodes=corridor_nodes,
                                        entrance_node=entrance_node, slots=slots,
                                        main_artery=main_artery, entrance_buffer=entrance_buffer,
                                        zone_label=rp.get("zone_label") or zone_label,
                                        height_mm=obj.get("height_mm", 0),
                                        direction=direction, rp_label=rp.get("label", ""), dynamic_gap_mm=dynamic_gap_mm,
                                        sprinklers_mm=state.get("sprinklers_mm") or [],
                                        venue_rules=venue_rules,
                                        brand_clearances=brand_clearances,
                                        scaled_clearances=scaled_clearances,
                                        all_entrances_mm=state.get("all_entrances_mm") or [],
                                        is_partition_attached=bool(rp.get("is_partition")))
            if reason != "ok":
                logger.debug(f"    [reject] {obj['object_type']} @ {rp['id']}: {reason}")
                # 사유별 카운트
                short = reason.split("(")[0].strip()
                reject_reasons[short] = reject_reasons.get(short, 0) + 1
                # ref_point별 거부 사유 기록
                rp_reject_tracker.setdefault(rp["id"], []).append({
                    "obj_type": obj["object_type"], "reason": reason, "stage": "ref_point",
                })
            if reason == "ok":
                footprint = obj["width_mm"] * obj["depth_mm"]
                if cumulative_footprint + footprint > max_footprint:
                    logger.info(f"  [reject] {rp['id']}: density limit")
                    rp_reject_tracker.setdefault(rp["id"], []).append({
                        "obj_type": obj["object_type"], "reason": "density limit", "stage": "ref_point",
                    })
                    continue
                cumulative_footprint += footprint
                entry = _build_entry(result, rp["id"], rp.get("zone_label") or zone_label,
                                     direction, intent, obj)
                entry["is_partition_face"] = bool(rp.get("is_partition"))
                entry["candidates_count"] = len(rp_candidates)
                placed_polygons.append(entry)
                rp_success_tracker[rp["id"]] = obj["object_type"]
                logger.info(f"[placement] 배치: {obj['object_type']} @ ({entry['center_x_mm']},{entry['center_y_mm']}) rot={entry['rotation_deg']} fv={entry.get('front_vec')} slot={rp['id']} partition_face={entry['is_partition_face']}")
                log.append(f"{intent['object_type']} → {rp['id']} (ref_point{', partition_face' if entry['is_partition_face'] else ''})")
                placed = True
                if is_center_dir:
                    center_placement_count += 1
                break

            # ── 2단계: ref_point 주변 slot 순회 (해상도 탐색) ──
            radius = _get_search_radius(rp)
            nearby = _find_nearby_slots(rp, slots, radius)
            slot_placed = False
            for slot_key, slot in nearby:
                # flush 기물은 벽 slot만 허용 — center/interior에 밀리는 것 방지
                if obj.get("wall_attachment") == "flush" and ("center" in slot_key or "interior" in slot_key):
                    continue
                slot["_floor_poly"] = usable_poly
                slot["_entrance_mm"] = state.get("entrance_mm")
                result = calculate_position(slot, obj, direction, alignment, usable_poly, structural_dead_zones=structural_dz)
                reason = _validate_placement(result, usable_poly, static_cache, placed_polygons, clearspace,
                                            obj_type=obj["object_type"], join_with=intent.get("join_with"),
                                            pair_rules=pair_rules,
                                            corridor_graph=corridor_graph, corridor_nodes=corridor_nodes,
                                            entrance_node=entrance_node, slots=slots,
                                            main_artery=main_artery, entrance_buffer=entrance_buffer,
                                            zone_label=rp.get("zone_label") or zone_label,
                                            height_mm=obj.get("height_mm", 0),
                                            direction=direction, rp_label=slot.get("label", "") or rp.get("label", ""), dynamic_gap_mm=dynamic_gap_mm,
                                            sprinklers_mm=state.get("sprinklers_mm") or [],
                                            venue_rules=venue_rules,
                                            brand_clearances=brand_clearances,
                                            scaled_clearances=scaled_clearances,
                                            all_entrances_mm=state.get("all_entrances_mm") or [],
                                            is_partition_attached=bool(rp.get("is_partition")))
                if reason != "ok":
                    logger.debug(f"      [slot reject] {obj['object_type']} @ {slot_key}: {reason}")
                    short = reason.split("(")[0].strip()
                    reject_reasons[short] = reject_reasons.get(short, 0) + 1
                    rp_reject_tracker.setdefault(slot_key, []).append({
                        "obj_type": obj["object_type"], "reason": reason, "stage": "slot",
                    })
                if reason == "ok":
                    footprint = obj["width_mm"] * obj["depth_mm"]
                    if cumulative_footprint + footprint > max_footprint:
                        continue
                    cumulative_footprint += footprint
                    entry = _build_entry(result, slot_key, rp.get("zone_label") or zone_label,
                                         direction, intent, obj)
                    entry["is_partition_face"] = bool(rp.get("is_partition"))
                    entry["candidates_count"] = len(rp_candidates)
                    placed_polygons.append(entry)
                    rp_success_tracker[slot_key] = obj["object_type"]
                    logger.info(f"[placement] 배치: {obj['object_type']} @ ({entry['center_x_mm']},{entry['center_y_mm']}) rot={entry['rotation_deg']} fv={entry.get('front_vec')} slot={slot_key} partition_face={entry['is_partition_face']}")
                    log.append(f"{intent['object_type']} → {slot_key} (slot near {rp['id']}{', partition_face' if entry['is_partition_face'] else ''})")
                    slot_placed = True
                    if is_center_dir:
                        center_placement_count += 1
                    break
            if slot_placed:
                placed = True
                break
            else:
                logger.info(f"  [reject] {rp['id']}: ref_point + 주변 slot {len(nearby)}개 전부 실패")

        # flush 기물이 벽 아닌 곳에 착지했으면 강제 취소
        if placed and obj.get("wall_attachment") == "flush":
            last_entry = placed_polygons[-1]
            sk = last_entry.get("anchor_key", "")
            if "center" in sk or "interior" in sk:
                logger.info(f"  [FORCE REJECT] {obj['object_type']}: flush인데 {sk}에 착지 → 배치 취소")
                placed_polygons.pop()
                placed = False

        if not placed:
            top_reasons = sorted(reject_reasons.items(), key=lambda x: -x[1])[:5]
            reasons_str = ", ".join(f"{r}({c})" for r, c in top_reasons)
            logger.info(f"  [FAIL] {intent['object_type']}: 전부 실패 — {reasons_str}")
            failed.append({"object_type": intent["object_type"], "reason": f"전부 실패: {reasons_str}"})
            # 1-3 (#523 후속): sub_graph_reasons dump — agent 가 왜 못놨는지 사유 가시화
            try:
                from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
                top_rp_rejects = []
                for rp_id, rj_list in list(rp_reject_tracker.items())[:5]:
                    matching = [r for r in rj_list if r.get("obj_type") == intent.get("object_type")]
                    if matching:
                        top_rp_rejects.append({
                            "rp": rp_id,
                            "reason": matching[0].get("reason", "?")[:120],
                            "stage": matching[0].get("stage", "?"),
                        })
                dump_agent_reason(state, node="placement", decision="fail",
                                  reason=f"{intent.get('object_type', '?')} 전부 실패: {reasons_str[:200]}",
                                  context={
                                      "object_type": intent.get("object_type"),
                                      "manual_label": intent.get("manual_label"),
                                      "intent_zone": intent.get("zone_label"),
                                      "intent_ref": intent.get("ref_point_id"),
                                      "intent_direction": intent.get("direction"),
                                      "top_reject_reasons": [(r, c) for r, c in top_reasons],
                                      "candidate_rp_count": len(rp_candidates) if 'rp_candidates' in locals() else None,
                                      "rp_reject_samples": top_rp_rejects,
                                  })
            except Exception as _e:
                logger.warning(f"[placement] reason_dump 실패 — skip: {_e}")

    # 1-3 (#523 후속): placement 노드 전체 요약 — placed/failed 갯수 + 사유 분포
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        from collections import Counter
        reason_counter = Counter()
        for f in failed:
            reason_counter[f.get("reason", "?")[:60]] += 1
        dump_agent_reason(state, node="placement",
                          decision="success" if not failed else "partial",
                          reason=f"placed={len(placed_polygons)} failed={len(failed)}",
                          context={
                              "placed_types": [p.get("object_type") for p in placed_polygons],
                              "failed_types": [f.get("object_type") for f in failed],
                              "failure_reason_distribution": dict(reason_counter),
                          })
    except Exception as _e:
        logger.warning(f"[placement] summary reason_dump 실패 — skip: {_e}")

    logger.info(f"[placement] {len(placed_polygons)} placed, {len(failed)} failed")

    # ── 시각화용 JSON 덤프 ──
    # 정확도 보장 구조:
    #   success 마커 = placed_polygons 직접 순회 → 실제 배치 center 좌표 사용 (가벽 포함)
    #   rejected 마커 = rp_reject_tracker → slot_key 시작점 좌표 사용
    try:
        import os as _os, json as _json
        from datetime import datetime as _dt
        _dd = _os.path.join(_os.path.dirname(__file__), "..", "..", "debug_logs", _dt.now().strftime("%Y-%m-%d"))
        _os.makedirs(_dd, exist_ok=True)
        ref_points_meta = state.get("reference_points") or []
        slots_meta = state.get("slots") or {}

        # 좌표 + 타입 + 사이즈 룩업 (rejected/untried용)
        # ref_point size = search_radius (실제 탐색 반경)
        # slot size = 250mm (grid step 500mm의 절반)
        coord_map: dict[str, list[float]] = {}
        zone_map: dict[str, str] = {}
        type_map: dict[str, str] = {}
        size_map: dict[str, float] = {}  # 마커 반경(mm)
        for rp in ref_points_meta:
            coord_map[rp["id"]] = list(rp["coord"])
            zone_map[rp["id"]] = rp.get("zone_label") or ""
            type_map[rp["id"]] = "ref_point"
            size_map[rp["id"]] = _get_search_radius(rp)  # 1000/2000/3000mm
        for slot_key, slot in slots_meta.items():
            if "coord" in slot:
                coord_map[slot_key] = list(slot["coord"])
            elif "x_mm" in slot and "y_mm" in slot:
                coord_map[slot_key] = [slot["x_mm"], slot["y_mm"]]
            zone_map.setdefault(slot_key, slot.get("zone_label") or "")
            type_map.setdefault(slot_key, "slot")
            size_map.setdefault(slot_key, 250.0)  # grid step 500mm / 2

        rp_status = []

        # ── 1. success 마커 — placed_polygons 직접 순회 (실제 좌표) ──
        # placed_polygons에는 partition_wall(전처리) + locked_objects + 본 배치가 모두 포함됨
        for idx, p in enumerate(placed_polygons):
            anchor_key = p.get("anchor_key", f"placed_{idx}")
            rp_type = type_map.get(anchor_key, "ref_point" if anchor_key.startswith(("wall_", "iwall_", "center_")) else "slot")
            rp_status.append({
                "id": f"placed_{idx}_{anchor_key}",  # 중복 anchor_key 허용 위해 인덱스 prefix
                "coord": [round(p.get("center_x_mm", 0), 1), round(p.get("center_y_mm", 0), 1)],
                "zone_label": p.get("zone_label", ""),
                "type": rp_type,
                "size_mm": size_map.get(anchor_key, 250.0 if rp_type == "slot" else 2000.0),
                "status": "success",
                "placed_obj": p.get("object_type", ""),
                "anchor_key": anchor_key,
                "rejects": [],
            })

        # ── 2. rejected 마커 — 트래커의 거부된 위치 (성공한 곳은 제외) ──
        success_keys = {p.get("anchor_key") for p in placed_polygons}
        for rp_id, rejects in rp_reject_tracker.items():
            if rp_id in success_keys:
                continue  # 같은 slot에 성공한 게 있으면 거부 마커 표시 안 함
            if rp_id not in coord_map:
                continue
            rp_status.append({
                "id": rp_id,
                "coord": coord_map[rp_id],
                "zone_label": zone_map.get(rp_id, ""),
                "type": type_map.get(rp_id, "slot"),
                "size_mm": size_map.get(rp_id, 250.0),
                "status": "rejected",
                "placed_obj": None,
                "rejects": rejects,
            })

        # ── 3. untried 마커 — 시도조차 안 된 ref_point/slot ──
        tried_keys = set(rp_success_tracker.keys()) | set(rp_reject_tracker.keys()) | success_keys
        for rp_id in coord_map:
            if rp_id in tried_keys:
                continue
            rp_status.append({
                "id": rp_id,
                "coord": coord_map[rp_id],
                "zone_label": zone_map.get(rp_id, ""),
                "type": type_map.get(rp_id, "slot"),
                "size_mm": size_map.get(rp_id, 250.0),
                "status": "untried",
                "placed_obj": None,
                "rejects": [],
            })

        with open(_os.path.join(_dd, "ref_point_status.json"), "w", encoding="utf-8") as _f:
            _json.dump({
                "total_points": len(rp_status),
                "success_count": sum(1 for r in rp_status if r["status"] == "success"),
                "rejected_count": sum(1 for r in rp_status if r["status"] == "rejected"),
                "untried_count": sum(1 for r in rp_status if r["status"] == "untried"),
                "ref_points": rp_status,
            }, _f, ensure_ascii=False, indent=2)
    except Exception as _e:
        logger.warning(f"[placement] ref_point_status.json 덤프 실패: {_e}")

    return {
        "placed_objects": [serialize_placement(p) for p in placed_polygons],
        "placed_raw": placed_polygons,
        "failed_objects": failed,
        "placement_log": log,
        "ref_point_status": rp_status if 'rp_status' in locals() else [],
        "scaled_clearances": scaled_clearances,
    }






def _get_clearspace(brand_data):
    cs = brand_data.get("brand", {}).get("clearspace_mm", {})
    if isinstance(cs, dict):
        return cs.get("value", DEFAULT_CLEARSPACE_MM)
    return DEFAULT_CLEARSPACE_MM


def _generate_partition_wall_linestrings(
    placed_entry: dict,
    usable_poly,
    structural_dead_zones: list = None,
) -> list:
    """가벽 배치 결과 → 양면 LineString 생성 (Virtual Wall).

    가벽의 긴 면(width)을 LineString으로 추출하여 inner_wall_linestrings에 추가.
    ref_point_gen이 이 LineString에서 벽면 ref_point를 자동 생성.
    650mm 허공 ref_point hack 폐기 → 기존 벽면과 동일한 처리.
    dead zone 안에 있는 면은 스킵 (결정 2, 4/18).
    """
    from shapely.geometry import LineString

    cx = placed_entry["center_x_mm"]
    cy = placed_entry["center_y_mm"]
    angle_deg = placed_entry.get("rotation_deg", 0)
    angle_rad = math.radians(angle_deg)
    w = placed_entry["width_mm"]
    d = placed_entry.get("depth_mm", 150)

    # width 방향 벡터
    wx = math.cos(angle_rad) * w / 2
    wy = math.sin(angle_rad) * w / 2

    # depth 방향 벡터 (법선)
    dx = -math.sin(angle_rad) * d / 2
    dy = math.cos(angle_rad) * d / 2

    linestrings = []
    for sign, label in [(1, "앞면"), (-1, "뒷면")]:
        # 가벽 면의 양 끝점
        p1 = (cx - wx + dx * sign, cy - wy + dy * sign)
        p2 = (cx + wx + dx * sign, cy + wy + dy * sign)
        ls = LineString([p1, p2])

        # usable_poly 안에 있는 부분만
        if usable_poly:
            clipped = usable_poly.intersection(ls)
            if clipped.is_empty or clipped.length < 100:
                continue
            if clipped.geom_type == "MultiLineString":
                clipped = max(clipped.geoms, key=lambda g: g.length)
            if clipped.geom_type == "LineString":
                ls = clipped

        # dead zone 안이면 스킵 — 이 면에 기물 배치해봤자 충돌로 거부됨
        if structural_dead_zones:
            mid = ls.interpolate(0.5, normalized=True)
            skip = False
            for dz in structural_dead_zones:
                if dz["poly"].contains(mid):
                    logger.info(f"[placement] 가벽 Virtual Wall 스킵: {placed_entry['anchor_key']} ({label}) — {dz['type']} dead zone 안")
                    skip = True
                    break
            if skip:
                continue

        linestrings.append(ls)
        logger.info(f"[placement] 가벽 Virtual Wall 생성: {placed_entry['anchor_key']} ({label}, {ls.length:.0f}mm)")

    return linestrings


# ── VMD 절대 차단 (헌법 — 프롬프트가 아닌 코드로 강제) ─────────────────

def _vmd_blocking_check(obj_type: str, zone_label: str, height_mm: float,
                        direction: str, rp_label: str,
                        venue_rules: dict | None = None) -> str | None:
    """VMD 헌법 위반 시 배치 절대 차단. 반환값이 있으면 거부 사유.

    - 벽면 선반이 중앙에 표류하는 현상 차단
    - 계산대가 입구를 막는 것 차단
    - R2: 계산대는 deep_zone만
    - R4: entrance_zone 중앙에 높이 초과 금지 (venue_rules로 기준값 오버라이드)
    """
    vr = venue_rules or {}

    # 1. 벽면 선반 표류 방지
    if obj_type in ("shelf_wall", "shelf_standard"):
        if direction == "center" or "center" in (rp_label or ""):
            return f"VMD 무관용 차단: {obj_type}이 중앙 공간(center)에 배치되었습니다."

    # 2. 입구 차단 방지 — 단 wall_facing 은 허용 (벽 부착 시 입구 중앙 차단 X)
    # 1-3 후속 (#535 후속, 5-8): drop 회피 우선. wall_facing counter 는 입구 막지 않음.
    # 회귀 (5-8 13:22 라이브): 증정품 counter step-down 시 entrance ref 시도 → 차단 → drop.
    # 진규님 의도: deep/mid 강제하다 drop 되면 entrance 까지 허용 (drop 보다 시퀀스 위반 나음).
    if obj_type in ("counter", "pos_counter") and zone_label == "entrance_zone" and direction != "wall_facing":
        return f"VMD 무관용 차단: 계산대({obj_type})가 입구(entrance_zone) 중앙을 차단했습니다."

    # R2: 계산대는 deep_zone + mid_zone + entrance(wall_facing) 허용 (drop 회피)
    # entrance_zone counter 는 wall_facing 일 때만 허용 (위 line 에서 center 차단됨)
    if obj_type in ("counter", "pos_counter") and zone_label not in ("deep_zone", "mid_zone", "entrance_zone"):
        return f"VMD R2 위반: {obj_type}은 deep/mid/entrance만 허용 (현재 {zone_label})"

    # R4: entrance_zone에 높이 초과 기물 차단 (venue_rules 기준값 우선)
    # 단, wall_facing 방향은 면제 — 벽에 밀착된 키 큰 기물은 시야 차단 아님
    max_h = vr.get("entrance_max_height_mm", ENTRANCE_MAX_HEIGHT_MM)
    if zone_label == "entrance_zone" and (height_mm or 0) > max_h and direction != "wall_facing":
        return f"VMD R4 위반: entrance_zone에 {height_mm}mm 기물 배치 금지 (가슴 높이 {max_h}mm 초과)"

    return None


def _build_entry(result, anchor_key, zone_label, direction, intent, obj):
    """배치 성공 시 entry dict 생성."""
    return {
        **result,
        "anchor_key": anchor_key,
        "zone_label": zone_label,
        "direction": direction,
        "placed_because": intent.get("placed_because", ""),
        "height_mm": obj.get("height_mm", DEFAULT_HEIGHT_MM),
        "category": obj.get("category", ""),
        # b-3: raw 명명 보존 — frontend (LayoutObject.label) 가 fallback 으로 object_type 사용.
        "label": obj.get("label") or obj.get("name") or obj.get("object_type", ""),
        # 1-2 (#520 후속): 매뉴얼 명시 의도 라벨 보존 — intent 우선 (LLM 명시), fallback eligible obj.
        # placed_objects 가 라벨 들고 있어야 design retry / 응답 직렬화 / debug trace 에서 추적 가능.
        "manual_label": intent.get("manual_label") or obj.get("manual_label"),
        "wall_attachment": obj.get("wall_attachment", "free"),
        "front_edge": obj.get("front_edge", "width"),
        "join_with": intent.get("join_with"),
        # PR #226 Phase 2 복원: ref 이미지 추적성 — design.py 가 정규화한 식별자 리스트
        "inspired_by_images": intent.get("inspired_by_images") or [],
        # PR #226 Phase 2.1 복원: 인용된 인사이트 ID 리스트 (L0/P0/F0/D0)
        "inspired_by_insights": intent.get("inspired_by_insights") or [],
    }


def _get_search_radius(rp: dict) -> float:
    """ref_point의 wall_length_mm 기반 동적 탐색 반경.

    넓은 벽 → 넓게 탐색, 좁은 벽 → 좁게 (LLM 의도 보존).
    design.py의 벽 크기 판정과 동일 기준.
    """
    wall_len = rp.get("wall_length_mm", 0)
    if wall_len > WALL_WIDE_THRESHOLD_MM:
        return SEARCH_RADIUS_WIDE_MM
    elif wall_len > WALL_NORMAL_THRESHOLD_MM:
        return SEARCH_RADIUS_NORMAL_MM
    elif wall_len > 0:
        return SEARCH_RADIUS_NARROW_MM
    else:
        return SEARCH_RADIUS_NORMAL_MM  # 중앙 ref_point


def _find_nearby_slots(rp: dict, slots: dict, radius_mm: float) -> list:
    """ref_point 주변 radius_mm 이내의 slot을 거리순으로 반환."""
    coord = rp.get("coord")
    if not coord:
        return []
    rx, ry = coord
    nearby = []
    for key, slot in slots.items():
        dist = math.hypot(slot["x_mm"] - rx, slot["y_mm"] - ry)
        if dist <= radius_mm:
            nearby.append((key, slot, dist))
    nearby.sort(key=lambda x: x[2])
    return [(key, slot) for key, slot, _ in nearby]


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


def _validate_placement(
    result, usable_poly, static_cache, placed_polygons, clearspace,
    obj_type: str = "", join_with: str = None, pair_rules: list = None,
    corridor_graph=None, corridor_nodes=None, entrance_node=None,
    slots=None, main_artery=None, entrance_buffer=None,
    zone_label: str = "", height_mm: float = 0,
    strict: bool = True, corridor_relax_mm: int = 0,
    direction: str = "", rp_label: str = "", dynamic_gap_mm: int = DEFAULT_GAP_MM,
    sprinklers_mm: list = None,
    venue_rules: dict = None,
    brand_clearances: dict = None,
    scaled_clearances: dict = None,
    all_entrances_mm: list = None,
    is_partition_attached: bool = False,
) -> str:
    """검증 + 실패 사유 반환. 'ok'면 성공.

    pair_rules 기반 충돌/간격 검사:
    - join 관계: 겹침 허용 (overlap_margin_mm 이내) + 통로 검사 스킵
    - separate 관계: min_gap_mm 이상 간격 강제
    - 기본: 겹침 불가 + 보조동선 450mm 간격
    """
    bbox = result["bbox_polygon"]

    # 0. VMD 절대 차단 (헌법 — LLM 환각 방어)
    blocking = _vmd_blocking_check(obj_type, zone_label, height_mm, direction, rp_label, venue_rules=venue_rules)
    if blocking:
        return blocking

    # 0.5. 스프링클러 높이 기반 차단 — 기물 상단이 헤드 450mm 이내에 도달할 때만 차단
    # 천장고(3000) - 이격(450) = 2550mm 이상 기물만 검사
    ceiling = DEFAULT_CEILING_HEIGHT_MM
    sprinkler_threshold = ceiling - SPRINKLER_CLEARANCE_MM
    if (height_mm or 0) >= sprinkler_threshold and sprinklers_mm:
        cx = (bbox.bounds[0] + bbox.bounds[2]) / 2
        cy = (bbox.bounds[1] + bbox.bounds[3]) / 2
        for sp in sprinklers_mm:
            dist = math.hypot(cx - sp[0], cy - sp[1])
            if dist < SPRINKLER_CLEARANCE_MM:
                return f"sprinkler 살수 차단 (높이 {height_mm}mm >= {sprinkler_threshold}mm, 헤드 거리 {dist:.0f}mm < {SPRINKLER_CLEARANCE_MM}mm)"
    # 분전반: 바닥~천장 수직 기둥. dead zone(static_cache)에서 무조건 차단. 별도 검사 불필요.

    # 1. floor 99.5%
    if bbox.area > 0:
        overlap = usable_poly.intersection(bbox).area
        if overlap / bbox.area < FLOOR_OVERLAP_MIN:
            return f"floor 이탈 ({overlap/bbox.area*100:.0f}%)"

    # 1.5. 비상구 2단계 (verify.py 에서 이전 — verify 폐기)
    # Step 1: 비상구 1200mm 이내 차단 / Step 2: 비상구 전면 복도 (1200x600) 차단
    if all_entrances_mm:
        from shapely.geometry import Point as _Point, box as _box
        for ent in all_entrances_mm:
            if ent.get("type") != "EMERGENCY_EXIT":
                continue
            ex, ey = ent["coord"]
            ent_pt = _Point(ex, ey)
            dist = ent_pt.distance(bbox)
            if dist < 1200:  # EMERGENCY_EXIT_MIN_DIST_MM
                return f"비상구 인접 차단 ({dist:.0f}mm < 1200mm)"
            corridor_rect = _box(ex - 1200, ey - 600, ex + 1200, ey + 600)
            if bbox.intersects(corridor_rect) and dist < 2400:
                return "비상구 전면 복도 차단 (1.2m × 0.6m)"

    # 2. static cache (dead_zone + main_artery 600mm + entrance)
    if static_cache and bbox.intersects(static_cache):
        return "static cache 충돌 (dead_zone/artery/entrance)"

    # 3. 기배치 충돌 + 4. 통로 간격 (pair_rules 기반)
    for existing in placed_polygons:
        existing_type = existing.get("object_type", "")
        pair = _find_pair_rule(obj_type, existing_type, join_with, pair_rules or [])
        intersection_area = bbox.intersection(existing["bbox_polygon"]).area

        if pair and pair["relation"] == "join":
            # join: overlap_margin_mm가 허용하는 깊이까지만 겹침 허용.
            # [중요/회귀방지] 2026-04-20: margin=0은 "겹침 완전 금지(edge-to-edge 인접만)"로 해석.
            # 이전 구현은 margin=0을 20% 면적 허용 fallback으로 떨어뜨려서 shelf_wall 2개가
            # 200mm(16.7%) 겹쳐 "짝짓기" 배치되는 버그 발생. 20%는 "적당히 허용" 은닉 규칙이라
            # 제거. margin>0을 명시할 때만 해당 깊이까지 허용. 8개 join 쌍 전부 margin=0이므로
            # 모두 "정확한 인접"으로 해석됨.
            # 참고: reports/AD/2026-04-20_shelf_wall_pair_overlap_fix.md
            if intersection_area > 0:
                margin = pair.get("overlap_margin_mm", 0)
                ix0, iy0, ix1, iy1 = bbox.intersection(existing["bbox_polygon"]).bounds
                overlap_depth = min(ix1 - ix0, iy1 - iy0)
                if margin > 0:
                    if overlap_depth > margin:
                        return f"join 겹침 초과 ({overlap_depth:.0f}mm > {margin}mm, {existing_type})"
                else:
                    # margin == 0 → 완전 금지 (면적 무관, 깊이 1mm라도 거부)
                    return f"join 겹침 금지 (margin=0, {overlap_depth:.0f}mm 겹침, {existing_type})"
            # join이면 통로 검사 스킵
            continue

        elif pair and pair["relation"] == "separate":
            # separate: min_gap_mm 이상 간격 강제
            if intersection_area > 0:
                return f"separate 쌍 겹침 ({obj_type}↔{existing_type})"
            gap = bbox.distance(existing["bbox_polygon"])
            min_gap = pair["min_gap_mm"]
            if gap < min_gap:
                return f"separate 간격 부족 ({gap:.0f}mm < {min_gap}mm, {obj_type}↔{existing_type})"

        else:
            # 기본 보조동선 규칙 적용: 겹침 불가 + 동적 간격(dynamic_gap_mm)
            if intersection_area > 0:
                return f"기배치 충돌 ({existing_type})"
            gap = bbox.distance(existing["bbox_polygon"])
            # strict=False 시 corridor_relax_mm만큼 완화
            effective_gap = max(dynamic_gap_mm - corridor_relax_mm, 0)
            if gap < effective_gap:
                return f"간격 부족 ({gap:.0f}mm < {effective_gap}mm, {existing_type})"

    # 4.5. 전후 이격 (Directional Clearance) — front/back 방향별 최소 이격
    # 조회 우선순위: scaled_clearances (Tier 1-1 면적 비례 + floor 강제)
    #              > brand_clearances (브랜드 매뉴얼 명시값, scaled에서 이미 max(brand,floor) 처리됨)
    #              > DIRECTIONAL_CLEARANCE (기본값, fallback)
    # scaled_clearances가 우선인 이유: 산출 단계에서 brand_override를 이미 흡수하면서 floor 보장.
    from app.vmd_constants import DIRECTIONAL_CLEARANCE

    # A. 새 기물의 전후 이격 체크
    dc = (
        (scaled_clearances or {}).get(obj_type)
        or (brand_clearances or {}).get(obj_type)
        or DIRECTIONAL_CLEARANCE.get(obj_type)
    )
    fv = result.get("front_vec")
    if dc and ((dc.get("front") or 0) > 0 or (dc.get("back") or 0) > 0) and fv:
        cx = (bbox.bounds[0] + bbox.bounds[2]) / 2
        cy = (bbox.bounds[1] + bbox.bounds[3]) / 2
        d = result.get("depth_mm", 0)
        for dir_name, clearance_mm in [("front", dc.get("front") or 0), ("back", dc.get("back") or 0)]:
            if clearance_mm <= 0:
                continue
            # 1-3 후속 (#535 후속): 가벽 면 ref_point 매핑 시 back 이격 무시.
            # 진규님 5-8 의문: "가벽에 obj 붙을 때 이격 X (join_with 같은 개념)".
            # 이유: 가벽 자체가 벽 역할 — back side 가 가벽이면 정상 부착. 이격 강제 시
            # 가벽 옆에 obj 못 박아서 fallback step-down 으로 좌측 외곽 강제 끼워박힘 회귀.
            # front 이격 (고객 응대 영역) 은 유지 — 가벽 부착 obj 의 앞쪽은 보호 필요.
            if is_partition_attached and dir_name == "back":
                continue
            if dir_name == "front":
                dx, dy = fv[0], fv[1]
            else:
                dx, dy = -fv[0], -fv[1]
            probe = Point(cx + dx * (d/2 + clearance_mm/2), cy + dy * (d/2 + clearance_mm/2)).buffer(clearance_mm/2)
            # 기배치 오브젝트 충돌
            for existing in placed_polygons:
                if probe.intersects(existing["bbox_polygon"]):
                    return f"전후 이격 부족 ({dir_name} {clearance_mm}mm, {existing.get('object_type', '')})"
            # 장애물 충돌 — 화장실/계단/기둥/가벽/분전반/소화전/비상구 dead zone
            if static_cache and probe.intersects(static_cache):
                return f"전후 이격 내 장애물 ({dir_name} {clearance_mm}mm, dead zone)"

    # B. 기배치 기물의 전후 이격 역방향 체크 — 새 bbox가 기존 기물의 clearance 영역을 침범하는지
    for existing in placed_polygons:
        ex_type = existing.get("object_type", "")
        ex_dc = (
            (scaled_clearances or {}).get(ex_type)
            or (brand_clearances or {}).get(ex_type)
            or DIRECTIONAL_CLEARANCE.get(ex_type)
        )
        # 2026-05-08: partition_wall_I/L 의 graphic_face='outer' = 포토존 역할 흡수.
        # 그래픽 면 앞쪽은 사람 서서 사진 찍는 자리 → photo_wall 수준 front clearance 적용.
        # 진규님 5-8 명시: "그래픽 있는 면쪽은 포토존의 역할 → clearance 적용. 수치는 포토존만큼".
        # graphic_face='outer' = front_vec 방향이 그래픽 면. 기본 partition clearance (front=0)
        # 무력화하고 photo_wall front (1500mm) 강제 사용.
        if (ex_type.startswith("partition_wall")
                and existing.get("graphic_face") == "outer"):
            ex_dc = DIRECTIONAL_CLEARANCE.get("photo_wall") or ex_dc
        ex_fv = existing.get("front_vec")
        if not ex_dc or not ex_fv:
            continue
        if (ex_dc.get("front") or 0) <= 0 and (ex_dc.get("back") or 0) <= 0:
            continue
        ex_bbox = existing["bbox_polygon"]
        ex_cx = (ex_bbox.bounds[0] + ex_bbox.bounds[2]) / 2
        ex_cy = (ex_bbox.bounds[1] + ex_bbox.bounds[3]) / 2
        ex_d = existing.get("depth_mm", 0)
        for dir_name, clearance_mm in [("front", ex_dc.get("front") or 0), ("back", ex_dc.get("back") or 0)]:
            if clearance_mm <= 0:
                continue
            if dir_name == "front":
                dx, dy = ex_fv[0], ex_fv[1]
            else:
                dx, dy = -ex_fv[0], -ex_fv[1]
            probe = Point(ex_cx + dx * (ex_d/2 + clearance_mm/2), ex_cy + dy * (ex_d/2 + clearance_mm/2)).buffer(clearance_mm/2)
            if probe.intersects(bbox):
                return f"기존 {ex_type}의 {dir_name} {clearance_mm}mm 침범"

    # 5. Choke point — 동선 병목 900mm (타협 불가, strict 무관)
    if _check_choke_point(bbox, placed_polygons, usable_poly, main_artery, entrance_buffer):
        return "동선 병목 (choke point < 900mm)"

    if strict:
        # 6. 접근성 4방향 — 비활성화 (전후 이격 + gap 검사로 대체)
        # if not _is_accessible(bbox, clearspace, usable_poly, static_cache, placed_polygons):
        #     return f"접근성 실패 (clearspace={clearspace}mm)"
        pass

        # 7. Corridor connectivity — 연산 무거움 (fallback 시 생략)
        if corridor_graph and corridor_nodes and entrance_node and slots:
            if not _check_corridor_connectivity(
                corridor_graph, corridor_nodes, entrance_node,
                bbox, slots, placed_polygons,
            ):
                return "통로 차단 (corridor connectivity)"

    return "ok"


def _find_pair_rule(obj_type_a: str, obj_type_b: str, join_with: str, pair_rules: list) -> dict | None:
    """두 오브젝트 타입 간 pair rule 조회.

    1순위: join_with 직접 지정 (Agent 3 출력)
    2순위: pair_rules 테이블에서 매칭 (* 와일드카드 지원)
    """
    # join_with 직접 지정
    if join_with and join_with == obj_type_b:
        return {"relation": "join", "min_gap_mm": 0, "overlap_margin_mm": JOIN_WITH_OVERLAP_MARGIN_MM}

    # pair_rules 테이블 조회
    for rule in pair_rules:
        a, b = rule["object_a"], rule["object_b"]
        if (a == obj_type_a and (b == obj_type_b or b == "*")) or \
           (a == obj_type_b and (b == obj_type_a or b == "*")) or \
           (b == obj_type_a and (a == obj_type_b or a == "*")) or \
           (b == obj_type_b and (a == obj_type_a or a == "*")):
            return rule

    return None


def _can_place(result, usable_poly, static_cache, placed_polygons, clearspace, **kwargs):
    """배치 결과가 유효한지 검증. _validate_placement의 boolean 래퍼."""
    return _validate_placement(result, usable_poly, static_cache, placed_polygons, clearspace, **kwargs) == "ok"


# ── NetworkX 통로 검증 (Rendy corridor_graph + choke point 이식) ──────────

def _init_corridor_graph(usable_poly, dead_zones, entrance_mm):
    """배치 엔진 시작 시 corridor 그래프 초기화.

    walk_mm.py의 _build_corridor_graph와 동일한 500mm 그리드.
    Returns: (graph, nodes_dict, entrance_node) or (None, None, None)
    """
    if not usable_poly:
        return None, None, None

    try:
        from app.nodes_small.walk_mm import _build_corridor_graph, _nearest_node
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
    new_bbox, slots, placed_polygons,
) -> bool:
    """새 bbox 배치 시 entrance → 미배치 slot 경로가 유지되는지 확인.

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

    # 미배치 slot 중 하나라도 도달 가능한지 확인
    from app.nodes_small.walk_mm import _nearest_node
    placed_anchor_keys = {p.get("anchor_key") for p in placed_polygons}
    for slot_key, slot_val in slots.items():
        if slot_key in placed_anchor_keys:
            continue
        if not isinstance(slot_val, dict) or "x_mm" not in slot_val:
            continue
        slot_node = _nearest_node(nodes, (slot_val["x_mm"], slot_val["y_mm"]))
        if slot_node in G and nx.has_path(G, entrance_node, slot_node):
            return True

    return False


def _check_choke_point(new_bbox, placed_polygons, usable_poly, main_artery, entrance_buffer):
    """새 bbox 배치 시 동선 병목 검사.

    1차: 기물 간 절대 최소 간격(600mm) — main_artery 무관, 무조건 적용
    2차: 주동선 교차 시 보조동선 폭 확보 검사

    Returns: True=병목 발생, False=안전
    """
    if not usable_poly:
        return False

    # 1차: 기물 간 절대 최소 간격 — main_artery 존재 여부와 무관
    for existing in placed_polygons:
        ep = existing.get("bbox_polygon")
        if not ep:
            continue
        gap = new_bbox.distance(ep)
        if 0 < gap < MIN_ABSOLUTE_GAP_MM:
            return True

    # 2차: 외벽 근처 입구 병목
    MIN_CORRIDOR_MM = CORRIDOR_HALF_BUFFER_MM * 2  # 600mm
    wall_gap = usable_poly.exterior.distance(new_bbox)
    if 0 < wall_gap < MIN_CORRIDOR_MM:
        if entrance_buffer and new_bbox.intersects(entrance_buffer.buffer(MIN_CORRIDOR_MM)):
            return True

    # 3차: 주동선 교차 병목 (main_artery 있을 때만)
    if main_artery:
        for existing in placed_polygons:
            ep = existing.get("bbox_polygon")
            if not ep:
                continue
            gap = new_bbox.distance(ep)
            if 0 < gap < MIN_CORRIDOR_MM:
                buf_new = new_bbox.buffer(CORRIDOR_HALF_BUFFER_MM)
                buf_old = ep.buffer(CORRIDOR_HALF_BUFFER_MM)
                choke_zone = buf_new.intersection(buf_old)
                if not choke_zone.is_empty and main_artery.intersects(choke_zone):
                    return True

    return False
