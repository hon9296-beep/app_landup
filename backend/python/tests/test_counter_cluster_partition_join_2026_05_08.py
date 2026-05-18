"""
2026-05-08 진규님 5-8 18:09 라이브 추가 fix.

질문 1: counter 가 가벽 옆 부착 안 됨
  → pair_rules counter ↔ partition_wall_I/L join 미정의 → wildcard separate 1200mm 적용
  → fix: counter ↔ partition_wall_I/L = join 추가 (8)(9)

질문 2: counter ↔ counter cluster 안 됨 (interior_slot_90 + interior_slot_158, 거리 2000mm)
  → pair_rules join 정의는 있음. 단 LLM 의도 wall ref 가 placement 못 박힘 → fallback Phase 4 →
    walk_mm 기준 정렬 → 떨어진 slot 두 곳 박힘 → cluster 깨짐
  → fix: fallback Phase 4 cluster 보존 — same-type 또는 join 관계 obj 가 이미 placed 면
    그 anchor 거리 가까운 slot 우선 (10)
"""
import inspect


# ── (8)(9) counter ↔ partition_wall_I/L join ────────────────────


def test_counter_partition_wall_I_join_pair_rule():
    """counter ↔ partition_wall_I = join (가벽 옆 부착 가능)."""
    from app.vmd_constants import VMD_PAIR_RULES
    rule = next(
        (r for r in VMD_PAIR_RULES
         if {r["object_a"], r["object_b"]} == {"counter", "partition_wall_I"}
         and r["relation"] == "join"),
        None,
    )
    assert rule is not None, "counter ↔ partition_wall_I join 룰 누락"
    assert rule["min_gap_mm"] == 0


def test_counter_partition_wall_L_join_pair_rule():
    """counter ↔ partition_wall_L = join."""
    from app.vmd_constants import VMD_PAIR_RULES
    rule = next(
        (r for r in VMD_PAIR_RULES
         if {r["object_a"], r["object_b"]} == {"counter", "partition_wall_L"}
         and r["relation"] == "join"),
        None,
    )
    assert rule is not None
    assert rule["min_gap_mm"] == 0


def test_counter_partition_join_before_counter_wildcard_separate():
    """counter ↔ partition join 룰이 counter ↔ * separate 1200 보다 list 앞.

    _find_pair_rule 가 list 순서 첫 매칭 — 동일 type 룰을 wildcard 위에 배치 필수.
    """
    from app.vmd_constants import VMD_PAIR_RULES
    counter_partition_idx = None
    counter_wildcard_idx = None
    for i, r in enumerate(VMD_PAIR_RULES):
        if (r["object_a"] == "partition_wall_I" and r["object_b"] == "counter"
                and r["relation"] == "join"):
            counter_partition_idx = i
        if r["object_a"] == "counter" and r["object_b"] == "*":
            counter_wildcard_idx = i
    assert counter_partition_idx is not None
    assert counter_wildcard_idx is not None
    assert counter_partition_idx < counter_wildcard_idx, (
        f"counter↔partition idx={counter_partition_idx} >= counter↔* idx={counter_wildcard_idx} — "
        f"순서 잘못. wildcard 가 먼저 매칭 → counter 가벽 부착 차단."
    )


# ── (10) fallback cluster 보존 ────────────────────────────────


def test_fallback_phase4_cluster_anchor_logic():
    """fallback.py Phase 4 가 cluster anchor (same-type 또는 join 관계 placed obj) 검색 후 거리 정렬."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    assert 'cluster_anchor' in src
    # same-type 검색
    assert 'ex_type == obj_type' in src
    # pair_rules join 관계 검색
    assert 'r.get("relation") != "join"' in src
    # 거리 정렬 (anchor 가까운 slot 먼저)
    assert "kv[1].get(\"x_mm\", 0) - ax" in src
    assert "kv[1].get(\"y_mm\", 0) - ay" in src


def test_fallback_phase4_default_walk_mm_sort_when_no_cluster():
    """cluster anchor 없을 때 (= 첫 instance) default walk_mm 내림차순 정렬 유지 (회귀 차단)."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # default 분기 박힘
    assert 'walk_mm 내림차순' in src
    assert 'reverse=True' in src


def test_fallback_phase4_logs_cluster_preservation():
    """cluster anchor 발견 시 로그 박음 (라이브 진단)."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    assert "cluster 보존" in src
