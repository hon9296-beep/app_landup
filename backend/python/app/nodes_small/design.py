"""
Agent 3 디자인 의도 결정 노드 — Shin 코드 베이스 + buildup/agent3 강화.

레퍼런스 이미지 + zone_map → LLM이 "뭘 어디에 왜" 결정.
좌표/mm 값 출력 금지. zone_label + direction + priority만.
강화: Circuit Breaker (좌표 주입 방지) + fill 수량 파싱.
"""
import json
import logging
import os
import re
from typing import Optional

from anthropic import Anthropic
from pydantic import RootModel, field_validator, model_validator

from app.nodes_small.llm_policy import StrictLLMModel
from app.state import SmallState
from app.utils import OBJECT_STANDARDS
from app.core.exceptions import LLMParsingError, LLMValidationError

logger = logging.getLogger(__name__)


# 2026-04-29 Phase 3 harness: design.py LLM 응답 Pydantic 모델.
# DESIGN_PROMPT_TEMPLATE 의 example JSON 과 1:1.
# StrictLLMModel (app.llm_policy):
#   extra="allow" + 위험 키 (BANNED_LLM_KEYS — x_mm/y_mm/center_x/width_mm 등) 자동 거부 +
#   새 필드 logger.warning. forbid 의 over-strict 차단 회피 (LLM 의 정당한 확장 보존).
# placed_because 의 자연어 mm 수치는 자유 텍스트라 검사 안 됨 (오탐 방지 — 기존 정책 유지).
class DesignIntent(StrictLLMModel):
    object_type: str
    ref_point_id: Optional[str] = None
    zone_label: str = "mid_zone"
    direction: str = "wall_facing"
    alignment: str = "parallel"
    priority: int = 1
    join_with: Optional[str] = None
    placement_reason: str = ""
    placed_because: str = ""
    # 1-2 (#520 후속): 매뉴얼 명시 별도 라벨 (예: "POS 카운터" / "증정품 카운터") 보존.
    # 같은 object_type 안에서 라벨이 다르면 의미적 기능이 다른 인스턴스 — placement 가
    # 해당 라벨 가진 eligible 과 1:1 매칭하도록 LLM 출력에서부터 들고 다님. None 허용 (default 풀).
    manual_label: Optional[str] = None
    # 1-3 후속 (B1, #533): ref_analysis 영감 추적. 어느 ref 분석 항목 (layout_patterns / focal_points 등)
    # 에서 영감 받았는지 LLM 이 자유 텍스트로 인용. design_reviewer 가 ref 활용도 검증 가능.
    # 빈 문자열 = ref 영감 무관 (매뉴얼 / R 룰 단독 결정). None X (text 0/N).
    inspired_by_ref: str = ""

    # 2026-04-29 (#260): placement_reason schema 검증 — 하네스 retry 안전망.
    # PLACEMENT_REASONS 미등록 키 / RESTRICTED_REASONS 위반 → ValueError → 하네스 재시도.
    # prompt 만 의존하면 LLM 이 무시 가능 — schema 강제로 최종 안전망 (제미나이 자문 9.5).
    # PLACEMENT_REASONS / RESTRICTED_REASONS 는 import 순환 회피 위해 validator 내부 import.
    @model_validator(mode="after")
    def _validate_placement_reason(self):
        from app.nodes_small.prompt_rules import PLACEMENT_REASONS, RESTRICTED_REASONS
        # 빈 값 허용 (non-partition 객체) — partition 만 필수 강제 (아래 분기)
        valid_keys = set(PLACEMENT_REASONS.keys()) | {""}
        if self.placement_reason not in valid_keys:
            raise ValueError(
                f"placement_reason={self.placement_reason!r} PLACEMENT_REASONS 미등록 키. "
                f"허용: {sorted(PLACEMENT_REASONS.keys())}"
            )
        # partition_wall_I/L 은 RESTRICTED_REASONS 화이트리스트 강제
        if self.object_type.startswith("partition_wall"):
            allowed = RESTRICTED_REASONS.get(self.object_type, [])
            if allowed:
                if self.placement_reason == "":
                    raise ValueError(
                        f"{self.object_type} 의 placement_reason 누락 — 필수. 허용: {allowed}"
                    )
                if self.placement_reason not in allowed:
                    raise ValueError(
                        f"{self.object_type} 의 placement_reason={self.placement_reason!r} "
                        f"RESTRICTED_REASONS 위반. 허용: {allowed}"
                    )
        return self


class DesignIntentList(RootModel[list[DesignIntent]]):
    """LLM 응답 top-level array 모델 (RootModel)."""

    @field_validator("root")
    @classmethod
    def reject_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("design_intents 빈 list — LLM 응답 무효")
        return v

# ── 면적 기반 R1~R5 분기 (66㎡ = 20평 기준) ──────────────────────────────
# SMALL_AREA_THRESHOLD_MM2 는 app.constants 로 중앙화 (2026-04-22 S-8g-1)
from app.constants import SMALL_AREA_THRESHOLD_MM2  # noqa: E402,F401

def _build_rules_text(usable_area_mm2: float) -> str:
    """면적 기반으로 ZONING + R룰 프롬프트 텍스트 생성.

    R룰 원본은 prompt_rules.py에서 관리. 수정은 그 파일만.
    """
    from app.nodes_small.prompt_rules import build_zoning_prompt
    size = "small" if usable_area_mm2 < SMALL_AREA_THRESHOLD_MM2 else "medium"
    header = "소형 매장" if size == "small" else "중형 매장"
    zoning_text = build_zoning_prompt(size)
    return (
        f"## 공간 분할(Zoning) + 배치 규칙 — {header}\n\n"
        f"**우선순위: 브랜드 규정 > R 룰.** 브랜드 규정과 R 룰이 충돌하면 브랜드 규정을 따르세요.\n\n"
        f"{zoning_text}"
    )


# Design prompt — #491 prompts 중앙화 (nodes_small/prompts/design.py)
from app.nodes_small.prompts.design import (
    DESIGN_SYSTEM_TEMPLATE,
    DESIGN_PROMPT_TEMPLATE,
)

def run(state: SmallState) -> SmallState:
    """Agent 3: 배치 의도 결정. LLM은 이름만 받고 방향만 결정."""
    brand_data = state.get("brand_data") or {}
    zone_map = state.get("zone_map") or {}
    usable_poly = state.get("usable_poly")
    ref_analysis = state.get("ref_analysis") or {}

    # ── eligible_objects는 object_selection이 만든 것 재사용 ──
    eligible_objects = state.get("eligible_objects") or []
    if not eligible_objects:
        logger.warning("[design] eligible_objects 없음")
        return {
            "design_intents": [], "eligible_objects": [],
            "prev_design_intents": state.get("design_intents") or [],
            "_review_iteration": state.get("_review_iteration", 0) + 1,
            "_reviewer_feedback": "",
        }

    # ── 재호출 판단: choke_feedback이 있으면 실패 오브젝트만 재기획 ──
    choke_feedback = state.get("choke_feedback") or ""
    failed_objects = state.get("failed_objects") or []
    placed_objects = state.get("placed_objects") or []
    is_retry = bool(choke_feedback and failed_objects)

    # ── [I-5 / 2026-04-23] ref 컨텍스트 부재 시 LLM 스킵 + 룰 기반 fallback ──
    # 트리거: reference_images 0건 (DDG rate limit / 신규 카테고리 첫 호출 등)
    #         OR ref_analysis status=error (크레딧 고갈 / 분석 실패)
    # 목적:
    #   - 토큰 절감 (사이클당 약 $0.05+ 감소 — design.py LLM 호출 제거)
    #   - 결정론 확보 (LLM variance 제거)
    #   - 크레딧 고갈 시 파이프라인 continuity 보장 (크래시 대신 룰 기반 완료)
    # 배경: 2026-04-23 11:03 실측에서 DDG rate limit → ref 이미지 0건 상황 확증.
    #       기존엔 빈 ref 컨텍스트로 그대로 LLM 호출되어 토큰 낭비 + 품질 저하 발생.
    _reference_images = state.get("reference_images") or []
    # 2026-04-28 fix(A → B 정식): ref_analysis 가 평면 dict (layout_patterns/focal_points 등).
    # envelope (status/result) 가정 회귀 차단 — state.is_ref_analysis_empty helper 통일.
    # 명세: state.RefAnalysisDict (TypedDict). #263 B 안.
    from app.state import is_ref_analysis_empty
    if not _reference_images or is_ref_analysis_empty(ref_analysis):
        _category = brand_data.get("brand", {}).get("brand_category", "기타")
        if isinstance(_category, dict):
            _category = _category.get("value", "기타") or "기타"
        # 2026-04-29 (#264 fail-loud): info → error 격상.
        # ref 컨텍스트 부재는 정상 흐름 아님 — DDG rate limit / API 실패 / 이미지 0건 등
        # 실제 이상 상황. 로그 격상 + 응답 필드 (design_fallback_reason) + 프론트 경고 (#264)
        # 3중으로 사용자/운영자 즉시 인지 가능하게.
        logger.error(
            "[design] FAIL-LOUD: REF_CONTEXT_MISSING → LLM 스킵 + 룰 기반 fallback. "
            f"images={len(_reference_images)}, analyzer_keys={list(ref_analysis.keys()) if ref_analysis else None}. "
            "ref_image_analyzer 단계 점검 필요 (DDG rate limit / API key / 이미지 검색 결과)."
        )
        _rps = state.get("reference_points") or []
        # 2026-05-01 SSOT trace: design fallback 진입 (REF_CONTEXT_MISSING)
        from app.categories import dump_category_trace
        dump_category_trace(
            stage="design.fallback_ref_context_missing",
            raw_brand_category=_category,
            eligible_count=len(eligible_objects),
            eligible_types=[o.get("object_type") for o in eligible_objects],
            ref_points_count=len(_rps),
        )
        intents = _default_intents(eligible_objects, _rps, _category)
        if is_retry:
            intents = _merge_retry_intents(placed_objects, intents)
        intents = _enforce_placement_hints(intents, state.get("resolved_intents") or [], _rps)
        intents = _apply_global_direction(intents, state.get("global_direction_hint"))
        # 1-2 (#520 후속): sub_graph_reasons dump — fallback 사유 가시화
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        dump_agent_reason(state, node="design", decision="fallback",
                          reason="REF_CONTEXT_MISSING",
                          context={
                              "images": len(_reference_images),
                              "ref_analysis_keys": list(ref_analysis.keys()) if ref_analysis else [],
                              "eligible_count": len(eligible_objects),
                              "intents_generated": len(intents),
                              "is_retry": is_retry,
                          })
        return {
            "design_intents": intents,
            "eligible_objects": eligible_objects,
            "design_fallback_reason": "REF_CONTEXT_MISSING",
            # #474 reviewer iteration 추적 — 다른 4 return path 와 일관 (이 path 만 누락이었음, 무한 루프 유발)
            "prev_design_intents": state.get("design_intents") or [],
            "_review_iteration": state.get("_review_iteration", 0) + 1,
            "_reviewer_feedback": "",
        }

    if is_retry:
        # 실패한 object_type만 LLM에 전달
        failed_types = {f["object_type"] for f in failed_objects}
        retry_eligible = [o for o in eligible_objects if o["object_type"] in failed_types]
        unique_types = list(dict.fromkeys(o["object_type"] for o in retry_eligible))
        logger.info(f"[design] 재호출: 실패 {len(failed_types)}종만 재기획 — {list(failed_types)}")
    else:
        unique_types = list(dict.fromkeys(o["object_type"] for o in eligible_objects))

    # 밀도 가이드 생성
    density_ratio = state.get("density_ratio") or 0.25
    density_guide = _build_density_guide(density_ratio)

    # Reference points 요약 — _is_blocked 플래그가 있는 ref_point는 LLM 전달에서 제외
    reference_points = state.get("reference_points") or []
    llm_reference_points = [rp for rp in reference_points if not rp.get("_is_blocked")]
    blocked_count = len(reference_points) - len(llm_reference_points)
    if blocked_count:
        logger.info(f"[design] _is_blocked ref_point {blocked_count}개 LLM 전달 제외")
        # 필터링 결과 덤프
        import json as _json, os as _os
        _dump_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "debug_logs", "ref_point_filter.json")
        try:
            with open(_dump_path, "w", encoding="utf-8") as _f:
                _json.dump({
                    "total": len(reference_points),
                    "survived": len(llm_reference_points),
                    "dropped_count": blocked_count,
                    "dropped_ids": [rp["id"] for rp in reference_points if rp.get("_is_blocked")],
                    "survived_ids": [rp["id"] for rp in llm_reference_points],
                }, _f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    # dead zone 좌표 → ref_point 근접 경고용
    from app.utils import extract_structural_dead_zones
    from shapely.ops import unary_union as _unary_union
    structural_dz = extract_structural_dead_zones(state)
    # static_cache 구성 — 벽면 가용 길이 계산용 (placement.py와 동일 로직)
    _dead_zones = state.get("dead_zones") or []
    _static_obs = [dz for dz in _dead_zones if hasattr(dz, "area")]
    for _dz_entry in structural_dz:
        if _dz_entry["type"] == "core_access":
            _static_obs.append(_dz_entry["poly"])
    _main_artery = state.get("main_artery")
    if _main_artery:
        _static_obs.append(_main_artery.buffer(450))
    _entrance_buffer = state.get("entrance_buffer")
    if _entrance_buffer:
        _static_obs.append(_entrance_buffer)
    _static_cache = _unary_union(_static_obs) if _static_obs else None
    ref_points_summary = _build_ref_points_summary(llm_reference_points, structural_dead_zones=structural_dz, static_cache=_static_cache)

    # 배치 예시 (이전 성공 사례)
    layout_examples = state.get("layout_examples") or []
    examples_text = _build_layout_examples_text(layout_examples)

    # 프롬프트 구성 — 이름만, 치수 없음
    usable_area = usable_poly.area / 1_000_000 if usable_poly else 0
    # 타입별 수량 카운트 → LLM에 전달
    from collections import Counter
    type_counts = Counter(o["object_type"] for o in eligible_objects)
    objects_list = "\n".join(f"- {ot} (최대 {type_counts[ot]}개)" for ot in unique_types)
    # 1-2 (#520 후속): 같은 std_id 인데 brand 매뉴얼이 별도 manual_label 로 명시한 인스턴스를
    # design LLM 이 1개로 합치는 회귀 차단. multi-label std_id 가 있을 때만 별도 섹션 inject.
    manual_label_section = _build_manual_label_section(eligible_objects)

    # 브랜드 매뉴얼에 조형물 목록이 있으면 필수 배치 섹션 생성
    figures_mentioned = brand_data.get("brand", {}).get("figures_mentioned") or []
    if figures_mentioned:
        names = "\n".join(f"  - {f}" for f in figures_mentioned)
        required_figures = f"\n## 필수 배치 조형물\n브랜드 매뉴얼에 명시된 아래 조형물을 각 1개씩 반드시 배치하세요:\n{names}\n"
    else:
        required_figures = ""

    brand_rules_text = json.dumps(brand_data.get("brand", {}), ensure_ascii=False, indent=2)

    # pair_rules → LLM용 텍스트
    pair_rules = brand_data.get("pair_rules") or []
    pair_rules_text = _build_pair_rules_text(pair_rules)

    # wall_attachment → LLM용 텍스트
    wall_attachment_text = _build_wall_attachment_text(eligible_objects)

    # placement_reasons → LLM용 텍스트  ← prompt_rules.PLACEMENT_REASONS
    from app.nodes_small.prompt_rules import PLACEMENT_REASONS, RESTRICTED_REASONS
    placement_reasons_text = "\n".join(f"- {k}: {v}" for k, v in PLACEMENT_REASONS.items())

    # 2026-04-28: object_type 별 placement_reason 화이트리스트 동적 주입.
    # eligible_objects 안에 RESTRICTED_REASONS 대상 type 이 있을 때만 제약 라인 추가.
    eligible_types = {o["object_type"] for o in eligible_objects}
    restriction_lines = []
    for ot, allowed in RESTRICTED_REASONS.items():
        if ot in eligible_types:
            restriction_lines.append(
                f"- [강제 제약] {ot} 의 placement_reason 은 다음 중 하나만 허용된다: {', '.join(allowed)}. "
                f"이 외 사유 (예: balance, hero_display) 사용 시 도메인 룰 위반."
            )
    if restriction_lines:
        placement_reasons_text += "\n\n[기물별 사유 제한]\n" + "\n".join(restriction_lines)

    # IQI: 면적 기반 적정 수량
    max_points = len(reference_points)
    avg_footprint = sum(o["width_mm"] * o["depth_mm"] for o in eligible_objects) / max(len(eligible_objects), 1)
    density_ratio = state.get("density_ratio") or 0.25
    usable_area_mm2 = usable_area * 1_000_000
    iqi_max = int((usable_area_mm2 * density_ratio) / avg_footprint) if avg_footprint > 0 else max_points
    recommended_count = min(iqi_max, max_points)

    from app.venue_rules import get_venue_label, DEFAULT_VENUE_TYPE
    from app.facade_rules import get_facade_label, get_facade_rules, DEFAULT_FACADE_TYPE
    venue_type = state.get("venue_type") or DEFAULT_VENUE_TYPE
    facade_type = state.get("facade_type") or DEFAULT_FACADE_TYPE
    facade_rules_runtime = get_facade_rules(facade_type)
    # 파사드 조건부 프롬프트  ← facade_rules.py FACADE_RULES
    if facade_rules_runtime.get("allow_rear_graphic_wall"):
        facade_note = "본 매장은 외부에서 내부 시인이 가능한 파사드이므로 가벽 단면을 브랜드 그래픽 월 용도로 활용해도 외부 고객 시선 확보 측면에서 의미가 있다."
    else:
        facade_note = "본 매장은 폐쇄형 파사드(출입문만 존재)로 외부 시선 확보 없음. 가벽 뒷면이 벽에 붙거나 외부에 노출되지 않으면 그래픽 월 용도 사유는 무효이다. 가벽 단면 활용 시 반드시 실제 고객 동선에서 시인 가능한 면을 기준으로 판단할 것."

    prompt = DESIGN_PROMPT_TEMPLATE.format(
        usable_area_sqm=usable_area,
        venue_type_label=get_venue_label(venue_type),
        facade_type_label=get_facade_label(facade_type),
        facade_note=facade_note,
        zone_map=json.dumps(zone_map),
        entrance_count=len(state.get("all_entrances_mm") or []) or 1,
        ref_point_count=len(reference_points),
        ref_points_summary=ref_points_summary,
        brand_rules=brand_rules_text,
        max_slots=max_points,
        recommended_count=recommended_count,
        objects_list=objects_list,
        manual_label_section=manual_label_section,
        wall_attachment_text=wall_attachment_text,
        pair_rules_text=pair_rules_text,
        placement_reasons_text=placement_reasons_text,
        layout_examples=examples_text,
        density_guide=density_guide,
        required_figures=required_figures,
    )

    # ── 기존 배치 현황 주입 (locked_objects) ──
    locked_objects = state.get("locked_objects") or []
    if locked_objects:
        from app.core.intent_parser import _build_locked_summary
        locked_summary = _build_locked_summary(locked_objects)
        prompt += f"\n## 이미 배치된 오브젝트 (건드리지 마세요)\n"
        prompt += "아래 오브젝트는 사용자가 유지하도록 요청한 기존 배치입니다. 이 오브젝트들은 배치 결과에 포함하지 말고, 공간 점유 장애물로만 취급하세요.\n"
        prompt += locked_summary + "\n"
        logger.info(f"[design] locked_objects {len(locked_objects)}개 컨텍스트 주입")

    # ── 사용자 요구사항 인텐트 주입 (intent_parser 출력) ──
    resolved_intents = state.get("resolved_intents") or []
    if resolved_intents:
        intent_lines = []
        for it in resolved_intents:
            qty = "fill(최대)" if it.get("quantity") == -1 else f"{it.get('quantity', 1)}개"
            zone = f" (zone: {it['zone_hint']})" if it.get("zone_hint") else ""
            direction = f" (direction: {it['direction_hint']})" if it.get("direction_hint") else ""
            wall = f" (wall: {it['wall_hint']})" if it.get("wall_hint") else ""
            intent_lines.append(
                f"- {it.get('object_type', '?')} {qty}{zone}{direction}{wall}  ※원문: \"{it.get('original_text', '')}\""
            )
        prompt += "\n## 사용자 요구사항 (반드시 포함 — 하드 제약)\n"
        prompt += "아래 오브젝트를 지정된 수량만큼 **반드시** 배치하세요.\n"
        prompt += "**[zone 강제] zone이 명시된 경우 반드시 해당 zone의 ref_point만 선택하세요. P1~P4 원칙보다 zone 제약이 우선합니다.**\n"
        prompt += "**[wall 강제] wall 힌트(right/left/center)가 명시된 경우 entrance_side가 일치하는 ref_point를 반드시 선택하세요.**\n"
        prompt += "아래 목록에 없는 오브젝트는 배치하지 마세요.\n"
        prompt += "\n".join(intent_lines) + "\n"
        logger.info(f"[design] resolved_intents {len(resolved_intents)}개 주입")

    # ── 재호출 피드백 주입 (failure_classifier → choke_feedback) ──
    choke_feedback = state.get("choke_feedback") or ""
    if choke_feedback:
        prompt += f"""

## 이전 배치 실패 피드백
아래 오브젝트가 이전 시도에서 배치 실패했습니다. 다른 zone이나 direction/alignment으로 재기획하세요.
{choke_feedback}
"""
        logger.info(f"[design] 재호출: choke_feedback 주입 ({len(choke_feedback)}자)")

    # LLM 호출
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # 2026-04-29 (#264): fail-loud — API key 미설정은 운영 환경 치명적 이상
        logger.error("[design] FAIL-LOUD: API_KEY_MISSING → ANTHROPIC_API_KEY 환경변수 설정 필요. 룰 기반 fallback.")
        category = brand_data.get("brand", {}).get("brand_category", "\uae30\ud0c0")
        if isinstance(category, dict):
            category = category.get("value", "\uae30\ud0c0")
        # 2026-05-01 SSOT trace: API_KEY_MISSING fallback
        from app.categories import dump_category_trace
        dump_category_trace(
            stage="design.fallback_api_key_missing",
            raw_brand_category=category,
            eligible_count=len(eligible_objects),
        )
        intents = _default_intents(eligible_objects, reference_points, category)
        # 1-2 (#520 후속): sub_graph_reasons dump
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        dump_agent_reason(state, node="design", decision="fallback",
                          reason="API_KEY_MISSING",
                          context={
                              "eligible_count": len(eligible_objects),
                              "intents_generated": len(intents),
                          })
        return {
            "design_intents": intents, "eligible_objects": eligible_objects,
            "design_fallback_reason": "API_KEY_MISSING",
            "prev_design_intents": state.get("design_intents") or [],
            "_review_iteration": state.get("_review_iteration", 0) + 1,
            "_reviewer_feedback": "",
        }

    client = Anthropic(api_key=api_key)

    # 2026-05-01 SSOT trace: design LLM 호출 진입 (정상 흐름 시작점)
    _llm_cat = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(_llm_cat, dict):
        _llm_cat = _llm_cat.get("value", "기타")
    from app.categories import dump_category_trace
    dump_category_trace(
        stage="design.llm_call_start",
        raw_brand_category=_llm_cat,
        eligible_count=len(eligible_objects),
        eligible_types=[o.get("object_type") for o in eligible_objects],
        ref_points_count=len(reference_points),
        is_retry=is_retry,
    )

    # 메시지 구성 (ref_analysis 텍스트 — 이미지 base64는 보내지 않음)
    ref_analysis_text = _build_ref_analysis_text(ref_analysis)
    if ref_analysis_text:
        prompt = ref_analysis_text + "\n\n" + prompt

    # #474 reviewer feedback inject — design 재호출 (iteration > 0) 시 prompt 에 위반 사유 + 피드백 추가
    _reviewer_feedback = state.get("_reviewer_feedback", "")
    if _reviewer_feedback:
        prompt = prompt + "\n\n" + _reviewer_feedback

    # #490 placement_reviewer feedback inject — placement 후 reviewer reject 로 design 재호출 시
    # slot 양보 hint inject. drop 된 매뉴얼 obj 우선 + 점유 obj 양보 검토 의도.
    _placement_reviewer_feedback = state.get("_placement_reviewer_feedback", "")
    if _placement_reviewer_feedback:
        # 1-3 (#523 후속): design 한테 양보 권한 명시 + placed_objects 현황 inject.
        # 진규님 비전: "양보하고 조금밀고 ... 어떤 기물이니까 저기로 옮기되 벽이랑 붙여야지" 판단을
        # design (LLM agent) 가 자체 결정. 단순 retry 가 아니라 placement 결과 보고 재기획.
        _placed = state.get("placed_objects") or []
        _failed = state.get("failed_objects") or []
        _placed_summary_lines = []
        for p in _placed:
            ot = p.get("object_type", "?")
            ml = p.get("manual_label")
            anchor = p.get("anchor_key", "?")
            zone = p.get("zone_label", "?")
            direction = p.get("direction", "?")
            attach = p.get("wall_attachment", "?")
            because = (p.get("placed_because") or "")[:80]
            is_fb = "fallback_phase" in because
            label_str = f' (라벨 "{ml}")' if ml else ""
            flag = " [강제 끼워박힘]" if is_fb else ""
            _placed_summary_lines.append(f"  - {ot}{label_str} @ {zone} / ref={anchor} / dir={direction} / attach={attach}{flag}")
        _placed_summary = "\n".join(_placed_summary_lines) or "  (placed 없음)"
        _failed_summary_lines = []
        for f in _failed:
            ot = f.get("object_type", "?")
            reason = (f.get("reason") or "?")[:120]
            _failed_summary_lines.append(f"  - {ot} (사유: {reason})")
        _failed_summary = "\n".join(_failed_summary_lines) or "  (failed 없음)"

        # 1-3 (#523 후속): 이전 라운드 fail / fallback 끼워박힌 obj 의 zone 추적 — design 재시도 시 차단.
        _failed_or_fallback_zones: dict[str, set[str]] = {}
        for p in _placed:
            if "fallback_phase" in (p.get("placed_because") or ""):
                ot = p.get("object_type", "")
                _failed_or_fallback_zones.setdefault(ot, set()).add(p.get("zone_label", ""))
        for f in _failed:
            ot = f.get("object_type", "")
            # failed 의 본 의도 zone 도 차단 (그 zone 자체가 부적합)
            for intent in (state.get("design_intents") or []):
                if intent.get("object_type") == ot:
                    iz = intent.get("zone_label")
                    if iz:
                        _failed_or_fallback_zones.setdefault(ot, set()).add(iz)
                    break
        _zone_blocklist_lines = []
        for ot, zones in _failed_or_fallback_zones.items():
            _zone_blocklist_lines.append(f"  - **{ot}** 는 {sorted(zones)} 에서 실패 / fallback. 이번 라운드엔 **다른 zone** 으로 강제 이동.")
        _zone_blocklist = "\n".join(_zone_blocklist_lines) or "  (이전 fail / fallback 케이스 없음)"

        retry_authority = f"""

## [재기획 권한 — design director 모드]
당신은 단순 retry 가 아니라 **placement 결과를 보고 재기획하는 design director**입니다.
다음 권한을 자율적으로 행사하세요:

- **양보 (Yield)**: 기존 placed obj 의 zone / ref_point 옮겨서 더 중요한 obj 가 들어갈 자리 마련.
  예: shelf_wall 이 wall_15_left 차지해서 photo_wall fail → shelf_wall 을 다른 ref 로 옮기고 photo_wall 을 wall_15_left 로.
- **이동 (Relocate)**: structural anchor 의 zone 재기획. counter 가 entrance_zone 단독 → deep_zone (결제 동선 끝점) 으로 재기획.
- **벽 부착 강제 (Wall-attach)**: standalone 으로 박힌 obj (placed_because 에 'fallback_phase' 흔적) 는 의도가 깨진 것. 다음 라운드엔 명확한 wall_facing + 부착 가능한 ref_point 매핑.
- **띄움 (Float)**: 좁은 동선 / 충돌 가능 자리에선 일부러 다른 ref_point 로 띄워 동선 확보.
- **붙임 (Cluster)**: pair_rules join 관계 obj 는 같은 ref_point 또는 인접 ref 매핑.

## [실패 / fallback zone 강제 차단 — 같은 zone 재시도 금지]
이전 라운드에서 다음 obj 들이 해당 zone 에서 실패 또는 fallback 으로 강제 끼워박힘. **같은 zone 재시도 절대 금지** — 다른 zone 으로 이동 강제:

{_zone_blocklist}

P3 (Focal Point deep_zone 권장) 같은 일반 룰보다 위 zone 차단이 우선. 의도 (magnet anchor / 동선 유도 등) 는 다른 zone 에서도 살릴 수 있음.

**[재기획 시 placement 흐름 인지]:**
- 이전 라운드 placed_objects 가 그대로 다시 박힐 거라 가정하지 마세요 — placement 가 **처음부터 다시** 돕니다.
- 직전 placed_objects 는 placement 의 step-down / slot 순회 결과 — 당신 원래 의도와 다른 자리일 수 있음. 즉 "직전에 거기 박혔으니 거기 좋다" 가정 X.
- 직전에 fail 한 obj 의 zone 그대로 두면 또 fail 가능. 후보 ref_point 다 시도 후 drop 했으므로 zone 자체 변경 또는 그 zone 의 다른 obj 양보 받기 필수.
- 당신이 출력한 새 design_intents 가 그대로 placement 입력. 양보 받아 옮기려는 obj 의 새 zone/ref 명시 필수 — 그 obj 가 자동으로 옮겨지지 않음.

## [이전 라운드 placement 결과 — 참고]
### placed (현재 자리 잡은 obj):
{_placed_summary}

### failed (drop 된 obj — 못 들어간 사유):
{_failed_summary}

위 정보 + 아래 placement_reviewer 피드백 종합해서 새 design_intents 작성.
"""
        prompt = prompt + retry_authority + "\n\n" + _placement_reviewer_feedback

    # 1-3 (#533) C1: pathing_validator feedback inject — 동선 차단 (trapped) 시 design 재호출.
    # placement_reviewer 와 동일 재기획 권한 모드 — agent 자율 양보 / 이동 / 띄움 판단.
    _pathing_feedback = state.get("_pathing_validator_feedback", "")
    if _pathing_feedback:
        prompt = prompt + "\n\n" + _pathing_feedback

    content = [{"type": "text", "text": prompt}]

    # LLM 설정 중앙 관리 (app.llm_config) — temperature=0.3 낮은 variance
    # 키 "small.design" = 네임스페이스 규약. "small." prefix 제거 금지
    # (Shin이 "large.design" 추가 시 충돌 방지). 상세: app/llm_config.py 최상단
    from app.llm_config import get_llm_config
    _cfg = get_llm_config("small.design")

    # 2026-04-29 Phase 3 harness: app.llm_harness.call_llm_text_json 으로 위임.
    # 기존: for-range retry + parse_llm_json_list + _has_coordinate_injection 루프
    # 신규: call_llm_text_json 1 호출 — Pydantic strict (DesignIntent + extra=forbid) 가
    #       좌표 키 추가 (x_mm/y_mm/center_x/center_y) 자동 차단 + RootModel reject_empty
    #       validator 가 빈 list 차단. 텍스트 단위 forbid_coordinate_injection 은 OFF —
    #       placed_because 의 정상 mm 수치 false positive 방지 (기존 정책 보존).
    from app.nodes_small.llm_harness import (
        call_llm_text_json, LLMHarnessError,
        LLMSchemaValidationError, LLMJSONParseError, LLMResponseEmptyError,
    )

    last_error = None
    try:
        result_obj, meta = call_llm_text_json(
            client,
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            # 프롬프트 캐싱 — system prompt는 도면마다 동일하므로 캐시 (같은 size 기준 동일 텍스트)
            system=[{
                "type": "text",
                "text": DESIGN_SYSTEM_TEMPLATE.format(rules_section=_build_rules_text(usable_area_mm2)),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
            response_model=DesignIntentList,
            forbid_coordinate_injection=False,
            track_usage_node="design",
            max_attempts=3,
        )
        # RootModel → list[dict]
        intents = [intent.model_dump() for intent in result_obj.root]
        logger.info(f"[design] {len(intents)} intents generated (attempts={meta.get('attempts', 1)})")

        # ── 하네스: LLM 응답의 object_type을 eligible 키로 복원 ──
        intents = _remap_object_types(intents, unique_types)

        # ── zone_hint / wall_hint 후처리 강제 (LLM이 무시했을 때 교정) ──
        intents = _enforce_placement_hints(intents, resolved_intents, reference_points)

        # 재호출 시: 기배치 intents 유지 + 실패분 intents 합치기
        if is_retry:
            intents = _merge_retry_intents(placed_objects, intents)
            logger.info(f"[design] 재호출 병합: 기배치 {len(placed_objects)}개 유지 + 신규 {len(intents) - len(placed_objects)}개")

        # ── global_direction_hint 후처리 (FULL_RELAYOUT 시) ──
        intents = _apply_global_direction(intents, state.get("global_direction_hint"))

        # 1-2 (#520 후속): sub_graph_reasons dump — LLM 정상 path 도 결정 가시화
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        manual_label_intents = sum(1 for i in intents if i.get("manual_label"))
        dump_agent_reason(state, node="design", decision="success",
                          reason="LLM_INTENTS_GENERATED",
                          context={
                              "intents_count": len(intents),
                              "manual_label_intents": manual_label_intents,
                              "is_retry": is_retry,
                              "attempts": meta.get("attempts", 1),
                              "iteration": state.get("_review_iteration", 0) + 1,
                          })
        return {
            "design_intents": intents,
            "eligible_objects": eligible_objects,
            # #474 reviewer iteration 추적 — 직전 intents 보존 (유사도 비교용) + iteration 증가
            "prev_design_intents": state.get("design_intents") or [],
            "_review_iteration": state.get("_review_iteration", 0) + 1,
            # 다음 iteration 위해 feedback 초기화 (재호출 시 reviewer 가 다시 채움)
            "_reviewer_feedback": "",
        }
    except LLMSchemaValidationError as e:
        last_error = LLMValidationError(f"좌표 키 또는 schema 위반: {e}", {})
    except LLMJSONParseError as e:
        last_error = LLMParsingError(f"JSON 파싱 실패: {e}", {})
    except LLMResponseEmptyError as e:
        last_error = LLMParsingError(f"LLM 응답 비어있음: {e}", {})
    except LLMHarnessError as e:
        last_error = LLMParsingError(f"하네스 실패: {type(e).__name__}: {e}", {})
    except Exception as e:
        last_error = LLMParsingError(str(e), {"attempt": "exception"})

    # Circuit Breaker 3회 소진 — 기본 의도로 fallback
    # 2026-04-29 (#264): warning → error 격상. Circuit Breaker 3회 소진은 LLM/하네스 이상 상태.
    fallback_reason = f"CIRCUIT_BREAKER: {last_error}"
    logger.error(f"[design] FAIL-LOUD: CIRCUIT_BREAKER 3회 소진 → 룰 기반 fallback. last_error={last_error}")
    # 2026-05-01 SSOT trace: Circuit Breaker fallback (LLM 호출 3회 모두 실패 시)
    _cat_for_trace = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(_cat_for_trace, dict):
        _cat_for_trace = _cat_for_trace.get("value", "기타")
    from app.categories import dump_category_trace
    dump_category_trace(
        stage="design.fallback_circuit_breaker",
        raw_brand_category=_cat_for_trace,
        eligible_count=len(eligible_objects),
        last_error=str(last_error),
    )
    category = brand_data.get("brand", {}).get("brand_category", "\uae30\ud0c0")
    if isinstance(category, dict):
        category = category.get("value", "\uae30\ud0c0")
    intents = _default_intents(eligible_objects, reference_points, category)
    if is_retry:
        intents = _merge_retry_intents(placed_objects, intents)
    intents = _enforce_placement_hints(intents, resolved_intents, reference_points)
    intents = _apply_global_direction(intents, state.get("global_direction_hint"))
    # 1-2 (#520 후속): sub_graph_reasons dump
    from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
    dump_agent_reason(state, node="design", decision="fallback",
                      reason="CIRCUIT_BREAKER",
                      context={
                          "last_error": str(last_error),
                          "eligible_count": len(eligible_objects),
                          "intents_generated": len(intents),
                          "is_retry": is_retry,
                      })
    return {
        "design_intents": intents, "eligible_objects": eligible_objects,
        "design_fallback_reason": fallback_reason,
        "prev_design_intents": state.get("design_intents") or [],
        "_review_iteration": state.get("_review_iteration", 0) + 1,
        "_reviewer_feedback": "",
    }


# ── 재호출 시 기배치 유지 + 실패분 병합 ─────────────────────────────────

def _merge_retry_intents(placed_objects: list, new_intents: list) -> list:
    """기배치(성공) intents 유지 + LLM이 재기획한 실패분 intents 합치기.

    placed_objects: 이전 라운드에서 성공한 배치 목록 (placement 결과)
    new_intents: LLM이 실패 오브젝트에 대해 새로 생성한 intents
    """
    # 기배치를 intent 형태로 변환 (placement 결과 → design intent)
    kept_intents = []
    for i, p in enumerate(placed_objects):
        kept_intents.append({
            "object_type": p.get("object_type", ""),
            "ref_point_id": p.get("anchor_key"),
            "zone_label": p.get("zone_label", "mid_zone"),
            "direction": p.get("direction", "wall_facing"),
            "alignment": "parallel",
            "priority": i + 1,
            "placed_because": p.get("placed_because", "기배치 유지"),
            # 1-2 (#520 후속): retry path 도 manual_label 보존 — placed obj 가 들고 있는 라벨
            # 그대로 들고 다음 라운드 design intent 로. placement 가 같은 라벨 eligible 와 재매칭.
            "manual_label": p.get("manual_label"),
        })

    # 신규 intents의 priority를 기배치 뒤로 밀기
    offset = len(kept_intents)
    for j, intent in enumerate(new_intents):
        intent["priority"] = offset + j + 1

    merged = kept_intents + new_intents
    return merged


# ── LLM 응답 object_type → eligible 키로 복원 ────────────────────────

def _remap_object_types(intents: list, valid_types: list[str]) -> list:
    """LLM이 이름을 바꿨을 때 원본 eligible 키로 복원.

    1차: 정확 매칭
    2차: 부분 문자열 매칭 (LLM이 줄인 경우)
    3차: 매칭 실패 시 원본 유지 (placement에서 skip됨)
    """
    valid_set = set(valid_types)
    remapped = []
    for intent in intents:
        ot = intent.get("object_type", "")

        if ot in valid_set:
            # 정확 매칭
            intent["object_type"] = ot
        else:
            # 부분 매칭: LLM이 "포토존"이라 줄였는데 eligible에 "포토존 배경 월"이 있는 경우
            matched = None
            for vt in valid_types:
                if ot in vt or vt in ot:
                    matched = vt
                    break
            if matched:
                logger.info(f"[design] remap: '{ot}' → '{matched}'")
                intent["object_type"] = matched
            else:
                logger.warning(f"[design] remap 실패: '{ot}' — eligible에 매칭 없음")

        remapped.append(intent)

    return remapped


# ── global_direction_hint 후처리 ─────────────────────────────────────

# flush 기물은 벽에 붙어야 하므로 방향 강제 적용 제외
_FLUSH_TYPES = {"shelf_wall", "shelf_standard", "shelf_3tier", "photo_wall", "partition_wall_I", "partition_wall_L"}


def _apply_global_direction(intents: list, global_dir: Optional[str]) -> list:
    """FULL_RELAYOUT 시 모든 non-flush 기물의 direction을 global_direction_hint로 덮어씌움."""
    if not global_dir:
        return intents

    from app.vmd_constants import VMD_WALL_ATTACHMENT
    flush_types = {ot for ot, att in VMD_WALL_ATTACHMENT.items() if att == "flush"}

    overridden = 0
    for intent in intents:
        obj_type = intent.get("object_type", "")
        if obj_type not in flush_types:
            intent["direction"] = global_dir
            overridden += 1

    if overridden:
        logger.info(f"[design] global_direction_hint='{global_dir}' → {overridden}개 direction 적용 (flush 제외)")
    return intents


# ── 오브젝트 타입별 선호 위치 (의미라벨 + direction) ─────────────────

# ── 오브젝트별 허용 direction + 선호 위치 ─────────────────────────────
# allowed_directions: LLM이 이 중에서 자유롭게 선택. fallback 시 첫 번째 사용.
# - wall_facing: 벽에 밀착 배치
# - center: 공간 중앙 (아일랜드)
# - inward: 벽에서 떨어져 안쪽으로
# - focal: 입구에서 잘 보이는 메인 위치

_OBJ_PREFERENCE = {
    "counter":        {"labels": ["deep_wall", "side_wall"], "allowed_directions": ["wall_facing", "inward"],           "alignment": "parallel"},
    "pos_counter":    {"labels": ["deep_wall", "side_wall"], "allowed_directions": ["wall_facing", "inward"],           "alignment": "parallel"},
    "character_bbox": {"labels": ["entrance_adjacent", "side_wall"], "allowed_directions": ["focal", "wall_facing"], "alignment": "parallel"},
    "photo_wall":     {"labels": ["side_wall", "deep_wall"], "allowed_directions": ["wall_facing", "focal"],            "alignment": "parallel"},
    "photo_island":   {"labels": ["center_freestanding", "entrance_adjacent"], "allowed_directions": ["focal", "center"], "alignment": "none"},
    "shelf_wall":     {"labels": ["side_wall"],             "allowed_directions": ["wall_facing", "inward"],           "alignment": "parallel"},
    "shelf_3tier":    {"labels": ["side_wall"],             "allowed_directions": ["wall_facing", "inward", "center"], "alignment": "parallel"},
    "display_table":  {"labels": ["center_freestanding", "side_wall"], "allowed_directions": ["center", "inward", "wall_facing"], "alignment": "none"},
    "banner_stand":   {"labels": ["entrance_adjacent"],     "allowed_directions": ["wall_facing", "focal", "center"], "alignment": "parallel"},
    # partition_wall (범용) 폐기 — flush+center_freestanding 모순. I/L만 사용.
    # 1-3 (#523) zones 제약 폐기 — agent 자율 영역. fallback (LLM 실패 시 룰 기반) path 에서도 zone 강제 X.
    # 단 partition_wall_L 은 코너 사각지대 의도 강함 → label deep_wall 우선 (zone 무관). 진규님 비전:
    # 위치 강제 X, 목적 위주 자율 판단. fallback 도 LLM 의도 가능한 한 살리되 룰 기반 default 시 무리한 zone 박지 않음.
    # (4-29 zones 명시 회귀 차단 → 1-3 자율 전환)
    "partition_wall_I": {"labels": ["side_wall", "deep_wall"],                              "allowed_directions": ["wall_facing", "inward"], "alignment": "perpendicular"},
    "partition_wall_L": {"labels": ["deep_wall"],                                            "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
}

_OBJ_DEFAULT_PREF = {"labels": ["side_wall", "center_freestanding"], "allowed_directions": ["center", "inward", "wall_facing", "focal"], "alignment": "none"}

# 2026-05-01 SSOT 마이그레이션: 카테고리별 우선 배치 오버라이드는 app.categories.Category.cat_overrides
# 로 이전. _default_intents 가 `get_category(key).cat_overrides` 로 lookup.
# Drift 방지 — 신규 카테고리 추가 시 categories.py 한 곳만 수정.


# ── Fallback 경로 자연어 매핑 (I-7 / 2026-04-23) ────────────────────
# design LLM 호출 스킵 시 _default_intents 가 placed_because 생성. 기존 dev 포맷
# "side_wall → photo_wall (wall_facing)" → 한글 자연어로 전환하여 FE 리포트
# 사용자 경험 보존. 본 매핑/헬퍼는 fallback 전용 (LLM 정상 경로 미영향).

_ZONE_KO: dict[str, str] = {
    "entrance_zone": "입구 구역",
    "mid_zone": "중간 구역",
    "deep_zone": "안쪽 구역",
}

_LABEL_KO: dict[str, str] = {
    "side_wall": "측면 벽",
    "deep_wall": "후면 벽",
    "center_freestanding": "매장 중앙",
    "entrance_adjacent": "입구 인접",
    "facing_entrance": "입구 정면",
}

_DIRECTION_KO: dict[str, str] = {
    "wall_facing": "벽 부착",
    "center": "중앙 아일랜드형",
    "inward": "매장 안쪽 지향",
    "focal": "시선 집중 지점",
}


def _ko_object_name(object_type: str) -> str:
    """OBJECT_STANDARDS 에서 한글명 조회. 미등록이면 raw object_type 반환."""
    std = OBJECT_STANDARDS.get(object_type)
    if std and "name" in std:
        return std["name"]
    return object_type


def _build_fallback_placed_because(
    object_type: str, zone_label: str, label: str, direction: str
) -> str:
    """Fallback 경로 배치 사유를 한글 자연어로 생성.

    예시:
      (counter, deep_zone, deep_wall, wall_facing)
        → "안쪽 구역의 후면 벽에 계산대 배치 — 벽 부착"
      (display_table, mid_zone, center_freestanding, center)
        → "중간 구역의 매장 중앙에 진열대 배치 — 중앙 아일랜드형"
      ref_point 매칭 실패 (zone/label 모두 빈 값):
        → "배너 기본 배치 — 시선 집중 지점"
    """
    name_ko = _ko_object_name(object_type)
    dir_ko = _DIRECTION_KO.get(direction, direction)
    zone_ko = _ZONE_KO.get(zone_label, zone_label) if zone_label else ""
    label_ko = _LABEL_KO.get(label, label) if label else ""

    if zone_ko and label_ko:
        return f"{zone_ko}의 {label_ko}에 {name_ko} 배치 — {dir_ko}"
    if zone_ko:
        return f"{zone_ko}에 {name_ko} 배치 — {dir_ko}"
    return f"{name_ko} 기본 배치 — {dir_ko}"


def _default_intents(eligible_objects: list, reference_points: list = None, category: str = "\uae30\ud0c0") -> list:
    """LLM 실패 시 기본 배치 의도 — 의미라벨 기반 매칭."""
    rps = reference_points or []

    # 의미라벨별 ref_point 그룹핑
    label_rps: dict[str, list] = {}
    for rp in rps:
        lbl = rp.get("label", "side_wall")
        label_rps.setdefault(lbl, []).append(rp)

    # 사용 추적 (같은 ref_point 중복 배치 방지)
    used_rp_ids: set = set()

    # 카테고리 오버라이드 — SSOT (app.categories) lookup. 미등록 카테고리 → 빈 dict.
    from app.categories import get_category
    cat_overrides = get_category(category).cat_overrides

    def _pick_rp_by_label(
        preferred_labels: list[str],
        allowed_zones: list[str] | None = None,
    ) -> tuple[str | None, dict | None]:
        """선호 라벨 순서대로 미사용 ref_point 탐색.

        매칭 실패 시 (None, None) 반환 — placement.py 가 zone 기준 fallback 처리.
        2026-04-29: 부적합 매칭(예: counter 가 banner 자리 잡거나 fitting_room 이 좁은 벽 잡음)
        차단 위해 Shin 04-09 의 loose fallback (선호 실패 → 아무 미사용 ref) 제거.
        2026-04-29 (가벽 entrance_zone fix): allowed_zones 파라미터 추가. ref_point 의
        label 과 zone_label 이 디커플 (label=거리 ratio 기준, zone_label=walk_mm 기준) 이라
        label=side_wall + zone=entrance_zone 인 ref 가 발생 가능. partition_wall_I/L 같이
        zone 제약이 강한 객체는 _OBJ_PREFERENCE 의 zones 명시로 차단.
        """
        for lbl in preferred_labels:
            for rp in label_rps.get(lbl, []):
                if rp["id"] in used_rp_ids:
                    continue
                if allowed_zones and rp.get("zone_label") not in allowed_zones:
                    continue
                used_rp_ids.add(rp["id"])
                return rp["id"], rp
        return None, None

    intents = []
    for i, obj in enumerate(eligible_objects):
        ot = obj["object_type"]

        # 카테고리 오버라이드 → 타입별 기본 → 전체 기본
        pref = cat_overrides.get(ot) or _OBJ_PREFERENCE.get(ot) or _OBJ_DEFAULT_PREF

        ref_id, rp = _pick_rp_by_label(pref["labels"], pref.get("zones"))
        zone = rp.get("zone_label", "mid_zone") if rp else "mid_zone"
        label = rp.get("label", "") if rp else ""

        # allowed_directions의 첫 번째를 기본 direction으로 사용
        directions = pref.get("allowed_directions", ["center"])
        direction = directions[0]

        intents.append({
            "object_type": ot,
            "ref_point_id": ref_id,
            "zone_label": zone,
            "direction": direction,
            "alignment": pref["alignment"],
            "priority": i + 1,
            "placed_because": _build_fallback_placed_because(ot, zone, label, direction),
            # 1-2 (#520 후속): fallback path 도 manual_label 보존 — eligible obj 가 brand 매뉴얼
            # 출신이면 그 라벨 그대로 inherit. placement 단계에서 1:1 매칭 가능하게.
            "manual_label": obj.get("manual_label"),
        })

    logger.info(f"[design] fallback intents: {[(i['object_type'], i['ref_point_id'], i['direction']) for i in intents]}")
    return intents


def _build_ref_analysis_text(ref_analysis: dict) -> str:
    """Vision 분석 결과 → 프롬프트 텍스트. 비어있으면 빈 문자열.

    1-3 후속 (B1, #533): ref 활용도 강화. 5-7 라이브에서 design intents 9개 중 ref 인용 1개만 — P 룰 / 카테고리 시퀀스 우선.
    Fix:
      - 모든 분석 필드 출력 (이전 누락: composition_principle / space_mood)
      - 명령형 강화 ("참고하세요" → "본 매장 design intent 에 직접 반영 + 각 intent placed_because 에 인용")
      - 끝에 "인용 강제" 명시
    """
    if not ref_analysis:
        return ""

    sections = []
    sections.append("## ★ 레퍼런스 이미지 분석 결과 (본 매장 design 의 1차 영감 source)")
    sections.append(
        "비슷한 카테고리 팝업스토어의 Vision 분석 결과입니다. **본 매장 design intent 에 직접 반영하세요** — "
        "단순 \"참고\" 가 아니라 layout_patterns / focal_points / composition_principle / space_mood "
        "를 본 매장 컨텍스트에 맞게 변환해 적용. P1~P4 / R 룰과 동등 또는 더 높은 우선순위로 따를 것."
    )

    patterns = ref_analysis.get("layout_patterns", [])
    if patterns:
        sections.append("\n### 배치 패턴 (layout_patterns) — 가구 배열 / 그룹핑 / 동선 형성 방식")
        for p in patterns:
            sections.append(f"- {p}")

    partitions = ref_analysis.get("partition_usage", [])
    if partitions:
        sections.append("\n### 가벽/파티션 활용 (partition_usage)")
        for p in partitions:
            sections.append(f"- {p}")

    focal = ref_analysis.get("focal_points", [])
    if focal:
        sections.append("\n### 시선 집중 포인트 (focal_points) — visual magnet 위치 / 종류")
        for f in focal:
            sections.append(f"- {f}")

    flow = ref_analysis.get("flow_description", "")
    if flow:
        sections.append(f"\n### 동선 흐름 (flow_description)\n{flow}")

    density = ref_analysis.get("density_impression", "")
    if density:
        sections.append(f"\n### 밀도감 (density_impression)\n{density}")

    composition = ref_analysis.get("composition_principle", "")
    if composition:
        sections.append(f"\n### 구성 원리 (composition_principle) — 대칭/비대칭 / 중앙집중/분산\n{composition}")

    mood = ref_analysis.get("space_mood", "")
    if mood:
        sections.append(f"\n### 공간 분위기 (space_mood)\n{mood}")

    highlights = ref_analysis.get("design_highlights", [])
    if highlights:
        sections.append("\n### 디자인 하이라이트 (design_highlights)")
        for h in highlights:
            sections.append(f"- {h}")

    sections.append(
        "\n### ★ 강제 룰 (B1 — ref 활용 강화)\n"
        "- 위 분석 결과를 본 매장 design intent 에 **직접 반영**. 단순 첨부 X.\n"
        "- 각 design intent 의 `placed_because` 에 **위 layout_patterns / focal_points / composition_principle 중 1개 이상 인용**. "
        "예: \"레퍼런스의 '벽면을 따라 선반 3개 연속 배치' 패턴 반영해 좌측벽 mid_zone 에 shelf_wall 배치\".\n"
        "- 본 매장 매뉴얼 / 카테고리 / 도면 컨텍스트와 **상충하면 매뉴얼 우선** (ref 는 영감 source, 본 매장 의도가 최종 결정자).\n"
        "- ref 가 본 매장 도면 / 매뉴얼과 매우 다르면 (예: 면적 차이 큼) 유연하게 적용. 무리한 복사 X."
    )

    return "\n".join(sections)


def _build_density_guide(density_ratio: float) -> str:
    """슬라이더 밀도 비율 → LLM용 배치 밀도 가이드 텍스트."""
    pct = int(density_ratio * 100)

    if density_ratio <= 0.15:
        mood = "매우 여유로운"
        guide = (
            "핵심 오브젝트(캐릭터, 계산대, 포토존)만 배치하세요.\n"
            "넓은 동선과 여백을 유지하고, 개방감을 살리세요."
        )
    elif density_ratio <= 0.25:
        mood = "여유로운"
        guide = (
            "핵심 오브젝트를 우선 배치하고, 필요한 곳에만 선반/진열대를 추가하세요.\n"
            "동선이 넉넉하게 느껴지도록 배치하세요."
        )
    elif density_ratio <= 0.40:
        mood = "적절한"
        guide = (
            "공간 전체를 고르게 활용하세요.\n"
            "중앙에 아일랜드 진열대 1~2개를 추가하고, 동선을 확보하세요."
        )
    elif density_ratio <= 0.55:
        mood = "밀도 높은"
        guide = (
            "공간을 적극적으로 활용하세요.\n"
            "중앙에도 진열대/테이블을 2~3개 아일랜드 배치하세요.\n"
            "동선은 최소 900mm만 유지하면 됩니다."
        )
    else:
        mood = "빽빽한"
        guide = (
            "가능한 모든 공간을 오브젝트로 채우세요.\n"
            "중앙에도 진열대를 최대한 넣으세요.\n"
            "동선은 최소 기준(900mm)만 확보하세요."
        )

    return (
        f"## 공간 밀도 가이드\n"
        f"밀도 설정: {pct}% — {mood} 배치\n"
        f"{guide}"
    )


def _build_ref_points_summary(reference_points: list, max_count: int = 20, structural_dead_zones: list = None, static_cache=None) -> str:
    """reference_points → Agent 3용 요약 텍스트. 토큰 절약을 위해 max_count개로 제한."""
    if not reference_points:
        return "(없음)"

    # 벽면 ref_point 우선 + center/interior 보충 (토큰 절약)
    wall_rps = [rp for rp in reference_points if not rp.get("label", "").startswith("center")]
    center_rps = [rp for rp in reference_points if rp.get("label", "").startswith("center")]
    selected = wall_rps[:max_count]
    remaining = max_count - len(selected)
    if remaining > 0:
        selected.extend(center_rps[:remaining])
    reference_points = selected

    # 바닥 bbox로 좌/우/후면 벽 판별 기준 계산
    all_coords = [rp.get("coord", [0, 0]) for rp in reference_points if rp.get("coord")]
    if all_coords:
        xs = [c[0] for c in all_coords]
        ys = [c[1] for c in all_coords]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_margin = (x_max - x_min) * 0.15  # 15% 이내면 해당 벽
        y_margin = (y_max - y_min) * 0.15
    else:
        x_min = x_max = y_min = y_max = 0
        x_margin = y_margin = 500

    def _wall_side(coord):
        """좌표 기반 벽 위치 라벨 — 좌측벽/우측벽/후면벽/입구측벽"""
        x, y = coord
        tags = []
        if x <= x_min + x_margin:
            tags.append("좌측벽")
        if x >= x_max - x_margin:
            tags.append("우측벽")
        if y <= y_min + y_margin:
            tags.append("후면벽")
        if y >= y_max - y_margin:
            tags.append("입구측벽")
        return "/".join(tags) if tags else ""

    lines = []
    for rp in reference_points:
        rp_id = rp["id"]
        zone = rp.get("zone_label") or "미정"
        label = rp.get("label", "")
        wall_len = rp.get("wall_length_mm", 0)
        coord = rp.get("coord", [0, 0])

        # 벽 위치 태그 추가 (좌측벽/우측벽/후면벽 + entrance_side)
        wall_side = _wall_side(coord)
        entrance_side = rp.get("entrance_side")
        entrance_side_ko = {"right": "입구오른쪽", "left": "입구왼쪽", "center": "입구정면"}.get(entrance_side or "", "")
        line = f"- {rp_id}: {zone}"
        side_tags = [t for t in [entrance_side_ko, wall_side] if t]
        if side_tags:
            line += f" ({'/'.join(side_tags)})"

        # 의미 라벨 → 정성적 설명 (Shin 방식)
        if label == "entrance_adjacent":
            line += " (입구 측 벽 — 집기 배치 주의)"
        elif label == "facing_entrance":
            line += " (입구 맞은편 벽 — 정면 노출 최적)"
        elif label == "deep_wall":
            line += " (안쪽 깊숙한 벽)"
        elif label == "side_wall":
            line += " (측면 벽)"
        elif label == "inner_wall":
            line += " (내벽/가벽)"
        elif "center" in label:
            line += " (중앙 자유 공간 — 아일랜드 배치 가능)"

        # 벽 크기 라벨 + 가용 길이
        if wall_len > 0:
            if wall_len > 3000:
                line += f" [넓은 벽]"
            elif wall_len > 1500:
                line += f" [보통 벽]"
            else:
                line += f" [좁은 벽]"

            # 벽면 가용 길이 — static_cache(데드존+동선버퍼)를 뺀 최대 연속 길이  ← static_cache param
            avail_len = wall_len  # 기본값: 벽 전체
            wall_ls = rp.get("wall_linestring")
            if wall_ls and static_cache:
                try:
                    remaining = wall_ls.difference(static_cache.buffer(100))  # 100mm 여유
                    from shapely.geometry import MultiLineString, LineString as _LS
                    if remaining.is_empty:
                        avail_len = 0
                    elif isinstance(remaining, _LS):
                        avail_len = int(remaining.length)
                    elif isinstance(remaining, MultiLineString):
                        avail_len = int(max(seg.length for seg in remaining.geoms))
                    else:
                        avail_len = int(remaining.length)
                except Exception:
                    pass  # 기하 연산 실패 시 원본 길이 유지

            if avail_len < wall_len:
                line += f" [가용 {avail_len}mm / 전체 {wall_len}mm]"
                if avail_len < 1200:
                    line += " [주의: 대형 기물 배치 불가]"

            # 벽 수용량 추정 (가용 길이 기준)
            shelf_cap = max(0, avail_len // 1800)
            display_cap = max(0, avail_len // 1200)
            if shelf_cap > 0 or display_cap > 0:
                line += f"\n    수용 가능: shelf_wall 최대 {shelf_cap}개 / display_table 최대 {display_cap}개"
            else:
                line += f"\n    수용 가능: 대형 기물 없음 (소형만 가능)"

        # 구조물 dead zone 근접 경고 — bbox 확장 범위(벽 길이 + 오브젝트 크기) 고려
        if structural_dead_zones:
            coord = rp.get("coord")
            if coord:
                import math
                DZ_TYPE_LABEL = {
                    "pillar": "기둥", "toilet": "화장실", "stair": "계단",
                    "core": "코어", "core_access": "계단 입구 감압구역",
                }
                # 벽 따라 뻗는 최대 범위 = 벽 길이/2 또는 최소 1500mm
                check_radius = max(wall_len / 2 if wall_len > 0 else 1500, 1500) + 1200  # +1200: 대형 기물 반폭
                for dz_entry in structural_dead_zones:
                    dz_poly = dz_entry["poly"]
                    dz_type = dz_entry["type"]
                    # polygon 경계까지 최단 거리 (centroid가 아닌 실제 거리)
                    from shapely.geometry import Point as _Pt
                    dist = dz_poly.distance(_Pt(coord[0], coord[1]))
                    if dist < check_radius:
                        label = DZ_TYPE_LABEL.get(dz_type, "구조물")
                        if dz_type == "core_access":
                            # 계단 입구 감압구역 — 소방법 기준 모든 기물 배치 절대 금지
                            line += f"\n    [금지] {label} {dist:.0f}mm — 모든 기물 배치 절대 금지 (소방법 1500mm 감압구역)"
                            rp["_all_blocked"] = True
                        else:
                            line += f"\n    [주의] {label} {dist:.0f}mm — photo_wall/shelf_wall 배치 금지"
                            rp["_large_blocked"] = True

        lines.append(line)

    return "\n".join(lines)


def _build_layout_examples_text(layout_examples: list) -> str:
    """이전 성공 배치 예시 → 프롬프트 텍스트 (Shin 방식)."""
    if not layout_examples:
        return ""

    text = "\n## 이전 성공 배치 참고\n"
    for i, ex in enumerate(layout_examples, 1):
        area = ex.get("floor_area_sqm", ex.get("usable_area_sqm", "?"))
        category = ex.get("category", "")
        placed = ex.get("placed_objects", ex.get("layout_objects", []))
        text += f"- 예시{i}: {area}㎡ {category} 공간, 오브젝트 {len(placed)}개\n"
        for obj in placed[:5]:
            ot = obj.get("object_type", "?")
            # layout_*.json 은 정본 네이밍 사용 (anchor_key). 현재 레퍼런스 JSON 없음 (dead path).
            ref = obj.get("anchor_key", "?")
            direction = obj.get("direction", "?")
            text += f"  · {ot} → {ref} ({direction})\n"
    text += "위 예시를 참고하되, 현재 공간 조건에 맞게 조정하세요.\n"
    return text


# ── 매뉴얼 명시 별도 의도 라벨 (1-2 #520 후속) ──────────────────────────
# brand 매뉴얼이 같은 std_id 를 별도 manual_label 로 명시한 경우 (예: counter "POS 카운터" + "증정품 카운터"),
# design LLM 이 std_id 만 보고 1개 intent 로 합치는 회귀를 차단. multi-label std_id 1건 이상일 때만 섹션 inject.

def _build_manual_label_section(eligible_objects: list) -> str:
    """매뉴얼 명시 manual_label 분리 보존 안내 섹션. multi-label std_id 없으면 빈 문자열."""
    from collections import defaultdict
    label_map: dict[str, list[str]] = defaultdict(list)
    for o in eligible_objects:
        ml = o.get("manual_label")
        if ml:
            label_map[o["object_type"]].append(ml)

    multi_label = {ot: labels for ot, labels in label_map.items() if len(set(labels)) >= 2}
    if not multi_label:
        return ""

    lines = ["", "## 매뉴얼 명시 별도 의도 (의미적으로 다른 기능 — 반드시 분리)"]
    lines.append(
        "아래 object_type 은 같은 std_id 이지만 브랜드 매뉴얼이 의미적으로 다른 기능 / 역할로 명시한 인스턴스입니다. "
        "**같은 object_type 이라고 다 같은 기능이 아님** — 라벨이 다르면 동선 / 위치 / 사용 맥락이 다릅니다.\n\n"
        "**원칙:**\n"
        "1. 매뉴얼 라벨을 **그대로 manual_label 필드에 복사**. 임의로 새 라벨 (매뉴얼에 없는 일반 용어 / 추상 표현) 만들지 말 것.\n"
        "2. 별도 intent 로 분리 — 1개 intent 로 합치거나 모두 같은 zone / direction 에 단순 중복 배치 금지.\n"
        "3. 각 intent 의 zone / direction / 사유 결정은 **해당 매뉴얼 라벨의 의미** + brand 카테고리 / 매장 컨텍스트 종합. 일반론 추측 금지. 매뉴얼 작성자 의도를 우선 반영.\n"
        "4. 라벨 의미 단서 부족 시 매뉴얼 placement_rules 의 description / 기타 필드 참고. 단서 없으면 보수적으로 별도 zone / 인접 ref_point 분리 정도.\n"
        "5. 라벨은 placed_because 자유 서술에도 표기 권장 (사유 추적성)."
    )
    lines.append("\n현재 도면 매뉴얼 명시 라벨:")
    for ot, labels in multi_label.items():
        unique_labels = sorted(set(labels))
        lines.append(f"- {ot}: {len(unique_labels)}개 별도 기능 — {', '.join(unique_labels)}")
    return "\n".join(lines) + "\n"


# ── wall_attachment → LLM 프롬프트 텍스트 ─────────────────────────────────

_ATTACH_KO = {"flush": "벽 밀착", "near": "벽 근접", "free": "자유 배치", "either": "벽/자유 모두 가능"}


def _build_wall_attachment_text(eligible_objects: list) -> str:
    """eligible_objects의 wall_attachment → Agent 3용 텍스트."""
    seen = {}
    for obj in eligible_objects:
        ot = obj["object_type"]
        if ot not in seen:
            attach = obj.get("wall_attachment", "free")
            seen[ot] = attach

    if not seen:
        return "(없음)"

    lines = []
    for ot, attach in seen.items():
        ko = _ATTACH_KO.get(attach, attach)
        if attach == "flush":
            lines.append(f"- {ot}: {ko} → 벽면 ref_point에 배치하세요")
        elif attach == "free":
            lines.append(f"- {ot}: {ko} → 중앙 또는 벽면 어디든 가능")
        else:
            lines.append(f"- {ot}: {ko}")

    return "\n".join(lines)


# ── pair rules → LLM 프롬프트 텍스트 ─────────────────────────────────────

_RELATION_KO = {"join": "밀착 가능", "separate": "분리 필수", "adjacent": "근접 배치 권장"}


def _build_pair_rules_text(pair_rules: list) -> str:
    """pair_rules → Agent 3용 자연어 텍스트."""
    if not pair_rules:
        return "(없음)"

    lines = []
    for rule in pair_rules:
        a = rule.get("object_a", "?")
        b = rule.get("object_b", "?")
        rel = rule.get("relation", "?")
        rel_ko = _RELATION_KO.get(rel, rel)
        gap = rule.get("min_gap_mm", 0)

        if rel == "join":
            lines.append(f"- {a} ↔ {b}: {rel_ko} (join_with로 지정하세요)")
        elif rel == "separate":
            lines.append(f"- {a} ↔ {b}: {rel_ko} (최소 {gap}mm 간격)")
        else:
            lines.append(f"- {a} ↔ {b}: {rel_ko}")

    return "\n".join(lines)


# ── Circuit Breaker (buildup/schemas.py) ─────────────────────────────────

_COORD_KEYS = re.compile(r'"(center_x|center_y|x_px|y_px)"')


def _has_coordinate_injection(intents: list) -> bool:
    """LLM 출력에 px/절대좌표 값이 섞여 있으면 True.

    ref_point_id, placed_because의 mm 숫자는 허용 (오탐 방지).
    """
    raw = json.dumps(intents)

    # 절대 좌표 키 탐지 (x_mm, y_mm는 ref_point가 아닌 직접 좌표일 때만)
    if _COORD_KEYS.search(raw):
        return True

    # intent에 x_mm/y_mm 키가 직접 들어있으면 주입
    for intent in intents:
        if "x_mm" in intent or "y_mm" in intent:
            return True

    return False


# ── zone_hint / wall_hint 후처리 강제 ────────────────────────────────────

_ZONE_ADJACENCY_ORDER = {
    "entrance_zone": ["entrance_zone", "mid_zone", "deep_zone"],
    "mid_zone": ["mid_zone", "entrance_zone", "deep_zone"],
    "deep_zone": ["deep_zone", "mid_zone", "entrance_zone"],
}

_ENTRANCE_ZONE_PREFERRED_LABELS = {"entrance_adjacent", "interior_entrance", "center_entrance_area"}


def _enforce_placement_hints(intents: list, resolved_intents: list, reference_points: list) -> list:
    """resolved_intents의 zone_hint / wall_hint를 design_intents에 강제 적용.

    LLM이 P1~P4 원칙을 우선시해 zone 제약을 무시했을 때 ref_point와 zone_label을 교정.
    """
    if not resolved_intents or not reference_points:
        return intents

    # obj_type → {zone_hint, wall_hint} (add 액션만)
    hint_map: dict[str, dict] = {}
    for ri in resolved_intents:
        if ri.get("action") != "add":
            continue
        obj_type = ri.get("object_type", "")
        zone_hint = ri.get("zone_hint")
        wall_hint = ri.get("wall_hint")
        if zone_hint or wall_hint:
            hint_map[obj_type] = {"zone_hint": zone_hint, "wall_hint": wall_hint}

    if not hint_map:
        return intents

    rp_map = {rp["id"]: rp for rp in reference_points}

    # zone별 사용 가능한 ref_points (blocked 제외)
    zone_rps: dict[str, list] = {}
    for rp in reference_points:
        if rp.get("_is_blocked") or rp.get("_all_blocked"):
            continue
        zone = rp.get("zone_label") or "mid_zone"
        zone_rps.setdefault(zone, []).append(rp)

    # 이미 올바른 zone에 배치된 intents의 ref_point_id → 보호 (교체 대상에서 제외)
    correctly_placed_rp_ids: set = set()
    for intent in intents:
        obj_type = intent.get("object_type", "")
        hints = hint_map.get(obj_type)
        if not hints or not hints.get("zone_hint"):
            continue
        rp_id = intent.get("ref_point_id")
        if rp_id and rp_map.get(rp_id, {}).get("zone_label") == hints["zone_hint"]:
            correctly_placed_rp_ids.add(rp_id)

    # 전체 사용 중인 ref_point_ids
    all_used_rp_ids: set = {i.get("ref_point_id") for i in intents if i.get("ref_point_id")}

    for intent in intents:
        obj_type = intent.get("object_type", "")
        hints = hint_map.get(obj_type)
        if not hints:
            continue

        required_zone = hints.get("zone_hint")
        required_wall = hints.get("wall_hint")

        current_rp_id = intent.get("ref_point_id")
        current_rp = rp_map.get(current_rp_id) if current_rp_id else None

        zone_ok = (not required_zone) or (current_rp and current_rp.get("zone_label") == required_zone)
        wall_ok = (not required_wall) or (current_rp and current_rp.get("entrance_side") == required_wall)

        if zone_ok and wall_ok:
            continue

        # 올바른 ref_point 탐색 (정확한 zone → 인접 zone 순)
        zone_order = _ZONE_ADJACENCY_ORDER.get(required_zone or "mid_zone", ["mid_zone"])

        chosen = None
        for zone in zone_order:
            candidates = [
                rp for rp in zone_rps.get(zone, [])
                if rp["id"] not in correctly_placed_rp_ids
                and (rp["id"] not in all_used_rp_ids or rp["id"] == current_rp_id)
            ]
            if required_wall:
                wall_matches = [rp for rp in candidates if rp.get("entrance_side") == required_wall]
                if wall_matches:
                    candidates = wall_matches

            # entrance_zone은 입구 인접 label 선호
            if zone == "entrance_zone":
                preferred = [rp for rp in candidates if rp.get("label") in _ENTRANCE_ZONE_PREFERRED_LABELS]
                if preferred:
                    candidates = preferred

            if candidates:
                # 현재 ref_point가 후보에 포함되면 교체 불필요
                current_ids = {c["id"] for c in candidates}
                if current_rp and current_rp["id"] in current_ids:
                    chosen = current_rp
                else:
                    chosen = candidates[0]
                break

        if chosen and chosen["id"] != current_rp_id:
            if current_rp_id:
                all_used_rp_ids.discard(current_rp_id)
            all_used_rp_ids.add(chosen["id"])
            old_zone = current_rp.get("zone_label") if current_rp else "없음"
            intent["ref_point_id"] = chosen["id"]
            intent["zone_label"] = chosen.get("zone_label") or required_zone
            logger.info(
                f"[design:hint_enforce] {obj_type}: {current_rp_id}({old_zone})"
                f" → {chosen['id']}({chosen.get('zone_label')})"
                + (f" [zone:{required_zone}]" if required_zone else "")
                + (f" [wall:{required_wall}]" if required_wall else "")
            )
        elif required_zone:
            # 적합 ref_point 없음 — zone_label만 보정해 placement가 같은 zone에서 탐색하게 함
            intent["zone_label"] = required_zone
            logger.warning(
                f"[design:hint_enforce] {obj_type}: {required_zone} ref_point 없음 "
                f"— zone_label 보정만 적용"
            )

    return intents
