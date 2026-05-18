"""
파사드(facade) 타입별 배치 규칙 — Single Source of Truth.

venue_type(건물 소유 형태)과 별개로 파사드 형태가 배치 의사결정에 영향:
  - 그래픽 월(가벽 단면 그래픽) 허용 여부
  - 외부 시선 확보 중요도
  - 입구 쇼윈도 연출 필요 여부

규칙 추가/제거는 이 파일만 수정. design.py·placement.py 등에서 import해 사용.
"""

# ── 기본값 ──────────────────────────────────────────────────────────────
DEFAULT_FACADE_TYPE = "closed"  # 가장 흔한 형태 — 안전한 기본값


# ── 표시 라벨 (LLM 프롬프트·UI용) ────────────────────────────────────────
FACADE_LABELS = {
    "open_glass": "개방형 파사드 (전면 통유리, 백화점 오픈 인숍)",
    "show_window": "쇼윈도형 파사드 (유리창 일부, 가두상권 일반)",
    "closed": "폐쇄형 파사드 (출입문만, 벽으로 둘러싸임)",
}


# ── 파사드별 배치 규칙 ──────────────────────────────────────────────────
# 새 규칙 추가 시 모든 facade_type에 동일 키 추가 (누락 시 기본값 폴백)

FACADE_RULES = {
    "open_glass": {
        # ── [외부 노출] ──
        "external_visibility": True,        # 외부에서 매장 내부 시인. 근거: 전면 유리 파사드
        # ── [그래픽 월] ──
        "allow_rear_graphic_wall": True,    # 가벽 뒷면 그래픽 활용 허용. 근거: 유리 너머로 뒷면 시인 가능
        # ── [입구 중앙 배치] ──
        "entrance_center_block": True,       # 중앙에 큰 기물 배치 절대 금지(쇼윈도 시야 차단). 근거: 외부 시선 확보
        # ── [히어로 존 시인성] ──
        "hero_visibility_priority": True,    # 히어로 기물은 외부에서 보이는 위치 우선
    },
    "show_window": {
        "external_visibility": True,
        "allow_rear_graphic_wall": True,    # 유리창 있으면 조건부 허용
        "entrance_center_block": True,       # 쇼윈도 유리면 시야 확보
        "hero_visibility_priority": True,
    },
    "closed": {
        "external_visibility": False,       # 출입문 통과해야 내부 시인
        "allow_rear_graphic_wall": False,   # 외부 시선 없음 → 가벽 뒷면 그래픽 월 무의미
        "entrance_center_block": False,      # 외부 시야 차단 우려 없음
        "hero_visibility_priority": False,   # 내부 동선 기준으로 배치
    },
}


# ── 조회 함수 ───────────────────────────────────────────────────────────
def get_facade_rules(facade_type: str | None) -> dict:
    """facade_type → 규칙 딕셔너리. 미지정/오타 시 DEFAULT_FACADE_TYPE."""
    return FACADE_RULES.get(facade_type or DEFAULT_FACADE_TYPE, FACADE_RULES[DEFAULT_FACADE_TYPE])


def get_facade_label(facade_type: str | None) -> str:
    """facade_type → 표시 라벨."""
    return FACADE_LABELS.get(facade_type or DEFAULT_FACADE_TYPE, facade_type or DEFAULT_FACADE_TYPE)
