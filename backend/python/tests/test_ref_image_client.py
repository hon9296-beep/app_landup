"""
Java /api/internal/ref-images 클라이언트 검증 (feature/ref-image-python-handoff).

검증 범위:
  - 활성화 off 시 모든 호출 no-op
  - blacklist 체크: 200 응답 파싱 / 에러 상황 안전 default
  - register: 필수 필드 검증 / 성공 반환 / 실패 None 반환
  - 파이프라인 blocking 금지 (네트워크 / timeout 모두 swallow)

HTTP 모킹: unittest.mock (respx 의존성 추가 없이 httpx.get/post 직접 patch).
"""
import os
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.clients.ref_image_client import is_blacklisted, register_ref_image


VALID_SHA = "a" * 64


# ── 활성화 flag off ─────────────────────────────────────────

def test_is_blacklisted_disabled_returns_false_without_http():
    """REF_IMAGE_HANDOFF_ENABLED 미설정 시 HTTP 호출 없이 False 반환."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("REF_IMAGE_HANDOFF_ENABLED", None)
        with patch("httpx.get") as mock_get:
            assert is_blacklisted(VALID_SHA) is False
            mock_get.assert_not_called()


def test_register_disabled_returns_none_without_http():
    os.environ.pop("REF_IMAGE_HANDOFF_ENABLED", None)
    with patch("httpx.post") as mock_post:
        result = register_ref_image({
            "brandCategoryId": 1,
            "imageSha256": VALID_SHA,
            "floorSizeTier": "small",
        })
        assert result is None
        mock_post.assert_not_called()


# ── 활성화 후 blacklist 체크 ─────────────────────────────────

def _env_enabled():
    return patch.dict(os.environ, {"REF_IMAGE_HANDOFF_ENABLED": "1"})


def _mock_response(status_code: int, json_body: dict = None, text: str = ""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


def test_is_blacklisted_returns_true_on_positive_response():
    with _env_enabled(), patch("httpx.get",
                              return_value=_mock_response(200, {"blacklisted": True})) as mock_get:
        assert is_blacklisted(VALID_SHA) is True
        # URL + sha256 파라미터로 호출됐는지
        args, kwargs = mock_get.call_args
        assert "/internal/ref-images/blacklist" in args[0]
        assert kwargs["params"]["sha256"] == VALID_SHA


def test_is_blacklisted_returns_false_on_negative_response():
    with _env_enabled(), patch("httpx.get",
                              return_value=_mock_response(200, {"blacklisted": False})):
        assert is_blacklisted(VALID_SHA) is False


def test_is_blacklisted_invalid_sha_length_returns_false():
    """64자 아닌 sha 전달 시 HTTP 호출 없이 False."""
    with _env_enabled(), patch("httpx.get") as mock_get:
        assert is_blacklisted("abc") is False
        mock_get.assert_not_called()


def test_is_blacklisted_5xx_returns_false_and_does_not_raise():
    with _env_enabled(), patch("httpx.get", return_value=_mock_response(500)):
        assert is_blacklisted(VALID_SHA) is False


def test_is_blacklisted_network_error_returns_false():
    with _env_enabled(), patch("httpx.get", side_effect=httpx.RequestError("connection refused")):
        assert is_blacklisted(VALID_SHA) is False


def test_is_blacklisted_timeout_returns_false():
    with _env_enabled(), patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
        assert is_blacklisted(VALID_SHA) is False


# ── 활성화 후 register ───────────────────────────────────────

def test_register_success_returns_json_body():
    response_body = {"id": 42, "imageSha256": VALID_SHA}
    with _env_enabled(), patch("httpx.post",
                              return_value=_mock_response(201, response_body)):
        result = register_ref_image({
            "userProjectId": 1,
            "brandCategoryId": 2,
            "imageSha256": VALID_SHA,
            "floorSizeTier": "small",
            "filePath": "test/path.jpg",
        })
        assert result == response_body


def test_register_posts_json_payload():
    with _env_enabled(), patch("httpx.post",
                              return_value=_mock_response(200, {"id": 1})) as mock_post:
        payload = {
            "userProjectId": 10,
            "brandCategoryId": 2,
            "imageSha256": VALID_SHA,
            "floorSizeTier": "medium",
            "filePath": "test.jpg",
            "fileSizeBytes": 100,
        }
        register_ref_image(payload)

        args, kwargs = mock_post.call_args
        assert "/internal/ref-images" in args[0]
        assert kwargs["json"] == payload


def test_register_missing_required_field_returns_none():
    """brandCategoryId / imageSha256 / floorSizeTier 중 하나라도 빈 값이면 None."""
    cases = [
        {"imageSha256": VALID_SHA, "floorSizeTier": "small"},             # brandCategoryId 누락
        {"brandCategoryId": 1, "floorSizeTier": "small"},                  # imageSha256 누락
        {"brandCategoryId": 1, "imageSha256": VALID_SHA},                  # floorSizeTier 누락
        {"brandCategoryId": 0, "imageSha256": VALID_SHA, "floorSizeTier": "small"},  # 0도 falsy
        {"brandCategoryId": 1, "imageSha256": "", "floorSizeTier": "small"},          # 빈 문자열
    ]
    with _env_enabled(), patch("httpx.post") as mock_post:
        for case in cases:
            assert register_ref_image(case) is None
        mock_post.assert_not_called()


def test_register_4xx_returns_none():
    with _env_enabled(), patch("httpx.post",
                              return_value=_mock_response(400, text="Bad Request")):
        assert register_ref_image({
            "brandCategoryId": 1,
            "imageSha256": VALID_SHA,
            "floorSizeTier": "small",
        }) is None


def test_register_network_error_returns_none():
    with _env_enabled(), patch("httpx.post", side_effect=httpx.RequestError("down")):
        assert register_ref_image({
            "brandCategoryId": 1,
            "imageSha256": VALID_SHA,
            "floorSizeTier": "small",
        }) is None


# ── 환경변수 JAVA_API_BASE override ──────────────────────────

def test_java_api_base_custom_url():
    with patch.dict(os.environ, {
        "REF_IMAGE_HANDOFF_ENABLED": "1",
        "JAVA_API_BASE": "http://custom-host:9000/api",
    }), patch("httpx.get",
              return_value=_mock_response(200, {"blacklisted": False})) as mock_get:
        is_blacklisted(VALID_SHA)
        args, _ = mock_get.call_args
        assert args[0].startswith("http://custom-host:9000/api/internal/ref-images/blacklist")
