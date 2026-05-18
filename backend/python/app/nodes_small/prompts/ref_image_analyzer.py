"""
ref_image_analyzer Vision LLM prompt / Tool schema — #491 prompts 중앙화.
"""

VISION_ANALYSIS_SYSTEM = """당신은 팝업스토어/전시 공간 디자인 분석 전문가입니다.
제공된 레퍼런스 이미지를 꼼꼼히 관찰하고, 배치 설계에 활용할 수 있는 구조화된 패턴을 추출합니다.
이미지에서 보이는 것만 기술하세요. 추측이나 일반론은 제외.

[필수 사전 판정 1 — is_real_photo (batch 단위)]
분석 전 반드시 이미지가 '실제로 시공된 매장/전시 공간을 촬영한 사진' 인지 판별합니다.
공간 자체가 보여야 함 (벽 / 바닥 / 천장 / 가구 배치 등). 단일 피사체 클로즈업은 공간 정보 부재로 reject.

- 매장/전시 공간 실사 (벽·바닥·가구 배치 보임) → is_real_photo=true, reject_reason="실사"
- 3D 렌더링 / CG / 합성 시각화 → is_real_photo=false, reject_reason="3D 렌더"
- 일러스트레이션 / 그림 / 스케치 → is_real_photo=false, reject_reason="일러스트"
- 2D 평면도 / 도면 / 다이어그램 → is_real_photo=false, reject_reason="2D 도면"
- 단일 피사체 클로즈업 (캐릭터 굿즈 / 인물 셀카·화보 / 제품 컷 / 음식 close-up 등 — 실사여도 공간 정보 미포함) → is_real_photo=false, reject_reason="단일_피사체"
- 그 외 비실사 → is_real_photo=false, reject_reason="기타 비실사"

[카테고리별 자주 잡히는 함정 패턴 — 절대 통과시키지 말 것]
- "캐릭터 IP" 검색: 단일 캐릭터 일러스트 / 굿즈 패키지 클로즈업이 빈번. **매장 공간이 보이지 않으면 reject.**
- "패션 브랜드" 검색: 룩북 모델 사진 / 의류 컷이 빈번. **매장 인테리어가 아니면 reject.**
- "F&B" 검색: 음식 클로즈업 / 메뉴판 사진이 빈번. **카페·매장 공간이 아니면 reject.**
- "뷰티·코스메틱" 검색: 제품 패키지 컷 / 모델 화보 빈번. **매장 공간이 아니면 reject.**

[필수 사전 판정 2 — per-image 카테고리 부합 검증 (1-3 #523 신규)]
batch 가 is_real_photo=true 통과해도 **개별 이미지가 명시된 카테고리에 부합하는지** 0..N-1 인덱스 단위로 판정.

- 명백히 다른 업종 매장 (예: '뷰티·코스메틱' 검색에 성인용품 매장 / 의류 매장 / 음식점 등) → rejected_image_indices 에 해당 인덱스 추가 + rejected_image_reasons 에 사유 자연어
- 카테고리 매칭 모호 (예: 라이프스타일 편집숍에 뷰티 코너 일부 보임) → 통과. 명백한 mismatch 만 reject.

판정 기준 (다른 업종 식별):
- 매장 사인보드 / 브랜드 명 / 제품군이 다른 업종을 명백히 가리킴 (예: TENGA 사인 = 성인용품, 약국 / 음식점 사인 = 다른 업종)
- 진열 제품군이 카테고리와 명백히 불일치 (예: 뷰티 검색에 자전거 / 가전 / 의류만 진열)
- 카테고리 모호하면 통과 (over-reject 방지)

[per-image 거부 → 결과 처리]
rejected_image_indices 에 박힌 이미지는 통합 분석에서 제외 — layout_patterns / focal_points 등은 **거부 안 된 이미지만 기반**으로 작성.
rejected_image_indices 가 모든 이미지 (예: 5장 모두) 면 통합 분석 빈 배열.

is_real_photo=false 인 경우에도 나머지 필드는 빈 배열 / 빈 문자열로 채워 schema 만 만족시키면 됩니다 (호출자가 결과를 폐기).
오직 is_real_photo=true 인 이미지에 대해서만 layout_patterns / focal_points / 등 본 분석을 수행하세요."""


# Anthropic tool use schema — JSON 강제 (수동 파싱 X)
VISION_ANALYSIS_TOOL = {
    "name": "analyze_reference_images",
    "description": "팝업스토어 레퍼런스 이미지를 분석해 배치 설계 참조용 구조화 데이터 추출.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_real_photo": {"type": "boolean", "description": "실제로 시공된 물리적 공간을 촬영한 사진인지 여부 — false 면 호출자가 분석 결과 폐기"},
            "reject_reason": {"type": "string", "description": "판정 사유 — '실사' / '3D 렌더' / '일러스트' / '2D 도면' / '단일_피사체' / '기타 비실사' 중 하나"},
            "rejected_image_indices": {"type": "array", "items": {"type": "integer"}, "description": "1-3 (#523) 신규 — 카테고리에 명백히 부합 안 하는 이미지의 0-base 인덱스 list (예: 뷰티 검색에 성인용품 매장 = 거부). 모호하면 통과. is_real_photo=false 시 빈 배열."},
            "rejected_image_reasons": {"type": "array", "items": {"type": "string"}, "description": "1-3 (#523) 신규 — rejected_image_indices 와 같은 순서. 거부 사유 자연어 (예: 'TENGA 사인보드 보임 — 성인용품 매장'). is_real_photo=false 시 빈 배열."},
            "layout_patterns": {"type": "array", "items": {"type": "string"}, "description": "종합적으로 관찰된 구체적 배치 패턴 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 배열)"},
            "partition_usage": {"type": "array", "items": {"type": "string"}, "description": "가벽/파티션 활용 방식 (rejected 제외 이미지 기반. 없으면 '가벽 미사용', is_real_photo=false 시 빈 배열)"},
            "focal_points": {"type": "array", "items": {"type": "string"}, "description": "시선 집중 포인트와 위치 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 배열)"},
            "flow_description": {"type": "string", "description": "방문자 동선 흐름 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 문자열)"},
            "density_impression": {"type": "string", "description": "공간 밀도감 + 벽면 활용도 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 문자열)"},
            "space_mood": {"type": "string", "description": "공간 전체 분위기 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 문자열)"},
            "composition_principle": {"type": "string", "description": "구성 원리 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 문자열)"},
            "design_highlights": {"type": "array", "items": {"type": "string"}, "description": "디자인적 눈에 띄는 연출 (rejected 제외 이미지 기반. is_real_photo=false 시 빈 배열)"},
        },
        "required": [
            "is_real_photo", "reject_reason",
            "rejected_image_indices", "rejected_image_reasons",
            "layout_patterns", "partition_usage", "focal_points",
            "flow_description", "density_impression", "space_mood", "composition_principle", "design_highlights",
        ],
    },
}


# 옛 수동 파싱 시절 prompt — tool use 전환 후 미사용. 방어선으로 보존 (tool 정의 깨질 시 fallback).
VISION_ANALYSIS_PROMPT = """위 이미지들을 분석해서 아래 JSON 형식으로 출력하세요. 다른 텍스트 없이 JSON만.

[JSON 문법 엄수 — 2026-04-20 파싱 에러 대응]
- 문자열 값 내부에 **큰따옴표(") 절대 사용 금지**. 파싱 에러 원인.
- 강조/인용이 필요하면 **홑따옴표(')**, 대괄호([]), 소괄호(()) 사용.
- 예: "style": "미니멀 '파스텔' 톤" (OK), "style": "미니멀 "파스텔" 톤" (금지).
- 모든 문자열은 한 줄로 작성. 문자열 값 내부에 줄바꿈(\\n) 넣지 말 것.

제공된 이미지 순서대로 `per_image_analysis` 배열에 **각 이미지별 개별 분석**을 채우세요.
각 이미지의 `applicable_fixtures`는 다음 fixture_role 중에서만 선택:
`checkout` (계산대), `graphic_wall` (포토월/그래픽월), `display_wall` (벽면 선반/진열),
`display_rack` (3단 선반), `display_island` (아일랜드 진열대), `test` (시연대),
`consultation` (상담 데스크), `partition` (가벽), `character` (캐릭터 조형물),
`interactive` (키오스크), `signage` (안내판), `banner` (배너).

```json
{
  "per_image_analysis": [
    {
      "index": 0,
      "detected_content": "이미지에 실제로 보이는 것을 구체적으로 (예: 중앙 아일랜드 테이블 2개 + 벽면 선반 3개 + 계산대 1개, 파스텔 톤, 자연광)",
      "style": "스타일 키워드 (예: 미니멀 파스텔, 인더스트리얼, 레트로 등)",
      "key_elements": ["주요 요소 3~5개 리스트"],
      "applicable_fixtures": ["이 이미지가 참고됨직한 fixture_role 리스트 (위 목록에서만)"],
      "usage_intent": "design LLM이 이 이미지를 어떤 배치 의도에 쓸지 한 문장 (예: photo_wall을 입구 정면에 세워 파스텔 배경으로 활용)"
    }
  ],
  "layout_patterns": [
    "종합적으로 관찰된 구체적 배치 패턴 (예: 벽면을 따라 선반 3개 연속 배치, 중앙에 아일랜드형 테이블 2개)"
  ],
  "partition_usage": [
    "가벽/파티션 활용 방식 (예: 포토존 배경으로 사용 + 캐릭터 그래픽 부착, 체험존과 판매존 분리용)",
    "가벽이 없다면 '가벽 미사용'이라고 기술"
  ],
  "focal_points": [
    "시선이 집중되는 포인트와 위치 (예: 입구 정면에 대형 캐릭터 조형물, 안쪽 벽에 포토존 배경)"
  ],
  "flow_description": "방문자 동선 흐름 (입구에서 시작해서 어떤 순서로 이동할 것 같은지)",
  "density_impression": "공간 밀도감 (빽빽한/적당한/여유로운) + 벽면 활용도",
  "space_mood": "공간 전체 분위기 (따뜻한/차가운/활기찬/차분한/고급스러운 등)",
  "composition_principle": "구성 원리 (대칭/비대칭, 중앙집중/분산, 동선유도 방식 등)",
  "design_highlights": [
    "디자인적으로 눈에 띄는 연출 (조명, 색상, 소재, 그래픽, 가벽 활용 등)"
  ]
}
```"""
