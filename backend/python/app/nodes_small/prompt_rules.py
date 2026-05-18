"""
배치 규칙 사전 — R룰 원본 + ZONING 매핑.

R룰 수정은 이 파일만. ZONING에서 참조만 하고 design.py의 _build_rules_text가 조립.
"""

# ── R룰 원본 사전 (Single Source of Truth) ──────────────────────────────

R_RULES = {
    "small": {
        "R1": "[진입 동선 최소화] 입구 개방 반경(900mm)만 확보하고, 입구 직후 측면 벽면(side_wall)부터 즉시 기물 진열을 시작하라.",
        "R2": "[계산대 유연 배치] 계산대(counter/pos_counter)는 deep_zone 배치를 최우선으로 하되, 해당 구역 공간이 협소할 경우 차선책으로 mid_zone의 측면 벽(side_wall)으로 전진 배치를 적극 허용한다.",
        "R3": "[사각지대 방지] 코너나 기둥 뒤(dead_zone 주변) 등 인지하기 어려운 곳에는 크기가 큰 기물이나 조명/포토존 등을 배치하여 동선을 유도.",
        "R4": "[시야 확보] entrance_zone 중앙부(center/freestanding)에는 높이 1200mm 초과 기물 배치를 절대 금지한다. 단, wall_facing인 경우 높이 제한을 무시하고 entrance_zone 양쪽 벽면에 키 큰 진열대를 적극 배치할 것.",
        "R5": "[밀도 극대화] 기물 간 최소 간격은 600~800mm로 타이트하게 유지하라. 900mm 이상의 과도한 이격은 피할 것.",
        "R6": "[중앙 배치 제한] center/freestanding 방향 배치는 최대 2개, 폭 850mm 이하의 소형 테이블만 허용한다. 대형 아일랜드 매대는 소형 매장에서 사방 통로를 잡아먹어 배치 실패를 유발하므로 절대 금지.",
        "R7": "[수량 준수] 배치 가능 오브젝트 목록에 나온 수량을 절대 초과하지 마라. 목록에 shelf_wall이 3개면 3개까지만 배치하라. 임의로 더 추가하는 것은 금지.",
        "R8": "[가벽 zone 자율 — 1-3 (#523) 폐기 후 가이드만] partition_wall_I / partition_wall_L 의 zone 은 design agent 자율 결정. 목적 (동선 분할 / 유도 / 공간 분리 / staff_zone / pair_join 등) 이 명확하면 zone 무관 배치 가능. 단 입구 정면 시야 차단 케이스 (entrance_zone 중앙부에 가벽 단독 배치) 는 첫인상 손실 가능 — placement_reason 에 명확한 의도 (동선 분기 유도 / 파사드 미디어 / 파빌리온 진입 분리 등) 명시 시에만 entrance_zone 허용. 단순 'space_partition' 만으로 entrance_zone 가벽 배치는 의도 부족. (4-29 R8 = entrance_zone 절대 금지 → 1-3 에서 자율 영역 전환. 진규님 비전: 위치 강제 X, 목적 위주 자율 판단.)",
    },
    "medium": {
        "R1": "[전이 지대] entrance_zone 1.5~2m는 무조건 비워라. 이 영역에 기물을 배치하지 마라.",
        "R2": "[자석 효과] 계산대(counter/pos_counter)는 반드시 deep_zone 최후방에 배치. 고객이 매장 끝까지 이동하게 유도.",
        "R3": "[히어로 존] 입구 직후 전면 1/3 지점(entrance_zone과 mid_zone 경계)에 메인 매대(display_table 등)를 배치. 진입 직후 시선을 사로잡는 역할.",
        "R4": "[시야각 제약] 중앙 공간(center_freestanding): 1200mm 이하만 배치. 벽면: 1500mm 이상 우선. entrance_zone 중앙부: 1200mm 초과 절대 금지.",
        "R5": "[동선 폭] 기물 간 간격 최소 900~1200mm 유지. 같은 ref_point에 2개 이상 몰아넣지 마라. 분산 배치 우선.",
        "R6": "[중앙 배치 균형] center/freestanding 방향 배치는 공간 대비 적절한 수량으로 제한. 중앙 배치가 벽면 배치보다 많아지지 않도록 균형을 맞출 것.",
        "R7": "[수량 준수] 배치 가능 오브젝트 목록에 나온 수량을 절대 초과하지 마라.",
    },
}

# ── ZONING 정의 (zone별 의도 + 적정 기물 + R룰 매핑) ──────────────────

ZONING = {
    "small": {
        "context": "[공간 특성] 이 매장은 15~20평(50~66㎡) 소형 가두상권 팝업스토어입니다. 면적이 극히 제한적이므로 벽면 밀착 배치를 최우선으로 하고, 중앙은 최소한으로 활용하세요.",
        "layout": "[배치 형태 — ㄷ자(U-Shape) 최우선] 좌측 벽(side_wall) → 후면 벽(deep_wall) → 우측 벽(side_wall) 순으로 3면을 진열장으로 채우고 중앙을 비워라. 고객이 좌벽→후면→우벽→입구로 자연 순환하는 ㄷ자 동선이 소형 매장의 정석이다. 도면이 좁고 깊은 직사각형이면 좌우 벽에만 붙이는 11자(Parallel) 배치로 전환하라.",
        "entrance": {
            "intent": "고객이 매장 환경에 적응하는 감압 구역. 제품 판매보다 시야를 넓게 트여주고, 시각적 장치로 고객을 멈춰 세우는 데 집중.",
            "objects": ["signage_stand", "kiosk", "test_bar", "character_bbox"],
            "rules": ["R1", "R4", "R8"],
        },
        "mid": {
            "intent": "고객의 보행 속도를 늦추고 실질적 탐색이 일어나는 메인 스테이지. 동선이 일직선으로 통과하지 못하도록 물리적 장애물 배치. 체류 시간 극대화.",
            "objects": ["display_table", "shelf_wall", "consultation_desk", "partition_wall_I"],
            "rules": ["R3", "R5", "R6"],
        },
        "deep": {
            "intent": "고객을 최심부까지 끌어당기는 앵커 장치 + 스태프 기능 시설. 가장 목적성이 뚜렷한 기물을 배치하여 고객이 매장 끝까지 이동하게 유도.",
            "objects": ["counter", "photo_wall", "partition_wall_L"],
            "rules": ["R2"],
        },
        "glob": {
            "rules": ["R5", "R7", "R8"],
        },
    },
    "medium": {
        "context": "",
        "layout": "",
        "entrance": {
            "intent": "고객의 감압 전이 구역. 1.5~2m 비워두고, 히어로 매대로 시선 사로잡기.",
            "objects": ["display_table", "signage_stand", "character_bbox"],
            "rules": ["R1", "R3", "R4"],
        },
        "mid": {
            "intent": "주력 상품 탐색 + 체험 구역. 벽면 고밀도 진열 + 중앙 아일랜드로 동선 분기.",
            "objects": ["shelf_wall", "display_table", "consultation_desk", "partition_wall_I"],
            "rules": ["R5", "R6"],
        },
        "deep": {
            "intent": "결제 앵커 + 백오피스. 고객을 최심부까지 유도.",
            "objects": ["counter", "photo_wall", "partition_wall_L"],
            "rules": ["R2"],
        },
        "glob": {
            "rules": ["R5", "R7"],
        },
    },
}


# ── 배치 사유 사전 (Placement Reason Catalog) ──────────────────────────
# LLM이 placed_because 작성 시 아래 사유 중 해당하는 것을 선택 + 자유 서술 보충.
# placement_reason: 사전 키 (코드에서 분류/필터링용)
# placed_because: 자유 서술 (왜 이 ref_point인지, 주변 기물과의 관계 등)

PLACEMENT_REASONS = {
    # ── 운영 필수 ──
    "magnet_anchor": "자석 효과 — 고객을 매장 최심부까지 끌어들이기 위해 결제/목적 기물을 가장 안쪽에 배치",
    "staff_ops": "스태프 운영 — 결제·상담·재고 보충 등 스태프 동선 효율을 위한 배치",

    # ── 고객 동선 ──
    "decompression": "감압 구역 — 입구 직후 고객이 매장 환경에 적응하는 완충 공간 확보",
    "speed_bump": "속도 저감 — 고객 보행 속도를 늦추고 체류 시간을 늘리기 위한 물리적 장애물",
    "flow_guide": "동선 유도 — 고객이 특정 경로로 이동하도록 기물로 동선을 설계",
    "dead_spot_fill": "사각지대 해소 — 코너·기둥 뒤 등 인지하기 어려운 구역에 기물을 배치하여 동선 유도",

    # ── 시각·브랜드 ──
    "hero_display": "히어로 진열 — 입구 진입 직후 시선을 사로잡는 핵심 전시물",
    "power_wall": "파워 월 — 벽면 전체를 활용한 브랜드 임팩트 극대화",
    "sight_line": "시야 확보 — 매장 안쪽이 보이도록 시야선을 열어두는 배치",

    # ── 공간 구조 ──
    "space_partition": "공간 분할 — 가벽·파티션으로 zone 간 물리적 경계 형성",
    "balance": "좌우 균형 — 한쪽에 기물이 치우친 경우 반대편에 배치하여 시각적 무게 균형",
    "u_shape": "ㄷ자 배치 — 좌벽→후면→우벽 3면 진열로 자연 순환 동선 형성",

    # ── 기물 관계 ──
    "category_cluster": "카테고리 군집 — 체험→상담→구매 등 연관 기물을 인접 배치하여 자연스러운 전환",
    "pair_join": "기물 결합 — pair_rules에 따라 두 기물을 밀착/결합 배치",
    "back_to_back": "양면 결합 — 가벽 앞뒤 양면에 기물을 등지게 배치하여 진열 밀도 극대화",

    # ── 가벽 전용 (#253) ──
    "staff_zone": "스태프·창고 영역 분할 — 가벽으로 Back of House (스태프 대기 / 재고 / 쓰레기 등) 시야 차단 폐쇄 구역 형성",
}


# 2026-04-28: object_type 별 placement_reason 화이트리스트.
# PLACEMENT_REASONS 의 평면 dict 는 그대로 두되, 특정 object_type 은 사유 사용을 제한.
# 예: partition_wall_I 가 "balance" 같은 일반 사유로 단독 배치되는 패턴 차단 (구조적 결합 강제).
# 비어 있는 type 은 PLACEMENT_REASONS 전체 사용 가능.
RESTRICTED_REASONS = {
    # 2026-04-29 (#253): staff_zone 추가 — 가벽 Back of House 분할 의도 명시 가능.
    # I 도 좁은 매장에서 L 대신 staff 영역 분리 가능 → 둘 다 허용.
    "partition_wall_I": ["space_partition", "u_shape", "back_to_back", "pair_join", "staff_zone"],
    "partition_wall_L": ["space_partition", "back_to_back", "pair_join", "staff_zone"],
}


# 2026-04-29 (#254): 가벽 짝꿍 (pair_join / back_to_back) 후보 객체 정의.
# partition_placement.py Layer 3 에서 단독 배치 가벽 drop 검증 시 사용.
# 기존 partition_placement.py L309-312 의 로컬 _PARTITION_PAIR_CANDIDATES 외부화.
# 카테고리별 차등 — 매장 운영 특성에 맞는 짝꿍 객체 set.
# 미정의 카테고리 → GENERIC fallback (기타 / 미등록).

PARTITION_PAIR_GENERIC: dict[str, set[str]] = {
    # 모든 카테고리 공통 짝꿍 후보. 카테고리 차등 없을 때 fallback.
    "partition_wall_I": {"shelf_wall", "shelf_3tier", "photo_wall", "display_table", "consultation_desk"},
    "partition_wall_L": {"shelf_wall", "shelf_3tier"},
}

# 2026-05-01 SSOT 마이그레이션: PARTITION_PAIR_BY_CATEGORY 는 app.categories 의
# `Category.partition_pair` 로 이전. get_partition_pair_candidates 가 SSOT lookup.
# Drift 방지 — 신규 카테고리 추가 시 categories.py 한 곳만 수정.


def get_partition_pair_candidates(obj_type: str, category: str = "기타") -> set[str]:
    """가벽 (partition_wall_I/L) 의 짝꿍 (pair_join / back_to_back) 후보 객체 set 반환.

    SSOT (app.categories) 의 카테고리별 partition_pair → GENERIC fallback.

    Args:
        obj_type: "partition_wall_I" 또는 "partition_wall_L"
        category: brand_category. 미등록 / "기타" → GENERIC

    Returns:
        짝꿍 후보 object_type set. obj_type 이 partition_wall_I/L 외면 빈 set.

    예:
        get_partition_pair_candidates("partition_wall_I", "뷰티·코스메틱")
        → {"shelf_wall", "shelf_3tier", "consultation_desk", "test_bar", "display_table"}

        get_partition_pair_candidates("partition_wall_I", "기타")
        → GENERIC 의 partition_wall_I set
    """
    from app.categories import get_category
    overrides = get_category(category).partition_pair
    if obj_type in overrides:
        return overrides[obj_type]
    return PARTITION_PAIR_GENERIC.get(obj_type, set())


def build_zoning_prompt(size: str) -> str:
    """ZONING + R_RULES → LLM용 프롬프트 텍스트 조립.

    R룰을 펼쳐서 zone별로 붙인 최종 텍스트 반환.
    """
    rules = R_RULES.get(size, R_RULES["small"])
    zoning = ZONING.get(size, ZONING["small"])

    lines = []

    # CONTEXT, LAYOUT
    if zoning.get("context"):
        lines.append(zoning["context"])
        lines.append("")
    if zoning.get("layout"):
        lines.append(zoning["layout"])
        lines.append("")

    # 각 zone
    zone_labels = {
        "entrance": "Entrance Zone — 감압 및 후킹 구역",
        "mid": "Mid Zone — 핵심 제품 관여 및 순환 구역",
        "deep": "Deep Zone — 목적지 및 백오피스 구역",
    }

    for zone_key, zone_title in zone_labels.items():
        zone = zoning.get(zone_key)
        if not zone:
            continue

        lines.append(f"[{zone_title}]")
        lines.append(f"- 기획 의도: {zone['intent']}")

        if zone.get("objects"):
            obj_str = ", ".join(zone["objects"])
            lines.append(f"- 적정 기물: {obj_str}")

        # R룰 펼치기
        for r_key in zone.get("rules", []):
            r_text = rules.get(r_key, "")
            if r_text:
                lines.append(f"- {r_key}: {r_text}")

        lines.append("")

    # 전역 규칙
    glob = zoning.get("glob")
    if glob and glob.get("rules"):
        lines.append("[전역 규칙]")
        for r_key in glob["rules"]:
            r_text = rules.get(r_key, "")
            if r_text:
                lines.append(f"- {r_key}: {r_text}")
        lines.append("")

    return "\n".join(lines)
