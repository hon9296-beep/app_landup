"""
B-3 후속 (#535 후속) — 동일 std_id cluster 강제 (pair_rules + prompt + AP-208).

진규님 5-7 21:17 라이브 진단:
  "POS 카운터 + 증정품 카운터 = 현실에서 붙어있어도 되잖아. 이런거 prompt 로 조정 못하냐?
   ref zone 에 obj 하나만 허용이 패착인가?"

진단:
  - placement.py:1168-1170 _find_pair_rule = join_with 직접 지정 1순위 처리 ✓
  - 단 pair_rules default = `counter ↔ * separate 1200mm` / `display_table ↔ display_table separate 600mm`
  - LLM 이 join_with 안 채우면 default separate 적용 → counter 2개가 각 wall 차지 → 18평에서
    photo_wall 자리 부족 → drop 회귀 (5-7 21:17 라이브 확증)

fix:
  1. pair_rules: counter ↔ counter / display_table ↔ display_table = join 추가
     (wildcard separate 룰보다 위에 배치 — _find_pair_rule list 순서 매칭)
  2. design prompt [클러스터 진열 원칙]: 동일 std_id 다른 manual_label cluster 1순위 강조
  3. AP-208 description: 동일 std_id 케이스 강한 reject 권장 명시

회귀 차단 검증.
"""
from app.nodes_small.anti_patterns import ANTI_PATTERNS
from app.nodes_small.prompts.design import DESIGN_SYSTEM_TEMPLATE
from app.vmd_constants import VMD_PAIR_RULES


# ── pair_rules: 동일 std_id join ─────────────────────────────


def test_counter_counter_join_in_pair_rules():
    """counter ↔ counter = join (separate 1200mm 회귀 차단)."""
    rule = next(
        (r for r in VMD_PAIR_RULES
         if r["object_a"] == "counter" and r["object_b"] == "counter"),
        None,
    )
    assert rule is not None, "counter ↔ counter pair_rule 누락"
    assert rule["relation"] == "join", (
        f"counter ↔ counter relation={rule['relation']} — join 이어야 cluster 가능"
    )
    assert rule["min_gap_mm"] == 0, (
        f"counter ↔ counter min_gap={rule['min_gap_mm']} — 0 이어야 edge-to-edge"
    )


def test_display_table_display_table_join():
    """display_table ↔ display_table = join (separate 600mm → join 변경)."""
    rule = next(
        (r for r in VMD_PAIR_RULES
         if r["object_a"] == "display_table" and r["object_b"] == "display_table"),
        None,
    )
    assert rule is not None
    assert rule["relation"] == "join", (
        f"display_table ↔ display_table relation={rule['relation']} — 진열대 라인업 차단 회귀"
    )


def test_shelf_wall_shelf_wall_join_preserved():
    """shelf_wall ↔ shelf_wall = join (기존 정상 — 회귀 차단)."""
    rule = next(
        (r for r in VMD_PAIR_RULES
         if r["object_a"] == "shelf_wall" and r["object_b"] == "shelf_wall"),
        None,
    )
    assert rule is not None
    assert rule["relation"] == "join"


# ── pair_rules: list 순서 (동일 type 우선 매칭) ───────────────


def test_counter_counter_before_counter_wildcard():
    """counter ↔ counter 룰이 counter ↔ * separate 룰보다 list 앞.

    _find_pair_rule 가 list 순서대로 첫 매칭 반환 → 동일 type 룰을 wildcard 위에 배치 필수.
    위에 안 두면 wildcard 의 separate 1200 이 먼저 매칭 → cluster 차단 회귀.
    """
    counter_counter_idx = None
    counter_wildcard_idx = None
    for i, r in enumerate(VMD_PAIR_RULES):
        if r["object_a"] == "counter" and r["object_b"] == "counter":
            counter_counter_idx = i
        if r["object_a"] == "counter" and r["object_b"] == "*":
            counter_wildcard_idx = i
    assert counter_counter_idx is not None
    assert counter_wildcard_idx is not None
    assert counter_counter_idx < counter_wildcard_idx, (
        f"counter↔counter idx={counter_counter_idx} >= counter↔* idx={counter_wildcard_idx} — "
        f"순서 잘못. wildcard 가 먼저 매칭 → counter cluster 차단."
    )


def test_counter_other_obj_separate_preserved():
    """counter ↔ 다른 obj (display_table 등) = separate 1200 유지 (의미 분리)."""
    rule = next(
        (r for r in VMD_PAIR_RULES
         if r["object_a"] == "counter" and r["object_b"] == "*"),
        None,
    )
    assert rule is not None
    assert rule["relation"] == "separate"
    assert rule["min_gap_mm"] == 1200


# ── design prompt: 동일 std_id cluster 강조 ────────────────


def test_system_prompt_emphasizes_same_std_id_cluster():
    """system prompt [클러스터 진열 원칙] 에 동일 std_id 다른 manual_label cluster 강조 (추상 표현)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "동일 std_id" in template
    # 추상 표현 — manual_label 인스턴스 (구체 라벨 X — AP-303 회귀 차단)
    assert "manual_label 인스턴스" in template


def test_system_prompt_explains_5_7_regression():
    """5-7 18평 LUMIA 회귀 사례 명시 — counter cluster 안 하면 photo_wall drop."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert "회귀 사례" in template or "회귀" in template
    # photo_wall drop 사례 또는 핵심 인과
    assert "photo_wall" in template


def test_system_prompt_says_join_with_format_required():
    """`join_with: "<std_id>"` 명시 권장 (LLM 이 std_id 박도록 가이드)."""
    template = DESIGN_SYSTEM_TEMPLATE
    assert 'join_with: "<std_id>"' in template


def test_system_prompt_no_specific_manual_label_in_cluster_section():
    """cluster 섹션에 구체 manual_label phrase 없음 (AP-303 회귀 차단)."""
    template = DESIGN_SYSTEM_TEMPLATE
    # AP-303 forbidden_phrases 가 cluster 섹션에 안 들어가게
    forbidden = ["POS 카운터", "증정품 카운터", "1차 상담", "2차 시연", "신상 진열", "체험용"]
    for phrase in forbidden:
        assert phrase not in template, (
            f"cluster 섹션 또는 다른 곳에 manual_label phrase '{phrase}' 잔존 — AP-303 회귀"
        )


# ── AP-208 description: 동일 std_id 강한 reject ────────────


def test_ap208_description_emphasizes_same_std_id():
    """AP-208 description 에 동일 std_id 다른 manual_label 케이스 강조 (추상 표현)."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-208"), None)
    assert found is not None
    desc = found["description"]
    assert "동일 std_id" in desc
    assert "manual_label 인스턴스" in desc
    assert "강한 reject" in desc


def test_ap208_description_mentions_drop_regression_consequence():
    """AP-208 description 에 cluster 안 하면 drop 회귀 가능성 명시."""
    found = next((ap for ap in ANTI_PATTERNS if ap.get("id") == "AP-208"), None)
    assert found is not None
    desc = found["description"]
    assert "drop" in desc
    # 자리 부족 / 다른 핵심 obj 영향
    assert "photo_wall" in desc or "자리 부족" in desc


# ── pair_rules + prompt 일관성 ──────────────────────────────


def test_prompt_cluster_targets_match_pair_rules_join():
    """prompt 가 권장하는 cluster 대상 (counter/display_table/shelf_wall) 모두 pair_rules join."""
    template = DESIGN_SYSTEM_TEMPLATE
    # prompt 에 명시된 대상 목록
    cluster_pairs = [
        ("counter", "counter"),
        ("display_table", "display_table"),
        ("shelf_wall", "shelf_wall"),
    ]
    for a, b in cluster_pairs:
        # prompt 에 등장
        assert f"{a} ↔ {b}" in template, f"prompt 에 {a} ↔ {b} cluster 권장 누락"
        # pair_rules 에 join 정의
        rule = next(
            (r for r in VMD_PAIR_RULES if r["object_a"] == a and r["object_b"] == b),
            None,
        )
        assert rule is not None and rule["relation"] == "join", (
            f"{a} ↔ {b} pair_rules join 누락 — prompt 가이드와 코드 default 불일치"
        )
