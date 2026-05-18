"""
두 placement 결과 (place_result.json 의 placed_objects 리스트) 간 거리 metric.

용도: ref 이미지 영향 검증 — 같은 도면 + 다른 ref_analysis 조건의 결과 차이 측정.

매칭 전략 (단순 그리디):
  1. object_type 우선 매칭. 같은 type 끼리 좌표 가까운 순서로 짝지음.
  2. 매칭 안 된 객체는 unmatched (한쪽에만 존재 = 결과 차이의 신호).

거리 축:
  - centroid_distance_mm: 매칭된 객체 쌍의 좌표 유클리드 거리 (mm)
  - rotation_diff_deg: 회전 차 (mod 360, 최단 경로)
  - type_match_rate: 같은 type 매칭 비율 (0.0 ~ 1.0)

통계:
  - 평균 / 중앙값 / 최대값
  - unmatched 카운트 (양쪽)

사용:
    from app.metrics.placement_distance import compare_placements
    metric = compare_placements(result_a, result_b)
    print(metric)
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlacementMetric:
    """비교 결과 요약."""
    n_a: int = 0                      # A 의 객체 수
    n_b: int = 0                      # B 의 객체 수
    matched_pairs: int = 0            # type 매칭 + 짝지어진 쌍 수
    unmatched_a: list[str] = field(default_factory=list)   # A 에만 존재한 type
    unmatched_b: list[str] = field(default_factory=list)   # B 에만 존재한 type
    centroid_distances_mm: list[float] = field(default_factory=list)
    rotation_diffs_deg: list[float] = field(default_factory=list)
    type_match_rate: float = 0.0      # matched / max(n_a, n_b)

    def summary(self) -> dict:
        """사람이 읽는 dict 형태 (CLI / report 출력용)."""
        def stats(xs: list[float]) -> dict:
            if not xs:
                return {"mean": 0.0, "median": 0.0, "max": 0.0, "min": 0.0}
            return {
                "mean": round(statistics.fmean(xs), 1),
                "median": round(statistics.median(xs), 1),
                "max": round(max(xs), 1),
                "min": round(min(xs), 1),
            }
        return {
            "n_a": self.n_a,
            "n_b": self.n_b,
            "matched_pairs": self.matched_pairs,
            "type_match_rate": round(self.type_match_rate, 3),
            "unmatched_a": self.unmatched_a,
            "unmatched_b": self.unmatched_b,
            "centroid_distance_mm": stats(self.centroid_distances_mm),
            "rotation_diff_deg": stats(self.rotation_diffs_deg),
        }

    def is_significantly_different(self, distance_threshold_mm: float = 500.0) -> bool:
        """A vs B 가 의미 있는 차이인지 binary 판정.

        기준 (둘 중 하나라도 충족):
          - 평균 좌표 거리 ≥ threshold (default 500mm)
          - unmatched (한쪽에만 존재) 객체가 1 개 이상
          - type_match_rate < 0.7 (30% 이상 다른 type 구성)

        엣지: 양쪽 모두 비어 있으면 비교 불가 → False (판정 보류).
        """
        if self.n_a == 0 and self.n_b == 0:
            return False
        if self.unmatched_a or self.unmatched_b:
            return True
        if self.type_match_rate < 0.7:
            return True
        if self.centroid_distances_mm:
            return statistics.fmean(self.centroid_distances_mm) >= distance_threshold_mm
        return False


def _angular_diff(a: float, b: float) -> float:
    """두 회전각 (deg) 의 최단 경로 차이. 반환 [0, 180]."""
    diff = abs(a - b) % 360
    return diff if diff <= 180 else 360 - diff


def _euclid(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _extract(obj: dict) -> Optional[tuple[str, float, float, float]]:
    """placement dict → (type, cx, cy, rot). 필수 키 없으면 None."""
    obj_type = obj.get("object_type") or obj.get("type")
    cx = obj.get("center_x_mm")
    cy = obj.get("center_y_mm")
    rot = obj.get("rotation_deg", 0.0)
    if obj_type is None or cx is None or cy is None:
        return None
    return obj_type, float(cx), float(cy), float(rot or 0.0)


def compare_placements(a_objects: list[dict], b_objects: list[dict]) -> PlacementMetric:
    """A / B placed_objects 리스트 비교.

    매칭 알고리즘:
      1. type 별로 그룹화.
      2. 각 type 내부에서 A 와 B 의 객체를 좌표 거리 그리디 매칭
         (A_i 의 가장 가까운 미매칭 B_j 와 짝지음).
      3. 짝지어진 쌍의 거리/회전차 수집.
      4. type 그룹에서 한쪽에만 남은 객체는 unmatched.

    한계: 그리디라 최적 매칭 (Hungarian) 보다 약간 부정확. 18평 시나리오 (10 객체 이하) 에선
    실용상 차이 없음. 완전 최적이 필요하면 scipy.optimize.linear_sum_assignment 로 교체.
    """
    a_clean = [x for x in (_extract(o) for o in a_objects) if x is not None]
    b_clean = [x for x in (_extract(o) for o in b_objects) if x is not None]

    metric = PlacementMetric(n_a=len(a_clean), n_b=len(b_clean))

    # type 별 그룹
    by_type_a: dict[str, list[tuple[float, float, float]]] = {}
    by_type_b: dict[str, list[tuple[float, float, float]]] = {}
    for t, cx, cy, rot in a_clean:
        by_type_a.setdefault(t, []).append((cx, cy, rot))
    for t, cx, cy, rot in b_clean:
        by_type_b.setdefault(t, []).append((cx, cy, rot))

    all_types = set(by_type_a) | set(by_type_b)
    matched = 0
    for t in all_types:
        items_a = list(by_type_a.get(t, []))
        items_b = list(by_type_b.get(t, []))
        # 그리디 매칭
        while items_a and items_b:
            # A[0] 와 가장 가까운 B 인덱스 찾기
            ax, ay, arot = items_a[0]
            best_j = 0
            best_d = float("inf")
            for j, (bx, by, _brot) in enumerate(items_b):
                d = _euclid((ax, ay), (bx, by))
                if d < best_d:
                    best_d = d
                    best_j = j
            bx, by, brot = items_b[best_j]
            metric.centroid_distances_mm.append(best_d)
            metric.rotation_diffs_deg.append(_angular_diff(arot, brot))
            matched += 1
            items_a.pop(0)
            items_b.pop(best_j)
        # 한쪽에만 남은 잔여
        for _ in items_a:
            metric.unmatched_a.append(t)
        for _ in items_b:
            metric.unmatched_b.append(t)

    metric.matched_pairs = matched
    denom = max(metric.n_a, metric.n_b)
    metric.type_match_rate = (matched / denom) if denom else 0.0
    return metric
