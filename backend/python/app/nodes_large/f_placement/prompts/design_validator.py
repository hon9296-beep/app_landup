"""design_validator 프롬프트 — large 전용 (2026-05-06 신설).

design (영역별 가구 의도) + placement (실제 배치 좌표) 둘 다 검증하는 검증 LLM.
3노드 패턴 (작업 → 검증 → 수정) 의 검증 단계.

흐름:
  design (LLM) → placement (코드) → design_validator (LLM, 신규) → verdict
    ├─ ok → keywords_gen 등 다음 노드
    └─ fix_needed + retry < N → design_fix (LLM, 신규) → placement 재실행 → 다시 design_validator

검증 룰 = design 1차 prompt 의 5태그 #강제 / #금지 동기화 (concept_area 패턴 정합).
"""


# ── 판정 기준 list (확장 포인트) ───────────────────────────────────────
# 새 기준 추가 = 아래 list 에 dict 한 개 추가하면 prompt + tool schema 자동 갱신.
DESIGN_VALIDATION_RULES = [
    {
        "key": "ref_citation",
        "label": "ref 패턴 인용 형식",
        "question": "design intent 의 placed_because 가 [<field>: <패턴>] 형식으로 ref_analysis 패턴을 인용하는가? (ref 있을 시)",
    },
    {
        "key": "object_diversity",
        "label": "오브젝트 다양성",
        "question": "한 종류만 박힌 게 아니라 다양한 object_type 이 사용됐는가? (display_table N개만 X)",
    },
    {
        "key": "wall_balance",
        "label": "벽면 / 중앙 균형",
        "question": "direction 이 wall_facing 한 종류로 쏠리지 않고 center / inward / focal 도 적절히 쓰였는가?",
    },
    {
        "key": "area_object_match",
        "label": "영역 - 오브젝트 매칭",
        "question": "각 가구가 자신의 concept_area 와 적합한가? (예: 결제 영역에 photo_wall X)",
    },
    {
        "key": "entrance_appropriate",
        "label": "입구 주변 적합 가구",
        "question": "입구 가까운 가구가 첫인상 영역 (포토 / 체험 / 캐릭터) 인가? (선반 / 결제 카운터 X)",
    },
    {
        "key": "placement_success",
        "label": "배치 성공률",
        "question": "design intent 중 실제 배치 성공률이 70% 이상인가? (failed_objects 비율 ≤ 30%)",
    },
    {
        "key": "same_object_adjacent",
        "label": "굿즈판매/상영 영역 동일 오브젝트 인접 배치",
        "question": "굿즈판매 영역의 선반 (shelf_wall / shelf_3tier) 2개 이상이면 선반끼리 딱 붙어있는가? 상영 영역의 display_table 2개 이상이면 클러스터 묶음인가? 다른 영역은 검사 X.",
    },
]


# ── System prompt ────────────────────────────────────────────────────
DESIGN_VALIDATOR_SYSTEM = """당신은 팝업스토어 공간 배치의 검증 담당자입니다.
1차 design LLM 이 결정한 design intent + placement 단계가 박은 실제 배치 결과를 모두 받아,
아래 prompt 의 #강제 / #금지 룰 기반으로 검증합니다.

검증 흐름:
- design intent (영역별 가구 의도) + placed_objects (실제 배치 좌표) 둘 다 봄
- 각 #강제 / #금지 룰 위반 여부 판정 (DESIGN_VALIDATION_RULES key 별로 OK / WARN)
- 명백히 위반인 케이스만 WARN. 애매한 건 OK 로 분류 (자율도 우선).
- 좌표 자체는 받지 않고 자연어 위치 정보만으로 판정.

판정은 강제 차단이 아닌 권장 가이드 — OK / WARN 표시 + 자연어 사유."""


# ── User prompt template ─────────────────────────────────────────────
DESIGN_VALIDATOR_PROMPT_TEMPLATE = """## 태그 안내 (필수 — 아래 모든 # 태그의 의미)
- #강제 — design / placement 가 100% 따라야 할 룰. 위반 시 WARN.
- #권장 — **75% 강제성**. 부지/브랜드 특수성으로 어쩔 수 없는 위반만 OK. 사유 없는 위반 = WARN.
- #금지 — 100% 절대 X. 위반 시 WARN.
- #참조 — 정보성 데이터. 룰 X.
- #예외 — 특정 조건 (예: brand 매뉴얼 명시) 충족 시 #강제 / #금지 무시 가능.


## 공간 정보
- 면적: {area_sqm:.1f}㎡
- 입구 위치: {entrance_side}


## design intent (1차 LLM 출력)
{intents_description}


## placement 결과 (실제 배치 — 자연어 위치)
{placement_description}


## 검증 룰 (design 1차 prompt 와 동기화 — 같은 룰 기반 검증)

### 레퍼런스 활용
#강제
- ref_analysis 있으면 placed_because 에 [<field>: <패턴>] 형식 인용
#금지
- ref 있는데 [ref_없음] 박지 X
- placed_because 에 인용 형식 무시 X

### 오브젝트 다양성
#강제
- 다양한 object_type 사용 (한 종류만 X)
#금지
- 한 종류만 N개 박기 X (예: display_table 만 17개)

### 공간 활용 균형
#강제
- direction 다양화 (wall_facing 만 X)
#금지
- 모든 가구 wall_facing 만 = 외벽 쏠림 위반

### 영역 - 오브젝트 매칭
#강제
- 각 가구는 자신의 concept_area 와 적합한 종류
#금지
- 결제 영역에 photo_wall / 휴식 영역에 counter 같은 부적합 매칭 X

### 입구 주변 적합 가구
#강제
- 입구 가까운 가구 = 첫인상 영역 (포토 / 체험 / 캐릭터)
#금지
- 입구 가까이 선반 / 결제 카운터 박지 X

### 배치 성공률
#강제
- design intent 중 실제 배치 성공률 ≥ 70%
#금지
- 실패율 30% 초과 X (design intent 가 무리한 위치 박음)

### 굿즈판매/상영 영역 동일 오브젝트 인접 배치 (다른 영역은 검사 X)
#강제
- 굿즈판매: shelf_wall / shelf_3tier 2개 이상 → 선반끼리 딱 붙음 (사이 갭 X)
- 상영: display_table / banner_stand 2개 이상 → 같은 영역 클러스터 묶음
#금지
- 굿즈판매의 선반 사이에 갭 X
- 상영의 display_table 부지 양 끝 흩뿌리기 X


## 판정 항목
{validation_questions}


각 항목별로 OK / WARN 판정 + 자연어 사유 제출.
WARN 시 사유에 **위반 가구 / 위반 영역 + 어떻게 위반했는지** 구체 명시 (수정 LLM 이 정확히 fix 할 수 있게).
판정은 권장 가이드입니다. 강제 차단 아님."""


# ── Helper: prompt 텍스트 build ──────────────────────────────────────

def build_validation_questions_text() -> str:
    """DESIGN_VALIDATION_RULES → prompt 안 질문 list 텍스트."""
    lines = []
    for i, rule in enumerate(DESIGN_VALIDATION_RULES, 1):
        lines.append(f"{i}. {rule['label']}: {rule['question']}")
    return "\n".join(lines)


# ── Helper: Anthropic Tool use schema build ──────────────────────────

def build_tool_schema() -> dict:
    """DESIGN_VALIDATION_RULES → Anthropic Tool use schema (출력 형식 강제)."""
    properties = {
        "verdict": {
            "type": "string",
            "enum": ["ok", "fix_needed"],
            "description": (
                "전체 판정. WARN 가 1개 이상이고 명백히 문제 있으면 'fix_needed', "
                "OK 만 있거나 WARN 가 사소하면 'ok'. design_fix 노드 호출 트리거."
            ),
        },
    }
    required = ["verdict"]
    for rule in DESIGN_VALIDATION_RULES:
        key = rule["key"]
        properties[key] = {
            "type": "string",
            "enum": ["OK", "WARN"],
            "description": f"{rule['label']} 판정 — {rule['question']}",
        }
        properties[f"{key}_reason"] = {
            "type": "string",
            "description": f"{rule['label']} 판정 사유 (자연어 1-2 문장, WARN 시 구체 명시)",
        }
        required.append(key)
        required.append(f"{key}_reason")

    return {
        "name": "validate_design_layout",
        "description": "design intent + placement 결과의 룰 기반 검증 + 전체 verdict.",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
