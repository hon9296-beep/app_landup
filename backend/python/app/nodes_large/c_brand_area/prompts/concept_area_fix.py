"""concept_area_fix 프롬프트 — large 전용 (2026-05-06 5태그 구조 + violations 자세히 분석).

방향성:
- concept_area 1차 prompt 와 거의 동일 구조 (5태그 / 7섹션) — 룰 동기화 (B 안).
- 추가 = '## 1차 영역 분할 결과 (수정 대상)' + '## 검증 LLM 의 위반 사유' 섹션.
- 검증 LLM 의 위반 사유를 자세히 분석해 집중 수정 시키도록.
"""


# ── System prompt ────────────────────────────────────────────────────
CONCEPT_AREA_FIX_SYSTEM = """당신은 팝업스토어/전시 공간의 컨셉 영역 분할 수정 담당자입니다.
1차 영역 분할 결과 + 검증 LLM 의 위반 사유를 받고, **모든 위반 항목을 100% 해소** 해야 합니다.

핵심 원칙 (필수):
- **위반 사유 (violations) 의 모든 항목을 빠짐없이 해소.** 1개라도 잔존하면 발표 시 그림 망가짐.
- 검증 LLM 의 fix 지침을 줄별로 분석. 각 위반 영역의 이름 + split_at 비율을 직접 조정.
- 1차 결과의 큰 틀 유지 — 영역 종류 / 갯수는 가능한 재사용. 다만 **위반 영역의 비율 / 위치는 반드시 조정.**
- 좌표 / mm 수치 출력 금지. axis (x/y) + split_at (0.0-1.0) 비율로만 표현.
- 아래 prompt 의 #강제 / #금지 룰 100% 준수. 하나라도 위반하면 검증 단계 max_retry 반복."""


# ── User prompt template ─────────────────────────────────────────────
CONCEPT_AREA_FIX_PROMPT_TEMPLATE = """## 태그 안내 (필수 — 아래 모든 # 태그의 의미)
- #강제 — 100% 따르세요. 위반 시 검증 단계에서 수정 트리거됨.
- #권장 — **75% 강제성**. 거의 따르되, 부지/브랜드 특수성으로 어쩔 수 없을 때만 위반 가능. 위반 시 placed_because 에 사유 명시.
- #금지 — 100% 절대 X. 위반 시 검증 단계에서 수정 트리거됨.
- #참조 — 정보성 데이터만. 룰 X. 결정 시 참고.
- #예외 — 특정 조건 (예: brand 매뉴얼 명시) 충족 시 #강제 / #금지 무시 가능.


## 1차 영역 분할 결과 (수정 대상)
{areas_description}


## 검증 LLM 의 위반 사유 (반영 필수 — **모든 항목 100% 해소**)
{violations_text}

⚠️ **위 위반 사유의 모든 항목을 빠짐없이 fix 하세요.** 1개라도 잔존 시 max_retry 반복 → 발표 시 그림 망가짐.
각 위반의 "수정 지침" 줄을 따라 split_at 비율 / 영역 위치 직접 조정. 임의 자율 X.


## 공간 정보
- 면적: {area_sqm:.1f}㎡ ({area_sqm_pyeong:.0f}평)
- 형태: {shape_desc} (가로세로비 {aspect_ratio:.2f})
- 입구 위치: {entrance_side}

#강제 — (해당 없음 — 부지 정의 섹션. 분할 룰은 영역 분할 섹션 참조)
#권장 — (해당 없음)
#금지 — (해당 없음)
#참조 (부지 분류 기준)
- 면적 51-120평 (≈ 168-396㎡) = 대형 부지
- 면적 120평+ (≈ 396㎡+) = 초대형 부지
- aspect_ratio < 0.67 = 세로형
- aspect_ratio 0.67-1.5 = 정방형
- aspect_ratio > 1.5 = 가로형
- 입구 위치 ({entrance_side}) = 동선 시작점
#예외
- outdoor 부지 (brand 매뉴얼 명시) — 별도 분류, 일반 룰 적용 X


## 브랜드 / 레퍼런스
{size_emphasis_text}

#강제
- brand 매뉴얼 (placement_rules / concept_areas_hint) 내용은 강제 반영
- 매뉴얼 명시 영역 / 면적 / 위치 누락 X
#권장
- ref_image 의 area_size_emphasis 자연어 활용해 영역 강조도 결정
#금지
- 매뉴얼 명시 내용 누락 금지
#참조
- 1차 결과의 영역 구성 (위 areas_description) 큰 틀 유지
- 위반 사유 (violations) 의 수정 지침 따라 집중 수정
#예외
- 프론트 UI 매뉴얼 무시 명시 시 매뉴얼 #강제 / #금지 무시 (현재 미구현)


## 가용 영역 유형
{types_text}

#강제
- 휴식 영역 = 120평 (≈ 396㎡) 미만 부지에서 사용 X
- leaf name 은 위 7종 한국어 안에서 선택
- 1차 결과의 영역 종류 재사용 권장 (새 이름 임의 만들기 X)
#권장
- 7종 안에서 우선 선택
#금지
- 7종 외 임의 영역 생성 X (커스텀 영역은 brand 매뉴얼 명시 시만 허용)
- 1차 결과에 없던 새 이름 박기 X (위반 사유 fix 만으로 충분)
#참조
- 7종 영역별 target_objects = 영역 안 채울 가구 종류
#예외
- brand 매뉴얼 (concept_areas_hint) 에 추가 영역 명시 시 그 영역 이름 그대로 사용 가능


## 면적 비율 (영역별 적정 size — area_balance 위반 fix 시 핵심)

#강제
- 모든 영역 area_ratio ≥ 0.04 (4%) 보장
- 영역 이름 보고 적정 크기 가늠 (예: 결제 = 카운터 1개라 작게, 포토 = 메인 가능 = 크게)
- 위반 사유 (area_balance) 가 있으면 → split_at 비율 직접 조정해 위반 영역 면적 ≥ 4% 만들기
#권장
- 영역별 적정 비율 가이드:
  - 결제: 5-15% (카운터 1-2개, 작게)
  - 휴식: 5-15% (좌석 클러스터 1개)
  - 포토: 15-50% (메인일 수 있음, brand 강조 시 큼)
  - 체험: 10-35% (중간)
  - 굿즈판매: 10-35% (중간, 진열대 다수)
  - 상영: 10-30% (미디어월 1-2개)
  - 혼합: 20-50% (카페+굿즈 복합)
#금지
- 한 영역이 부지의 60% 이상 차지 X (특정 영역 지배 회피)
- 결제 영역 20% 이상 X (카운터 1-2개 = 큰 면적 의미 X)
- 위반 fix 시 다른 영역을 극단으로 압축 X (한 영역 살리려고 다른 영역 < 4% 만들기 X)
#참조
- ref_image 의 area_size_emphasis → 영역별 size 결정 근거
- 부모/자식 split_at 누적 곱 = leaf 면적 비율
#예외
- brand 매뉴얼에 면적 비율 명시 시 매뉴얼 우선


## 영역 분할 — 위치 / 배치 (checkout_distance / flow_natural 위반 fix 시 핵심)

#강제
- 영역 이름 의미 보고 입구와 거리 결정:
  - 입구쪽 (가까이): 포토 / 체험 (첫인상 영역)
  - 입구 반대편 (멀리): 결제 (카운터 = 동선 후미)
- ㄱ자 / L자 / U자 부지에서 모퉁이 끼고 한 영역으로 묶지 X
- 위반 사유 (checkout_distance) 가 있으면 → 결제 leaf 를 입구 반대편 위치로 이동
- 위반 사유 (flow_natural) 가 있으면 → 동선 흐름 (입구 첫인상 → 굿즈/체험 → 결제) 따라 leaf 재배치
#권장
- 가로형 부지 (aspect_ratio > 1.5) → 좌우 (axis=x) 분할 우선
- 세로형 부지 (aspect_ratio < 0.67) → 상하 (axis=y) 분할 우선
- 정방형 부지 (0.67-1.5) → axis 자유 결정
#금지
- 한 영역이 부지의 길쭉한 strip (aspect 3:1 초과) X
- 영역 polygon 이 두 disconnected 부분으로 갈라짐 X
- 위반 fix 시 1차 결과의 큰 틀 (영역 종류 / 갯수) 통째 갈아엎기 X
#참조
- 부지 분류 (공간 정보 섹션) 기반 분할 방식 결정
- 입구 위치 ({entrance_side}) 기준으로 영역 위치 결정
#예외
- brand 매뉴얼에 영역 위치 명시 시 매뉴얼 우선


## 결정 항목 (BSP split_tree 재결정)
- axis (x: 좌우 / y: 상하) 자유
- split_at 비율 (0.0-1.0) 자유
- leaf 갯수 = 3-6개 권장 (1차 결과 갯수와 비슷하게)
- leaf 마다 name = 한국어 (위 7종 안에서 선택, 1차 결과 이름 재사용 권장)

#강제
- leaf 갯수 3-6개
- 모든 leaf area_ratio ≥ 0.04 (split_at 누적 곱 보장)
- leaf name = 한국어
- 위반 사유 (violations) 의 수정 지침 따라 split_tree 재결정
#권장
- split_at 0.15-0.85 안에서 결정 (극단 회피)
- 부지 분류 기반 axis 결정
#금지
- split_at = 0 또는 1 X
- 트리 depth 8 초과 X
- 위반 fix 시 1차 결과를 통째 다른 구조로 바꾸기 X (큰 틀 유지)
#참조
- 부모/자식 split_at 누적 곱 = leaf 면적 비율
- 예 (depth 1): split_at=0.5 → leaf area 0.5 / 0.5
- 예 (depth 2): 부모 0.5, 자식 0.4 → leaf area 0.5×0.4=0.20 / 0.5×0.6=0.30 / 0.5
#예외
- 단일 leaf 만 박을 때는 axis 없는 leaf 만 (예외 케이스)


호출: split_by_bsp"""


# ── Helper: violations text build ────────────────────────────────────

# 룰별 fix 지침 (위반 사유와 함께 LLM 한테 보냄, 집중 수정 유도).
_FIX_HINTS = {
    "area_balance": (
        "split_at 비율을 조정해서 위반 영역 면적 ≥ 4% 만들기. "
        "예: 부모 split_at=0.5 자식 split_at=0.07 → leaf area=0.5×0.07=0.035 (3.5%, 위반). "
        "부모/자식 모두 0.15-0.85 안에서 결정해 누적 곱이 ≥ 0.04 보장."
    ),
    "checkout_distance": (
        "결제 leaf 를 입구 반대편 (entrance_side 의 반대 위치) 에 박아. "
        "split_tree 에서 결제 leaf 의 위치 = 입구에서 가장 먼 사분면."
    ),
    "area_shape": (
        "aspect ratio > 3:1 영역의 split_at 비율 조정 — 가로/세로 비율 균등하게. "
        "axis 변경 (x → y 또는 반대) 도 고려."
    ),
    "flow_natural": (
        "동선 흐름 = 입구 첫인상 → 굿즈/체험 → 결제. "
        "입구 가까운 쪽 = 포토/체험, 먼 쪽 = 결제 순서로 leaf 재배치."
    ),
    "screening_square": (
        "상영 영역 aspect ratio 가 1:1 근사 (0.7-1.3) 되도록 split_at 비율 조정. "
        "미디어월 한 면 + 의자 마주봄 패턴이라 정사각형 필수. "
        "예: 상영 leaf 의 부모 split_at=0.5, 자식 split_at=0.5 → 정사각형 근사. "
        "현재 strip 형태면 axis 변경 (x → y 또는 반대) 도 고려."
    ),
}


def build_violations_text(layout_validator_result: dict) -> str:
    """layout_validator 출력 dict → 위반 사유 + fix 지침 구조화된 자연어 텍스트.

    2026-05-06: 번호 매김 + 구조화 (위반 사유 / 수정 지침 / 자기 검토 항목 분리).
    LLM 이 각 위반 항목별로 명확히 fix 하도록 유도.
    """
    from app.nodes_large.c_brand_area.prompts.layout_validator import LAYOUT_VALIDATION_RULES

    lines = []
    warn_count = 0
    for rule in LAYOUT_VALIDATION_RULES:
        key = rule["key"]
        verdict = layout_validator_result.get(key)
        if verdict == "WARN":
            warn_count += 1
            reason = layout_validator_result.get(f"{key}_reason", "")
            lines.append(f"")
            lines.append(f"### 위반 #{warn_count}: {rule['label']} ({key})")
            lines.append(f"**위반 사유**: {reason}")
            hint = _FIX_HINTS.get(key)
            if hint:
                lines.append(f"**수정 지침**: {hint}")
            lines.append(f"**자기 검토 (출력 전 확인)**: 새 split_tree 가 이 위반 ({rule['label']}) 을 100% 해소했는가?")

    if not lines:
        return "(WARN 없음 — 다만 verdict 가 fix_needed 라 호출됨)"

    header = f"## 총 {warn_count}건의 위반 — 모두 해소 필수\n"
    footer = (
        f"\n\n---\n"
        f"⚠️ **출력 전 self-check 필수**: 위 {warn_count}건 위반 항목을 새 split_tree 가 모두 해소했는지 "
        f"항목별로 검토. 1건이라도 잔존 시 출력 X — split_at 비율 / 영역 위치 다시 조정."
    )
    return header + "\n".join(lines) + footer
