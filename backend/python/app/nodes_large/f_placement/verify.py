"""
검증 노드 — Rendy 코드 베이스 + buildup/violations.py 강화.

검증 규칙 (2026-04-30 슬림화 — small VMD 룰 호출 끊기):
  BLOCKING: floor 이탈 / dead zone / main artery / 비상구 2단계 (소방법 + 물리 무결성)
  WARNING:  pair_rules separate (사용자 매뉴얼 의도)

폐기 (호출 끊기, 정의 보존):
  - 기본 보조동선 (CORRIDOR_HALF_BUFFER_MM × 2) — small VMD 룰
  - 벽체 이격 300mm (WALL_CLEARANCE_MM) — small VMD 룰
"""
import logging

from shapely.geometry import Point, box as shapely_box

from app.state import LargeState
from app.utils import make_rotated_rect
from app.nodes_large.f_placement.placement import (
    _find_pair_rule, FLOOR_OVERLAP_MIN,
    MAIN_ARTERY_HALF_BUFFER_MM,
)

# 벽체 최소 이격 (flush/near 제외)
WALL_CLEARANCE_MM = 300
# 비상구 최소 거리
EMERGENCY_EXIT_MIN_DIST_MM = 1200
# 비상구 전면 복도 사각형 (half-width, half-depth)
EMERGENCY_CORRIDOR_HALF_W_MM = 1200
EMERGENCY_CORRIDOR_HALF_D_MM = 600

logger = logging.getLogger(__name__)


def run(state: LargeState) -> LargeState:
    """최종 검증."""
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    dead_zones = state.get("dead_zones") or []
    main_artery = state.get("main_artery")
    brand_data = state.get("brand_data") or {}
    pair_rules = brand_data.get("pair_rules") or []

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

    for i, obj in enumerate(polys):
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

        # 3. Main Artery 1200mm
        if main_artery:
            artery_buffer = main_artery.buffer(MAIN_ARTERY_HALF_BUFFER_MM)
            if bbox.intersects(artery_buffer):
                blocking.append({
                    "object_type": obj_type, "rule": "main_artery",
                    "severity": "blocking", "detail": "대피로 1200mm 침범",
                })

        # 4. 오브젝트 간 통로 (pair_rules 기반)
        for j, other in enumerate(polys):
            if i >= j:
                continue
            other_type = other["object_type"]
            pair = _find_pair_rule(obj_type, other_type, None, pair_rules)
            gap = bbox.distance(other["bbox_polygon"])

            if pair and pair["relation"] == "join":
                # join 쌍: 통로 검사 스킵
                continue
            elif pair and pair["relation"] == "separate":
                # separate 쌍: min_gap_mm 기준 (사용자 매뉴얼 의도 강제)
                min_gap = pair["min_gap_mm"]
                if 0 < gap < min_gap:
                    warning.append({
                        "object_type": f"{obj_type}↔{other_type}",
                        "rule": "pair_separate", "severity": "warning",
                        "detail": f"분리 간격 {gap:.0f}mm < {min_gap}mm",
                    })
            # 기본 보조동선 규칙 (CORRIDOR_HALF_BUFFER_MM × 2) 호출 제거 — 2026-04-30 small VMD 룰

        # 5. 벽체 이격 300mm 호출 제거 — 2026-04-30 small VMD 룰 (정의 보존)

        # 6. 비상구 2단계 검증 (buildup/violations.py)
        #    Step 1: 거리 체크 — 비상구에서 1200mm 이내 오브젝트
        #    Step 2: 복도 차단 — 비상구 전면 복도 사각형과 교차
        for ent in (state.get("all_entrances_mm") or []):
            if ent.get("type") != "EMERGENCY_EXIT":
                continue
            ex, ey = ent["coord"]
            ent_pt = Point(ex, ey)
            dist = ent_pt.distance(bbox)
            if dist < EMERGENCY_EXIT_MIN_DIST_MM:
                blocking.append({
                    "object_type": obj_type, "rule": "emergency_exit_proximity",
                    "severity": "blocking",
                    "detail": f"비상구에서 {dist:.0f}mm (최소 {EMERGENCY_EXIT_MIN_DIST_MM}mm 필요)",
                })
            # 복도 차단: 비상구 전면 사각형
            corridor_rect = shapely_box(
                ex - EMERGENCY_CORRIDOR_HALF_W_MM, ey - EMERGENCY_CORRIDOR_HALF_D_MM,
                ex + EMERGENCY_CORRIDOR_HALF_W_MM, ey + EMERGENCY_CORRIDOR_HALF_D_MM,
            )
            if bbox.intersects(corridor_rect) and dist < EMERGENCY_CORRIDOR_HALF_W_MM * 2:
                blocking.append({
                    "object_type": obj_type, "rule": "emergency_corridor_block",
                    "severity": "blocking",
                    "detail": "비상구 전면 복도 차단",
                })

    passed = len(blocking) == 0
    logger.info(f"[verify] {'PASS' if passed else 'FAIL'}: {len(blocking)} blocking, {len(warning)} warnings")

    return {
        "verification": {
            "passed": passed,
            "blocking": blocking,
            "warning": warning,
            "checked_count": len(polys),
        },
    }
