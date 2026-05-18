"""
LLM 응답 정책 — 위험 키 black list + 새 필드 동적 처리.

llm_harness.py 가 mechanism (call/retry/Pydantic 호출) 담당이라면, 본 모듈은 policy 담당.
유지관리 단일 파일: 새 위험 키 추가 / 정책 변경 시 본 파일만 수정.

설계 원칙:
  - extra="allow" 로 모르는 필드 보존 (LLM 의 정당한 확장 안 깨뜨림)
  - 위험 키 명시 거부 → ValidationError → 하네스 retry
  - 알려지지 않은 정당한 필드 → logger.warning + 보존. 운영자가 로그 보고 정식 schema 승격 결정.
"""
from __future__ import annotations

import logging

from pydantic import ConfigDict, model_validator

from app.nodes_small.llm_harness import LLMResponseModel

logger = logging.getLogger(__name__)


# ── 위험 키 black list ───────────────────────────────────────────────
# LLM 이 자유롭게 출력해선 안 되는 키. 좌표/mm 직접 값 주입 등 system 룰 위반.
# 추가 발견 시 본 set 에 한 곳 추가하면 모든 StrictLLMModel 상속 모델에 자동 적용.
BANNED_LLM_KEYS: frozenset[str] = frozenset({
    # 좌표 직접 주입
    "x_mm", "y_mm", "center_x", "center_y",
    "x_px", "y_px",
    # 치수 직접 주입 (LLM 이 결정해선 안 됨 — VMD_BOUNDARIES 만 결정)
    "width_mm", "depth_mm", "height_mm",
    # 회전/방향 직접 주입
    "rotation_deg",
    "front_vec",
    # bbox 직접 출력
    "bbox_polygon", "bbox_bounds",
})


# ── Strict baseclass ────────────────────────────────────────────────
class StrictLLMModel(LLMResponseModel):
    """LLMResponseModel 확장 — extra=allow + 위험 키 자동 거부 + 새 필드 로깅.

    LLMResponseModel 의 default extra="forbid" 가 정당한 LLM 확장도 차단하는 trade-off
    (예: LLM 이 더 잘하려고 confidence 같은 새 필드 추가 시 retry 폭주 → fallback).
    StrictLLMModel 은 다음을 제공:

      1. extra="allow" — 정의되지 않은 필드를 model_extra 에 보존
      2. _BANNED_KEYS 검사 — 위험 키 (좌표/mm 직접 주입) 면 ValidationError → retry
      3. logger.warning — 알려지지 않은 정당한 필드 발견 시 알림 (운영 모니터링)

    사용:
        class DesignIntent(StrictLLMModel):
            object_type: str
            ...  # 알려진 필드들

    효과:
      - LLM 이 confidence 같은 새 필드 추가 → model_extra 보존 + WARN. 정상 처리.
      - LLM 이 x_mm 같은 좌표 키 추가 → ValidationError → 하네스 retry → fallback.
      - 운영자가 WARN 로그 보고 정당한 필드면 schema 정식 추가, 위험하면 BANNED 에 추가.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _validate_extras(self):
        extras = self.model_extra or {}
        if not extras:
            return self

        # 1. 위험 키 거부
        violations = set(extras) & BANNED_LLM_KEYS
        if violations:
            raise ValueError(f"위험 키 금지 (system 룰 위반): {sorted(violations)}")

        # 2. 알려지지 않은 정당한 필드 로깅
        logger.warning(
            f"[llm_policy] {type(self).__name__}: 새 필드 감지 {sorted(extras.keys())} — "
            f"정당한 확장이면 schema 정식 추가, 위험하면 BANNED_LLM_KEYS 에 추가."
        )
        return self


__all__ = [
    "BANNED_LLM_KEYS",
    "StrictLLMModel",
]
