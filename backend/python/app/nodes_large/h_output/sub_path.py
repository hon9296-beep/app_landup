"""
부동선 (sub_path) 가지 동선 노드 - large 전용.

main_artery (loop spine) 가 안 지나가는 빈 공간으로 들어가는 가지 동선들.
fallback 아님 - 정상 부동선. main_artery + sub_path 동시 존재.

알고리즘 (AE 안, 2026-05-06 본질 fix):
- usable_poly 에서 가구 buffer + main_artery_corridor 둘 다 차감
- 결과 = main_artery 안 지나가고 가구도 없는 빈 공간 = 부동선 필요 영역
- MultiPolygon 분리 시 각 sub-region centroid 까지 main_artery 에서 가지
- 단일 polygon 이면 그 centroid 까지 가지 (1 가지)

변경 이력:
- 2026-05-04 - 옵션 가 (가구 difference MultiPolygon 분리 시 작은 polygon centroid). 큰 부지 가구 듬성듬성 = 단일 polygon = 0가지 한계.
- 2026-05-06 Y 안 - 각 가구별 main_artery 에서 가구 boundary 까지 가지. "가구 접근 동선" 이지 "관람 동선" X — 사용자 지적.
- 2026-05-06 AE 안 (본질) - main_artery 가 안 지나가는 빈 공간 식별 → 그 영역으로 가지. "주동선이 못 들어간 좁은 곳" = 진짜 부동선.

state 입력:
- main_artery (LineString) - walk_mm 노드 결과
- usable_poly (Polygon)
- placed_raw (list of dict with bbox_polygon) - 배치된 가구

state 출력:
- sub_path (list of list of [x, y]) - 여러 가지 동선. 각 가지 = [[start_x, start_y], [end_x, end_y]] 형식.
"""
import logging

from shapely.geometry import MultiPolygon

from app.state import LargeState

logger = logging.getLogger(__name__)

# 가구 buffer (walk_mm 의 FURNITURE_BUFFER_MM 정합)
FURNITURE_BUFFER_MM = 450

# main_artery corridor 폭 — main_artery 가 통과한다고 간주하는 영역 (LineString 의 buffer).
# 사용자 결정 2026-05-06 = 600mm (부동선이라 좁아도 됨).
MAIN_ARTERY_CORRIDOR_MM = 600

# 너무 작은 sub-region 무시 임계값 (1m² 미만).
MIN_SUB_REGION_AREA_MM2 = 1_000_000

# 가지 cap (시각 복잡 방지).
MAX_BRANCHES = 20


def run(state: LargeState) -> dict:
    """sub_path 노드 — 2026-05-06 부동선 비활성화 (사용자 결정).

    노드 자체는 살림 (TR_Idle 의 영역별 동선 작업 시 인터페이스 재활용).
    빈 list 반환 = frontend 부동선 안 그려짐.

    추후 TR_Idle 작업 = concept_area 메인 영역 (휴식 제외) 안에서 영역별 동선.
    그 작업 시 이 run() 의 본체 채움.
    """
    return {"sub_path": []}


def _branches_to_uncovered_regions(main_artery, usable_poly, placed_polygons: list) -> list:
    """main_artery 안 지나가고 가구도 없는 빈 공간 식별 후 가지 생성 (AE 안).

    흐름:
    1. inner = usable_poly - 가구 bbox.buffer(450) — 가구 차감
    2. artery_corridor = main_artery.buffer(600) — 주동선 통과 영역 (폭 600mm)
    3. uncovered = inner - artery_corridor — 주동선이 안 지나가는 빈 공간
    4. uncovered 가 MultiPolygon 이면 각 sub-region centroid 까지 main_artery 에서 가지
       단일 Polygon 이면 그 centroid 까지 1 가지
    5. sub-region 면적 < 1m² skip
    """
    # 1. 가구 차감
    inner = usable_poly
    for p in placed_polygons:
        bbox = p.get("bbox_polygon") if isinstance(p, dict) else None
        if bbox is not None and not bbox.is_empty:
            inner = inner.difference(bbox.buffer(FURNITURE_BUFFER_MM))

    # 2. main_artery corridor (주동선 통과 영역)
    artery_corridor = main_artery.buffer(MAIN_ARTERY_CORRIDOR_MM)

    # 3. 주동선 안 지나가는 빈 공간
    uncovered = inner.difference(artery_corridor)

    if uncovered.is_empty:
        logger.info("[sub_path] uncovered 빈 결과 - 가지 0개 (주동선이 모든 빈 공간 커버)")
        return []

    # 4. MultiPolygon / Polygon 분기
    if isinstance(uncovered, MultiPolygon):
        regions = list(uncovered.geoms)
        areas_m2 = [round(r.area / 1_000_000, 2) for r in regions]
        logger.info(
            f"[sub_path] uncovered = MultiPolygon ({len(regions)}개 분리), "
            f"면적 분포(m²) = {areas_m2}"
        )
    else:
        regions = [uncovered]
        logger.info(
            f"[sub_path] uncovered = 단일 Polygon (area={uncovered.area / 1_000_000:.2f}m²)"
        )

    # 5. 각 region centroid 까지 가지
    branches = []
    skipped_small = 0
    for region in regions:
        if region.area < MIN_SUB_REGION_AREA_MM2:
            skipped_small += 1
            continue

        centroid = region.centroid
        proj_dist = main_artery.project(centroid)
        start_pt = main_artery.interpolate(proj_dist)

        branches.append([
            [round(start_pt.x, 1), round(start_pt.y, 1)],
            [round(centroid.x, 1), round(centroid.y, 1)],
        ])

    if skipped_small > 0:
        logger.info(
            f"[sub_path] sub-region {skipped_small}개 면적 < {MIN_SUB_REGION_AREA_MM2 / 1_000_000:.0f}m² skip"
        )

    return branches
