"""토큰 사용량 누적 조회 / 리셋 API — 개발 dashboard 용 (2026-05-07 신설).

기능:
  - GET  /api/token_usage/cumulative → 누적 요약 (모델별 + 노드별 + 총 토큰/$/₩)
  - POST /api/token_usage/reset      → 누적 store 0 리셋

저장:
  backend/python/debug_logs/cumulative_token_usage.json (단일 파일, 리셋 시 빈 list).
  매 LLM/embedding 호출마다 token_tracker._append_cumulative() 가 즉시 디스크 쓰기.

용도: 개발 중 비용 모니터링. 프로덕션 X.
"""
from fastapi import APIRouter

from app.token_tracker import get_cumulative_summary, reset_cumulative

router = APIRouter(prefix="/api/token_usage", tags=["token_usage"])


@router.get("/cumulative")
async def cumulative():
    """누적 토큰/비용 요약 — 마지막 리셋 이후 모든 호출 합산.

    Returns:
        {
          "total_calls": N,
          "total_input_tokens" / "total_output_tokens" / "total_cache_*",
          "total_tokens": (in + out + cache_read + cache_creation),
          "total_cost_usd": float,
          "total_cost_krw": float,
          "usd_to_krw": 1400.0,
          "by_model": {<model_id>: {input, output, cache_read, cache_creation, cost_usd, calls}},
          "by_node":  {<node_name>: {... 동일 ...}},
          "started_at": iso_str | null,
          "updated_at": iso_str | null,
        }
    """
    return get_cumulative_summary()


@router.post("/reset")
async def reset():
    """누적 0 리셋. 빈 list 로 덮어쓰기. 사이클별 dump 는 영향 X."""
    return reset_cumulative()
