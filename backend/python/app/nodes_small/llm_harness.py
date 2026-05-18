"""
LLM 호출 하네스 — Anthropic API 안전 통합 wrapper.

3 영역 통합 (제미나이 자문 2026-04-29 + 진규 OK):
  1. Validation: Pydantic BaseModel 로 응답 schema 강제
  2. Execution: tenacity 로 재시도 + Circuit Breaker (좌표 주입 감지)
  3. Test: fixture loader 로 실 API 우회

설계 원칙:
  - Single Source of Truth: 모든 LLM 호출이 이 모듈을 거침
  - 호출부 인터페이스 보존: 노드의 return value 형식 안 바꿈 (placement / verify / fallback 등 무영향)
  - Backward-compat: 기존 패턴 (parse_llm_json, _has_coordinate_injection 등) 흡수

사용 패턴:
  # 1. 노드별 응답 모델 정의 (Pydantic BaseModel 상속)
  class VisionAnalysisResult(LLMResponseModel):
      layout_patterns: list[str]
      ...

  # 2. call_llm_tool_use 호출 (tool_use 모드)
  result, meta = call_llm_tool_use(
      client, model="claude-sonnet-4-6", max_tokens=2048, temperature=0.3,
      system="...", messages=[...],
      tool_name="analyze_reference_images",
      tool_schema={...},
      response_model=VisionAnalysisResult,
  )

  # 3. call_llm_text 호출 (text + JSON 파싱 모드)
  result, meta = call_llm_text(
      client, model="...", max_tokens=...,
      system=..., messages=...,
      response_model=DesignIntentList,
      forbid_coordinate_injection=True,  # design 전용
  )
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Optional, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel, ConfigDict, ValidationError
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

logger = logging.getLogger(__name__)


# ── 예외 계층 ────────────────────────────────────────────────────────
class LLMHarnessError(Exception):
    """하네스 베이스 예외."""


class LLMResponseEmptyError(LLMHarnessError):
    """LLM 응답 비어있음."""


class LLMNoToolUseError(LLMHarnessError):
    """tool_use 모드인데 tool_use block 없이 text 만 반환됨."""


class LLMSchemaValidationError(LLMHarnessError):
    """Pydantic 검증 실패."""


class LLMCoordinateInjectionError(LLMHarnessError):
    """좌표 주입 감지 (LLM 이 mm 수치 자유 출력 — 시스템 룰 위반)."""


class LLMJSONParseError(LLMHarnessError):
    """text 응답의 JSON 파싱 실패."""


# 재시도 대상 예외 — 일시적 / LLM 응답 품질 문제
_RETRYABLE = (
    LLMResponseEmptyError,
    LLMNoToolUseError,
    LLMSchemaValidationError,
    LLMCoordinateInjectionError,
    LLMJSONParseError,
)


# ── 응답 모델 baseclass ─────────────────────────────────────────────
class LLMResponseModel(BaseModel):
    """노드별 LLM 응답 Pydantic 모델 baseclass.

    노드가 상속해서 자기 schema 정의:
      class DesignIntent(LLMResponseModel):
          object_type: str
          ref_point_id: str | None = None
          zone_label: str
          ...
    """
    # extra="forbid": 정의되지 않은 필드 거부 (LLM 환각 / 좌표 주입 기본 차단).
    # 각 노드가 필요 시 override 가능.
    model_config = ConfigDict(extra="forbid")


# ── 좌표 주입 감지 (design.py 의 _has_coordinate_injection 흡수) ───
# LLM 이 자유 텍스트에 좌표/mm 수치 출력하는 패턴 (시스템 설계 위반).
# placed_because 같은 자유 서술 필드의 사후 검증용.
_COORD_INJECTION_PATTERNS = (
    re.compile(r"\b\d{2,5}\s*mm\b", re.IGNORECASE),
    re.compile(r"\b(?:x|y|cx|cy|center_x|center_y)\s*[:=]\s*-?\d+", re.IGNORECASE),
    re.compile(r"\b(?:width|depth|height)_mm\s*[:=]", re.IGNORECASE),
)


def has_coordinate_injection(text: str) -> bool:
    """텍스트에 좌표/mm 수치 주입 흔적 있는지 검사."""
    if not text:
        return False
    return any(p.search(text) for p in _COORD_INJECTION_PATTERNS)


# ── tool_use 모드 ───────────────────────────────────────────────────
T = TypeVar("T", bound=BaseModel)


def call_llm_tool_use(
    client: Anthropic,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | list,
    messages: list,
    tool_name: str,
    tool_schema: dict,
    response_model: type[T],
    fixture: Optional[T] = None,
    track_usage_node: Optional[str] = None,
    max_attempts: int = 3,
) -> tuple[T, dict]:
    """tool_use 모드 LLM 호출 + Pydantic 검증 + 재시도.

    Anthropic tool_use 가 schema 강제하고, 추가로 Pydantic 으로 클라이언트 측 재검증.

    Args:
        client: Anthropic 인스턴스
        tool_name / tool_schema: tools=[{name, description, input_schema}] 의 한 항목
        response_model: tool_block.input 을 검증할 Pydantic 모델
        fixture: 테스트 환경에서 실 API 우회. None 아니면 fixture 그대로 반환.
        track_usage_node: token_tracker 에 기록할 노드 이름. None 이면 추적 스킵.
        max_attempts: 재시도 횟수 (기본 3)

    Returns: (validated_data, metadata).
        metadata = {
            "attempts": int,
            "input_tokens": int | None,
            "output_tokens": int | None,
            "mode": "tool_use",
        }

    Raises:
        LLMResponseEmptyError / LLMNoToolUseError / LLMSchemaValidationError 마지막 재시도 시 raise.
    """
    if fixture is not None:
        # 테스트 모드 — fixture 반환 + dummy meta
        if not isinstance(fixture, response_model):
            fixture = response_model.model_validate(fixture if isinstance(fixture, dict) else fixture.__dict__)
        return fixture, {"attempts": 0, "input_tokens": None, "output_tokens": None, "mode": "fixture"}

    last_response = None
    last_meta = {"attempts": 0, "input_tokens": None, "output_tokens": None, "mode": "tool_use"}

    for attempt in Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    ):
        with attempt:
            last_meta["attempts"] = attempt.retry_state.attempt_number
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                tools=[{
                    "name": tool_name,
                    "description": tool_schema.get("description", ""),
                    "input_schema": tool_schema.get("input_schema") or tool_schema,
                }],
                tool_choice={"type": "tool", "name": tool_name},
                messages=messages,
            )
            last_response = response
            last_meta["input_tokens"] = getattr(response.usage, "input_tokens", None)
            last_meta["output_tokens"] = getattr(response.usage, "output_tokens", None)

            if track_usage_node:
                _track_usage_safe(track_usage_node, response)

            if not response.content:
                raise LLMResponseEmptyError("response.content 비어있음")

            tool_block = next(
                (b for b in response.content if getattr(b, "type", None) == "tool_use"),
                None,
            )
            if tool_block is None:
                raise LLMNoToolUseError(f"tool_use block 없음 — text only: {str(response.content)[:200]}")

            try:
                validated = response_model.model_validate(dict(tool_block.input))
            except ValidationError as e:
                raise LLMSchemaValidationError(f"Pydantic 검증 실패: {e}") from e

            return validated, last_meta

    # Retrying(reraise=True) 라 여기 도달 X (마지막 attempt 의 예외가 직접 raise)
    # 방어선:
    raise LLMHarnessError("재시도 소진 — 도달 불가")


# ── text + JSON 모드 ────────────────────────────────────────────────
def call_llm_text_json(
    client: Anthropic,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | list,
    messages: list,
    response_model: type[T],
    forbid_coordinate_injection: bool = False,
    fixture: Optional[T] = None,
    track_usage_node: Optional[str] = None,
    max_attempts: int = 3,
) -> tuple[T, dict]:
    """text 응답 + JSON 파싱 + Pydantic 검증 모드.

    design.py 같이 tool_use 안 쓰고 LLM 이 JSON 자유 출력하는 케이스용.

    Args:
        forbid_coordinate_injection: True 면 응답 텍스트에 좌표/mm 수치 있으면 reject + 재시도.
                                      design.py 의 _has_coordinate_injection 같은 보호 활성화.
        나머지 args: call_llm_tool_use 와 동일.

    Returns: (validated_data, metadata).
    """
    if fixture is not None:
        if not isinstance(fixture, response_model):
            fixture = response_model.model_validate(fixture if isinstance(fixture, dict) else fixture.__dict__)
        return fixture, {"attempts": 0, "input_tokens": None, "output_tokens": None, "mode": "fixture"}

    last_meta = {"attempts": 0, "input_tokens": None, "output_tokens": None, "mode": "text_json"}

    for attempt in Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    ):
        with attempt:
            last_meta["attempts"] = attempt.retry_state.attempt_number
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            )
            last_meta["input_tokens"] = getattr(response.usage, "input_tokens", None)
            last_meta["output_tokens"] = getattr(response.usage, "output_tokens", None)

            if track_usage_node:
                _track_usage_safe(track_usage_node, response)

            if not response.content:
                raise LLMResponseEmptyError("response.content 비어있음")

            text = response.content[0].text if hasattr(response.content[0], "text") else ""
            if not text:
                raise LLMResponseEmptyError("response.content[0].text 비어있음")

            if forbid_coordinate_injection and has_coordinate_injection(text):
                raise LLMCoordinateInjectionError(
                    f"좌표/mm 주입 감지 — LLM 응답에 수치 자유 출력 (attempt {last_meta['attempts']})"
                )

            data = _parse_json_robust(text)
            if data is None:
                raise LLMJSONParseError(f"JSON 파싱 실패: {text[:200]}")

            try:
                validated = response_model.model_validate(data)
            except ValidationError as e:
                raise LLMSchemaValidationError(f"Pydantic 검증 실패: {e}") from e

            return validated, last_meta

    raise LLMHarnessError("재시도 소진 — 도달 불가")


# ── 내부 helper ─────────────────────────────────────────────────────
def _track_usage_safe(node: str, response) -> None:
    """token_tracker 호출 — 실패해도 LLM 호출 자체는 성공이므로 silent."""
    try:
        from app.token_tracker import track_usage
        track_usage(f"{node}.py", response)
    except Exception as e:
        logger.debug(f"[harness] token_tracker 실패 (무시): {e}")


_JSON_PATTERNS = (
    re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL),
    re.compile(r"```json\s*(\[.*?\])\s*```", re.DOTALL),
    re.compile(r"```\s*(\{.*?\})\s*```", re.DOTALL),
    re.compile(r"```\s*(\[.*?\])\s*```", re.DOTALL),
)


def _parse_json_robust(text: str) -> Any:
    """LLM 응답 텍스트에서 JSON 추출 + 파싱.

    1. ```json ... ``` 코드 블록 우선
    2. ``` ... ``` 일반 코드 블록
    3. 전체 text 를 직접 파싱
    """
    if not text:
        return None
    text = text.strip()

    # 코드 블록 추출
    for pattern in _JSON_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue

    # 직접 파싱
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 시작 { 또는 [ 위치부터 끝까지 직접 시도
    for start_char in ("{", "["):
        idx = text.find(start_char)
        if idx >= 0:
            try:
                return json.loads(text[idx:])
            except json.JSONDecodeError:
                continue

    return None


# ── fixture loader ──────────────────────────────────────────────────
def load_fixture(node: str, fixture_name: str = "default") -> Optional[dict]:
    """테스트용 fixture 로드.

    경로: tests/fixtures/llm_responses/{node}/{fixture_name}.json
    예: tests/fixtures/llm_responses/ref_image_analyzer/beauty_default.json

    Returns: dict 또는 None (파일 없음).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "tests", "fixtures", "llm_responses", node, f"{fixture_name}.json")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[harness] fixture 로드 실패 {path}: {e}")
        return None


__all__ = [
    "LLMHarnessError",
    "LLMResponseEmptyError",
    "LLMNoToolUseError",
    "LLMSchemaValidationError",
    "LLMCoordinateInjectionError",
    "LLMJSONParseError",
    "LLMResponseModel",
    "has_coordinate_injection",
    "call_llm_tool_use",
    "call_llm_text_json",
    "load_fixture",
]
