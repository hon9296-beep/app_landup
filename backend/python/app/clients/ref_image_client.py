"""
Java /api/internal/ref-images 클라이언트 (feature/ref-image-python-handoff).

역할:
  - DDG 다운로드 전 sha256 블랙리스트 체크 → 악질 이미지 재유입 차단
  - DDG 저장 성공 직후 Java 에 레코드 등록 → 관리자 페이지 조회 대상화

실패 정책 (배치 파이프라인 blocking 금지):
  - 네트워크 실패 / 5xx / timeout → warning 로그 + 안전한 default
    - blacklist check: False (저장 허용)
    - register: None (조용히 무시)
  - 운영 중 Java 임시 다운되어도 Python 배치는 정상 완료

활성화 조건:
  - 환경변수 REF_IMAGE_HANDOFF_ENABLED == "1"
  - 기본 off — Java 미기동 환경 / 로컬 python-only 테스트 호환
"""
from __future__ import annotations

import logging
import os
from typing import Optional, TypedDict

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_S = 3.0


def _enabled() -> bool:
    return os.environ.get("REF_IMAGE_HANDOFF_ENABLED") == "1"


def _base_url() -> str:
    # docker: backend-java:8080/api / local: localhost:8081/api
    return os.environ.get("JAVA_API_BASE", "http://localhost:8081/api").rstrip("/")


# ── 블랙리스트 체크 ───────────────────────────────────────────

def mark_blacklisted(sha256_full: str, reason: str = "") -> Optional[int]:
    """Java `POST /api/internal/ref-images/blacklist` — Vision LLM 부적절 판정 시 자동 차단 등록.

    같은 sha256 의 모든 user_project row 를 동시에 isBlacklisted=true 로 표시.
    blacklistedBy=null (system auto). 다음 DDG 다운로드 시 is_blacklisted 체크에서 skip.

    Returns: 새로 차단된 row 수 (이미 blacklisted 였던 row 제외) / 비활성·실패 시 None.
    배치 파이프라인 blocking 금지 — 등록 실패해도 분석 결과 폐기는 그대로 진행.
    """
    if not _enabled():
        return None
    if not sha256_full or len(sha256_full) != 64:
        logger.warning("[ref_image_client] mark_blacklisted: 잘못된 sha256 길이: %s", len(sha256_full or ""))
        return None

    url = f"{_base_url()}/internal/ref-images/blacklist"
    payload = {"sha256": sha256_full, "reason": reason or ""}
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT_S)
        if resp.status_code not in (200, 201):
            logger.warning(
                "[ref_image_client] mark_blacklisted %s status=%s body=%s",
                url, resp.status_code, resp.text[:200],
            )
            return None
        data = resp.json()
        return int(data.get("marked", 0))
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[ref_image_client] mark_blacklisted 실패: %s", e)
        return None


def is_blacklisted(sha256_full: str) -> bool:
    """sha256 (64자 hex) 이 관리자 블랙리스트에 있는지.

    활성화 off 또는 네트워크 실패 시 False (저장 허용 — 안전 default).
    """
    if not _enabled():
        return False
    if not sha256_full or len(sha256_full) != 64:
        logger.warning("[ref_image_client] 잘못된 sha256 길이: %s", len(sha256_full or ""))
        return False

    url = f"{_base_url()}/internal/ref-images/blacklist"
    try:
        resp = httpx.get(url, params={"sha256": sha256_full}, timeout=_TIMEOUT_S)
        if resp.status_code != 200:
            logger.warning("[ref_image_client] blacklist check %s status=%s", url, resp.status_code)
            return False
        data = resp.json()
        return bool(data.get("blacklisted", False))
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[ref_image_client] blacklist check 실패: %s", e)
        return False


# ── 등록 ─────────────────────────────────────────────────────

class CreateRefImagePayload(TypedDict, total=False):
    userProjectId: Optional[int]
    brandCategoryId: int
    imageSha256: str
    floorSizeTier: str   # "small" | "medium" | "large" | "outdoor"
    searchKeyword: Optional[str]
    sourceUrl: Optional[str]
    filePath: Optional[str]
    fileSizeBytes: Optional[int]
    refPath: Optional[str]


def register_ref_image(
    payload: CreateRefImagePayload,
    image_bytes: Optional[bytes] = None,
    image_filename: Optional[str] = None,
    image_content_type: str = "image/jpeg",
) -> Optional[dict]:
    """Java `POST /api/internal/ref-images` (multipart) — 등록 성공 시 JSON 반환, 실패 시 None.

    2026-04-29: multipart 확장 — image_bytes 있으면 S3 업로드 + s3Url 채움.
    image_bytes None 이면 backwards compat (S3 skip, JSON-only 메타 등록).

    활성화 off / 네트워크 실패 / 검증 실패 등 모두 None.
    배치 파이프라인은 어떤 경우에도 계속 진행.
    """
    if not _enabled():
        return None
    required = ("brandCategoryId", "imageSha256", "floorSizeTier")
    if any(not payload.get(k) for k in required):
        logger.warning("[ref_image_client] register payload 필수 필드 누락: %s", payload)
        return None

    url = f"{_base_url()}/internal/ref-images"
    # multipart: payload (JSON string) + image (binary, optional)
    import json as _json
    files: dict = {
        "payload": (None, _json.dumps(payload), "application/json"),
    }
    if image_bytes is not None:
        files["image"] = (
            image_filename or "image.jpg",
            image_bytes,
            image_content_type,
        )
    try:
        # multipart 업로드는 timeout 길게 (S3 업로드 포함)
        resp = httpx.post(url, files=files, timeout=10.0 if image_bytes else _TIMEOUT_S)
        if resp.status_code not in (200, 201):
            logger.warning(
                "[ref_image_client] register %s status=%s body=%s",
                url, resp.status_code, resp.text[:200],
            )
            return None
        return resp.json()
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[ref_image_client] register 실패: %s", e)
        return None


# ── 분석 결과 영속 (ref_image_analyses) ───────────────────────────────
# 2026-04-29 신설 — Vision 분석 결과를 Java 통해 ref_image_analyses 에 영구 저장.
# 재분석 회피 캐시 조회는 fetch_analysis_cache(refImageId, modelVersion).
# 활성화 조건은 등록과 동일 (REF_IMAGE_HANDOFF_ENABLED=1).

class CreateRefImageAnalysisPayload(TypedDict, total=False):
    refImageId: Optional[int]
    conceptArea: Optional[str]      # 영문 키 (welcome/photo/experience/screening/retail/checkout/hybrid/lounge)
    brandCategory: Optional[str]    # 보조 (뷰티/음식 등)
    visionAnalysisJson: str         # 8축 분석 결과 JSON (필수)
    modelVersion: Optional[str]


def register_ref_image_analysis(payload: CreateRefImageAnalysisPayload) -> Optional[dict]:
    """Java `POST /api/internal/ref-image-analyses` — 분석 결과 등록.

    활성화 off / 네트워크 실패 / 검증 실패 등 모두 None.
    배치 파이프라인 blocking 금지 — 저장 실패해도 분석 결과는 state 에 살아있음 (휘발 fallback).
    """
    if not _enabled():
        return None
    if not payload.get("visionAnalysisJson"):
        logger.warning("[ref_image_client] analysis payload visionAnalysisJson 누락")
        return None

    url = f"{_base_url()}/internal/ref-image-analyses"
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT_S)
        if resp.status_code not in (200, 201):
            logger.warning(
                "[ref_image_client] analysis register %s status=%s body=%s",
                url, resp.status_code, resp.text[:200],
            )
            return None
        return resp.json()
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[ref_image_client] analysis register 실패: %s", e)
        return None


def fetch_analysis_pool(
    concept_area: str,
    brand_category: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Java `GET /api/internal/ref-image-analyses/pool` — concept_area 별 분석 풀 fetch.

    N+1 흐름의 핵심: design LLM 컨텍스트로 활용할 누적된 분석 결과 가져오기.
    base64 이미지 X (분석 결과 JSON 만) → 토큰 절감.

    brand_category 지정 시 정밀 매칭 (B 옵션 — 두 차원 일치 우선). 없으면 concept_area 만.

    반환:
      - 활성화 + 매칭 N건: 분석본 dict list (id, refImageId, conceptArea, visionAnalysisJson, modelVersion 등)
      - 비활성 / 네트워크 실패: 빈 list (graceful — 신규 검색만으로 진행)
    """
    if not _enabled():
        return []
    if not concept_area:
        return []

    url = f"{_base_url()}/internal/ref-image-analyses/pool"
    params: dict = {"conceptArea": concept_area, "limit": limit}
    if brand_category:
        params["brandCategory"] = brand_category
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT_S)
        if resp.status_code != 200:
            logger.warning(
                "[ref_image_client] analysis pool %s status=%s",
                url, resp.status_code,
            )
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[ref_image_client] analysis pool 실패: %s", e)
        return []


def fetch_analysis_cache(ref_image_id: int, model_version: Optional[str] = None) -> Optional[dict]:
    """Java `GET /api/internal/ref-image-analyses/cache` — 캐시 hit 조회.

    model_version 지정 시 모델 버전까지 일치하는 분석본만 (mismatch → None).
    미지정 시 가장 최신 분석본 1건 (모델 무관).

    반환:
      - hit: 분석본 dict (id, refImageId, conceptArea, visionAnalysisJson, modelVersion, ...)
      - miss / 비활성 / 네트워크 실패: None (호출처에서 새로 분석)
    """
    if not _enabled():
        return None
    if not ref_image_id:
        return None

    url = f"{_base_url()}/internal/ref-image-analyses/cache"
    params = {"refImageId": ref_image_id}
    if model_version:
        params["modelVersion"] = model_version
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT_S)
        if resp.status_code == 200:
            data = resp.json()
            # null 응답은 cache miss
            return data if data else None
        logger.warning(
            "[ref_image_client] analysis cache %s status=%s",
            url, resp.status_code,
        )
        return None
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as e:
        logger.warning("[ref_image_client] analysis cache 실패: %s", e)
        return None
