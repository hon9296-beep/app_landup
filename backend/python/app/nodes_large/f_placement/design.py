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

from app.state import LargeState
from app.utils import parse_llm_json_list
from app.core.exceptions import LLMParsingError, LLMValidationError, CircuitBreakerTrippedError
from app.nodes_large.c_brand_area.concept_area import AREA_TYPES

logger = logging.getLogger(__name__)

# 2026-05-05 트랙 1 (3번) — 영역별 디자인 가이드 텍스트 빌드.
# AREA_TYPES.description 을 단일 진실로 활용 (drift 방지). 각 영역 1줄.
# DESIGN_SYSTEM 안에 inject 되어 LLM 이 영역별로 다른 톤으로 placed_because 작성.
#
# 2026-05-06: 영역별 디자인 톤 dict 신설 (사용자 결정). description + tone 합쳐 prompt 에 inject.
# tone = 디자인 도메인 상식 + 사용자 의도 반영 (체험에서 kiosk 빼고 굿즈로 / 결제 카운터 1개 등).
_CONCEPT_AREA_TONE = {
    "포토": "시각 임팩트 ↑. 정면 포커스 (hero element). 카메라 시선 고정. character_bbox / photo_wall 중앙 / 정면 강조.",
    "체험": "인터랙션 손에 닿는 거리. display_table / character_bbox 사용 (kiosk X — 굿즈판매 영역에 박음). 사용자 동선 자유.",
    "상영": "미디어월 한 면 + 의자 마주봄 패턴. 어두운 톤 (조명 절제). 영상 콘텐츠 집중. 정사각형 영역 권장.",
    "굿즈판매": "상품 진열 선반 (shelf_wall / shelf_3tier) 2개 이상이면 선반끼리 딱 붙여 묶음 배치 (선반 사이 갭 X). kiosk = 상품 검색용 1개. 동선 통로 1m 확보. (벽 위치는 자유 — 영역 안 어디든 OK)",
    "결제": "카운터 1개 (대형 부지 default). 초대형 부지 (120평+) 만 카운터 2개 인접 배치. 동선 후미 매끄러움. 카운터 외 가구 X. 통로 1.5m 이상 (대기 줄).",
    "혼합": "카페 + 굿즈 복합. 좌석 + 진열대 균형. 음료 카운터 구분 가능. 영역 큰 편 (20-50%).",
    "휴식": "좌석 클러스터 안쪽. 카페 톤. 음료 가구 / 좌석 가구 (브랜드 매뉴얼 따라). 동선 vs 정적 분리.",
}

_CONCEPT_AREA_GUIDE = "\n".join(
    f"- {ko}존: {info['description']}\n  톤: {_CONCEPT_AREA_TONE.get(ko, '(톤 미정)')}"
    for ko, info in AREA_TYPES.items()
)

DESIGN_SYSTEM = """당신은 팝업스토어 공간 배치 디자인 담당자입니다.
레퍼런스 분석 결과와 공간 정보를 바탕으로, 가벽 활용을 포함한 최적의 배치 계획을 수립합니다.

## 태그 안내 (필수 — 아래 모든 # 태그의 의미)
- #강제 — 100% 따르세요. 위반 시 검증 단계에서 수정 트리거됨.
- #권장 — **75% 강제성**. 거의 따르되, 부지/브랜드 특수성으로 어쩔 수 없을 때만 위반 가능. 위반 시 placed_because 에 사유 명시.
- #금지 — 100% 절대 X. 위반 시 검증 단계에서 수정 트리거됨.
- #참조 — 정보성 데이터만. 룰 X. 결정 시 참고.
- #예외 — 특정 조건 (예: brand 매뉴얼 명시) 충족 시 #강제 / #금지 무시 가능.


## 물리 제약 (위반 시 배치 무효)
- 절대 좌표나 mm 수치를 출력하지 마세요. reference_point 키이름과 direction만 사용하세요.
- 오브젝트끼리 겹치지 않게 배치하세요.
- 가구 사이에 사람이 지나갈 수 있는 통로 (최소 900mm) 를 확보하세요. 동선이 막히지 않도록 배치 의도를 결정하세요.
  (주의: 동선은 배치 후 자동 계산되며, 통로 부족 시 재배치됩니다.)

#강제
- 절대 좌표 / mm 수치 출력 금지 — ref_point_id 와 direction 만 사용
- 오브젝트끼리 겹침 X
- 가구 사이 통로 최소 900mm 확보
#권장
- 통로 1000mm 이상 확보 (여유 있게)
#금지
- 좌표 (mm 단위 숫자) 출력 X — 위반 시 배치 무효
- 좁은 통로 (< 900mm) 만드는 배치 X
#참조
- walk_mm 노드가 동선 자동 계산. 통로 부족 시 placement 가 reject 후 재시도.
#예외
- 매뉴얼에 통로 폭 명시 시 매뉴얼 우선


## 레퍼런스 활용 (핵심) — 2026-05-05 ref_quality_score 향상 위해 인용 형식 강화 (트랙 1)
- 레퍼런스 분석 결과(ref_analysis)가 있으면 배치의 1순위 근거로 사용하세요.
- **placed_because 안에 사용한 레퍼런스 패턴을 구조화된 형식으로 인용하세요** (권장).
  형식: `[<field>: <패턴 텍스트>] 따라 <배치 의도>`
  - <field>: layout_patterns / partition_usage / focal_points / design_highlights / flow_description / density_impression / space_mood / composition_principle / color_palette / lighting_mood 중 하나
  - 예 1: "[layout_patterns: 벽 옆 진열대 클러스터] 따라 북쪽 벽에 shelf_wall 배치"
  - 예 2: "[focal_points: 중앙 포커스 테이블] 따라 photo_island 중앙 배치"
  - 예 3: "[flow_description: 입구→포커스→측벽 순환] 따라 character_bbox 입구 정면 배치"
- **레퍼런스 분석 결과가 비어있는 경우**: placed_because 를 "[ref_없음] 자율 판단 — <배치 의도>" 로 시작하세요. 그 외에는 공간 형태와 브랜드 특성에 맞게 자유롭게 디자인하세요.

#강제
- ref_analysis 있으면 1순위 근거. placed_because 에 [<field>: <패턴 텍스트>] 형식 인용 필수
- 각 placed_because 에 ref 패턴 1개 이상 인용 (ref 있을 시)
#권장
- 같은 ref 패턴을 여러 intent 에 반복 인용 가능 (한 패턴이 여러 가구 결정 근거)
- 텍스트 그대로 인용 (의역 X — 임베딩 매칭률 ↑)
#금지
- ref 있는데 [ref_없음] 박지 X
- placed_because 에 인용 형식 무시하고 자유 작성 X (검증 단계에서 매칭 실패)
#참조
- ref 패턴 = 디자이너 의도 방향성. 임베딩 매칭 점수 (ref_quality_score) 위해 인용 형식 중요
- field 종류 10개: layout_patterns / partition_usage / focal_points / design_highlights / flow_description / density_impression / space_mood / composition_principle / color_palette / lighting_mood
#예외
- ref 비어있으면 [ref_없음] 자율 판단 OK


## 가벽(partition_wall_I / partition_wall_L) 활용
가벽은 단순한 구조물이 아니라 디자인 요소입니다:
- 공간 분할: 체험/전시/포토존 등 구역을 의미 있게 나눔
- 디자인 연출: 캐릭터 이미지·그래픽·브랜드 비주얼을 붙여 시각적 포인트로 활용
- 동선 유도: 방문자 흐름을 자연스럽게 안내
- 포토존 배경: 가벽 한 면을 포토 배경으로 활용, 반대면은 진열/그래픽
가벽을 어디에 세울지, 몇 개나 쓸지도 전체 디자인의 일부로 판단하세요.

#강제
- 가벽은 디자인 요소 (구조물 X). placed_because 에 가벽 의도 명시 (4가지 용도 중 1개)
#권장
- 가벽 4가지 용도 중 1개 명시: 공간 분할 / 디자인 연출 / 동선 유도 / 포토존 배경
- partition_wall_L (L자) = 모서리 / 코너 활용
- partition_wall_I (직선) = 영역 분할 / 포토 배경
#금지
- 목적 없는 가벽 임의 배치 X
- 가벽으로 통로 차단 X
#참조
- partition_wall_I = 직선 형태 / partition_wall_L = L자 형태
- 가벽 양면 활용 가능 (한 면 포토, 반대면 진열)
#예외
- 매뉴얼에 가벽 X 명시 시 가벽 사용 X


## 공간 활용
- 벽면과 중앙 공간을 균형 있게 활용하세요
- 오브젝트를 벽에만 붙이지 말고, 공간 전체를 디자인하세요
- 브랜드 매뉴얼 규정이 있으면 반드시 따르세요

#강제
- 벽면과 중앙 균형 활용 — wall_facing 만으로 모든 가구 채우지 X
- direction 다양화 (wall_facing / center / inward / focal 중 골고루)
- **동일 object_type 인접 묶음 = 굿즈판매 / 상영 영역에서만 강제**:
  - 굿즈판매: shelf_wall / shelf_3tier 2개 이상 → 선반끼리 딱 붙여 묶음
  - 상영: display_table / banner_stand 2개 이상 → 같은 영역 클러스터 묶음
  - 다른 영역 (포토 / 체험 / 결제 / 혼합 / 휴식) = 동일 종류 가구 흩어져도 OK (강제 X)
#권장
- 큰 부지 (100평+) 는 중앙 아일랜드 (center direction) 적극 활용
- 작은 부지는 벽 중심 + 일부 center
- 굿즈판매 / 상영 영역의 동일 object_type cluster priority 연속 (예: 3, 4, 5)
#금지
- 모든 가구를 wall_facing 한 종류로만 X (벽 쏠림)
- 모든 가구를 center 만 X (중앙 혼잡)
- **굿즈판매 영역의 진열 선반을 흩뿌려 배치 X (선반끼리 딱 붙여 묶음)**
- **상영 영역의 display_table 을 부지 양 끝에 흩뿌리지 X (같은 영역 클러스터)**
#참조
- 부지 크기 / aspect_ratio 따라 균형 조정
- 굿즈판매 / 상영 = 동일 가구 묶음 디자인 의도
#예외
- 매뉴얼에 배치 방향 명시 시 매뉴얼 우선
- 굿즈판매 / 상영 외 영역의 동일 가구 분산 = 자유


## 영역별 디자인 가이드 (concept_area 별 권장 톤 — AREA_TYPES.description 정합)
{concept_area_guide}

#강제
- 각 가구는 자신의 concept_area 에 맞는 종류 (target_objects) 선택
- placed_because 에 영역 톤 (description) 반영
- **굿즈판매 영역 = 진열 선반 (shelf_wall / shelf_3tier) 2개 이상이면 선반끼리 딱 붙여 묶음 배치 (선반 사이 갭 X). 벽 위치는 자유.**
- 입구 1m 이내 부적합 가구 (선반 / 결제 카운터 / 미디어월) 박지 X. 첫인상 가구 (character_bbox / photo_wall / banner_stand) 만 입구 가까이.
#권장
- 영역별 적합 가구:
  - 포토존: photo_wall / photo_island / character_bbox / banner_stand
  - 체험: display_table / character_bbox (kiosk X — 굿즈판매 영역으로 이동)
  - 굿즈판매: display_table / shelf_wall / shelf_3tier / kiosk (상품 진열용 + 검색 키오스크 1개)
  - 결제: counter (대형 1개 / 초대형 120평+ 만 2개 인접)
  - 상영: display_table / banner_stand (미디어월 + 의자 마주봄 패턴)
  - 휴식: 좌석 / 음료 가구 (브랜드 매뉴얼 따라)
- **영역 경계 (boundary) 인접부 배치 지양 (85% 권장)** — 두 영역의 경계선 부근 (300mm 이내) 에 가구 두지 X.
  - 이유: 경계선 위/근처 가구 = 어느 영역에 속하는지 모호 + 양쪽 영역 동선 침범.
  - 우선순위: 영역 안쪽 (중앙 또는 영역 boundary 에서 떨어진 자리) 부터 자리 잡고, 경계 부근은 마지막 보조 가구만.
  - 예외: 부지 좁아 경계 부근 외 자리 없을 때만 허용 (#예외 케이스).
#금지
- 영역과 무관한 가구 박지 X (예: 결제 영역에 photo_wall X)
- 결제 영역에 카운터 외 가구 다수 박지 X
- 입구 1m 이내에 선반 / 카운터 박지 X (동선 후미 가구 = 입구 부적합)
- 굿즈판매 영역의 선반 사이에 갭 두지 X (선반 2개 이상이면 딱 붙여 묶음)
#참조
- AREA_TYPES.target_objects = 영역별 가능 가구 list (concept_area.py 정의)
#예외
- 매뉴얼 명시 영역 시 매뉴얼의 target_objects 우선


## 출력 규칙
- 좌표/mm 수치 절대 출력 금지
- reference_point, direction, priority만 결정
- object_type은 주어진 목록의 이름을 정확히 사용
- JSON만 출력

#강제
- JSON list only (배열). 다른 형식 X
- object_type 이름 한 글자도 변경 X (영문 코드 그대로)
- ref_point_id / direction / priority 박기
#권장
- priority 1부터 순서대로 (1 = 최우선 배치)
#금지
- 좌표 / mm 수치 출력 X
- object_type 이름 한국어 / 한자 / 변형 X
#참조
- 출력 = list of design_intent dict (각 dict = 1개 가구)
- ref_point_id null 가능 (concept_area 만 박을 때)
#예외
- ref_point_id 없으면 null + concept_area 만
""".format(concept_area_guide=_CONCEPT_AREA_GUIDE)

DESIGN_PROMPT_TEMPLATE = """## 공간 정보
- 바닥 면적: {usable_area_sqm:.1f}m²
- zone 분포: {zone_map}
- 입구 수: {entrance_count}
- 디자인 포인트 수: {ref_point_count}

#강제 — (해당 없음 — 부지 정보 섹션)
#권장 — (해당 없음)
#금지 — (해당 없음)
#참조
- 바닥 면적 100m² 이상 = 큰 부지, 가구 다양화 가능
- ref_point_count = 디자인 포인트 갯수 (가구 박을 후보 위치)
#예외 — (해당 없음)


## 디자인 포인트 (Design Points)
각 포인트는 오브젝트를 배치할 수 있는 디자인 위치입니다. ref_point_id로 선택하세요.
{ref_points_summary}

#강제
- 모든 ref_point_id 는 위 list 중에서만 선택
- ref_point_id null 박을 때는 concept_area 반드시 명시
#권장
- 영역별로 골고루 ref_point 사용 (한 영역에 가구 몰빵 X)
- ref_point 의 concept_area 와 design intent 의 concept_area 일치
#금지
- 위 list 외 ref_point_id 박지 X (배치 무효)
#참조
- ref_points_summary = 가능 ref_point list (concept_area 별 그룹핑)
#예외
- 매뉴얼에 좌표 / 위치 명시 시 ref_point_id null 가능 + concept_area 만 박기


## 브랜드 규정
{brand_rules}

#강제
- 매뉴얼 (placement_rules) 규정 무조건 따름 (최우선)
- 매뉴얼 명시 figures_mentioned (필수 조형물) 누락 X
#권장
- 브랜드 카테고리 분위기 반영 (placed_because 톤)
#금지
- 매뉴얼 누락 X
- 매뉴얼 규정 임의 무시 X
#참조
- brand_data.brand = 카테고리 / 컨셉 / figures_mentioned / prohibited_material 등
- placement_rules = 매뉴얼 명시 가구 종류 / 수량 / 위치
#예외
- 매뉴얼 무시 명시 (사용자 UI 입력) 시 무시 가능 (현재 미구현)


{density_guide}

## 배치 가능 오브젝트 타입
아래 목록은 배치 가능한 타입입니다. 전부 사용할 필요 없습니다. 공간과 컨셉에 맞게 적절한 수량만 배치하세요.
{objects_list}

#강제
- 위 list 외 object_type 박지 X (배치 무효)
- object_type 이름 한 글자도 변경 X (영문 코드 그대로)
#권장
- 다양한 종류 사용 (한 종류만 N개 X)
- 영역별 적합 가구 사용 (concept_area target_objects 참조)
#금지
- 한 종류만 박기 X (display_table N개만 = 다양성 X)
- list 외 임의 object_type X
#참조
- objects_list = eligible_objects (object_selection 노드 출력)
#예외
- 매뉴얼에 추가 가구 명시 시 그 가구도 가능 (placement_rules 우선)


## 벽 밀착 속성 (wall_attachment)
{wall_attachment_text}

#강제
- wall_attachment="wall_only" 인 오브젝트 = direction "wall_facing" 만 사용
#권장
- wall_attachment="free" 인 오브젝트 = wall_facing / center / inward / focal 다양 사용
#금지
- wall_only 오브젝트를 center / inward 박지 X (벽 밀착 가구가 중앙 → 의미 X)
#참조
- wall_attachment 종류: "wall_only" / "free" / "wall_preferred"
- 오브젝트별 wall_attachment 위 표 참조
#예외
- 매뉴얼에 명시된 위치 시 매뉴얼 우선


## 오브젝트 쌍 규칙 (pair_rules)
{pair_rules_text}

#강제
- "join" 쌍 = join_with 박기 (밀착 배치 보장)
- "separate" 쌍 = 분리 배치 (직접 인접 X)
- "adjacent" 쌍 = 근접 배치 (같은 영역 또는 인접 영역)
#권장
- pair 룰이 있으면 두 가구 동시 배치
#금지
- "separate" 쌍을 인접 배치 X
- "join" 쌍에 join_with 누락 X
#참조
- pair_rules_text = 오브젝트 쌍 룰 list (brand 매뉴얼 기반)
#예외
- 매뉴얼에 pair 룰 없으면 자유

{layout_examples}{required_figures}
## 수량 결정 원칙
- 브랜드 매뉴얼에 수량이 명시되어 있으면 무조건 따르세요 (최우선)
- 같은 타입을 여러 개 배치하려면 배열에 같은 object_type을 여러 번 넣으세요

#강제
- 매뉴얼 수량 명시 시 무조건 따름
- 같은 종류 여러 개 박을 때 배열에 같은 object_type 여러 번
#권장
- 영역 크기 비례 수량 결정 (큰 영역 = 가구 多, 작은 영역 = 1-2개)
- 결제 영역 = counter 1-2개 (충분, 더 많이 X)
#금지
- 매뉴얼 수량 위반 X
- 한 영역에 같은 종류 5개+ 박지 X (과밀)
#참조
- objects_list 의 max_count = 가구별 최대 수량 (object_selection 산출)
#예외
- 매뉴얼에 명시 수량 시 max_count 무시 가능


## 지시
위 오브젝트를 공간에 배치하세요.

**중요: object_type은 위 목록의 이름을 한 글자도 바꾸지 말고 정확히 그대로 사용하세요.**
**반드시 ref_point_id를 지정하세요** — 디자인 포인트에 배치 의도를 연결합니다.
해당하는 기준점이 없으면 ref_point_id: null + concept_area만 지정.

```json
[
  {{
    "object_type": "character_bbox",
    "ref_point_id": "wall_3_mid",
    "concept_area": "맞이",
    "direction": "wall_facing",
    "alignment": "parallel",
    "priority": 1,
    "join_with": null,
    "placed_because": "[layout_patterns: 입구 정면 히어로 캐릭터] 따라 facing_entrance 벽에 character_bbox 배치"
  }}
]
```

direction: "wall_facing" | "center" | "inward" | "focal"
  - wall_facing: 벽에 밀착 배치 (선반, 계산대 등)
  - center: 공간 중앙 아일랜드 배치 (진열대, 테이블 등)
  - inward: 벽에서 떨어져 안쪽으로 배치
  - focal: 입구에서 잘 보이는 메인 위치 (히어로 캐릭터, 포토존 등)
alignment: "parallel" | "perpendicular" | "none"
concept_area: "맞이" | "포토" | "체험" | "상영" | "굿즈판매" | "결제" | "혼합" | "휴식"
priority: 1(최우선) ~ 10(최후순)
join_with: 밀착 배치할 대상 object_type (pair_rules에서 "join" 관계인 경우). 없으면 null.

규칙 (우선순위 순):
1. 브랜드 매뉴얼 규정이 있으면 반드시 따를 것 (최우선)
2. pair_rules의 쌍 규칙을 반드시 준수할 것 (join=밀착 가능, separate=분리 필수, adjacent=근접 배치)
3. 각 벽의 수용 가능 수를 초과하지 마세요
4. 포토존과 캐릭터는 가까이 배치 (포토 동선 확보)
5. reference_point는 반드시 위 허용 목록 중 하나만 사용
6. priority는 1부터 순서대로 (낮을수록 먼저 배치)"""


def run(state: LargeState) -> LargeState:
    """Agent 3: 배치 의도 결정. LLM은 이름만 받고 방향만 결정."""
    brand_data = state.get("brand_data") or {}
    zone_map = state.get("zone_map") or {}
    usable_poly = state.get("usable_poly")
    ref_analysis = state.get("ref_analysis") or {}
    concept_areas = state.get("concept_areas") or []

    # ── eligible_objects는 object_selection이 만든 것 재사용 ──
    eligible_objects = state.get("eligible_objects") or []
    if not eligible_objects:
        logger.warning("[design] eligible_objects 없음")
        return {"design_intents": [], "eligible_objects": []}

    if not concept_areas:
        logger.warning("[design] concept_areas 없음 — 기능 영역 블록 없이 진행")

    # ── 재호출 판단: choke_feedback이 있으면 실패 오브젝트만 재기획 ──
    choke_feedback = state.get("choke_feedback") or ""
    failed_objects = state.get("failed_objects") or []
    placed_objects = state.get("placed_objects") or []
    is_retry = bool(choke_feedback and failed_objects)

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

    # Reference points 요약 — concept_areas 있으면 영역별 그룹핑
    reference_points = state.get("reference_points") or []
    ref_points_summary = _build_ref_points_summary(reference_points, concept_areas)

    # 배치 예시 (이전 성공 사례)
    layout_examples = state.get("layout_examples") or []
    examples_text = _build_layout_examples_text(layout_examples)

    # 프롬프트 구성 — 이름만, 치수 없음
    usable_area = usable_poly.area / 1_000_000 if usable_poly else 0
    objects_list = "\n".join(f"- {ot}" for ot in unique_types)

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

    prompt = DESIGN_PROMPT_TEMPLATE.format(
        usable_area_sqm=usable_area,
        zone_map=json.dumps(zone_map),
        entrance_count=len(state.get("all_entrances_mm") or []) or 1,
        ref_point_count=len(reference_points),
        ref_points_summary=ref_points_summary,
        brand_rules=brand_rules_text,
        objects_list=objects_list,
        wall_attachment_text=wall_attachment_text,
        pair_rules_text=pair_rules_text,
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
        prompt += "**[zone 강제] zone이 명시된 경우 반드시 해당 zone의 ref_point만 선택하세요.**\n"
        prompt += "**[wall 강제] wall 힌트(right/left/center)가 명시된 경우 entrance_side가 일치하는 ref_point를 반드시 선택하세요.**\n"
        prompt += "아래 목록에 없는 오브젝트는 배치하지 마세요.\n"
        prompt += "\n".join(intent_lines) + "\n"
        logger.info(f"[design] resolved_intents {len(resolved_intents)}개 주입")

    # ── 재호출 피드백 주입 (failure_classifier → choke_feedback) ──
    # choke_feedback는 상단에서 이미 읽음 (is_retry 판단용). 중복 read 제거.
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
        logger.warning("[design] API 키 없음 — 기본 의도 반환")
        category = brand_data.get("brand", {}).get("brand_category", "\uae30\ud0c0")
        if isinstance(category, dict):
            category = category.get("value", "\uae30\ud0c0")
        intents = _default_intents(eligible_objects, reference_points, category)
        return {"design_intents": intents, "eligible_objects": eligible_objects, "design_fallback_reason": "API_KEY_MISSING"}

    client = Anthropic(api_key=api_key)

    # 메시지 구성: concept_areas + concept_area_check + ref_analysis + dead_zones 를 프롬프트 상단에 삽입
    concept_areas_text = _build_concept_areas_text(concept_areas)
    concept_area_check_text = _build_concept_area_check_text(state.get("concept_area_check") or {})
    ref_analysis_text = _build_ref_analysis_text(ref_analysis)
    dead_zones_text = _build_dead_zones_text(state.get("dead_zones") or [])

    prefix = ""
    if concept_areas_text:
        prefix += concept_areas_text + "\n\n"
    if concept_area_check_text:
        prefix += concept_area_check_text + "\n\n"
    if ref_analysis_text:
        prefix += ref_analysis_text + "\n\n"
    if dead_zones_text:
        prefix += dead_zones_text + "\n\n"
    if prefix:
        prompt = prefix + prompt

    content = [{"type": "text", "text": prompt}]

    last_error = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16384,  # 2026-05-06: 4096 → 16384 (prompt 강화 후 design intent 17+개 + 긴 placed_because 담기 위해)
                system=DESIGN_SYSTEM,
                messages=[{"role": "user", "content": content}],
            )
            from app.token_tracker import track_usage
            track_usage("large.design", response)
            if not response.content:
                last_error = LLMParsingError("LLM 응답 비어있음", {"attempt": attempt + 1})
                continue

            intents = parse_llm_json_list(response.content[0].text)
            if not intents:
                last_error = LLMParsingError("JSON 배열 파싱 결과 0개", {"attempt": attempt + 1})
                continue

            # Circuit Breaker — 좌표 주입 감지
            if _has_coordinate_injection(intents):
                last_error = LLMValidationError("좌표 주입 감지", {"attempt": attempt + 1})
                logger.warning(f"[design] attempt {attempt+1}: 좌표 주입 감지, 재시도")
                continue

            # ── 하네스: LLM 응답의 object_type을 eligible 키로 복원 ──
            intents = _remap_object_types(intents, unique_types)

            logger.info(f"[design] {len(intents)} intents generated")
            for idx, it in enumerate(intents):
                logger.info(f"[design]   #{idx+1} {it.get('object_type','?')} | reason={it.get('placed_because','')}")

            # 2026-05-01 Phase 3-2 — concept_area 도입 후 LLM 출력 형식 추적 (fail 대비)
            n_with_concept = sum(1 for it in intents if it.get("concept_area"))
            n_with_zone = sum(1 for it in intents if it.get("zone_label"))
            concept_values = sorted({it.get("concept_area") for it in intents if it.get("concept_area")})
            zone_values = sorted({it.get("zone_label") for it in intents if it.get("zone_label")})
            logger.info(
                "[design] LLM 출력 형식 — concept_area=%d/%d %s / zone_label=%d/%d %s (Phase 3-2 적응 추적)",
                n_with_concept, len(intents), concept_values,
                n_with_zone, len(intents), zone_values,
            )

            # ── zone_hint / wall_hint 후처리 강제 ──
            intents = _enforce_placement_hints(intents, resolved_intents, reference_points)

            # 재호출 시: 기배치 intents 유지 + 실패분 intents 합치기
            if is_retry:
                intents = _merge_retry_intents(placed_objects, intents)
                logger.info(f"[design] 재호출 병합: 기배치 {len(placed_objects)}개 유지 + 신규 {len(intents) - len(placed_objects)}개")

            # ── global_direction_hint 후처리 (FULL_RELAYOUT 시) ──
            intents = _apply_global_direction(intents, state.get("global_direction_hint"))

            return {
                "design_intents": intents,
                "eligible_objects": eligible_objects,
            }
        except (LLMParsingError, LLMValidationError) as e:
            last_error = e
            logger.warning(f"[design] attempt {attempt+1} 실패: {type(e).__name__}: {e}")
        except Exception as e:
            last_error = LLMParsingError(str(e), {"attempt": attempt + 1})
            logger.warning(f"[design] attempt {attempt+1} 실패: {e}")

    # Circuit Breaker 3회 소진 — 에러 반환
    logger.error(f"[design] Circuit Breaker: 3회 실패 → 디자인 생성 실패 (last_error={last_error})")
    raise LLMParsingError(f"디자인 생성 3회 실패: {last_error}", {"attempts": 3})


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
    "counter":        {"labels": ["deep_wall"],             "allowed_directions": ["wall_facing", "inward"],           "alignment": "parallel"},
    # pos_counter 는 utils.OBJECT_STANDARDS 에서 counter 의 alias 로 흡수됨 (normalize 단계 치환). 별도 항목 불필요.
    "character_bbox": {"labels": ["facing_entrance"],       "allowed_directions": ["focal", "wall_facing", "center"], "alignment": "parallel"},
    "photo_wall":     {"labels": ["side_wall", "deep_wall"], "allowed_directions": ["wall_facing", "focal", "inward"], "alignment": "parallel"},     # 일자형 벽 밀착 — 포토존 배경
    "photo_island":   {"labels": ["center_freestanding"],    "allowed_directions": ["center", "focal"],                "alignment": "none"},         # 아일랜드형 — 360도 포토
    "shelf_wall":     {"labels": ["side_wall"],             "allowed_directions": ["wall_facing", "inward"],           "alignment": "parallel"},
    "shelf_3tier":    {"labels": ["side_wall"],             "allowed_directions": ["wall_facing", "inward", "center"], "alignment": "parallel"},
    "display_table":  {"labels": ["center_freestanding", "side_wall"], "allowed_directions": ["center", "inward", "wall_facing"], "alignment": "none"},
    "banner_stand":   {"labels": ["entrance_adjacent"],     "allowed_directions": ["wall_facing", "focal", "center"], "alignment": "parallel"},
    # partition_wall (범용) 폐기 — flush+center_freestanding 모순. I/L만 사용 (small 정합).
    "partition_wall_I": {"labels": ["side_wall", "deep_wall"],         "allowed_directions": ["wall_facing", "inward"],              "alignment": "parallel"},       # 일자형 백월 — 벽 밀착 포토존 배경
    "partition_wall_L": {"labels": ["deep_wall"],                      "allowed_directions": ["wall_facing", "inward"],              "alignment": "parallel"},       # ㄱ자형 코너 — deep_zone 모서리 간이 창고
}

_OBJ_DEFAULT_PREF = {"labels": ["side_wall", "center_freestanding"], "allowed_directions": ["center", "inward", "wall_facing", "focal"], "alignment": "none"}

# 카테고리별 우선 배치 오버라이드
_CATEGORY_OVERRIDES = {
    "캐릭터 IP": {
        "character_bbox": {"labels": ["facing_entrance"], "allowed_directions": ["focal", "wall_facing"], "alignment": "parallel"},
        "photo_wall":     {"labels": ["side_wall"],       "allowed_directions": ["wall_facing", "focal"], "alignment": "parallel"},
        "photo_island":   {"labels": ["center_freestanding"], "allowed_directions": ["center", "focal"],  "alignment": "none"},
    },
    "F&B": {
        "counter":       {"labels": ["deep_wall", "side_wall"], "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
        "display_table": {"labels": ["center_freestanding"],    "allowed_directions": ["center", "inward"],      "alignment": "none"},
    },
    "패션 브랜드": {
        "shelf_wall":    {"labels": ["side_wall", "deep_wall"], "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
        "display_table": {"labels": ["center_freestanding"],    "allowed_directions": ["center", "inward"],      "alignment": "none"},
    },
}


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

    # 카테고리 오버라이드
    cat_overrides = _CATEGORY_OVERRIDES.get(category, {})

    def _pick_rp_by_label(preferred_labels: list[str]) -> tuple[str | None, dict | None]:
        """선호 라벨 순서대로 미사용 ref_point 탐색."""
        for lbl in preferred_labels:
            for rp in label_rps.get(lbl, []):
                if rp["id"] not in used_rp_ids:
                    used_rp_ids.add(rp["id"])
                    return rp["id"], rp
        # 선호 라벨에 없으면 아무 미사용 ref_point
        for rp in rps:
            if rp["id"] not in used_rp_ids:
                used_rp_ids.add(rp["id"])
                return rp["id"], rp
        return None, None

    intents = []
    for i, obj in enumerate(eligible_objects):
        ot = obj["object_type"]

        # 카테고리 오버라이드 → 타입별 기본 → 전체 기본
        pref = cat_overrides.get(ot) or _OBJ_PREFERENCE.get(ot) or _OBJ_DEFAULT_PREF

        ref_id, rp = _pick_rp_by_label(pref["labels"])
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
            "placed_because": f"{label} → {ot} ({direction})",
        })

    logger.info(f"[design] fallback intents: {[(i['object_type'], i['ref_point_id'], i['direction']) for i in intents]}")
    return intents


def _build_concept_areas_text(concept_areas: list) -> str:
    """concept_areas → 프롬프트 텍스트. 각 영역의 역할·비중·위치·타겟 오브젝트·키워드.

    design_concept(구 concept_gen 출력)을 대체. concept_areas는 공간을
    기능 영역으로 분할한 구조이므로, LLM이 "어느 영역에 어떤 오브젝트를
    둘지" 판단할 수 있도록 target_objects까지 명시한다.

    2026-05-03: AREA_TYPES.description fallback inject — role 비었을 때
    영역 본연의 역할(맞이=첫인상/캐릭터, 결제=카운터 등)을 LLM 에 권장 가이드로 전달.
    자율도 우선 정책 — 강제 표현 X, 짧게 한 줄.
    """
    if not concept_areas:
        return ""

    from app.nodes_large.c_brand_area.concept_area import AREA_TYPES

    lines = ["## 기능 영역 (Concept Areas — 이 영역 구성에 맞춰 배치하세요)"]
    lines.append("공간을 아래와 같이 기능별로 구획했습니다. 각 영역의 target_objects를 해당 영역에 속한 ref_point에 배치하세요.")

    for area in concept_areas:
        name = area.get("name", "?")
        ratio = area.get("area_ratio", 0)
        pos_hint = area.get("position_hint", "")
        targets = area.get("target_objects", [])
        keywords = area.get("search_keywords", [])
        role = area.get("role", "")

        # role 비었을 때 AREA_TYPES.description 으로 fallback (단일 진실)
        if not role and name in AREA_TYPES:
            role = AREA_TYPES[name].get("description", "")

        parts = [f"- **{name}**"]
        if ratio:
            parts.append(f"({ratio:.0%})")
        if pos_hint:
            parts.append(f"[{pos_hint}]")
        if role:
            parts.append(f"— {role}")
        if targets:
            parts.append(f"→ 타겟: {', '.join(targets)}")

        lines.append(" ".join(parts))
        if keywords:
            lines.append(f"    키워드: {', '.join(keywords)}")

    return "\n".join(lines)


def _build_concept_area_check_text(check: dict) -> str:
    """concept_area_check (lg_layout_validator 결과) → design prompt 자연어 블록.

    2026-05-04 신설. 자율도 우선 정책 — 강제 X, 참고 가이드.
    LAYOUT_VALIDATION_RULES 따라 동적 생성. WARN 항목 있을 때만 inject.
    """
    if not check:
        return ""

    from app.nodes_large.c_brand_area.prompts.layout_validator import LAYOUT_VALIDATION_RULES

    has_warn = any(check.get(rule["key"]) == "WARN" for rule in LAYOUT_VALIDATION_RULES)
    if not has_warn:
        return ""  # 모두 OK 면 inject 안 함 — prompt 토큰 절약

    lines = ["## 영역 배치 검토 결과 (참고용 가이드)"]
    lines.append("아래는 영역 분할 직후 LLM 검토 결과입니다. 강제 차단 X, 배치 결정 시 자율 보정 참고.")

    for rule in LAYOUT_VALIDATION_RULES:
        key = rule["key"]
        result = check.get(key, "")
        reason = check.get(f"{key}_reason", "")
        if result == "WARN":
            lines.append(f"- {rule['label']}: WARN — {reason}")
        elif result == "OK":
            lines.append(f"- {rule['label']}: OK")

    return "\n".join(lines)


def _build_ref_analysis_text(ref_analysis: dict) -> str:
    """Vision 분석 결과 → design 프롬프트 주입 (mid 강제 + JSON 10축).

    2026-04-28 결정 (`TR_S/2026-04-24_[프롬프트_강제도].md`):
      - 강제도 mid: "10축 모두 반영" — 항목 강제. value 는 자율 변형 OK.
      - 포맷 JSON: analyzer 의 tool_use 산출물 그대로 박기. key 강제 + value 자유.

    2026-05-03 확장: 8 → 10 축 (color_palette + lighting_mood 추가, Vision 확장 정합).
    """
    if not ref_analysis:
        return ""

    # 10축 추출 (analyzer tool_use schema 기준, 2026-05-03 확장)
    payload = {
        "layout_patterns":      ref_analysis.get("layout_patterns", []),
        "partition_usage":      ref_analysis.get("partition_usage", []),
        "focal_points":         ref_analysis.get("focal_points", []),
        "flow_description":     ref_analysis.get("flow_description", ""),
        "density_impression":   ref_analysis.get("density_impression", ""),
        "space_mood":           ref_analysis.get("space_mood", ""),
        "composition_principle": ref_analysis.get("composition_principle", ""),
        "design_highlights":    ref_analysis.get("design_highlights", []),
        "color_palette":        ref_analysis.get("color_palette", ""),
        "lighting_mood":        ref_analysis.get("lighting_mood", ""),
    }
    # 빈 값 모두 → 의미 없는 블록 → 빈 문자열
    if not any(payload.values()):
        return ""

    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

    return (
        "## 레퍼런스 이미지 분석 (필수 반영)\n"
        "아래 JSON 은 비슷한 카테고리 팝업스토어의 Vision 분석 결과입니다.\n"
        "**10축 모두 배치 설계에 반영하세요.** 각 축의 value 는 카테고리·존·분기 (공장형/야외 부스) 특성에 맞게 자율 변형 가능합니다.\n"
        "```json\n"
        f"{payload_json}\n"
        "```\n"
        "축 의미:\n"
        "- layout_patterns: 배치 패턴 (벽면/중앙/통로 등)\n"
        "- partition_usage: 가벽/파티션 활용\n"
        "- focal_points: 시선 집중 포인트\n"
        "- flow_description: 동선 흐름\n"
        "- density_impression: 밀도감\n"
        "- space_mood: 공간 분위기 (조명·톤·재질 인상)\n"
        "- composition_principle: 구성 원리 (대칭·비율·반복 등)\n"
        "- design_highlights: 연출 포인트\n"
        "- color_palette: 주조/보조 색상 (브랜드·존 톤 결정)\n"
        "- lighting_mood: 조명 톤·분위기 (focal/포토존 강조 결정)"
    )


def _build_dead_zones_text(dead_zones) -> str:
    """LLM 에 dead_zone (피해야 할 영역) 좌표 알리기.
    2026-04-28 신설 (TR_D [데드존_위_설치] fix 2).
    Shapely 객체 / dict 둘 다 처리. design.py 는 좌표 직접 결정 X 지만
    anchor/reference_point/의도 결정 시 dead_zone 근처 피하도록 유도."""
    if not dead_zones:
        return ""

    lines = []
    for dz in dead_zones:
        if hasattr(dz, "centroid") and hasattr(dz, "area"):  # Shapely
            c = dz.centroid
            lines.append(f"- 중심 ({c.x:.0f}, {c.y:.0f}) mm, 면적 {dz.area:.0f} mm²")
        elif isinstance(dz, dict):
            cm = dz.get("center_mm") or [0, 0]
            cx, cy = (cm[:2] + [0, 0])[:2]
            r = dz.get("radius_mm", 0)
            tp = dz.get("type", "?")
            lines.append(f"- {tp}: 중심 ({float(cx):.0f}, {float(cy):.0f}) mm, 반경 {float(r):.0f} mm")

    if not lines:
        return ""

    return (
        "## 피해야 할 영역 (dead_zone) — 객체 배치 금지\n"
        "다음 좌표는 스프링클러/소화전/분전반/기둥/내벽/계단/화장실/비상구 등 "
        "구조·설비·법규 제약 영역. 객체의 anchor / reference_point 가 이 영역과 겹치지 않도록 의도를 설계.\n"
        + "\n".join(lines)
    )


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


def _build_ref_points_summary(reference_points: list, concept_areas: list = None) -> str:
    """reference_points → Agent 3용 요약 텍스트.

    concept_areas 있으면 영역별 그룹핑해서 보여줌 — LLM이 "어느 영역의 어느
    ref_point에 뭘 둘지" 판단하기 쉬워짐. 없으면 기존 플랫 리스트.
    """
    if not reference_points:
        return "(없음)"

    if concept_areas:
        groups: dict[str, list] = {}
        for rp in reference_points:
            ca = rp.get("concept_area", "미정")
            groups.setdefault(ca, []).append(rp)

        # concept_areas 선언 순서대로 출력, 뒤에 "미정" 그룹 붙이기
        area_order = [a.get("name", "") for a in concept_areas if a.get("name")]
        if "미정" in groups:
            area_order.append("미정")

        lines = []
        for area_name in area_order:
            rps = groups.get(area_name)
            if not rps:
                continue
            lines.append(f"\n### [{area_name}] 영역의 ref_point")
            for rp in rps:
                lines.append(_format_ref_point_line(rp))
        return "\n".join(lines).lstrip()

    # fallback: concept_areas 없으면 기존 플랫 리스트
    return "\n".join(_format_ref_point_line(rp) for rp in reference_points)


def _format_ref_point_line(rp: dict) -> str:
    """한 ref_point를 한 줄 텍스트로 (Shin build_space_summary 방식).

    2026-05-01 Phase 3-2: zone_label (large 항상 None) → concept_area (한국어) 표시.
    """
    rp_id = rp["id"]
    zone = rp.get("concept_area") or rp.get("zone_label") or "미정"
    label = rp.get("label", "")
    wall_len = rp.get("wall_length_mm", 0)

    line = f"- {rp_id}: {zone}"

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

    if wall_len > 0:
        if wall_len > 3000:
            line += f" [넓은 벽]"
        elif wall_len > 1500:
            line += f" [보통 벽]"
        else:
            line += f" [좁은 벽]"

        shelf_cap = max(1, wall_len // 1800)
        display_cap = max(1, wall_len // 1200)
        line += f"\n    수용 가능: shelf_wall 최대 {shelf_cap}개 / display_table 최대 {display_cap}개"

    return line


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

    LLM이 zone 제약을 무시했을 때 ref_point와 zone_label을 교정.
    """
    if not resolved_intents or not reference_points:
        return intents

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

    zone_rps: dict[str, list] = {}
    for rp in reference_points:
        if rp.get("_is_blocked") or rp.get("_all_blocked"):
            continue
        zone = rp.get("zone_label") or "mid_zone"
        zone_rps.setdefault(zone, []).append(rp)

    correctly_placed_rp_ids: set = set()
    for intent in intents:
        obj_type = intent.get("object_type", "")
        hints = hint_map.get(obj_type)
        if not hints or not hints.get("zone_hint"):
            continue
        rp_id = intent.get("ref_point_id")
        if rp_id and rp_map.get(rp_id, {}).get("zone_label") == hints["zone_hint"]:
            correctly_placed_rp_ids.add(rp_id)

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

            if zone == "entrance_zone":
                preferred = [rp for rp in candidates if rp.get("label") in _ENTRANCE_ZONE_PREFERRED_LABELS]
                if preferred:
                    candidates = preferred

            if candidates:
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
            intent["zone_label"] = required_zone
            logger.warning(
                f"[design:hint_enforce] {obj_type}: {required_zone} ref_point 없음 "
                f"— zone_label 보정만 적용"
            )

    return intents
