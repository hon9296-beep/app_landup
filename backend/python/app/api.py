"""
배치 엔진 FastAPI 진입점 — Java 백엔드에서 내부 호출.

auth/DB/파일저장은 Java가 담당. Python은 순수 배치 연산만.
Java(8081) → Python(8000) 내부 통신.

구조:
  - 엔드포인트 정의           : app/routers/*
  - state 생성·파이프라인     : app/services/*
  - state → JSON 직렬화       : app/serializers/*
  - 요청/응답 Pydantic 스키마 : app/schemas/*
  - 실패 메시지 사전          : app/failure_messages.py
  - 디버그 덤프               : app/debug.py

규모별 분기:
  - 대형·야외 (>= 165m², ~50평): nodes_large 파이프라인
  - 소·중형 (< 165m²):           nodes_small 파이프라인
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 2026-05-01: 명시 경로 로드 — uvicorn cwd 에 의존하지 않게.
# 진규님 진단 (5-1 12:39 fallback): cwd=루트에서 uvicorn 실행 시 루트 .env 만 잡혀
# 루트 .env 의 ANTHROPIC_API_KEY 가 주석이면 키 누락 → API_KEY_MISSING fallback.
# 두 .env 명시 로드. override=False (이미 OS 환경변수에 있으면 보존).
# - 루트 .env  : 인프라 (DB / Java↔Python 인증)
# - backend/.env: LLM API 키 (ANTHROPIC_API_KEY 등)
# 같은 키가 양쪽 있으면 먼저 로드된 게 우선 (= 루트 .env). 충돌 시 명시 우선순위.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / "backend" / ".env")

# Issue #517 — langsmith 0.7.30 + pydantic 2.12 호환 fix.
# RunTree forward ref (Path) 미해결로 LangChainTracer.on_chain_start 콜백이
# PydanticUserError 던져 trace 차단. RunTree.model_rebuild() 강제 호출로 해결.
# LANGCHAIN_TRACING_V2=true 일 때만 의미 있고, 비활성화 시 무해.
if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true":
    try:
        from langsmith.run_trees import RunTree
        RunTree.model_rebuild()
    except Exception as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"[langsmith] RunTree.model_rebuild 실패: {_e}")

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import brand, ceiling, detect, health, place, report, run, space, token_usage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# placement 모듈만 DEBUG — slot별 reject 사유 추적용
logging.getLogger("app.nodes_small.placement").setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

_INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
_SKIP_AUTH_PATHS = {"/health", "/api/health", "/docs", "/openapi.json", "/redoc"}
# 2026-05-08: prefix 기반 SKIP — dev 용 endpoint 가 추가되면 여기 prefix 만 박으면 됨.
# /api/token_usage/* — 비용 추적 dev 배지 (frontend 직통 fetch, 인증 X 의도).
_SKIP_AUTH_PREFIXES = ("/api/token_usage/",)

app = FastAPI(title="LandUp Placement Engine", version="4.0.0")


@app.middleware("http")
async def internal_auth_middleware(request: Request, call_next):
    """Java→Python 내부 호출 전용 인증. INTERNAL_API_KEY 미설정 시 개발 모드로 동작."""
    path = request.url.path
    if not _INTERNAL_API_KEY or path in _SKIP_AUTH_PATHS or path.startswith(_SKIP_AUTH_PREFIXES):
        return await call_next(request)
    token = request.headers.get("X-Internal-Token", "")
    if token != _INTERNAL_API_KEY:
        logger.warning("internal_auth 실패: path=%s", path)
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 라우터 등록 ──────────────────────────────────────────
app.include_router(health.router)
app.include_router(detect.router)
app.include_router(ceiling.router)
app.include_router(brand.router)
app.include_router(space.router)
app.include_router(place.router)
app.include_router(run.router)
app.include_router(report.router)
app.include_router(token_usage.router)


# ── report endpoint test back-compat ─────────────────────
# tests/test_report_endpoint.py 가 `from app.api import _build_report_data` 로 import.
# 다른 shim (worker.py 호환용 _dump_debug / _is_large / _place_large 등) 은 2026-05-02
# 데드코드 검증으로 모두 삭제 — 호출자 0건 확인 (api.py 자체 주석 외).
from app.services.report_service import _build_report_data  # noqa: E402

__all__ = ["app", "_build_report_data"]
