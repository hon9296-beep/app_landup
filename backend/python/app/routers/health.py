"""헬스체크 — Java 내부 핑용."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}
