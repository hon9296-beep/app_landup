"""sub_path #494 — corridor graph 0 시 perimeter fallback 검증.

연화님 도커 환경에서 발견한 부동선 미생성 버그:
  도면 + placed_objects 비율로 corridor grid 가 막혀 그래프 노드 0 → 빈 list 반환.
  fallback 부재 = 부동선 시각화 자체 누락.

본 PR 은 _build_perimeter_fallback 신설 — 외곽 좌표 우회 단순 LineString 반환.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from app.nodes_small.sub_path import _build_perimeter_fallback, run as sub_path_run
from shapely.geometry import LineString


def test_perimeter_fallback_left_spine_returns_4_points():
    """spine 이 좌측 (x=2000, 매장 가운데 5000 보다 작음) → 우측 외곽 우회 경로."""
    poly = Polygon([(0, 0), (10000, 0), (10000, 8000), (0, 8000)])
    result = _build_perimeter_fallback(
        usable_poly=poly,
        spine_end=(2000, 7000),
        spine_start=(2000, 1000),
        entrance_pts=[(2000, 100)],
    )
    assert len(result) == 4, "외곽 우회 = 4 점 (spine_end + 반대편 상/하 + entrance)"
    # 첫 점 = spine_end, 마지막 점 = entrance
    assert result[0] == [2000, 7000]
    assert result[-1] == [2000, 100]
    # 가운데 두 점은 우측 (x > cx_floor=5000)
    assert result[1][0] > 5000
    assert result[2][0] > 5000


def test_perimeter_fallback_right_spine_uses_left_perimeter():
    """spine 이 우측 (x=8000) → 좌측 외곽 우회 경로."""
    poly = Polygon([(0, 0), (10000, 0), (10000, 8000), (0, 8000)])
    result = _build_perimeter_fallback(
        usable_poly=poly,
        spine_end=(8000, 7000),
        spine_start=(8000, 1000),
        entrance_pts=[(8000, 100)],
    )
    assert len(result) == 4
    # 가운데 두 점은 좌측 (x < cx_floor=5000)
    assert result[1][0] < 5000
    assert result[2][0] < 5000


def test_perimeter_fallback_handles_empty_entrance_pts():
    """entrance_pts 비어 있으면 spine_start 로 fallback."""
    poly = Polygon([(0, 0), (10000, 0), (10000, 8000), (0, 8000)])
    result = _build_perimeter_fallback(
        usable_poly=poly,
        spine_end=(2000, 7000),
        spine_start=(2500, 500),
        entrance_pts=[],
    )
    assert len(result) == 4
    # 마지막 점 = spine_start (entrance 가 없으므로)
    assert result[-1] == [2500, 500]


def test_perimeter_fallback_snaps_outside_points_inside():
    """매장 외부 점은 nearest_points 로 매장 안쪽으로 끌어당김."""
    # L-shape 매장 — 모서리 잘라낸 케이스
    poly = Polygon([(0, 0), (10000, 0), (10000, 4000), (5000, 4000), (5000, 8000), (0, 8000)])
    result = _build_perimeter_fallback(
        usable_poly=poly,
        spine_end=(1000, 7000),
        spine_start=(1000, 1000),
        entrance_pts=[(1000, 100)],
    )
    # 모든 점이 매장 안 또는 경계 위
    from shapely.geometry import Point
    for pt in result:
        p = Point(pt[0], pt[1])
        assert poly.distance(p) < 1.0, f"외부 점 검출: {pt}"


def test_run_with_dense_placed_objects_returns_fallback_path():
    """placed_objects 가 도면을 도배해 corridor 막힘 → fallback 경로 반환 (빈 list 아님)."""
    poly = Polygon([(0, 0), (5000, 0), (5000, 4000), (0, 4000)])
    artery = LineString([(500, 200), (500, 3800)])
    # 4×3 = 12 개 obstacle 로 도배
    placed = []
    for ix in range(4):
        for iy in range(3):
            cx = 500 + ix * 1100 + 800
            cy = 500 + iy * 1100 + 600
            placed.append({
                "object_type": f"obj_{ix}_{iy}",
                "center_x_mm": cx,
                "center_y_mm": cy,
                "bbox_bounds": [cx - 500, cy - 400, cx + 500, cy + 400],
            })
    state = {
        "main_artery": artery,
        "usable_poly": poly,
        "placed_objects": placed,
        "dead_zones": [],
        "entrance_mm": (500, 100),
        "all_entrances_mm": [{"coord": (500, 100), "type": "MAIN_DOOR"}],
    }
    out = sub_path_run(state)
    sub_path = out["sub_path"]
    # corridor graph 가 노드 0 일 가능성 높지만 graph 가 형성되면 정상 경로일 수도 있음.
    # 어느 쪽이든 빈 list 면 #494 회귀.
    assert isinstance(sub_path, list)
    assert len(sub_path) > 0, f"#494 회귀 — corridor 막혔을 때 fallback 미작동: {sub_path}"
