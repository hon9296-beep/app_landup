"""
공간 디자인 컨셉 생성 노드 — nodes_small 영역 placeholder.

[중요 — 삭제 금지]
본 모듈은 nodes_large/concept_gen.py 의 인터페이스 미러링 placeholder.
현재 nodes_small 파이프라인 (graph.py build_small_graph) 에서 호출되지 않음 (2026-04-29 grep 0건 확인).
nodes_large 와 nodes_small 가 동일 인터페이스 (def run(state) -> state) 를 유지하기 위해 보존.

미래 활용 시점:
- 소형·중형 매장에 컨셉 생성 도입 결정 시 graph.py 에서 호출 추가
- 그 전까지는 dead code 처럼 보여도 삭제 / 정리 금지

기능 (호출 시):
날짜(계절/이벤트) + 브랜드 카테고리 + 사용자 컨셉(있으면) → LLM이 디자인 컨셉 수립.
ref_image_loader 전에 실행되어 검색 키워드에도 영향.
design 노드에서 배치 시 컨셉을 프롬프트에 주입.
"""
import json
import logging
import os
from datetime import datetime

from anthropic import Anthropic

from app.state import SmallState
from app.utils import parse_llm_json

logger = logging.getLogger(__name__)

# ── 날짜 → 시즌/이벤트 매핑 (코드 레벨, LLM 불필요) ──────────────────

_SEASON_MAP = {
    (3, 4, 5): "봄",
    (6, 7, 8): "여름",
    (9, 10, 11): "가을",
    (12, 1, 2): "겨울",
}

_EVENT_MAP = [
    # (월, 일 범위, 이벤트명)
    (1, 1, 1, "새해/신년"),
    (2, 1, 14, "발렌타인"),
    (3, 1, 14, "화이트데이"),
    (4, 1, 30, "벚꽃 시즌"),
    (5, 1, 5, "어린이날"),
    (10, 15, 31, "할로윈"),
    (11, 20, 30, "블랙프라이데이"),
    (12, 1, 25, "크리스마스"),
    (12, 26, 31, "연말"),
]


def _get_season(month: int) -> str:
    for months, name in _SEASON_MAP.items():
        if month in months:
            return name
    return "봄"


def _get_nearby_event(month: int, day: int) -> str | None:
    for ev_month, ev_start, ev_end, ev_name in _EVENT_MAP:
        if month == ev_month and ev_start <= day <= ev_end:
            return ev_name
    return None


# ── LLM 컨셉 생성 ─────────────────────────────────────────────────────

CONCEPT_SYSTEM = """당신은 팝업스토어/전시 공간 디자인 디렉터입니다.
브랜드 정보, 시즌, 공간 조건을 종합하여 공간 디자인 컨셉을 수립합니다.
컨셉은 추상적이어도 좋습니다. 배치 설계자가 이 컨셉을 보고 오브젝트를 배치합니다."""

CONCEPT_PROMPT = """## 조건
- 브랜드 카테고리: {brand_category}
- 시즌: {season}
{event_line}
- 공간 면적: {area_sqm:.0f}㎡
{user_concept_line}

## 지시
위 조건을 종합하여 이 팝업스토어의 디자인 컨셉을 수립하세요.
JSON만 출력하세요.

```json
{{
  "theme": "컨셉 테마 한 문장 (예: 봄 벚꽃 캐릭터 팝업)",
  "mood": "공간 분위기 (예: 밝고 개방적, 파스텔 톤)",
  "story_flow": "방문자 경험 동선 (예: 입구→캐릭터 맞이→체험→포토→구매)",
  "zone_plan": {{
    "entrance": "입구 zone 역할/연출",
    "mid": "중앙 zone 역할/연출",
    "deep": "안쪽 zone 역할/연출"
  }},
  "partition_intent": "가벽 활용 계획 (공간분할/디자인연출/미사용)",
  "search_keywords": ["레퍼런스 검색용 영문 키워드 3~5개"]
}}
```"""


def run(state: SmallState) -> SmallState:
    """디자인 컨셉 생성 → design_concept + 검색 키워드."""
    brand_data = state.get("brand_data") or {}
    usable_poly = state.get("usable_poly")
    user_concept = state.get("user_design_concept")

    # 브랜드 카테고리
    category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(category, dict):
        category = category.get("value", "기타")

    # 공간 면적
    area_sqm = usable_poly.area / 1_000_000 if usable_poly else 50

    # 날짜 기반 시즌/이벤트
    now = datetime.now()
    season = _get_season(now.month)
    event = _get_nearby_event(now.month, now.day)

    event_line = f"- 시즌 이벤트: {event}" if event else ""
    user_concept_line = f"- 사용자 요청 컨셉: \"{user_concept}\" ← 이 컨셉을 최우선으로 반영하세요" if user_concept else ""

    # LLM 호출
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[concept_gen] API 키 없음 — 기본 컨셉 반환")
        concept = _default_concept(category, season, event, area_sqm)
        return {"design_concept": concept}

    prompt = CONCEPT_PROMPT.format(
        brand_category=category,
        season=season,
        event_line=event_line,
        area_sqm=area_sqm,
        user_concept_line=user_concept_line,
    )

    try:
        from app.llm_config import get_llm_config
        _cfg = get_llm_config("small.concept_gen")
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            system=CONCEPT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        from app.token_tracker import track_usage
        track_usage("concept_gen.py", response)
        if not response.content:
            raise ValueError("빈 응답")

        concept = parse_llm_json(response.content[0].text)
        logger.info(f"[concept_gen] 컨셉 생성: theme=\"{concept.get('theme', '')}\"")
        return {"design_concept": concept}

    except Exception as e:
        logger.warning(f"[concept_gen] LLM 실패 — 기본 컨셉 사용: {e}")
        concept = _default_concept(category, season, event, area_sqm)
        return {"design_concept": concept}


def _default_concept(category: str, season: str, event: str | None, area_sqm: float) -> dict:
    """LLM 실패 시 기본 컨셉."""
    theme = f"{season} {category} 팝업스토어"
    if event:
        theme = f"{event} {category} 팝업스토어"

    keywords = [
        f"{season} popup store",
        f"{category} popup",
        "popup store layout aerial view",
    ]
    if event:
        keywords.append(f"{event} popup store")

    return {
        "theme": theme,
        "mood": "밝고 활기찬",
        "story_flow": "입구→메인 전시→체험→포토존→구매",
        "zone_plan": {
            "entrance": "개방적, 브랜드 히어로로 시선 유도",
            "mid": "체험/전시 중심",
            "deep": "포토존 + 구매",
        },
        "partition_intent": "필요 시 체험존 분리용",
        "search_keywords": keywords,
    }
