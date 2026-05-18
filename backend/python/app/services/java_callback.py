"""
Java 내부 API 콜백 — 워커 작업 상태 업데이트 전송.

Python worker(비동기 파이프라인) → Java backend(/api/internal/job-update).
status/progress/error 를 평탄화해서 Java InternalJobUpdate record 에 맞춤.

2026-05-04 (M1 fix) - exponential backoff 재시도 추가 (3회). Java 일시 down / 네트워크 글리치 방어.
"""
import asyncio
import logging
from typing import Any

import httpx

from app.worker_config import JAVA_INTERNAL_URL, get_http_client

logger = logging.getLogger(__name__)

# 재시도 정책 (M1 fix). 1s → 2s → 4s 지연 후 포기. critical=True 면 마지막 실패 시 raise.
_NOTIFY_MAX_ATTEMPTS = 3
_NOTIFY_BASE_DELAY_S = 1.0


async def notify_java(job_id: int, *, critical: bool = False, **fields: Any) -> None:
    """
    Java `/internal/job-update` 엔드포인트에 상태 업데이트 전송.

    fields 예시:
      - status: "running" | "done" | "error"
      - progress: {stage, pct, message}  → progress_stage/pct/message 로 평탄화
      - result_project_id: int
      - error_message: str
    """
    url = f"{JAVA_INTERNAL_URL}/api/internal/job-update"
    payload: dict[str, Any] = {"job_id": job_id}
    # Java InternalJobUpdate record 는 flat 3필드 (progress_stage/pct/message). dict 평탄화.
    for key, value in fields.items():
        if key == "progress" and isinstance(value, dict):
            payload["progress_stage"] = value.get("stage")
            payload["progress_pct"] = value.get("pct")
            payload["progress_message"] = value.get("message")
        else:
            payload[key] = value

    last_exc: Exception | None = None
    for attempt in range(1, _NOTIFY_MAX_ATTEMPTS + 1):
        try:
            r = await get_http_client().post(url, json=payload)
            r.raise_for_status()
            return
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < _NOTIFY_MAX_ATTEMPTS:
                delay = _NOTIFY_BASE_DELAY_S * (2 ** (attempt - 1))
                logger.warning(
                    f"[notify_java] 시도 {attempt}/{_NOTIFY_MAX_ATTEMPTS} 실패 job_id={job_id}: {e}. {delay:.1f}s 후 재시도"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"[notify_java] {_NOTIFY_MAX_ATTEMPTS}회 모두 실패 job_id={job_id}: {e}")

    if critical and last_exc is not None:
        raise last_exc
