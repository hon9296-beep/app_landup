"""
I-5 / 2026-04-23 — design.py ref 컨텍스트 부재 시 LLM 스킵 + 룰 기반 fallback.

배경:
  DDG rate limit (신규 카테고리 첫 호출) / 크레딧 고갈 등으로 reference_images 0건이거나
  ref_analysis 실패 시, 기존엔 design.py LLM 을 빈 컨텍스트로 그대로 호출 → 토큰 $0.05+ 낭비.

  옵션 A (Gemini 자문 결과) 적용: ref 컨텍스트 부재 감지 → LLM 스킵 → _default_intents 분기.

검증:
  - LLM 호출 없이 design_intents 생성
  - design_fallback_reason = "REF_CONTEXT_MISSING"
  - intents 에 eligible 타입 포함
  - API 키 존재 여부와 무관하게 동작
"""
import os
from unittest.mock import patch

from app.nodes_small.design import run as design_run


def _make_minimal_state(
    *,
    reference_images: list = None,
    ref_analysis: dict = None,
    eligible_objects: list = None,
    reference_points: list = None,
    brand_category: str = "패션 브랜드",
    is_retry: bool = False,
) -> dict:
    """design.run() 분기 테스트용 최소 state 구성."""
    # `or` 는 빈 리스트([]) 를 falsy 로 치환하므로 `is None` 명시 비교 사용
    state = {
        "brand_data": {"brand": {"brand_category": brand_category}},
        "eligible_objects": eligible_objects if eligible_objects is not None else [
            {"object_type": "counter", "width_mm": 1500, "depth_mm": 600},
            {"object_type": "display_table", "width_mm": 1500, "depth_mm": 900},
        ],
        "reference_points": reference_points if reference_points is not None else [
            {"id": "rp_1", "zone_label": "entrance_zone", "label": "side_wall"},
            {"id": "rp_2", "zone_label": "deep_zone", "label": "deep_wall"},
        ],
        "reference_images": reference_images if reference_images is not None else [],
        "ref_analysis": ref_analysis if ref_analysis is not None else {},
        "zone_map": {},
        "usable_poly": None,
    }
    if is_retry:
        state["choke_feedback"] = "테스트 피드백"
        state["failed_objects"] = [{"object_type": "counter"}]
        state["placed_objects"] = []
    return state


# ── Fallback 트리거 케이스 ────────────────────────────────────────────

def test_fallback_when_no_reference_images():
    """reference_images 빈 리스트 → LLM 호출 없이 fallback."""
    state = _make_minimal_state(reference_images=[])

    with patch("app.nodes_small.design.Anthropic") as mock_anthropic:
        result = design_run(state)

    mock_anthropic.assert_not_called()
    assert result["design_fallback_reason"] == "REF_CONTEXT_MISSING"
    assert result["design_intents"]
    assert result["eligible_objects"] == state["eligible_objects"]


# 2026-04-29 (#309 cleanup): 아래 2개 stale 테스트 삭제.
# - test_fallback_when_analyzer_status_error (status=='error' 케이스)
# - test_fallback_when_ref_analysis_no_result (result 키 빈 dict 케이스)
# A-fix (commit 1725cb2) 에서 design.py 의 envelope 가정 (status/result 키) 제거 후
# flat dict 검사 (`_ref_analysis_empty = not ref_analysis`) 로 변경.
# 두 테스트는 envelope 시대 코드라 더 이상 fallback 분기 안 들어가서 mock_anthropic
# 호출됨 → assert_not_called() 실패.
# 빈 dict 케이스는 test_fallback_when_both_missing (아래) 가 이미 커버.


def test_fallback_when_both_missing():
    """reference_images + ref_analysis 둘 다 없음 → fallback (가장 흔한 케이스)."""
    state = _make_minimal_state(reference_images=[], ref_analysis={})

    with patch("app.nodes_small.design.Anthropic") as mock_anthropic:
        result = design_run(state)

    mock_anthropic.assert_not_called()
    assert result["design_fallback_reason"] == "REF_CONTEXT_MISSING"


# ── Fallback intents 내용 검증 ───────────────────────────────────────

def test_fallback_intents_contain_eligible_types():
    """fallback intents 에 eligible_objects 의 object_type 포함."""
    state = _make_minimal_state(reference_images=[])

    with patch("app.nodes_small.design.Anthropic"):
        result = design_run(state)

    intent_types = {i["object_type"] for i in result["design_intents"]}
    eligible_types = {o["object_type"] for o in state["eligible_objects"]}
    assert eligible_types.issubset(intent_types), \
        f"fallback 이 eligible 타입 {eligible_types - intent_types} 을 intent 로 변환하지 못함"


def test_fallback_preserves_eligible_objects():
    """fallback 경로에서도 eligible_objects 보존 (placement 노드로 전달)."""
    state = _make_minimal_state(reference_images=[])
    original_eligible = list(state["eligible_objects"])

    with patch("app.nodes_small.design.Anthropic"):
        result = design_run(state)

    assert result["eligible_objects"] == original_eligible


# ── Retry 시나리오 ──────────────────────────────────────────────────

def test_fallback_in_retry_mode():
    """is_retry=True 상태에서도 ref 부재면 fallback + retry merge 동작."""
    state = _make_minimal_state(reference_images=[], is_retry=True)

    with patch("app.nodes_small.design.Anthropic") as mock_anthropic:
        result = design_run(state)

    mock_anthropic.assert_not_called()
    assert result["design_fallback_reason"] == "REF_CONTEXT_MISSING"
    # retry 병합 후에도 intents 존재
    assert result["design_intents"]


# ── 경계 케이스 ─────────────────────────────────────────────────────

def test_no_eligible_objects_early_return():
    """eligible_objects 빈 경우 — fallback 분기 전에 이미 return (기존 로직 보존)."""
    state = _make_minimal_state(reference_images=[], eligible_objects=[])

    with patch("app.nodes_small.design.Anthropic") as mock_anthropic:
        result = design_run(state)

    mock_anthropic.assert_not_called()
    assert result["design_intents"] == []
    assert result["eligible_objects"] == []
    # eligible 없어서 fallback_reason 도 설정 안 됨 (기존 동작)
    assert "design_fallback_reason" not in result


def test_brand_category_dict_wrapped():
    """brand_category 가 {value, confidence, source} 래핑된 경우에도 동작."""
    state = _make_minimal_state(reference_images=[])
    state["brand_data"] = {
        "brand": {
            "brand_category": {"value": "패션 브랜드", "confidence": "high", "source": "manual"}
        }
    }

    with patch("app.nodes_small.design.Anthropic"):
        result = design_run(state)

    assert result["design_fallback_reason"] == "REF_CONTEXT_MISSING"
    assert result["design_intents"]


# ── LLM 정상 경로 (fallback 미진입) ─────────────────────────────────

def test_llm_path_when_ref_context_valid():
    """reference_images + ref_analysis 정상 → fallback 미진입, LLM 경로 실행."""
    state = _make_minimal_state(
        reference_images=[{"url": "x", "base64": "y", "media_type": "image/jpeg"}],
        ref_analysis={
            "status": "ok",
            "result": {"layout_patterns": ["전면 진열 강조"]},
        },
    )

    # API 키 없는 환경으로 강제 → 또 다른 fallback (API_KEY_MISSING) 으로 귀결.
    # 핵심은 REF_CONTEXT_MISSING 이 아니라는 것 — 즉 본 fallback 은 스킵됨
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
        result = design_run(state)

    # 본 I-5 fallback 은 안 타야 함
    assert result.get("design_fallback_reason") != "REF_CONTEXT_MISSING"
