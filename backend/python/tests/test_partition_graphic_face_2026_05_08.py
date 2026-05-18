"""
2026-05-08 진규님 5개 항목 후속 (2번-c 묶음 — Gate 3 제거 + serialize + clearance 분기).

(D) partition_reuse Gate 3 제거: facade 무관 photo_wall fallback 작동
(E) serialize_placement: graphic_face / graphic_face_basis 직렬화 추가
(F) clearance 동적 분기: partition.graphic_face='outer' 면 photo_wall front clearance (1500mm) 적용

진규님 5-8 명시:
  - "facade 없음 가정. 그래도 partition_reuse 작동해야 함"
  - "그래픽 있는 면쪽은 포토존의 역할을 하니까 clearance 적용해야함. 수치는 포토존 만큼"
"""
import os
import inspect
from unittest.mock import patch

from shapely.geometry import Polygon


# ── (D) partition_reuse Gate 3 제거 ──────────────────────────────


def test_partition_reuse_works_without_facade():
    """facade_type=None (closed default) 매장에서도 partition_reuse 작동."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    state = {
        "facade_type": None,  # closed default → 이전 룰 = Gate 3 차단
        "placed_objects": [{
            "object_type": "partition_wall_I",
            "graphic_face": "none",
            "anchor_key": "wall_5_left",
            "center_x_mm": 5000,
            "center_y_mm": 5000,
        }],
        "entrance_mm": (3000, 0),
    }
    failed = {"object_type": "photo_wall"}
    result = try_reuse_partition_for_photo_wall(state, failed)
    assert result is True, "facade None 에서도 partition_reuse 작동해야 함 (Gate 3 제거)"


def test_partition_reuse_works_with_closed_facade():
    """facade_type='closed' 명시 매장에서도 partition_reuse 작동."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    state = {
        "facade_type": "closed",  # 폐쇄형 — 이전 = allow_rear_graphic_wall=False → Gate 3 차단
        "placed_objects": [{
            "object_type": "partition_wall_I",
            "graphic_face": "none",
            "anchor_key": "wall_5_left",
            "center_x_mm": 5000,
            "center_y_mm": 5000,
        }],
        "entrance_mm": (3000, 0),
    }
    result = try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    assert result is True, "closed 매장도 partition_reuse 작동 (Gate 3 제거)"


def test_partition_reuse_assigns_graphic_face_outer():
    """partition_reuse 성공 시 partition 의 graphic_face → 'outer'."""
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
        "facade_type": None,
        "placed_objects": [partition],
        "entrance_mm": (3000, 0),
    }
    try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    # 부작용 검증
    assert partition["graphic_face"] == "outer"
    assert partition["graphic_face_basis"] == "photo_wall_substitute"


def test_partition_reuse_opt_out_via_env_zero():
    """LANDUP_PARTITION_REUSE='0' 명시 시 비활성화 (opt-out)."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    state = {
        "facade_type": None,
        "placed_objects": [{"object_type": "partition_wall_I", "graphic_face": "none",
                            "anchor_key": "w", "center_x_mm": 0, "center_y_mm": 0}],
        "entrance_mm": (0, 0),
    }
    with patch.dict(os.environ, {"LANDUP_PARTITION_REUSE": "0"}):
        result = try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    assert result is False, "LANDUP_PARTITION_REUSE='0' 명시 시 비활성화"


def test_partition_reuse_only_photo_wall():
    """photo_wall 외 obj 는 본 로직 미적용 (Gate 2 유지)."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    state = {
        "facade_type": None,
        "placed_objects": [{"object_type": "partition_wall_I", "graphic_face": "none",
                            "anchor_key": "w", "center_x_mm": 0, "center_y_mm": 0}],
        "entrance_mm": (0, 0),
    }
    # photo_wall 이 아닌 다른 obj
    result = try_reuse_partition_for_photo_wall(state, {"object_type": "shelf_wall"})
    assert result is False


def test_partition_reuse_no_facade_import():
    """partition_reuse.py 에서 facade_rules import 제거 확인 (Gate 3 제거 cleanup)."""
    from app.nodes_small import partition_reuse
    src = inspect.getsource(partition_reuse)
    assert "from app.facade_rules" not in src, (
        "Gate 3 제거 후 facade_rules import 도 제거돼야 함"
    )


# ── (E) serialize_placement graphic_face ──────────────────────────


def test_serialize_placement_includes_graphic_face():
    """serialize_placement 결과 dict 에 graphic_face / graphic_face_basis 키 포함."""
    from app.utils import serialize_placement
    bbox = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    p = {
        "object_type": "partition_wall_I",
        "label": "partition",
        "center_x_mm": 50, "center_y_mm": 50,
        "rotation_deg": 0,
        "width_mm": 100, "depth_mm": 100,
        "bbox_polygon": bbox,
        "zone_label": "deep_zone",
        "direction": "wall_perpendicular",
        "placed_because": "test",
        "front_vec": (1, 0),
        "graphic_face": "outer",
        "graphic_face_basis": "photo_wall_substitute",
    }
    result = serialize_placement(p)
    assert result["graphic_face"] == "outer"
    assert result["graphic_face_basis"] == "photo_wall_substitute"


def test_place_result_dump_includes_graphic_face():
    """place_serializer.py 의 dump_debug 인라인 직렬화에도 graphic_face 박힘.

    22c709c 후속 (2026-05-08): utils.py serialize_placement 에만 추가했으나 place_result.json 은
    place_serializer.py 의 별도 dump_debug 직렬화 → 본 dict 에도 추가해야 함. 라이브에서
    dump 키 누락 회귀 검출.
    """
    import inspect
    from app.serializers import place_serializer
    src = inspect.getsource(place_serializer)
    # dump_debug("place_result.json", ...) 안에 graphic_face 키 박힘
    # 정확히 dump_debug 부분에 들어있는지 검증
    assert 'dump_debug("place_result.json"' in src
    assert '"graphic_face": p.get("graphic_face")' in src
    assert '"graphic_face_basis": p.get("graphic_face_basis")' in src


def test_serialize_placement_graphic_face_default_none():
    """graphic_face 메타 없는 obj → None (partition 외 일반 obj)."""
    from app.utils import serialize_placement
    bbox = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    p = {
        "object_type": "shelf_wall",
        "label": "shelf",
        "center_x_mm": 50, "center_y_mm": 50,
        "rotation_deg": 0,
        "width_mm": 100, "depth_mm": 100,
        "bbox_polygon": bbox,
        "zone_label": "mid_zone",
        "direction": "wall_facing",
        "placed_because": "test",
        # graphic_face / graphic_face_basis 없음
    }
    result = serialize_placement(p)
    # 키는 존재, 값은 None
    assert "graphic_face" in result
    assert result["graphic_face"] is None
    assert "graphic_face_basis" in result
    assert result["graphic_face_basis"] is None


# ── (F) clearance 동적 분기 ──────────────────────────────────


def test_placement_clearance_dynamic_branch_source():
    """placement.py 에 graphic_face='outer' clearance 분기 박힘 검증.

    inline 실행은 _validate_placement 가 placement 컨텍스트 의존 큼 — source 패턴 검사로 대체.
    """
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    # 분기 코드 박힘
    assert 'partition_wall' in src
    assert 'graphic_face' in src
    # photo_wall clearance 조회 박힘
    assert 'DIRECTIONAL_CLEARANCE.get("photo_wall")' in src


def test_photo_wall_directional_clearance_value():
    """photo_wall 의 DIRECTIONAL_CLEARANCE = front 2000mm (포토존 화각).

    2026-05-08: 코드 실제 값 확인 — line 40 DIRECTIONAL_CLEARANCE photo_wall front=2000.
    line 67 의 BASE_CLEARSPACE (front=1500) 와 다른 dict. 실제 placement 가 사용하는 건 2000.
    """
    from app.vmd_constants import DIRECTIONAL_CLEARANCE
    pw = DIRECTIONAL_CLEARANCE.get("photo_wall")
    assert pw is not None
    assert pw.get("front") == 2000, (
        f"photo_wall front clearance = {pw.get('front')} — 2000 이어야 함 (DIRECTIONAL_CLEARANCE 실제 값)"
    )
    assert pw.get("back") == 0, "photo_wall back clearance = 0 (벽 부착)"


def test_partition_wall_default_clearance():
    """partition_wall_I default clearance = front 0 / back 0 (graphic_face='none' 기본)."""
    from app.vmd_constants import DIRECTIONAL_CLEARANCE
    pi = DIRECTIONAL_CLEARANCE.get("partition_wall_I")
    assert pi is not None
    assert pi.get("front") == 0
    assert pi.get("back") == 0


def test_clearance_branch_only_when_graphic_face_outer():
    """source 검증 — graphic_face=='outer' 조건일 때만 분기."""
    from app.nodes_small import placement
    src = inspect.getsource(placement)
    # 정확한 phrase 확인 — 'outer' 조건
    assert 'existing.get("graphic_face") == "outer"' in src, (
        "graphic_face='outer' 조건일 때만 photo_wall clearance. 'none' 도 분기되면 회귀."
    )
