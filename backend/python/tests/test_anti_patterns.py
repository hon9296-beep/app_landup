"""
#474 anti_patterns.py 단위 테스트.

Python validator 16개 + 헬퍼 (run_validators / get_llm_anti_patterns / compute_intent_similarity / build_designer_feedback).
LLM stub 10개는 stub 동작만 확인 (위반 0). 1-2 (#520 후속) 에서 AP-303 (manual_label semantic) 추가.

테스트 패턴 — 각 룰 마다:
  - 위반 케이스 (validator 가 violation 검출)
  - 정상 케이스 (violation 0)
  - edge (빈 intents / state 누락) — graceful
"""
import pytest
from shapely.geometry import LineString, Polygon

from app.nodes_small.anti_patterns import (
    ANTI_PATTERNS,
    run_validators,
    get_llm_anti_patterns,
    compute_intent_similarity,
    build_designer_feedback,
    _validate_AP_001,
    _validate_AP_002,
    _validate_AP_003,
    _validate_AP_004,
    _validate_AP_005,
    _validate_AP_006,
    _validate_AP_007,
    _validate_AP_008,
    _validate_AP_101,
    _validate_AP_102,
    _validate_AP_103,
    _validate_AP_104,
    _validate_AP_105,
    _validate_AP_108,
    _validate_AP_203,  # 1-3 #533 B2 — python 이동
    _validate_AP_207,  # 1-3 #533 B2 — python 이동
    _validate_AP_301,
    _validate_AP_302,
)


# ── 카탈로그 무결성 ──────────────────────────────────────────────────


def test_catalog_count():
    # 1-2 (#520 후속): AP-303 추가 25 → 26
    # 1-3 (#523 후속): AP-009 (structural_constraint, ref_point 1:1) 추가 26 → 27
    # B-3 (#535 후속): AP-208 (cluster 진열 기회 놓침, zone_flow LLM) 추가 27 → 28
    # C4 (5-7+5-8 시위 회귀): AP-010 (partition_wall_I mid/entrance_zone reject) 추가 28 → 29
    assert len(ANTI_PATTERNS) == 29


def test_catalog_id_unique():
    ids = [ap["id"] for ap in ANTI_PATTERNS]
    assert len(ids) == len(set(ids)), f"중복 ID: {[i for i in ids if ids.count(i) > 1]}"


def test_catalog_required_fields():
    required = {"id", "category", "severity", "description", "validator_type", "validator", "enabled", "categories_only"}
    for ap in ANTI_PATTERNS:
        assert required.issubset(ap.keys()), f"{ap['id']} 필드 누락"


def test_catalog_category_distribution():
    from collections import Counter
    cat = Counter(ap["category"] for ap in ANTI_PATTERNS)
    # 1-3 (#523 후속): structural_constraint 카테고리 (AP-009) 신규
    # B-3 (#535 후속): zone_flow 7 → 8 (AP-208 cluster 룰 추가)
    # C4 (5-7+5-8 시위): single_entrance 8 → 9 (AP-010 partition mid_zone reject)
    assert cat == {
        "single_entrance": 9,
        "structural_constraint": 1,
        "multi_entrance": 8,
        "zone_flow": 8,
        "family_entrance_pass": 2,
        "manual_label_semantic": 1,
    }


def test_llm_anti_patterns_count():
    # 1-2 (#520 후속): zone/동선 7 + AP-106/AP-107 + AP-303 = 10
    # 1-3 후속 (#533 B2): AP-203 / AP-207 → python validator 로 이동 → 10 - 2 = 8
    # B-3 (#535 후속): AP-208 (cluster, LLM) 추가 8 → 9
    assert len(get_llm_anti_patterns()) == 9


# ── compute_intent_similarity ───────────────────────────────────────


def test_similarity_empty():
    assert compute_intent_similarity([], []) == 0.0
    assert compute_intent_similarity(None, None) == 0.0


def test_similarity_identical():
    a = [{"object_type": "counter", "zone_label": "deep_zone", "direction": "wall_facing"}]
    assert compute_intent_similarity(a, a) == 1.0


def test_similarity_partial():
    prev = [
        {"object_type": "counter", "zone_label": "deep_zone", "direction": "wall_facing"},
        {"object_type": "photo_wall", "zone_label": "mid_zone", "direction": "wall_facing"},
    ]
    curr = [
        {"object_type": "counter", "zone_label": "deep_zone", "direction": "wall_facing"},
        {"object_type": "display_table", "zone_label": "mid_zone", "direction": "center"},
    ]
    # 1/2 매칭
    assert compute_intent_similarity(prev, curr) == 0.5


def test_similarity_disjoint():
    prev = [{"object_type": "counter", "zone_label": "deep_zone", "direction": "wall_facing"}]
    curr = [{"object_type": "photo_wall", "zone_label": "mid_zone", "direction": "wall_facing"}]
    assert compute_intent_similarity(prev, curr) == 0.0


# ── build_designer_feedback ─────────────────────────────────────────


def test_feedback_empty():
    assert build_designer_feedback([]) == ""


def test_feedback_format():
    blocking = [{
        "rule_id": "AP-001", "severity": "blocking",
        "intent_object_type": "partition_wall_I", "intent_zone": "entrance_zone", "intent_ref_point_id": "wall_1",
        "violation_detail": "입구 정면 800mm < 1500mm 이내 가벽 배치"
    }]
    text = build_designer_feedback(blocking)
    assert "AP-001" in text
    assert "partition_wall_I" in text
    assert "위반" in text or "수정" in text


# ── run_validators graceful ─────────────────────────────────────────


def test_run_validators_empty_state():
    assert run_validators([], {}) == []


def test_run_validators_minimal_state():
    # 1-3 #533 B2: AP-207 venue_type 검증 추가 — 운영 흐름 가정 (venue_type default).
    # state_builder.rebuild_state_from_body 가 항상 venue_type 박음 (default street_complex).
    state = {"brand_data": {"brand": {"brand_category": "기타"}}, "venue_type": "street_complex"}
    assert run_validators([], state) == []


# ── A. 단일 입구 (AP-001 ~ AP-008) ──────────────────────────────────


def _build_state(**overrides):
    """공통 mock state."""
    base = {
        "entrance_mm": (5000, 1000),
        # 1-3 #533 B2: AP-207 graceful skip 회피 — 운영 흐름 일관 (venue_type default 박힘)
        "venue_type": "street_complex",
        "usable_poly": Polygon([(0, 0), (10000, 0), (10000, 10000), (0, 10000)]),
        "reference_points": [
            # 1-3 #533 후속 동기화: ENTRANCE_FRONT_CLEAR_MM 1500→900 하향 반영.
            # wall_1 거리 1000 → 500 (AP-001 위반 유지 — 500 < 900).
            {"id": "wall_1", "coord": (5000, 1500), "label": "entrance_adjacent", "zone_label": "entrance_zone"},
            {"id": "wall_2", "coord": (5000, 5000), "label": "side_wall", "zone_label": "mid_zone"},
            {"id": "center_3", "coord": (5000, 5000), "label": "center_freestanding", "zone_label": "mid_zone"},
        ],
        "eligible_objects": [
            {"object_type": "partition_wall_I", "width_mm": 2000, "depth_mm": 150, "height_mm": 2400},
            {"object_type": "counter", "width_mm": 1500, "depth_mm": 600, "height_mm": 900},
            {"object_type": "photo_island", "width_mm": 1500, "depth_mm": 1500, "height_mm": 2200},
            {"object_type": "shelf_wall", "width_mm": 1500, "depth_mm": 400, "height_mm": 2400},
            {"object_type": "consultation_desk", "width_mm": 700, "depth_mm": 600, "height_mm": 750},
            {"object_type": "test_bar", "width_mm": 1200, "depth_mm": 700, "height_mm": 950},
            {"object_type": "display_table", "width_mm": 1200, "depth_mm": 800, "height_mm": 900},
        ],
        "brand_data": {"brand": {"brand_category": "기타"}, "placement_rules": []},
    }
    base.update(overrides)
    return base


def test_AP_001_violation():
    """입구 (5000,1000) 정면 ENTRANCE_FRONT_CLEAR_MM 이내 가벽 — wall_1 (5000,1500) = 500mm 거리 < 900 → 위반."""
    state = _build_state()
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_1", "zone_label": "entrance_zone"}]
    v = _validate_AP_001(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-001"


def test_AP_001_no_violation_far():
    """입구에서 멀리 — 위반 X."""
    state = _build_state()
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_2", "zone_label": "mid_zone"}]
    v = _validate_AP_001(intents, state)
    assert v == []


def test_AP_001_no_entrance():
    """entrance_mm 없으면 graceful skip."""
    state = _build_state(entrance_mm=None)
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_1", "zone_label": "entrance_zone"}]
    assert _validate_AP_001(intents, state) == []


def test_AP_002_violation():
    """main_artery 폭 900mm 이내 photo_island — 위반."""
    main_artery = LineString([(5000, 1000), (5000, 9000)])  # 입구→깊음 vertical
    state = _build_state(main_artery=main_artery)
    # center_3 (5000, 5000) 가 main_artery 위 → 거리 0
    intents = [{"object_type": "photo_island", "ref_point_id": "center_3", "zone_label": "mid_zone"}]
    v = _validate_AP_002(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-002"


def test_AP_002_no_artery():
    """main_artery 없으면 graceful skip."""
    state = _build_state()
    intents = [{"object_type": "photo_island", "ref_point_id": "center_3"}]
    assert _validate_AP_002(intents, state) == []


def test_AP_003_violation():
    """화장실 (Polygon, inaccessible_types=toilet) 정면 1500mm 이내 consultation_desk — 위반.

    2026-05-08: AP-003 변경 — inaccessible_types 의 'toilet' 만 필터.
    """
    inaccessible = [Polygon([(7000, 4000), (9000, 4000), (9000, 6000), (7000, 6000)])]
    state = _build_state(inaccessible_polys=inaccessible, inaccessible_types=["toilet"])
    state["reference_points"].append({"id": "near_restroom", "coord": (6000, 5000), "label": "side_wall", "zone_label": "mid_zone"})
    intents = [{"object_type": "consultation_desk", "ref_point_id": "near_restroom", "zone_label": "mid_zone"}]
    v = _validate_AP_003(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-003"


def test_AP_003_counter_violation():
    """2026-05-08 신규 — counter 도 화장실 1500mm 차단 대상."""
    inaccessible = [Polygon([(7000, 4000), (9000, 4000), (9000, 6000), (7000, 6000)])]
    state = _build_state(inaccessible_polys=inaccessible, inaccessible_types=["toilet"])
    state["reference_points"].append({"id": "near_restroom", "coord": (6000, 5000), "label": "side_wall", "zone_label": "mid_zone"})
    intents = [{"object_type": "counter", "ref_point_id": "near_restroom", "zone_label": "mid_zone"}]
    v = _validate_AP_003(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-003"
    assert "counter" in v[0]["violation_detail"]


def test_AP_003_kiosk_violation():
    """2026-05-08 신규 — kiosk 도 화장실 1500mm 차단 대상."""
    state = _build_state(
        inaccessible_polys=[Polygon([(7000, 4000), (9000, 4000), (9000, 6000), (7000, 6000)])],
        inaccessible_types=["toilet"],
    )
    state["eligible_objects"].append({"object_type": "kiosk", "width_mm": 600, "depth_mm": 600, "height_mm": 1700})
    state["reference_points"].append({"id": "near_restroom", "coord": (6000, 5000), "label": "side_wall", "zone_label": "mid_zone"})
    intents = [{"object_type": "kiosk", "ref_point_id": "near_restroom", "zone_label": "mid_zone"}]
    v = _validate_AP_003(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-003"


def test_AP_003_stair_not_filtered():
    """2026-05-08 — 계단 (stair) 폴리곤은 본 룰 미적용 (toilet 만 필터)."""
    state = _build_state(
        inaccessible_polys=[Polygon([(7000, 4000), (9000, 4000), (9000, 6000), (7000, 6000)])],
        inaccessible_types=["stair"],  # 화장실 X — 계단
    )
    state["reference_points"].append({"id": "near_stair", "coord": (6000, 5000), "label": "side_wall", "zone_label": "mid_zone"})
    intents = [{"object_type": "consultation_desk", "ref_point_id": "near_stair", "zone_label": "mid_zone"}]
    v = _validate_AP_003(intents, state)
    assert v == [], "계단은 AP-003 미적용 (toilet 만 필터)"


def test_AP_003_low_value_obj_pass():
    """2026-05-08 — 보조 테이블 / 진열대 등 저 value obj 는 화장실 근처 OK."""
    state = _build_state(
        inaccessible_polys=[Polygon([(7000, 4000), (9000, 4000), (9000, 6000), (7000, 6000)])],
        inaccessible_types=["toilet"],
    )
    state["reference_points"].append({"id": "near_restroom", "coord": (6000, 5000), "label": "side_wall", "zone_label": "mid_zone"})
    # display_table 은 target_types 외 — 통과
    intents = [{"object_type": "display_table", "ref_point_id": "near_restroom", "zone_label": "mid_zone"}]
    v = _validate_AP_003(intents, state)
    assert v == []


def test_AP_004_violation():
    """entrance_zone center 에 height > 1200 — 위반."""
    state = _build_state()
    state["eligible_objects"].append({"object_type": "tall_obj", "width_mm": 800, "depth_mm": 800, "height_mm": 2000})
    state["reference_points"].append({"id": "center_entrance", "coord": (5000, 1500), "label": "center_entrance_area", "zone_label": "entrance_zone"})
    intents = [{"object_type": "tall_obj", "ref_point_id": "center_entrance", "zone_label": "entrance_zone", "direction": "center"}]
    v = _validate_AP_004(intents, state)
    assert len(v) == 1


def test_AP_004_wall_facing_pass():
    """entrance_zone wall_facing — 높이 제한 무관 (R4 단서)."""
    state = _build_state()
    state["eligible_objects"].append({"object_type": "tall_obj", "width_mm": 800, "depth_mm": 800, "height_mm": 2000})
    intents = [{"object_type": "tall_obj", "ref_point_id": "wall_1", "zone_label": "entrance_zone", "direction": "wall_facing"}]
    assert _validate_AP_004(intents, state) == []


def test_AP_005_violation():
    """짝꿍 없는 partition_wall — 위반."""
    state = _build_state()
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_2", "zone_label": "mid_zone"}]
    v = _validate_AP_005(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-005"


def test_AP_005_pass_with_join_with():
    """join_with 있으면 통과."""
    state = _build_state()
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_2", "zone_label": "mid_zone", "join_with": "photo_wall_42"}]
    assert _validate_AP_005(intents, state) == []


def test_AP_006_warning_no_pair():
    """shelf_wall 만 있고 짝꿍 (display_table 등) 부재 — warning."""
    state = _build_state()
    intents = [{"object_type": "shelf_wall", "ref_point_id": "wall_2", "zone_label": "mid_zone"}]
    v = _validate_AP_006(intents, state)
    assert len(v) == 1 and v[0]["severity"] == "warning"


def test_AP_006_pass_with_pair():
    """shelf_wall + display_table — 통과."""
    state = _build_state()
    intents = [
        {"object_type": "shelf_wall", "ref_point_id": "wall_2"},
        {"object_type": "display_table", "ref_point_id": "center_3"},
    ]
    assert _validate_AP_006(intents, state) == []


def test_AP_007_violation_no_reason():
    """가벽인데 placement_reason / placed_because 모두 빈 — 위반."""
    state = _build_state()
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_2", "zone_label": "mid_zone", "placement_reason": "", "placed_because": ""}]
    v = _validate_AP_007(intents, state)
    assert len(v) == 1


def test_AP_007_pass_valid_reason():
    """가벽 + valid reason (staff_zone) — 통과."""
    state = _build_state()
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "wall_2", "placement_reason": "staff_zone Back of House"}]
    assert _validate_AP_007(intents, state) == []


def test_AP_008_warning_18py_overflow():
    """18평 (60M mm²) 이하 + intents > 8 — warning."""
    state = _build_state(usable_poly=Polygon([(0, 0), (7700, 0), (7700, 7700), (0, 7700)]))  # ~60M mm²
    intents = [{"object_type": f"obj_{i}", "ref_point_id": f"rp_{i}"} for i in range(9)]
    v = _validate_AP_008(intents, state)
    assert len(v) == 1 and v[0]["severity"] == "warning"


def test_AP_008_pass_under_8():
    """intents <= 8 — 통과."""
    state = _build_state(usable_poly=Polygon([(0, 0), (7700, 0), (7700, 7700), (0, 7700)]))
    intents = [{"object_type": f"obj_{i}", "ref_point_id": f"rp_{i}"} for i in range(7)]
    assert _validate_AP_008(intents, state) == []


# ── B. 다중 입구 (AP-101 ~ AP-108) ──────────────────────────────────


def _multi_entrance_state(secondary_count: int = 1, with_zone: bool = False):
    """다중 입구 mock state. secondary_count = 2~N번째 입구 수."""
    state = _build_state()
    primary = (5000, 1000)
    secondary = [(1000, 5000), (9000, 5000), (5000, 9000)][:secondary_count]
    state["all_entrances_mm"] = [{"coord": primary, "type": "MAIN_DOOR"}] + [{"coord": s, "type": "MAIN_DOOR"} for s in secondary]
    if with_zone:
        # 2~N번째 입구 반경 안에 entrance_zone ref_point 추가
        for i, s in enumerate(secondary):
            state["reference_points"].append({
                "id": f"sec_ent_{i}", "coord": (s[0], s[1] + 500),
                "label": "entrance_adjacent", "zone_label": "entrance_zone",
            })
    return state


def test_AP_101_violation_no_secondary_zone():
    """2~N번째 입구 반경에 entrance_zone ref_point 0건 — 위반."""
    state = _multi_entrance_state(secondary_count=2, with_zone=False)
    intents = [{"object_type": "counter", "ref_point_id": "wall_1"}]
    v = _validate_AP_101(intents, state)
    assert len(v) == 2  # 2개 secondary 입구 각각 위반


def test_AP_101_pass_with_zone():
    """2~N번째 입구 반경에 entrance_zone ref_point 있음 — 통과."""
    state = _multi_entrance_state(secondary_count=2, with_zone=True)
    intents = [{"object_type": "counter", "ref_point_id": "wall_1"}]
    assert _validate_AP_101(intents, state) == []


def test_AP_102_violation_in_decompression():
    """2~N번째 입구 앞 1.5m 이내 placed — 위반."""
    state = _multi_entrance_state(secondary_count=1)
    # secondary = (1000, 5000), 가까운 ref_point 추가
    state["reference_points"].append({"id": "near_sec", "coord": (1500, 5000), "zone_label": "mid_zone"})
    intents = [{"object_type": "display_table", "ref_point_id": "near_sec"}]
    v = _validate_AP_102(intents, state)
    assert len(v) == 1 and v[0]["rule_id"] == "AP-102"


def test_AP_103_violation_secondary_center_height():
    """2~N번째 입구 앞 center 에 height > 1200 — 위반."""
    state = _multi_entrance_state(secondary_count=1)
    state["eligible_objects"].append({"object_type": "tall_obj", "width_mm": 800, "depth_mm": 800, "height_mm": 2000})
    state["reference_points"].append({"id": "near_sec_center", "coord": (1300, 5000), "label": "center_freestanding", "zone_label": "mid_zone"})
    intents = [{"object_type": "tall_obj", "ref_point_id": "near_sec_center", "direction": "center"}]
    v = _validate_AP_103(intents, state)
    assert len(v) == 1


def test_AP_104_violation_partition_at_secondary():
    """2~N번째 입구 앞에 가벽 — 위반."""
    state = _multi_entrance_state(secondary_count=1)
    state["reference_points"].append({"id": "near_sec_w", "coord": (1500, 5000), "zone_label": "mid_zone"})
    intents = [{"object_type": "partition_wall_I", "ref_point_id": "near_sec_w"}]
    v = _validate_AP_104(intents, state)
    assert len(v) == 1


def test_AP_105_violation_large_at_secondary():
    """2~N번째 입구 반경에 large 기물 — 위반."""
    state = _multi_entrance_state(secondary_count=1)
    state["eligible_objects"].append({"object_type": "big_table", "width_mm": 1500, "depth_mm": 1200, "height_mm": 900})
    state["reference_points"].append({"id": "near_sec_big", "coord": (2500, 5000), "zone_label": "mid_zone"})
    intents = [{"object_type": "big_table", "ref_point_id": "near_sec_big"}]
    v = _validate_AP_105(intents, state)
    assert len(v) == 1


def test_AP_108_warning_4_entrance_no_entrance_zone_intents():
    """4입구 매장 — entrance_zone intents 부족 — warning."""
    state = _multi_entrance_state(secondary_count=3)  # 1+3 = 4 입구
    intents = [{"object_type": "counter", "ref_point_id": "wall_2", "zone_label": "mid_zone"}]
    v = _validate_AP_108(intents, state)
    assert len(v) == 1 and v[0]["severity"] == "warning"


# ── D. family_cap / 입구 통과 (AP-301 / AP-302) ──────────────────────


def test_AP_301_warning_dual_label_single_intent():
    """매뉴얼 counter 2개 (POS / Reward) 인데 intents counter 1개 — warning."""
    state = _build_state()
    state["brand_data"]["placement_rules"] = [
        {"object_type": "counter", "name": "POS 카운터", "label": "POS 카운터"},
        {"object_type": "counter", "name": "Reward Counter", "label": "Reward Counter"},
    ]
    intents = [{"object_type": "counter", "ref_point_id": "wall_2"}]
    v = _validate_AP_301(intents, state)
    assert len(v) == 1 and v[0]["severity"] == "warning"


def test_AP_301_pass_matching_intent_count():
    """매뉴얼 2 + intents 2 — 통과."""
    state = _build_state()
    state["brand_data"]["placement_rules"] = [
        {"object_type": "counter", "name": "POS"},
        {"object_type": "counter", "name": "Reward"},
    ]
    intents = [{"object_type": "counter", "ref_point_id": "wall_1"}, {"object_type": "counter", "ref_point_id": "wall_2"}]
    assert _validate_AP_301(intents, state) == []


def test_AP_302_violation_too_big_for_entrance():
    """기물 짧은 변 > entrance_width — 위반 (반입 불가)."""
    state = _build_state(entrance_width_mm=1000)
    state["eligible_objects"].append({"object_type": "huge_obj", "width_mm": 1500, "depth_mm": 1300, "height_mm": 1500})
    intents = [{"object_type": "huge_obj", "ref_point_id": "wall_2"}]
    v = _validate_AP_302(intents, state)
    assert len(v) == 1 and v[0]["severity"] == "blocking"


def test_AP_302_pass_fits_through():
    """기물 짧은 변 < entrance_width — 통과."""
    state = _build_state(entrance_width_mm=1200)
    state["eligible_objects"].append({"object_type": "ok_obj", "width_mm": 1500, "depth_mm": 800, "height_mm": 900})
    intents = [{"object_type": "ok_obj", "ref_point_id": "wall_2"}]
    assert _validate_AP_302(intents, state) == []


def test_AP_302_no_entrance_width():
    """entrance_width_mm 없으면 graceful skip."""
    state = _build_state(entrance_width_mm=None)
    intents = [{"object_type": "counter", "ref_point_id": "wall_2"}]
    assert _validate_AP_302(intents, state) == []


# ── 통합 — run_validators 전체 호출 ────────────────────────────────


def test_run_validators_all_python_rules_no_violations_minimal():
    """정상 mock state + 빈 intents → violations 0."""
    state = _build_state()
    assert run_validators([], state) == []


def test_run_validators_multiple_violations():
    """여러 룰 동시 위반."""
    state = _build_state(entrance_width_mm=1000)
    state["eligible_objects"].append({"object_type": "huge_obj", "width_mm": 1500, "depth_mm": 1500, "height_mm": 2000})
    intents = [
        # AP-001 (입구 정면 가벽) + AP-005 (단독 가벽) + AP-007 (vmd 의도 X)
        {"object_type": "partition_wall_I", "ref_point_id": "wall_1", "zone_label": "entrance_zone", "placement_reason": ""},
        # AP-302 (큰 기물 반입 불가)
        {"object_type": "huge_obj", "ref_point_id": "wall_2"},
    ]
    v = run_validators(intents, state)
    rule_ids = {viol["rule_id"] for viol in v}
    assert "AP-001" in rule_ids
    assert "AP-005" in rule_ids
    assert "AP-007" in rule_ids
    assert "AP-302" in rule_ids


def test_run_validators_graceful_on_validator_exception(monkeypatch):
    """validator 가 exception 발생 시 graceful — 다른 룰만 처리."""
    from app.nodes_small import anti_patterns
    def _broken(intents, state):
        raise ValueError("intentional")
    # AP-001 의 validator 를 broken 으로 monkeypatch
    original = anti_patterns.ANTI_PATTERNS[0]["validator"]
    anti_patterns.ANTI_PATTERNS[0]["validator"] = _broken
    try:
        state = _build_state()
        intents = [{"object_type": "counter", "ref_point_id": "wall_2"}]
        v = run_validators(intents, state)  # exception 발생해도 다른 룰 정상 실행
        assert isinstance(v, list)  # 빈 list 또는 다른 룰 결과
    finally:
        anti_patterns.ANTI_PATTERNS[0]["validator"] = original


# ── B2 (1-3 #533) — AP-203 / AP-207 python validator 신규 ─────────────


def test_AP_203_no_main_artery_skip():
    """main_artery 부재 시 graceful skip — 빈 list."""
    state = {}
    assert _validate_AP_203([], state) == []


def test_AP_203_straight_line_violation():
    """waypoints 2 이하 (start + end 만) → 직선 → warning."""
    straight = LineString([(0, 0), (10000, 0)])  # 2 points only
    state = {"main_artery": straight}
    intents = [{"object_type": "counter"}]
    v = _validate_AP_203(intents, state)
    assert len(v) == 1
    assert v[0]["rule_id"] == "AP-203"
    assert v[0]["severity"] == "warning"


def test_AP_203_curved_path_pass():
    """waypoints 3+ (S/U/Z 우회) → 빈 list."""
    curved = LineString([(0, 0), (5000, 5000), (10000, 0)])  # 3 points
    state = {"main_artery": curved}
    assert _validate_AP_203([], state) == []


def test_AP_207_unknown_venue_warning():
    """venue_type 미정 / unknown + brand_data 있음 → warning.

    graceful skip 회피 위해 brand_data / usable_poly 중 하나 박음 (운영 흐름 가정).
    """
    for missing in [None, "unknown"]:
        state = {"venue_type": missing, "brand_data": {"brand": {}}}
        v = _validate_AP_207([{"object_type": "counter"}], state)
        assert len(v) == 1, f"venue_type={missing!r} 에 warning 부재"
        assert v[0]["rule_id"] == "AP-207"


def test_AP_207_known_venue_pass():
    """venue_type 명시 → 빈 list."""
    for venue in ["street_complex", "department_store", "standalone"]:
        state = {"venue_type": venue, "brand_data": {"brand": {}}}
        assert _validate_AP_207([], state) == []


def test_AP_207_graceful_skip_minimal_state():
    """brand_data 와 usable_poly 둘 다 없으면 graceful skip — test/운영 진입 전 상태."""
    assert _validate_AP_207([], {}) == []
    assert _validate_AP_207([], {"venue_type": None}) == []


# ── catalog 재배치 검증 — AP-203 / AP-207 → python ─────────────────────


def test_ap203_validator_type_python():
    """AP-203 validator_type 이 python 으로 변경됨 (1-3 B2)."""
    ap = next(a for a in ANTI_PATTERNS if a["id"] == "AP-203")
    assert ap["validator_type"] == "python"


def test_ap207_validator_type_python():
    """AP-207 validator_type 이 python 으로 변경됨 (1-3 B2)."""
    ap = next(a for a in ANTI_PATTERNS if a["id"] == "AP-207")
    assert ap["validator_type"] == "python"


def test_zone_flow_descriptions_strengthened():
    """B2: AP-201~207 description 풍부화 (이전 짧은 한 줄 → 카테고리별 가이드 + 임계 명시).

    기존 짧은 description 회귀 차단 — 50 자 이상 보장.
    """
    for ap_id in ["AP-201", "AP-202", "AP-203", "AP-204", "AP-205", "AP-206", "AP-207"]:
        ap = next(a for a in ANTI_PATTERNS if a["id"] == ap_id)
        assert len(ap["description"]) >= 50, f"{ap_id} description 50 자 미만 — 풍부화 회귀"
