"""placement 후처리 안전망 — 2026-05-06 신설.

LLM (design) 이 prompt #강제 / #금지 무시할 경우 코드가 강제 fix.
prompt 가이드 + 코드 안전망 = 발표 시 결과 안정성 보장.

함수:
- _reject_area_mismatch (안전망 D): 영역과 부적합한 가구 reject (예: 결제에 photo_wall)
- _reject_entrance_mismatch (안전망 E): 입구 1m 이내 부적합 가구 (선반/카운터) reject
- _cap_wall_facing_ratio (안전망 F): wall_facing > 70% 면 일부 변환

호출: placement.py 의 run() 끝에서 적용.
"""
import logging

from shapely.geometry import Point

from app.nodes_large.c_brand_area.concept_area import AREA_TYPES

logger = logging.getLogger(__name__)

# 임계값 (사용자 결정 2026-05-06)
ENTRANCE_NEAR_THRESHOLD_MM = 1000  # 입구에서 1m 이내 = 입구 영역
WALL_FACING_RATIO_CAP = 0.70  # wall_facing > 70% 면 cap 발동

# 입구 부적합 가구 (입구 1m 이내 박지 X — 선반/카운터)
_NOT_AT_ENTRANCE_TYPES = {"shelf_wall", "shelf_3tier", "counter"}


def apply_safety_nets(placed_polygons: list, entrance_mm) -> list:
    """placement 후처리 안전망 (D + E + F) 모두 적용.

    placed_polygons = placement 결과 (dict list with bbox_polygon, concept_area, direction 등).
    return = 수정된 placed_polygons (일부 reject 또는 direction 변경).
    """
    if not placed_polygons:
        return placed_polygons

    # 안전망 D: 영역 부적합 가구 reject
    placed_polygons = _reject_area_mismatch(placed_polygons)

    # 안전망 E: 입구 부적합 가구 reject
    if entrance_mm:
        placed_polygons = _reject_entrance_mismatch(placed_polygons, entrance_mm)

    # 안전망 F: wall_facing 비율 cap
    placed_polygons = _cap_wall_facing_ratio(placed_polygons)

    return placed_polygons


def _reject_area_mismatch(placed_polygons: list) -> list:
    """안전망 D — 가구가 자신의 concept_area target_objects 안에 없으면 reject.

    예: 결제 영역에 박힌 photo_wall → reject.
    AREA_TYPES dict 의 target_objects 기준 검사.
    """
    if not placed_polygons:
        return placed_polygons

    rejected_count = 0
    keep = []
    for p in placed_polygons:
        concept_area = p.get("concept_area")
        obj_type = p.get("object_type")

        if not concept_area or not obj_type:
            keep.append(p)
            continue

        # AREA_TYPES 매핑 (영문 키 또는 한국어)
        from app.nodes_large.c_brand_area.concept_area import CONCEPT_AREA_LABEL_KO
        area_ko = CONCEPT_AREA_LABEL_KO.get(concept_area, concept_area)
        area_info = AREA_TYPES.get(area_ko)
        if not area_info:
            # 커스텀 영역 — 검증 skip
            keep.append(p)
            continue

        target_objects = area_info.get("target_objects", [])
        if not target_objects:
            # 빈 list (예: 휴식) — 검증 skip
            keep.append(p)
            continue

        if obj_type in target_objects:
            keep.append(p)
        else:
            # 부적합 — reject
            rejected_count += 1
            logger.info(
                f"[placement:safety D] 영역-가구 부적합 reject: "
                f"{obj_type} @ '{area_ko}' (allowed: {target_objects})"
            )

    if rejected_count > 0:
        logger.info(f"[placement:safety D] {rejected_count}개 가구 영역 부적합 reject")

    return keep


def _reject_entrance_mismatch(placed_polygons: list, entrance_mm) -> list:
    """안전망 E — 입구 1m 이내의 부적합 가구 (선반/카운터) reject.

    입구 가까이 박혀야 하는 = 첫인상 가구 (character_bbox / photo_wall / banner_stand).
    선반 / 카운터 = 동선 후미라 입구 근처 박지 X.
    """
    if not placed_polygons or not entrance_mm:
        return placed_polygons

    ent_pt = Point(*entrance_mm)
    rejected_count = 0
    keep = []
    for p in placed_polygons:
        obj_type = p.get("object_type", "")
        bbox = p.get("bbox_polygon")
        if not bbox or bbox.is_empty:
            keep.append(p)
            continue

        # 가구 boundary 의 입구 거리
        dist = bbox.distance(ent_pt)

        if dist < ENTRANCE_NEAR_THRESHOLD_MM and obj_type in _NOT_AT_ENTRANCE_TYPES:
            rejected_count += 1
            logger.info(
                f"[placement:safety E] 입구 부적합 reject: "
                f"{obj_type} @ {dist:.0f}mm < {ENTRANCE_NEAR_THRESHOLD_MM}mm"
            )
        else:
            keep.append(p)

    if rejected_count > 0:
        logger.info(f"[placement:safety E] {rejected_count}개 가구 입구 부적합 reject")

    return keep


def _cap_wall_facing_ratio(placed_polygons: list) -> list:
    """안전망 F — wall_facing direction 비율 > 70% 면 일부 가구 direction 변환.

    벽 쏠림 방지. wall_facing 가구 중 일부를 inward 또는 center 로 변경.
    근데 direction 만 바꾸면 placement 좌표는 그대로 — 시각적 효과 X.
    => 실제로는 direction 표시만 변경 (frontend / report 용).
    실제 좌표 변경은 placement 재실행 필요 (현재 안전망 범위 X).

    이 함수 = 통계 기반 경고 + direction 메타 변경. 실제 위치 변경 X.
    """
    if not placed_polygons:
        return placed_polygons

    total = len(placed_polygons)
    wall_count = sum(1 for p in placed_polygons if p.get("direction") == "wall_facing")
    ratio = wall_count / total if total > 0 else 0

    if ratio <= WALL_FACING_RATIO_CAP:
        return placed_polygons

    # cap 초과 — 일부 wall_facing → center 로 변경 (메타만, 좌표 X)
    target_wall_count = int(total * WALL_FACING_RATIO_CAP)
    excess = wall_count - target_wall_count

    converted = 0
    for p in placed_polygons:
        if converted >= excess:
            break
        if p.get("direction") == "wall_facing":
            p["direction"] = "center"
            converted += 1

    logger.info(
        f"[placement:safety F] wall_facing 비율 cap 발동: "
        f"{wall_count}/{total} ({ratio:.0%}) → {target_wall_count}/{total} ({WALL_FACING_RATIO_CAP:.0%}). "
        f"{converted}개 direction wall_facing → center 변환 (메타만, 좌표 그대로)."
    )
    return placed_polygons
