"""/api/brand — 브랜드 메뉴얼 LLM 추출."""
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/brand")
async def extract_brand(
    brand_manual: UploadFile = File(...),
    file_type: str = Form("pdf"),
):
    try:
        brand_bytes = await brand_manual.read()
        from app.nodes_small.reference import run as reference_run
        result = reference_run({"brand_bytes": brand_bytes, "brand_file_type": file_type})
        brand_data = result.get("brand_data", {})
        return brand_data
    except Exception as e:
        logger.error(f"Brand 추출 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
