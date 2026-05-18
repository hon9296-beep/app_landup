"""
Anti-Pattern Reviewer 룰 catalog — designer LLM 결과 (design_intents) 의 명백한 오답 검출.

#474 도박수 — small 종결 가속용. Phase 1 single small 단독.
설계: reports/AD/2026-05-04_15-21_474_anti_pattern_reviewer_USER.md
worklog: reports/AD/2026-05-04_15-21_474_anti_pattern_reviewer_WORKLOG.md

룰 분류 (27개):
  A. 단일 입구 (5-1 baseline)             AP-001 ~ AP-008  (8)
  A2. structural_constraint (1-3 신규)    AP-009            (1) — ref_point 1:1
  B. 다중 입구 (5-2 #486 흡수)            AP-101 ~ AP-108  (8)
  C. zone 분류 / 동선 정책 (5-2 신규)     AP-201 ~ AP-207  (7)
  D. family_cap / 입구 통과 / manual_label semantic
                                           AP-301 ~ AP-303  (3)

validator_type:
  python  — 좌표 비교 / 거리 측정 (Shapely + ref_point 좌표). 비용 0, 결정적.
  llm     — 모호한 판단 (동선 자연성 / 카테고리 의도). design_reviewer LLM 호출 시 prompt 에 포함.

severity:
  blocking — 위반 시 reviewer reject + designer 재호출 트리거
  warning  — 위반 시 logger.warning, 통과
"""
import logging
import math
from typing import Callable, Optional

from shapely.geometry import Point

logger = logging.getLogger(__name__)


# ── 임계값 (jinkyu 검토 시점에 조정 가능) ────────────────────────────
# 1-3 (#533) 후속 동기화: 입구 감압존 반경은 slot_gen.DECOMPRESSION_RADIUS_MM (single source).
# 진규님 2026-04-22 결정: 소형 (0~50평 미만, 165m² 미만) 1500→900 하향 — 18평 도면에서
# 1500이 deep_zone 절반 잠식. anti_patterns 의 reviewer 검증도 같은 기준 따라가야 함.
# 기존 slot_gen=900 / anti_patterns=1500 / ref_point_gen=1500 불일치 회귀 차단.
from app.nodes_small.slot_gen import DECOMPRESSION_RADIUS_MM as _DECOMPRESSION_RADIUS_MM

ENTRANCE_FRONT_CLEAR_MM = _DECOMPRESSION_RADIUS_MM  # 입구 정면 빈 공간 반경 (AP-001/AP-105)
MAIN_ARTERY_HALF_WIDTH_MM = 900         # main_artery 폭 (AP-002)
RESTROOM_FRONT_CLEAR_MM = 1500          # 화장실 정면 빈 공간 (AP-003) — dead_zone 별개 도메인, 동기화 X
ENTRANCE_ZONE_MAX_HEIGHT_MM = 1200      # entrance_zone 중앙부 최대 높이 (AP-004 / AP-103)
SECONDARY_ENTRANCE_ZONE_RADIUS_MM = 2000  # 2~N번째 입구 zone 인정 반경 (AP-101)
SECONDARY_DECOMPRESSION_RADIUS_MM = _DECOMPRESSION_RADIUS_MM  # 2~N번째 입구 감압존 반경 (AP-102)
LARGE_OBJECT_WIDTH_MM = 1000            # large 기물 판단 (width 또는 depth ≥ 이 값)


# ── 위반 dict 생성 헬퍼 ────────────────────────────────────────────
def _make_violation(rule_id: str, severity: str, intent: dict, detail: str) -> dict:
    """validator 함수에서 위반 발견 시 반환할 dict 표준화."""
    return {
        "rule_id": rule_id,
        "severity": severity,
        "intent_object_type": intent.get("object_type", "?"),
        "intent_zone": intent.get("zone_label", "?"),
        "intent_ref_point_id": intent.get("ref_point_id", "?"),
        "violation_detail": detail,
    }


# ── 공통 헬퍼 ──────────────────────────────────────────────────────
def _get_ref_point(state: dict, ref_point_id: str) -> Optional[dict]:
    """ref_point_id → state["reference_points"] 의 dict 조회. None 가능."""
    if not ref_point_id:
        return None
    for rp in state.get("reference_points") or []:
        if rp.get("id") == ref_point_id:
            return rp
    return None


def _get_intent_dimensions(intent: dict, state: dict) -> tuple[int, int, int]:
    """intent 의 object_type → eligible_objects 에서 width/depth/height 조회. 누락 시 0."""
    obj_type = intent.get("object_type", "")
    for obj in state.get("eligible_objects") or []:
        if obj.get("object_type") == obj_type:
            return (obj.get("width_mm", 0), obj.get("depth_mm", 0), obj.get("height_mm", 0))
    return (0, 0, 0)


def _is_large_object(width: int, depth: int) -> bool:
    """large 기물 판단 — width 또는 depth ≥ 임계."""
    return width >= LARGE_OBJECT_WIDTH_MM or depth >= LARGE_OBJECT_WIDTH_MM


def _distance_to_entrance(coord: tuple, entrance: tuple) -> float:
    """두 좌표 간 직선 거리 (mm)."""
    if not coord or not entrance:
        return float("inf")
    return math.hypot(coord[0] - entrance[0], coord[1] - entrance[1])


# ─────────────────────────────────────────────────────────────────────
# A. 단일 입구 anti-pattern (AP-001 ~ AP-008)
# ─────────────────────────────────────────────────────────────────────


def _validate_AP_001(intents: list, state: dict) -> list[dict]:
    """단일 입구 매장: 입구 정면 감압존 이내 가벽/대형 obj 금지.

    1-3 (#533) C3: 면적별 동적 — state["decompression_radius_mm"] 우선 (slot_gen 박음).
    """
    violations = []
    entrance_mm = state.get("entrance_mm")
    if not entrance_mm:
        return []
    decomp_radius = state.get("decompression_radius_mm", ENTRANCE_FRONT_CLEAR_MM)
    for intent in intents:
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp:
            continue
        dist = _distance_to_entrance(rp.get("coord"), entrance_mm)
        if dist >= decomp_radius:
            continue
        obj_type = intent.get("object_type", "")
        width, depth, _ = _get_intent_dimensions(intent, state)
        is_partition = obj_type.startswith("partition_wall")
        is_large = _is_large_object(width, depth)
        if is_partition or is_large:
            violations.append(_make_violation(
                "AP-001", "blocking", intent,
                f"입구 정면 {int(dist)}mm < {decomp_radius}mm 이내 {'가벽' if is_partition else '대형 기물'} 배치"
            ))
    return violations


def _validate_AP_002(intents: list, state: dict) -> list[dict]:
    """main_artery 폭 900mm 이내 photo_island/대형 obj 금지."""
    violations = []
    main_artery = state.get("main_artery")
    if not main_artery:
        return []
    for intent in intents:
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp:
            continue
        coord = rp.get("coord")
        if not coord:
            continue
        dist = main_artery.distance(Point(coord))
        if dist >= MAIN_ARTERY_HALF_WIDTH_MM:
            continue
        obj_type = intent.get("object_type", "")
        width, depth, _ = _get_intent_dimensions(intent, state)
        if obj_type == "photo_island" or _is_large_object(width, depth):
            violations.append(_make_violation(
                "AP-002", "blocking", intent,
                f"main_artery 거리 {int(dist)}mm < {MAIN_ARTERY_HALF_WIDTH_MM}mm 이내 {obj_type} 배치"
            ))
    return violations


def _validate_AP_003(intents: list, state: dict) -> list[dict]:
    """화장실 정면 1500mm 이내 고객 체류 obj (consultation_desk/counter/kiosk/test_bar) 금지.

    2026-05-08: target 확장 + toilet 필터.
      - target_types: consultation_desk + test_bar → counter / kiosk 추가 (고객 체류 시간 긴 obj 전부)
      - inaccessible_polys 무차별 → inaccessible_types 의 'toilet' 만 필터 (계단/pillar 별도)
      - 사유: 진규님 5-8 명시 — "화장실 근처 고객 오래 머물게 하는 obj 기피. 보조 테이블 / 진열대 등 value 낮은 obj 만 OK"
    """
    violations = []
    inaccessible_polys = state.get("inaccessible_polys") or []
    inaccessible_types = state.get("inaccessible_types") or []
    if not inaccessible_polys:
        return []
    # 2026-05-08: counter / kiosk 추가
    target_types = {"consultation_desk", "test_bar", "counter", "kiosk"}
    # 2026-05-08: toilet 폴리곤만 필터 (계단/pillar 별도 검사)
    toilet_polys = [
        poly for i, poly in enumerate(inaccessible_polys)
        if i < len(inaccessible_types)
        and inaccessible_types[i] == "toilet"
        and hasattr(poly, "distance")
    ]
    if not toilet_polys:
        return []
    for intent in intents:
        if intent.get("object_type") not in target_types:
            continue
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp or not rp.get("coord"):
            continue
        pt = Point(rp["coord"])
        for poly in toilet_polys:
            dist = poly.distance(pt)
            if dist < RESTROOM_FRONT_CLEAR_MM:
                violations.append(_make_violation(
                    "AP-003", "blocking", intent,
                    f"화장실 정면 {int(dist)}mm < {RESTROOM_FRONT_CLEAR_MM}mm 이내 고객 체류 obj ({intent['object_type']}) 배치"
                ))
                break
    return violations


def _validate_AP_004(intents: list, state: dict) -> list[dict]:
    """entrance_zone 중앙부 1200mm 초과 obj 금지 (R4 strict)."""
    violations = []
    for intent in intents:
        if intent.get("zone_label") != "entrance_zone":
            continue
        # center/freestanding 방향만 적용 (R4)
        direction = intent.get("direction", "")
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        rp_label = rp.get("label", "") if rp else ""
        is_center = direction in ("center", "focal") or "center" in rp_label
        if not is_center:
            continue
        _, _, height = _get_intent_dimensions(intent, state)
        if height > ENTRANCE_ZONE_MAX_HEIGHT_MM:
            violations.append(_make_violation(
                "AP-004", "blocking", intent,
                f"entrance_zone 중앙부 height {height}mm > {ENTRANCE_ZONE_MAX_HEIGHT_MM}mm"
            ))
    return violations


def _validate_AP_005(intents: list, state: dict) -> list[dict]:
    """단독 floating 가벽 (짝꿍 없는 partition_wall_I) 금지."""
    violations = []
    partition_intents = [i for i in intents if i.get("object_type", "").startswith("partition_wall")]
    if not partition_intents:
        return []
    # 짝꿍 = 같은 ref_point 또는 인접 ref_point 에 다른 obj 가 join_with 로 연결
    for intent in partition_intents:
        join_with = intent.get("join_with")
        if join_with:
            continue
        # 같은 ref_point 에 다른 intent 있으면 짝꿍 인정
        rp_id = intent.get("ref_point_id")
        same_rp = [i for i in intents if i.get("ref_point_id") == rp_id and i is not intent]
        if same_rp:
            continue
        violations.append(_make_violation(
            "AP-005", "blocking", intent,
            f"단독 floating 가벽 (join_with X, 같은 ref_point 다른 obj 0)"
        ))
    return violations


def _validate_AP_006(intents: list, state: dict) -> list[dict]:
    """shelf_wall 의 짝꿍 (display_table 등) 부재 시 효과 ↓ (warning)."""
    violations = []
    has_shelf = any(i.get("object_type") == "shelf_wall" for i in intents)
    if not has_shelf:
        return []
    pair_types = {"display_table", "display_table_standard", "test_bar"}
    has_pair = any(i.get("object_type") in pair_types for i in intents)
    if not has_pair:
        # warning — shelf_wall 만 있고 짝꿍 X
        for i in intents:
            if i.get("object_type") == "shelf_wall":
                violations.append(_make_violation(
                    "AP-006", "warning", i,
                    f"shelf_wall 의 짝꿍 (display_table/test_bar 등) 부재 — 효과 저하"
                ))
                break  # 1개만 warning
    return violations


def _validate_AP_007(intents: list, state: dict) -> list[dict]:
    """vmd 의도 없는 가벽 (space_partition / staff_zone / pair_join 외) 배치 금지."""
    violations = []
    valid_reasons = {"space_partition", "staff_zone", "pair_join", "back_to_back", "facade_media"}
    for intent in intents:
        if not intent.get("object_type", "").startswith("partition_wall"):
            continue
        reason = intent.get("placement_reason", "") or intent.get("placed_because", "")
        # placement_reason 이 명시되지 않거나 valid_reasons 외
        if not any(vr in reason for vr in valid_reasons):
            violations.append(_make_violation(
                "AP-007", "blocking", intent,
                f"가벽 vmd 의도 없음 (reason='{reason[:50]}', valid: {valid_reasons})"
            ))
    return violations


def _validate_AP_008(intents: list, state: dict) -> list[dict]:
    """면적 대비 기물 폭증 (#377 M backstop 외 추가) — 18평 placed > 8 시 warning."""
    violations = []
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        return []
    area_mm2 = usable_poly.area
    # 18평 (~60M mm²) 이하에서 intents > 8 시 warning
    if area_mm2 <= 60_000_000 and len(intents) > 8:
        # 첫 intent 에 대표 warning
        violations.append(_make_violation(
            "AP-008", "warning", intents[0] if intents else {},
            f"18평 ({int(area_mm2/1_000_000)}㎡) 이하 기물 {len(intents)}개 — 폭증 의심"
        ))
    return violations


def _validate_AP_010(intents: list, state: dict) -> list[dict]:
    """[blocking] partition_wall_I 가 mid_zone 또는 entrance_zone 매핑 금지.

    C4 (5-7 21:36 + 5-8 13:30 라이브 회귀 fix):
      - 5-7 21:36: 가벽이 매장 한복판 가로로 박혀 카운터들 사이 끼임 (시위 형태)
      - 5-8 13:30: partition_wall_I @ (5000, 8250) anchor=wall_9_left mid_zone — 다시 시위
      - 본질: mid_zone wall ref 에 가벽 매핑 시 placement 가 매장 중앙 향해 수직 돌출 →
        매장 한가운데 가로 시위 형태. 양옆 통로 폭 잠식 + 동선 차단 + VMD 부적절.

    fix: zone_label = deep_zone 만 허용 (mid/entrance 절대 금지).
      - L 은 별도. staff_zone (deep_zone 코너) 정공 — 본 룰 미적용.
      - intent.zone_label 또는 ref_point.zone_label 둘 중 하나만 mid/entrance 면 위반 (LLM
        이 zone_label 누락 + ref 만 박는 케이스도 차단).
    """
    violations = []
    for intent in intents:
        obj_type = intent.get("object_type", "")
        if obj_type != "partition_wall_I":
            continue
        intent_zone = intent.get("zone_label", "")
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        rp_zone = rp.get("zone_label", "") if rp else ""
        # 둘 중 하나라도 mid/entrance 면 위반
        forbidden_zones = {"mid_zone", "entrance_zone"}
        if intent_zone in forbidden_zones or rp_zone in forbidden_zones:
            violations.append(_make_violation(
                "AP-010", "blocking", intent,
                f"partition_wall_I {obj_type} 가 {intent_zone or rp_zone} 매핑 — "
                f"deep_zone 만 허용 (mid_zone wall ref 에 가벽 매핑 시 매장 중앙 시위 형태 회귀)"
            ))
    return violations


def _validate_AP_009(intents: list, state: dict) -> list[dict]:
    """[blocking] 같은 ref_point_id 에 2+ obj 중복 매핑 금지 (정당 케이스 제외).

    1-3 (#523 후속): 5-7 14:26 라이브에서 design LLM 이 wall_15_left 에 photo_wall + counter
    둘 다 매핑 → placement priority counter(95) 우선 → photo_wall 다른 ref 시도 fail → fallback
    step-down 으로 inward 강제 끼워박힘 → standalone 가벽처럼 보이는 회귀 발생.

    원칙: ref_point 1:1 매핑. 단 가벽 양면 / join_with 짝꿍은 정당.
    """
    from collections import defaultdict
    rp_groups: dict[str, list[dict]] = defaultdict(list)
    for i in intents:
        rp = i.get("ref_point_id")
        if rp:
            rp_groups[rp].append(i)

    violations = []
    for rp, group in rp_groups.items():
        if len(group) <= 1:
            continue
        # 정당 케이스 제외: partition_wall 면 활용 또는 join_with 짝꿍
        has_partition = any(g.get("object_type", "").startswith("partition_wall") for g in group)
        has_join = any(g.get("join_with") for g in group)
        if has_partition or has_join:
            continue
        # 단순 중복 — 위반. 모든 group 멤버에 violation 박음 (어느 게 우선인지 LLM 이 결정)
        types = [g.get("object_type", "?") for g in group]
        for g in group:
            violations.append(_make_violation(
                "AP-009", "blocking", g,
                f"ref_point '{rp}' 에 {len(group)}개 obj 중복 매핑 ({types}) — ref_point 1:1 원칙 위반. "
                f"우선순위 obj 1개만 남기고 나머지 다른 ref_point 로 이동 필요. "
                f"가벽 양면 / join_with 짝꿍 정당 케이스는 partition_wall 또는 join_with 명시 필요"
            ))
    return violations


# ─────────────────────────────────────────────────────────────────────
# B. 다중 입구 anti-pattern (AP-101 ~ AP-108)
# ─────────────────────────────────────────────────────────────────────


def _get_secondary_entrances(state: dict) -> list[tuple]:
    """all_entrances_mm 에서 첫 입구 (entrance_mm) 제외 나머지 좌표 list."""
    entrance_mm = state.get("entrance_mm")
    all_entrances = state.get("all_entrances_mm") or []
    secondary = []
    for ent in all_entrances:
        coord = ent.get("coord") if isinstance(ent, dict) else ent
        if not coord:
            continue
        if entrance_mm and abs(coord[0] - entrance_mm[0]) < 100 and abs(coord[1] - entrance_mm[1]) < 100:
            continue  # 첫 입구 제외
        secondary.append(coord)
    return secondary


def _validate_AP_101(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 좌표 기준 1.5~2m 반경에 entrance_zone 분류 ref_point 0건 → zone 미인정."""
    violations = []
    secondary = _get_secondary_entrances(state)
    if not secondary:
        return []
    reference_points = state.get("reference_points") or []
    for ent_coord in secondary:
        ent_pt = Point(ent_coord)
        # 반경 내 ref_point 중 entrance_zone 분류 0개?
        nearby_entrance_zones = 0
        for rp in reference_points:
            if rp.get("zone_label") != "entrance_zone":
                continue
            rp_coord = rp.get("coord")
            if not rp_coord:
                continue
            if ent_pt.distance(Point(rp_coord)) < SECONDARY_ENTRANCE_ZONE_RADIUS_MM:
                nearby_entrance_zones += 1
        if nearby_entrance_zones == 0:
            # 첫 intent 대표 (특정 intent 에 귀속 X — state 차원 위반)
            violations.append(_make_violation(
                "AP-101", "blocking", intents[0] if intents else {},
                f"2~N번째 입구 ({int(ent_coord[0])},{int(ent_coord[1])}) 반경 {SECONDARY_ENTRANCE_ZONE_RADIUS_MM}mm 에 entrance_zone ref_point 0건"
            ))
    return violations


def _validate_AP_102(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 앞 감압존 안에 placed_object bbox 침범.

    1-3 (#533) C3: 면적별 동적 — state["decompression_radius_mm"] 우선.
    """
    violations = []
    secondary = _get_secondary_entrances(state)
    if not secondary:
        return []
    decomp_radius = state.get("decompression_radius_mm", SECONDARY_DECOMPRESSION_RADIUS_MM)
    for intent in intents:
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp or not rp.get("coord"):
            continue
        coord = rp["coord"]
        for ent_coord in secondary:
            dist = _distance_to_entrance(coord, ent_coord)
            if dist < decomp_radius:
                violations.append(_make_violation(
                    "AP-102", "blocking", intent,
                    f"2~N번째 입구 앞 감압존 ({int(dist)}mm < {decomp_radius}mm) 침범"
                ))
                break
    return violations


def _validate_AP_103(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 중앙부 (center_freestanding) 에 height_mm > 1200 placed → R4 미적용.

    1-3 (#533) C3: 면적별 동적 감압존.
    """
    violations = []
    secondary = _get_secondary_entrances(state)
    if not secondary:
        return []
    decomp_radius = state.get("decompression_radius_mm", SECONDARY_DECOMPRESSION_RADIUS_MM)
    for intent in intents:
        direction = intent.get("direction", "")
        if direction not in ("center", "focal"):
            continue
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp or not rp.get("coord"):
            continue
        coord = rp["coord"]
        # 2~N번째 입구 감압존 이내?
        for ent_coord in secondary:
            if _distance_to_entrance(coord, ent_coord) >= decomp_radius:
                continue
            _, _, height = _get_intent_dimensions(intent, state)
            if height > ENTRANCE_ZONE_MAX_HEIGHT_MM:
                violations.append(_make_violation(
                    "AP-103", "blocking", intent,
                    f"2~N번째 입구 앞 center 에 height {height}mm > {ENTRANCE_ZONE_MAX_HEIGHT_MM}mm"
                ))
                break
    return violations


def _validate_AP_104(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 앞에 partition_wall_I/L placed → R8 미적용.

    1-3 (#533) C3: 면적별 동적 감압존.
    """
    violations = []
    secondary = _get_secondary_entrances(state)
    if not secondary:
        return []
    decomp_radius = state.get("decompression_radius_mm", SECONDARY_DECOMPRESSION_RADIUS_MM)
    for intent in intents:
        if not intent.get("object_type", "").startswith("partition_wall"):
            continue
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp or not rp.get("coord"):
            continue
        coord = rp["coord"]
        for ent_coord in secondary:
            if _distance_to_entrance(coord, ent_coord) < decomp_radius:
                violations.append(_make_violation(
                    "AP-104", "blocking", intent,
                    f"2~N번째 입구 앞 ({int(_distance_to_entrance(coord, ent_coord))}mm) 가벽 배치"
                ))
                break
    return violations


def _validate_AP_105(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 1.5~2m 반경에 large 기물 placed → R1 미적용."""
    violations = []
    secondary = _get_secondary_entrances(state)
    if not secondary:
        return []
    for intent in intents:
        rp = _get_ref_point(state, intent.get("ref_point_id"))
        if not rp or not rp.get("coord"):
            continue
        coord = rp["coord"]
        width, depth, _ = _get_intent_dimensions(intent, state)
        if not _is_large_object(width, depth):
            continue
        for ent_coord in secondary:
            dist = _distance_to_entrance(coord, ent_coord)
            if dist < SECONDARY_ENTRANCE_ZONE_RADIUS_MM:
                violations.append(_make_violation(
                    "AP-105", "blocking", intent,
                    f"2~N번째 입구 반경 {int(dist)}mm < {SECONDARY_ENTRANCE_ZONE_RADIUS_MM}mm 에 large ({width}×{depth}) 배치"
                ))
                break
    return violations


def _validate_AP_106(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 ↔ mid 이동 path 가 placed_object 로 막힘 → 동선 차단.

    LLM 판단 영역 — design 단계에서 path 검증 어려움. placement 후 verify 노드 영역.
    여기서는 placement_log / failed_objects 기반 간접 검출 시도. 미검출 시 0 violation."""
    # placement 후 검증 영역. design 단계에선 stub.
    return []


def _validate_AP_107(intents: list, state: dict) -> list[dict]:
    """2~N번째 입구 기준 right/left/center 와 placed_object 위치 불일치 → entrance_side 잘못.

    LLM 판단 영역 — entrance_side 가 첫 입구 기준만 태깅됨. 2~N번째 입구는 별도 기준 X.
    design 단계에서 검증 어려움. stub."""
    return []


def _validate_AP_108(intents: list, state: dict) -> list[dict]:
    """사방 개방 부스 (4입구) 인데 mid_zone 좌표만으로 배치 결정 → 4면 entrance 룰 X."""
    violations = []
    all_entrances = state.get("all_entrances_mm") or []
    if len(all_entrances) < 3:
        return []  # 4입구 가까운 케이스만 적용
    # mid_zone 비율 검사 — entrance_zone 0 또는 너무 적으면 위반
    entrance_count = sum(1 for i in intents if i.get("zone_label") == "entrance_zone")
    if entrance_count < len(all_entrances) // 2:
        violations.append(_make_violation(
            "AP-108", "warning", intents[0] if intents else {},
            f"{len(all_entrances)} 입구 매장에 entrance_zone intents {entrance_count}개 — 4면 룰 미적용"
        ))
    return violations


# ─────────────────────────────────────────────────────────────────────
# C. zone 분류 / 동선 정책 anti-pattern (AP-201 ~ AP-207)
# ─────────────────────────────────────────────────────────────────────
# 대부분 LLM 판단 영역 — design 단계 자동 검출 어려움. design_reviewer LLM prompt 에 흡수.


def _validate_AP_201(intents: list, state: dict) -> list[dict]:
    """entrance_zone 면적이 매장 형태 대비 부적절 — LLM 판단 영역. stub."""
    return []


def _validate_AP_202(intents: list, state: dict) -> list[dict]:
    """카테고리 무관 zone 분할 — LLM 판단 영역. stub."""
    return []


def _validate_AP_203(intents: list, state: dict) -> list[dict]:
    """main_artery 가 직선 (waypoints 2 이하 / S자·U자·Z자 우회 부재) → python 검출.

    1-3 후속 (B2, #533): 간단한 직선 검출은 결정론적 가능.
    waypoints 카운트 + bbox 가로/세로 비율로 직선 판정. 정밀 동선 평가는 LLM 영역으로 위임.
    """
    main_artery = state.get("main_artery")
    if not main_artery or not hasattr(main_artery, "coords"):
        return []
    coords = list(main_artery.coords)
    if len(coords) <= 2:
        # waypoint 부재 (start + end 만) = 직선
        return [_make_violation(
            "AP-203", "warning", intents[0] if intents else {},
            f"main_artery waypoints {len(coords)}개 — S자/U자/Z자 우회 부재. 동선 단조."
        )]
    return []


def _validate_AP_204(intents: list, state: dict) -> list[dict]:
    """입구 → 가장 깊은 곳 도달 동선 (체험→진열→결제 sequence X) — LLM 판단 영역. stub."""
    return []


def _validate_AP_205(intents: list, state: dict) -> list[dict]:
    """main_artery 1개 + sub_path 보조만 → 메인/서브 다층 부재 — LLM 판단 영역. stub."""
    return []


def _validate_AP_206(intents: list, state: dict) -> list[dict]:
    """가벽 random 배치 (가벽 동선 설계 의도 미반영) — AP-007 와 부분 중복. LLM 보강 영역. stub."""
    return []


def _validate_AP_207(intents: list, state: dict) -> list[dict]:
    """venue_type 미반영 — python 보강.

    1-3 후속 (B2, #533): venue_type 명시되면 카테고리 / 매장 위치 룰 매칭 권고. 명시 X 시 warning.
    LLM 판단은 design_reviewer 가 venue_type 기반 동선 / fixture 적정성 추가 검증.

    minimal/empty state graceful skip — 운영 흐름에서 brand_data / usable_poly 둘 다 부재 시
    test 환경 또는 노드 진입 전 상태로 간주해 검증 skip.
    """
    if not state.get("brand_data") and not state.get("usable_poly"):
        return []
    venue_type = state.get("venue_type")
    if not venue_type or venue_type == "unknown":
        return [_make_violation(
            "AP-207", "warning", intents[0] if intents else {},
            "venue_type 미정 / unknown — 백화점 / 가두상권 등 매장 위치 룰 (clearance / 동선 / facade) 미반영"
        )]
    return []


# ─────────────────────────────────────────────────────────────────────
# D. family_cap / 입구 통과 anti-pattern (AP-301 ~ AP-302)
# ─────────────────────────────────────────────────────────────────────


def _validate_AP_301(intents: list, state: dict) -> list[dict]:
    """같은 std_id (counter) 다른 매뉴얼 명시 (POS / Reward) 시 1개만 alloc → 매뉴얼 의도 손실.

    placement_rules 의 같은 std_id + 다른 label 카운트 vs 실제 intents 매핑 비교.

    1-2 (#520 후속): violation_detail 에 누락 인스턴스 수 / 라벨 list / fix 방향 명시 강화.
    severity 는 warning 유지 — design 프롬프트 강화 (`_build_manual_label_section`) + DESIGN_SYSTEM_TEMPLATE
    출력 규칙 추가가 1차 enforcement. AP-301 은 LLM 무시 시 backstop 신호.
    """
    violations = []
    brand_data = state.get("brand_data") or {}
    placement_rules = brand_data.get("placement_rules") or []
    if not placement_rules:
        return []
    # std_id 별 매뉴얼 명시 수 (label 분리)
    from collections import defaultdict
    manual_by_std = defaultdict(set)
    for r in placement_rules:
        std_id = r.get("object_type", "")
        label = r.get("label") or r.get("name") or std_id
        if std_id:
            manual_by_std[std_id].add(label)
    # intents 의 std_id 별 카운트
    intent_count_by_std = defaultdict(int)
    for i in intents:
        intent_count_by_std[i.get("object_type", "")] += 1
    # 매뉴얼이 같은 std_id 2+ label 인데 intents 가 1개 이하 → 위반
    for std_id, labels in manual_by_std.items():
        if len(labels) >= 2 and intent_count_by_std[std_id] < len(labels):
            sorted_labels = sorted(labels)
            shortage = len(labels) - intent_count_by_std[std_id]
            violations.append(_make_violation(
                "AP-301", "warning",
                {"object_type": std_id, "zone_label": "?", "ref_point_id": "?"},
                f"매뉴얼 명시 {std_id} {len(labels)}개 라벨 ({sorted_labels}) 중 "
                f"{intent_count_by_std[std_id]}개만 intent 화 — {shortage}개 손실. "
                f"design 프롬프트 manual_label_section 무시 의심 — 별도 intent 로 분리 필요"
            ))
    return violations


def _validate_AP_302(intents: list, state: dict) -> list[dict]:
    """큰 기물 (bbox/diagonal) 이 entrance_width 못 통과 → 시공 시 반입 불가.

    회전 후 bbox 의 짧은 변 또는 대각선 vs entrance_width 비교."""
    violations = []
    entrance_width = state.get("entrance_width_mm")
    if not entrance_width or entrance_width <= 0:
        return []
    for intent in intents:
        width, depth, _ = _get_intent_dimensions(intent, state)
        if width <= 0 or depth <= 0:
            continue
        # 회전 무관 통과 가능성: min(width, depth) <= entrance_width 면 OK
        # 회전 시 대각선 = sqrt(w^2 + d^2). 단 좁은 변 통과면 문제 X
        short_side = min(width, depth)
        if short_side > entrance_width:
            violations.append(_make_violation(
                "AP-302", "blocking", intent,
                f"기물 짧은 변 {short_side}mm > entrance_width {int(entrance_width)}mm — 반입 불가"
            ))
    return violations


def _validate_AP_303(intents: list, state: dict) -> list[dict]:
    """[LLM] 매뉴얼 명시 manual_label 의 의미적 구분이 design intents 에 반영됐는지 LLM 판단.

    1-2 (#520 후속): AP-301 (python — 단순 라벨 카운트 비교) 의 한계 보완. LLM 이 라벨의
    의미적 기능 (예: 'POS 카운터' = 결제 동선 / '증정품 카운터' = 사은품 증정 동선) 차이를
    파악해 design intents 의 zone/direction/reason 이 그 기능을 반영했는지 판정.

    python validator 빈 list — design_reviewer._call_llm_reviewer 가 LLM 호출 시 본 룰의
    description + manual_labels context 사용. severity=warning (LLM variance 감안).
    """
    return []


# ─────────────────────────────────────────────────────────────────────
# 룰 catalog (25개 등록)
# ─────────────────────────────────────────────────────────────────────

ANTI_PATTERNS: list[dict] = [
    # A. 단일 입구 (5-1 baseline, 8개)
    {"id": "AP-001", "category": "single_entrance", "severity": "blocking",
     "description": "단일 입구 매장: 입구 정면 1500mm 이내 가벽/대형 obj 금지",
     "validator_type": "python", "validator": _validate_AP_001, "enabled": True, "categories_only": []},
    {"id": "AP-002", "category": "single_entrance", "severity": "blocking",
     "description": "main_artery 폭 900mm 이내 photo_island/대형 obj 금지",
     "validator_type": "python", "validator": _validate_AP_002, "enabled": True, "categories_only": []},
    {"id": "AP-003", "category": "single_entrance", "severity": "blocking",
     "description": "화장실 정면 1500mm 이내 고객 체류 obj (consultation_desk/counter/kiosk/test_bar) 금지. "
                    "보조 테이블 / 진열대 등 value 낮은 obj 만 허용. "
                    "2026-05-08: target 확장 (counter/kiosk 추가) + toilet 만 필터 (계단/pillar 별도)",
     "validator_type": "python", "validator": _validate_AP_003, "enabled": True, "categories_only": []},
    {"id": "AP-004", "category": "single_entrance", "severity": "blocking",
     "description": "entrance_zone 중앙부 1200mm 초과 obj 금지 (R4 strict)",
     "validator_type": "python", "validator": _validate_AP_004, "enabled": True, "categories_only": []},
    {"id": "AP-005", "category": "single_entrance", "severity": "blocking",
     "description": "단독 floating 가벽 (짝꿍 없는 partition_wall_I) 금지",
     "validator_type": "python", "validator": _validate_AP_005, "enabled": True, "categories_only": []},
    {"id": "AP-006", "category": "single_entrance", "severity": "warning",
     "description": "shelf_wall 의 짝꿍 (display_table 등) 부재 시 효과 ↓",
     "validator_type": "python", "validator": _validate_AP_006, "enabled": True, "categories_only": []},
    {"id": "AP-007", "category": "single_entrance", "severity": "blocking",
     "description": "vmd 의도 없는 가벽 (space_partition / staff_zone / pair_join 외) 배치 금지",
     "validator_type": "python", "validator": _validate_AP_007, "enabled": True, "categories_only": []},
    {"id": "AP-008", "category": "single_entrance", "severity": "warning",
     "description": "면적 대비 기물 폭증 (#377 M backstop 외 추가) — 18평 placed > 8 시 warning",
     "validator_type": "python", "validator": _validate_AP_008, "enabled": True, "categories_only": []},
    {"id": "AP-009", "category": "structural_constraint", "severity": "blocking",
     "description": "같은 ref_point_id 에 2+ obj 중복 매핑 금지 (가벽 양면 / join_with 짝꿍 제외) — ref_point 1:1 원칙",
     "validator_type": "python", "validator": _validate_AP_009, "enabled": True, "categories_only": []},
    {"id": "AP-010", "category": "single_entrance", "severity": "blocking",
     "description": "partition_wall_I 가 mid_zone / entrance_zone 매핑 금지 — deep_zone 만 허용. "
                    "mid_zone wall ref 에 가벽 매핑 시 placement 가 매장 중앙 향해 수직 돌출 → "
                    "매장 한복판 가로 시위 형태 회귀 (5-7 21:36 + 5-8 13:30 라이브). "
                    "L 은 별도 (staff_zone deep_zone 코너 정공 — 본 룰 미적용)",
     "validator_type": "python", "validator": _validate_AP_010, "enabled": True, "categories_only": []},

    # B. 다중 입구 (5-2 #486 흡수, 8개)
    {"id": "AP-101", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 좌표 기준 1.5~2m 반경에 entrance_zone 분류 ref_point 0건 → zone 미인정",
     "validator_type": "python", "validator": _validate_AP_101, "enabled": True, "categories_only": []},
    {"id": "AP-102", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 앞 1.5m 빈 공간 (감압존) 안에 placed_object bbox 침범",
     "validator_type": "python", "validator": _validate_AP_102, "enabled": True, "categories_only": []},
    {"id": "AP-103", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 중앙부 (center_freestanding) 에 height_mm > 1200 placed → R4 미적용",
     "validator_type": "python", "validator": _validate_AP_103, "enabled": True, "categories_only": []},
    {"id": "AP-104", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 앞에 partition_wall_I/L placed → R8 미적용",
     "validator_type": "python", "validator": _validate_AP_104, "enabled": True, "categories_only": []},
    {"id": "AP-105", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 1.5~2m 반경에 large 기물 placed → R1 미적용",
     "validator_type": "python", "validator": _validate_AP_105, "enabled": True, "categories_only": []},
    {"id": "AP-106", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 ↔ mid 이동 path 가 placed_object 로 막힘 → 동선 차단",
     "validator_type": "llm", "validator": _validate_AP_106, "enabled": True, "categories_only": []},
    {"id": "AP-107", "category": "multi_entrance", "severity": "blocking",
     "description": "2~N번째 입구 기준 right/left/center 와 placed_object 위치 불일치 → entrance_side 잘못",
     "validator_type": "llm", "validator": _validate_AP_107, "enabled": True, "categories_only": []},
    {"id": "AP-108", "category": "multi_entrance", "severity": "warning",
     "description": "사방 개방 부스 (4입구) 인데 mid_zone 좌표만으로 배치 결정 → 4면 entrance 룰 X",
     "validator_type": "python", "validator": _validate_AP_108, "enabled": True, "categories_only": []},

    # C. zone 분류 / 동선 정책 (5-2 신규, 7개) — 모두 LLM 판단 영역
    {"id": "AP-201", "category": "zone_flow", "severity": "warning",
     "description": "entrance_zone 면적이 매장 형태 / 카테고리 대비 부적절. 가두상권 유리 facade = 진입부 시야 확보 위해 entrance_zone 넉넉. 백화점 인숍 / 좁은 매장 = entrance_zone 최소화 + mid/deep 비중 ↑. 33%/66% 고정 비율 부작용.",
     "validator_type": "llm", "validator": _validate_AP_201, "enabled": True, "categories_only": []},
    {"id": "AP-202", "category": "zone_flow", "severity": "warning",
     "description": "카테고리 무관 zone 분할 — 뷰티 (체험/상담 mid 강함) / F&B (음식 진열 + 좌석) / 캐릭터 IP (포토존 + 굿즈) 별 권장 비율 다름. 같은 비율로 분할 시 의도 무시.",
     "validator_type": "llm", "validator": _validate_AP_202, "enabled": True, "categories_only": []},
    {"id": "AP-203", "category": "zone_flow", "severity": "warning",
     "description": "main_artery 가 직선 (waypoints 2 이하) → S자/U자/Z자 우회 부재. 체류 시간 ↓. python validator (waypoints 카운트) + LLM 판정 (의도 평가).",
     "validator_type": "python", "validator": _validate_AP_203, "enabled": True, "categories_only": []},
    {"id": "AP-204", "category": "zone_flow", "severity": "warning",
     "description": "동선 sequence 부적절 — 카테고리별 권장 흐름: 뷰티 = 체험(test_bar)→상담(consultation)→진열(shelf)→결제(counter). F&B = 메뉴/주문→대기→결제. 캐릭터 IP = 포토존→굿즈진열→결제. zone 배치가 sequence 역방향 / 단축 시 위반.",
     "validator_type": "llm", "validator": _validate_AP_204, "enabled": True, "categories_only": []},
    {"id": "AP-205", "category": "zone_flow", "severity": "warning",
     "description": "main_artery 1개 + sub_path 보조만 — 메인/서브 다층 동선 부재. 50평 ↑ 매장은 main + sub_path 분기 필수. 18평 소형은 main 1개 OK (이 케이스 LLM 이 면적 보고 판정).",
     "validator_type": "llm", "validator": _validate_AP_205, "enabled": True, "categories_only": []},
    {"id": "AP-206", "category": "zone_flow", "severity": "warning",
     "description": "가벽 (partition_wall) random 배치 — placement_reason 자유 서술에 동선 분할 / 유도 / 시각 차단 / staff_zone 등 명확한 의도 없으면 random. AP-007 와 partial 중복.",
     "validator_type": "llm", "validator": _validate_AP_206, "enabled": True, "categories_only": []},
    {"id": "AP-207", "category": "zone_flow", "severity": "warning",
     "description": "venue_type (백화점 인숍 vs 가두상권 vs 단독 매장) 동선 / clearance / facade 차이 미반영. python validator (venue_type 미정 시 warning) + LLM (venue 별 동선 적정성).",
     "validator_type": "python", "validator": _validate_AP_207, "enabled": True, "categories_only": []},
    {"id": "AP-208", "category": "zone_flow", "severity": "warning",
     "description": "클러스터 진열 기회 놓침 — 같은 카테고리 obj (shelf_wall ↔ shelf_wall / display_table ↔ display_table / counter ↔ counter / shelf_wall ↔ display_table 등) 2+ 가 같은 zone + 같은 wall_facing 인데 join_with 모두 null. "
                    "placement 코드는 pair_rules 의 join 관계 obj 를 edge-to-edge 인접 (margin=0) 배치 허용. join_with 누락 시 placement 가 600~900mm 간격 강제 → cluster 진열 패턴 (선반 라인업 / 카운터 라인업) 안 나옴. "
                    "★ 동일 std_id 다른 manual_label 인스턴스 케이스 (매뉴얼이 같은 std_id 를 별도 라벨로 분리 명시한 counter / display_table / shelf_wall 등) = 강한 reject 권장: "
                    "현실 매장에서 1 wall 라인업으로 나란히 배치되며, 각 다른 wall 차지 시 다른 핵심 obj (photo_wall 등) 자리 부족 → drop 회귀. "
                    "ref_analysis.layout_patterns 에 '선반 라인업' / '연속 배치' / '벽면 따라 진열' 같은 패턴 명시 시도 강한 reject. "
                    "정당 회피: 카테고리 명확 분리 (shelf_wall + counter 의미 구획) / 좁은 zone 통로 폭 부족 / pair_rules 에 separate 정의.",
     "validator_type": "llm", "validator": _validate_AP_201, "enabled": True, "categories_only": []},

    # D. family_cap / 입구 통과 (#479 / #485, 3개 — 1-2 #520 후속에 AP-303 LLM 의미 판단 추가)
    {"id": "AP-301", "category": "family_entrance_pass", "severity": "warning",
     "description": "같은 std_id (counter) 다른 매뉴얼 명시 (POS / Reward) 시 1개만 alloc → 매뉴얼 의도 손실",
     "validator_type": "python", "validator": _validate_AP_301, "enabled": True, "categories_only": []},
    {"id": "AP-302", "category": "family_entrance_pass", "severity": "blocking",
     "description": "큰 기물 (bbox/diagonal) 이 entrance_width 못 통과 → 시공 시 반입 불가",
     "validator_type": "python", "validator": _validate_AP_302, "enabled": True, "categories_only": []},
    {"id": "AP-303", "category": "manual_label_semantic", "severity": "warning",
     "description": "매뉴얼 명시 manual_label 의 의미적 기능 (결제 vs 증정품 vs 안내) 차이가 "
                    "design intents 의 zone/direction/reason 에 반영됐는지 — 단순 중복 배치만 됐다면 의도 손실",
     "validator_type": "llm", "validator": _validate_AP_303, "enabled": True, "categories_only": []},
]

# ─────────────────────────────────────────────────────────────────────
# 실행 인터페이스
# ─────────────────────────────────────────────────────────────────────


def run_validators(intents: list, state: dict) -> list[dict]:
    """모든 enabled 룰 실행 → violations list 반환.

    Python validator 만 실행 (LLM 판단 영역은 design_reviewer 가 호출).
    각 validator exception 발생 시 graceful — logger.warning + skip.
    """
    violations: list[dict] = []
    brand_category = (state.get("brand_data") or {}).get("brand", {}).get("brand_category")
    if isinstance(brand_category, dict):
        brand_category = brand_category.get("value")

    for ap in ANTI_PATTERNS:
        if not ap.get("enabled", True):
            continue
        if ap.get("validator_type") != "python":
            continue  # LLM 영역은 별도 처리
        # 카테고리 한정 룰 검사
        cats = ap.get("categories_only") or []
        if cats and brand_category not in cats:
            continue
        try:
            v = ap["validator"](intents, state)
            if v:
                violations.extend(v)
        except Exception as e:
            logger.warning(f"[reviewer] {ap['id']} validator exception — skip: {e}")
    return violations


def get_llm_anti_patterns() -> list[dict]:
    """LLM 판단 영역 룰 list — design_reviewer LLM prompt 에 inject 용."""
    return [ap for ap in ANTI_PATTERNS if ap.get("enabled", True) and ap.get("validator_type") == "llm"]


def compute_intent_similarity(prev: list, curr: list) -> float:
    """결정 동등성 비교 — (object_type, zone_label, direction) tuple 매칭율.

    유사도 0.0 ~ 1.0. 1.0 = 완전 일치 (수렴 검출용).
    """
    if not prev or not curr:
        return 0.0
    prev_set = {(i.get("object_type"), i.get("zone_label"), i.get("direction")) for i in prev}
    curr_set = {(i.get("object_type"), i.get("zone_label"), i.get("direction")) for i in curr}
    if not prev_set or not curr_set:
        return 0.0
    return len(prev_set & curr_set) / max(len(prev_set), len(curr_set))


def build_designer_feedback(blocking_violations: list[dict]) -> str:
    """blocking violations → designer 재호출 prompt inject 용 자연어 피드백."""
    if not blocking_violations:
        return ""
    lines = ["## 이전 설계 검토 피드백 — 다음 위반을 수정해서 다시 작성:"]
    for v in blocking_violations:
        lines.append(f"- [{v['rule_id']}] {v['violation_detail']} (object_type={v['intent_object_type']}, zone={v['intent_zone']})")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# E. placement 단계 reviewer 룰 (#490 — 2026-05-05)
# ═════════════════════════════════════════════════════════════════════
# design_reviewer (#474) 가 design_intents 단계 (좌표 결정 전) 만 검증하는 한계 보완.
# placement 후 placed_objects + failed_objects + 좌표 기반 검증.
#
# placement_reviewer.py 가 호출. 별도 list (PLACEMENT_ANTI_PATTERNS) 로 분리해
# design_reviewer 의 run_validators 가 이 룰들을 실행하지 않도록 격리.
# (design 단계엔 placed_objects 가 비어 false negative 회피)


def _placement_make_violation(rule_id: str, severity: str, obj_type: str, detail: str) -> dict:
    """placement 단계 violation dict — design_reviewer 형식과 일관."""
    return {
        "rule_id": rule_id,
        "severity": severity,
        "intent_object_type": obj_type,
        "intent_zone": "?",
        "intent_ref_point_id": "?",
        "violation_detail": detail,
    }


def _validate_AP_401(intents: list, state: dict) -> list[dict]:
    """[blocking] brand 매뉴얼 명시 obj 가 failed_objects 에 있음 (drop).

    매뉴얼 placement_rules 의 obj_type 이 placed 안 되고 failed 면 drop. design 재호출
    시 slot 양보 hint 인 다른 obj 옮기게 유도.
    """
    failed = state.get("failed_objects") or []
    if not failed:
        return []
    brand_rules = (state.get("brand_data") or {}).get("placement_rules") or []
    manual_types = {r.get("object_type") for r in brand_rules if isinstance(r, dict) and r.get("object_type")}
    placed = state.get("placed_objects") or []
    placed_types = {p.get("object_type") for p in placed if isinstance(p, dict)}

    violations: list[dict] = []
    for f in failed:
        obj_type = f.get("object_type", "")
        if obj_type in manual_types and obj_type not in placed_types:
            reason = f.get("reason", "?") if isinstance(f, dict) else "?"
            violations.append(_placement_make_violation(
                "AP-401", "blocking", obj_type,
                f"매뉴얼 명시 obj {obj_type} drop (사유={reason}). slot 점유한 다른 obj 양보 검토 필요"
            ))
    return violations


def _validate_AP_402(intents: list, state: dict) -> list[dict]:
    """[blocking] structural anchor (photo_wall / counter / partition) fail.

    AP-401 의 특수 케이스 — anchor 가 fail 이면 다른 obj 가 같은 slot 차지했을 가능성 ↑.
    """
    STRUCTURAL = {"photo_wall", "counter", "partition_wall_I", "partition_wall_L"}
    failed = state.get("failed_objects") or []
    if not failed:
        return []
    placed = state.get("placed_objects") or []
    placed_types = {p.get("object_type") for p in placed if isinstance(p, dict)}

    violations: list[dict] = []
    for f in failed:
        obj_type = f.get("object_type", "")
        if obj_type in STRUCTURAL and obj_type not in placed_types:
            reason = f.get("reason", "?") if isinstance(f, dict) else "?"
            violations.append(_placement_make_violation(
                "AP-402", "blocking", obj_type,
                f"structural anchor {obj_type} fail (사유={reason}). 같은 slot 점유 obj 양보 시 안착 가능"
            ))
    return violations


def _validate_AP_403(intents: list, state: dict) -> list[dict]:
    """[warning] placed obj 회전 후 bbox 가 entrance_width_mm 통과 가능?

    AP-302 (design 단계) 의 placement 후속 검증. 회전 후 실제 bbox 의 짧은 변과 비교.
    placed_raw 의 rotation_deg 사용해 회전 후 bbox 짧은 변 계산.
    """
    placed = state.get("placed_objects") or []
    if not placed:
        return []
    entrance_width = state.get("entrance_width_mm")
    if not entrance_width or entrance_width <= 0:
        return []  # entrance_width 미상 시 검증 skip

    violations: list[dict] = []
    for p in placed:
        if not isinstance(p, dict):
            continue
        w = p.get("width_mm", 0) or 0
        d = p.get("depth_mm", 0) or 0
        # rotation_deg 와 무관하게 w/d 중 짧은 변이 entrance_width 보다 크면 통과 불가
        # (bbox 회전해도 짧은 변은 보존)
        short_side = min(w, d)
        if short_side > entrance_width:
            violations.append(_placement_make_violation(
                "AP-403", "warning", p.get("object_type", "?"),
                f"placed bbox 짧은 변 {short_side}mm > entrance_width {int(entrance_width)}mm — 시공 시 반입 검증 필요"
            ))
    return violations


def _validate_AP_404(intents: list, state: dict) -> list[dict]:
    """[warning] placed 면적 비율 — design intent 부실 의심.

    placed bbox 합 / usable_poly area 가 너무 작으면 (예: 5%) intent 부실. 너무 크면
    (예: 70%) over-pack. 둘 다 warning.
    """
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    if not placed or not usable_poly:
        return []

    total_bbox_area = 0
    for p in placed:
        if not isinstance(p, dict):
            continue
        w = p.get("width_mm", 0) or 0
        d = p.get("depth_mm", 0) or 0
        total_bbox_area += w * d

    floor_area = usable_poly.area
    if floor_area <= 0:
        return []
    ratio = total_bbox_area / floor_area

    if ratio < 0.05:
        return [_placement_make_violation(
            "AP-404", "warning", "(전체)",
            f"placed bbox 비율 {ratio*100:.1f}% < 5% — design intent 부실 의심 (placed={len(placed)}개)"
        )]
    if ratio > 0.70:
        return [_placement_make_violation(
            "AP-404", "warning", "(전체)",
            f"placed bbox 비율 {ratio*100:.1f}% > 70% — over-pack 의심 (placed={len(placed)}개)"
        )]
    return []


def _validate_AP_405(intents: list, state: dict) -> list[dict]:
    """[LLM] 통합 layout sanity check — 자연어 판단. python validator 빈 list 반환.

    placement_reviewer.py 가 LLM 호출 시 본 룰의 description 사용. python 빈 list.
    """
    return []


def _validate_AP_406(intents: list, state: dict) -> list[dict]:
    """[warning] 오브젝트 간 통로 부족 — verify.py 의 pair_separate / corridor 검증 이전.

    pair_rules separate min_gap 미달 또는 pair 없는 쌍의 일반 corridor < 900mm.
    placement.py 가 reject 안 한 쌍 = 이미 placed. 그 placed 쌍의 gap 검증.
    """
    from app.nodes_small.placement import _find_pair_rule, CORRIDOR_HALF_BUFFER_MM
    from app.utils import make_rotated_rect
    placed = state.get("placed_objects") or []
    pair_rules = (state.get("brand_data") or {}).get("pair_rules") or []
    if len(placed) < 2:
        return []
    polys = []
    for p in placed:
        try:
            bbox = make_rotated_rect(
                (p["center_x_mm"], p["center_y_mm"]),
                p["width_mm"], p["depth_mm"], p["rotation_deg"],
            )
            polys.append({**p, "_bbox": bbox})
        except Exception:
            continue
    out = []
    min_corridor = CORRIDOR_HALF_BUFFER_MM * 2
    for i, a in enumerate(polys):
        for j, b in enumerate(polys):
            if i >= j:
                continue
            gap = a["_bbox"].distance(b["_bbox"])
            pair = _find_pair_rule(a["object_type"], b["object_type"], None, pair_rules)
            if pair and pair.get("relation") == "join":
                continue
            if pair and pair.get("relation") == "separate":
                min_gap = pair.get("min_gap_mm", 0) or 0
                if 0 < gap < min_gap:
                    out.append(_placement_make_violation(
                        "AP-406", "warning",
                        f"{a['object_type']}↔{b['object_type']}",
                        f"분리 간격 부족 ({gap:.0f}mm < {min_gap}mm)",
                    ))
            else:
                if 0 < gap < min_corridor:
                    out.append(_placement_make_violation(
                        "AP-406", "warning",
                        f"{a['object_type']}↔{b['object_type']}",
                        f"통로 폭 부족 ({gap:.0f}mm < {min_corridor}mm)",
                    ))
    return out


def _validate_AP_407(intents: list, state: dict) -> list[dict]:
    """[warning] 벽 이격 부족 — verify.py 의 wall_clearance 검증 이전.

    flush / near / wall_facing 외 free 가구가 매장 외곽선과 300mm 미만 이격.
    """
    from app.utils import make_rotated_rect
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    if not placed or not usable_poly or not hasattr(usable_poly, "exterior"):
        return []
    out = []
    for p in placed:
        wall_attach = p.get("wall_attachment", "free")
        direction = p.get("direction", "")
        if wall_attach in ("flush", "near") or direction == "wall_facing":
            continue
        try:
            bbox = make_rotated_rect(
                (p["center_x_mm"], p["center_y_mm"]),
                p["width_mm"], p["depth_mm"], p["rotation_deg"],
            )
        except Exception:
            continue
        wall_dist = usable_poly.exterior.distance(bbox)
        if wall_dist < 300:
            out.append(_placement_make_violation(
                "AP-407", "warning",
                p.get("object_type", "?"),
                f"벽 이격 {wall_dist:.0f}mm < 300mm",
            ))
    return out


PLACEMENT_ANTI_PATTERNS: list[dict] = [
    {"id": "AP-401", "category": "placement_review", "severity": "blocking",
     "description": "brand 매뉴얼 명시 obj 가 failed_objects 에 있음 (drop) — slot 점유한 다른 obj 양보 검토",
     "validator_type": "python", "validator": _validate_AP_401, "enabled": True, "categories_only": []},
    {"id": "AP-402", "category": "placement_review", "severity": "blocking",
     "description": "structural anchor (photo_wall / counter / partition) fail — 같은 slot 점유 obj 양보 시 안착 가능",
     "validator_type": "python", "validator": _validate_AP_402, "enabled": True, "categories_only": []},
    {"id": "AP-403", "category": "placement_review", "severity": "warning",
     "description": "placed obj 짧은 변 > entrance_width — 시공 시 반입 검증 필요",
     "validator_type": "python", "validator": _validate_AP_403, "enabled": True, "categories_only": []},
    {"id": "AP-404", "category": "placement_review", "severity": "warning",
     "description": "placed bbox 면적 비율 < 5% (intent 부실) 또는 > 70% (over-pack)",
     "validator_type": "python", "validator": _validate_AP_404, "enabled": True, "categories_only": []},
    {"id": "AP-405", "category": "placement_review", "severity": "warning",
     "description": "통합 layout sanity (LLM) — 케이스별 적극 reject 권장: "
                    "(a) structural anchor (photo_wall / counter / partition_wall) 가 카테고리 / 동선 의미와 불일치 zone "
                    "(예: 뷰티 photo_wall mid_zone standalone — magnet 역할 상실). "
                    "(b) placed_because 에 'fallback_phase' 흔적 (벽 부착 의도 깨진 강제 끼워박힘). "
                    "(c) zone 폭증 (한쪽 zone 에 obj > 70% 집중 / 다른 zone 0). "
                    "(d) 매뉴얼 명시 obj drop + default 풀 obj 가 그 자리 차지. "
                    "(e) ref_analysis 영감 반영 부재 (intents 의 inspired_by_ref 거의 빈값) — 단 ref_analysis 정상 시만.",
     "validator_type": "llm", "validator": _validate_AP_405, "enabled": True, "categories_only": []},
    # AP-406 / AP-407 — verify.py 폐기 시 이전 (보완 룰)
    {"id": "AP-406", "category": "placement_review", "severity": "warning",
     "description": "오브젝트 간 통로 부족 (pair_rules separate min_gap 미달 또는 일반 corridor < 900mm)",
     "validator_type": "python", "validator": _validate_AP_406, "enabled": True, "categories_only": []},
    {"id": "AP-407", "category": "placement_review", "severity": "warning",
     "description": "벽 이격 부족 (flush/near 외 free 가구가 벽에서 300mm 미만)",
     "validator_type": "python", "validator": _validate_AP_407, "enabled": True, "categories_only": []},
]


def run_placement_validators(state: dict) -> list[dict]:
    """placement 단계 룰 실행 (PLACEMENT_ANTI_PATTERNS 의 python 룰만)."""
    violations: list[dict] = []
    for ap in PLACEMENT_ANTI_PATTERNS:
        if not ap.get("enabled", True):
            continue
        if ap.get("validator_type") != "python":
            continue
        try:
            result = ap["validator"](None, state)  # intents 미사용 — placement 단계라 None
            if result:
                violations.extend(result)
        except Exception as e:
            logger.warning(f"[placement_reviewer] {ap['id']} validator 예외 — skip: {e}")
    return violations


def get_placement_llm_anti_patterns() -> list[dict]:
    """placement 단계 LLM 영역 룰 list (placement_reviewer 가 LLM 호출 시 description 사용)."""
    return [ap for ap in PLACEMENT_ANTI_PATTERNS if ap.get("enabled", True) and ap.get("validator_type") == "llm"]


def build_placement_designer_feedback(blocking_violations: list[dict]) -> str:
    """placement 단계 blocking violations → design 재호출 시 slot 양보 hint inject."""
    if not blocking_violations:
        return ""
    lines = ["## placement_reviewer 피드백 — 직전 시도에서 다음 obj drop. design 재호출 시 slot 양보 의도 반영:"]
    for v in blocking_violations:
        lines.append(f"- [{v['rule_id']}] {v['violation_detail']}")
    lines.append(
        "\n[slot 양보 hint] structural anchor (photo_wall / counter / partition_wall) 가 우선. "
        "같은 zone / 같은 ref_point 후보에 다른 obj 가 차지하면 그 obj 를 다른 zone 으로 옮기거나 priority 낮춤."
    )
    return "\n".join(lines)
