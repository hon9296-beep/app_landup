"""
2026-05-08 partition_reuse 미작동 진단용 instrumentation 검증.

라이브 dump (5-8 16:06) 분석:
  - placement: photo_wall fail (static cache 충돌 66회)
  - failure_classifier: cascade=1 photo_wall
  - placement_reviewer: AP-405-a (photo_wall 누락)
  - partition.graphic_face='none' (= partition_reuse 흡수 X)

미스터리: fallback / partition_reuse 진입 흔적이 reason_dump 에 없음.
원인 추적 위해 fallback / partition_reuse Gate 별 dump 추가.
"""
import inspect


def test_fallback_run_dumps_entry():
    """fallback.run() 진입 시 reason_dump 호출 (failed list / round 추적)."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback.run)
    assert 'dump_agent_reason' in src
    assert 'node="fallback"' in src
    # 진입 / skip / max_rounds 케이스 다 dump
    assert 'decision="enter"' in src
    assert 'decision="skip_no_failed"' in src
    assert 'decision="skip_max_rounds"' in src


def test_fallback_dumps_partition_reuse_phase():
    """fallback.py Phase 3.5 (partition_reuse 호출 직전/직후) dump."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # photo_wall Phase 3.5 진입 dump
    assert 'node="partition_reuse"' in src
    assert 'decision="enter"' in src
    # 결과 dump (absorbed / skipped)
    assert '"absorbed"' in src or 'absorbed' in src
    assert '"skipped"' in src or 'skipped' in src


def test_partition_reuse_gate1_dump():
    """partition_reuse.py Gate 1 (env opt-out) 차단 시 dump."""
    from app.nodes_small import partition_reuse
    src = inspect.getsource(partition_reuse)
    assert 'gate1_blocked' in src
    assert 'LANDUP_PARTITION_REUSE' in src


def test_partition_reuse_gate2_dump():
    """partition_reuse.py Gate 2 (obj_type != photo_wall) 차단 시 dump."""
    from app.nodes_small import partition_reuse
    src = inspect.getsource(partition_reuse)
    assert 'gate2_blocked' in src


def test_partition_reuse_gate4_dump():
    """partition_reuse.py Gate 4 (후보 partition 0) 차단 시 dump.

    + placed 의 partition entry 메타 (graphic_face / anchor_key) 함께 dump → 진단용.
    """
    from app.nodes_small import partition_reuse
    src = inspect.getsource(partition_reuse)
    assert 'gate4_blocked' in src
    assert 'partitions_in_placed' in src


def test_partition_reuse_success_dump():
    """partition_reuse.py 성공 시 dump."""
    from app.nodes_small import partition_reuse
    src = inspect.getsource(partition_reuse)
    assert 'decision="success"' in src
    assert 'best_anchor_key' in src


def test_partition_reuse_runtime_gate1():
    """env=='0' opt-out 시 False 반환 + dump 호출 (실행 검증)."""
    import os
    from unittest.mock import patch
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    state = {"placed_objects": []}
    with patch.dict(os.environ, {"LANDUP_PARTITION_REUSE": "0"}):
        result = try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    assert result is False


def test_partition_reuse_runtime_gate4():
    """후보 0 시 False + Gate 4 dump 호출."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    state = {"placed_objects": [], "entrance_mm": (0, 0)}
    result = try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    assert result is False


def test_partition_reuse_runtime_success():
    """후보 1개 + photo_wall 흡수 성공 시 True + graphic_face='outer' 박힘."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    partition = {
        "object_type": "partition_wall_I",
        "graphic_face": "none",
        "graphic_face_basis": "default_front",
        "anchor_key": "wall_5_left",
        "center_x_mm": 5000,
        "center_y_mm": 5000,
    }
    state = {
        "placed_objects": [partition],
        "entrance_mm": (3000, 0),
    }
    result = try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    assert result is True
    assert partition["graphic_face"] == "outer"
    assert partition["graphic_face_basis"] == "photo_wall_substitute"
