"""
reference (brand 매뉴얼 추출) BRAND prompt / Tool schema — #491 prompts 중앙화.

BRAND_TOOL.input_schema.brand_category.enum 은 categories.py 의 llm_extractable_keys()
로 모듈 load 시점에 동적 생성. categories.py 의 is_llm_extractable=True 토글하면
enum 자동 반영.
"""

from app.categories import llm_extractable_keys as _llm_extractable_keys

BRAND_SYSTEM = """당신은 팝업스토어 브랜드 메뉴얼에서 공간 배치 제약 조건을 추출하는 전문가입니다.
정확히 명시된 내용만 추출하고, 문서에 없는 내용은 절대 추측하지 마세요.

## 단위 변환 규칙 (항상 적용)
- cm → mm: ×10 (예: 50cm → 500)
- m  → mm: ×1000 (예: 1.2m → 1200)
- clearspace_mm, logo_clearspace_mm가 범위로 표현된 경우 (예: 300~500mm) → 최솟값 사용 (예: 300)

## confidence 판단 기준
- high:   수치나 명칭이 문서에 명확히 적혀있음
- medium: 언급은 있지만 해석이 필요한 경우
- low:    암시적이거나 불분명한 경우, 또는 문서에 없어서 null인 경우

## 수량 규칙 (min_count, max_count)
- 문서에 숫자로 명확히 적혀있을 때만 설정 (예: "최소 2개", "3개 이상")
- 명시되지 않은 경우 반드시 null — 절대 추측하지 말 것
- "메인", "대표", "주요" 같은 수식어는 수량 근거가 아님 → null

## 오브젝트 타입 정의 (매뉴얼 항목 분류 기준)
- character_bbox: 바닥에 독립으로 서는 3D 입체물. 브랜드 마스코트·캐릭터·피규어·오브제·설치물 등 시각적 포인트가 되는 모든 입체 오브젝트
- photo_wall: 벽/가벽에 밀착하는 포토 배경 패널·그래픽 월 (flush, 벽면 평행)
- photo_island: 벽에 붙지 않고 사방이 열린 360도 포토 구조물·조형물 (free, 중앙 독립)
- counter: 직원이 서서 고객 응대·결제를 처리하는 테이블형 구조물
- display_table: 바닥에 독립으로 서는 상품 진열 테이블 (아일랜드형)
- shelf_wall: 벽에 부착하거나 벽에 세우는 상품 진열 선반
- shelf_3tier: 바닥에 독립으로 서는 다단 선반
- banner_stand: 천·패브릭·인쇄물을 걸어두는 세로형 스탠드
- signage_stand: A형 입간판, 방향·정보 안내 표지판
- kiosk: 무인 결제기·터치스크린 안내 단말기
- partition_wall_I: 공간 분리용 일자형 임시 벽체
- partition_wall_L: 공간 분리용 ㄱ자형 코너 벽체"""

BRAND_PROMPT = """아래 브랜드 매뉴얼에서 배치 규칙을 추출하세요.
문서에 명시되지 않은 항목은 value를 null, confidence를 low로 설정하세요.
수치는 반드시 mm 정수로 변환하세요."""

# 2026-05-01 SSOT 마이그레이션: brand_category enum 은 app.categories.llm_extractable_keys()
# 로 자동 생성. BRAND_TOOL 정의 시점 (module load) 에 한번 평가됨.
# Drift 방지 — 신규 LLM 추출 카테고리 추가 시 categories.py 의 is_llm_extractable=True 만
# 토글하면 enum 에 자동 반영.
from app.categories import llm_extractable_keys as _llm_extractable_keys

BRAND_TOOL = {
    "name": "extract_brand_rules",
    "description": "브랜드 매뉴얼에서 공간 배치 제약 조건을 구조화하여 추출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand_category": {
                "type": "string",
                "enum": _llm_extractable_keys(),
                "description": "브랜드 카테고리. 명시되지 않으면 '기타'.",
            },
            "clearspace_mm": {
                "type": "object",
                "properties": {
                    "value": {"type": ["integer", "null"], "description": "이격 거리 (mm 정수). cm→×10, m→×1000 변환."},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["value", "confidence"],
            },
            "character_orientation": {
                "type": "object",
                "properties": {
                    "value": {"type": ["string", "null"], "enum": ["입구 정면", "벽면", "자유", None]},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["value", "confidence"],
            },
            "prohibited_material": {
                "type": "object",
                "properties": {
                    "value": {"type": ["string", "null"], "description": "금지 소재. 없으면 null."},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["value", "confidence"],
            },
            "logo_clearspace_mm": {
                "type": "object",
                "properties": {
                    "value": {"type": ["integer", "null"], "description": "로고 여백 (mm 정수). 없으면 null."},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["value", "confidence"],
            },
            "pair_rules": {
                "type": "array",
                "description": "오브젝트 쌍 간 관계 규정. 문서에 명시된 것만. 없으면 빈 배열.",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_a": {
                            "type": "string",
                            "description": "오브젝트 타입 ID (영문 snake_case). 매뉴얼에 명시된 기물을 자유롭게 명명.",
                        },
                        "object_b": {
                            "type": "string",
                            "description": "오브젝트 타입 ID (영문 snake_case). 매뉴얼에 명시된 기물을 자유롭게 명명.",
                        },
                        "relation": {"type": "string", "enum": ["join", "separate", "adjacent"]},
                        "min_gap_mm": {"type": "integer", "description": "최소 간격 (join이면 0)"},
                    },
                    "required": ["object_a", "object_b", "relation", "min_gap_mm"],
                },
            },
            "figures_mentioned": {
                "type": "array",
                "description": "매뉴얼에 언급된 독립 입체 조형물 목록. 상품 판매·진열 목적이 아닌, 시각적 포인트·포토존·공간 연출 목적으로 공간에 단독 배치되는 3D 오브젝트. 캐릭터 조형물·마스코트 피규어·아트 오브제·브랜드 상징물 등이 해당. 진열대·선반·계산대·배너·가벽은 제외. 없으면 빈 배열.",
                "items": {"type": "string"},
            },
            "placement_rules": {
                "type": "array",
                "description": "집기별 배치 규정. 문서에 명시된 것만. 없으면 빈 배열.",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "description": (
                                "오브젝트 타입 ID — 반드시 표준 목록 중 하나만 사용 (영문 snake_case). "
                                "표준 목록: counter, display_table, display_table_standard, character_bbox, "
                                "photo_wall, photo_island, shelf_wall, shelf_wall_standard, test_bar, "
                                "consultation_desk, shelf_3tier, banner_stand, partition_wall_I, "
                                "partition_wall_L, signage_stand, kiosk, aux_table. "
                                "[분류 책임은 LLM] 매뉴얼이 'mooni_figure', 'consultation_table' 처럼 자유 명명을 사용해도 "
                                "의미상 가장 가까운 표준 ID 로 매핑하여 object_type 에 기입할 것 — "
                                "예: 'mooni_figure'(캐릭터 피규어) → 'character_bbox', "
                                "'consultation_table'(상담 테이블) → 'consultation_desk', "
                                "'pos_counter'(POS 카운터) → 'counter'. "
                                "매뉴얼의 raw 명명은 name 필드에 별도 보존."
                            ),
                        },
                        "name": {
                            "type": "string",
                            "description": (
                                "매뉴얼에 명시된 raw 명명 (자유 텍스트). "
                                "object_type 이 표준 ID 로 통일됐을 때 매뉴얼 어휘 보존용. "
                                "매장 표시 + 같은 std_id 내 개체 분리 (mooni vs stella) 키로 사용. "
                                "매뉴얼이 별도 명칭 없으면 object_type 의 std_id 그대로 기입."
                            ),
                        },
                        "preferred_wall": {"type": ["string", "null"]},
                        "required_direction": {"type": ["string", "null"]},
                        "width_mm": {"type": ["integer", "null"]},
                        "depth_mm": {"type": ["integer", "null"]},
                        "height_mm": {"type": ["integer", "null"]},
                        "min_count": {"type": ["integer", "null"]},
                        "max_count": {"type": ["integer", "null"]},
                        "max_count_source": {
                            "type": "string",
                            "enum": ["manual", "inferred"],
                            "description": "manual: 매뉴얼에 숫자로 명확히 명시됨. inferred: 명시 없이 추측한 값.",
                        },
                        "front_clearance_mm": {
                            "type": ["integer", "null"],
                            "description": "전면 최소 이격 거리 (mm). 매뉴얼에 '전면 개방 공간', '대기 공간', '촬영 거리' 등으로 명시된 값. 없으면 null.",
                        },
                        "back_clearance_mm": {
                            "type": ["integer", "null"],
                            "description": "후면 최소 이격 거리 (mm). 매뉴얼에 '후방 이격', '벽면 이격' 등으로 명시된 값. 없으면 null.",
                        },
                        "wall_attachment": {
                            "type": ["string", "null"],
                            "enum": ["flush", "near", "free"],
                            "description": "벽 밀착 속성. flush=벽 밀착, near=벽 근처, free=자유 배치. 매뉴얼에 '벽면 부착', '벽면에서 띄워' 등 명시 시 추출. 없으면 null.",
                        },
                        "preferred_zone": {
                            "type": ["string", "null"],
                            "enum": ["entrance_zone", "mid_zone", "deep_zone"],
                            "description": "권장 배치 존. 매뉴얼에 '입구', '중앙', '후방', '출구 방향' 등 위치 지시가 있으면 매핑. 없으면 null.",
                        },
                    },
                    "required": ["object_type"],
                },
            },
        },
        "required": [
            "brand_category", "clearspace_mm", "character_orientation",
            "prohibited_material", "logo_clearspace_mm", "pair_rules", "placement_rules",
            "figures_mentioned",
        ],
    },
}
