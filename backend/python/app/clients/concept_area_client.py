"""
Java /api/internal/concept-areas 클라이언트 (2026-05-01 신설).

역할:
  - concept_area.py LLM 결정 후 Java 통해 concept_areas 테이블에 batch INSERT
  - 응답으로 {area_name: id} dict 받아 state.concept_areas[i].id 채움
  - 이후 placement.py 가 anchor / placement_object 의 concept_area_id FK 채우기 가능

실패 정책 (배치 파이프라인 blocking 금지):
  - 네트워크 실패 / 5xx / timeout → warning + 빈 dict 반환
  - 활성화 off / Java 다운 시 빈 dict — 파이프라인 정상 진행 (FK NULL 로)

활성화 조건:
  - 환경변수 REF_IMAGE_HANDOFF_ENABLED == "1" (ref_image 와 동일 스위치 — Java API 통합 토글)
  - 기본 off — 로컬 python-only 테스트 호환
"""
from __future__ import annotations

import logging
import os
from typing import Optional, TypedDict

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_S = 5.0


def _enabled() -> bool:
    return os.environ.get("REF_IMAGE_HANDOFF_ENABLED") == "1"


def _base_url() -> str:
    return os.environ.get("JAVA_API_BASE", "http://localhost:8081/api").rstrip("/")


class ConceptAreaPayload(TypedDict, total=False):
    name: str                  # 영문 키 (welcome / photo / experience / ...)
    polygonJson: Optional[str]  # Shapely Polygon → [[x,y],...] JSON str
    areaRatio: Optional[float]
    targetObjectsJson: Optional[str]  # ["counter"] 같은 JSON list str


def register_concept_areas_batch(
    floor_detection_id: int,
    areas: list[ConceptAreaPayload],
) -> dict[str, int]:
    """Java `POST /internal/concept-areas/batch` — 일괄 영속.

    반환:
      - 활성화 + 성공: {"welcome": 1, "photo": 2, ...} (name → id)
      - 비활성 / 네트워크 실패 / 검증 실패: 빈 dict (FK NULL 흐름 정상 진행)
    """
    if not _enabled():
        return {}
    if not floor_detection_id or not areas:
        return {}

    url = f"{_base_url()}/internal/concept-areas/batch"
    payload = {
        "floorDetectionId": floor_detection_id,
        "areas": areas,
    }
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT_S)
        if resp.status_code not in (200, 201):
            logger.warning(
                "[concept_area_client] batch %s status=%s body=%s",
                url, resp.status_code, resp.text[:200],
            )
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[concept_area_client] batch 실패: %s", e)
        return {}
