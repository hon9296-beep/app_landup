"""
/api/place 요청 스키마.

응답 구조는 PlacementResultService.applyPlaceResult 와의 계약이므로
response_model 로 강제하지 않음 (깨지면 Java 쪽이 터짐).
구조 참조: app/serializers/place_serializer.format_place_response
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class PlaceRequest(BaseModel):
    """POST /api/place 요청 body. _rebuild_state_from_body 입력과 1:1."""
    model_config = ConfigDict(extra="allow")

    # 공간 데이터 (space-data 응답 재입력)
    floor: dict[str, Any] = {}
    entrance: dict[str, Any] = {}
    dead_zones: list[dict] = []
    sprinklers_mm: list = []
    hydrants_mm: list = []
    electric_panels_mm: list = []

    # 브랜드
    brand_dict: dict[str, Any] = {}
    brand_category: Optional[str] = None

    # 엔진 분기 힌트 (space-data 에서 내려준 값 그대로)
    venue_type: Optional[str] = None
    facade_type: Optional[str] = None

    # 실행 파라미터
    density_ratio: Optional[float] = None
    user_requirements: Optional[str] = ""
    locked_objects: list[dict] = []

    # extra=allow 로 수용되는 필드 (Pydantic v2 에서 언더스코어 prefix 는 private 취급이라 모델 선언 불가)
    #   _session_id: Optional[str]  — space-data 응답에서 내려준 세션 토큰. 캐시 비활성화 상태라 로그 키용.
