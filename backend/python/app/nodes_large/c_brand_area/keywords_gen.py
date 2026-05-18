"""
키워드 생성 노드 — concept_area별 영문 검색 키워드 생성.

concept_area.py가 결정한 영역(맞이/포토/체험/상영/굿즈판매/결제/혼합 + 커스텀)별로
Pinterest/DuckDuckGo 검색에 쓸 영문 키워드를 LLM이 생성.

각 area의 dict에 search_keywords (영문 3~5개) 추가 → ref_image_loader가 사용.
사용자 design_concept (있으면) 반영.

2026-05-04: prompt 분리 (Phase 1) + 카테고리 × 영역 64셀 매트릭스 가이드 도입.
prompt 본체는 nodes_large/prompts/keywords_gen.py 에 박힘. 본 파일은 로직만.
"""
import logging
import os

from anthropic import Anthropic

from app.state import LargeState
from app.utils import parse_llm_json
from app.nodes_large.c_brand_area.prompts.keywords_gen import KEYWORDS_SYSTEM, KEYWORDS_PROMPT

logger = logging.getLogger(__name__)


def run(state: LargeState) -> LargeState:
    """concept_areas의 각 area에 search_keywords 추가."""
    concept_areas = state.get("concept_areas") or []
    if not concept_areas:
        logger.info("[keywords_gen] concept_areas 없음 — 스킵")
        return {}

    brand_data = state.get("brand_data") or {}
    user_concept = state.get("user_design_concept") or ""

    # 카테고리
    category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(category, dict):
        category = category.get("value", "기타")

    # LLM 호출
    keywords_map = _call_llm(concept_areas, category, user_concept)

    # 각 area에 search_keywords 추가 (LLM 결과 없으면 폴백)
    for area in concept_areas:
        name = area.get("name", "")
        kw = keywords_map.get(name, [])
        if not kw:
            # 폴백: 영역 이름 + 카테고리 영문 1개
            kw = [f"popup store {name} {category} layout"]
        area["search_keywords"] = kw

    logger.info(
        "[keywords_gen] %d개 영역 키워드: %s",
        len(concept_areas),
        ", ".join(f"{a['name']}({len(a.get('search_keywords', []))})" for a in concept_areas),
    )

    return {"concept_areas": concept_areas}


# ── LLM 호출 ──────────────────────────────────────────────────────────

def _call_llm(concept_areas: list, category: str, user_concept: str) -> dict:
    """LLM에게 area별 영문 키워드 생성하게 한다. 실패 시 빈 dict (폴백은 호출자가 처리)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[keywords_gen] API 키 없음 — 빈 dict 반환")
        return {}

    areas_text = "\n".join(
        f"- {a.get('name', '')}: target_objects={a.get('target_objects', [])}"
        for a in concept_areas
    )
    user_line = f"- 사용자 요구사항: \"{user_concept}\"" if user_concept else ""

    prompt = KEYWORDS_PROMPT.format(
        category=category,
        user_line=user_line,
        areas_text=areas_text,
    )

    client = Anthropic(api_key=api_key)

    last_error = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                temperature=0.2,
                system=KEYWORDS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            from app.token_tracker import track_usage
            track_usage("large.keywords_gen", response)
            if not response.content:
                last_error = "빈 응답"
                continue

            result = parse_llm_json(response.content[0].text)
            keywords = result.get("keywords", {})
            if not keywords:
                last_error = "keywords 비어있음"
                continue

            return keywords

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[keywords_gen] attempt {attempt+1} 실패: {e}")

    logger.warning(f"[keywords_gen] 3회 실패, 빈 dict 반환: {last_error}")
    return {}
