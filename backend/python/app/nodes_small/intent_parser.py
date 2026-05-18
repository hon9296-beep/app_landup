"""
intent_parser 노드 — 소·중형 파이프라인 (Rendy).

object_selection 이후, design 이전에 실행.
user_requirements(자연어) → resolved_intents(구조화된 배치 의도) 변환.
요구사항이 없으면 no-op으로 동작.
"""
import dataclasses
import logging

from app.state import SmallState
from app.core.intent_parser import IntentParseError, parse_intents

logger = logging.getLogger(__name__)


def run(state: SmallState) -> SmallState:
    """자연어 요구사항을 구조화된 인텐트로 변환."""
    user_requirements = state.get("user_requirements") or ""
    if not user_requirements.strip():
        logger.info("[intent_parser:small] user_requirements 없음 — 건너뜀")
        return {"resolved_intents": []}

    reference_points = state.get("reference_points") or []
    locked_objects = state.get("locked_objects") or []

    try:
        intents = parse_intents(
            user_requirements=user_requirements,
            reference_points=reference_points,
            locked_objects=locked_objects,
        )
    except IntentParseError as e:
        logger.error(f"[intent_parser:small] LLM 호출 실패 — 기존 배치 유지: {e}")
        return {"resolved_intents": [], "intent_parse_error": str(e)}

    serialized = [dataclasses.asdict(i) for i in intents]
    logger.info(f"[intent_parser:small] {len(serialized)}개 인텐트 → state['resolved_intents']")
    return {"resolved_intents": serialized}
