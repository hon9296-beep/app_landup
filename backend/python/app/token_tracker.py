"""LLM 토큰 사용량 추적 — 메모리 누적 (dev 용도, 단순 버전).

2026-05-08 단순화:
  이전 버전은 매 LLM 호출마다 cumulative_token_usage.json 파일을 read-modify-write 했음.
  Windows 도커 볼륨 마운트 IO 가 host↔container 통과 시 매우 느려서 분석 시간 2배.
  → 메모리 list 만 유지 (디스크 X). dev 환경에 backend 재시작 시 reset 되도 OK.

2026-05-09 사이클 분리 복원:
  5/8 단순화 시 dump_and_reset 의 reset 폐기 → 누적만 반환 → place_service 가 매 사이클마다 누적 받음
  → DB 의 placement_results.token_usage 에 사이클 단위 분리 X (이전 사이클 비용까지 포함된 누적값).
  → _CYCLE_ENTRIES 사이클 store 신설. dump_and_reset 가 사이클 summary 만 반환 + 사이클 store 비움.
  누적 store (_ENTRIES) 는 영구 유지 (dashboard endpoint 용). logger.info 추가 X (로그 뭉터기 회피).

사용법:
    from app.token_tracker import track_usage, track_embedding_usage

    response = client.messages.create(...)
    track_usage("design.py", response)

    resp = client.embeddings.create(model="text-embedding-3-small", input=[...])
    track_embedding_usage("ref_trace_scorer", "text-embedding-3-small", resp.usage.total_tokens)

조회:
  GET  /api/token_usage/cumulative → 모든 호출 누적 (모델별 + 노드별)
  POST /api/token_usage/reset      → 메모리 list 비움

가격: Anthropic 공식 (2026-05-07) + OpenAI 공식. 환율 $1=1400원 (사용자 고정).
"""
import logging
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── 가격표 (1M 토큰당 USD) ─────────────────────────────────────────────
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7":   {"input": 5.0,  "cache_write": 6.25, "cache_read": 0.50, "output": 25.0},
    "claude-opus-4-6":   {"input": 5.0,  "cache_write": 6.25, "cache_read": 0.50, "output": 25.0},
    "claude-opus-4-5":   {"input": 5.0,  "cache_write": 6.25, "cache_read": 0.50, "output": 25.0},
    "claude-opus-4-1":   {"input": 15.0, "cache_write": 18.75, "cache_read": 1.50, "output": 75.0},
    "claude-opus-4":     {"input": 15.0, "cache_write": 18.75, "cache_read": 1.50, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0,  "cache_write": 3.75, "cache_read": 0.30, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0,  "cache_write": 3.75, "cache_read": 0.30, "output": 15.0},
    "claude-sonnet-4":   {"input": 3.0,  "cache_write": 3.75, "cache_read": 0.30, "output": 15.0},
    "claude-haiku-4-5":  {"input": 1.0,  "cache_write": 1.25, "cache_read": 0.10, "output": 5.0},
    "claude-haiku-3-5":  {"input": 0.80, "cache_write": 1.0,  "cache_read": 0.08, "output": 4.0},
    "claude-haiku-3":    {"input": 0.25, "cache_write": 0.30, "cache_read": 0.03, "output": 1.25},
    "text-embedding-3-small": {"input": 0.02, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0},
    "text-embedding-ada-002": {"input": 0.10, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0},
}
_FALLBACK_PRICING = MODEL_PRICING["claude-sonnet-4-6"]

USD_TO_KRW = 1400.0


def _resolve_pricing(model: str) -> dict[str, float]:
    """모델 ID 로 가격표 lookup. prefix 매칭 fallback (예: 'claude-sonnet-4-6-20251001'). 그래도 없으면 sonnet 기준."""
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, pricing in MODEL_PRICING.items():
        if model.startswith(key):
            return pricing
    logger.warning(f"[token] 알 수 없는 모델 '{model}' — sonnet-4-6 가격으로 추정")
    return _FALLBACK_PRICING


def _calc_cost_usd(model: str, input_tokens: int, output_tokens: int,
                   cache_read: int = 0, cache_write: int = 0) -> float:
    p = _resolve_pricing(model)
    return (
        input_tokens   * p["input"]       / 1_000_000
        + output_tokens  * p["output"]      / 1_000_000
        + cache_read     * p["cache_read"]  / 1_000_000
        + cache_write    * p["cache_write"] / 1_000_000
    )


# ── 메모리 store (누적 + 사이클, 단일 lock thread-safe) ─────────────────────────
# _ENTRIES: 영구 누적 (dashboard endpoint /api/token_usage/cumulative 용).
# _CYCLE_ENTRIES: 사이클 단위 (place_service 사이클 끝 시 dump_and_reset 호출 → 비움).
# 5/9 사이클 분리 복원 — DB 의 placement_results.token_usage 에 사이클 단위 정확 분리.
_LOCK = threading.Lock()
_ENTRIES: list[dict] = []
_CYCLE_ENTRIES: list[dict] = []


def _append_entry(entry: dict) -> None:
    """thread-safe append — 두 store 모두."""
    with _LOCK:
        _ENTRIES.append(entry)
        _CYCLE_ENTRIES.append(entry)


def track_usage(node_name: str, response: Any, model: str | None = None) -> None:
    """Anthropic API 응답 → 메모리 누적. 매 호출마다 디스크 IO X."""
    try:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        m = model or getattr(response, "model", "unknown")
        in_tok = getattr(usage, "input_tokens", 0)
        out_tok = getattr(usage, "output_tokens", 0)
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cost_usd = _calc_cost_usd(m, in_tok, out_tok, cache_read, cache_write)

        _append_entry({
            "node": node_name,
            "model": m,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
            "cost_usd": round(cost_usd, 6),
            "timestamp": datetime.now().isoformat(),
        })
        # info → debug 로 줄임 (호출 폭주 시 로그 시끄러워서). 중요한 정보는 endpoint 로 본다.
        logger.debug(
            f"[token] {node_name} ({m}): in={in_tok}, out={out_tok}, cost=${cost_usd:.4f}"
        )
    except Exception as e:
        logger.warning(f"[token] {node_name} 사용량 추출 실패: {e}")


def track_embedding_usage(node_name: str, model: str, total_tokens: int) -> None:
    """OpenAI 임베딩 호출 토큰 추적."""
    try:
        cost_usd = _calc_cost_usd(model, total_tokens, 0, 0, 0)
        _append_entry({
            "node": node_name,
            "model": model,
            "input_tokens": total_tokens,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cost_usd": round(cost_usd, 6),
            "timestamp": datetime.now().isoformat(),
        })
        logger.debug(f"[token] {node_name} ({model}): in={total_tokens}, cost=${cost_usd:.6f}")
    except Exception as e:
        logger.warning(f"[token] {node_name} (embedding) 사용량 추출 실패: {e}")


# ── summary 빌더 (누적 / 사이클 공용 helper) ─────────────────────────

def _build_summary_from_entries(entries: list[dict]) -> dict:
    """entries list → 모델별 + 노드별 집계 + total summary.

    누적 store (_ENTRIES) / 사이클 store (_CYCLE_ENTRIES) 둘 다 같은 형식이라 공용 helper.
    호출자 (get_cumulative_summary / dump_and_reset) 가 entries snapshot 떠서 전달.
    """
    from collections import defaultdict
    by_model: dict[str, dict[str, float]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "cost_usd": 0.0, "calls": 0}
    )
    by_node: dict[str, dict[str, float]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "cost_usd": 0.0, "calls": 0}
    )
    total_in = total_out = total_cr = total_cw = 0
    total_cost = 0.0
    for e in entries:
        m = e.get("model", "unknown")
        n = e.get("node", "unknown")
        in_tok = e.get("input_tokens", 0)
        out_tok = e.get("output_tokens", 0)
        cr = e.get("cache_read_input_tokens", 0)
        cw = e.get("cache_creation_input_tokens", 0)
        cost = e.get("cost_usd", 0.0)

        for bucket, key in ((by_model, m), (by_node, n)):
            bucket[key]["input"] += in_tok
            bucket[key]["output"] += out_tok
            bucket[key]["cache_read"] += cr
            bucket[key]["cache_creation"] += cw
            bucket[key]["cost_usd"] += cost
            bucket[key]["calls"] += 1

        total_in += in_tok
        total_out += out_tok
        total_cr += cr
        total_cw += cw
        total_cost += cost

    for bucket in (by_model, by_node):
        for v in bucket.values():
            v["cost_usd"] = round(v["cost_usd"], 6)

    return {
        "total_calls": len(entries),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cache_read_tokens": total_cr,
        "total_cache_creation_tokens": total_cw,
        "total_tokens": total_in + total_out + total_cr + total_cw,
        "total_cost_usd": round(total_cost, 6),
        "total_cost_krw": round(total_cost * USD_TO_KRW, 0),
        "usd_to_krw": USD_TO_KRW,
        "by_model": dict(by_model),
        "by_node": dict(by_node),
        "started_at": entries[0]["timestamp"] if entries else None,
        "updated_at": entries[-1]["timestamp"] if entries else None,
    }


# ── 누적 API ─────────────────────────────────────────────────────────

def get_cumulative_summary() -> dict:
    """영구 누적 store summary — dashboard endpoint 용."""
    with _LOCK:
        entries = list(_ENTRIES)
    return _build_summary_from_entries(entries)


def reset_cumulative() -> dict:
    """메모리 store 둘 다 비움 — 누적 + 사이클 (일관성)."""
    with _LOCK:
        _ENTRIES.clear()
        _CYCLE_ENTRIES.clear()
    logger.info("[token] 누적 store 리셋")
    return {"ok": True, "reset_at": datetime.now().isoformat()}


# ── 호환 stub (기존 호출자 deprecation 방지) ─────────────────────────
# 이전 dump_and_reset / reset 함수가 다른 모듈에서 import 되면 깨지지 않게 stub 유지.
# 사이클별 디스크 dump 는 제거 (필요 시 endpoint 로 조회).

def dump_and_reset() -> dict:
    """사이클별 summary 반환 + _CYCLE_ENTRIES 비움 (2026-05-09 사이클 분리 복원).

    호출 시점: place_service 의 사이클 끝 (ㄴ-1 ~ ㄴ-3 LangGraph 종료 직후).
    반환: 그 사이클의 LLM 호출만 집계한 summary (place_service → state["token_usage_summary"]
          → place_serializer → Java placement_results.token_usage 영속).
    누적 store (_ENTRIES) 는 영구 유지 — dashboard endpoint 로 조회.

    logger.info 제거 (2026-05-09) — 5/8 단순화 시 30초 주기 로그 뭉터기 회피 의도. dump 로그 X.
    """
    with _LOCK:
        cycle_entries = list(_CYCLE_ENTRIES)
        _CYCLE_ENTRIES.clear()
    return _build_summary_from_entries(cycle_entries)


def reset() -> None:
    """[deprecated] 사이클 단위 reset 폐기. 누적 reset 은 reset_cumulative 사용."""
    pass
