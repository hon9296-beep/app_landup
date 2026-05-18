"""
layout_validator 프롬프트 — large 전용. 컨셉_영역 분할 검증.

디자인 친화적 노드 전략 Phase 1 정합 — prompt 를 노드 로직과 분리.
세부: docs/docs-shin/main_tasks/공통/2026-05-03_[프롬프트_노드]_영역_배치_검증.md

LAYOUT_VALIDATION_RULES list 에 dict 한 개 추가하면 prompt 텍스트 + tool schema 자동 갱신.
"""

# ── 판정 기준 list (확장 포인트) ───────────────────────────────────────
# 새 기준 추가 = 아래 list 에 dict 한 개 추가하면 끝.
# - key: state["concept_area_check"] 에 박힐 필드 이름 (영문)
# - label: LLM 답 / design inject 시 사용 라벨 (한국어)
# - question: LLM 한테 던질 질문 (한국어)
LAYOUT_VALIDATION_RULES = [
    # 2026-05-06: welcome_at_entrance 폐기 — 맞이존 default 폐기 (사용자 결정).
    # brand 매뉴얼에 입구 영역 명시 시 추후 동적 룰로 부활 가능.
    {
        "key": "checkout_distance",
        "label": "결제 거리",
        "question": "결제가 입구에 너무 가깝지 않나? (구매 동선 후미에 두는 게 통상)",
    },
    {
        "key": "flow_natural",
        "label": "동선 흐름",
        "question": "동선 흐름이 자연스러운가? (맞이 → 체험/포토 → 굿즈 → 결제)",
    },
    # 2026-05-05 TR_TH 트랙 1 (concept_area 3노드 패턴) — area_balance 신설.
    {
        "key": "area_balance",
        "label": "영역 면적 균형",
        "question": "한 영역이 너무 크거나 작아 불균형하지 않은가? (예: 60% 초과로 한 영역이 공간 지배 / 8% 미만으로 무의미)",
    },
    # 2026-05-05 burning_task 2단계 첫 번째 작업 — area_shape 신설 (코드 검증).
    {
        "key": "area_shape",
        "label": "영역 모양 (aspect ratio)",
        "question": "영역 모양이 너무 길쭉 (가로/세로 비율 4:1 초과) 하지 않은가? — 가구 못 박는 strip 형태 catch.",
    },
    # 2026-05-06 추가 — 상영 영역 정사각형 검증.
    {
        "key": "screening_square",
        "label": "상영 영역 정사각형",
        "question": "상영 영역의 aspect ratio 가 1:1 근사 (0.7-1.3) 인가? 미디어월 + 의자 마주봄 패턴이라 정사각형 권장.",
    },
]


# ── System prompt ────────────────────────────────────────────────────
LAYOUT_VALIDATOR_SYSTEM = """당신은 팝업스토어 공간의 컨셉 영역 분할 검증 담당자입니다.
1차 LLM 이 결정한 영역 분할 결과를, 아래 prompt 의 #강제 / #금지 룰 기반으로 검증합니다.

검증 흐름:
- 영역 분할 결과 (자연어 풀이) 를 받음
- 각 #강제 / #금지 룰 위반 여부 판정 (LAYOUT_VALIDATION_RULES key 별로 OK / WARN)
- 명백히 위반인 케이스만 WARN. 애매한 건 OK 로 분류 (자율도 우선).
- 좌표는 받지 않고 자연어 위치 정보만으로 판정.

판정은 강제 차단이 아닌 권장 가이드 — OK / WARN 표시 + 자연어 사유."""


# ── User prompt template ─────────────────────────────────────────────
LAYOUT_VALIDATOR_PROMPT_TEMPLATE = """## 태그 안내 (필수 — 아래 모든 # 태그의 의미)
- #강제 — 1차 LLM 이 100% 따라야 할 룰. 위반 시 WARN.
- #권장 — **75% 강제성**. 부지/브랜드 특수성으로 어쩔 수 없는 위반만 OK. 사유 없는 위반 = WARN.
- #금지 — 100% 절대 X. 위반 시 WARN.
- #참조 — 정보성 데이터. 룰 X.
- #예외 — 특정 조건 (예: brand 매뉴얼 명시) 충족 시 #강제 / #금지 무시 가능.


## 공간 정보
- 면적: {area_sqm:.1f}㎡
- 형태: {shape_desc} (가로세로비 {aspect_ratio:.2f})
- 입구 위치: {entrance_side}

#참조 (부지 분류 기준)
- 면적 51-120평 = 대형 부지
- 면적 120평+ = 초대형 부지
- aspect_ratio < 0.67 = 세로형 / 0.67-1.5 = 정방형 / > 1.5 = 가로형


## 영역 분할 결과 (검증 대상)
{areas_description}


## 검증 룰 (1차 LLM 의 prompt 와 동기화 — 같은 룰 기반 검증)

### 가용 영역 유형
#강제
- 휴식 영역 = 120평 (≈ 396㎡) 미만 부지에서 사용 X
- leaf name 은 7종 한국어 안에서 선택
#금지
- 7종 외 임의 영역 생성 X (커스텀 영역은 brand 매뉴얼 명시 시만 허용)

### 면적 비율
#강제
- 모든 영역 area_ratio ≥ 0.04 (4%) 보장
#금지
- 한 영역이 부지의 60% 이상 차지 X
- 결제 영역 20% 이상 X
#참조 (영역별 적정 비율)
- 결제: 5-15% / 휴식: 5-15% / 포토: 15-50% / 체험: 10-35% / 굿즈판매: 10-35% / 상영: 10-30% / 혼합: 20-50%

### 영역 분할 — 위치 / 배치
#강제
- 입구쪽 (가까이): 포토 / 체험
- 입구 반대편 (멀리): 결제
- **동선 흐름 자연 — 입구 → 중간 (포토/체험/굿즈) → 결제 순서**
  - 결제가 입구 가까이 / 가운데 박히면 = 동선 부자연 = WARN
  - 영역 centroid 의 입구 거리 순서가 흐름과 일치하는지 검사
- **좁은 통로 strip 검사 — 영역 폭 (bbox 짧은 변) < 1000mm 이면 = 가구 못 박는 통로 형태 = WARN**
#금지
- 한 영역이 부지의 길쭉한 strip (aspect 4:1 초과) X — 가구 못 박는 형태
- ㄱ자 / L자 / U자 부지에서 모퉁이 끼고 한 영역으로 묶지 X (영역 polygon 두 부분 갈라짐)
- 영역 폭이 1000mm 미만인 strip 형태 영역 X


## 판정 항목
{validation_questions}


각 항목별로 OK / WARN 판정 + 자연어 사유를 제출하세요.
WARN 시 사유에 **위반 영역 이름 + 어떻게 위반했는지** 구체 명시 (수정 LLM 이 정확히 fix 할 수 있게).
판정은 권장 가이드입니다. 강제 차단 아님."""


# ── Helper: prompt 텍스트 build ──────────────────────────────────────

def build_validation_questions_text() -> str:
    """LAYOUT_VALIDATION_RULES → prompt 안 질문 list 텍스트."""
    lines = []
    for i, rule in enumerate(LAYOUT_VALIDATION_RULES, 1):
        lines.append(f"{i}. {rule['label']}: {rule['question']}")
    return "\n".join(lines)


# ── Helper: Anthropic Tool use schema build ──────────────────────────

def build_tool_schema() -> dict:
    """LAYOUT_VALIDATION_RULES → Anthropic Tool use schema (출력 형식 강제).

    각 rule 마다 두 필드 추가:
    - {key}: "OK" 또는 "WARN" enum
    - {key}_reason: 자연어 사유

    2026-05-05 TR_TH 트랙 1 (concept_area 3노드 패턴) — verdict 필드 신설.
    - verdict: "ok" / "fix_needed" — 전체 판정. concept_area_fix 노드 호출 분기 결정.
    """
    properties = {
        "verdict": {
            "type": "string",
            "enum": ["ok", "fix_needed"],
            "description": (
                "전체 판정. WARN 가 1개 이상이고 명백히 문제 있으면 'fix_needed', "
                "OK 만 있거나 WARN 가 사소하면 'ok'. concept_area_fix 노드 호출 트리거."
            ),
        },
    }
    required = ["verdict"]
    for rule in LAYOUT_VALIDATION_RULES:
        key = rule["key"]
        properties[key] = {
            "type": "string",
            "enum": ["OK", "WARN"],
            "description": f"{rule['label']} 판정 — {rule['question']}",
        }
        properties[f"{key}_reason"] = {
            "type": "string",
            "description": f"{rule['label']} 판정 사유 (자연어 1~2 문장)",
        }
        required.append(key)
        required.append(f"{key}_reason")

    return {
        "name": "validate_concept_area_layout",
        "description": "컨셉_영역 분할 결과의 위치 배치 검증 + 전체 verdict.",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
