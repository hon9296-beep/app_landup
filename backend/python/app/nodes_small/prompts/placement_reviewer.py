"""
placement_reviewer LLM prompt / Tool schema — #490 (design_reviewer 패턴 미러링).

design_reviewer (#474) 가 design_intents 단계 (좌표 결정 전) 만 검증하는 한계를
보완. placement 후 placed_objects + failed_objects + 좌표 기반 검증.

build_llm_tool_schema: overall_status / violations / feedback (design_reviewer 와 동일)
LLM_REVIEWER_SYSTEM: placement 후 sanity check 전문가
build_llm_user_prompt: placed + failed + 매뉴얼 명시 obj → user prompt 자연어 변환
"""


def build_llm_tool_schema() -> dict:
    """Anthropic Tool use schema — design_reviewer 와 동일 형식 (호환성)."""
    return {
        "name": "review_placement_result",
        "description": "placement 결과 anti-pattern 검토 — drop / slot 경쟁 / 통합 layout sanity 판정.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overall_status": {
                    "type": "string",
                    "enum": ["pass", "reject"],
                    "description": "전체 판정 — pass: 모든 룰 OK, reject: 1개 이상 위반",
                },
                "violations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string", "description": "위반 룰 ID (AP-401~)"},
                            "severity": {"type": "string", "enum": ["blocking", "warning"]},
                            "detail": {"type": "string", "description": "위반 사유 자연어 1-2 문장"},
                        },
                        "required": ["rule_id", "severity", "detail"],
                    },
                    "description": "위반 룰 list (없으면 빈 배열)",
                },
                "feedback": {
                    "type": "string",
                    "description": "design 재호출 시 inject 할 slot 양보 hint (위반 없으면 빈 문자열)",
                },
            },
            "required": ["overall_status", "violations", "feedback"],
        },
    }


LLM_REVIEWER_SYSTEM = """당신은 팝업스토어 배치 결과를 평가하고 **재기획 명령을 내리는 권한을 가진 design director** 입니다.
placement 후 placed_objects + failed_objects + 좌표를 받고, 의미적 합리성을 판정 + 부적합 시 design 재호출 (reject) 트리거.

[권한]
당신은 보수적 검토자가 아닙니다. **agent 자율 판단으로 양보 / 이동 / 띄움 / 붙임 결정 권한** 보유:
- "기존 placed obj 양보 받아 다른 곳 옮기기" (예: shelf_wall 이 photo_wall 자리 차지 → shelf_wall 을 mid_zone 으로 이동)
- "특정 obj 띄우기 / 벽 부착 강제" (예: photo_wall 이 standalone 으로 박힘 → 벽에 부착)
- "drop 된 매뉴얼 obj 가 우선" 결정 (manual_obj 살리기 위해 default obj 양보)
- "structural anchor 위치 재기획" (counter/photo_wall 의 zone 적합성 강제)

[판정 기준 — 적극적 reject (AP-405 5 케이스)]
다음 케이스는 **blocking 으로 reject** 권장 (warning 으로 통과 X):
(a) structural anchor (photo_wall / counter / partition_wall) 가 카테고리 / 동선 의미와 불일치 zone 에 박힘
  - 예: 뷰티 카테고리에서 photo_wall 이 mid_zone 단독 standalone (deep_zone magnet 역할 못 함)
  - 예: counter 가 entrance_zone 단독 (체험→상담→진열→결제 sequence 깨짐)
(b) placement.placed_because 가 'fallback_phase_X' — fallback 강제 끼워박힘 흔적 (벽 부착 못 한 standalone)
(c) 같은 zone 에 obj 폭증 (한쪽 zone 70% 이상 집중) / 다른 zone 0 — 동선 균형 깨짐
(d) 매뉴얼 명시 obj 가 drop 됐는데 default 풀 obj 가 그 자리 차지 (slot 양보 가능성 ↑)
(e) ref_analysis 정상인데 design intents 의 inspired_by_ref 거의 빈값 — ref 영감 무시. ref_analysis 자체 empty 면 skip.

[★ 가벽 그래픽 월 흡수 인정 룰 (AP-405-a 회귀 차단)]
**partition_wall_I/L 의 `graphic_face='outer'` 메타가 박혀있으면, 해당 가벽이 photo_wall 의 그래픽 / 시각 앵커 역할을 흡수한 상태**. 매장 자리 부족으로 photo_wall 이 별도 obj 로 placed 안 됐어도, 가벽이 그 역할 대체 → 매뉴얼 의도 충족됨.
- placed list 에 partition.graphic_face='outer' 인 가벽이 있고 photo_wall obj 가 없으면 → **drop 으로 판정 X**. 흡수 케이스로 인정 후 pass.
- 단 partition.graphic_face='none' (= 흡수 안 됨) 이고 photo_wall 도 없으면 → 진짜 drop. AP-405-a 적용.
- 본 룰은 진규님 5-8 명시 — "가벽이 구조물 + 포토존 동시 역할" 정공 흐름.

[판정 기준 — pass]
- 매뉴얼 의도 + 카테고리 sequence 일치
- structural anchor 가 의미적 위치 (deep_zone photo_wall / mid 또는 deep counter)
- 동선 균형

[reject 시 feedback 작성]
design 재호출에 inject 될 자연어 피드백 — **구체적 재기획 명령** 작성:
- "photo_wall 을 deep_zone 으로 이동. 현재 mid_zone 의 wall_X 차지한 shelf_wall 을 다른 ref_point 로 양보"
- "counter (POS) 를 entrance_zone 에서 deep_zone 으로 이동 — 결제 동선 끝점"
- "placed obj 의 wall_attachment 가 standalone 인 케이스: 벽 부착 ref_point 우선 매핑"
좌표 / mm 수치 절대 금지. zone / direction / 사유만.

[보수적 영역]
- 도메인 룰 (R1~R8) 또는 brand 매뉴얼 룰은 명시적 위반 시만 blocking. 모호 시 pass.
- 좌표 단위 충돌 / 거리는 이미 python validator 가 잡음. 의미 판단만 LLM 영역."""


def build_llm_user_prompt(state: dict, llm_rules: list[dict]) -> str:
    """placed + failed + 매뉴얼 명시 obj → LLM user prompt (자연어 변환)."""
    placed = state.get("placed_objects") or []
    failed = state.get("failed_objects") or []
    brand_data = state.get("brand_data") or {}
    placement_rules = brand_data.get("placement_rules") or []
    manual_obj_types = sorted({r.get("object_type") for r in placement_rules if isinstance(r, dict) and r.get("object_type")})

    # 매장 정보 자연어
    usable_poly = state.get("usable_poly")
    area_sqm = (usable_poly.area / 1_000_000) if usable_poly else 0
    all_entrances = state.get("all_entrances_mm") or []
    entrance_count = len(all_entrances) or 1
    venue_type = state.get("venue_type", "street_complex")
    brand_category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(brand_category, dict):
        brand_category = brand_category.get("value", "기타")

    # placed 자연어 변환 (개별 obj 자세히 — agent 가 양보/이동 판단할 정보 충분히)
    # 1-3 (#523 후속): zone group 에서 개별 obj detail 로 전환. ref_point / manual_label /
    # direction / wall_attachment / placed_because 를 보고 agent 가 재기획 결정 가능.
    placed_lines = []
    fallback_count = 0
    graphic_absorbed_count = 0
    for p in placed:
        if not isinstance(p, dict):
            continue
        ot = p.get("object_type", "?")
        manual = p.get("manual_label")
        anchor = p.get("anchor_key", "?")
        zone = p.get("zone_label", "?")
        direction = p.get("direction", "?")
        wall_att = p.get("wall_attachment", "?")
        because = (p.get("placed_because") or "")[:120]
        is_fallback = "fallback_phase" in because
        if is_fallback:
            fallback_count += 1
        flag = " [FALLBACK 강제 끼워박힘]" if is_fallback else ""
        label_str = f' (라벨: "{manual}")' if manual else ""
        # 2026-05-08: 가벽 그래픽 월 흡수 메타 표시 — AP-405-a 회귀 차단.
        # partition.graphic_face='outer' = photo_wall 역할 흡수. reviewer 가 drop 으로 판정 X.
        graphic_face = p.get("graphic_face")
        graphic_flag = ""
        if str(ot).startswith("partition_wall") and graphic_face == "outer":
            graphic_flag = " [★ photo_wall 흡수 — 가벽 외측면 = 포토존 역할 동시 수행]"
            graphic_absorbed_count += 1
        placed_lines.append(
            f"  - {ot}{label_str} @ {zone} / ref={anchor} / dir={direction} / attach={wall_att}{flag}{graphic_flag}"
        )
    placed_desc = "\n".join(placed_lines) or "  (placed_objects 비어있음)"
    if fallback_count > 0:
        placed_desc += f"\n  ※ FALLBACK 강제 끼워박힘 {fallback_count}건 — 벽 부착 의도 깨짐 가능성. 재기획 검토 권장."
    if graphic_absorbed_count > 0:
        placed_desc += (
            f"\n  ※ ★ 가벽 그래픽 월 흡수 {graphic_absorbed_count}건 — photo_wall 자리 부족으로 가벽 외측면이 포토존 역할 흡수. "
            f"매뉴얼 photo_wall 이 별도 obj 로 placed 안 됐어도 의도 충족됨 (drop 판정 X)."
        )

    # failed 자연어 (intent 의도 — placement 가 떨어뜨린 obj 의 본 zone/ref)
    failed_lines = []
    intents_by_type: dict = {}
    for i in (state.get("design_intents") or []):
        intents_by_type.setdefault(i.get("object_type", ""), []).append(i)
    for f in failed:
        if not isinstance(f, dict):
            continue
        ot = f.get("object_type", "?")
        reason = (f.get("reason") or "?")[:150]
        # 같은 type 의 intent 중 첫 번째의 의도 표시 (어디 가야 했는지)
        intent = (intents_by_type.get(ot) or [None])[0]
        intent_str = ""
        if intent:
            intent_str = f" [본 의도: zone={intent.get('zone_label')} / ref={intent.get('ref_point_id')} / dir={intent.get('direction')}]"
        failed_lines.append(f"  - {ot}{intent_str} (사유: {reason})")
    failed_desc = "\n".join(failed_lines) or "  (failed_objects 비어있음)"

    # 검토 룰
    rules_desc = "\n".join(
        f"- [{ap['id']}] ({ap['severity']}) {ap['description']}"
        for ap in llm_rules
    )

    return f"""## 매장 정보
- 면적: {area_sqm:.1f}㎡
- 입구 수: {entrance_count}
- 유형: {venue_type}
- 카테고리: {brand_category}

## 매뉴얼 명시 obj 풀 (배치 우선 순위)
{', '.join(manual_obj_types) or '(매뉴얼 placement_rules 비어있음)'}

## placement 결과 — placed (zone 별 group)
{placed_desc}

## placement 결과 — failed (drop 된 obj)
{failed_desc}

## 검토할 anti-pattern 룰 (LLM 영역)
{rules_desc}

위 룰 + 통합 layout 합리성 판정. 위반 시 rule_id + 자연어 사유 + design 재호출용 slot 양보 hint 작성.
drop 이 있고 매뉴얼 명시 obj 라면, 그 obj 가 가야 할 slot 을 점유한 다른 obj 가 양보할 수 있는지 판단해 hint 작성."""
