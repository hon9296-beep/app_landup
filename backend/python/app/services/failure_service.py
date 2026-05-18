"""
배치 실패 메시지 가공 서비스.

기술적 reason 문자열을 번역하고, 사용자 요구사항과 매핑해
프론트가 그대로 보여줄 수 있는 메시지 리스트로 만든다.
"""
import logging

from app.failure_messages import FAILURE_REASON_EXPLAINS, OBJECT_KO

logger = logging.getLogger(__name__)


def translate_failure_reason(reason: str) -> str:
    """기술적 실패 사유 문자열 → 한국어 설명."""
    for keyword, explanation in FAILURE_REASON_EXPLAINS:
        if keyword in reason:
            return explanation
    return f"배치 실패 — {reason}"


def collect_requirement_failures(state: dict) -> list[dict]:
    """사용자 요구사항 중 배치 실패한 항목을 사람이 읽을 수 있는 형태로 정리."""
    failed = state.get("failed_objects") or []
    original_intents = state.get("_original_resolved_intents") or []
    if not failed or not original_intents:
        return []

    # 사용자가 요청한 타입 → 원문 매핑
    requested: dict[str, str] = {}
    for ri in original_intents:
        obj_type = ri.get("object_type")
        if obj_type and obj_type != "*":
            requested[obj_type] = ri.get("original_text", "")

    messages = []
    for f in failed:
        obj_type = f.get("object_type", "")
        if obj_type not in requested:
            continue
        name = OBJECT_KO.get(obj_type, obj_type)
        original_text = requested[obj_type]
        explanation = translate_failure_reason(f.get("reason", ""))
        entry = {
            "object_type": obj_type,
            "name": name,
            "user_message": f'"{original_text}" 요청이 실패했습니다: {explanation}',
            "technical_reason": f.get("reason", ""),
        }
        messages.append(entry)
        logger.info(f"[req_failure] {name}: {explanation}")

    return messages
