"""
건물 유형(venue_type)별 배치 규제 사전 — Single Source of Truth.

규칙 추가/제거는 이 파일만 수정. 모든 노드에서 `from app.venue_rules import ...`로 사용.

카테고리:
  [소방법]    — 방화셔터, 비상구, 감압구역 등
  [전력]      — 분전반 근접성, 배선 제약
  [건축]      — 파사드 확장, 쇼윈도 시야
  [동선]      — 복도 버퍼, 통로 폭
  [높이]      — 시야 제한, 층고 제약

각 규칙에 **법령 근거** 또는 **실무 근거**를 inline 주석으로 명시.
"""

# ── 기본값 ──────────────────────────────────────────────────────────────
DEFAULT_VENUE_TYPE = "street_complex"  # 가장 엄격한 유형 — 안전한 기본값


# ── 표시 라벨 (LLM 프롬프트·UI용) ────────────────────────────────────────
VENUE_LABELS = {
    "street_complex": "집합 상가 (상업건축물)",
    "street_standalone": "단독 로드샵 (개인건축물)",
}


# ── 규제 규칙 사전 ──────────────────────────────────────────────────────
# 규칙명 = 값 형식. True/False 플래그 또는 mm 단위 수치.
# 주석 규칙:
#   [카테고리] 설명. 근거: 법령/실무 출처
#
# 새 규칙 추가 시:
#   1. 아래 두 venue_type 모두에 동일 키 추가 (누락 시 기본값 폴백)
#   2. 주석에 근거 명시
#   3. 사용하는 노드에서 venue_rules.get(key) 참조

VENUE_RULES = {
    "street_complex": {
        # ── [전력] ──
        "mep_power_constraint": True,       # counter ↔ 분전반 3000mm 이내 강제. 근거: 집합 상가는 분전반 위치 고정, 바닥 매립 불가

        # ── [소방법] ──
        "fire_shutter_check": True,         # 방화셔터 하강 라인 양쪽 500mm 버퍼 침범 차단. 근거: 공용 복도 천장 셔터 99% 존재 (파서 데이터 있을 때만 동작)

        # ── [건축] ──
        "facade_expansion": False,          # 계약 면적(usable_poly) 외부 배치 금지. 근거: 집합 상가 통제 엄격
        "show_window_penalty": True,        # 유리면 근처 shelf_wall 시야 차단 시 감점. 근거: 쇼윈도 시야 확보 상업 원칙

        # ── [동선] ──
        "corridor_half_buffer_mm": 300,     # 보조동선 반버퍼 (합 600mm)

        # ── [높이] ──
        "entrance_max_height_mm": 1200,     # entrance_zone 중앙부 높이 제한. 근거: R4 시야 확보 원칙
    },

    "street_standalone": {
        # ── [전력] ──
        "mep_power_constraint": False,      # 단상 배선 연장 자유, 3000mm 제한 해제. 근거: 단독 건물 전력 자율성

        # ── [소방법] ──
        "fire_shutter_check": False,        # 내부 방화셔터 없음. 근거: 외부 직접 연결 단독 건물

        # ── [건축] ──
        "facade_expansion": True,           # 외부 영역(배너, 웨이팅 기기) 배치 조건부 허용. 근거: 통임대 단독 상가 권한
        "show_window_penalty": False,       # 감점 없음. 근거: 파사드 자율 설계

        # ── [동선] ──
        "corridor_half_buffer_mm": 300,     # 소형 동일

        # ── [높이] ──
        "entrance_max_height_mm": 1200,     # 동일
    },
}


# ── 조회 함수 ───────────────────────────────────────────────────────────
def get_venue_rules(venue_type: str | None) -> dict:
    """venue_type → 규칙 딕셔너리. 미지정/오타 시 DEFAULT_VENUE_TYPE."""
    return VENUE_RULES.get(venue_type or DEFAULT_VENUE_TYPE, VENUE_RULES[DEFAULT_VENUE_TYPE])


def get_venue_label(venue_type: str | None) -> str:
    """venue_type → 표시 라벨."""
    return VENUE_LABELS.get(venue_type or DEFAULT_VENUE_TYPE, venue_type or DEFAULT_VENUE_TYPE)
