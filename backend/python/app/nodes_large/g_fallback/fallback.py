"""
Fallback 노드 — rendy/modules/failure_handler.py 강화.

3단계 재시도 (ref_point 기반):
  Phase 1: zone 무시, 전체 ref_point 순회 (wall_facing + parallel)
  Phase 2: direction 변경 (inward + perpendicular)
  Phase 3: 결정론적 최후 — walk_mm 가장 먼 ref_point에 강제 배치
"""
import logging

from app.state import LargeState
from app.utils import calculate_position, serialize_placement
from app.nodes_large.f_placement.placement import (
    _try_place_verbose,
    DEFAULT_HEIGHT_MM,
)

logger = logging.getLogger(__name__)

MAX_FALLBACK_ROUNDS = 3  # Rendy 기준 3회. 통합 시 2회로 줄었으나 원작자 판단 복원.


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


def run(state: LargeState) -> LargeState:
    """실패 오브젝트 재배치 시도 — ref_point 기반."""
    failed = state.get("failed_objects") or []
    if not failed:
        return {"fallback_round": 0}

    current_round = state.get("fallback_round", 0)
    if current_round >= MAX_FALLBACK_ROUNDS:
        logger.info(f"[fallback] max rounds reached ({MAX_FALLBACK_ROUNDS})")
        return {}

    eligible = state.get("eligible_objects") or []
    reference_points = state.get("reference_points") or []
    usable_poly = state.get("usable_poly")
    placed_raw = list(state.get("placed_raw") or [])
    placed_objects = list(state.get("placed_objects") or [])
    brand_data = state.get("brand_data") or {}
    pair_rules = brand_data.get("pair_rules") or []

    # static cache (placement.py와 동일)
    # 2026-05-04: main_artery 빠짐 — 사용자 의도 흐름 정합 (배치 후 동선 계산).
    # walk_mm 이 placement 다음으로 이동됐으므로 fallback 단계도 main_artery 사전 차단 X.
    from shapely.ops import unary_union
    dead_zones = state.get("dead_zones") or []
    entrance_buffer = state.get("entrance_buffer")
    static_obstacles = [dz for dz in dead_zones if hasattr(dz, "area")]
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None
    # 2026-04-30: clearspace 변수 제거 — Step A 정합 (small VMD 룰 호출 끊기)

    if not usable_poly or not reference_points:
        return {"fallback_round": current_round + 1}

    obj_map = {o["object_type"]: o for o in eligible}
    still_failed = []
    new_placed = []

    # 3단계 시도 전략
    strategies = [
        ("wall_facing", "parallel"),    # Phase 1: 기본
        ("inward", "perpendicular"),    # Phase 2: direction 변경
        ("center", "none"),             # Phase 3: 최후 수단
    ]

    # walk_mm 내림차순 정렬 (먼 ref_point부터 — 여유 공간 가능성 높음)
    sorted_rps = sorted(reference_points, key=lambda rp: rp.get("walk_mm", 0), reverse=True)

    for fail_entry in failed:
        obj_type = fail_entry["object_type"]
        obj = obj_map.get(obj_type)
        if not obj:
            still_failed.append(fail_entry)
            continue

        placed = False
        for direction, alignment in strategies:
            if placed:
                break

            for rp in sorted_rps:
                rp_slot = _ref_point_to_slot(rp)
                rp_slot["_floor_poly"] = usable_poly

                result = calculate_position(rp_slot, obj, direction, alignment, usable_poly)

                # 검증 (placement.py 와 동일한 _try_place_verbose 사용 — Step A 정합)
                reason = _try_place_verbose(
                    result, usable_poly, static_cache, placed_raw,
                    obj_type=obj_type, pair_rules=pair_rules,
                )
                if reason != "ok":
                    continue

                entry = {
                    **result,
                    "anchor_key": rp["id"],
                    "zone_label": rp.get("zone_label", "mid_zone"),
                    "concept_area_id": rp.get("concept_area_id"),  # 2026-05-01 Phase 2
                    "concept_area": rp.get("concept_area"),         # 2026-05-01 Phase 4
                    "direction": direction,
                    "placed_because": f"fallback_phase_{strategies.index((direction, alignment)) + 1}",
                    "height_mm": obj.get("height_mm", DEFAULT_HEIGHT_MM),
                    "category": obj.get("category", ""),
                }
                placed_raw.append(entry)
                placed_objects.append(serialize_placement(entry))
                new_placed.append(obj_type)
                placed = True
                break

        if not placed:
            still_failed.append(fail_entry)

    logger.info(f"[fallback] round {current_round+1}: {len(new_placed)} recovered, {len(still_failed)} still failed")

    return {
        "placed_objects": placed_objects,
        "placed_raw": placed_raw,
        "failed_objects": still_failed,
        # fallback_round는 failure_classifier에서 관리
    }
