"""
ref_image_analyzer 프롬프트·스키마 — large 전용.

디자인 친화적 노드 전략 Phase 1: 프롬프트를 노드 로직에서 분리.
상세: docs/docs-shin/main_tasks/2026-04-24_디자인친화적노드전략.md

Phase 2 (예정): aspects/ 폴더로 다각도 분석 변형 (layout/mood/composition/flow) 신설.

대형(large) 자율성 지향 — fixture_role 매핑 강제 X. 추상 패턴·분위기·구성 원리만 추출.
design LLM 이 이 텍스트를 받아 "어느 기물에 어떻게 쓸지" 자율 해석.
"""

VISION_ANALYSIS_SYSTEM = """당신은 팝업스토어/전시 공간 디자인 분석 전문가입니다.
제공된 레퍼런스 이미지를 꼼꼼히 관찰하고, 배치 설계에 활용할 수 있는 구조화된 패턴을 추출합니다.
이미지에서 보이는 것만 기술하세요. 추측이나 일반론은 제외."""


# Tool use 패턴 — Anthropic 의 스키마 강제로 파싱 실패 원천 차단.
# 2026-04-24 large 채택 (small 은 2026-04-20 Tier 1-4 에서 도입).
# 2026-05-03: 8 → 10 종 확장 (color_palette + lighting_mood 추가, 자율도 우선 보수적 default).
# material_texture / signage_style / crowd_density / seasonal_cue 는 후순위 (디자인 도메인 협의 후).
VISION_ANALYSIS_TOOL = {
    "name": "analyze_reference_images",
    "description": (
        "팝업스토어 레퍼런스 이미지의 추상적 배치 패턴·분위기·구성 원리 추출. "
        "기물 매핑·위치 선정은 design LLM 자율 해석에 맡김 (large 자율성 지향)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "layout_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "구체적 배치 패턴. **각 패턴에 위치(어디) + 분포(어떻게 퍼졌는지) 를 반드시 명시** "
                    "(2026-05-05 트랙 1 임베딩 매칭 강화 — placed_because 와 cosine 매칭 표면적 ↑). "
                    "분포 예: 단독 / 1열 정렬 / 클러스터 / 균등 분산. "
                    "(예: 좌측 벽면 따라 선반 3개 1열 분포, 중앙 아일랜드 테이블 2개 단독 배치)"
                ),
            },
            "partition_usage": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "가벽/파티션 활용 방식. **위치(어디) + 분포(몇 개, 어떻게 배치)** 명시 필수. "
                    "(예: 입구 우측에 L자 가벽 1개로 포토존 분리, 중앙에 I자 가벽 2개 평행 분포). "
                    "없으면 '가벽 미사용'"
                ),
            },
            "focal_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "시선 집중 포인트. **위치(어디) + 분포(단독/클러스터/분산)** 명시 필수. "
                    "(예: 입구 정면 단독 대형 캐릭터, 중앙+측벽 2점 분산 디스플레이)"
                ),
            },
            "flow_description": {
                "type": "string",
                "description": (
                    "방문자 동선 흐름 한 문장. **위치 변화(어디→어디→어디) 순서대로** 명시 필수. "
                    "(예: 입구→우측 벽면 진열대→중앙 포커스존→안쪽 결제 카운터 순환)"
                ),
            },
            "density_impression": {
                "type": "string",
                "description": "공간 밀도감 + 벽면 활용도 (예: 적당한 밀도, 벽면 약 60% 가 오브젝트로 채워짐)",
            },
            "space_mood": {
                "type": "string",
                "description": "공간 전체 분위기 (예: 밝고 활기찬, 파스텔 톤 위주 / 차분하고 고급스러운, 우드+골드)",
            },
            "composition_principle": {
                "type": "string",
                "description": "구성 원리 (예: 비대칭 분산 배치, 벽면 활용 + 중앙 아일랜드 조합)",
            },
            "design_highlights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "디자인적 눈에 띄는 연출 (예: 천장 간접 조명으로 포토존 강조, 바닥 브랜드 컬러 라인)",
            },
            "color_palette": {
                "type": "string",
                "description": "주조 색상 + 보조 색상 (예: 주조 화이트+우드, 보조 핑크 포인트 / 주조 블랙+골드, 보조 네온 그린). 2026-05-03 추가",
            },
            "lighting_mood": {
                "type": "string",
                "description": "조명 톤 + 분위기 (예: 따뜻한 전구색 간접조명 / 차가운 화이트 LED 직접조명 / 네온 컬러 강조). 2026-05-03 추가",
            },
            "area_size_emphasis": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "영역별 면적 강조도 (concept_area 의 size_hint 결정 근거). "
                    "이미지에서 어느 영역이 크게 / 작게 잡혔는지 자연어로 추출. "
                    "**영역 종류 + 강조 등급(큰/중/작) + 근거** 명시. "
                    "(예: 포토존 큰 — 중앙 면적 절반 차지하며 시선 집중 / "
                    "결제 작은 — 우측 모서리 미니멀 카운터 1개 / "
                    "체험 중간 — 좌측 벽면 따라 디스플레이 분포). "
                    "2026-05-06 burning_task 2단계 본질 정비 — concept_area 비율 결정 LLM 자율 근거."
                ),
            },
        },
        "required": [
            "layout_patterns", "partition_usage", "focal_points",
            "flow_description", "density_impression", "space_mood",
            "composition_principle", "design_highlights",
            "color_palette", "lighting_mood",
            "area_size_emphasis",
        ],
    },
}


# Tool use 사용 후 USER 프롬프트는 보조 안내만 (스키마가 강제하므로 예시 JSON 불필요).
# 카테고리 컨텍스트만 동적 주입하고 스키마가 필드 의도를 전달.
VISION_ANALYSIS_PROMPT_TEMPLATE = (
    "아래는 '{category}' 카테고리 팝업스토어/전시 공간의 레퍼런스 이미지 {count}장입니다.\n"
    "각 이미지를 주의 깊게 관찰하고, 배치 설계에 참고할 추상적 패턴·분위기·구성 원리를 분석해주세요.\n"
    "tool 스키마 필드 description 을 따라 각 항목을 채우세요."
)
