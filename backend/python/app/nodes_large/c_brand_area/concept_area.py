"""
기능 영역(concept_area) 설계 노드.

공간 형태 + 브랜드 + 레퍼런스 → LLM이 BSP split_tree 자유 결정.
LLM은 split_at 비율 / leaf 이름 / 트리 깊이 / 영역 갯수 모두 자유 결정.

2026-05-06 BSP 롤백 (voronoi 실험 폐기):
- voronoi grid sampling / weighted Voronoi / zigzag / SIZE_FACTOR 모두 폐기 (strip / 들쭉날쭉 / 영역 누적 부적합)
- BSP split_tree 부활 — 직사각형 분할, LLM split_at 비율 자유
- size_hint 폐기 (split_at 비율이 면적 의도 직접 표현)
- ref area_size_emphasis 는 prompt inject 유지 (LLM split_at 결정 근거)
- 같은 영역 종류 중복 허용 (포토존 여러 개)

입력: usable_poly, entrance_mm, reference_points, brand_data, ref_analysis, user_design_concept
출력: concept_areas (영역 목록 + polygon), reference_points (concept_area 라벨 추가)
"""
import json
import logging
import os

from anthropic import Anthropic
from shapely.geometry import Point, Polygon, box

from app.state import LargeState
from app.core.exceptions import LLMParsingError


class SplitTreeInvalidError(Exception):
    """LLM split_tree 가 빈 polygon 만들 때 raise (2026-05-08 신설).

    원인:
    - split_at 극단값 (0.99 등) → leaf box 가 부지 외곽 안 걸침
    - ㄱ/L/U/T 부지에서 leaf box 가 잘린 코너 영역에 위치
    - BSP depth 깊고 누적 split_at 작아 leaf box 매우 작음

    catch 위치: _call_llm 의 attempt loop → 다음 attempt (LLM 새 호출)
    + concept_area_fix.run() → retry_count + 1 반환 (LangGraph 재시도)
    """
    pass

logger = logging.getLogger(__name__)

# ── 고정 영역 유형 ────────────────────────────────────────────────────

AREA_TYPES = {
    # 2026-05-06: "맞이" default 폐기 (사용자 결정 — 첫인상은 다른 영역도 가능, 강제 X).
    # brand 매뉴얼에 명시 시 brand_concept_areas_hint 로 동적 흡수 가능.
    "포토": {
        "target_objects": ["photo_wall", "photo_island", "character_bbox", "banner_stand"],
        "description": "포토존, 캐릭터 조형물, 배경 세트",
        "search_keyword": "팝업스토어 포토존 포토스팟 배경 연출",
    },
    "체험": {
        # 2026-05-06: kiosk 제거 → 굿즈판매로 이동 (사용자 결정)
        "target_objects": ["display_table", "character_bbox"],
        "description": "인터랙션, 손에 닿는 체험 콘텐츠",
        "search_keyword": "팝업스토어 체험존 인터랙션 인테리어",
    },
    "상영": {
        "target_objects": ["display_table", "banner_stand"],
        "description": "미디어 상영, 전시 패널, 영상 콘텐츠",
        "search_keyword": "팝업스토어 상영존 미디어월 영상 공간",
    },
    "굿즈판매": {
        # 2026-05-06: kiosk 흡수 (체험에서 이동, 결제 보조 + 진열 검색용)
        "target_objects": ["display_table", "shelf_wall", "shelf_3tier", "kiosk"],
        "description": "굿즈 진열, 판매 선반, 검색 키오스크",
        "search_keyword": "팝업스토어 굿즈 판매 진열대 선반",
    },
    "결제": {
        "target_objects": ["counter"],
        "description": "결제 카운터",
        "search_keyword": "팝업스토어 카운터 결제 POS",
    },
    "혼합": {
        "target_objects": ["display_table", "shelf_wall", "kiosk"],
        "description": "카페+굿즈, 체험+포토 등 복합 영역",
        "search_keyword": "팝업스토어 복합 카페 굿즈 체험 인테리어",
    },
    "휴식": {
        # TODO 디자인 도메인 협의 — 좌석 / 음료 / 카페 오브젝트 정의 후 채움
        "target_objects": [],
        "description": "좌석 / 음료 / 카페 영역, 사용자 휴식",
        "search_keyword": "팝업스토어 라운지 좌석 휴식 공간",
    },
}

# ── 컨셉존 영문 키 ↔ 한국어 라벨 매핑 ──────────────────────────────────
# DB / state / API 키는 영문, LLM 입출력 / 사용자 표시는 한국어.
# DB 진입 게이트 (ref_image 분석 결과 저장 등) 에서만 한국어 → 영문 변환.
# 결정 근거: docs/docs-shin/main_tasks/TR_S_고도화/2026-04-29_[컨셉존_기반_디자인]_컨셉존_정의_체계.md
# small 정합: docs/docs-shin/main_tasks/TR_M_협의대기/2026-04-29_[ref_image_small_정합]_concept_area_영문키.md
CONCEPT_AREA_LABEL_KO = {
    # 2026-05-06: "welcome:맞이" default 폐기. brand 매뉴얼 명시 시 hint 로 동적 흡수.
    "photo": "포토",
    "experience": "체험",
    "screening": "상영",
    "retail": "굿즈판매",
    "checkout": "결제",
    "hybrid": "혼합",
    "lounge": "휴식",
}

# 한국어 → 영문 reverse lookup (DB 저장 시점 변환용)
CONCEPT_AREA_LABEL_EN = {v: k for k, v in CONCEPT_AREA_LABEL_KO.items()}

# split_tree 의 axis 유효 값 (LLM 출력 검증용)
# - "x": 좌우 분할 (수직선으로 자름)
# - "y": 상하 분할 (수평선으로 자름)
VALID_SPLIT_AXES = {"x", "y"}


# 2026-05-06 burning_task 2단계 세 번째 작업 — 커스텀 영역 → 가장 비슷한 8종 매핑 룰.
# (key=AREA_TYPES 영역명, value=매칭 키워드 list — 한/영 둘 다)
# 우선순위: 위에서부터 매칭 시 즉시 반환.
_SIMILAR_AREA_KEYWORDS = [
    # 2026-05-06: "맞이" default 폐기. 맞이 키워드 박힌 커스텀 영역은 "포토" 로 fallback (입구쪽 첫인상 영역).
    ("포토",     ["맞이", "입구", "웰컴", "welcome", "entrance", "greeting", "intro",
                "포토", "사진", "포토존", "photo", "picture"]),
    ("체험",     ["체험", "인터랙션", "터치", "experience", "interactive", "hands"]),
    ("상영",     ["상영", "영상", "미디어", "screening", "media", "video", "screen"]),
    ("결제",     ["결제", "카운터", "캐셔", "checkout", "counter", "cashier", "pay", "register"]),
    ("휴식",     ["휴식", "라운지", "카페", "좌석", "lounge", "rest", "cafe", "seating"]),
    ("굿즈판매", ["굿즈", "판매", "선반", "진열", "스킨케어", "화장품", "뷰티", "메이크업",
                "retail", "shop", "skincare", "beauty", "makeup", "merch", "display"]),
    ("혼합",     ["혼합", "복합", "hybrid", "mixed"]),
]


def _find_similar_area_type(name_ko: str, name_en: str = "") -> str | None:
    """커스텀 영역명 (한/영) → 가장 비슷한 8종 AREA_TYPES 매핑.

    단순 키워드 매칭 (LLM 호출 X). 매칭 안 되면 None.
    target_objects fallback 결정 시 사용.
    """
    text = f"{name_ko} {name_en}".lower()
    for area_name, keywords in _SIMILAR_AREA_KEYWORDS:
        if any(kw in text for kw in keywords):
            return area_name
    return None


def run(state: LargeState) -> LargeState:
    """LLM이 영역 구성 결정 (Voronoi Tool) → Shapely가 폴리곤 분할 → ref_point에 라벨 할당."""
    usable_poly = state.get("usable_poly")
    if not usable_poly:
        raise LLMParsingError("usable_poly 없음 — concept_area 실행 불가", {})

    entrance_mm = state.get("entrance_mm")
    brand_data = state.get("brand_data") or {}
    ref_analysis = state.get("ref_analysis") or {}
    user_concept = state.get("user_design_concept") or ""
    reference_points = state.get("reference_points") or []

    # 공간 특성 추출
    area_sqm = usable_poly.area / 1_000_000
    minx, miny, maxx, maxy = usable_poly.bounds
    width_mm = maxx - minx
    height_mm = maxy - miny
    aspect_ratio = width_mm / height_mm if height_mm > 0 else 1.0
    entrance_side = _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy)

    # 브랜드 카테고리
    category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(category, dict):
        category = category.get("value", "기타")

    # 2026-05-06 burning_task 2단계 세 번째 작업 — brand 매뉴얼 영역 hint 받기.
    brand_concept_areas_hint = brand_data.get("concept_areas_hint", []) if isinstance(brand_data, dict) else []

    tool_input = _call_llm(
        area_sqm=area_sqm,
        aspect_ratio=aspect_ratio,
        entrance_side=entrance_side,
        category=category,
        ref_analysis=ref_analysis,
        user_concept=user_concept,
        brand_concept_areas_hint=brand_concept_areas_hint,
        usable_poly=usable_poly,
    )

    # BSP split_tree → 직사각형 영역 polygon 분할
    split_tree = tool_input.get("split_tree", {})
    areas = _apply_split_tree(split_tree, usable_poly)

    logger.info(f"[concept_area] areas={len(areas)}")

    # 영역별 target_objects 매핑 (2026-05-06 세 번째 작업 — 매뉴얼 hint + AREA_TYPES + fallback).
    # 우선순위:
    #   1. 매뉴얼 hint 의 target_objects (직접 명시)
    #   2. AREA_TYPES (기본 8종) 의 target_objects
    #   3. 매뉴얼 hint 의 name_ko 매칭 (커스텀 영역)
    #   4. fallback: ["display_table"]
    hint_lookup = {h.get("name_ko", ""): h for h in brand_concept_areas_hint}
    for area in areas:
        name = area.get("name", "")
        # 1. 매뉴얼 hint 의 target_objects 직접 명시
        if name in hint_lookup and hint_lookup[name].get("target_objects"):
            area["target_objects"] = hint_lookup[name]["target_objects"]
        # 2. AREA_TYPES 기본 8종
        elif name in AREA_TYPES:
            area["target_objects"] = AREA_TYPES[name]["target_objects"]
        # 3. 커스텀 영역 — name_en 보고 가장 비슷한 8종 매핑 (간단 키워드)
        elif "target_objects" not in area:
            similar = _find_similar_area_type(name, hint_lookup.get(name, {}).get("name_en", ""))
            if similar:
                area["target_objects"] = AREA_TYPES[similar]["target_objects"]
            else:
                area["target_objects"] = ["display_table"]

    # ── Java 영속화 (2026-05-01 Phase 2) ─────────────────────────────────
    # state.floor_detection_id 가 있으면 batch INSERT → 응답 id 를 area dict 에 박음.
    # 라벨 할당 전에 영속화해서 reference_points 에 concept_area_id 도 같이 박음.
    # 활성화 off / Java 다운 시 빈 dict → FK NULL 로 정상 진행 (graceful).
    floor_detection_id = state.get("floor_detection_id")
    if floor_detection_id:
        _persist_concept_areas(floor_detection_id, areas)

    # reference_points 에 concept_area 라벨 + id 할당
    for rp in reference_points:
        coord = rp.get("coord")
        if not coord:
            continue
        pt = Point(coord)
        assigned_area = None
        for area in areas:
            poly = area.get("polygon_mm")
            if poly and poly.contains(pt):
                assigned_area = area
                break
        if assigned_area is None:
            # 가장 가까운 영역에 fallback 할당
            min_dist = float("inf")
            for area in areas:
                poly = area.get("polygon_mm")
                if poly:
                    d = poly.distance(pt)
                    if d < min_dist:
                        min_dist = d
                        assigned_area = area
        if assigned_area is not None:
            # state 는 한국어 (LLM intent 와 매칭 일관) — 응답/DB 시점에 영문 변환
            rp["concept_area"] = assigned_area.get("name")
            rp["concept_area_id"] = assigned_area.get("id")

    # 2026-05-06 안전망 (A + B + C) — LLM 이 prompt 룰 무시할 경우 코드 강제 fix.
    # B (strip 흡수) 후 영역 갯수 변동 가능 → ref_point assignment 다시 해야 안전.
    # 다만 위에서 이미 ref_point 매핑 완료 → 안전망 적용 후 재매핑 필요.
    from app.nodes_large.c_brand_area.concept_area_safety import apply_safety_nets
    areas = apply_safety_nets(areas, entrance_mm, usable_poly)

    # ref_point concept_area 라벨 재매핑 (안전망 후 영역 변경 반영)
    for rp in reference_points:
        coord = rp.get("coord")
        if not coord:
            continue
        pt = Point(coord)
        assigned_area = None
        for area in areas:
            poly = area.get("polygon_mm")
            if poly and poly.contains(pt):
                assigned_area = area
                break
        if assigned_area is None:
            min_dist = float("inf")
            for area in areas:
                poly = area.get("polygon_mm")
                if poly:
                    d = poly.distance(pt)
                    if d < min_dist:
                        min_dist = d
                        assigned_area = area
        if assigned_area is not None:
            rp["concept_area"] = assigned_area.get("name")
            rp["concept_area_id"] = assigned_area.get("id")

    logger.info(
        "[concept_area] %d개 영역 (안전망 적용 후): %s",
        len(areas),
        ", ".join(f"{a['name']}({a['area_ratio']:.0%})" for a in areas),
    )

    # 디버그 (2026-05-01) — ref_point 라벨 매핑 결과 확인
    n_with_id = sum(1 for rp in reference_points if rp.get("concept_area_id"))
    logger.info(
        "[concept_area] ref_point concept_area_id 매핑: %d/%d",
        n_with_id, len(reference_points),
    )

    # 2026-05-08 안전망 H 강화 — history list 시작 (1차 결과). fix retry 마다 append.
    # max_retry 도달 시 history 안 위반 가장 적은 결과 선택 (1차 vs retry1 vs retry2).
    import copy
    concept_areas_history = [copy.deepcopy(areas)]

    return {
        "concept_areas": areas,
        "concept_areas_history": concept_areas_history,  # H 안전망용 결과 누적 list
        "reference_points": reference_points,
    }


def _persist_concept_areas(floor_detection_id: int, areas: list[dict]) -> None:
    """Java batch INSERT 호출 + 응답 id 를 areas[i]["id"] 에 채움.

    name 영문 키 변환 (CONCEPT_AREA_LABEL_EN) — DB 는 영문 키로 저장 (4-29 결정).
    polygon_mm (Shapely) → [[x,y],...] JSON 직렬화.
    target_objects → JSON list str.
    """
    from app.clients.concept_area_client import register_concept_areas_batch

    payloads = []
    for area in areas:
        name_ko = area.get("name", "")
        name_en = CONCEPT_AREA_LABEL_EN.get(name_ko, name_ko)  # 매핑 없으면 그대로 (커스텀 영역)

        polygon_json = None
        poly = area.get("polygon_mm")
        if poly is not None and not poly.is_empty:
            try:
                coords = list(poly.exterior.coords)
                polygon_json = json.dumps([[float(x), float(y)] for x, y in coords])
            except Exception as e:
                logger.warning("[concept_area] polygon 직렬화 실패 area=%s: %s", name_ko, e)

        target_objects = area.get("target_objects") or []
        target_objects_json = json.dumps(target_objects, ensure_ascii=False)

        payloads.append({
            "name": name_en,
            "polygonJson": polygon_json,
            "areaRatio": float(area.get("area_ratio") or 0),
            "targetObjectsJson": target_objects_json,
        })

    name_to_id = register_concept_areas_batch(floor_detection_id, payloads)
    if not name_to_id:
        logger.info("[concept_area] 영속화 skip 또는 실패 — FK NULL 로 진행")
        return

    # 응답 id 를 area dict 에 박음 (영문 키 → id 매핑 → 한국어 area name 으로 lookup)
    for area in areas:
        name_ko = area.get("name", "")
        name_en = CONCEPT_AREA_LABEL_EN.get(name_ko, name_ko)
        area["id"] = name_to_id.get(name_en)
    logger.info("[concept_area] 영속화 완료 — %d/%d 매핑", sum(1 for a in areas if a.get("id")), len(areas))


# ── LLM 호출 ──────────────────────────────────────────────────────────

def _call_llm(
    area_sqm: float,
    aspect_ratio: float,
    entrance_side: str,
    category: str,
    ref_analysis: dict,
    user_concept: str,
    brand_concept_areas_hint: list = None,
    usable_poly: Polygon = None,
) -> dict:
    """LLM 가 BSP Tool 호출 → split_tree (axis / split_at / leaf) 자유 결정.

    2026-05-06 BSP 롤백 — voronoi 실험 폐기. tool_choice="auto" 유지.

    반환: tool_input dict ({"split_tree": {...}}).
    """
    from app.nodes_large.c_brand_area.prompts.concept_area import (
        CONCEPT_AREA_SYSTEM as PROMPT_SYSTEM,
        CONCEPT_AREA_PROMPT_TEMPLATE,
        BSP_TOOL,
    )
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMParsingError("API 키 없음 — concept_area 생성 불가", {})

    # 영역 유형 목록 — 기본 8종 + brand 매뉴얼 hint (2026-05-06 세 번째 작업).
    types_lines = [
        f"- {name}: {info['description']}" for name, info in AREA_TYPES.items()
    ]
    if brand_concept_areas_hint:
        types_lines.append("")
        types_lines.append("## 매뉴얼 명시 영역 (우선 사용 권장)")
        for hint in brand_concept_areas_hint:
            ko = hint.get("name_ko", "?")
            en = hint.get("name_en", "")
            desc = hint.get("description", "")
            types_lines.append(f"- {ko} ({en}): {desc}")
    types_text = "\n".join(types_lines)

    # 레퍼런스 요약
    ref_text = ""
    if ref_analysis:
        parts = []
        for field in ("layout_patterns", "partition_usage", "focal_points"):
            items = ref_analysis.get(field, [])
            if items:
                parts.extend(items if isinstance(items, list) else [items])
        if parts:
            ref_text = "\n## 레퍼런스 분석\n" + "\n".join(f"- {p}" for p in parts)

    # 2026-05-06 BSP 롤백 — 레퍼런스 area_size_emphasis 는 split_at 비율 결정 근거로 inject
    size_emphasis_text = ""
    if ref_analysis:
        emphasis_items = ref_analysis.get("area_size_emphasis", []) or []
        if emphasis_items:
            size_emphasis_text = (
                "\n## 레퍼런스 — 영역별 면적 강조도 (split_at 비율 결정 근거)\n"
                + "\n".join(f"- {e}" for e in emphasis_items)
            )

    user_line = ""
    if user_concept:
        user_line = f"\n## 사용자 요구사항 (최우선 반영)\n{user_concept}"

    shape_desc = "가로로 긴 공간" if aspect_ratio > 1.3 else (
        "세로로 긴 공간" if aspect_ratio < 0.77 else "정방형에 가까운 공간"
    )

    prompt = CONCEPT_AREA_PROMPT_TEMPLATE.format(
        area_sqm=area_sqm,
        area_sqm_pyeong=area_sqm / 3.3,
        shape_desc=shape_desc,
        aspect_ratio=aspect_ratio,
        entrance_side=entrance_side,
        category=category,
        types_text=types_text,
        ref_text=ref_text,
        size_emphasis_text=size_emphasis_text,
        user_line=user_line,
    )

    client = Anthropic(api_key=api_key)

    last_error = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                temperature=0.5,
                system=PROMPT_SYSTEM,
                tools=[BSP_TOOL],
                tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": prompt}],
            )
            from app.token_tracker import track_usage
            track_usage("large.concept_area", response)
            if not response.content:
                last_error = "빈 응답"
                continue

            # Tool use 응답 파싱 — block 중 type=="tool_use" 찾기
            tool_input = None
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "split_by_bsp":
                    tool_input = dict(block.input or {})
                    break

            if not tool_input:
                last_error = "Tool 호출 안 됨 (text 응답만 또는 잘못된 Tool)"
                continue

            split_tree = tool_input.get("split_tree")
            if not split_tree or not isinstance(split_tree, dict):
                last_error = "split_tree 없음"
                continue

            err = _validate_split_tree(split_tree)
            if err:
                last_error = f"split_tree invalid: {err}"
                continue

            # 2026-05-08: polygon 시뮬레이션 — 빈 polygon 검사 (198% 차단).
            # _apply_split_tree 가 SplitTreeInvalidError raise 하면 다음 attempt (LLM 새 호출).
            if usable_poly is not None:
                try:
                    _apply_split_tree(split_tree, usable_poly)
                except SplitTreeInvalidError as e:
                    last_error = f"polygon empty: {e}"
                    logger.warning(f"[concept_area] attempt {attempt+1} polygon empty — retry")
                    continue

            logger.info(f"[concept_area:llm] tool=bsp, split_tree depth OK")
            return tool_input

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[concept_area] attempt {attempt+1} 실패: {e}")

    raise LLMParsingError(f"concept_area 3회 실패: {last_error}", {"attempts": 3})


# ── 입구 위치 감지 ─────────────────────────────────────────────────────

def _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy) -> str:
    """입구 좌표 → 상/하/좌/우 판정."""
    if not entrance_mm:
        return "하단"
    ex, ey = entrance_mm
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    dx, dy = ex - cx, ey - cy
    w, h = maxx - minx, maxy - miny

    # 정규화
    nx = dx / (w / 2) if w > 0 else 0
    ny = dy / (h / 2) if h > 0 else 0

    if abs(nx) > abs(ny):
        return "우측" if nx > 0 else "좌측"
    else:
        return "하단" if ny > 0 else "상단"


# ── BSP split_tree 검증 + 적용 (2026-05-06 BSP 롤백) ────────────────────
# voronoi 실험 (grid sampling / weighted Voronoi / zigzag / SIZE_FACTOR) 모두 폐기.
# BSP split_tree = 직사각형 분할, LLM 이 axis / split_at / leaf 자유 결정.

def _validate_split_tree(node: dict, depth: int = 0, max_depth: int = 8) -> str | None:
    """LLM 출력 split_tree 재귀 검증.

    leaf:    {"name_ko": <str>, "name_en": <str>}  (옛 schema {"name"} 호환)
    branch:  {"axis": "x"|"y", "split_at": 0.0-1.0, "first": <node>, "second": <node>}

    오류 발견 시 사람이 읽을 수 있는 메시지 반환, 정상이면 None.
    max_depth 초과 시 무한 재귀 / 과분할 방어.
    """
    if not isinstance(node, dict):
        return f"node 가 dict 아님 (got {type(node).__name__})"
    if depth > max_depth:
        return f"depth={depth} max_depth={max_depth} 초과 — 분할 트리 너무 깊음"

    # leaf 인지 branch 인지 판정 — axis 없으면 leaf
    if "axis" not in node:
        # leaf — name_ko / name 둘 다 호환
        name = node.get("name_ko") or node.get("name")
        if not isinstance(name, str) or not name.strip():
            return f"leaf 의 name_ko/name 비어있음 또는 str 아님 (depth={depth})"
        return None

    # branch
    axis = node.get("axis")
    if axis not in VALID_SPLIT_AXES:
        return f"axis={axis!r} invalid (depth={depth}, valid={sorted(VALID_SPLIT_AXES)})"

    split_at = node.get("split_at")
    if not isinstance(split_at, (int, float)):
        return f"split_at={split_at!r} numeric 아님 (depth={depth})"
    if not (0.0 < split_at < 1.0):
        return f"split_at={split_at} 범위 (0,1) 벗어남 (depth={depth})"

    if "first" not in node or "second" not in node:
        return f"branch 에 first/second 없음 (depth={depth})"

    err = _validate_split_tree(node["first"], depth + 1, max_depth)
    if err:
        return err
    return _validate_split_tree(node["second"], depth + 1, max_depth)


def _apply_split_tree(split_tree: dict, usable_poly: Polygon) -> list[dict]:
    """LLM 출력 split_tree 를 재귀 적용해 영역 polygon 생성.

    bounds = usable_poly.bounds 로 시작. 각 분기마다 axis 따라 box 로 자르고
    usable_poly 와 intersection. leaf 도달 시 area dict (name + polygon_mm + area_ratio) 생성.
    """
    bounds = usable_poly.bounds  # (minx, miny, maxx, maxy)
    total_area = usable_poly.area or 1.0  # 분모 0 회피

    areas_out: list[dict] = []
    _walk_tree(split_tree, bounds, usable_poly, total_area, areas_out)

    # 2026-05-08: 빈 polygon 발견 시 buffer(-100) 부지 전체 대체 폐기 (사용자 결정 — 198% root cause).
    # 명시적 예외 raise → _call_llm attempt loop / concept_area_fix.run() 가 catch → retry.
    for area in areas_out:
        poly = area.get("polygon_mm")
        if poly is None or poly.is_empty:
            raise SplitTreeInvalidError(
                f"leaf '{area.get('name', '?')}' polygon empty "
                f"— split_at 극단값 또는 box 가 부지 외곽 안 걸침"
            )

    return areas_out


def _walk_tree(
    node: dict,
    bounds: tuple[float, float, float, float],
    usable_poly: Polygon,
    total_area: float,
    areas_out: list[dict],
) -> None:
    """split_tree 재귀 walk — leaf 만나면 polygon 만들어 areas_out 에 append."""
    minx, miny, maxx, maxy = bounds

    # leaf — axis 없으면 leaf
    if "axis" not in node:
        area_box = box(minx, miny, maxx, maxy)
        polygon_mm = usable_poly.intersection(area_box)
        # MultiPolygon 시 가장 큰 것
        if hasattr(polygon_mm, "geoms") and not polygon_mm.is_empty:
            polygon_mm = max(polygon_mm.geoms, key=lambda g: g.area)
        # name (한국어) — name_ko 우선, 옛 name fallback
        name_ko = node.get("name_ko") or node.get("name", "?")
        name_en = node.get("name_en", "")
        areas_out.append({
            "name": name_ko,
            "name_en": name_en,
            "polygon_mm": polygon_mm,
            "area_ratio": (polygon_mm.area or 0) / total_area,
        })
        return

    # branch
    axis = node["axis"]
    split_at = float(node["split_at"])

    if axis == "x":
        x_split = minx + (maxx - minx) * split_at
        first_bounds = (minx, miny, x_split, maxy)
        second_bounds = (x_split, miny, maxx, maxy)
    else:  # "y"
        y_split = miny + (maxy - miny) * split_at
        first_bounds = (minx, miny, maxx, y_split)
        second_bounds = (minx, y_split, maxx, maxy)

    _walk_tree(node["first"], first_bounds, usable_poly, total_area, areas_out)
    _walk_tree(node["second"], second_bounds, usable_poly, total_area, areas_out)
