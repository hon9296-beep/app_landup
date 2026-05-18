"""
final 검증 노드 — placement reject 가 다 잡지 못한 케이스 final 안전망.

3규칙 BLOCKING (placement.py 와 중복이지만 final 재검증):
  - floor 이탈
  - dead_zone 침범
  - main_artery 침범

[verify 폐기 대신 축소 — 2026-05-05]
이전엔 6규칙 (비상구 / pair_rules 통로 / 벽간격 추가) 이었으나, 보완 룰들은 다른 곳으로 이전:
  - 비상구 → placement.py:_validate_placement (배치 시 reject)
  - pair_rules 통로 → anti_patterns.py:AP-406 (placement_reviewer warning)
  - 벽간격 → anti_patterns.py:AP-407 (placement_reviewer warning)

응답 contract (verification dict + Java enum) 는 유지. Java DB schema 무영향.
"""
import logging

from app.state import SmallState
from app.utils import make_rotated_rect
from app.nodes_small.placement import FLOOR_OVERLAP_MIN, MAIN_ARTERY_HALF_BUFFER_MM

logger = logging.getLogger(__name__)


def run(state: SmallState) -> SmallState:
    """final 검증 — floor / dead_zone / main_artery 안전망."""
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    dead_zones = state.get("dead_zones") or []
    main_artery = state.get("main_artery")

    blocking = []
    warning = []

    # bbox 복원
    polys = []
    for p in placed:
        bbox = make_rotated_rect(
            (p["center_x_mm"], p["center_y_mm"]),
            p["width_mm"], p["depth_mm"],
            p["rotation_deg"],
        )
        polys.append({**p, "bbox_polygon": bbox})

    for obj in polys:
        bbox = obj["bbox_polygon"]
        obj_type = obj["object_type"]

        # 1. floor 이탈
        if usable_poly:
            overlap = usable_poly.intersection(bbox).area
            ratio = overlap / bbox.area if bbox.area > 0 else 0
            if ratio < FLOOR_OVERLAP_MIN:
                blocking.append({
                    "object_type": obj_type, "rule": "floor_exit",
                    "severity": "blocking", "detail": f"floor 이탈 ({ratio:.0%})",
                })

        # 2. Dead Zone
        for dz in dead_zones:
            if bbox.intersects(dz):
                blocking.append({
                    "object_type": obj_type, "rule": "dead_zone",
                    "severity": "blocking", "detail": "Dead Zone 침범",
                })
                break

        # 3. Main Artery (1200mm)
        if main_artery:
            artery_buffer = main_artery.buffer(MAIN_ARTERY_HALF_BUFFER_MM)
            if bbox.intersects(artery_buffer):
                blocking.append({
                    "object_type": obj_type, "rule": "main_artery",
                    "severity": "blocking", "detail": "대피로 1200mm 침범",
                })

    passed = len(blocking) == 0
    logger.info(f"[verify] {'PASS' if passed else 'FAIL'}: {len(blocking)} blocking (final 안전망)")

    return {
        "verification": {
            "passed": passed,
            "blocking": blocking,
            "warning": warning,
            "checked_count": len(polys),
        },
    }
