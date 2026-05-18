"""
2026-05-08 partition_reuse 누락 fix 묶음 검증 (5-8 16:23 라이브 진단 후속).

진단 결과:
  - partition_reuse 호출됨 ✓ / 흡수 성공 ✓ / state.placed_objects 의 partition.graphic_face='outer' 박힘 ✓
  - 그러나 dump (place_serializer.py 가 state.placed_raw 직렬화) 에는 'none' → placed_raw 동기화 누락
  - 결과: placement_reviewer 가 photo_wall drop 으로 인식 → AP-405-a reject → design retry 무한 루프

fix:
  (A) partition_reuse.py 가 state.placed_raw 의 동일 partition entry 도 동기화 (anchor_key 매칭)
  (B) placement_reviewer prompt 에 partition.graphic_face='outer' 표시 + AP-405-a 흡수 인정 룰
"""
import inspect


# ── (A) partition_reuse placed_raw 동기화 ────────────────────


def test_partition_reuse_syncs_placed_raw():
    """partition_reuse.py 가 state.placed_raw 의 partition entry 동기화."""
    from app.nodes_small import partition_reuse
    src = inspect.getsource(partition_reuse)
    # placed_raw 동기화 코드 박힘
    assert 'state.get("placed_raw"' in src
    assert 'raw["graphic_face"] = "outer"' in src
    assert 'raw["graphic_face_basis"] = "photo_wall_substitute"' in src
    # anchor_key 매칭으로 식별
    assert 'raw.get("anchor_key") == best.get("anchor_key")' in src


def test_partition_reuse_runtime_syncs_both():
    """placed_objects + placed_raw 둘 다 graphic_face='outer' 박힘."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    # placed_raw 와 placed_objects 가 다른 dict (=실제 흐름 시뮬)
    raw_partition = {
        "object_type": "partition_wall_I",
        "graphic_face": "none",
        "graphic_face_basis": "default_front",
        "anchor_key": "wall_14_right",
        "center_x_mm": 5000,
        "center_y_mm": 3750,
    }
    serialized_partition = {
        "object_type": "partition_wall_I",
        "graphic_face": "none",
        "graphic_face_basis": "default_front",
        "anchor_key": "wall_14_right",
        "center_x_mm": 5000,
        "center_y_mm": 3750,
    }
    state = {
        "placed_objects": [serialized_partition],
        "placed_raw": [raw_partition],
        "entrance_mm": (3000, 0),
    }
    result = try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    assert result is True
    # 둘 다 동기화됨
    assert serialized_partition["graphic_face"] == "outer"
    assert raw_partition["graphic_face"] == "outer", (
        "placed_raw 의 partition entry 도 graphic_face='outer' 박혀야 함 (5-8 16:23 진단 fix)"
    )
    assert raw_partition["graphic_face_basis"] == "photo_wall_substitute"


def test_partition_reuse_label_distinguishes_graphic_wall():
    """흡수 성공 시 label = 'partition_wall_I (graphic_wall)' — 일반 가벽과 구분."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    raw = {
        "object_type": "partition_wall_I",
        "label": "partition_wall_I",
        "graphic_face": "none",
        "anchor_key": "wall_14_right",
        "center_x_mm": 5000, "center_y_mm": 3750,
    }
    serialized = dict(raw)
    state = {
        "placed_objects": [serialized],
        "placed_raw": [raw],
        "entrance_mm": (3000, 0),
    }
    try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    # 둘 다 label 변경됨
    assert serialized["label"] == "partition_wall_I (graphic_wall)"
    assert raw["label"] == "partition_wall_I (graphic_wall)"


def test_partition_reuse_runtime_anchor_match():
    """placed_raw 에 다른 anchor 의 partition 도 있을 때 best 의 anchor_key 매칭만 동기화."""
    from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
    raw_a = {
        "object_type": "partition_wall_I",
        "graphic_face": "none", "anchor_key": "wall_14_right",
        "center_x_mm": 5000, "center_y_mm": 3750,
    }
    raw_b = {
        "object_type": "partition_wall_I",
        "graphic_face": "none", "anchor_key": "wall_5_left",
        "center_x_mm": 1000, "center_y_mm": 2000,
    }
    serialized_a = dict(raw_a)
    serialized_b = dict(raw_b)
    state = {
        "placed_objects": [serialized_a, serialized_b],
        "placed_raw": [raw_a, raw_b],
        "entrance_mm": (3000, 0),
    }
    # entrance (3000,0) 거리 — wall_14_right (5000,3750) 거리 4609, wall_5_left (1000,2000) 거리 2828
    # → best = wall_5_left (더 가까움)
    try_reuse_partition_for_photo_wall(state, {"object_type": "photo_wall"})
    # best 만 동기화 (raw_b)
    assert raw_b["graphic_face"] == "outer"
    # 다른 partition 은 변경 X
    assert raw_a["graphic_face"] == "none"


# ── (B) placement_reviewer prompt 에 graphic_face 흡수 인정 ──


def test_reviewer_prompt_recognizes_graphic_absorbed():
    """placement_reviewer system prompt 에 가벽 그래픽 월 흡수 인정 룰 명시."""
    from app.nodes_small.prompts.placement_reviewer import LLM_REVIEWER_SYSTEM
    assert "가벽 그래픽 월 흡수 인정" in LLM_REVIEWER_SYSTEM or "graphic_face='outer'" in LLM_REVIEWER_SYSTEM
    assert "drop 으로 판정 X" in LLM_REVIEWER_SYSTEM
    # 진규님 5-8 명시 컨텍스트 박힘
    assert "구조물 + 포토존 동시 역할" in LLM_REVIEWER_SYSTEM


def test_reviewer_user_prompt_marks_absorbed_partition():
    """user prompt 에 partition.graphic_face='outer' 표시 박힘."""
    from app.nodes_small.prompts.placement_reviewer import build_llm_user_prompt
    state = {
        "placed_objects": [{
            "object_type": "partition_wall_I",
            "anchor_key": "wall_14_right",
            "zone_label": "deep_zone",
            "direction": "wall_perpendicular",
            "wall_attachment": "flush",
            "graphic_face": "outer",
            "graphic_face_basis": "photo_wall_substitute",
            "placed_because": "",
        }],
        "failed_objects": [],
        "brand_data": {"brand": {"brand_category": "뷰티"}, "placement_rules": [{"object_type": "photo_wall"}]},
        "design_intents": [],
        "venue_type": "street_complex",
    }
    prompt = build_llm_user_prompt(state, [])
    assert "photo_wall 흡수" in prompt
    assert "포토존 역할 동시 수행" in prompt or "★" in prompt


def test_reviewer_user_prompt_no_absorb_flag_when_none():
    """partition.graphic_face='none' 일 땐 흡수 표시 안 함."""
    from app.nodes_small.prompts.placement_reviewer import build_llm_user_prompt
    state = {
        "placed_objects": [{
            "object_type": "partition_wall_I",
            "anchor_key": "wall_14_right",
            "zone_label": "deep_zone",
            "direction": "wall_perpendicular",
            "wall_attachment": "flush",
            "graphic_face": "none",
            "graphic_face_basis": "default_front",
            "placed_because": "",
        }],
        "failed_objects": [],
        "brand_data": {"brand": {"brand_category": "뷰티"}, "placement_rules": []},
        "design_intents": [],
        "venue_type": "street_complex",
    }
    prompt = build_llm_user_prompt(state, [])
    assert "photo_wall 흡수" not in prompt


def test_reviewer_user_prompt_summary_count():
    """흡수 1건 이상 시 summary line 박힘 (LLM 가이드 강조)."""
    from app.nodes_small.prompts.placement_reviewer import build_llm_user_prompt
    state = {
        "placed_objects": [{
            "object_type": "partition_wall_I",
            "anchor_key": "wall_14_right",
            "zone_label": "deep_zone",
            "direction": "wall_perpendicular",
            "wall_attachment": "flush",
            "graphic_face": "outer",
            "graphic_face_basis": "photo_wall_substitute",
            "placed_because": "",
        }],
        "failed_objects": [],
        "brand_data": {"brand": {"brand_category": "뷰티"}, "placement_rules": [{"object_type": "photo_wall"}]},
        "design_intents": [],
        "venue_type": "street_complex",
    }
    prompt = build_llm_user_prompt(state, [])
    assert "가벽 그래픽 월 흡수" in prompt
    assert "1건" in prompt or "drop 판정 X" in prompt
