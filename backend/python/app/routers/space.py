"""/api/space-data — 공간 계산 + state 캐싱."""
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.space import SpaceDataRequest
from app.services.space_service import build_space_data

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/space-data")
async def space_data(body: SpaceDataRequest):
    """공간 데이터 계산. 면적에 따라 대형/소중형 노드 분기. DB 저장 없음 — Java가 처리."""
    try:
        return build_space_data(body.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Space-data 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
