"""
concept_area_fix 노드 — burning_task 2단계 (수정 LLM, BSP split_tree).

역할: layout_validator 가 verdict='fix_needed' 판정 시 호출. 1차 concept_area 출력 +
위반 사유 받고 새 BSP 분할 결정 (Sonnet, split_tree 자유 결정).

흐름 (graph.py):
    lg_concept_area (Sonnet, BSP Tool) → lg_layout_validator (Haiku, 코드 룰 + LLM 룰)
       → conditional:
          ├─ ok → lg_keywords_gen
          ├─ fix_needed + retry < 2 → lg_concept_area_fix (Sonnet, BSP Tool) → 다시 lg_layout_validator
          └─ retry >= 2 → lg_keywords_gen (포기)

설계:
- docs/docs-shin/main_tasks/TR_TH/2026-05-05_[concept_area]_3노드_패턴.md
- docs/docs-shin/main_tasks/burning_task/1_[concept_area]_BSP_분할_모양_정형화.md

2026-05-06 BSP 롤백 — voronoi 실험 폐기.
"""
import logging
import os

from anthropic import Anthropic

from app.state import LargeState
from app.nodes_large.c_brand_area.concept_area import (
    AREA_TYPES,
    _apply_split_tree,
    _validate_split_tree,
    _detect_entrance_side,
)
from app.nodes_large.c_brand_area.prompts.concept_area import BSP_TOOL
from app.nodes_large.c_brand_area.prompts.concept_area_fix import (
    CONCEPT_AREA_FIX_SYSTEM,
    CONCEPT_AREA_FIX_PROMPT_TEMPLATE,
    build_violations_text,
)

logger = logging.getLogger(__name__)


def run(state: LargeState) -> dict:
    """concept_area_fix — 1차 concept_areas + 위반 사유 받고 새 BSP 분할 결정.

    return:
      - 성공: {"concept_areas": <new>, "concept_area_fix_retry_count": <inc>}
      - 실패 (LLM 오류 / 입력 부족): {"concept_area_fix_retry_count": <max>} (재시도 차단)
    """
    concept_areas = state.get("concept_areas") or []
    layout_validator_result = state.get("concept_area_check") or {}
    usable_poly = state.get("usable_poly")
    entrance_mm = state.get("entrance_mm")
    retry_count = state.get("concept_area_fix_retry_count") or 0
    ref_analysis = state.get("ref_analysis") or {}

    if not concept_areas or not usable_poly or not entrance_mm:
        logger.info("[concept_area_fix] 입력 부족 — skip")
        return {"concept_area_fix_retry_count": 99}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[concept_area_fix] API 키 없음 — skip")
        return {"concept_area_fix_retry_count": 99}

    # 공간 정보 자연어
    minx, miny, maxx, maxy = usable_poly.bounds
    width = maxx - minx
    height = maxy - miny
    aspect_ratio = width / height if height > 0 else 1.0
    shape_desc = "가로로 긴 공간" if aspect_ratio > 1.3 else (
        "세로로 긴 공간" if aspect_ratio < 0.77 else "정방형에 가까운 공간"
    )
    entrance_side = _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy)
    area_sqm = usable_poly.area / 1_000_000

    # 영역 위치 자연어 변환
    areas_description = "\n".join(
        f"- {area.get('name', '?')} ({area.get('area_ratio', 0):.0%}): "
        f"{_describe_area_position(area, entrance_mm, usable_poly)}"
        for area in concept_areas
    )

    # 위반 사유 자연어
    violations_text = build_violations_text(layout_validator_result)

    # 영역 유형
    types_text = "\n".join(
        f"- {name}: {info['description']}" for name, info in AREA_TYPES.items()
    )

    # 레퍼런스 area_size_emphasis (split_at 결정 근거 — 면적 의도 표현)
    size_emphasis_text = ""
    if ref_analysis:
        emphasis_items = ref_analysis.get("area_size_emphasis", []) or []
        if emphasis_items:
            size_emphasis_text = (
                "\n## 레퍼런스 — 영역별 면적 강조도 (split_at 비율 결정 근거)\n"
                + "\n".join(f"- {e}" for e in emphasis_items)
            )

    prompt = CONCEPT_AREA_FIX_PROMPT_TEMPLATE.format(
        area_sqm=area_sqm,
        area_sqm_pyeong=area_sqm / 3.3,
        shape_desc=shape_desc,
        aspect_ratio=aspect_ratio,
        entrance_side=entrance_side,
        areas_description=areas_description,
        violations_text=violations_text,
        types_text=types_text,
        size_emphasis_text=size_emphasis_text,
    )

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0.3,  # 1차보다 약간 ↓ — 일관성 ↑
            system=CONCEPT_AREA_FIX_SYSTEM,
            tools=[BSP_TOOL],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": prompt}],
        )
        from app.token_tracker import track_usage
        track_usage("large.concept_area_fix", response)

        if not response.content:
            logger.warning("[concept_area_fix] 빈 응답 — retry_count 증가")
            return {"concept_area_fix_retry_count": retry_count + 1}

        # Tool use 응답 파싱
        tool_input = None
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "split_by_bsp":
                tool_input = dict(block.input or {})
                break

        if not tool_input:
            logger.warning("[concept_area_fix] Tool 호출 안 됨 — retry_count 증가")
            return {"concept_area_fix_retry_count": retry_count + 1}

        split_tree = tool_input.get("split_tree")
        if not split_tree or not isinstance(split_tree, dict):
            logger.warning("[concept_area_fix] split_tree 없음 — retry_count 증가")
            return {"concept_area_fix_retry_count": retry_count + 1}

        err = _validate_split_tree(split_tree)
        if err:
            logger.warning(f"[concept_area_fix] split_tree invalid: {err} — retry_count 증가")
            return {"concept_area_fix_retry_count": retry_count + 1}

        # 2026-05-08: _apply_split_tree 가 빈 polygon 시 SplitTreeInvalidError raise (198% 차단).
        # catch 해서 retry_count 증가 후 return → LangGraph 가 다음 retry 호출 (또는 max retry 도달 시 pass).
        from app.nodes_large.c_brand_area.concept_area import SplitTreeInvalidError
        try:
            new_areas = _apply_split_tree(split_tree, usable_poly)
        except SplitTreeInvalidError as e:
            logger.warning(f"[concept_area_fix] polygon empty: {e} — retry_count 증가")
            return {"concept_area_fix_retry_count": retry_count + 1}

        # target_objects 매핑 (concept_area.py 와 동일 로직)
        for area in new_areas:
            name = area.get("name", "")
            if name in AREA_TYPES:
                area["target_objects"] = AREA_TYPES[name]["target_objects"]
            elif "target_objects" not in area:
                area["target_objects"] = ["display_table"]

        # 2026-05-08 안전망 H 강화 — 매 retry 결과 history 에 append.
        # max_retry 도달 시 history 전체 (1차 + retry 1 + retry 2) 비교해서 best 선택.
        new_retry_count = retry_count + 1
        MAX_RETRY = 2

        # 현재 fix 결과를 history 에 deepcopy 로 박음 (state mutation 방지)
        import copy as _copy
        history = list(state.get("concept_areas_history") or [])
        history.append(_copy.deepcopy(new_areas))

        if new_retry_count >= MAX_RETRY:
            # 2026-05-08: _force_merge_small_areas 폐기 — 사용자 결정 (영역 의도 보존 우선).
            # 작은 영역을 인접 영역에 polygon union 흡수하면 LLM 의도 영역 (이름/갯수) 잃음.
            # 함수 자체는 코드에 남겨둠 (필요 시 복원).

            # 안전망 H — history 전체 (1차 + retry 1 + retry 2) 중 위반 가장 적은 결과 선택.
            best_idx = min(range(len(history)), key=lambda i: _count_violations(history[i]))
            best_violations = _count_violations(history[best_idx])
            current_violations = _count_violations(new_areas)
            if best_idx != len(history) - 1 and best_violations < current_violations:
                logger.warning(
                    f"[concept_area_fix:safety H] history[{best_idx}] 가 가장 적은 위반 ({best_violations}건) "
                    f"vs 현재 retry 결과 위반 {current_violations}건 → history[{best_idx}] 채택 "
                    f"(0=1차, {MAX_RETRY}=마지막 retry)"
                )
                new_areas = [dict(a) for a in history[best_idx]]
            else:
                logger.info(
                    f"[concept_area_fix:safety H] 현재 retry 결과 ({current_violations}건) 가 best — 그대로 채택"
                )

        logger.info(
            "[concept_area_fix] retry %d → %d개 영역: %s",
            new_retry_count,
            len(new_areas),
            ", ".join(f"{a['name']}({a['area_ratio']:.0%})" for a in new_areas),
        )

        return {
            "concept_areas": new_areas,
            "concept_areas_history": history,
            "concept_area_fix_retry_count": new_retry_count,
        }

    except Exception as e:
        logger.warning(f"[concept_area_fix] LLM 호출 실패: {e}")
        return {"concept_area_fix_retry_count": retry_count + 1}


def _count_violations(areas: list) -> int:
    """위반 갯수 카운트 — 안전망 H (1차 fallback) 의 비교용.

    검증:
    - area_balance: area_ratio < 0.05 (5%) 인 영역 갯수
    - area_shape: bbox aspect > 4:1 인 영역 갯수
    합산 갯수 반환. 작을수록 좋음.
    """
    from app.nodes_large.c_brand_area.layout_validator import (
        AREA_BALANCE_THRESHOLD,
        AREA_SHAPE_ASPECT_LIMIT,
    )

    if not areas:
        return 0

    count = 0
    for a in areas:
        # area_balance
        if a.get("area_ratio", 0) < AREA_BALANCE_THRESHOLD:
            count += 1
        # area_shape
        poly = a.get("polygon_mm")
        if poly and not poly.is_empty:
            minx, miny, maxx, maxy = poly.bounds
            w, h = maxx - minx, maxy - miny
            if min(w, h) > 0:
                aspect = max(w / h, h / w)
                if aspect > AREA_SHAPE_ASPECT_LIMIT:
                    count += 1

    return count


def _force_merge_small_areas(areas: list, usable_poly, threshold: float) -> list:
    """area_ratio < threshold 영역을 인접 큰 영역에 강제 병합 (D 안, 2026-05-06).

    fix LLM 이 max_retry 도달까지 위반 못 고치면 코드가 안전망 — 작은 영역을
    boundary 공유 가장 긴 인접 큰 영역에 흡수 (polygon union).

    인접 영역 없으면 (이상 케이스) 가장 큰 영역에 흡수.
    """
    from shapely.ops import unary_union

    if not areas:
        return areas

    total_area = usable_poly.area or 1.0
    big_areas = [a for a in areas if a.get("area_ratio", 0) >= threshold]
    small_areas = [a for a in areas if a.get("area_ratio", 0) < threshold]

    if not small_areas:
        return areas

    if not big_areas:
        # 모든 영역 < threshold (이상 케이스) — 그대로 반환
        logger.warning(
            f"[concept_area_fix] 강제 병합 실패 — 모든 영역 < {threshold:.0%} (이상 케이스)"
        )
        return areas

    for small in small_areas:
        small_poly = small.get("polygon_mm")
        if small_poly is None or small_poly.is_empty:
            continue

        # 인접 영역 중 boundary 공유 가장 긴 것 찾기
        best_neighbor = None
        best_shared_length = 0.0
        for big in big_areas:
            big_poly = big.get("polygon_mm")
            if big_poly is None or big_poly.is_empty:
                continue
            shared = small_poly.boundary.intersection(big_poly.boundary)
            shared_length = getattr(shared, "length", 0.0) or 0.0
            if shared_length > best_shared_length:
                best_shared_length = shared_length
                best_neighbor = big

        if best_neighbor is None:
            # 인접 X — 가장 큰 영역에 흡수 (fallback)
            best_neighbor = max(big_areas, key=lambda a: a.get("area_ratio", 0))
            logger.info(
                f"[concept_area_fix] 강제 병합 fallback: {small.get('name')} "
                f"({small.get('area_ratio', 0):.0%}) → 가장 큰 영역 {best_neighbor.get('name')} (인접 X)"
            )
        else:
            logger.info(
                f"[concept_area_fix] 강제 병합: {small.get('name')} "
                f"({small.get('area_ratio', 0):.0%}) → {best_neighbor.get('name')} "
                f"(boundary 공유 {best_shared_length:.0f}mm)"
            )

        # polygon union + area_ratio 갱신
        merged_poly = unary_union([best_neighbor["polygon_mm"], small_poly])
        # MultiPolygon 시 가장 큰 part
        if hasattr(merged_poly, "geoms") and merged_poly.geom_type == "MultiPolygon":
            merged_poly = max(merged_poly.geoms, key=lambda g: g.area)
        best_neighbor["polygon_mm"] = merged_poly
        best_neighbor["area_ratio"] = (merged_poly.area or 0) / total_area

    return big_areas


def _describe_area_position(area: dict, entrance_mm, usable_poly) -> str:
    """영역 polygon 위치 자연어 변환 — layout_validator.py 와 같은 로직.

    좌표는 LLM 한테 안 보냄 (할루시네이션 회피).
    """
    poly = area.get("polygon_mm")
    if poly is None or poly.is_empty:
        return "위치 미상"

    centroid = poly.centroid
    dx = centroid.x - entrance_mm[0]
    dy = centroid.y - entrance_mm[1]
    distance = (dx ** 2 + dy ** 2) ** 0.5

    minx, miny, maxx, maxy = usable_poly.bounds
    width = maxx - minx
    height = maxy - miny
    diagonal = (width ** 2 + height ** 2) ** 0.5
    distance_pct = distance / diagonal if diagonal > 0 else 0

    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    side_h = "좌측" if centroid.x < cx else "우측"
    side_v = "상단" if centroid.y > cy else "하단"

    return f"{side_h} {side_v}, 입구에서 대각선 {distance_pct:.0%} 위치"
