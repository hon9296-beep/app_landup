"""
#263 B 안 — RefAnalysisDict TypedDict + is_ref_analysis_empty helper 단위 테스트.

배경:
- ref_image_analyzer 가 flat dict 반환 (envelope X)
- 5-1 A-fix (1725cb2) 가 envelope 가정 (status/result) 제거 임시 처리
- 본 PR (#263) 이 정식 TypedDict 정의 + helper 통일

검증:
- RefAnalysisDict 가 8 필드 명세 보유 (VisionAnalysisResult Pydantic 과 1:1)
- is_ref_analysis_empty 가 4 path (None / 빈 dict / 정상 / 부분) 정확히 판정
- design.py 의 envelope 회귀 차단 (sample 데이터)
"""
from app.state import RefAnalysisDict, is_ref_analysis_empty


# ── RefAnalysisDict 명세 검증 ────────────────────────────────────────


def test_ref_analysis_dict_accepts_all_8_fields():
    """VisionAnalysisResult 의 8 필드 모두 입력 가능."""
    full: RefAnalysisDict = {
        "layout_patterns": ["좌우 대칭 배치"],
        "partition_usage": ["반투명 가벽"],
        "focal_points": ["중앙 포토존"],
        "flow_description": "입구→체험→포토→상담",
        "density_impression": "적당한 밀도",
        "space_mood": "밝고 화사",
        "composition_principle": "비대칭",
        "design_highlights": ["조명 연출"],
    }
    assert full["layout_patterns"] == ["좌우 대칭 배치"]
    assert full["composition_principle"] == "비대칭"


def test_ref_analysis_dict_accepts_empty():
    """total=False 라 빈 dict 도 valid (analyzer 비정상 path 반환값)."""
    empty: RefAnalysisDict = {}
    assert empty == {}


def test_ref_analysis_dict_accepts_partial():
    """일부 필드만 — total=False 효과. analyzer 가 일부만 채워도 OK."""
    partial: RefAnalysisDict = {
        "layout_patterns": ["테스트"],
        "flow_description": "동선 설명",
    }
    assert "layout_patterns" in partial
    assert "focal_points" not in partial


# ── is_ref_analysis_empty helper ─────────────────────────────────────


def test_is_ref_analysis_empty_for_empty_dict():
    """빈 dict → True (analyzer 비정상 path 4종 모두 빈 dict 반환)."""
    assert is_ref_analysis_empty({}) is True


def test_is_ref_analysis_empty_for_none():
    """None → True (state.get('ref_analysis') 가 미설정 시)."""
    assert is_ref_analysis_empty(None) is True


def test_is_ref_analysis_empty_for_normal_result():
    """8 필드 채워진 정상 결과 → False."""
    normal: RefAnalysisDict = {
        "layout_patterns": ["A"],
        "focal_points": ["B"],
        "design_highlights": ["C"],
    }
    assert is_ref_analysis_empty(normal) is False


def test_is_ref_analysis_empty_for_single_field():
    """1 필드만 채워진 부분 결과 → False (envelope 가정 X — 키 존재만으로 valid)."""
    single: RefAnalysisDict = {"flow_description": "x"}
    assert is_ref_analysis_empty(single) is False


# ── 회귀 차단: envelope (status/result) 가정 사용 시 ──────────────────


def test_envelope_assumption_does_not_match_helper():
    """5-1 A-fix 케이스 — envelope (status/result) 가정 dict 가 실제 analyzer 출력 아님.

    옛 design.py 는 ref_analysis.get('result') 검사로 항상 None → empty 판정.
    helper 는 status/result 키 무시 — envelope 자체가 비정상 형식이라도 키 있으면 non-empty.
    """
    envelope_like = {"status": "ok", "result": {}}
    # envelope 형식이지만 키 자체가 있으니 non-empty (analyzer 는 절대 이런 형식 반환 X — 회귀 신호)
    assert is_ref_analysis_empty(envelope_like) is False


def test_helper_signature_matches_state_field():
    """state.RefAnalysisDict 가 SmallState/LargeState 의 ref_analysis 타입과 일치.
    `from __future__ import annotations` 효과로 type hint 가 ForwardRef → typing.get_type_hints 로 resolve."""
    from typing import get_type_hints
    from app.state import SmallState, LargeState
    assert get_type_hints(SmallState)["ref_analysis"] is RefAnalysisDict
    assert get_type_hints(LargeState)["ref_analysis"] is RefAnalysisDict
