"""/api/run — 전체 파이프라인 1회 실행 (디버그용, large 만)."""
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.graph import compile_large_graph
from app.serializers.place_serializer import serialize_result

router = APIRouter()
logger = logging.getLogger(__name__)

# 그래프 컴파일 (1회) — module-level 싱글톤. large 디버그 통합본만 유지.
# (small 통합본 build_small_graph 는 1-1 작업으로 제거됨 — Small 운영은 place_service.place_small + AGENT_GRAPH 가 담당)
_pipeline_large = compile_large_graph()


@router.post("/api/run")
async def run_pipeline(
    floor_plan: UploadFile = File(...),
    brand_manual: Optional[UploadFile] = File(None),
    file_type: str = Form("pdf"),
    density_ratio: Optional[float] = Form(None),
):
    """전체 파이프라인 실행 (large 디버그 통합본)."""
    try:
        floor_bytes = await floor_plan.read()
        brand_bytes = None
        if brand_manual:
            brand_bytes = await brand_manual.read()

        initial_state = {
            "file_bytes": floor_bytes,
            "file_type": file_type,
            "brand_bytes": brand_bytes,
            "density_ratio": density_ratio,
            "fallback_round": 0,
        }

        result = _pipeline_large.invoke(initial_state)
        return serialize_result(result)

    except Exception as e:
        logger.error(f"Pipeline 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
