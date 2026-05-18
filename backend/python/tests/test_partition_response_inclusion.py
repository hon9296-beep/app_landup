"""
가벽 응답 포함 회귀 차단 — B-2 (1-3 후속 #535 후속).

회귀 사유:
  2026-05-05 sub-graph 도입 (PR #506/#507) 시 partition_placement 가 박는
  `_partition_placed_raw` 키가 SmallState 정의에 없어 LangGraph state reduce 에서
  누락. placement.py 가 그 키 읽으려 하면 항상 [] → placed_polygons 시작값에 가벽
  포함 못 함 → placed_objects 응답에 가벽 누락 → 프론트/GLB 둘 다 가벽 안 보임.

회귀 시점 (debug_logs 추적):
  2026-05-04: ✅ placed_objects[0]=partition_wall_I 정상
  2026-05-06: ❌ placed_objects 에 partition_wall 없음
  2026-05-07: ❌ 지속

fix:
  placement.py 가 SmallState 정의된 `placed_partitions` 키 우선 참조.
  fallback 으로 `_partition_placed_raw` 도 유지 (backward compat).
"""
import inspect

from app.nodes_small import placement, partition_placement
from app.state import SmallState


# ── SmallState 필드 정의 ─────────────────────────────────────


def test_smallstate_has_placed_partitions_field():
    """SmallState 에 placed_partitions 필드 정의 — sub-graph reduce 시 보존."""
    assert "placed_partitions" in SmallState.__annotations__, (
        "SmallState 에 placed_partitions 필드 누락 — sub-graph state reduce 시 가벽 정보 손실"
    )


# ── partition_placement.run() return contract ────────────────


def test_partition_placement_returns_placed_partitions_key():
    """partition_placement.run() 이 placed_partitions 키 반환 (state.py 정의 일치)."""
    src = inspect.getsource(partition_placement.run)
    assert '"placed_partitions"' in src, (
        "partition_placement.run() 이 placed_partitions 키 반환 안 함"
    )


# ── placement.py 가 placed_partitions 우선 참조 ───────────────


def test_placement_reads_placed_partitions_first():
    """placement.run() 이 placed_partitions 키 우선 참조 (B-2 fix 핵심).

    회귀: placement 가 _partition_placed_raw 만 참조하면 sub-graph 에서 항상 [] 반환.
    fix: placed_partitions 우선, _partition_placed_raw fallback.
    """
    src = inspect.getsource(placement.run)
    assert 'state.get("placed_partitions")' in src, (
        "placement.run() 이 placed_partitions 직접 참조 안 함 — sub-graph 진입 시 가벽 누락 회귀 가능"
    )


def test_placement_partition_fallback_order():
    """우선순위 검증: placed_partitions 가 _partition_placed_raw 보다 먼저 참조."""
    src = inspect.getsource(placement.run)
    pos_placed = src.find('"placed_partitions"')
    pos_raw = src.find('"_partition_placed_raw"')
    # 둘 다 존재
    assert pos_placed >= 0, "placed_partitions 참조 누락"
    # _partition_placed_raw 는 fallback 으로 유지 (backward compat). 없어도 OK
    if pos_raw >= 0:
        assert pos_placed < pos_raw, (
            f"우선순위 잘못: placed_partitions 가 _partition_placed_raw 보다 먼저 참조해야 함"
        )


# ── 회귀 가드 ────────────────────────────────────────────────


def test_no_legacy_only_partition_placed_raw():
    """placement.run() 이 _partition_placed_raw 단독 참조 (placed_partitions 없이) 회귀 차단."""
    src = inspect.getsource(placement.run)
    # _partition_placed_raw 만 있으면 회귀 (B-2 fix 무효화)
    if '"_partition_placed_raw"' in src:
        assert '"placed_partitions"' in src, (
            "_partition_placed_raw 만 참조 = B-2 fix 회귀 (sub-graph 에서 항상 [] 반환)"
        )


def test_partition_placement_state_key_consistency():
    """partition_placement 가 박는 키 ↔ placement 가 읽는 키 일관성."""
    pp_src = inspect.getsource(partition_placement.run)
    pl_src = inspect.getsource(placement.run)

    # partition_placement 가 placed_partitions 박음
    assert '"placed_partitions"' in pp_src
    # placement 가 placed_partitions 읽음
    assert '"placed_partitions"' in pl_src, (
        "partition_placement 박음 vs placement 안 읽음 — state 키 불일치 회귀"
    )
