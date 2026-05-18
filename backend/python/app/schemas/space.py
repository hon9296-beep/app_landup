"""
/api/space-data 요청/응답 스키마.

현재 라우터는 `dict` 로 받지만 Pydantic 스키마를 병행 노출해 계약 문서화.
모든 필드 Optional + extra=allow 로 시작 (422 회귀 방지).
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SpaceDataRequest(BaseModel):
    """POST /api/space-data 요청 body."""
    model_config = ConfigDict(extra="allow")

    auto_detected: dict[str, Any] = {}
    """파서+비전 결과 (floor_polygon_px, scale_mm_per_px, entrance, sprinklers, ...)"""

    brand_dict: dict[str, Any] = {}
    brand_category: Optional[str] = "기타"

    venue_type: Optional[str] = None
    facade_type: Optional[str] = None

    manual_dead_zones_px: list[dict] = []
    """프론트에서 유저가 찍은 수동 데드존 — rect or circle (shape 필드로 구분)"""


class SpaceDataResponse(BaseModel):
    """POST /api/space-data 응답. `space_data` 안에 serialize 결과."""
    model_config = ConfigDict(extra="allow")

    space_data: dict[str, Any]
