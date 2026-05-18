"""
design_reviewer LLM prompt / Tool schema — #491 prompts 중앙화.

build_llm_tool_schema: Anthropic Tool use schema (overall_status / violations / feedback)
LLM_REVIEWER_SYSTEM: system prompt (anti-pattern 검토 전문가)
build_llm_user_prompt: design_intents + 검토 룰 → user prompt 자연어 변환
"""


def build_llm_tool_schema() -> dict:
    """Anthropic Tool use schema — overall_status / violations / feedback 강제."""
    return {
        "name": "review_design_intents",
        "description": "design_intents 의 anti-pattern 검토 — OK/REJECT 판정 + 위반 사유.",
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
                            "rule_id": {"type": "string", "description": "위반 룰 ID (AP-XXX)"},
                            "severity": {"type": "string", "enum": ["blocking", "warning"]},
                            "detail": {"type": "string", "description": "위반 사유 자연어 1-2 문장"},
                        },
                        "required": ["rule_id", "severity", "detail"],
                    },
                    "description": "위반 룰 list (없으면 빈 배열)",
                },
                "feedback": {
                    "type": "string",
                    "description": "designer 재호출 시 inject 할 자연어 피드백 (위반 없으면 빈 문자열)",
                },
            },
            "required": ["overall_status", "violations", "feedback"],
        },
    }


LLM_REVIEWER_SYSTEM = """당신은 팝업스토어 배치 anti-pattern 검토 전문가입니다.
designer 가 결정한 design_intents (오브젝트 배치 의도) 를 받고, 명백한 오답 패턴을 검출합니다.

판정 원칙:
- 명백히 위반된 케이스만 reject (애매한 건 pass)
- 좌표 / 수치는 받지 않음 — 자연어 위치 정보만으로 판정
- 위반 시 자연어 사유 + designer 재호출용 자연어 피드백 작성
- 좌표 / mm 수치 출력 절대 금지 (BANNED_LLM_KEYS 차단)

[ref_analysis 활용도 검증 — 1-3 (#533) B1 추가]
ref_analysis 가 정상 (분석 결과 비어있지 않음) 인데 design_intents 의 inspired_by_ref 필드가
대부분 빈 문자열이면 ref 활용 부족 — design 이 영감 무시. warning 발화 권장.
- intent 절반 이상이 inspired_by_ref 빈 값 → "ref 활용 부족" warning
- inspired_by_ref 가 채워졌어도 ref_analysis 의 실제 항목 (layout_patterns / focal_points / flow_description / composition_principle) 인용 없으면 형식적 — warning
- 단 ref_analysis 자체가 empty (loader fail / analyzer skip) 인 경우는 검증 스킵 — pass"""


def build_llm_user_prompt(intents: list, state: dict, llm_rules: list[dict]) -> str:
    """design_intents + 검토 룰 → LLM user prompt (자연어 변환)."""
    # intents 자연어 변환
    intents_desc = []
    for i, intent in enumerate(intents, 1):
        obj_type = intent.get("object_type", "?")
        zone = intent.get("zone_label", "?")
        direction = intent.get("direction", "?")
        ref_id = intent.get("ref_point_id", "?")
        reason = intent.get("placement_reason") or intent.get("placed_because", "")[:80]
        intents_desc.append(f"{i}. {obj_type} (zone={zone}, dir={direction}, ref={ref_id}, 사유: {reason})")

    # 매장 정보 자연어
    usable_poly = state.get("usable_poly")
    area_sqm = (usable_poly.area / 1_000_000) if usable_poly else 0
    all_entrances = state.get("all_entrances_mm") or []
    entrance_count = len(all_entrances) or 1
    venue_type = state.get("venue_type", "street_complex")
    brand_data = state.get("brand_data") or {}
    brand_category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(brand_category, dict):
        brand_category = brand_category.get("value", "기타")

    # 1-2 (#520 후속): manual_label semantic context inject — AP-303 LLM 판단 영역.
    # multi-label std_id (예: counter "POS 카운터" + "증정품 카운터") 가 있을 때만 섹션 추가.
    # LLM 이 라벨의 의미적 기능 차이를 파악해 intents 의 zone/direction 매칭 적절성 판정.
    manual_labels_section = _build_manual_labels_review_section(state)

    # 검토 룰 목록
    rules_desc = "\n".join(f"- [{ap['id']}] ({ap['severity']}) {ap['description']}" for ap in llm_rules)

    return f"""## 매장 정보
- 면적: {area_sqm:.1f}㎡
- 입구 수: {entrance_count}
- 유형: {venue_type}
- 카테고리: {brand_category}

## design_intents (검토 대상)
{chr(10).join(intents_desc)}
{manual_labels_section}
## 검토할 anti-pattern 룰
{rules_desc}

위 룰을 기반으로 design_intents 검토. 위반 시 rule_id + 자연어 사유 + 재호출 피드백 작성."""


def _build_manual_labels_review_section(state: dict) -> str:
    """매뉴얼 명시 manual_label 의 의미적 분리 검증용 컨텍스트 섹션. multi-label std_id 0건이면 빈 문자열.

    AP-303 (LLM 판단 — manual_label semantic) 룰을 LLM 이 의미적으로 판정하도록 라벨 정보 inject.
    LLM 이 'POS 카운터' 와 '증정품 카운터' 의 기능 차이 (결제 vs 증정) 를 파악해 intents 가 그
    구분을 zone/direction 으로 반영했는지 판정.
    """
    brand_data = state.get("brand_data") or {}
    placement_rules = brand_data.get("placement_rules") or []
    if not placement_rules:
        return ""
    from collections import defaultdict
    labels_by_std: dict[str, set[str]] = defaultdict(set)
    for r in placement_rules:
        if not isinstance(r, dict):
            continue
        std_id = r.get("object_type", "")
        label = r.get("name") or r.get("label")
        if std_id and label and label != std_id:
            labels_by_std[std_id].add(label)
    multi_label = {ot: sorted(labels) for ot, labels in labels_by_std.items() if len(labels) >= 2}
    if not multi_label:
        return ""

    lines = ["", "## 매뉴얼 명시 별도 의도 (AP-303 의미적 분리 검증)"]
    for ot, labels in multi_label.items():
        lines.append(f"- {ot}: {len(labels)}개 별도 라벨 — {', '.join(labels)}")
    lines.append(
        "\n위 라벨들은 같은 std_id 이지만 **의미적 기능이 다른** 인스턴스입니다.\n\n"
        "**판정 기준 (AP-303)**:\n"
        "1. design_intents 가 매뉴얼 라벨마다 별도 intent 로 분리했는가? (1개로 합쳐졌으면 위반)\n"
        "2. 각 intent 의 manual_label 필드가 **매뉴얼 라벨과 글자 그대로 일치**하는가? (AI 가 임의로 만든 일반 용어 = 위반)\n"
        "3. 각 intent 의 zone / direction / 사유 가 매뉴얼 라벨의 **의미** + brand 카테고리 / 매장 컨텍스트에 부합하는가?\n"
        "   - 일반론 추측 (결제용 → deep_zone / 증정용 → entrance 같은 generic) 만으로 분리됐으면 의도 손실 가능.\n"
        "   - 매뉴얼 placement_rules 의 description / 기타 필드 단서 없으면 보수적으로 별도 zone 분리만 OK.\n"
        "4. 모두 같은 zone / direction 에 단순 중복 배치 = 의도 손실 — 위반."
    )
    return "\n" + "\n".join(lines) + "\n"
