"""design_fix 노드 (lg_design_fix) — 2026-05-06 신설.

design_validator 가 verdict='fix_needed' 판정 시 호출. 1차 design intent + placement 결과 +
위반 사유 받고 design_intents 재결정 (위반 항목 집중 수정). placement 가 새 intents 받아 재배치.

흐름 (graph.py):
    lg_design (Sonnet) → lg_placement (코드) → lg_design_validator (Haiku)
       → conditional:
          ├─ ok → 다음 노드
          ├─ fix_needed + retry < 2 → lg_design_fix (Sonnet) → lg_placement 재호출 → 다시 lg_design_validator
          └─ retry >= 2 → 다음 노드 (포기)

return:
  - 성공: {"design_intents": <new>, "design_fix_retry_count": <inc>}
  - 실패: {"design_fix_retry_count": <max>} (재시도 차단)
"""
import json
import logging
import os
import re

from anthropic import Anthropic

from app.state import LargeState
from app.nodes_large.f_placement.prompts.design_fix import (
    DESIGN_FIX_SYSTEM,
    DESIGN_FIX_PROMPT_TEMPLATE,
    build_violations_text,
)

logger = logging.getLogger(__name__)


def run(state: LargeState) -> dict:
    """design_fix — 1차 design intent + 위반 사유 받고 새 intents 결정. placement 재실행 트리거."""
    design_intents = state.get("design_intents") or []
    placed_objects = state.get("placed_objects") or []
    failed_objects = state.get("failed_objects") or []
    validator_result = state.get("design_check") or {}
    usable_poly = state.get("usable_poly")
    entrance_mm = state.get("entrance_mm")
    ref_analysis = state.get("ref_analysis") or {}
    retry_count = state.get("design_fix_retry_count") or 0

    if not design_intents or not usable_poly:
        logger.info("[lg_design_fix] 입력 부족 — skip")
        return {"design_fix_retry_count": 99}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[lg_design_fix] API 키 없음 — skip")
        return {"design_fix_retry_count": 99}

    minx, miny, maxx, maxy = usable_poly.bounds
    area_sqm = usable_poly.area / 1_000_000
    entrance_side = _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy)

    intents_description = _build_intents_description(design_intents)
    placement_description = _build_placement_description(placed_objects, failed_objects)
    violations_text = build_violations_text(validator_result)

    # ref 요약 (간단)
    ref_summary = ""
    if ref_analysis:
        parts = []
        for field in ("layout_patterns", "focal_points", "partition_usage"):
            items = ref_analysis.get(field, [])
            if items:
                parts.extend(items if isinstance(items, list) else [items])
        if parts:
            ref_summary = "\n".join(f"- [{field}: {p}]" for p in parts[:10])  # cap 10

    prompt = DESIGN_FIX_PROMPT_TEMPLATE.format(
        area_sqm=area_sqm,
        entrance_side=entrance_side,
        intents_description=intents_description,
        placement_description=placement_description,
        violations_text=violations_text,
        ref_summary=ref_summary,
    )

    client = Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16384,  # 대량 design intent + placed_because 대비
            temperature=0.3,
            system=DESIGN_FIX_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        from app.token_tracker import track_usage
        track_usage("large.design_fix", response)

        if not response.content:
            logger.warning("[lg_design_fix] 빈 응답 — retry_count 증가")
            return {"design_fix_retry_count": retry_count + 1}

        # 응답에서 JSON list 파싱
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text

        new_intents = _parse_json_list(text)
        if not new_intents:
            logger.warning("[lg_design_fix] JSON 파싱 실패 — retry_count 증가")
            return {"design_fix_retry_count": retry_count + 1}

        new_retry_count = retry_count + 1

        logger.info(
            "[lg_design_fix] retry %d → %d intents (1차 %d → fix %d)",
            new_retry_count,
            len(new_intents),
            len(design_intents),
            len(new_intents),
        )

        return {
            "design_intents": new_intents,
            "design_fix_retry_count": new_retry_count,
        }

    except Exception as e:
        logger.warning(f"[lg_design_fix] LLM 호출 실패: {e}")
        return {"design_fix_retry_count": retry_count + 1}


def _parse_json_list(text: str) -> list:
    """LLM 응답 텍스트에서 JSON list 추출."""
    if not text:
        return []
    # ```json ... ``` 블록 우선
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 직접 JSON 배열
    m = re.search(r"(\[[\s\S]*\])", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return []


def _build_intents_description(design_intents: list) -> str:
    if not design_intents:
        return "(design intent 없음)"
    lines = []
    for i, intent in enumerate(design_intents[:30], 1):
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
            lines.append(f"- {f.get('object_type', '?')}: {f.get('reason', '?')}")
    return "\n".join(lines)


def _detect_entrance_side(entrance_mm, minx, miny, maxx, maxy) -> str:
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
