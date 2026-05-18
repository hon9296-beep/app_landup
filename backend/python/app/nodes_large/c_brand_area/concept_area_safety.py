"""concept_area 후처리 안전망 — 2026-05-06 신설.

LLM 이 prompt #강제 / #금지 무시할 경우 코드가 강제 fix.
prompt 가이드 + 코드 안전망 = 발표 시 결과 안정성 보장.

함수:
- _force_checkout_position (안전망 A): 결제 영역이 입구 가장 먼 위치 아니면 name swap
- _absorb_strip_areas (안전망 B): aspect > 4:1 strip 영역을 인접 영역에 흡수
- _force_entrance_first_impression (안전망 C): 입구 가까운 영역 name 이 결제/휴식이면 첫인상 영역과 swap

호출: concept_area.py 의 run() 끝에서 적용.
"""
import logging

from shapely.geometry import Point
from shapely.ops import unary_union

from app.nodes_large.c_brand_area.layout_validator import AREA_SHAPE_ASPECT_LIMIT

logger = logging.getLogger(__name__)

# 2026-05-08: STRIP_ASPECT_LIMIT 변수 폐기 — AREA_SHAPE_ASPECT_LIMIT (layout_validator) 와 통일.
# 사유: 같은 의미 (영역 길쭉함 임계) 인데 두 변수로 따로 정의되어 있어 5/8 불일치 사고 발생
# (validator 3.5 로 강화, safety 4.0 그대로 → 198% 폭증). 한 곳에서 관리하도록 통일.
# _absorb_strip_areas 함수 본체에서 직접 AREA_SHAPE_ASPECT_LIMIT 사용.

# 첫인상 영역 후보 (입구 가까이 박혀야 자연)
_FIRST_IMPRESSION_NAMES = {"포토", "체험"}
# 입구 부적합 영역 (입구 가까이 X — 카운터는 동선 후미, 휴식은 안쪽)
_NOT_AT_ENTRANCE_NAMES = {"결제", "휴식"}


def apply_safety_nets(areas: list, entrance_mm, usable_poly) -> list:
    """concept_area 후처리 안전망 (A + C) 적용.

    순서:
    1. A (결제↔굿즈 인접 강제) — 두 영역 boundary 공유 X 면 인접 영역과 name swap.
    2. C (입구 첫인상 swap) — name 만 swap.

    2026-05-08: B (_absorb_strip_areas) 폐기 — 사용자 결정.
      strip 영역을 인접 영역에 polygon union 흡수하면 LLM 의도 영역 (이름/갯수) 잃음.
      strip 발생 자체를 prompt 강화로 줄이는 방향.
      _absorb_strip_areas 함수는 코드에 남겨둠 (필요 시 복원).
    """
    if not areas or not entrance_mm:
        return areas

    # 안전망 A: 결제↔굿즈 인접 강제
    areas = _force_checkout_retail_adjacent(areas)

    # 안전망 C: 입구 첫인상 강제
    areas = _force_entrance_first_impression(areas, entrance_mm)

    return areas


def _force_checkout_retail_adjacent(areas: list) -> list:
    """안전망 A — 결제와 굿즈판매가 boundary 공유 안 하면 인접하게 name swap.

    배경: 결제 동선 = 굿즈판매 후 결제. 두 영역이 인접해야 자연스러움.
    LLM 이 두 영역을 멀리 박으면 코드가 강제 인접화.

    알고리즘:
    1. 결제 / 굿즈판매 영역 둘 다 있는지 확인. 한 쪽이라도 없으면 skip.
    2. 두 영역 boundary 공유 길이 검사. > 0 이면 이미 인접 → skip.
    3. 결제 영역의 boundary 공유 가장 긴 영역 (굿즈판매 외) 찾기.
    4. 그 인접 영역의 name 과 굿즈판매 영역의 name + target_objects swap.
    5. 결과: 결제 옆에 굿즈판매가 박힘 (polygon 그대로, name 만 교체).
    """
    if not areas:
        return areas

    # 결제 / 굿즈판매 영역 찾기
    checkout_idx = None
    retail_idx = None
    for i, a in enumerate(areas):
        if a.get("name") == "결제":
            checkout_idx = i
        elif a.get("name") == "굿즈판매":
            retail_idx = i

    if checkout_idx is None or retail_idx is None:
        return areas  # 둘 중 하나라도 없으면 skip

    checkout_poly = areas[checkout_idx].get("polygon_mm")
    retail_poly = areas[retail_idx].get("polygon_mm")
    if not checkout_poly or not retail_poly or checkout_poly.is_empty or retail_poly.is_empty:
        return areas

    # 인접 검사 (boundary 공유 길이)
    shared = checkout_poly.boundary.intersection(retail_poly.boundary)
    shared_len = getattr(shared, "length", 0.0) or 0.0
    if shared_len > 0:
        return areas  # 이미 인접

    # 결제 영역의 boundary 공유 가장 긴 다른 영역 찾기 (굿즈판매 제외)
    best_neighbor = None
    best_shared = 0.0
    for i, a in enumerate(areas):
        if i == checkout_idx or i == retail_idx:
            continue
        nb_poly = a.get("polygon_mm")
        if not nb_poly or nb_poly.is_empty:
            continue
        sh = checkout_poly.boundary.intersection(nb_poly.boundary)
        sh_len = getattr(sh, "length", 0.0) or 0.0
        if sh_len > best_shared:
            best_shared = sh_len
            best_neighbor = i

    if best_neighbor is None:
        logger.info(
            "[concept_area:safety A] 결제와 굿즈 멀음 — 결제 인접 영역도 없음 (swap 불가)"
        )
        return areas

    # name + target_objects swap (결제 인접 영역 ↔ 굿즈판매)
    n_neighbor = areas[best_neighbor]["name"]
    n_retail = areas[retail_idx]["name"]  # "굿즈판매"
    t_neighbor = areas[best_neighbor].get("target_objects", [])
    t_retail = areas[retail_idx].get("target_objects", [])
    areas[best_neighbor]["name"] = n_retail
    areas[retail_idx]["name"] = n_neighbor
    areas[best_neighbor]["target_objects"] = t_retail
    areas[retail_idx]["target_objects"] = t_neighbor

    logger.info(
        f"[concept_area:safety A] 결제↔굿즈 인접 강제 swap: "
        f"'{n_neighbor}'↔'{n_retail}' "
        f"(결제 옆 = '{n_retail}' 로 변경, 기존 굿즈 위치 = '{n_neighbor}' 로)"
    )
    return areas


def _absorb_strip_areas(areas: list, usable_poly) -> list:
    """안전망 B — aspect > 4:1 strip 영역을 인접 큰 영역에 polygon union 흡수.

    알고리즘:
    1. 각 영역 bbox aspect 계산 (max(w/h, h/w)).
    2. aspect > 4:1 영역을 strip 으로 분류.
    3. 각 strip 을 boundary 공유 가장 긴 인접 영역에 polygon union.
    4. strip 영역은 list 에서 제거.
    """
    if not areas or len(areas) < 2:
        return areas

    total_area = usable_poly.area if usable_poly else 1.0

    strip_indices = []
    for i, a in enumerate(areas):
        poly = a.get("polygon_mm")
        if not poly or poly.is_empty:
            continue
        minx, miny, maxx, maxy = poly.bounds
        w, h = maxx - minx, maxy - miny
        if min(w, h) <= 0:
            continue
        aspect = max(w / h, h / w)
        if aspect > AREA_SHAPE_ASPECT_LIMIT:
            strip_indices.append(i)

    if not strip_indices:
        return areas

    # strip 흡수 — 각 strip 마다 인접 큰 영역 찾아 union
    strip_indices_set = set(strip_indices)
    big_indices = [i for i in range(len(areas)) if i not in strip_indices_set]

    if not big_indices:
        # 모두 strip — 흡수 불가능
        logger.warning(f"[concept_area:safety B] 모든 영역이 strip — 흡수 skip")
        return areas

    for s_idx in strip_indices:
        small_poly = areas[s_idx].get("polygon_mm")
        if not small_poly:
            continue

        # boundary 공유 가장 긴 big 영역 찾기
        best_big = None
        best_shared = 0.0
        for b_idx in big_indices:
            big_poly = areas[b_idx].get("polygon_mm")
            if not big_poly:
                continue
            shared = small_poly.boundary.intersection(big_poly.boundary)
            shared_len = getattr(shared, "length", 0.0) or 0.0
            if shared_len > best_shared:
                best_shared = shared_len
                best_big = b_idx

        if best_big is None:
            # 인접 X — 가장 큰 영역에 fallback
            best_big = max(big_indices, key=lambda i: areas[i].get("area_ratio", 0))

        # union
        target = areas[best_big]
        merged = unary_union([target["polygon_mm"], small_poly])
        if hasattr(merged, "geoms") and merged.geom_type == "MultiPolygon":
            merged = max(merged.geoms, key=lambda g: g.area)
        target["polygon_mm"] = merged
        target["area_ratio"] = (merged.area or 0) / total_area

        logger.info(
            f"[concept_area:safety B] strip 흡수: "
            f"'{areas[s_idx].get('name', '?')}' (aspect>{AREA_SHAPE_ASPECT_LIMIT:.0f}:1) "
            f"→ '{target.get('name', '?')}' (boundary 공유 {best_shared:.0f}mm)"
        )

    # strip 영역 제거 (역순으로 pop 해야 인덱스 안 깨짐)
    for s_idx in sorted(strip_indices, reverse=True):
        areas.pop(s_idx)

    return areas


def _force_entrance_first_impression(areas: list, entrance_mm) -> list:
    """안전망 C — 입구 가장 가까운 영역 name 이 결제/휴식이면 첫인상 영역과 swap.

    알고리즘:
    1. 모든 영역의 centroid 입구 거리 계산.
    2. 가장 가까운 영역의 name 이 _NOT_AT_ENTRANCE_NAMES 면:
       - 다른 영역 중 name 이 _FIRST_IMPRESSION_NAMES 인 영역 찾기.
       - 두 영역 name + target_objects swap.
    """
    if not areas:
        return areas

    ent_pt = Point(*entrance_mm)
    distances = []
    for a in areas:
        poly = a.get("polygon_mm")
        if poly and not poly.is_empty:
            distances.append(poly.centroid.distance(ent_pt))
        else:
            distances.append(float("inf"))

    nearest_idx = min(range(len(areas)), key=lambda i: distances[i])
    nearest_name = areas[nearest_idx].get("name", "")

    if nearest_name not in _NOT_AT_ENTRANCE_NAMES:
        # 이미 첫인상 또는 적합 영역 — swap 불필요
        return areas

    # 첫인상 영역 후보 찾기
    first_imp_idx = None
    for i, a in enumerate(areas):
        if i != nearest_idx and a.get("name") in _FIRST_IMPRESSION_NAMES:
            first_imp_idx = i
            break

    if first_imp_idx is None:
        # 첫인상 영역 없음 — swap 불가
        logger.info(
            f"[concept_area:safety C] 입구 가까이 '{nearest_name}' 인데 "
            f"첫인상 영역 (포토/체험) 없음 — swap skip"
        )
        return areas

    # name + target_objects swap
    n1, n2 = areas[nearest_idx]["name"], areas[first_imp_idx]["name"]
    t1 = areas[nearest_idx].get("target_objects", [])
    t2 = areas[first_imp_idx].get("target_objects", [])
    areas[nearest_idx]["name"] = n2
    areas[first_imp_idx]["name"] = n1
    areas[nearest_idx]["target_objects"] = t2
    areas[first_imp_idx]["target_objects"] = t1

    logger.info(
        f"[concept_area:safety C] 입구 첫인상 강제 swap: '{n1}'↔'{n2}'"
    )
    return areas
