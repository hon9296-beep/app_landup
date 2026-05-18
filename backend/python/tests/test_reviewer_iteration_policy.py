"""
B4 (1-3 #533) — reviewer iteration 정책 일관성 검증.

design_reviewer (MAX_REVIEW_ITERATIONS) 와 placement_reviewer (MAX_PLACEMENT_REVIEW_ITERATIONS)
의 한도 정책 일관성 강제. 변경 시 양쪽 동시 검토 필수.

회귀 차단:
- MAX=1 폐기 (1-3 #530 fix — 첫 reject 도 한도 도달 회귀)
- MAX=3+ 회피 (LLM variance 누적 + 비용 ↑)
- 적정 = 2 (1회 retry — 진규님 비전 + 비용 균형)
"""
from app.nodes_small.design_reviewer import (
    MAX_REVIEW_ITERATIONS,
    SIMILARITY_THRESHOLD,
)
from app.nodes_small.placement_reviewer import MAX_PLACEMENT_REVIEW_ITERATIONS


def test_design_reviewer_max_is_1():
    """MAX_REVIEW_ITERATIONS = 1 (1-3 후속 #535 후속 D — retry 무용 fix)."""
    assert MAX_REVIEW_ITERATIONS == 1


def test_placement_reviewer_max_is_1():
    """MAX_PLACEMENT_REVIEW_ITERATIONS = 1 (D — design_reviewer 와 일관)."""
    assert MAX_PLACEMENT_REVIEW_ITERATIONS == 1


def test_max_iterations_consistency():
    """B4 핵심: 두 reviewer 의 MAX 가 일관 — 변경 시 양쪽 동시 검토 강제."""
    assert MAX_REVIEW_ITERATIONS == MAX_PLACEMENT_REVIEW_ITERATIONS, (
        f"design_reviewer MAX={MAX_REVIEW_ITERATIONS} vs placement_reviewer MAX={MAX_PLACEMENT_REVIEW_ITERATIONS} "
        f"불일치 — 정책 일관성 위반. 변경 시 양쪽 동시 갱신 필수."
    )


def test_max_iterations_in_range():
    """MAX 적정 범위 검증 (1-3 후속 #535 후속 D 변경 후).

    1-3 #530 fix 시 MAX=1 회귀 차단 (첫 reject 한도 도달) — 단 그 이후
    MAX=2 가 실효 X (5-7 라이브 분석: retry 가 같은 회귀 반복).
    1-3 후속: MAX=1 채택 + 결정적 fix (pair_rules / prompt / placement priority).
    """
    assert 1 <= MAX_REVIEW_ITERATIONS <= 3
    assert 1 <= MAX_PLACEMENT_REVIEW_ITERATIONS <= 3


def test_max_iterations_not_too_high():
    """MAX=4+ 차단 — LLM variance 누적 + 비용 ↑. 적정 한도."""
    assert MAX_REVIEW_ITERATIONS <= 3
    assert MAX_PLACEMENT_REVIEW_ITERATIONS <= 3


def test_similarity_threshold_in_valid_range():
    """SIMILARITY_THRESHOLD: 직전 intents 와 0.95 이상 동일 시 수렴 검출 — 무한 retry 방지."""
    assert 0.8 <= SIMILARITY_THRESHOLD <= 1.0
