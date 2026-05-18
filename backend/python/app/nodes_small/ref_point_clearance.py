"""
ref_point 의 max_front_clearance_mm 계산 (raycasting wrapper).

ref_point_gen.py 호출 직후 state_builder 가 본 노드 호출 → 각 ref_point 에
`max_front_clearance_mm` 속성 부여. design / placement 단계에서 sort key 로 사용.

알고리즘:
  ref_point coord 에서 wall_normal_vec 방향으로 100mm 간격 ray 발사.
  매 step 에서 두 가지 검사:
    1. usable_poly 외곽 도달 (반대편 벽 / 매장 끝) → STOP, 거리 반환
    2. dead_zone polygon 진입 (계단/화장실/패널/기둥/core_access 등) → STOP, 거리 반환
  상한 5000mm 까지 가도 장애물 없으면 5000mm 반환 (충분히 깊은 ref_point).

설계 원칙 (Gemini 자문 2026-04-29 — Shadow Mode / Soft Filter):
  - hard reject 안 함 (placement 단의 step-down fallback 과 충돌 회피)
  - 정렬 key 만 사용 — 큰 max_clearance ref_point 가 먼저 시도됨
  - Shin 영역 (ref_point_gen.py) 직접 수정 안 함 — wrapper 패턴

비용:
  ref_point ~50개 × 평균 30 step × shapely.contains ~µs = 수십 ms 추가. 무시 가능.
"""
from __future__ import annotations

import logging
from typing import Iterable

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.state import SmallState
from app.utils import extract_structural_dead_zones

logger = logging.getLogger(__name__)


# 알고리즘 파라미터
RAY_STEP_MM = 100         # 100mm 간격 (정확도 vs 속도 trade-off)
RAY_MAX_MM = 5000         # 5m 상한 (일반 매장 깊이 +α)


def _cast_ray(
    rx: float, ry: float,
    nx: float, ny: float,
    usable_poly: Polygon,
    obstacle_union,
) -> int:
    """ref_point 에서 wall_normal 방향으로 ray 발사 → 첫 장애물까지 거리 (mm)."""
    for d in range(RAY_STEP_MM, RAY_MAX_MM + 1, RAY_STEP_MM):
        px = rx + nx * d
        py = ry + ny * d
        pt = Point(px, py)
        # 1. usable_poly 외각 도달
        if not usable_poly.contains(pt):
            return d - RAY_STEP_MM  # 직전 step 까지가 안전 거리
        # 2. dead_zone 진입
        if obstacle_union is not None and obstacle_union.contains(pt):
            return d - RAY_STEP_MM
    return RAY_MAX_MM


def run(state: SmallState) -> SmallState:
    """모든 ref_point 에 max_front_clearance_mm 속성 부여."""
    reference_points = state.get("reference_points") or []
    usable_poly = state.get("usable_poly")

    if not reference_points or not usable_poly:
        return {}

    # 장애물 union — dead_zone (Polygon) + structural_dz (core_access 등)
    dead_zones: Iterable = state.get("dead_zones") or []
    obstacle_polys = [dz for dz in dead_zones if hasattr(dz, "centroid")]

    # core_access 같은 structural 추가 (계단 입구 1500mm 감압 zone 등)
    structural_dz = extract_structural_dead_zones(state)
    for dz_entry in structural_dz:
        poly = dz_entry.get("poly")
        if poly is not None and hasattr(poly, "centroid"):
            obstacle_polys.append(poly)

    obstacle_union = unary_union(obstacle_polys) if obstacle_polys else None

    enriched = 0
    for rp in reference_points:
        coord = rp.get("coord")
        nvec = rp.get("wall_normal_vec")
        if not coord or not nvec:
            rp["max_front_clearance_mm"] = RAY_MAX_MM  # 정보 부족 시 보수적으로 큰 값
            continue
        rx, ry = coord
        nx, ny = nvec
        rp["max_front_clearance_mm"] = _cast_ray(rx, ry, nx, ny, usable_poly, obstacle_union)
        enriched += 1

    logger.info(
        f"[ref_point_clearance] {enriched}/{len(reference_points)} ref_point 에 max_front_clearance_mm 부여 "
        f"(step={RAY_STEP_MM}mm, max={RAY_MAX_MM}mm)"
    )

    return {"reference_points": reference_points}
