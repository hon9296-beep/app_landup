"""
design_intents anti-pattern reviewer 노드 (#474 도박수, Phase 1 small 단독).

흐름:
  sm_design (LLM, intents 결정) → sm_design_reviewer (본 노드)
    → conditional edge (graph.py):
        - reviewer_status=pass → sm_partition_placement (다음)
        - reject + iteration < MAX → sm_design (재호출, prompt 에 reviewer_feedback inject)
        - iteration ≥ MAX 또는 유사도 ≥ THRESHOLD → sm_partition_placement (한도 / 수렴, warning)
        - kill switch (ANTI_PATTERN_REVIEWER_ENABLED=false) → sm_partition_placement

검증 = 하이브리드:
  python validator (anti_patterns.py:run_validators) — 좌표 비교 / 거리 측정 / 면적
  + LLM 검토 (zone/동선 정책 등 모호한 anti-pattern, large layout_validator 패턴 일관)

graceful fallback:
  - API key 없음 / LLM 호출 실패 → LLM 검토 skip + python 결과만 사용
  - 모든 validator exception → reviewer_status="skipped" (design 결과 그대로 통과)

설계 문서:
  - reports/AD/2026-05-04_15-21_474_anti_pattern_reviewer_USER.md
  - reports/AD/2026-05-04_15-21_474_anti_pattern_reviewer_WORKLOG.md
"""
import logging
import os
from typing import Optional

from anthropic import Anthropic
from pydantic import Field

from app.nodes_small.llm_policy import StrictLLMModel
from app.state import SmallState
from app.nodes_small.anti_patterns import (
    run_validators,
    get_llm_anti_patterns,
    compute_intent_similarity,
    build_designer_feedback,
)
from app.nodes_small.prompts.design_reviewer import (
    build_llm_tool_schema,
    LLM_REVIEWER_SYSTEM,
    build_llm_user_prompt,
)

logger = logging.getLogger(__name__)


# ── Feature flag ─────────────────────────────────────────────────────
def _flag_enabled() -> bool:
    """ANTI_PATTERN_REVIEWER_ENABLED 환경변수 — default True (활성)."""
    val = os.environ.get("ANTI_PATTERN_REVIEWER_ENABLED", "true").lower()
    return val in ("true", "1", "yes", "on")


# ── 종료 조건 상수 ───────────────────────────────────────────────────
# MAX_REVIEW_ITERATIONS 변천:
#   - 1-3 #533 B4: 1 → 2 (1회 retry 허용. 재기획 권한 부여)
#   - 1-3 후속 (#535 후속, 5-7 라이브 분석 D): 2 → 1 (retry 무용 + 시간 단축)
# 변경 사유 (5-7 21:36 라이브 측정):
#   - retry 3회 (iter 0/1/2) 발생 — 매번 같은 회귀 (counter wall 분산 / photo_wall drop)
#   - LLM compliance 한계: reviewer reject 받아도 자기 패턴 반복. retry = 사실상 무용
#   - 시간 측정: retry 1회당 ~20~25s. 3회면 ~60~75s 추가. 총 라이브 시간 ~50% 가 retry
#   - prompt 강화 (B-1/B-3/A1~A4) + pair_rules 강제 (B) + placement priority 로
#     첫 시도 quality 보장 → retry 없이 결정적 fix 가 본질. retry 는 보험 X 손해.
# 변경 시 placement_reviewer (MAX_PLACEMENT_REVIEW_ITERATIONS) 와 일관성 유지.
MAX_REVIEW_ITERATIONS = 1
# SIMILARITY_THRESHOLD: 직전 intents 와 유사도 ≥ 0.95 면 수렴 검출 — 무한 retry 방지.
# LLM 이 같은 결정만 반복하면 추가 retry 무용 → partition_placement 진행.
SIMILARITY_THRESHOLD = 0.95


# ── LLM 응답 Pydantic 모델 (StrictLLMModel — BANNED_LLM_KEYS 자동 거부) ──
class LLMReviewerResult(StrictLLMModel):
    overall_status: str = "pass"  # pass | reject
    violations: list = Field(default_factory=list)  # [{rule_id, severity, detail}]
    feedback: str = ""


def _call_llm_reviewer(intents: list, state: dict) -> Optional[dict]:
    """LLM 검토 호출 — graceful fallback (API key 없음 / 호출 실패 시 None)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[reviewer] API key 없음 — LLM 검토 skip")
        return None

    llm_rules = get_llm_anti_patterns()
    if not llm_rules:
        return None  # LLM 영역 룰 0 → 호출 불필요

    tool = build_llm_tool_schema()
    prompt = build_llm_user_prompt(intents, state, llm_rules)

    try:
        from app.llm_config import get_llm_config
        _cfg = get_llm_config("small.design_reviewer")
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            system=LLM_REVIEWER_SYSTEM,
            tools=[tool],
            tool_choice={"type": "tool", "name": "review_design_intents"},
            messages=[{"role": "user", "content": prompt}],
        )
        # token tracker (있으면)
        try:
            from app.token_tracker import track_usage
            track_usage("small.design_reviewer", response)
        except ImportError:
            pass

        # Tool use 응답 파싱 — block 중 type=="tool_use" 의 input 사용
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                raw = dict(block.input or {})
                # StrictLLMModel 검증 (BANNED_LLM_KEYS 자동 거부)
                validated = LLMReviewerResult.model_validate(raw)
                return validated.model_dump()

        logger.warning("[reviewer] LLM 응답에 tool_use block 없음")
        return None

    except Exception as e:
        logger.warning(f"[reviewer] LLM 호출 실패 — graceful skip: {e}")
        return None


def _merge_violations(python_violations: list[dict], llm_result: Optional[dict]) -> tuple[list[dict], str]:
    """python validator + LLM 결과 병합 → (전체 violations, feedback)."""
    all_violations = list(python_violations)
    llm_feedback = ""
    if llm_result:
        llm_violations = llm_result.get("violations") or []
        for v in llm_violations:
            # LLM 결과 dict 정규화 (python validator 와 동일 schema)
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
    """designer 재호출용 통합 피드백 — python blocking + LLM feedback."""
    parts = []
    if blocking:
        parts.append(build_designer_feedback(blocking))
    if llm_feedback:
        parts.append("## LLM 검토 피드백\n" + llm_feedback)
    return "\n\n".join(parts)


def run(state: SmallState) -> dict:
    """anti-pattern reviewer LangGraph 노드.

    Returns dict — state 에 박힐 키:
      - reviewer_status: "pass" | "reject" | "skipped"
      - reviewer_violations: list[dict]
      - reviewer_feedback: str (designer retry prompt inject 용)
      - _reviewer_feedback: str (state 에 저장 — design 재호출 시 inject)
      - _review_similarity_converged: bool
    """
    # kill switch — feature flag
    if not _flag_enabled():
        logger.info("[reviewer] ANTI_PATTERN_REVIEWER_ENABLED=false — skip")
        # 1-2 (#520 후속): sub_graph_reasons dump
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        dump_agent_reason(state, node="design_reviewer", decision="skipped",
                          reason="KILL_SWITCH_DISABLED",
                          context={"flag": "ANTI_PATTERN_REVIEWER_ENABLED=false"})
        return {
            "reviewer_status": "skipped",
            "reviewer_violations": [],
            "reviewer_feedback": "",
            "_reviewer_feedback": "",
            "_review_similarity_converged": False,
        }

    intents = state.get("design_intents") or []
    prev_intents = state.get("prev_design_intents")
    iteration = state.get("_review_iteration", 0)

    # 유사도 검증 (수렴 검출 — iteration > 0 일 때만)
    similarity_converged = False
    similarity = 0.0
    if iteration > 0 and prev_intents:
        similarity = compute_intent_similarity(prev_intents, intents)
        if similarity >= SIMILARITY_THRESHOLD:
            similarity_converged = True

    # 1. python validator 실행 (graceful — anti_patterns.run_validators 가 exception 처리)
    try:
        python_violations = run_validators(intents, state)
    except Exception as e:
        logger.warning(f"[reviewer] python validator 전체 실패 — skip: {e}")
        python_violations = []

    # 2. LLM 검토 (graceful — None 가능)
    llm_result = _call_llm_reviewer(intents, state)

    # 3. 병합
    all_violations, llm_feedback = _merge_violations(python_violations, llm_result)

    # 4. 판정
    blocking = [v for v in all_violations if v["severity"] == "blocking"]
    warnings = [v for v in all_violations if v["severity"] == "warning"]
    status = "reject" if blocking else "pass"

    # warning 로깅
    for w in warnings:
        logger.warning(f"[reviewer] {w['rule_id']} (warning): {w['violation_detail']}")

    # 5. designer 재호출 피드백 (blocking 만)
    feedback = _build_combined_feedback(blocking, llm_feedback) if blocking else ""

    # 6. dump_category_trace
    try:
        from app.categories import dump_category_trace
        dump_category_trace(
            stage="design.reviewer_iteration",
            raw_brand_category=(state.get("brand_data") or {}).get("brand", {}).get("brand_category"),
            iteration=iteration,
            reviewer_status=status,
            violation_count=len(all_violations),
            blocking_count=len(blocking),
            warning_count=len(warnings),
            violations=[{"rule_id": v["rule_id"], "severity": v["severity"]} for v in all_violations],
            similarity_with_prev=similarity if iteration > 0 else None,
            similarity_converged=similarity_converged,
            llm_called=llm_result is not None,
        )
    except Exception as e:
        logger.warning(f"[reviewer] dump_category_trace 실패 — skip: {e}")

    sim_str = f"{similarity:.2f}" if iteration > 0 else "N/A"
    logger.info(
        f"[reviewer] iter={iteration} status={status} "
        f"violations={len(all_violations)} (blocking={len(blocking)}, warning={len(warnings)}) "
        f"similarity={sim_str} converged={similarity_converged}"
    )

    # 1-2 (#520 후속): sub_graph_reasons dump — pass / reject 사유 + 위반 룰 list 기록
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        violation_summary = [
            {"rule_id": v.get("rule_id"), "severity": v.get("severity"),
             "obj": v.get("intent_object_type"), "detail": v.get("violation_detail", "")[:200]}
            for v in all_violations
        ]
        dump_agent_reason(state, node="design_reviewer", decision=status,
                          reason=f"violations={len(all_violations)} blocking={len(blocking)} warning={len(warnings)}",
                          context={
                              "iteration": iteration,
                              "similarity": similarity if iteration > 0 else None,
                              "similarity_converged": similarity_converged,
                              "llm_called": llm_result is not None,
                              "violations": violation_summary,
                              "feedback_excerpt": feedback[:500] if feedback else "",
                          })
    except Exception as e:
        logger.warning(f"[reviewer] reason_dump 실패 — skip: {e}")

    return {
        "reviewer_status": status,
        "reviewer_violations": all_violations,
        "reviewer_feedback": feedback,
        "_reviewer_feedback": feedback,
        "_review_similarity_converged": similarity_converged,
    }
