"""
실패 분류 노드 — rendy/modules/failure_classifier.py 기반.

cascade(순서 문제) vs physical(공간 부족) 실패 진단.
단독 배치 테스트(ref_point 기반)로 판별 + Choke Point 피드백 생성.
"""
import logging

from shapely.ops import unary_union

from app.state import LargeState
from app.utils import calculate_position
from app.nodes_large.f_placement.placement import (
    _try_place_verbose,
)

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


def run(state: LargeState) -> LargeState:
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
    # 2026-05-04: main_artery 빠짐 — 사용자 의도 흐름 정합 (배치 후 동선 계산).
    dead_zones = state.get("dead_zones") or []
    entrance_buffer = state.get("entrance_buffer")
    static_obstacles = [dz for dz in dead_zones if hasattr(dz, "area")]
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None

    # 2026-04-30: clearspace 변수 제거 — Step A 정합 (small VMD 룰 호출 끊기)

    for fail_entry in failed:
        obj_type = fail_entry["object_type"]
        obj = obj_map.get(obj_type)
        if not obj:
            physical.append(fail_entry)
            continue

        # 단독 배치 테스트 — 빈 공간(placed_polygons=[])에서 ref_point 순회
        # placement.py 와 동일한 _try_place_verbose 사용 (Step A 정합)
        placed_alone = False
        for rp in reference_points:
            rp_slot = _ref_point_to_slot(rp)
            rp_slot["_floor_poly"] = usable_poly
            result = calculate_position(rp_slot, obj, "wall_facing", "parallel", usable_poly)
            reason = _try_place_verbose(
                result, usable_poly, static_cache, [],
                obj_type=obj_type,
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
