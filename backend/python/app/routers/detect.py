"""/api/detect — 파싱(PDF/DXF/Image) + Vision 감지."""
import base64
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/detect")
async def detect_only(
    floor_plan: UploadFile = File(...),
    file_type: str = Form("pdf"),
    force_layer: str = Form(None),
):
    """파싱 + Vision 감지. DB 저장 없음 — Java가 처리."""
    try:
        floor_bytes = await floor_plan.read()

        initial_state = {
            "file_bytes": floor_bytes,
            "file_type": file_type,
            "fallback_round": 0,
            "force_layer": force_layer,
        }

        from app.nodes_small import parser, parser_dxf, parser_image, vision

        if file_type in ("dxf", "dwg"):
            parse_result = parser_dxf.run(initial_state)
            # Tier 2: 자동 추출 실패 → 레이어 목록만 반환 (Vision 호출 생략)
            if parse_result.get("parse_status") == "layer_select_needed":
                return {
                    "parse_status": "layer_select_needed",
                    "available_layers": parse_result.get("available_layers", []),
                }
        elif file_type == "image":
            parse_result = parser_image.run(initial_state)
        else:
            parse_result = parser.run(initial_state)

        merged = {**initial_state, **parse_result}
        vision_result = vision.run(merged)
        merged.update(vision_result)

        image_bytes = merged.get("image_bytes")
        image_base64 = base64.b64encode(image_bytes).decode() if image_bytes else None

        return {
            "floor_polygon_px": merged.get("floor_polygon_px"),
            "scale_mm_per_px": merged.get("scale_mm_per_px"),
            "scale_confirmed": merged.get("scale_confirmed", False),
            "entrance": merged.get("entrance"),
            "entrances": merged.get("entrances") or [],
            "sprinklers": merged.get("sprinklers") or [],
            "fire_hydrants": merged.get("fire_hydrants") or [],
            "electrical_panels": merged.get("electrical_panels") or [],
            "inaccessible_rooms": merged.get("inaccessible_rooms") or [],
            "inner_walls": merged.get("inner_walls") or [],
            "detected_width_mm": merged.get("detected_width_mm"),
            "detected_height_mm": merged.get("detected_height_mm"),
            "ceiling_height_mm": merged.get("ceiling_height_mm"),
            "image_base64": image_base64,
            "vision_transform": merged.get("vision_transform"),
            "page_count": merged.get("page_count") or 1,
        }

    except Exception as e:
        logger.error(f"Detect 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
