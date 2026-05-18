"""
레퍼런스 반영도 추적/채점 노드.

ref_analysis 패턴 → design_intents placed_because → placed/failed 연결을 추적하고
반영도 스코어(0.0~1.0)를 산출한다.

입력: ref_analysis, design_intents, placed_objects, failed_objects
출력: ref_trace (dict), ref_quality_score (float)

매칭 알고리즘 (2026-05-04 변경, 트랙 7):
  과거: 키워드 2개 이상 겹침 (단순 토큰 set intersection) — 거품 점수 (0.93 등) 빈발
  현재: cosine similarity (OpenAI text-embedding-3-small) ≥ 0.65 → match
        → 의미적 유사성 기반. 거품 점수 줄어듦.
  Fallback: OPENAI_API_KEY 없거나 API 실패 시 → 키워드 매칭으로 자동 회귀 (worker 멈춤 X).
"""
import logging
import re
from typing import Optional

from app.services import embedding as emb
from app.state import LargeState

logger = logging.getLogger(__name__)

# ── 임베딩 임계값 (사용자 결정 2026-05-04, 트랙 7) ────────────────────────
# cosine ≥ threshold → match. semantic 기본값 (LangChain / RAG 기준 = 0.65).
# 2026-05-06: 0.65 → 0.45 완화 (사용자 결정 — 발표용 점수 50% 이상 보장).
# 데이터 쌓이면 튜닝 — 0.5 (중간) / 0.65 (엄격) 조정 가능.
SEMANTIC_THRESHOLD = 0.45

# ── 키워드 매칭에서 무시할 불용어 (fallback 시에만 사용) ───────────────
_STOPWORDS = frozenset(
    "의 가 이 은 는 을 를 에 에서 와 과 로 으로 도 만 까지 부터 "
    "및 등 수 것 위 중 후 때 더 잘 매우 통해 대한 위한 하는 하고 있는 "
    "the a an and or in on at to for of with is are was were".split()
)

# ── fallback intent 판별 패턴 ─────────────────────────────────────────
_FALLBACK_PATTERN = re.compile(
    r"(fallback|default|기본\s*의도|자동\s*배치)", re.IGNORECASE
)


def run(state: LargeState) -> LargeState:
    """ref_analysis → design_intents → placement 연결을 추적하고 반영도를 채점.

    매칭 우선순위 (2026-05-04 트랙 7):
      1) 임베딩 cosine similarity ≥ SEMANTIC_THRESHOLD → match (정본)
      2) OPENAI_API_KEY 없거나 첫 호출 실패 → 키워드 2개 겹침 fallback (worker 멈춤 X)
    """
    ref_analysis = state.get("ref_analysis") or {}
    design_intents = state.get("design_intents") or []
    placed_objects = state.get("placed_objects") or []
    failed_objects = state.get("failed_objects") or []

    # 1) ref_analysis 패턴 평탄화
    patterns = _flatten_ref_patterns(ref_analysis)

    # 2) placed/failed object_type 집합
    placed_types = {p.get("object_type") for p in placed_objects}
    failed_types = {f.get("object_type") for f in failed_objects}

    # 3) fallback이 아닌 유효 intent만 필터
    valid_intents = [i for i in design_intents if not _is_fallback_intent(i)]

    # 4) 모든 텍스트 임베딩 일괄 생성 (실패 시 None — 키워드 fallback 자동 분기)
    pattern_texts = [pat["text"] for pat in patterns]
    intent_texts = [intent.get("placed_because", "") for intent in valid_intents]
    pattern_embeddings = emb.embed_texts(pattern_texts) if pattern_texts else []
    intent_embeddings = emb.embed_texts(intent_texts) if intent_texts else []

    # 임베딩 사용 가능 여부 — 어느 한쪽이라도 None 이면 fallback (혼합 매칭 회피)
    use_semantic = (
        pattern_embeddings and intent_embeddings
        and all(v is not None for v in pattern_embeddings)
        and all(v is not None for v in intent_embeddings)
    )
    matching_mode = "semantic" if use_semantic else "keyword"
    logger.info(f"[ref_trace_scorer] matching_mode={matching_mode} (threshold={SEMANTIC_THRESHOLD if use_semantic else 'N/A (keyword)'})")

    # 5) 패턴 → intent 매칭
    pattern_intent_map = []
    matched_pattern_count = 0

    for pat_idx, pat in enumerate(patterns):
        matched_intents = []
        pat_keywords = _extract_keywords(pat["text"]) if not use_semantic else None

        for intent_idx, intent in enumerate(valid_intents):
            reason = intent.get("placed_because", "")

            if use_semantic:
                similarity = emb.cosine_similarity(
                    pattern_embeddings[pat_idx], intent_embeddings[intent_idx]
                )
                is_match = similarity >= SEMANTIC_THRESHOLD
                match_evidence = {"similarity": round(similarity, 4)}
            else:
                reason_keywords = _extract_keywords(reason)
                overlap = pat_keywords & reason_keywords
                is_match = len(overlap) >= 2
                match_evidence = {"matched_keywords": list(overlap)}

            if is_match:
                obj_type = intent.get("object_type", "")
                status = "placed" if obj_type in placed_types else (
                    "failed" if obj_type in failed_types else "unknown"
                )
                matched_intents.append({
                    "object_type": obj_type,
                    "placed_because": reason,
                    "placement_status": status,
                    **match_evidence,
                })

        entry = {
            "source_field": pat["field"],
            "pattern_text": pat["text"],
            "matched_intents": matched_intents,
        }
        pattern_intent_map.append(entry)
        if matched_intents:
            matched_pattern_count += 1

    # 6) 미반영 패턴 / 근거 없는 intent
    unmatched_patterns = [
        e["pattern_text"] for e in pattern_intent_map if not e["matched_intents"]
    ]

    unexplained_intents = []
    if use_semantic:
        # intent 별로 어느 패턴과도 임계값 못 넘었으면 unexplained
        for i_idx, intent in enumerate(valid_intents):
            best_sim = max(
                (emb.cosine_similarity(intent_embeddings[i_idx], pe) for pe in pattern_embeddings),
                default=0.0,
            )
            if best_sim < SEMANTIC_THRESHOLD:
                unexplained_intents.append({
                    "object_type": intent.get("object_type", ""),
                    "placed_because": intent.get("placed_because", ""),
                    "best_similarity": round(best_sim, 4),
                })
    else:
        # 키워드 fallback - 기존 로직 유지
        all_pattern_keywords = set()
        for pat in patterns:
            all_pattern_keywords |= _extract_keywords(pat["text"])
        for intent in valid_intents:
            reason_kw = _extract_keywords(intent.get("placed_because", ""))
            if len(reason_kw & all_pattern_keywords) < 2:
                unexplained_intents.append({
                    "object_type": intent.get("object_type", ""),
                    "placed_because": intent.get("placed_because", ""),
                })

    # 6) 스코어 계산
    scores = _compute_scores(
        pattern_count=len(patterns),
        matched_pattern_count=matched_pattern_count,
        valid_intent_count=len(valid_intents),
        unexplained_count=len(unexplained_intents),
        pattern_intent_map=pattern_intent_map,
        placed_types=placed_types,
        failed_types=failed_types,
    )

    ref_trace = {
        "pattern_count": len(patterns),
        "intent_count": len(design_intents),
        "valid_intent_count": len(valid_intents),
        "placed_count": len(placed_objects),
        "failed_count": len(failed_objects),
        "pattern_intent_map": pattern_intent_map,
        "unmatched_patterns": unmatched_patterns,
        "unexplained_intents": unexplained_intents,
        "score_breakdown": scores["breakdown"],
        "reflection_score": scores["total"],
        "matching_mode": matching_mode,
    }

    logger.info(
        f"[ref_trace_scorer] 반영도={scores['total']:.2f} mode={matching_mode} "
        f"(coverage={scores['breakdown']['pattern_coverage']:.2f}, "
        f"grounding={scores['breakdown']['intent_grounding']:.2f}, "
        f"success={scores['breakdown']['placement_success']:.2f}) "
        f"| 패턴 {len(patterns)}개 중 {matched_pattern_count}개 매칭, "
        f"미반영 {len(unmatched_patterns)}개"
    )

    return {"ref_trace": ref_trace, "ref_quality_score": scores["total"]}


# ── 내부 함수 ────────────────────────────────────────────────────────

_LIST_FIELDS = (
    "layout_patterns", "partition_usage", "focal_points", "design_highlights",
    "area_size_emphasis",  # 2026-05-06 burning_task 2단계 — concept_area size_hint 근거
)
# 2026-05-05 dev2 머지 후 정합 fix - ref_image_analyzer._merge_analyses 의 string_fields 와 일치.
# 2026-05-03 dev2 PR #483 에서 8 → 10 축 확장 (color_palette + lighting_mood). scorer 가 누락 중이었음.
_STRING_FIELDS = (
    "flow_description", "density_impression", "space_mood", "composition_principle",
    "color_palette", "lighting_mood",
)


def _flatten_ref_patterns(ref_analysis: dict) -> list[dict]:
    """ref_analysis의 모든 필드를 [{field, index, text}, ...] 형태로 평탄화."""
    patterns = []
    for field in _LIST_FIELDS:
        items = ref_analysis.get(field) or []
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, str) and item.strip():
                    patterns.append({"field": field, "index": i, "text": item.strip()})
    for field in _STRING_FIELDS:
        value = ref_analysis.get(field)
        if isinstance(value, str) and value.strip():
            patterns.append({"field": field, "index": 0, "text": value.strip()})
    return patterns


def _extract_keywords(text: str) -> set[str]:
    """텍스트에서 의미 있는 키워드 토큰 추출 (한/영 2글자 이상, 불용어 제외)."""
    tokens = re.split(r"[\s,./\-_()\[\]{}:;\"'·~!@#$%^&*+=|<>?]+", text)
    return {
        t.lower() for t in tokens
        if len(t) >= 2 and t.lower() not in _STOPWORDS
    }


def _is_fallback_intent(intent: dict) -> bool:
    """fallback/default에 의해 생성된 intent인지 판별."""
    reason = intent.get("placed_because", "")
    return bool(_FALLBACK_PATTERN.search(reason))


def _compute_scores(
    pattern_count: int,
    matched_pattern_count: int,
    valid_intent_count: int,
    unexplained_count: int,
    pattern_intent_map: list,
    placed_types: set,
    failed_types: set,
) -> dict:
    """3개 서브스코어 + 가중 합산."""

    # pattern_coverage: ref 패턴 중 intent에 반영된 비율
    if pattern_count > 0:
        pattern_coverage = matched_pattern_count / pattern_count
    else:
        pattern_coverage = 0.0

    # intent_grounding: 유효 intent 중 ref 패턴 근거가 있는 비율
    grounded_count = valid_intent_count - unexplained_count
    if valid_intent_count > 0:
        intent_grounding = grounded_count / valid_intent_count
    else:
        intent_grounding = 0.0

    # placement_success: ref 근거 intent 중 실제 배치 성공 비율
    ref_placed = 0
    ref_total = 0
    for entry in pattern_intent_map:
        for mi in entry["matched_intents"]:
            ref_total += 1
            if mi["placement_status"] == "placed":
                ref_placed += 1

    if ref_total > 0:
        placement_success = ref_placed / ref_total
    else:
        placement_success = 0.0

    total = (
        0.4 * pattern_coverage
        + 0.3 * intent_grounding
        + 0.3 * placement_success
    )

    return {
        "total": round(total, 4),
        "breakdown": {
            "pattern_coverage": round(pattern_coverage, 4),
            "intent_grounding": round(intent_grounding, 4),
            "placement_success": round(placement_success, 4),
        },
    }
