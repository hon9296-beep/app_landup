"""pillar_toilet_detect 프롬프트 — large 전용 (2026-05-05 burning_task 1단계).

도면 이미지에서 기둥(pillar)과 화장실(toilet) 만 검출. Haiku Vision 단순 판정.
별도 노드라 기존 vision 흐름 (sprinkler / fire_hydrant / electrical_panel) 영향 X.
"""


PILLAR_TOILET_DETECT_SYSTEM = """당신은 팝업스토어 도면 분석 전문가입니다.
도면 이미지에서 기둥(pillar)과 화장실(toilet) 영역만 검출합니다.
다른 요소 (가구, 동선, 스프링클러 / 소화전 / 분전반 등) 는 무시하세요.
검출 못 하면 빈 list 반환 — 추측 / 일반론 X. 명확한 패턴만 출력."""


PILLAR_TOILET_DETECT_TOOL = {
    "name": "detect_pillar_toilet",
    "description": "도면 이미지의 기둥과 화장실 영역 검출.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pillars": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x_px": {"type": "number", "description": "기둥 좌상단 x (px, 0 = 이미지 좌측)"},
                        "y_px": {"type": "number", "description": "기둥 좌상단 y (px, 0 = 이미지 상단)"},
                        "w_px": {"type": "number", "description": "기둥 폭 (px)"},
                        "h_px": {"type": "number", "description": "기둥 높이 (px)"},
                    },
                    "required": ["x_px", "y_px", "w_px", "h_px"],
                },
                "description": (
                    "기둥 위치 + 크기. 도면에서 보통 작은 사각형 (해치 / 검은 채움 / 진한 실선) 패턴. "
                    "공장형 / 큰 부지에 4–8개 분포. 가구 / 동선 X."
                ),
            },
            "toilets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x_px": {"type": "number", "description": "화장실 영역 좌상단 x (px)"},
                        "y_px": {"type": "number", "description": "화장실 영역 좌상단 y (px)"},
                        "w_px": {"type": "number", "description": "화장실 영역 폭 (px)"},
                        "h_px": {"type": "number", "description": "화장실 영역 높이 (px)"},
                        "label": {"type": "string", "description": "발견된 라벨 텍스트 (예: 'WC', '화장실', 'TOILET', '욕실')"},
                    },
                    "required": ["x_px", "y_px", "w_px", "h_px"],
                },
                "description": (
                    "화장실 영역 (사각 영역으로 단순화). 'WC' / '화장실' / 'TOILET' / '욕실' 텍스트 + 닫힌 영역 검출. "
                    "텍스트 없는 단순 닫힌 영역은 무시 (다른 데드존 가능성)."
                ),
            },
        },
        "required": ["pillars", "toilets"],
    },
}


PILLAR_TOILET_DETECT_PROMPT = """첨부된 도면 이미지에서 기둥과 화장실만 검출:

1. **기둥 (pillar)**: 작은 사각형 패턴 (해치 / 검은 채움 / 진한 실선). 공장형 / 큰 부지에 4–8개 분포 가능.
2. **화장실 (toilet)**: 'WC' / '화장실' / 'TOILET' / '욕실' 텍스트 + 닫힌 영역.

좌표 = 픽셀 단위 (이미지 좌상단 0,0 기준).

다른 요소 (가구 / 동선 / 스프링클러 / 분전반 등) 무시.
검출 못 하면 빈 list 반환 — 추측 X."""
