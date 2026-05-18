"""
영역 배치 검증 노드 (lg_layout_validator) — large 전용.

lg_concept_area 다음, lg_keywords_gen 이전에 실행.
좌표 → 자연어 변환 후 LLM 한테 영역 배치 검증 요청.
state["concept_area_check"] 에 결과 박음 (design 노드에서 prompt 에 inject).

자율도 우선 정책: 강제 차단 X, warning log + design 자율 보정.
설계: docs/docs-shin/main_tasks/공통/2026-05-03_[프롬프트_노드]_영역_배치_검증.md

2026-05-05 burning_task 2단계 첫 번째 작업 — 코드 룰 + LLM 룰 분리:
  명확한 룰 (거리/면적/aspect) = 코드 검증 (Shapely, 100% catch).
  모호한 룰 (동선 자연스러움) = LLM 자율.
  → LLM 자율의 한계 (자연어 추론 누락) 우회.
"""
import logging
import os

from anthropic import Anthropic
from shapely.geometry import Point

from app.state import LargeState
from app.nodes_large.c_brand_area.prompts.layout_validator import (
    LAYOUT_VALIDATOR_SYSTEM,
    LAYOUT_VALIDATOR_PROMPT_TEMPLATE,
    LAYOUT_VALIDATION_RULES,
    build_validation_questions_text,
    build_tool_schema,
)

logger = logging.getLogger(__name__)


# 2026-05-05 burning_task 2단계 첫 번째 작업 — 코드 룰 임계값 (사용자 결정).
# 2026-05-06: 8% → 5% 완화 (사용자 결정 — 결제 같은 작은 영역 자연 허용)
AREA_BALANCE_THRESHOLD = 0.05   # 5% 미만 영역 = WARN
AREA_SHAPE_ASPECT_LIMIT = 4.0   # aspect ratio 4:1 초과 = WARN (2026-05-08: 3.5:1 → 4:1 임시 롤백. safety B STRIP_ASPECT_LIMIT=4.0 과 통일. 198% 트리거 가설 검증)


def _check_code_rules(
    concept_areas: list,
    entrance_mm,
) -> dict:
    """코드 사전 검증 — 명확한 룰 4개 (LLM 자율 무시, Shapely 계산 100% catch).

    검증 룰:
    - welcome_at_entrance: 입구 가장 가까운 영역 = 맞이/체험?
    - checkout_distance: 입구 가장 먼 영역 = 결제?
    - area_balance: 8% 미만 영역 X?
    - area_shape: aspect ratio 3:1 이하?

    Returns: dict (각 룰별 OK/WARN + reason)
    """
    result: dict = {}
    if not concept_areas or not entrance_mm:
        return result

    ent_pt = Point(*entrance_mm)

    # ── 1. welcome_at_entrance — 2026-05-06 폐기 (맞이존 default 폐기 — 사용자 결정).
    # brand 매뉴얼에 입구 영역 명시 시 추후 동적 룰로 부활 가능.
    # 검증 대상에서 빠짐. layout_validator prompt 도 룰 list 에서 제거.
    valid_areas = [a for a in concept_areas if a.get("polygon_mm") and not a["polygon_mm"].is_empty]
    if valid_areas:
        # ── 2. checkout_distance ──
        farthest = max(valid_areas, key=lambda a: a["polygon_mm"].centroid.distance(ent_pt))
        farthest_name = farthest.get("name", "")
        if farthest_name != "결제":
            result["checkout_distance"] = "WARN"
            result["checkout_distance_reason"] = f"입구 가장 먼 영역 = {farthest_name} (필수: 결제)"
        else:
            result["checkout_distance"] = "OK"
            result["checkout_distance_reason"] = f"입구 가장 먼 영역 = {farthest_name}"

    # ── 3. area_balance — 8% 미만 영역 검출 ──
    small_areas = [a for a in concept_areas if a.get("area_ratio", 0) < AREA_BALANCE_THRESHOLD]
    if small_areas:
        names_with_ratio = [(a.get("name", "?"), a.get("area_ratio", 0)) for a in small_areas]
        result["area_balance"] = "WARN"
        result["area_balance_reason"] = (
            f"{len(small_areas)}개 영역이 {AREA_BALANCE_THRESHOLD:.0%} 미만: "
            + ", ".join(f"{n}({r:.0%})" for n, r in names_with_ratio)
        )
    else:
        result["area_balance"] = "OK"
        result["area_balance_reason"] = f"모든 영역 {AREA_BALANCE_THRESHOLD:.0%} 이상"

    # ── 4. area_shape — aspect ratio 3:1 초과 검출 ──
    bad_shapes = []
    for area in concept_areas:
        poly = area.get("polygon_mm")
        if not poly or poly.is_empty:
            continue
        minx, miny, maxx, maxy = poly.bounds
        w, h = maxx - minx, maxy - miny
        if min(w, h) <= 0:
            bad_shapes.append((area.get("name", "?"), 999.0))
            continue
        aspect = max(w / h, h / w)
        if aspect > AREA_SHAPE_ASPECT_LIMIT:
            bad_shapes.append((area.get("name", "?"), aspect))
    if bad_shapes:
        result["area_shape"] = "WARN"
        result["area_shape_reason"] = (
            f"{len(bad_shapes)}개 영역이 aspect {AREA_SHAPE_ASPECT_LIMIT:.0f}:1 초과 (길쭉 strip): "
            + ", ".join(f"{n}({a:.1f}:1)" for n, a in bad_shapes)
        )
    else:
        result["area_shape"] = "OK"
        result["area_shape_reason"] = f"모든 영역 모양 aspect {AREA_SHAPE_ASPECT_LIMIT:.0f}:1 이하"

    # ── 5. screening_square — 상영 영역 정사각형 (aspect 0.7-1.3) ──
    SCREENING_ASPECT_MIN = 0.7
    SCREENING_ASPECT_MAX = 1.3
    screening_areas = [a for a in concept_areas if a.get("name") == "상영"]
    if screening_areas:
        bad_screen = []
        for area in screening_areas:
            poly = area.get("polygon_mm")
            if not poly or poly.is_empty:
                continue
            minx, miny, maxx, maxy = poly.bounds
            w, h = maxx - minx, maxy - miny
            if min(w, h) <= 0:
                continue
            aspect = w / h
            if aspect < SCREENING_ASPECT_MIN or aspect > SCREENING_ASPECT_MAX:
                bad_screen.append((area.get("name", "?"), aspect))
        if bad_screen:
            result["screening_square"] = "WARN"
            result["screening_square_reason"] = (
                f"상영 영역 aspect 1:1 근사 X: "
                + ", ".join(f"{n}({a:.2f})" for n, a in bad_screen)
                + f" (적정: {SCREENING_ASPECT_MIN}-{SCREENING_ASPECT_MAX})"
            )
        else:
            result["screening_square"] = "OK"
            result["screening_square_reason"] = "상영 영역 정사각형 근사 OK"
    else:
        result["screening_square"] = "OK"
        result["screening_square_reason"] = "상영 영역 없음 — 검증 skip"

    return result


def run(state: LargeState) -> dict:
    """concept_areas 의 위치 배치 LLM 검증 → state["concept_area_check"] 박음.

    Shin 결정 (2026-05-04, 2026-05-05 갱신):
    - 호출 빈도: 매 요청마다 (무조건)
    - 모델: claude-haiku-4-5 (2026-05-05 TR_TH 트랙 1 - Sonnet → Haiku 비용 절약, 단순 룰 판정 충분)
    - temperature: 0.1 (일관성 + 약간 자연스러움)
    - 자율도 우선: 강제 차단 X. verdict='fix_needed' 시 concept_area_fix 노드 호출 (3노드 패턴).
    """
    concept_areas = state.get("concept_areas") or []
    entrance_mm = state.get("entrance_mm")
    usable_poly = state.get("usable_poly")

    if not concept_areas or not entrance_mm or not usable_poly:
        logger.info("[lg_layout_validator] 입력 부족 — skip")
        return {"concept_area_check": {}}

    # 2026-05-05 burning_task 2단계 — 코드 룰 먼저 (LLM 호출 실패해도 catch 보장).
    code_result = _check_code_rules(concept_areas, entrance_mm)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[lg_layout_validator] API 키 없음 — 코드 룰 결과만 반환")
        return {"concept_area_check": code_result}

    # 영역 위치 자연어 변환 — 좌표는 LLM 한테 안 보냄
    areas_description = "\n".join(
        f"- {area.get('name', '?')} ({area.get('area_ratio', 0):.0%}): "
        f"{_describe_area_position(area, entrance_mm, usable_poly)}"
        for area in concept_areas
    )

    # 공간 형태 자연어
    minx, miny, maxx, maxy = usable_poly.bounds
    width = maxx - minx
    height = maxy - miny
    aspect_ratio = width / height if height > 0 else 1.0
    shape_desc = "가로로 긴 공간" if aspect_ratio > 1.3 else (
        "세로로 긴 공간" if aspect_ratio < 0.77 else "정방형에 가까운 공간"
    )
    entrance_side = _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy)
    area_sqm = usable_poly.area / 1_000_000

    prompt = LAYOUT_VALIDATOR_PROMPT_TEMPLATE.format(
        area_sqm=area_sqm,
        shape_desc=shape_desc,
        aspect_ratio=aspect_ratio,
        entrance_side=entrance_side,
        areas_description=areas_description,
        validation_questions=build_validation_questions_text(),
    )

    # LLM 호출 (Tool use — 출력 형식 강제)
    tool = build_tool_schema()
    client = Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",  # 2026-05-05 TR_TH - Sonnet → Haiku (비용 ↓, 단순 룰 판정 충분)
            max_tokens=1024,
            temperature=0.1,
            system=LAYOUT_VALIDATOR_SYSTEM,
            tools=[tool],
            tool_choice={"type": "tool", "name": "validate_concept_area_layout"},
            messages=[{"role": "user", "content": prompt}],
        )
        from app.token_tracker import track_usage
        track_usage("large.layout_validator", response)

        # Tool use 응답 파싱 — block 중 type=="tool_use" 의 input 사용
        result = {}
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                result = dict(block.input or {})
                break

        # 2026-05-05 burning_task 2단계 첫 번째 작업 — 코드 룰 결과로 덮어쓰기.
        # Haiku 자율 판정 한계 (명확 룰도 누락) 우회 — 코드가 100% catch.
        # LLM 의 모호 룰 (flow_natural) 만 자율 유지.
        # code_result 는 위에서 이미 계산됨 (LLM 호출 실패 fallback 대비).
        for k, v in code_result.items():
            result[k] = v

        # WARN 항목만 로그
        warned = [r["label"] for r in LAYOUT_VALIDATION_RULES if result.get(r["key"]) == "WARN"]
        if warned:
            logger.warning(f"[lg_layout_validator] WARN: {warned}")
        else:
            logger.info("[lg_layout_validator] 모든 기준 OK")

        return {"concept_area_check": result}

    except Exception as e:
        logger.warning(f"[lg_layout_validator] LLM 호출 실패 — 코드 룰 결과만 반환: {e}")
        return {"concept_area_check": code_result}


def _describe_area_position(area: dict, entrance_mm, usable_poly) -> str:
    """영역 polygon 위치를 자연어로 풀어서 LLM 입력용 텍스트 생성.

    Shapely centroid (다각형 무게중심점) 기반 거리 + 사분면 표기.
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


def _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy) -> str:
    """입구 좌표 → 상/하/좌/우 판정 (concept_area.py 와 같은 로직)."""
    if not entrance_mm:
        return "하단"
    ex, ey = entrance_mm
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    dx, dy = ex - cx, ey - cy
    w, h = maxx - minx, maxy - miny
    nx = dx / (w / 2) if w > 0 else 0
    ny = dy / (h / 2) if h > 0 else 0
    if abs(nx) > abs(ny):
        return "우측" if nx > 0 else "좌측"
    return "하단" if ny > 0 else "상단"
