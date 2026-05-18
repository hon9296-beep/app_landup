"""
1-3 (#533) 후속 — 입구 감압존 반경 single source 동기화 검증.

진규님 2026-04-22 결정: 소형 (nodes_small, 0~50평 미만 / 165m² 미만) 18평 도면 기준
1500→900 하향. slot_gen 만 적용된 상태에서 anti_patterns / ref_point_gen 은 1500 잔존
하던 회귀 차단.

회귀 시 발생 문제:
- slot 은 입구 앞 900mm 만 비웠는데 ref_point_gen 은 1500mm 비움 → ref_point 없는 floating slot
- AP-001 reviewer 가 1500mm 기준으로 reject → 진규님 의도 (소형 900) 와 어긋남

Single source: app.nodes_small.slot_gen.DECOMPRESSION_RADIUS_MM
"""
from app.nodes_small.slot_gen import DECOMPRESSION_RADIUS_MM as SLOT_DECOMP
from app.nodes_small.ref_point_gen import DECOMPRESSION_RADIUS_MM as REFPT_DECOMP
from app.nodes_small.anti_patterns import (
    ENTRANCE_FRONT_CLEAR_MM,
    SECONDARY_DECOMPRESSION_RADIUS_MM,
)


def test_slot_gen_decomp_baseline():
    """slot_gen.DECOMPRESSION_RADIUS_MM 현재 baseline 검증.

    히스토리:
    - 2026-04-22: 1500 → 900 (18평 photo_wall drop 3/3 해소, 커밋 ff64521)
    - 2026-05-07 1차: 900 → 1200 라이브 — photo_wall 1개 박힘 (standalone)
    - 2026-05-07 2차: 1200 → 900 revert 라이브 — photo_wall drop (1200 보다 나쁜 결과)
    - 2026-05-07 3차: 900 → 1200 재채택 — 1200 이 일관되게 더 나은 결과 확증

    값 변경 시 본 baseline + 다른 곳 (ref_point_gen / anti_patterns) 자동 동기 검증.
    """
    assert SLOT_DECOMP == 1200


def test_ref_point_gen_decomp_synced():
    """ref_point_gen 의 DECOMPRESSION_RADIUS_MM 가 slot_gen 과 동일."""
    assert REFPT_DECOMP == SLOT_DECOMP, (
        f"ref_point_gen={REFPT_DECOMP} vs slot_gen={SLOT_DECOMP} 불일치 — "
        f"slot 은 입구 앞 {SLOT_DECOMP}mm 비웠는데 ref_point 는 {REFPT_DECOMP}mm 비움 → "
        f"ref_point 없는 floating slot 회귀."
    )


def test_anti_patterns_entrance_front_clear_synced():
    """anti_patterns.ENTRANCE_FRONT_CLEAR_MM (AP-001/AP-105) 가 slot_gen 과 동일.

    AP-001: 단일 입구 매장 입구 정면 가벽/대형 obj 금지 임계.
    slot_gen 이 입구 앞 900mm 비웠으면 reviewer 도 900mm 기준으로 검증해야 일관.
    """
    assert ENTRANCE_FRONT_CLEAR_MM == SLOT_DECOMP, (
        f"ENTRANCE_FRONT_CLEAR_MM={ENTRANCE_FRONT_CLEAR_MM} vs slot_gen={SLOT_DECOMP} 불일치 — "
        f"reviewer 가 진규님 의도보다 엄격하게 reject."
    )


def test_anti_patterns_secondary_decompression_synced():
    """anti_patterns.SECONDARY_DECOMPRESSION_RADIUS_MM (AP-102) 가 slot_gen 과 동일.

    AP-102: 2~N번째 입구 감압존 침범 검증 — 첫 입구 감압존과 같은 기준.
    """
    assert SECONDARY_DECOMPRESSION_RADIUS_MM == SLOT_DECOMP, (
        f"SECONDARY_DECOMPRESSION_RADIUS_MM={SECONDARY_DECOMPRESSION_RADIUS_MM} vs slot_gen={SLOT_DECOMP} 불일치."
    )


def test_all_three_sources_identical():
    """3개 모듈 (slot_gen / ref_point_gen / anti_patterns) 입구 감압존 반경 일치.

    진규님이 slot_gen 만 바꿔도 자동 동기화 되는 구조 검증.
    """
    values = {
        "slot_gen": SLOT_DECOMP,
        "ref_point_gen": REFPT_DECOMP,
        "anti_patterns.ENTRANCE_FRONT_CLEAR_MM": ENTRANCE_FRONT_CLEAR_MM,
        "anti_patterns.SECONDARY_DECOMPRESSION_RADIUS_MM": SECONDARY_DECOMPRESSION_RADIUS_MM,
    }
    unique_values = set(values.values())
    assert len(unique_values) == 1, (
        f"입구 감압존 반경 불일치 — {values}. "
        f"single source (slot_gen.DECOMPRESSION_RADIUS_MM) 사용 검증."
    )


def test_decomp_in_reasonable_range():
    """입구 감압존 반경이 합리적 범위 (600~3000mm) — 극단값 회귀 차단.

    600 미만: 인간 통과 폭도 안 됨 → 무의미.
    3000 초과: 소형 매장 deep_zone 절반 이상 잠식 (Phase 3-C 자문 medium 상한).
    Phase 3-C 면적별 동적화 시 micro 1200 / standard 1800 / medium 2400~3000 권장.
    """
    assert 600 <= SLOT_DECOMP <= 3000
