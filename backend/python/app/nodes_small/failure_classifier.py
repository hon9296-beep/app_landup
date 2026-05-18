"""
실패 분류 노드 — rendy/modules/failure_classifier.py 기반.

cascade(순서 문제) vs physical(공간 부족) 실패 진단.
단독 배치 테스트(ref_point 기반)로 판별 + Choke Point 피드백 생성.
"""
import logging

from shapely.ops import unary_union

from app.state import SmallState
from app.utils import calculate_position
from app.nodes_small import placement as _placement  # 동적 상수 접근용
from app.nodes_small.placement import _validate_placement, CORRIDOR_HALF_BUFFER_MM

logger = logging.getLogger(__name__)


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


def run(state: SmallState) -> SmallState:
    """실패 오브젝트 분류 + 피드백 생성 — ref_point 기반."""
    failed = state.get("failed_objects") or []
    if not failed:
        return {"cascade_failures": [], "physical_failures": [], "choke_feedback": ""}

    eligible = state.get("eligible_objects") or []
    reference_points = state.get("reference_points") or []
    usable_poly = state.get("usable_poly")

    if not eligible or not reference_points or not usable_poly:
        return {
            "cascade_failures": [],
            "physical_failures": failed,
            "choke_feedback": "",
        }

    obj_map = {o["object_type"]: o for o in eligible}
    cascade = []
    physical = []

    # static cache 구축 (placement.py와 동일)
    dead_zones = state.get("dead_zones") or []
    main_artery = state.get("main_artery")
    entrance_buffer = state.get("entrance_buffer")
    static_obstacles = [dz for dz in dead_zones if hasattr(dz, "area")]
    if main_artery:
        # placement.py가 면적 기반으로 갱신한 최신 값 사용 (소형 450 / 중형 600)
        static_obstacles.append(main_artery.buffer(_placement.MAIN_ARTERY_HALF_BUFFER_MM))
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None

    brand_data = state.get("brand_data") or {}
    clearspace_field = brand_data.get("brand", {}).get("clearspace_mm", {})
    clearspace = clearspace_field.get("value", 600) if isinstance(clearspace_field, dict) else 600

    # Tier 1-1 Layer 1-D — placement.py/fallback.py와 동일한 기준으로 단독 배치 테스트
    # scaled_clearances + brand_clearances 전달해야 cascade vs physical 분류가 일관됨.
    # 이전엔 DIRECTIONAL_CLEARANCE 기본값(2000mm 등)으로만 판정 → 18평 photo_wall이
    # 무조건 physical로 분류 → design 재호출에서 걸러지지 않고 바로 fallback 진입.
    # 참고: reports/AD/2026-04-20_small_store_finalization_tier1.md §1
    scaled_clearances = state.get("scaled_clearances") or {}
    brand_clearances_raw = {}
    for rule in brand_data.get("placement_rules") or []:
        ot = rule.get("object_type")
        if ot and (rule.get("front_clearance_mm") is not None or rule.get("back_clearance_mm") is not None):
            brand_clearances_raw[ot] = {
                "front": rule.get("front_clearance_mm", 0),
                "back": rule.get("back_clearance_mm", 0),
            }

    for fail_entry in failed:
        obj_type = fail_entry["object_type"]
        obj = obj_map.get(obj_type)
        if not obj:
            physical.append(fail_entry)
            continue

        # 단독 배치 테스트 — 빈 공간(placed_polygons=[])에서 ref_point 순회
        # placement.py와 동일한 _validate_placement 사용
        placed_alone = False
        for rp in reference_points:
            rp_slot = _ref_point_to_slot(rp)
            rp_slot["_floor_poly"] = usable_poly
            result = calculate_position(rp_slot, obj, "wall_facing", "parallel", usable_poly)
            reason = _validate_placement(
                result, usable_poly, static_cache, [], clearspace,
                obj_type=obj_type,
                brand_clearances=brand_clearances_raw,
                scaled_clearances=scaled_clearances,
            )
            if reason == "ok":
                placed_alone = True
                break

        if placed_alone:
            cascade.append(fail_entry)
        else:
            physical.append(fail_entry)

    # Choke Point 피드백 생성
    feedback = _generate_choke_feedback(
        cascade, state.get("placed_objects") or []
    )

    logger.info(f"[failure_classifier] cascade={len(cascade)}, "
                f"physical={len(physical)}")

    # 1-3 (#523 후속): sub_graph_reasons dump — 실패 분류 결과.
    # cascade = 다른 obj 가 자리 차지 → choke. physical = 도면 자체 공간 부족.
    # design 재호출 시 cascade 만 재기획 (choke_feedback inject) → 사용자 의문 path 의 핵심 단서.
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        dump_agent_reason(state, node="failure_classifier",
                          decision="classified",
                          reason=f"cascade={len(cascade)} physical={len(physical)}",
                          context={
                              "cascade_types": [c.get("object_type") for c in cascade],
                              "physical_types": [p.get("object_type") for p in physical],
                              "cascade_reasons": [c.get("reason", "")[:80] for c in cascade],
                              "physical_reasons": [p.get("reason", "")[:80] for p in physical],
                              "choke_feedback_excerpt": feedback[:300] if feedback else "",
                              "fallback_round_next": state.get("fallback_round", 0) + 1,
                          })
    except Exception as _e:
        logger.warning(f"[failure_classifier] reason_dump 실패 — skip: {_e}")

    return {
        "cascade_failures": cascade,
        "physical_failures": physical,
        "choke_feedback": feedback,
        "fallback_round": state.get("fallback_round", 0) + 1,
    }


def _generate_choke_feedback(cascade_objects: list[dict], placed: list[dict]) -> str:
    """Choke Point 기반 Agent 3 재호출 피드백."""
    if not cascade_objects:
        return ""

    lines = []

    choke = []
    rp_fail = []
    for obj in cascade_objects:
        reason = obj.get("reason", "")
        if any(kw in reason for kw in ("병목", "choke", "통로")):
            choke.append(obj)
        else:
            rp_fail.append(obj)

    if choke:
        lines.append("## 동선 병목(Choke Point) 실패:")
        for obj in choke:
            lines.append(f"- {obj['object_type']}: 배치 시 동선이 900mm 미만으로 좁아짐")
        lines.append("→ direction을 'center'로 변경하면 벽과의 거리가 확보됩니다.")

    if rp_fail:
        lines.append("\n## 배치 위치 부족 실패:")
        for obj in rp_fail:
            lines.append(f"- {obj['object_type']}: {obj.get('reason', 'unknown')}")

    # zone별 점유 상태
    zone_counts: dict[str, int] = {}
    for p in placed:
        z = p.get("zone_label", "?")
        zone_counts[z] = zone_counts.get(z, 0) + 1
    if zone_counts:
        lines.append(f"\n현재 점유 상태: {zone_counts}")
    for zone, count in zone_counts.items():
        if count >= 4:
            lines.append(f"→ {zone}에 {count}개 집중 — 다른 zone으로 분산 권장")

    lines.append("\n다른 zone이나 direction/alignment으로 재배치를 시도하세요.")
    return "\n".join(lines)
