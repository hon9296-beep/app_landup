"""
B3 (1-3 #533) — AP-405 정밀화 contract 검증.

이전 AP-405 description = "통합 layout sanity check" 한 줄 → 5 케이스 분기 (a~e):
  (a) structural anchor zone 부적합
  (b) fallback_phase 강제 끼워박힘
  (c) zone 폭증 / 분포 불균형
  (d) 매뉴얼 obj drop + default obj 가 자리 차지
  (e) ref_analysis 정상인데 inspired_by_ref 거의 빈값

placement_reviewer LLM_REVIEWER_SYSTEM 도 동기화 — 5 케이스 (a~e) 명시.
"""
from app.nodes_small.anti_patterns import PLACEMENT_ANTI_PATTERNS
from app.nodes_small.prompts.placement_reviewer import LLM_REVIEWER_SYSTEM


def _ap405():
    return next(a for a in PLACEMENT_ANTI_PATTERNS if a["id"] == "AP-405")


# ── AP-405 description 정밀화 ───────────────────────────────────────


def test_ap405_description_long_enough():
    """B3: description 100 자 이상 (이전 약 30 자 짧음 회귀 차단)."""
    assert len(_ap405()["description"]) >= 100


def test_ap405_includes_5_case_keywords():
    """B3: AP-405 의 5 케이스 (a~e) 핵심 단어 포함."""
    desc = _ap405()["description"]
    # (a) structural anchor zone 부적합
    assert "structural anchor" in desc
    # (b) fallback_phase
    assert "fallback_phase" in desc or "fallback" in desc
    # (c) zone 폭증 / 분포 불균형
    assert "폭증" in desc or "분포" in desc or "집중" in desc or "균형" in desc
    # (d) 매뉴얼 obj drop
    assert "매뉴얼" in desc and "drop" in desc
    # (e) ref 영감
    assert "ref_analysis" in desc or "inspired_by_ref" in desc


def test_ap405_validator_type_llm():
    """AP-405 = LLM 영역 (python validator stub)."""
    assert _ap405()["validator_type"] == "llm"


def test_ap405_severity_warning():
    """AP-405 = warning (LLM 이 자율 판정으로 blocking 승격 가능)."""
    assert _ap405()["severity"] == "warning"


# ── placement_reviewer SYSTEM 동기화 ─────────────────────────────────


def test_reviewer_system_includes_5_cases():
    """B3: placement_reviewer LLM_REVIEWER_SYSTEM 의 [판정 기준 적극 reject] 가 AP-405 5 케이스 명시."""
    # (a) structural anchor zone 부적합
    assert "structural anchor" in LLM_REVIEWER_SYSTEM
    # (b) fallback_phase
    assert "fallback_phase" in LLM_REVIEWER_SYSTEM
    # (c) zone 분포 / 균형
    assert "zone" in LLM_REVIEWER_SYSTEM
    # (d) 매뉴얼 obj drop
    assert "매뉴얼" in LLM_REVIEWER_SYSTEM and "drop" in LLM_REVIEWER_SYSTEM
    # (e) ref_analysis 영감
    assert "ref_analysis" in LLM_REVIEWER_SYSTEM or "inspired_by_ref" in LLM_REVIEWER_SYSTEM


def test_reviewer_system_has_5_case_marker():
    """B3: 5 케이스 marker (a/b/c/d/e) 또는 'AP-405' 5 케이스 라벨 명시."""
    has_case_marker = (
        "(a)" in LLM_REVIEWER_SYSTEM
        and "(b)" in LLM_REVIEWER_SYSTEM
        and "(c)" in LLM_REVIEWER_SYSTEM
        and "(d)" in LLM_REVIEWER_SYSTEM
        and "(e)" in LLM_REVIEWER_SYSTEM
    )
    assert has_case_marker, "5 케이스 marker (a/b/c/d/e) 부재"
