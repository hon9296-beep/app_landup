"""
/api/detect 응답 스키마.

파싱(PDF/DXF/Image) + Vision 감지 결과. DB 저장은 Java 가 담당.
현재 엔드포인트는 Pydantic response_model 를 강제하지 않음 — Java 계약 보호용.
이 스키마는 구조 문서 + 프론트 타입 동기화 참고용.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DetectResponse(BaseModel):
    """POST /api/detect 응답. 필드 거의 전부 Optional — 파서/비전 실패 시 일부 누락 가능."""
    model_config = ConfigDict(extra="allow")

    floor_polygon_px: Optional[list] = None
    scale_mm_per_px: Optional[float] = None
    scale_confirmed: bool = False
    entrance: Optional[dict] = None
    entrances: list = []
    sprinklers: list = []
    fire_hydrants: list = []
    electrical_panels: list = []
    inaccessible_rooms: list = []
    inner_walls: list = []
    detected_width_mm: Optional[float] = None
    detected_height_mm: Optional[float] = None
    ceiling_height_mm: Optional[float] = None
    image_base64: Optional[str] = None
    vision_transform: Optional[dict] = None
    page_count: int = 1
