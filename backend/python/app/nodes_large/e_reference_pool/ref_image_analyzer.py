"""
레퍼런스 이미지 Vision 분석 노드 (large).

ref_image_loader 가 수집한 이미지를 Claude Vision 으로 구조화 분석.
"보는" 단계를 독립시켜서, design 노드에는 분석 결과 텍스트만 전달.
이미지 base64 는 이 노드에서만 사용하고 design 에는 넘기지 않음.

2026-04-24 TR R 재작성:
- 모델 Haiku → Sonnet 4-6 (llm_config 중앙 관리)
- Tool use 강제 (스키마 위반 차단, parse_llm_json 제거)
- status 5단계 추적 (ok/skipped/empty_response/no_tool_block/error)
- 프롬프트 분리 (prompts/ref_image_analyzer.py — 디자인 친화 Phase 1)
- 이미지 수 env 소프트코딩 (REF_IMAGES_FOR_ANALYSIS, 기본 5)
- token_usage prefix "large." 적용
- LangSmith 가 state 자동 가시화 (로컬 dump 코드 미도입)
"""
import json
import logging
import os

from anthropic import Anthropic

from app.state import LargeState
from app.nodes_large.e_reference_pool.prompts.ref_image_analyzer import (
    VISION_ANALYSIS_SYSTEM,
    VISION_ANALYSIS_TOOL,
    VISION_ANALYSIS_PROMPT_TEMPLATE,
)
from app.nodes_large.c_brand_area.concept_area import CONCEPT_AREA_LABEL_EN
from app.clients.ref_image_client import register_ref_image_analysis

logger = logging.getLogger(__name__)


# 이미지 수 상한 — env 소프트코딩 (loader 의 REF_IMAGES_PER_ZONE 과 다른 레이어).
# Vision 호출당 첨부 이미지 총 개수 제한 (토큰·비용).
MAX_IMAGES_FOR_ANALYSIS = int(os.environ.get("REF_IMAGES_FOR_ANALYSIS", "5"))

# Vision 모델 버전 식별자 — DB 의 ref_image_analyses.model_version 과 매칭.
# 모델 / 프롬프트 / 스키마 변경 시 이 상수 갱신 → 기존 분석본은 stale 로 취급되어 재분석 가능.
# 형식: "<short_model>-<schema_rev>" 권장 (예: "sonnet45-v1")
REF_ANALYSIS_MODEL_VERSION = os.environ.get("REF_ANALYSIS_MODEL_VERSION", "sonnet46-v1")


def _merge_analyses(analyses: list[dict]) -> dict:
    """N개 Vision 분석 결과 dict 를 1개로 합산 (N+1 흐름의 풀 + 신규 결합).

    list 필드 (layout_patterns / partition_usage / focal_points / design_highlights):
      concat + dedup (string 기준 순서 유지, dict 항목은 그대로 추가 — Phase 2.1 인사이트 ID 보존)
    string 필드 (flow_description / density_impression / space_mood / composition_principle / color_palette / lighting_mood):
      첫 번째 비어있지 않은 값 (분석본별로 큰 차이 없다는 가정)

    2026-05-03: 8 → 10 축 (color_palette + lighting_mood string 필드 추가).
    """
    if not analyses:
        return {}
    if len(analyses) == 1:
        return dict(analyses[0])

    list_fields = (
        "layout_patterns", "partition_usage", "focal_points", "design_highlights",
        "area_size_emphasis",  # 2026-05-06 burning_task 2단계 — concept_area size_hint 근거
    )
    string_fields = (
        "flow_description", "density_impression", "space_mood", "composition_principle",
        "color_palette", "lighting_mood",
    )

    merged: dict = {}

    for field in list_fields:
        seen: set[str] = set()
        items: list = []
        for a in analyses:
            for it in (a.get(field) or []):
                if isinstance(it, str):
                    if it and it not in seen:
                        items.append(it)
                        seen.add(it)
                elif isinstance(it, dict):
                    items.append(it)  # Phase 2.1 인사이트 dict 등 — 그대로
        merged[field] = items

    for field in string_fields:
        for a in analyses:
            v = a.get(field)
            if v:
                merged[field] = v
                break

    return merged


def run(state: LargeState) -> LargeState:
    """레퍼런스 이미지 Vision 분석 → ref_analysis 반환 + status 추적.

    2026-04-29 N+1 흐름 도입:
      - 풀 (has_cached_analysis=True) → 이미 분석된 JSON 합산 (Vision 호출 skip — 토큰 절감)
      - 신규 (base64) → Vision 호출 + 영속 (ref_image_analyses INSERT)
    """
    reference_images = state.get("reference_images") or []

    if not reference_images:
        logger.info("[ref_image_analyzer] 레퍼런스 이미지 없음 — 스킵")
        return {
            "ref_analysis": {},
            "analyzer_status": "skipped",
            "analyzer_skip_reason": "reference_images 비어있음 (loader 단계 0건)",
        }

    brand_data = state.get("brand_data") or {}
    category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(category, dict):
        category = category.get("value", "기타")

    # ── 풀 vs 신규 분기 ──────────────────────────────────────────────
    pool_imgs = [img for img in reference_images if img.get("has_cached_analysis")]
    new_imgs = [img for img in reference_images if not img.get("has_cached_analysis")]

    # 풀에서 분석 결과 JSON 추출 (이미 8축 분석 완료 — Vision 호출 skip)
    pool_analyses: list[dict] = []
    for img in pool_imgs:
        cached = img.get("cached_analysis_json")
        if not cached:
            continue
        try:
            pool_analyses.append(json.loads(cached) if isinstance(cached, str) else cached)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("[ref_image_analyzer] 풀 분석 JSON 파싱 실패 — skip: %s", e)

    logger.info(
        "[ref_image_analyzer] 풀=%d (Vision skip) / 신규=%d (Vision 호출 대상)",
        len(pool_analyses), len(new_imgs),
    )

    # ── 풀만 있고 신규 없음 — Vision 호출 자체 skip (토큰 0) ────────────
    if not new_imgs:
        merged = _merge_analyses(pool_analyses)
        return {
            "ref_analysis": merged,
            "analyzer_status": "ok_pool_only" if pool_analyses else "skipped",
            "analyzer_skip_reason": None if pool_analyses else "신규 이미지 0건 + 풀 0건",
        }

    # ── 신규 이미지 있음 — Vision 호출 ──────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[ref_image_analyzer] API 키 없음 — 풀만 사용")
        return {
            "ref_analysis": _merge_analyses(pool_analyses),
            "analyzer_status": "ok_pool_only" if pool_analyses else "skipped",
            "analyzer_skip_reason": "ANTHROPIC_API_KEY 환경 변수 없음" if not pool_analyses else None,
        }

    client = Anthropic(api_key=api_key)

    # LLM 설정 중앙 관리
    from app.llm_config import get_llm_config
    _cfg = get_llm_config("large.ref_image_analyzer")

    # 이미지 첨부 (신규만, env 상한)
    analyzed_images = new_imgs[:MAX_IMAGES_FOR_ANALYSIS]
    content: list[dict] = []
    content.append({
        "type": "text",
        "text": VISION_ANALYSIS_PROMPT_TEMPLATE.format(
            category=category, count=len(analyzed_images),
        ),
    })
    for img in analyzed_images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["base64"],
            },
        })

    try:
        response = client.messages.create(
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            system=VISION_ANALYSIS_SYSTEM,
            tools=[VISION_ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "analyze_reference_images"},
            messages=[{"role": "user", "content": content}],
        )
        from app.token_tracker import track_usage
        track_usage("large.ref_image_analyzer", response)

        if not response.content:
            logger.warning("[ref_image_analyzer] 빈 응답")
            return {
                "ref_analysis": {},
                "analyzer_status": "empty_response",
                "analyzer_skip_reason": "response.content 비어있음",
            }

        # Tool use: response.content 에 tool_use block 포함. input 은 이미 parsed dict.
        tool_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if tool_block is None:
            logger.warning("[ref_image_analyzer] tool_use block 없음 (텍스트만 반환됨)")
            return {
                "ref_analysis": {},
                "analyzer_status": "no_tool_block",
                "analyzer_skip_reason": "tool_use block 없음, 텍스트만 반환",
            }

        result = dict(tool_block.input)
        logger.info(
            "[ref_image_analyzer] 분석 완료: patterns=%d, partitions=%d, focal=%d (model=%s, images=%d)",
            len(result.get("layout_patterns", [])),
            len(result.get("partition_usage", [])),
            len(result.get("focal_points", [])),
            _cfg["model"],
            len(analyzed_images),
        )

        # ── 분석 결과 영속화 (ref_image_analyses 테이블) ────────────────────
        # 활성화 조건: REF_IMAGE_HANDOFF_ENABLED=1 (ref_image_client 의 _enabled 게이트)
        # 실패 정책: 영속 실패해도 분석 자체는 계속 진행 (state 에 result 살아있음)
        # 메타 활용 (ref_image_loader 가 image dict 에 ref_image_id / zone 포함):
        #   - ref_image_id: 첫 번째 이미지의 id (대표 — N 이미지 = 1 분석 = 1 row 구조 한계)
        #   - concept_area: 가장 많이 등장한 zone 의 한국어 → CONCEPT_AREA_LABEL_EN 으로 영문 변환
        # 추후 1→1 매핑 (이미지당 1 row) 마이그레이션 시 캐시 hit ratio 향상 가능.
        try:
            from collections import Counter
            zones_ko = [img.get("zone") for img in analyzed_images if img.get("zone")]
            dominant_zone_ko = Counter(zones_ko).most_common(1)[0][0] if zones_ko else None
            concept_area_en = CONCEPT_AREA_LABEL_EN.get(dominant_zone_ko) if dominant_zone_ko else None
            ref_image_id = next(
                (img.get("ref_image_id") for img in analyzed_images if img.get("ref_image_id") is not None),
                None,
            )
            register_ref_image_analysis({
                "refImageId": ref_image_id,
                "conceptArea": concept_area_en,
                "brandCategory": category if category and category != "기타" else None,
                "visionAnalysisJson": json.dumps(result, ensure_ascii=False),
                "modelVersion": REF_ANALYSIS_MODEL_VERSION,
            })
        except Exception as persist_err:
            logger.warning("[ref_image_analyzer] 영속 실패 — 분석은 계속: %s", persist_err)

        # 풀 (이미 분석된 N건) + 신규 (방금 분석한 1 result) 합산
        merged = _merge_analyses([*pool_analyses, result])
        logger.info(
            "[ref_image_analyzer] 풀+신규 합산: pool=%d / new=1 → patterns=%d, partitions=%d, focal=%d",
            len(pool_analyses),
            len(merged.get("layout_patterns", [])),
            len(merged.get("partition_usage", [])),
            len(merged.get("focal_points", [])),
        )

        return {
            "ref_analysis": merged,
            "analyzer_status": "ok",
            "analyzer_skip_reason": None,
        }

    except Exception as e:
        logger.warning("[ref_image_analyzer] Vision 분석 실패: %s", e)
        return {
            "ref_analysis": {},
            "analyzer_status": "error",
            "analyzer_skip_reason": str(e)[:500],
        }
