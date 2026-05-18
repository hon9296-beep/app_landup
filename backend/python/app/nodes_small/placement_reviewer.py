"""
placement 후 anti-pattern reviewer 노드 (#490).

design_reviewer (#474) 가 design_intents 단계 (좌표 결정 전) 만 검증하는 한계 보완.
placement 후 placed_objects + failed_objects + 좌표 기반 검증 → drop / slot 경쟁 검출.

흐름 (place_service.place_small() 직접 호출):
  placement.run() → verify.run() → fallback 루프
    → placement_reviewer.run() (본 노드)
        - status=pass → sub_path / report_gen 진행
        - status=reject + iter < MAX → design.run() 부터 재시도 (slot 양보 hint inject)
        - status=reject + iter >= MAX → 다음 단계 진행 (warning)
        - kill switch (PLACEMENT_REVIEWER_ENABLED=false) → skip

검증 = 하이브리드 (#474 와 동일 패턴):
  python validator (anti_patterns.run_placement_validators)
    + LLM 검토 (통합 layout sanity)

graceful fallback:
  - API key 없음 / LLM 호출 실패 → LLM skip + python 결과만
  - validator exception → reviewer_status="skipped"

설계 문서:
  - reports/AD/2026-05-05_14-47_small_finalization_plan.md §3
"""
import logging
import os
from typing import Optional

from anthropic import Anthropic
from pydantic import Field

from app.nodes_small.llm_policy import StrictLLMModel
from app.state import SmallState
from app.nodes_small.anti_patterns import (
    run_placement_validators,
    get_placement_llm_anti_patterns,
    build_placement_designer_feedback,
)
from app.nodes_small.prompts.placement_reviewer import (
    build_llm_tool_schema,
    LLM_REVIEWER_SYSTEM,
    build_llm_user_prompt,
)

logger = logging.getLogger(__name__)


# ── Feature flag ─────────────────────────────────────────────────────
def _flag_enabled() -> bool:
    """PLACEMENT_REVIEWER_ENABLED 환경변수 — default True (활성)."""
    val = os.environ.get("PLACEMENT_REVIEWER_ENABLED", "true").lower()
    return val in ("true", "1", "yes", "on")


# ── 종료 조건 상수 ───────────────────────────────────────────────────
# MAX_PLACEMENT_REVIEW_ITERATIONS 변천:
#   - 1-3 (#523 후속): 1 → 2 (routes 의 `iter_count >= MAX` 비교 + iter+1 박는 패턴 fix)
#   - 1-3 #533 B4: 2 유지 (design_reviewer 와 일관)
#   - 1-3 후속 (#535 후속, 5-7 라이브 분석 D): 2 → 1 (retry 무용 + 시간 단축)
# 변경 사유 (5-7 21:36 라이브 측정):
#   - placement_reviewer reject 후 design 재호출 → 같은 회귀 (counter wall 분산 / photo_wall drop) 반복
#   - LLM compliance 한계: reviewer 가 정확히 잡았지만 LLM 이 따르지 못함
#   - 시간 측정: retry 1회당 ~20~25s 추가. 결정적 fix 는 placement priority + pair_rules + prompt
#   - design_reviewer 와 일관성 유지 (MAX=1 양쪽 동시 변경 — B4 정책 준수)
MAX_PLACEMENT_REVIEW_ITERATIONS = 1


# ── LLM 응답 Pydantic 모델 ────────────────────────────────────────────
class LLMReviewerResult(StrictLLMModel):
    overall_status: str = "pass"
    violations: list = Field(default_factory=list)
    feedback: str = ""


def _call_llm_reviewer(state: dict) -> Optional[dict]:
    """LLM 검토 호출 — graceful fallback (API key 없음 / 호출 실패 시 None)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[placement_reviewer] API key 없음 — LLM 검토 skip")
        return None

    llm_rules = get_placement_llm_anti_patterns()
    if not llm_rules:
        return None

    tool = build_llm_tool_schema()
    prompt = build_llm_user_prompt(state, llm_rules)

    try:
        from app.llm_config import get_llm_config
        # design_reviewer 와 같은 키 사용 — 모델/파라미터 재활용 (별도 키 필요 시 후속)
        _cfg = get_llm_config("small.design_reviewer")
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            system=LLM_REVIEWER_SYSTEM,
            tools=[tool],
            tool_choice={"type": "tool", "name": "review_placement_result"},
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from app.token_tracker import track_usage
            track_usage("small.placement_reviewer", response)
        except ImportError:
            pass

        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                raw = dict(block.input or {})
                validated = LLMReviewerResult.model_validate(raw)
                return validated.model_dump()

        logger.warning("[placement_reviewer] LLM 응답에 tool_use block 없음")
        return None

    except Exception as e:
        logger.warning(f"[placement_reviewer] LLM 호출 실패 — graceful skip: {e}")
        return None


def _merge_violations(python_violations: list[dict], llm_result: Optional[dict]) -> tuple[list[dict], str]:
    """python validator + LLM 결과 병합."""
    all_violations = list(python_violations)
    llm_feedback = ""
    if llm_result:
        for v in llm_result.get("violations") or []:
            all_violations.append({
                "rule_id": v.get("rule_id", "AP-LLM"),
                "severity": v.get("severity", "warning"),
                "intent_object_type": "?",
                "intent_zone": "?",
                "intent_ref_point_id": "?",
                "violation_detail": v.get("detail", ""),
            })
        llm_feedback = llm_result.get("feedback", "")
    return all_violations, llm_feedback


def _build_combined_feedback(blocking: list[dict], llm_feedback: str) -> str:
    """design 재호출용 통합 피드백 — python blocking + LLM hint."""
    parts = []
    if blocking:
        parts.append(build_placement_designer_feedback(blocking))
    if llm_feedback:
        parts.append("## LLM 통합 sanity 피드백\n" + llm_feedback)
    return "\n\n".join(parts)


def run(state: SmallState) -> dict:
    """placement reviewer 노드.

    Returns dict — state 에 박힐 키:
      - placement_reviewer_status: "pass" | "reject" | "skipped"
      - placement_reviewer_violations: list[dict]
      - placement_reviewer_feedback: str (design retry prompt inject 용)
      - _placement_reviewer_feedback: str (state 에 저장 — design 재호출 시 inject)
    """
    # kill switch
    if not _flag_enabled():
        logger.info("[placement_reviewer] PLACEMENT_REVIEWER_ENABLED=false — skip")
        # 1-2 (#520 후속): sub_graph_reasons dump
        try:
            from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
            dump_agent_reason(state, node="placement_reviewer", decision="skipped",
                              reason="KILL_SWITCH_DISABLED",
                              context={"flag": "PLACEMENT_REVIEWER_ENABLED=false"})
        except Exception:
            pass
        return {
            "placement_reviewer_status": "skipped",
            "placement_reviewer_violations": [],
            "placement_reviewer_feedback": "",
            "_placement_reviewer_feedback": "",
        }

    iteration = state.get("_placement_review_iteration", 0)

    # 1. python validator
    try:
        python_violations = run_placement_validators(state)
    except Exception as e:
        logger.warning(f"[placement_reviewer] python validator 전체 실패 — skip: {e}")
        python_violations = []

    # 2. LLM 검토
    llm_result = _call_llm_reviewer(state)

    # 3. 병합
    all_violations, llm_feedback = _merge_violations(python_violations, llm_result)

    # 4. 판정
    blocking = [v for v in all_violations if v["severity"] == "blocking"]
    warnings = [v for v in all_violations if v["severity"] == "warning"]
    status = "reject" if blocking else "pass"

    for w in warnings:
        logger.warning(f"[placement_reviewer] {w['rule_id']} (warning): {w['violation_detail']}")

    # 5. design 재호출용 피드백 (blocking 만)
    feedback = _build_combined_feedback(blocking, llm_feedback) if blocking else ""

    # 6. dump_category_trace
    try:
        from app.categories import dump_category_trace
        dump_category_trace(
            stage="placement.reviewer_iteration",
            raw_brand_category=(state.get("brand_data") or {}).get("brand", {}).get("brand_category"),
            iteration=iteration,
            placement_reviewer_status=status,
            violation_count=len(all_violations),
            blocking_count=len(blocking),
            warning_count=len(warnings),
            violations=[{"rule_id": v["rule_id"], "severity": v["severity"]} for v in all_violations],
            llm_called=llm_result is not None,
            placed_count=len(state.get("placed_objects") or []),
            failed_count=len(state.get("failed_objects") or []),
        )
    except Exception as e:
        logger.warning(f"[placement_reviewer] dump_category_trace 실패 — skip: {e}")

    logger.info(
        f"[placement_reviewer] iter={iteration} status={status} "
        f"violations={len(all_violations)} (blocking={len(blocking)}, warning={len(warnings)}) "
        f"placed={len(state.get('placed_objects') or [])} failed={len(state.get('failed_objects') or [])}"
    )

    # 1-2 (#520 후속): sub_graph_reasons dump
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        violation_summary = [
            {"rule_id": v.get("rule_id"), "severity": v.get("severity"),
             "obj": v.get("intent_object_type"), "detail": v.get("violation_detail", "")[:200]}
            for v in all_violations
        ]
        dump_agent_reason(state, node="placement_reviewer", decision=status,
                          reason=f"violations={len(all_violations)} blocking={len(blocking)} warning={len(warnings)}",
                          context={
                              "iteration": iteration,
                              "llm_called": llm_result is not None,
                              "placed_count": len(state.get("placed_objects") or []),
                              "failed_count": len(state.get("failed_objects") or []),
                              "violations": violation_summary,
                              "feedback_excerpt": feedback[:500] if feedback else "",
                          })
    except Exception as e:
        logger.warning(f"[placement_reviewer] reason_dump 실패 — skip: {e}")

    return {
        "placement_reviewer_status": status,
        "placement_reviewer_violations": all_violations,
        "placement_reviewer_feedback": feedback,
        "_placement_reviewer_feedback": feedback,
        "_placement_review_iteration": iteration + 1,
    }
