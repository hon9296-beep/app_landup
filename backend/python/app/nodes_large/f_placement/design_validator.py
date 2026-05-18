"""design 검증 노드 (lg_design_validator) — 2026-05-06 신설.

design (1차 LLM, 영역별 가구 의도) + placement (코드, 실제 좌표) 결과 둘 다 받아
prompt 의 #강제 / #금지 룰 위반 검증. concept_area 의 layout_validator 패턴 동일.

흐름 (graph.py):
    lg_design (Sonnet) → lg_placement (코드) → lg_design_validator (Haiku, 룰 검증)
       → conditional:
          ├─ ok → 다음 노드
          ├─ fix_needed + retry < 2 → lg_design_fix (Sonnet) → lg_placement 재호출 → 다시 lg_design_validator
          └─ retry >= 2 → 다음 노드 (포기)

검증 룰 = DESIGN_VALIDATION_RULES (prompts/design_validator.py 정의).
- ref_citation / object_diversity / wall_balance / area_object_match / entrance_appropriate / placement_success / same_object_adjacent

state["design_check"] 박음.
"""
import logging
import os

from anthropic import Anthropic

from app.state import LargeState
from app.nodes_large.f_placement.prompts.design_validator import (
    DESIGN_VALIDATOR_SYSTEM,
    DESIGN_VALIDATOR_PROMPT_TEMPLATE,
    DESIGN_VALIDATION_RULES,
    build_validation_questions_text,
    build_tool_schema,
)

logger = logging.getLogger(__name__)


def run(state: LargeState) -> dict:
    """design intent + placement 결과 검증 → state["design_check"] 박음."""
    design_intents = state.get("design_intents") or []
    placed_objects = state.get("placed_objects") or []
    failed_objects = state.get("failed_objects") or []
    usable_poly = state.get("usable_poly")
    entrance_mm = state.get("entrance_mm")

    if not design_intents or not usable_poly:
        logger.info("[lg_design_validator] 입력 부족 — skip")
        return {"design_check": {}}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[lg_design_validator] API 키 없음 — skip")
        return {"design_check": {}}

    # 공간 정보
    minx, miny, maxx, maxy = usable_poly.bounds
    area_sqm = usable_poly.area / 1_000_000
    entrance_side = _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy)

    # design intent 자연어 변환
    intents_description = _build_intents_description(design_intents)
    # placement 결과 자연어 변환
    placement_description = _build_placement_description(placed_objects, failed_objects)

    prompt = DESIGN_VALIDATOR_PROMPT_TEMPLATE.format(
        area_sqm=area_sqm,
        entrance_side=entrance_side,
        intents_description=intents_description,
        placement_description=placement_description,
        validation_questions=build_validation_questions_text(),
    )

    tool = build_tool_schema()
    client = Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",  # 비용 절약 (concept_area 의 layout_validator 와 정합)
            max_tokens=2048,
            temperature=0.1,
            system=DESIGN_VALIDATOR_SYSTEM,
            tools=[tool],
            tool_choice={"type": "tool", "name": "validate_design_layout"},
            messages=[{"role": "user", "content": prompt}],
        )
        from app.token_tracker import track_usage
        track_usage("large.design_validator", response)

        result = {}
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                result = dict(block.input or {})
                break

        warned = [r["label"] for r in DESIGN_VALIDATION_RULES if result.get(r["key"]) == "WARN"]
        if warned:
            logger.warning(f"[lg_design_validator] WARN: {warned}")
        else:
            logger.info("[lg_design_validator] 모든 기준 OK")

        return {"design_check": result}

    except Exception as e:
        logger.warning(f"[lg_design_validator] LLM 호출 실패: {e}")
        return {"design_check": {}}


def _build_intents_description(design_intents: list) -> str:
    """design_intents → 자연어 요약 (LLM 검증 입력용). 좌표 X."""
    if not design_intents:
        return "(design intent 없음)"
    lines = []
    for i, intent in enumerate(design_intents[:30], 1):  # cap 30 (토큰 절약)
        obj_type = intent.get("object_type", "?")
        concept_area = intent.get("concept_area", "?")
        direction = intent.get("direction", "?")
        priority = intent.get("priority", "?")
        because = intent.get("placed_because", "")[:120]
        lines.append(
            f"#{i} {obj_type} | concept_area={concept_area}, dir={direction}, priority={priority}"
            + (f" | reason={because}" if because else "")
        )
    if len(design_intents) > 30:
        lines.append(f"... (총 {len(design_intents)}개, 30개만 표시)")
    return "\n".join(lines)


def _build_placement_description(placed_objects: list, failed_objects: list) -> str:
    """placement 결과 → 자연어 요약."""
    placed_count = len(placed_objects)
    failed_count = len(failed_objects)
    total = placed_count + failed_count
    success_rate = (placed_count / total * 100) if total > 0 else 0

    lines = [
        f"총 design intent: {total}개",
        f"배치 성공: {placed_count}개 ({success_rate:.0f}%)",
        f"배치 실패: {failed_count}개",
    ]

    if failed_objects:
        lines.append("\n실패 목록:")
        for f in failed_objects[:10]:
            obj_type = f.get("object_type", "?")
            reason = f.get("reason", "?")
            lines.append(f"- {obj_type}: {reason}")
        if len(failed_objects) > 10:
            lines.append(f"... ({len(failed_objects)}개 중 10개만 표시)")

    # direction 분포
    if placed_objects:
        from collections import Counter
        dir_counts = Counter(p.get("direction", "?") for p in placed_objects)
        lines.append(f"\ndirection 분포: {dict(dir_counts)}")

    # object_type 분포
    if placed_objects:
        from collections import Counter
        type_counts = Counter(p.get("object_type", "?") for p in placed_objects)
        lines.append(f"object_type 분포: {dict(type_counts)}")

    return "\n".join(lines)


def _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy) -> str:
    """입구 좌표 → 상/하/좌/우 판정 (concept_area / layout_validator 와 같은 로직)."""
    if not entrance_mm:
        return "하단"
    ex, ey = entrance_mm
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    dx, dy = ex - cx, ey - cy
    w, h = maxx - minx, maxy - miny
    nx = dx / (w / 2) if w > 0 else 0
    ny = dy / (h / 2) if h > 0 else 0
    if abs(nx) > abs(ny):
        return "우측" if nx > 0 else "좌측"
    return "하단" if ny > 0 else "상단"
