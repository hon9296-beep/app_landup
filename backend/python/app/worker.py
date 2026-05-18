"""
배치 워커 — Redis 큐 기반 비동기 백그라운드 작업 처리.

실행:
    python -m app.worker

구조:
  - Redis `job_queue` 리스트에서 BRPOP 으로 블로킹 대기
  - Java 가 `LPUSH job_queue {id, type, params}` 로 작업 넣음
  - 워커가 type 별 핸들러 분기 (app/handlers/*.handle)
  - 완료/실패 시 Java 에 HTTP 콜백 (services/java_callback.notify_java)

모듈 분해:
  - 설정/Redis 커넥션 : app/worker_config.py
  - Java 콜백         : app/services/java_callback.py
  - 각 작업 핸들러    : app/handlers/{detect,brand,space_data,place,export}.py
  - 이 파일            : 루프 + dispatch + shutdown 제어만

흐름:
    [Java]  LPUSH job_queue {id, type, params}
              ↓
    [Python worker]  BRPOP job_queue → dispatch_job
              ↓
    [handler]   파이프라인 호출 (services/*) + 단계별 notify_java(progress)
              ↓
    [Python worker]  POST http://backend-java:8080/api/internal/job-update
                      body: {job_id, status, progress, result, error}
"""
import asyncio
import json
import logging
import signal

import redis

from app.handlers import JOB_HANDLERS
from app.services.java_callback import notify_java
from app.worker_config import (
    BRPOP_TIMEOUT,
    MAX_CONCURRENT_JOBS,
    QUEUE_NAME,
    REDIS_HOST,
    REDIS_PORT,
    get_redis,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── dispatch ──────────────────────────────────────────

# 2026-05-04 (R3 fix) - Idempotency 정책. worker 크래시 후 재시작 / 동일 job 재 dispatch 방지.
_IDEMPOTENCY_KEY_PREFIX = "job:done:"
_IDEMPOTENCY_TTL_SEC = 24 * 3600  # 24h. Redis 컨테이너 재시작 시 자동 휘발이라 사실상 안전 마진.


async def dispatch_job(raw_job: str) -> None:
    """
    Redis에서 꺼낸 job JSON을 파싱 → 타입별 핸들러로 분기.

    예상 포맷:
      {"id": 123, "type": "place", "params": {...}}

    Idempotency: `job:done:{job_id}` SET 존재 시 skip (중복 dispatch 방지).
    핸들러 성공 시 mark done. 실패 시 mark X (재시도 가능).
    """
    try:
        job = json.loads(raw_job)
        job_id = job["id"]
        job_type = job["type"]
        params = job.get("params", {})
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"[dispatch] job 파싱 실패: {e}, raw={raw_job[:200]}")
        return

    # 2026-05-04 (R3 fix) - Idempotency 검사. 동일 job_id 중복 처리 방지.
    r = get_redis()
    idem_key = f"{_IDEMPOTENCY_KEY_PREFIX}{job_id}"
    if r.exists(idem_key):
        logger.warning(f"[dispatch] job_id={job_id} 이미 처리 완료 (idempotency hit) — skip")
        return

    handler = JOB_HANDLERS.get(job_type)
    if handler is None:
        logger.error(f"[dispatch] 알 수 없는 job_type={job_type}, id={job_id}")
        await notify_java(job_id, status="error", error_message=f"unknown job_type: {job_type}")
        return

    logger.info(f"[dispatch] 작업 시작 id={job_id} type={job_type}")
    try:
        await handler(job_id, params)
        # 2026-05-04 (R3 fix) - 성공 후 idempotency 마킹. 실패 시 마킹 X (재시도 가능).
        r.set(idem_key, "1", ex=_IDEMPOTENCY_TTL_SEC)
    except NotImplementedError as e:
        logger.warning(f"[dispatch] 미구현 핸들러 id={job_id} type={job_type}")
        await notify_java(job_id, status="error", error_message=f"핸들러 미구현: {e}")
    except Exception as e:
        logger.error(f"[dispatch] 작업 실패 id={job_id}: {e}", exc_info=True)
        await notify_java(job_id, status="error", error_message=str(e))


# ── 메인 루프 ─────────────────────────────────────────

_shutdown_requested = False


def _handle_signal(signum, _frame):
    """Graceful shutdown 플래그 설정 (실제 종료는 루프가 확인)."""
    global _shutdown_requested
    logger.info(f"[worker] 시그널 수신: {signum}. 종료 준비 중...")
    _shutdown_requested = True


async def worker_loop() -> None:
    """
    Redis BRPOP 루프 — 큐 비어있으면 블로킹 대기, 작업 오면 dispatch.

    `MAX_CONCURRENT_JOBS` 동시 처리 제한:
      - asyncio.Semaphore 로 동시 실행 태스크 수 제한
      - 초과 시 새 작업은 semaphore 대기
    """
    sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    r = get_redis()
    logger.info(
        f"[worker] 시작: redis={REDIS_HOST}:{REDIS_PORT} queue={QUEUE_NAME} "
        f"max_concurrent={MAX_CONCURRENT_JOBS}"
    )

    async def run_one(raw_job: str) -> None:
        async with sem:
            await dispatch_job(raw_job)

    # 실행 중인 태스크 추적 (graceful shutdown 용)
    pending: set[asyncio.Task] = set()

    while not _shutdown_requested:
        try:
            # BRPOP 은 블로킹 — 비동기 루프에 안 맞으므로 run_in_executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, lambda: r.brpop(QUEUE_NAME, timeout=BRPOP_TIMEOUT)
            )
            if result is None:
                # 타임아웃 — shutdown 체크 후 계속
                continue

            _, raw_job = result  # (queue_name, value)
            task = asyncio.create_task(run_one(raw_job))
            pending.add(task)
            task.add_done_callback(pending.discard)

        except redis.ConnectionError as e:
            logger.error(f"[worker] Redis 연결 실패: {e}. 5초 후 재시도")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"[worker] 루프 에러: {e}", exc_info=True)
            await asyncio.sleep(1)

    # Graceful shutdown — 진행 중 작업 완료 대기
    logger.info(f"[worker] 종료 대기: 진행 중 {len(pending)}개 작업")
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    logger.info("[worker] 종료 완료")


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
