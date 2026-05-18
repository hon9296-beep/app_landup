"""
프로젝트 공용 VMD 상수 — 타입명, 키 이름, 규격, 이격 등 여러 모듈에서 참조하는 값을 한 곳에서 정의.

변경 시 이 파일만 수정하면 import한 모든 곳에 자동 반영.
reference.py에서 이동 (2026-04-16).
"""

# ── inaccessible room 타입 ─────────────────────────────────────────────
ROOM_TYPE_STAIR = "stair"
ROOM_TYPE_TOILET = "toilet"
ROOM_TYPE_PILLAR = "pillar"
ROOM_TYPE_CORE = "core"

POLYGON_RENDER_TYPES = {ROOM_TYPE_CORE, ROOM_TYPE_TOILET, ROOM_TYPE_STAIR, ROOM_TYPE_PILLAR, "core_access", "inner_wall"}

DEAD_ZONE_LABELS = {
    "sprinkler": "SP", "fire_hydrant": "FH", "electrical_panel": "EP",
    ROOM_TYPE_CORE: "화장실", ROOM_TYPE_TOILET: "TO", ROOM_TYPE_STAIR: "ST",
    ROOM_TYPE_PILLAR: "기둥", "core_access": "진입로", "inner_wall": "내벽",
    "emergency_exit": "비상구",
}

DEAD_ZONE_NAMES = {
    "sprinkler": "스프링클러", "fire_hydrant": "소화전", "electrical_panel": "분전반",
    ROOM_TYPE_CORE: "화장실/계단", ROOM_TYPE_TOILET: "화장실", ROOM_TYPE_STAIR: "계단",
    ROOM_TYPE_PILLAR: "기둥", "core_access": "진입로 확보", "inner_wall": "내벽",
    "emergency_exit": "비상구",
}

CORE_FILTER_RADIUS = {
    ROOM_TYPE_STAIR: 1500, ROOM_TYPE_TOILET: 900,
    ROOM_TYPE_CORE: 900, ROOM_TYPE_PILLAR: 300,
}

# ── 전후 이격 (Directional Clearance) ────────────────────────────────
# 기물 정면(front) / 후면(back) 방향으로 확보해야 할 사용자 활동 공간(mm).
# 본 값은 "정상 환경에서의 기본 이격". 실제 적용은 면적 비례 스케일 + floor 하한선이
# 적용된 값을 사용 (compute_scaled_clearance 참조).
DIRECTIONAL_CLEARANCE = {
    "photo_wall":     {"front": 2000, "back": 0},
    "photo_island":   {"front": 1500, "back": 0},
    "counter":        {"front": 900,  "back": 600},
    "consultation_desk": {"front": 900, "back": 0},   # 2026-04-20 Tier 1-1 보강
    "shelf_wall":     {"front": 600,  "back": 0},
    "shelf_standard": {"front": 600,  "back": 0},
    "shelf_3tier":    {"front": 600,  "back": 0},
    "test_bar":       {"front": 600,  "back": 0},     # 2026-04-20 Tier 1-1 보강
    "display_table":  {"front": 0,    "back": 0},
    "kiosk":          {"front": 600,  "back": 0},
    "banner_stand":   {"front": 0,    "back": 0},
    "character_bbox": {"front": 0,    "back": 0},
    "signage_stand":  {"front": 0,    "back": 0},
    "partition_wall_I": {"front": 0,  "back": 0},
    "partition_wall_L": {"front": 0,  "back": 0},
}

# ── DIRECTIONAL_CLEARANCE_FLOOR (인체 안전 하한선) ────────────────────
# [중요/회귀방지] 2026-04-20 Tier 1-1 도입.
# VMD 실무 floor 값 — 기물 본래 기능이 성립하는 최소 사용자 활동 공간(mm).
# 외부 VMD 전문가(제미나이) 검증 완료. 인체 치수 + 건축법 기반.
#   - photo_wall/island front=1500: 스마트폰 표준 화각으로 성인 전신 촬영 최소 거리
#   - counter/consultation_desk front=900: 직원-고객 응대 최소 거리
#   - shelf/test_bar/kiosk front=600: 사람 어깨넓이 + 통행 최소 폭
# 면적 비례 스케일이나 step-down 시에도 floor 이하로는 절대 내려가지 않음.
# 브랜드 매뉴얼이 floor 미만 값을 명시해도 max(brand, floor)로 강제 (옵션 A 채택).
DIRECTIONAL_CLEARANCE_FLOOR = {
    "photo_wall":        {"front": 1500, "back": 0},
    "photo_island":      {"front": 1500, "back": 0},
    "counter":           {"front": 900,  "back": 600},
    "consultation_desk": {"front": 900,  "back": 0},
    "shelf_wall":        {"front": 600,  "back": 0},
    "shelf_standard":    {"front": 600,  "back": 0},
    "shelf_3tier":       {"front": 600,  "back": 0},
    "test_bar":          {"front": 600,  "back": 0},
    "kiosk":             {"front": 600,  "back": 0},
}

# ── Step-down / 면적 스케일 파라미터 ───────────────────────────────────
STEP_DOWN_MM = 200                   # Phase 5 step-down 단위 (실무 정합성: 50은 마감 오차, 200이 도면 유의미 변화)
SCALING_REFERENCE_AREA_MM2 = 99_000_000  # 30평(99㎡) 기준 ratio=1.0


def compute_scaled_clearance(
    obj_type: str,
    usable_area_mm2: float,
    brand_override: dict | None = None,
) -> dict:
    """기물 전후 이격의 초기 시도값 산출.

    적용 순서:
      1. brand_override (브랜드 매뉴얼 명시값)이 있으면 → max(brand, floor) 반환
         (옵션 A: 인체 안전 우선. 브랜드가 floor 이하 지정해도 floor 강제)
      2. 없으면 면적 비례 스케일: int(base * min(1.0, area / 99㎡))
         결과가 floor 미만이면 floor로 clamp.

    Args:
        obj_type: 기물 표준 타입
        usable_area_mm2: 바닥 가용 면적 (mm²)
        brand_override: {"front": int, "back": int} 또는 None

    Returns:
        {"front": int, "back": int} dict
    """
    base = DIRECTIONAL_CLEARANCE.get(obj_type)
    if not base:
        return {"front": 0, "back": 0}
    floor = DIRECTIONAL_CLEARANCE_FLOOR.get(obj_type, {"front": 0, "back": 0})

    if brand_override:
        # 옵션 A: 인체 안전 floor 강제. 브랜드값이 floor 이하라도 floor 적용.
        return {
            "front": max(floor.get("front", 0), int(brand_override.get("front", 0) or 0)),
            "back":  max(floor.get("back", 0),  int(brand_override.get("back", 0) or 0)),
        }

    ratio = min(1.0, usable_area_mm2 / SCALING_REFERENCE_AREA_MM2)
    return {
        "front": max(floor.get("front", 0), int(base["front"] * ratio)),
        "back":  max(floor.get("back", 0),  int(base["back"]  * ratio)),
    }


def step_down_clearance(
    current: dict,
    obj_type: str,
) -> dict | None:
    """현재 clearance를 STEP_DOWN_MM(200mm)씩 낮춤. floor 도달 시 None 반환.

    Phase 5 fallback에서 호출. Phase 4까지 실패한 기물에 한해 점진적 완화 시도.

    Args:
        current: {"front": int, "back": int} 현재 적용 중 clearance
        obj_type: 기물 표준 타입

    Returns:
        한 단계 낮춘 {"front": int, "back": int} dict.
        front/back 둘 다 이미 floor에 도달했으면 None.
    """
    floor = DIRECTIONAL_CLEARANCE_FLOOR.get(obj_type, {"front": 0, "back": 0})
    new_front = max(floor.get("front", 0), current.get("front", 0) - STEP_DOWN_MM)
    new_back  = max(floor.get("back", 0),  current.get("back", 0) - STEP_DOWN_MM)
    if new_front == current.get("front", 0) and new_back == current.get("back", 0):
        return None  # 더 이상 낮출 수 없음
    return {"front": new_front, "back": new_back}

# ── VMD_BOUNDARIES: 팝업스토어 현실 규격 (min/std/max) ──────────────────
VMD_BOUNDARIES = {
    "counter":               {"width_mm": {"min": 900, "std": 1500, "max": 2400}, "depth_mm": {"min": 600, "std": 600, "max": 800}, "height_mm": {"min": 850, "std": 900, "max": 1100}, "front_edge": "width"},
    "display_table":         {"width_mm": {"min": 800, "std": 1200, "max": 1800}, "depth_mm": {"min": 600, "std": 800, "max": 1200}, "height_mm": {"min": 800, "std": 850, "max": 1200}, "front_edge": "width"},
    "display_table_standard": {"width_mm": {"min": 800, "std": 1200, "max": 1800}, "depth_mm": {"min": 600, "std": 800, "max": 1200}, "height_mm": {"min": 800, "std": 850, "max": 1200}, "front_edge": "width"},
    "shelf_wall":            {"width_mm": {"min": 900, "std": 1800, "max": 2400}, "depth_mm": {"min": 300, "std": 400, "max": 500}, "height_mm": {"min": 1500, "std": 1800, "max": 2400}, "front_edge": "width"},
    "shelf_standard":        {"width_mm": {"min": 900, "std": 1800, "max": 2400}, "depth_mm": {"min": 300, "std": 400, "max": 500}, "height_mm": {"min": 1500, "std": 1800, "max": 2400}, "front_edge": "width"},
    "photo_wall":            {"width_mm": {"min": 1500, "std": 2400, "max": 3600}, "depth_mm": {"min": 150, "std": 200, "max": 500}, "height_mm": {"min": 2100, "std": 2200, "max": 2400}, "front_edge": "width"},
    "photo_island":          {"width_mm": {"min": 1200, "std": 1800, "max": 2400}, "depth_mm": {"min": 800, "std": 1200, "max": 1500}, "height_mm": {"min": 1800, "std": 2200, "max": 2400}, "front_edge": "width"},
    "character_bbox":        {"width_mm": {"min": 300, "std": 600, "max": 1200}, "depth_mm": {"min": 200, "std": 300, "max": 500}, "height_mm": {"min": 500, "std": 1800, "max": 2000}, "front_edge": "width"},
    "shelf_3tier":           {"width_mm": {"min": 600, "std": 900, "max": 1200}, "depth_mm": {"min": 300, "std": 450, "max": 600}, "height_mm": {"min": 900, "std": 1200, "max": 1500}, "front_edge": "width"},
    "banner_stand":          {"width_mm": {"min": 600, "std": 600, "max": 800}, "depth_mm": {"min": 300, "std": 400, "max": 500}, "height_mm": {"min": 1800, "std": 1800, "max": 2200}, "front_edge": "width"},
    "signage_stand":         {"width_mm": {"min": 400, "std": 600, "max": 600}, "depth_mm": {"min": 350, "std": 500, "max": 500}, "height_mm": {"min": 900, "std": 900, "max": 1200}, "front_edge": "width"},
    "kiosk":                 {"width_mm": {"min": 500, "std": 500, "max": 500}, "depth_mm": {"min": 400, "std": 400, "max": 400}, "height_mm": {"min": 1700, "std": 1700, "max": 1700}, "front_edge": "width"},
    "partition_wall_I":      {"width_mm": {"min": 1000, "std": 2000, "max": 3000}, "depth_mm": {"min": 100, "std": 150, "max": 200}, "height_mm": {"min": 2100, "std": 2400, "max": 3000}, "front_edge": "width"},
    "partition_wall_L":      {"width_mm": {"min": 1000, "std": 2000, "max": 3000}, "depth_mm": {"min": 1000, "std": 1500, "max": 2000}, "height_mm": {"min": 2100, "std": 2400, "max": 3000}, "front_edge": "width"},
}

VMD_PAIR_RULES = [
    # 1-3 후속 (#535 후속): 동일 std_id cluster default = join.
    # 진규님 5-7 비전: VMD 실무에서 POS 카운터 + 증정품 카운터 / 진열대 라인업 = 나란히 붙어 있음 정상.
    # 18평 LUMIA 라이브 (5-7 21:17): counter 2개가 separate 1200mm 강제로 각 wall 차지 →
    # photo_wall 자리 부족 → drop 회귀. default 를 cluster 로 변경하면 1 wall 만 차지.
    # 단 counter ↔ 다른 obj (display_table 등) 는 separate 1200 유지 (의미 분리 / 동선 폭).
    # _find_pair_rule 은 list 순서대로 첫 매칭 반환 → 동일 type 룰을 wildcard 위에 배치.
    {"object_a": "counter",        "object_b": "counter",        "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "display_table",  "object_b": "display_table",  "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "shelf_wall",     "object_b": "shelf_wall",     "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    # 1-3 후속 (#535 후속 — B): 결제 (counter) ↔ 상담 (consultation_desk) 사이 빈 공간 강제.
    # 의미: 두 obj 박스 가장자리 사이 통로/분리 영역 최소 거리.
    # 변천:
    #   - 5-7 어제 박음: 2400mm (모호한 "VMD 시퀀스 분리" 의도, 실무 표준 X — 임의 수치)
    #   - 5-8 라이브 분석: 18평 우측벽 시리즈 (wall_13~15) 사이 거리가 2400 미만 →
    #     LLM 의도 (counter wall_15 + consultation wall_13 같은 우측벽 cluster) placement reject
    #     → consultation 좌측 외곽 강제 끼워박힘 회귀
    #   - 5-8 채택: 1500mm (응대 직원 + 통과 손님 동시 가능 실무 표준).
    #     어제 회귀 (상담 결제 옆) 차단 + 우측벽 cluster 의도 양립.
    {"object_a": "counter",        "object_b": "consultation_desk", "relation": "separate", "min_gap_mm": 1500, "overlap_margin_mm": 0},
    # consultation_desk 끼리는 cluster 가능 (같은 wall 라인업)
    {"object_a": "consultation_desk", "object_b": "consultation_desk", "relation": "join", "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "character_bbox", "object_b": "photo_wall",     "relation": "adjacent", "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "character_bbox", "object_b": "photo_island",   "relation": "adjacent", "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "partition_wall_I", "object_b": "photo_wall",   "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "counter",        "object_b": "*",              "relation": "separate", "min_gap_mm": 1200, "overlap_margin_mm": 0},
    {"object_a": "partition_wall_I", "object_b": "shelf_wall",       "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "partition_wall_L", "object_b": "shelf_wall",       "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "partition_wall_I", "object_b": "shelf_3tier",      "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "partition_wall_L", "object_b": "shelf_3tier",      "relation": "join",     "min_gap_mm": 0,    "overlap_margin_mm": 0},
    {"object_a": "partition_wall_I", "object_b": "*",                "relation": "separate", "min_gap_mm": 600,  "overlap_margin_mm": 0},
    {"object_a": "partition_wall_L", "object_b": "*",                "relation": "separate", "min_gap_mm": 600,  "overlap_margin_mm": 0},
    {"object_a": "partition_wall_I", "object_b": "partition_wall_I", "relation": "separate", "min_gap_mm": 1200, "overlap_margin_mm": 0},
    {"object_a": "partition_wall_I", "object_b": "partition_wall_L", "relation": "separate", "min_gap_mm": 1200, "overlap_margin_mm": 0},
]

VMD_WALL_ATTACHMENT: dict[str, str] = {
    "counter": "near",
    "display_table": "free", "display_table_standard": "free",
    "shelf_wall": "flush", "shelf_standard": "flush", "shelf_3tier": "flush",
    "photo_wall": "flush", "photo_island": "free",
    "character_bbox": "free", "banner_stand": "either",
    "partition_wall_I": "flush", "partition_wall_L": "flush",
    "signage_stand": "free", "kiosk": "near",
}

# ── 카테고리별 max_count ──────────────────────────────────────────────
import math as _math

# ════════════════════════════════════════════════════════════════════════
# [신규 / Single Source of Truth] 2026-04-23 도입
# 소형 파이프라인 default_placement_rules 의 새 카테고리 인식 구조.
# 사용처: app/nodes_small/object_selection.py (소형 only).
# nodes_large 및 scripts/seed_from_source.py 는 아래 LEGACY dict 를 계속 참조.
#
# 설계 원칙 (Gemini 자문 2026-04-23 기반):
#   - Data Layer 는 카테고리별 후보군 종류만 통제. 수량은 S-8 컴퓨팅이 결정
#   - Generic = 카테고리 무관 팝업스토어 공통 기물
#   - Extras = 그 카테고리에 특화된 추가 기물 (또는 generic count override)
#   - 합성: count_table = MAX_COUNT_GENERIC | CATEGORY_EXTRAS.get(category, {})
#     dict union 우선순위: 우항(extras) 이 좌항(generic) override
# ════════════════════════════════════════════════════════════════════════

MAX_COUNT_GENERIC: dict[str, int] = {
    # 카테고리 무관 팝업스토어 공통 기물
    "counter": 1,
    "display_table": 4,
    "shelf_wall": 6,
    "shelf_3tier": 3,
    "photo_wall": 1,
    "photo_island": 1,
    "banner_stand": 3,
}

# ⚠ 2026-05-01 SSOT 마이그레이션: 본 dict 는 app.categories 의 SSOT 와 병존.
# 신규 코드는 `from app.categories import get_category` → `get_category(key).extras` 사용 권장.
# 본 dict 는 후속 PR 에서 제거 예정. 단위 테스트가 SSOT 와 1:1 일치 강제 (drift 방지).
CATEGORY_EXTRAS: dict[str, dict[str, int]] = {
    # 캐릭터 IP — 메인 어트랙션(캐릭터 조형물) + 웨이팅/이벤트 키오스크
    "캐릭터 IP": {
        "character_bbox": 4,
        "kiosk": 1,
    },
    # 뷰티 — generic 의 진열 기물 축소 override (체험·상담 위주) + 고유 기물
    "뷰티·코스메틱": {
        "display_table": 2,        # generic 4 → 2
        "shelf_wall": 3,           # generic 6 → 3
        "test_bar": 2,
        "consultation_desk": 2,
        "signage_stand": 1,
        "kiosk": 1,
        "partition_wall_I": 1,
        "aux_table": 1,
    },
    # 패션 — 등록된 fashion 특화 기물 없음. fitting_room/hanger_rack/mannequin_stand
    # 신규 등록 후 추가 (worklist I-4)
    "패션 브랜드": {},
    # F&B — 회전율 키오스크 + 메뉴판 (showcase_cooler/tasting_stand 신규 등록 후 추가)
    "F&B": {
        "kiosk": 1,
        "signage_stand": 1,
    },
    # 테크 — 시연 + 상담 + 스펙 안내
    "테크·전자제품": {
        "test_bar": 2,
        "consultation_desk": 1,
        "signage_stand": 1,
    },
    # 아트 — 작품 걸이용 가벽 + 규격 굿즈 진열대 + 캡션 안내
    "아트·전시": {
        "partition_wall_I": 2,
        "display_table_standard": 2,
        "signage_stand": 2,
    },
    # 엔터·팬미팅 — 아티스트 등신대 (character_bbox 재활용. photo_booth 신규 등록 후 추가)
    "엔터·팬미팅": {
        "character_bbox": 1,
    },
    # "기타" 는 등록 안 함 → CATEGORY_EXTRAS.get(..., {}) → generic only
    # (이전 MAX_COUNT_BY_CATEGORY["기타"] = MAX_COUNT_CHARACTER_IP 의 fallback 버그 자연 해소)
}

# ════════════════════════════════════════════════════════════════════════
# [LEGACY / 하위 호환] 2026-04-23 이전부터 존재. 제거 금지.
# 사용처: nodes_large/reference.py (Shin 영역, 수정 금지),
#         scripts/seed_from_source.py (DB 시딩, 별도 마일스톤에서 신규 구조로 이행 예정)
# 신규 코드는 위 MAX_COUNT_GENERIC + CATEGORY_EXTRAS 사용할 것.
# ════════════════════════════════════════════════════════════════════════

MAX_COUNT_CHARACTER_IP: dict[str, int] = {
    "counter": 1, "display_table": 4, "shelf_wall": 6,
    "shelf_3tier": 3, "photo_wall": 1, "photo_island": 1, "character_bbox": 4, "banner_stand": 3,
}

MAX_COUNT_BEAUTY: dict[str, int] = {
    "counter": 1, "test_bar": 2, "consultation_desk": 2,
    "display_table": 2, "shelf_wall": 3, "photo_wall": 1,
    "signage_stand": 1, "kiosk": 1, "partition_wall_I": 1,
}

MAX_COUNT_BY_CATEGORY: dict[str, dict[str, int]] = {
    "캐릭터 IP": MAX_COUNT_CHARACTER_IP,
    "뷰티·코스메틱": MAX_COUNT_BEAUTY,
    "기타": MAX_COUNT_CHARACTER_IP,
}

VMD_BOUNDARIES_BEAUTY = {
    "counter":           {"width_mm": {"min": 900, "std": 1200, "max": 1500}, "depth_mm": {"min": 600, "std": 600, "max": 700}, "height_mm": {"min": 850, "std": 900, "max": 1100}, "front_edge": "width"},
    "test_bar":          {"width_mm": {"min": 900, "std": 1200, "max": 1800}, "depth_mm": {"min": 600, "std": 700, "max": 800}, "height_mm": {"min": 900, "std": 950, "max": 1000}, "front_edge": "width"},
    "consultation_desk": {"width_mm": {"min": 500, "std": 700, "max": 900},  "depth_mm": {"min": 500, "std": 600, "max": 700}, "height_mm": {"min": 700, "std": 750, "max": 800}, "front_edge": "width"},
    "display_table":     {"width_mm": {"min": 800, "std": 1200, "max": 1500}, "depth_mm": {"min": 600, "std": 800, "max": 1000}, "height_mm": {"min": 800, "std": 900, "max": 1000}, "front_edge": "width"},
    "shelf_wall":        {"width_mm": {"min": 900, "std": 1200, "max": 1800}, "depth_mm": {"min": 300, "std": 400, "max": 500},  "height_mm": {"min": 1800, "std": 2100, "max": 2400}, "front_edge": "width"},
    "photo_wall":        {"width_mm": {"min": 1500, "std": 2000, "max": 2400}, "depth_mm": {"min": 150, "std": 200, "max": 500},  "height_mm": {"min": 2100, "std": 2200, "max": 2400}, "front_edge": "width"},
    "photo_island":      {"width_mm": {"min": 1200, "std": 1800, "max": 2400}, "depth_mm": {"min": 800, "std": 1200, "max": 1500}, "height_mm": {"min": 1800, "std": 2200, "max": 2400}, "front_edge": "width"},
    "partition_wall_I":  {"width_mm": {"min": 1200, "std": 2000, "max": 2400}, "depth_mm": {"min": 100, "std": 150, "max": 300},  "height_mm": {"min": 2100, "std": 2400, "max": 2400}, "front_edge": "width"},
    "signage_stand":     {"width_mm": {"min": 400, "std": 600, "max": 600},   "depth_mm": {"min": 350, "std": 500, "max": 500},  "height_mm": {"min": 900, "std": 900, "max": 1200}, "front_edge": "width"},
    "kiosk":             {"width_mm": {"min": 300, "std": 400, "max": 500},   "depth_mm": {"min": 300, "std": 400, "max": 400},  "height_mm": {"min": 1200, "std": 1500, "max": 1700}, "front_edge": "width"},
}

VMD_BOUNDARIES_BY_CATEGORY = {
    "캐릭터 IP": VMD_BOUNDARIES,
    "뷰티·코스메틱": VMD_BOUNDARIES_BEAUTY,
    "기타": VMD_BOUNDARIES,
}


def get_vmd_boundaries(brand_category: str = "기타") -> dict:
    """카테고리별 VMD_BOUNDARIES 반환. 없으면 기본값."""
    return VMD_BOUNDARIES_BY_CATEGORY.get(brand_category, VMD_BOUNDARIES)


def scale_count(base: int, area_m2: float) -> int:
    """면적 기반 max_count 스케일링."""
    if area_m2 < 66:
        return max(1, _math.ceil(base * 0.5))
    elif area_m2 > 99:
        return max(1, _math.floor(base * 1.5))
    return base


