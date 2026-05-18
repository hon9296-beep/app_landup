"""
워커 런타임 설정 — Redis 커넥션 + Java 내부 API URL + 큐 파라미터.

worker.py / handlers/* / services/java_callback.py 공용. 환경변수 기반.
"""
import os

import redis

# ── 외부 서비스 ──────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
JAVA_INTERNAL_URL = os.getenv("JAVA_INTERNAL_URL", "http://backend-java:8080")

# ── 큐/워커 파라미터 ─────────────────────────────────────
QUEUE_NAME = "job_queue"
CANCEL_KEY_PREFIX = "cancel:"
BRPOP_TIMEOUT = 5   # 초. Ctrl+C 반응성 위해 짧게
MAX_CONCURRENT_JOBS = 10  # 동시 처리 중 작업 수 제한 (LLM I/O 바운드라 여유 있게 가능)


# ── Redis 클라이언트 싱글톤 ──────────────────────────────
_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Redis 커넥션 싱글톤."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
        )
    return _redis_client


def is_cancelled(job_id: int) -> bool:
    """Java 가 설정한 취소 신호 확인 — handler 단계 경계마다 호출."""
    return bool(get_redis().exists(f"{CANCEL_KEY_PREFIX}{job_id}"))


# ── 공유 HTTP 클라이언트 싱글톤 ──────────────────────────
import httpx as _httpx

_http_client: _httpx.AsyncClient | None = None


def get_http_client() -> _httpx.AsyncClient:
    """공유 httpx AsyncClient 싱글톤 — TCP 커넥션 재사용."""
    global _http_client
    if _http_client is None:
        _http_client = _httpx.AsyncClient(
            timeout=10,
            limits=_httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=30,
            ),
        )
    return _http_client
