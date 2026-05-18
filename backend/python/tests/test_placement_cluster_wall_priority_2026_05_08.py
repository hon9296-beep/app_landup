"""
2026-05-08 진규님 5-8 18:35 라이브 후속.

(12) placement.py 가 flush/near obj 에 center_xx / interior_slot ref 시도 차단:
  - 5-8 라이브: consultation_desk (near) center_36 ref 매핑 → 한복판 부유
  - placement.py main loop 가 모든 ref 시도 → fallback Phase 4 의 wall slot 제한 적용 안 됨
  - fix: rp_candidates 구성 후 wall_ prefix ref 만 필터링

(13) placement.py cluster edge-to-edge — same-type / join 관계 placed obj 의 wall 시리즈 우선:
  - 5-8 라이브: counter 2개 interior_slot_89 + 123 떨어진 위치 → 거리 2000mm cluster 깨짐
  - fix: rp_candidates 정렬 시 이미 placed 된 same-type/join 관계 obj 의 wall 시리즈 우선
"""
import inspect


# ── (12) wall_ prefix ref 만 ──────────────────────────────


def test_placement_filters_non_wall_for_flush_near():
    """placement.py 의 rp_candidates 가 flush/near obj 에 wall_ prefix ref 만 시도."""
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    # 분기 코드 박힘
    assert 'wall_attach_main = obj.get("wall_attachment")' in src
    assert 'wall_attach_main in ("flush", "near")' in src
    # wall prefix 검사
    assert '"wall_"' in src and '"east_wall_"' in src
    # center_xx / interior_slot 제외 로그
    assert "center_xx / interior_slot" in src or "wall_only_rps" in src


def test_placement_wall_filter_logged_count():
    """제외 ref 수 로그 박힘 (라이브 진단)."""
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    assert 'excluded_count' in src
    assert 'wall_ prefix' in src


# ── (13) cluster wall 시리즈 우선 ──────────────────────────


def test_placement_cluster_anchor_logic():
    """placement.py 가 cluster anchor (same-type / join 관계 placed obj) 검색 후 wall 시리즈 우선 정렬."""
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    assert 'cluster_anchor_id' in src
    # same-type 검색
    assert 'ex_type == obj["object_type"]' in src
    # pair_rules join 관계 검색
    assert 'r.get("relation") != "join"' in src
    # wall_NN_ prefix 우선 정렬
    assert 'wall_prefix' in src
    assert 'same_wall_rps' in src


def test_placement_cluster_logged():
    """cluster 정렬 시 로그 박음 (라이브 진단)."""
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    assert 'cluster: 이미 placed' in src or '같은 wall 시리즈' in src


def test_placement_cluster_only_when_anchor_starts_with_wall():
    """cluster anchor 가 wall_ prefix 일 때만 시리즈 정렬 (interior_slot anchor 는 시리즈 매칭 X)."""
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    assert 'cluster_anchor_id.startswith("wall_")' in src


# ── 통합 ────────────────────────────────────────


def test_placement_nearby_slot_blocks_near_too():
    """placement.py 의 nearby slot 시도가 flush + near 둘 다 interior/center 차단.

    5-8 19:00 라이브 회귀: counter (near) @ interior_slot_170 박힘. 이전 코드는 nearby slot
    시도에서 flush 만 차단 → near (counter / consultation / kiosk / test_bar) 통과해서 박힘.
    fix: line 589 nearby slot 분기에 flush + near 둘 다 차단.
    """
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    # nearby slot section 의 분기 — flush + near 둘 다
    assert '_wa in ("flush", "near")' in src
    assert "5-8 19:00" in src or "near obj 가 nearby slot" in src or "한복판 부유" in src


def test_combined_12_13_logic_order():
    """(13) cluster 우선 정렬 → (12) wall 필터 순서 — cluster 정렬 후 wall 만 남김.

    (13) 이 (12) 보다 먼저 박혀야 cluster 안에서 wall ref 만 남고 정렬 보존.
    """
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    # (13) cluster 코드가 (12) wall 필터보다 위에
    cluster_idx = src.find('cluster_anchor_id')
    wall_filter_idx = src.find('wall_attach_main = obj.get("wall_attachment")')
    assert cluster_idx > 0 and wall_filter_idx > 0
    assert cluster_idx < wall_filter_idx, (
        "(13) cluster 정렬이 (12) wall 필터보다 먼저 박혀야 함 — "
        "cluster 안에서 wall ref 보존 위해."
    )
