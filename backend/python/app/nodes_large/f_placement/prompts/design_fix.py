"""design_fix 프롬프트 — large 전용 (2026-05-06 신설).

design_validator 가 verdict='fix_needed' 판정 시 호출. 1차 design intent + placement 결과
+ 검증 LLM 의 위반 사유를 받고, 위반 항목 집중 수정.

3노드 패턴:
  design (1차 LLM) → placement (코드) → design_validator (검증 LLM) → verdict
    ├─ ok → 다음 노드
    └─ fix_needed + retry < N → design_fix (수정 LLM) → placement 재실행 → 다시 design_validator

흐름:
- 1차 design intent 큰 틀 유지
- 위반 항목 집중 수정 (validator 가 짚어준 fix 지침 따라)
- 출력 = 수정된 design intent list (placement 가 받아 재배치)
"""


# ── System prompt ────────────────────────────────────────────────────
DESIGN_FIX_SYSTEM = """당신은 팝업스토어 공간 배치 디자인 수정 담당자입니다.
1차 design intent + placement 결과 + 검증 LLM 의 위반 사유를 받고, **모든 위반 항목을 100% 해소** 해야 합니다.

핵심 원칙 (필수):
- **위반 사유 (violations) 의 모든 항목을 빠짐없이 해소.** 1개라도 잔존하면 max_retry 반복 → 발표 시 그림 망가짐.
- 검증 LLM 의 fix 지침을 줄별로 분석. 각 위반 가구 / 영역의 ref_point_id / direction / object_type / placed_because 직접 조정.
- 1차 design 의 큰 틀 유지 — 가구 갯수 / 영역 매칭은 가능한 재사용. 다만 **위반 가구의 항목은 반드시 변경.**
- 좌표 / mm 수치 출력 금지. ref_point_id + direction + concept_area + priority 만.
- 출력 형식 = 1차 design 와 동일 (list of design_intent dict).
- 아래 prompt 의 #강제 / #금지 룰 100% 준수. 하나라도 위반하면 검증 단계 max_retry 반복."""


# ── User prompt template ─────────────────────────────────────────────
DESIGN_FIX_PROMPT_TEMPLATE = """## 태그 안내 (필수 — 아래 모든 # 태그의 의미)
- #강제 — 100% 따르세요. 위반 시 검증 단계에서 수정 트리거됨.
- #권장 — **75% 강제성**. 거의 따르되, 부지/브랜드 특수성으로 어쩔 수 없을 때만 위반 가능. 위반 시 placed_because 에 사유 명시.
- #금지 — 100% 절대 X. 위반 시 검증 단계에서 수정 트리거됨.
- #참조 — 정보성 데이터만. 룰 X. 결정 시 참고.
- #예외 — 특정 조건 (예: brand 매뉴얼 명시) 충족 시 #강제 / #금지 무시 가능.


## 1차 design intent (수정 대상)
{intents_description}


## placement 결과 (실제 배치)
{placement_description}


## 검증 LLM 의 위반 사유 (반영 필수 — **모든 항목 100% 해소**)
{violations_text}

⚠️ **위 위반 사유의 모든 항목을 빠짐없이 fix 하세요.** 1개라도 잔존 시 max_retry 반복 → 발표 시 그림 망가짐.
각 위반의 "수정 지침" 줄을 따라 가구 / 영역 / direction / placed_because 직접 조정. 임의 자율 X.


## 공간 정보
- 면적: {area_sqm:.1f}㎡
- 입구 위치: {entrance_side}

#강제 — (해당 없음 — 부지 정보 섹션)
#권장 — (해당 없음)
#금지 — (해당 없음)
#참조
- 면적 100m² 이상 = 큰 부지, 가구 다양화 가능
- 입구 위치 = 동선 시작점 (가까운 곳 = 첫인상 영역)
#예외 — (해당 없음)


## 레퍼런스 활용 (1차 prompt 동기화)
{ref_summary}

#강제
- ref_analysis 있으면 placed_because 에 [<field>: <패턴>] 형식 인용
- 위반 사유에 ref_citation 있으면 → 부적합 placed_because 만 인용 형식 재작성
#권장
- 같은 ref 패턴 여러 intent 에 반복 인용 가능
- 텍스트 그대로 인용 (의역 X)
#금지
- ref 있는데 [ref_없음] 박지 X
#참조
- field 종류 10개: layout_patterns / partition_usage / focal_points / design_highlights / flow_description / density_impression / space_mood / composition_principle / color_palette / lighting_mood
#예외
- ref 비어있으면 [ref_없음] OK


## 오브젝트 다양성

#강제
- 위반 사유에 object_diversity 있으면 → 한 종류 N개 박힌 거 다양화. 다른 가구로 대체.
#권장
- 영역별 적합 가구 사용 (concept_area target_objects 참조)
#금지
- 한 종류만 N개 박기 X
- 위반 fix 시 다른 가구 통째 다 갈아엎기 X (큰 틀 유지)
#참조
- AREA_TYPES.target_objects = 영역별 가능 가구
#예외
- 매뉴얼에 단일 종류 명시 시 그대로


## 공간 활용 균형 (벽면 / 중앙)

#강제
- 위반 사유에 wall_balance 있으면 → wall_facing 쏠림 일부 가구를 center / inward / focal 로 변경
- **동일 object_type 인접 묶음 = 굿즈판매 / 상영 영역에서만 강제**:
  - 굿즈판매: 선반 (shelf_wall / shelf_3tier) 2개 이상 → 딱 붙여 묶음
  - 상영: display_table 2개 이상 → 같은 영역 클러스터
  - 다른 영역 = 자유
#권장
- direction 다양화: wall_facing / center / inward / focal 골고루
- 큰 부지 (100평+) = center 적극 활용
- 굿즈판매 / 상영 영역 동일 가구 cluster priority 연속
#금지
- 모든 가구 wall_facing X (벽 쏠림)
- 위반 fix 시 wall_facing 통째 0개로 X (균형 깨짐)
- 굿즈판매 영역의 선반 사이 갭 X
- 상영 영역의 display_table 부지 양 끝 흩뿌리기 X
#참조
- direction 4종 의미:
  - wall_facing: 벽 밀착
  - center: 공간 중앙 아일랜드
  - inward: 벽에서 떨어져 안쪽
  - focal: 입구에서 잘 보이는 메인 위치
- 동일 종류 가구 인접 = 디자인 의도 (벽 1열 / 중앙 클러스터 / 코너 묶음)
#예외
- 작은 영역은 wall_facing 우세 자연
- 의도적 분산 (예: 결제 카운터 2개 양 끝 = 동선 분산) 시 placed_because 에 사유 명시


## 영역 - 오브젝트 매칭

#강제
- 위반 사유에 area_object_match 있으면 → 부적합 가구를 영역에 맞는 종류로 교체
- 각 가구는 자신의 concept_area target_objects 안에서
#권장
- 영역별 적합 가구:
  - 포토: photo_wall / photo_island / character_bbox / banner_stand
  - 체험: display_table / kiosk / character_bbox
  - 굿즈판매: display_table / shelf_wall / shelf_3tier
  - 결제: counter
  - 휴식: 매뉴얼 따라 (좌석 / 음료)
#금지
- 영역과 무관한 가구 박기 X (예: 결제에 photo_wall)
- 결제 영역에 카운터 외 가구 다수 X
#참조
- AREA_TYPES (concept_area.py) = 영역별 가구 매핑
#예외
- 매뉴얼 명시 영역 시 매뉴얼 우선


## 입구 주변 적합 가구

#강제
- 위반 사유에 entrance_appropriate 있으면 → 입구 가까운 부적합 가구 (선반 / 카운터) 를 첫인상 영역 (포토 / 체험 / 캐릭터) 으로 교체
#권장
- 입구 가까운 가구 = 시각 임팩트 ↑ (character_bbox / photo_wall / banner_stand)
#금지
- 입구 가까이 선반 / 결제 카운터 / 미디어월 박지 X
#참조
- 입구 위치 = 동선 시작점. 첫 5초 인상 결정
#예외
- 매뉴얼에 입구 가구 명시 시 매뉴얼 우선


## 배치 성공률

#강제
- 위반 사유에 placement_success 있으면 → 실패한 가구의 ref_point_id / direction 재결정
#권장
- failed_objects 의 reason 보고 무리한 위치 회피
- 같은 ref_point 에 여러 가구 박지 X (충돌)
#금지
- 통로 < 900mm 만드는 위치 X
- 좁은 부지에 가구 과밀 X
#참조
- failed_objects = 배치 실패한 가구 (placement 노드가 거절한 이유 포함)
#예외
- 매뉴얼 강제 위치는 fail 해도 재시도


## 출력 규칙

#강제
- 출력 = list of design_intent dict (1차 design 와 같은 형식)
- ref_point_id / direction / priority / placed_because 박기
- object_type 이름 한 글자도 변경 X
#권장
- 1차 결과의 가구 수와 비슷하게 (큰 틀 유지)
- placed_because 에 위반 사유 fix 의도 명시 (예: "[fix: wall_balance 위반 → center 변경]")
#금지
- 좌표 / mm 수치 출력 X
- 1차 결과 통째 다른 구조로 갈아엎기 X
#참조
- 출력 JSON 예시 = 1차 design prompt 의 ## 지시 섹션 참조
#예외
- 1차 결과의 일부 가구 삭제 가능 (위반 영역의 가구 폐기 OK)


호출: 1차 design 와 같은 출력 형식 (JSON list)."""


# ── Helper: violations text build ────────────────────────────────────

# 룰별 fix 지침 (위반 사유와 함께 LLM 한테 보냄, 집중 수정 유도).
_FIX_HINTS = {
    "ref_citation": (
        "placed_because 가 [<field>: <패턴>] 형식 안 따른 가구 식별 → 그 가구의 placed_because 만 "
        "ref_analysis 패턴 인용 형식으로 재작성. 다른 가구는 그대로 유지."
    ),
    "object_diversity": (
        "한 종류 N개 박힌 가구 식별 → 일부를 다른 종류 (영역별 target_objects 참조) 로 교체. "
        "예: display_table 17개 중 일부를 character_bbox / shelf_wall 로 변경."
    ),
    "wall_balance": (
        "direction = wall_facing 만 박힌 가구 식별 → 일부를 center / inward / focal 로 변경. "
        "벽면 / 중앙 균형 (대략 50:50)."
    ),
    "area_object_match": (
        "영역과 부적합한 가구 식별 → 그 영역의 target_objects 안 가구로 교체. "
        "예: 결제 영역의 photo_wall → counter."
    ),
    "entrance_appropriate": (
        "입구 가까운 부적합 가구 (선반 / 카운터) 식별 → 첫인상 가구 (character_bbox / photo_wall / banner_stand) 로 교체. "
        "또는 그 가구를 안쪽 영역으로 이동 (ref_point_id 변경)."
    ),
    "placement_success": (
        "failed_objects 의 reason 보고 무리한 위치 (좁은 통로 / 충돌) 식별 → 다른 ref_point 또는 direction 으로 재결정."
    ),
    "same_object_adjacent": (
        "굿즈판매 영역의 선반 (shelf_wall / shelf_3tier) 2개 이상이 흩어져있으면 → 선반끼리 딱 붙여 묶음 배치 (사이 갭 X). "
        "상영 영역의 display_table 2개 이상이 흩어져있으면 → 같은 영역 클러스터로 묶음. "
        "다른 영역의 동일 가구 분산 = 자유 (수정 X)."
    ),
}


def build_violations_text(validator_result: dict) -> str:
    """design_validator 출력 dict → 위반 사유 + fix 지침 구조화된 자연어 텍스트.

    2026-05-06: 번호 매김 + 구조화 + self-check.
    """
    from app.nodes_large.f_placement.prompts.design_validator import DESIGN_VALIDATION_RULES

    lines = []
    warn_count = 0
    for rule in DESIGN_VALIDATION_RULES:
        key = rule["key"]
        verdict = validator_result.get(key)
        if verdict == "WARN":
            warn_count += 1
            reason = validator_result.get(f"{key}_reason", "")
            lines.append(f"")
            lines.append(f"### 위반 #{warn_count}: {rule['label']} ({key})")
            lines.append(f"**위반 사유**: {reason}")
            hint = _FIX_HINTS.get(key)
            if hint:
                lines.append(f"**수정 지침**: {hint}")
            lines.append(f"**자기 검토 (출력 전 확인)**: 새 design intent 가 이 위반 ({rule['label']}) 을 100% 해소했는가?")

    if not lines:
        return "(WARN 없음 — 다만 verdict 가 fix_needed 라 호출됨)"

    header = f"## 총 {warn_count}건의 위반 — 모두 해소 필수\n"
    footer = (
        f"\n\n---\n"
        f"⚠️ **출력 전 self-check 필수**: 위 {warn_count}건 위반 항목을 새 design intent 가 모두 해소했는지 "
        f"항목별로 검토. 1건이라도 잔존 시 출력 X — ref_point_id / direction / object_type 다시 조정."
    )
    return header + "\n".join(lines) + footer
