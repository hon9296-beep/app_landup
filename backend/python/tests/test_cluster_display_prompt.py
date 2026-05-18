"""
B-3 (1-3 후속 #535 후속) — 클러스터 진열 prompt 강화 (join_with cluster).

진규님 5-7 진단:
  "오브젝트 간격 없이 연달아 배치 절대 안 보임 — 코드는 허용 (placement.py:1035 join margin=0)
   인데 LLM 이 join_with 거의 안 채움. sub_graph prompt 강화로 처리 가능?"

회귀: VMD 실무에서 흔한 cluster 패턴 (선반 라인업 / 카운터 라인업 / 진열장 연속 배치) 안 나옴.
  모든 obj 가 600~900mm 간격 띄움.

fix:
  - DESIGN_SYSTEM_TEMPLATE 에 [클러스터 진열 원칙] 섹션 신규 (system prompt)
  - DESIGN_PROMPT_TEMPLATE 의 예시 JSON 에 join_with 채워진 예시 1개 추가
  - anti_patterns.AP-208 신규 LLM 룰 — cluster 기회 놓침 검증

회귀 차단:
  - AP-208 룰 등록 (id / category / severity / description 핵심 키워드)
  - system prompt [클러스터 진열 원칙] 섹션 존재 + 핵심 가이드
  - 예시 JSON 에 join_with: 채워진 값 (null 아님) 1개 이상
"""
from app.nodes_small.anti_patterns import ANTI_PATTERNS, get_llm_anti_patterns
from app.nodes_small.prompts.design import DESIGN_SYSTEM_TEMPLATE, DESIGN_PROMPT_TEMPLATE


# ── DESIGN_SYSTEM_TEMPLATE: [클러스터 진열 원칙] 섹션 ──────────


def test_system_prompt_has_cluster_section():
    """system prompt 에 [클러스터 진열 원칙] 섹션 존재."""
    assert "클러스터 진열 원칙" in DESIGN_SYSTEM_TEMPLATE


def test_system_prompt_explains_join_relation_margin_zero():
    """pair_rules join 관계 = edge-to-edge 인접 (간격 없음, margin=0) 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "edge-to-edge" in template
    assert "join_with" in template
    # 진규님 의도: 간격 없이 연달아 배치
    assert "간격 없이" in template or "연달아" in template


def test_system_prompt_lists_cluster_targets():
    """cluster 대상 obj 명시 (shelf_wall / display_table / counter)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "shelf_wall" in template
    assert "display_table" in template
    # ↔ 또는 + 같은 표현으로 cluster 쌍 명시
    assert "shelf_wall ↔" in template or "shelf_wall +" in template or "shelf_wall ↔ shelf_wall" in template


def test_system_prompt_mentions_layout_patterns_lineup():
    """ref_analysis.layout_patterns 에 라인업 패턴 검출 시 cluster 의도 강제 가이드."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "layout_patterns" in template
    assert "라인업" in template


def test_system_prompt_has_cluster_avoidance_guide():
    """정당 회피 케이스 (카테고리 분리 / 통로 폭 / separate) 명시."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "회피" in template
    # 회피 사유 명시
    assert "카테고리" in template


# ── DESIGN_PROMPT_TEMPLATE: 예시 JSON 에 join_with 채움 ──────


def test_example_json_has_filled_join_with():
    """예시 JSON 에 join_with 가 null 아닌 obj_type 으로 채워진 예시 1개 이상."""
    template = DESIGN_PROMPT_TEMPLATE
    # join_with: null 만 있으면 LLM 이 null 패턴 학습. 채워진 예시 필수.
    has_filled = '"join_with": "display_table"' in template or '"join_with": "shelf_wall"' in template or '"join_with": "counter"' in template
    assert has_filled, "예시 JSON 에 join_with 채워진 예시 없음 — LLM 이 null 패턴만 학습"


def test_example_json_cluster_intent_explained():
    """채워진 예시에 cluster 의도 placed_because 명시 (LLM 학습 유도)."""
    template = DESIGN_PROMPT_TEMPLATE
    # cluster / 라인업 / edge-to-edge 등 키워드
    assert "클러스터" in template or "라인업" in template or "edge-to-edge" in template


# ── AP-208 신규 룰 등록 ────────────────────────────────────


def test_ap208_registered_in_zone_flow():
    """AP-208 이 ZONE_FLOW_ANTI_PATTERNS 또는 ANTI_PATTERNS 에 등록."""
    # 검색
    found = None
    for ap in ANTI_PATTERNS:
        if ap.get("id") == "AP-208":
            found = ap
            break
    assert found is not None, "AP-208 룰 등록 안 됨"
    assert found["category"] == "zone_flow"
    assert found["severity"] == "warning"


def test_ap208_is_llm_rule():
    """AP-208 = LLM 룰 (validator_type=llm). design_reviewer 가 LLM 호출 시 description 사용."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-208"), None)
    assert found is not None
    assert found["validator_type"] == "llm"


def test_ap208_in_llm_rules_list():
    """AP-208 이 get_llm_anti_patterns() 결과에 포함 — design_reviewer LLM prompt inject."""
    llm_rules = get_llm_anti_patterns()
    ids = [r.get("id") for r in llm_rules]
    assert "AP-208" in ids


def test_ap208_description_has_cluster_keywords():
    """AP-208 description 에 cluster 핵심 키워드 (join_with / margin / pair_rules / 선반 라인업)."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-208"), None)
    assert found is not None
    desc = found["description"]
    assert "join_with" in desc
    assert "pair_rules" in desc
    assert "선반 라인업" in desc or "라인업" in desc
    assert "edge-to-edge" in desc or "margin=0" in desc


def test_ap208_description_lists_avoidance_cases():
    """AP-208 description 에 정당 회피 케이스 (separate / 통로 / 카테고리 분리) 명시."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-208"), None)
    assert found is not None
    desc = found["description"]
    assert "separate" in desc
    assert "통로" in desc or "카테고리" in desc


# ── 룰 충돌 회피 (기존 ref_point 1:1 룰 / pair_rules 가이드 양립) ────


def test_no_conflict_with_pair_rules_guide():
    """기존 pair_rules 가이드 (line 184) 가 신규 [클러스터 진열 원칙] 과 충돌 X."""
    template = DESIGN_SYSTEM_TEMPLATE
    # 기존 pair_rules 가이드 잔존
    assert "pair_rules" in template
    # 신규 cluster 원칙도 있음
    assert "클러스터 진열 원칙" in template
