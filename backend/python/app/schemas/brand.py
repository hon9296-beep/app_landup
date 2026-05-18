"""
/api/brand 응답 스키마.

브랜드 매뉴얼 LLM 추출 결과. 구조가 LLM 응답에 따라 가변적이라 lenient dict.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict


class BrandResponse(BaseModel):
    """POST /api/brand 응답. 최상위에 brand / fire / construction / placement_rules 등이 올 수 있음."""
    model_config = ConfigDict(extra="allow")

    brand: dict[str, Any] = {}
    fire: dict[str, Any] = {}
    construction: dict[str, Any] = {}
    placement_rules: list = []
