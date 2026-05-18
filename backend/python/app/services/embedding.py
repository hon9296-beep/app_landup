"""
임베딩 (semantic similarity) 래퍼 — 트랙 7 (2026-05-04 신설).

목적:
  ref_trace_scorer 의 키워드 2개 겹침 매칭 → cosine similarity 매칭 교체.
  거품 점수 (예: 단순 키워드 우연 매칭 0.93) 신빙성 개선.

선택지 비교 → text-embedding-3-small 채택 (사용자 결정 2026-05-04):
  - 비용 $0.02/1M tokens (3-large 대비 6.5x 저렴)
  - 1536 차원, 한국어 OK
  - 분석 1회당 약 0.03원 (25개 텍스트 × 50 tokens)
  - 짧은 디자인 패턴 ("벽 옆 진열대 클러스터") 매칭에 충분. 부족 시 모델명만 swap.

Anthropic 은 임베딩 API 미제공 → OpenAI 외부 사용. LLM 호출은 Claude 그대로 유지.

Fallback 정책:
  1) `OPENAI_API_KEY` 환경변수 미설정 → 키워드 매칭 회귀 (사용자 결정)
  2) API 호출 실패 (rate limit / 일시 down 등) → 키워드 매칭 회귀
  → ref_trace_scorer 가 무조건 점수 산출 가능 (worker 멈춤 X)

캐싱:
  같은 텍스트 반복 임베딩 방지 위해 lru_cache (최대 512 entries).
  ref_trace_scorer 한 번 호출 안에서 패턴/intent 텍스트 중복 케이스 방어.
"""
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# 사용자 결정 2026-05-04 - text-embedding-3-small + 임계값 0.65 (semantic match 기본).
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_THRESHOLD = 0.65

# OpenAI 클라이언트 (lazy 초기화 — API_KEY 없거나 모듈 import 실패해도 ref_trace_scorer 동작 보장)
_client_cache: Optional[object] = None
_client_init_failed: bool = False


def _get_client():
    """OpenAI 클라이언트 lazy 초기화. 실패 시 None 반환 (캐싱 — 매 호출마다 재시도 X)."""
    global _client_cache, _client_init_failed
    if _client_cache is not None:
        return _client_cache
    if _client_init_failed:
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[embedding] OPENAI_API_KEY 미설정 — 키워드 매칭 fallback")
        _client_init_failed = True
        return None

    try:
        from openai import OpenAI
        _client_cache = OpenAI(api_key=api_key)
        logger.info(f"[embedding] OpenAI 클라이언트 초기화 (model={DEFAULT_MODEL})")
        return _client_cache
    except Exception as e:
        logger.warning(f"[embedding] 클라이언트 초기화 실패 — 키워드 fallback: {e}")
        _client_init_failed = True
        return None


@lru_cache(maxsize=512)
def _embed_cached(text: str) -> Optional[tuple]:
    """단일 텍스트 → 임베딩 벡터 (tuple 형태, lru_cache 호환).

    None 반환 케이스:
      - OpenAI 클라이언트 초기화 실패 (API_KEY 없음 / import 실패)
      - API 호출 실패 (rate limit / network / etc)
    → caller (ref_trace_scorer) 가 None 받으면 키워드 매칭으로 회귀.
    """
    client = _get_client()
    if client is None:
        return None

    try:
        # OpenAI Python SDK >= 1.0 패턴
        response = client.embeddings.create(
            model=DEFAULT_MODEL,
            input=text,
        )
        # 토큰 사용량 추적 — 누적 store 에도 기록.
        try:
            from app.token_tracker import track_embedding_usage
            total = getattr(response.usage, "total_tokens", 0) if getattr(response, "usage", None) else 0
            track_embedding_usage("embedding.embed_text", DEFAULT_MODEL, total)
        except Exception:
            pass  # 추적 실패는 본기능에 영향 X
        return tuple(response.data[0].embedding)
    except Exception as e:
        logger.warning(f"[embedding] API 호출 실패 — 키워드 fallback: {e}")
        return None


def embed_text(text: str) -> Optional[list[float]]:
    """텍스트 한 개 → 임베딩 벡터 (list).

    빈 문자열 / 공백만 있으면 None 반환 (의미 없는 호출 차단).
    """
    text = (text or "").strip()
    if not text:
        return None
    result = _embed_cached(text)
    return list(result) if result is not None else None


def embed_texts(texts: list[str]) -> list[Optional[list[float]]]:
    """다수 텍스트 → 임베딩 벡터 list. 각 element 가 None 일 수 있음 (실패 시).

    2026-05-06 batch 화 — OpenAI 임베딩 API 1번 요청에 다수 input 지원.
    이전: 텍스트 N 개 → API 호출 N 회 (40초 / 200개 사례).
    현재: 호출 1회로 묶음 (빈 문자열 거르고 dedupe).

    캐시는 단일 호출 경로 (`embed_text`) 만 lru_cache 사용. batch 는 캐시 무시 —
    동일 호출 1회로 끝나니 캐시 hit 이득보다 코드 단순성 우선.
    """
    if not texts:
        return []

    results: list[Optional[list[float]]] = [None] * len(texts)

    # 빈 문자열 거르고 dedupe — 같은 텍스트 중복 호출 방지 (cost / latency ↓)
    text_to_indices: dict[str, list[int]] = {}
    for i, t in enumerate(texts):
        cleaned = (t or "").strip()
        if cleaned:
            text_to_indices.setdefault(cleaned, []).append(i)

    if not text_to_indices:
        return results

    client = _get_client()
    if client is None:
        return results  # 클라이언트 없음 → None 채로 반환 (caller 가 fallback)

    unique_texts = list(text_to_indices.keys())
    try:
        response = client.embeddings.create(
            model=DEFAULT_MODEL,
            input=unique_texts,
        )
    except Exception as e:
        logger.warning(f"[embedding] batch API 호출 실패 — 키워드 fallback: {e}")
        return results  # None 채로

    # 토큰 사용량 추적 — 누적 store 에 기록.
    try:
        from app.token_tracker import track_embedding_usage
        total = getattr(response.usage, "total_tokens", 0) if getattr(response, "usage", None) else 0
        track_embedding_usage("embedding.embed_texts", DEFAULT_MODEL, total)
    except Exception:
        pass

    for txt, data in zip(unique_texts, response.data):
        vec = list(data.embedding)
        for orig_idx in text_to_indices[txt]:
            results[orig_idx] = vec

    return results


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """두 벡터 cosine similarity. -1.0 부터 1.0.

    None / 빈 vector / 길이 불일치 → 0.0 반환 (안전한 fallback).
    """
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


def is_available() -> bool:
    """임베딩 사용 가능 여부 (caller 가 분기 결정용).

    True = OpenAI 호출 정상 (또는 아직 시도 안 함, 첫 호출이 실패할 수도)
    False = API_KEY 없거나 초기화 실패 확정 → 키워드 매칭 즉시 회귀.
    """
    return not _client_init_failed and (_get_client() is not None)
