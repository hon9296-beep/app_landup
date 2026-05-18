"""/api/ceiling-height — 단면도 파일에서 ceiling_height_mm 추출."""
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.dxf_utils import convert_dwg_to_dxf, extract_ceiling_height_from_dxf

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/ceiling-height")
async def detect_ceiling_height(
    cross_section: UploadFile = File(...),
    file_type: str = Form("pdf"),
):
    """단면도 파일(PDF/DXF/DWG)에서 천장 높이만 추출."""
    try:
        file_bytes = await cross_section.read()

        if file_type == "dwg":
            file_bytes = convert_dwg_to_dxf(file_bytes)
            result = extract_ceiling_height_from_dxf(file_bytes)
        elif file_type == "dxf":
            result = extract_ceiling_height_from_dxf(file_bytes)
        else:
            from app.nodes_small import parser
            state = {"file_bytes": file_bytes, "file_type": file_type, "fallback_round": 0}
            parsed = parser.run(state)
            result = {"ceiling_height_mm": parsed.get("ceiling_height_mm"), "confidence": None}

        logger.info("[ceiling] file_type=%s result=%s", file_type, result)
        return result

    except Exception as e:
        logger.error("[ceiling] 추출 실패: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
