"""
오브젝트 선별 노드 — rendy/modules/object_selection.py 기반.

IQI(Intelligent Quantity Inference) — 밀도 25% 상한 + 우선순위 스코어.
Supabase 의존 제거, brand_data의 placement_rules에서 오브젝트 목록 구성.
"""
import logging

from app.state import SmallState
from app.utils import OBJECT_STANDARDS, normalize_object_type
from app.vmd_constants import VMD_WALL_ATTACHMENT, get_vmd_boundaries

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# 밀도 tier — 2026-04-22 S-8g-1 제미나이 자문 Q1 반영
# ─────────────────────────────────────────────────────────────────────
# VMD 실무 "25% 밀도 법칙" 을 면적대별 동적 분기. 순수 기물 점유율(net) 기준.
# 경계값은 app.constants 의 SMALL/MEDIUM_AREA_THRESHOLD_MM2 재활용.
#
# 근거:
#   - small (< 20평): 0.15 — 18평 NEW 실측에서 net utilization 46% 폭증 관측.
#     동선/감압존 여유를 위해 기물 점유율 하향 필요.
#   - medium (20~50평): 0.20 — 중형 실측 진입 전 보수적 추정. M-7 에서 튜닝.
#   - large (≥ 50평): 0.25 — Shin 영역 fallback. Rendy 정상 진입 안 함.

DENSITY_RATIO_BY_TIER: dict[str, float] = {
    "small": 0.15,
    "medium": 0.20,
    "large": 0.25,
}

# 기존 호출부 호환용 fallback. 신규 코드는 _get_density_ratio() 사용 권장.
MAX_DENSITY_RATIO = DENSITY_RATIO_BY_TIER["large"]

# height_mm 누락 시 기본값
DEFAULT_HEIGHT_MM = 1500


def _get_density_ratio(usable_area_mm2: float) -> float:
    """면적 기반 density_ratio 조회. 3단 tier 분기.

    small  < 66M mm²        → 0.15
    medium 66M ~ 165M mm²   → 0.20
    large  ≥ 165M mm²       → 0.25 (Shin 영역 fallback)
    """
    from app.constants import SMALL_AREA_THRESHOLD_MM2, MEDIUM_AREA_THRESHOLD_MM2
    if usable_area_mm2 < SMALL_AREA_THRESHOLD_MM2:
        return DENSITY_RATIO_BY_TIER["small"]
    if usable_area_mm2 < MEDIUM_AREA_THRESHOLD_MM2:
        return DENSITY_RATIO_BY_TIER["medium"]
    return DENSITY_RATIO_BY_TIER["large"]

# 기물 우선순위 — OBJECT_STANDARDS에서 생성
_PRIORITY_SCORE: dict[str, int] = {
    std_id: std["priority"] for std_id, std in OBJECT_STANDARDS.items()
}


# ─────────────────────────────────────────────────────────────────────
# footprint 계산 — 2026-04-22 S-8a 제미나이 자문 반영
# ─────────────────────────────────────────────────────────────────────
# 기존 A안 공식 `(w + front + 1200) × (d + back + 1200)` 의 문제:
#   1. 차원 혼동: DIRECTIONAL_CLEARANCE front/back 은 모두 depth 축 공간인데
#      공식에서 front 를 width 축에 가산 → 의미 불일치
#   2. 1200mm 이중 가산: width/depth 양쪽 모두 가산 = 사방 개방 아일랜드 가정.
#      벽부착 기물(flush) 에서는 면적 과대 계상 (photo_wall, shelf_wall 등).
#
# 제미나이 권고 반영 (2026-04-22_cap_computing_design_question.md Q4):
#   VMD_WALL_ATTACHMENT 유형별로 버퍼 가산 방식 분기.
#     - flush (벽밀착, shelf_wall/photo_wall/partition_wall/shelf_standard/shelf_3tier):
#         width × (depth + front + BUFFER) — 정면 사용자 통로만
#     - near (벽근처, counter/kiosk):
#         (width + NEAR_SIDE) × (depth + front + back + BUFFER)
#         — 좌/우 여유 + 앞/뒤 공간
#     - free (아일랜드, display_table/photo_island/character_bbox/signage_stand):
#         (width + BUFFER) × (depth + front + back + BUFFER) — 사방 접근
#     - either (banner_stand): free 와 동일 보수 계산

BUFFER_MM = 1200          # 메인 보행 동선 여유 폭 (VMD 실무 기준)
NEAR_SIDE_BUFFER_MM = 600  # 벽근처(near) 기물 좌/우 여유 폭


def calculate_footprint(
    obj_type: str,
    width_mm: int,
    depth_mm: int,
) -> int:
    """기물 1개의 공간 점유 면적(mm²) 계산 — cap computing 용.

    VMD_WALL_ATTACHMENT 기반 벽부착 유형별 버퍼 가산 방식 분기.
    front/back clearance 는 DIRECTIONAL_CLEARANCE 기본값 사용.

    주의: 본 함수는 "공간 예산 대비 이 기물이 몇 개까지 들어가나" 계산용.
    실제 배치 성공 여부(벽 길이, 데드존, 충돌)는 placement 단계에서 결정.

    Args:
        obj_type: 기물 표준 타입 (VMD_WALL_ATTACHMENT 키와 매칭)
        width_mm: 기물 가로 (w 축)
        depth_mm: 기물 세로 (d 축)

    Returns:
        공간 점유 면적 (mm²). 최소 1 보장 (0 division 방어).
    """
    from app.vmd_constants import DIRECTIONAL_CLEARANCE

    attachment = VMD_WALL_ATTACHMENT.get(obj_type, "free")
    clearance = DIRECTIONAL_CLEARANCE.get(obj_type, {"front": 0, "back": 0})
    front = clearance.get("front", 0) or 0
    back = clearance.get("back", 0) or 0

    if attachment == "flush":
        w = width_mm
        d = depth_mm + front + BUFFER_MM
    elif attachment == "near":
        w = width_mm + NEAR_SIDE_BUFFER_MM
        d = depth_mm + front + back + BUFFER_MM
    else:  # free, either, 또는 미등록 타입
        w = width_mm + BUFFER_MM
        d = depth_mm + front + back + BUFFER_MM

    return max(1, w * d)


def calculate_local_cap(
    obj_type: str,
    width_mm: int,
    depth_mm: int,
    effective_area_mm2: float,
) -> int:
    """이 obj_type 1종이 effective_area 안에 몇 개까지 들어갈 수 있는지 산출.

    공식: max(1, int(effective_area / footprint))

    floor=1 의미: 공간이 좁아 footprint > effective 여도 최소 1개 시도 보장.
    배치 실패 여부(벽 길이/충돌)는 placement 단계 drop 으로 자연 해결.
    제미나이 자문 (Q2): cap 단계는 "허수 차단" 만, trade-off 는 placement 영역.

    Args:
        obj_type: 기물 표준 타입
        width_mm, depth_mm: 기물 크기
        effective_area_mm2: 가용 면적 × density_ratio (보통 0.25)

    Returns:
        local cap (≥ 1).
    """
    footprint = calculate_footprint(obj_type, width_mm, depth_mm)
    if footprint <= 0:
        return 1
    cap = int(effective_area_mm2 / footprint)
    if footprint > effective_area_mm2:
        # 공간 대비 footprint 초과 — placement 단계에서 drop 가능성 높음 (info 로그)
        logger.info(
            f"[local_cap] {obj_type} footprint({footprint:,}mm²) > "
            f"effective_area({int(effective_area_mm2):,}mm²) — "
            f"floor=1 적용. 배치 시도 후 drop 가능성"
        )
    return max(1, cap)


# ─────────────────────────────────────────────────────────────────────
# brand 가중치 정렬 — 2026-04-22 S-8c 제미나이 자문 반영
# ─────────────────────────────────────────────────────────────────────
# 권고 핵심:
#   - BRAND_BONUS = +20: 같은 등급 내 브랜드 우선, 공간 위계 파괴 안 함
#     · 예: brand kiosk(45+20=65) ≥ default shelf_wall(65) 동급, but counter(95) 자리는 못 뺏음
#     · +50/+100 은 오버엔지니어링 (악의적 brand 가 필수 기물 drop 시킴)
#   - 첫 1개만 가중: counter ×5 같은 스팸 방어. obj_type 별 첫 등장 brand 만 +20.
#     나머지는 default 점수로 다른 기물과 정당 경쟁
#   - tie-break: footprint ASC (작은 것 먼저) — 결정론 + 예산 효율
#   - Q4 family 자동 대체는 별도 작업 (S-8c-2) 으로 분리

BRAND_BONUS = 20


# ─────────────────────────────────────────────────────────────────────
# Family cap — 2026-04-22 S-8c-2 제미나이 자문 Q3/Q5 재진단 반영
# ─────────────────────────────────────────────────────────────────────
# 같은 기능 수행 기물군(consultation_desk + consultation_table 등)을 단일 family 로
# 묶어 합산 한도 적용. cap 단계에서 잉여 기물 사전 차단 → placement slot 경쟁 완화 →
# brand 필수 기물(photo_wall/counter) 보호.
#
# 값 근거: 2026-04-22 OLD (pre-refactor) 18평 LUMIA 실측 placed=10 결과 역산.
# 면적대별 동적 분기는 중형 실측 진입 시 확장 (M-7 Phase 3-A).

FAMILY_CAPS_SMALL: dict[str, int] = {
    "consultation": 2,   # desk + table 합산 — OLD 실측 2 기준
    "display": 2,        # table + table_standard
    "photo": 1,          # wall + island — 앵커 역할, 중복 금지
    # [2026-04-22 S-8f v2 — 제미나이 Q1] shelf 3 → 1 축소. 18평 유효 벽면(~15m)에
    # photo_wall(1.9m)+partition(2m)+counter(1.5m)+consultation×2(1.4m) 이미 ~7m 점유 +
    # clearance. shelf 2~3개 추가는 벽 slot 초과 → shelf_wall drop 변동 원인.
    # 18평 LUMIA OLD 실측도 shelf×1 성공한 수치.
    "shelf": 1,
    "partition": 1,      # I + L — 18평 소형 공간 분할 1개 충분
    # [2026-04-22 S-8f — 제미나이 Q5] counter single-type family cap.
    # 18평 counter 2개는 기하학적 허수 (separate 1200 + clearance 900/600).
    "counter": 1,
}

# prefix fallback 매핑 — OBJECT_STANDARDS 미등록 기물 커버 (e.g. LUMIA 의 consultation_table)
_FAMILY_PREFIX_FALLBACK: tuple[tuple[str, str], ...] = (
    ("consultation_", "consultation"),
    ("display_", "display"),
    ("shelf_", "shelf"),
    ("photo_", "photo"),
    ("partition_", "partition"),
)


def _get_family(obj_type: str) -> str:
    """obj_type 의 family 조회. OBJECT_STANDARDS 우선, 미등록 시 prefix fallback.

    Returns:
        family 문자열. 매칭 없으면 "" (family cap 미적용 = 단독 기물 취급)
    """
    std = OBJECT_STANDARDS.get(obj_type, {})
    family = std.get("family")
    if family:
        return family
    for prefix, fam in _FAMILY_PREFIX_FALLBACK:
        if obj_type.startswith(prefix):
            return fam
    return ""


def sort_eligible_with_brand_weight(eligible: list[dict]) -> list[dict]:
    """priority + brand 가중치 + footprint tie-break 으로 정렬.

    정렬 키: (-(priority + bonus), footprint, original_index)
      - 1차: priority + bonus DESC (높은 점수 먼저)
      - 2차: footprint ASC (작은 점유 먼저 — 예산 효율 + 결정론)
      - 3차: 입력 순서 (완전 결정론 보장)

    bonus 부여 조건:
      - obj["_from_brand"] == True 이고
      - 해당 obj_type 의 첫 등장 인스턴스인 경우만 +BRAND_BONUS

    Args:
        eligible: 정렬 전 obj 리스트. 각 obj 는 object_type/width_mm/depth_mm 필수,
                  _from_brand 선택 (없으면 False 취급)

    Returns:
        정렬된 새 리스트 (입력 mutate 안 함)
    """
    seen_brand_types: set[str] = set()

    enriched: list[tuple] = []
    for idx, o in enumerate(eligible):
        obj_type = o["object_type"]
        priority = _PRIORITY_SCORE.get(obj_type, 40)
        bonus = 0
        if o.get("_from_brand") and obj_type not in seen_brand_types:
            seen_brand_types.add(obj_type)
            bonus = BRAND_BONUS
        footprint = calculate_footprint(obj_type, o["width_mm"], o["depth_mm"])
        sort_key = (-(priority + bonus), footprint, idx)
        enriched.append((sort_key, o))

    enriched.sort(key=lambda x: x[0])
    return [o for _, o in enriched]


# ─────────────────────────────────────────────────────────────────────
# 통합 allocator — 2026-04-22 S-8d 제미나이 자문 반영
# ─────────────────────────────────────────────────────────────────────
# 단일 greedy 루프 — calculate_local_cap() 기반 수학 공식 + family_cap 적용.
# 제미나이 자문 요지:
#   - 단일 greedy 루프 — 두 번 자르면 예산 overshoot + 이중 필터링 모순.
#   - per-obj rejection reason 추적 (Budget_Exceeded / Cap_Exceeded / Family_Exceeded) — 디버깅 용.

def _allocate_eligible(
    eligible: list[dict],
    usable_area_mm2: float,
    density_ratio: float | None = None,
) -> tuple[list[dict], dict]:
    """IQI + cap 통합 단일 greedy allocator.

    파이프라인:
      1. effective_budget = usable_area × density_ratio
      2. sort_eligible_with_brand_weight() 로 정렬 (priority + brand bonus + footprint tie-break)
      3. greedy 루프:
         - local cap 체크 (calculate_local_cap) → 초과 시 Cap_Exceeded
         - 전체 예산 체크 → 초과 시 Budget_Exceeded
         - 통과 시 accepted 추가, 예산 차감, type_count 증가

    Args:
        eligible: 정렬 전 obj 리스트. object_type/width_mm/depth_mm 필수, _from_brand 선택
        usable_area_mm2: 가용 바닥 면적 (mm²)
        density_ratio: 밀도 상한 비율 (기본 0.25)

    Returns:
        (accepted, allocation_log)
          accepted: 통과한 obj 리스트 (입력 순서 mutate 안 함)
          allocation_log:
            - budget_summary: total_effective_budget / used_budget / utilization_rate
            - type_allocation: {obj_type: {requested, allocated}}
            - rejection_details: [{type, priority_score, reason, ...}] per-obj
    """
    if density_ratio is None:
        density_ratio = _get_density_ratio(usable_area_mm2)
    effective_budget = usable_area_mm2 * density_ratio
    sorted_pool = sort_eligible_with_brand_weight(eligible)

    accepted: list[dict] = []
    rejections: list[dict] = []
    used_budget: float = 0.0
    type_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    local_cap_cache: dict[str, int] = {}

    # 1-2 (#520 후속): brand 매뉴얼 명시 횟수만큼 cap 동적 raise (local_cap + family_cap 둘 다).
    # 기존 cap 들은 18평 기하학적 허수 차단용 (counter family=1, calculate_local_cap=1 등)
    # 이지만 매뉴얼이 별도 manual_label 로 2개 명시 (예: POS 카운터 + 증정품 카운터) 한 경우
    # cap=1 이 매뉴얼 의도 무시하고 1개로 자르는 회귀 발생. brand 명시 횟수와 default cap 의
    # max 로 effective cap 결정 → 매뉴얼 의도 보존 + default 안전망 유지.
    # placement 단계에서 진짜 공간 부족이면 자연 drop (failed_objects). cap 단계 차단 X.
    brand_count_by_type: dict[str, int] = {}
    brand_count_by_family: dict[str, int] = {}
    for o in eligible:
        if not o.get("_from_brand"):
            continue
        ot = o["object_type"]
        brand_count_by_type[ot] = brand_count_by_type.get(ot, 0) + 1
        f = _get_family(ot)
        if f:
            brand_count_by_family[f] = brand_count_by_family.get(f, 0) + 1

    # VMD 실무의 "25% 밀도 법칙" 은 **순수 기물 바닥 면적(net)** 기준이며,
    # 나머지 75% 공간 자체가 보행 동선 / 감압존 / 교행 공간.
    # budget 체크 = net_footprint (w × d), local cap 체크 = gross_footprint (버퍼 포함),
    # family cap 체크 = FAMILY_CAPS_SMALL (같은 기능 기물 합산, 2026-04-22 S-8c-2).
    for obj in sorted_pool:
        obj_type = obj["object_type"]
        width_mm = obj["width_mm"]
        depth_mm = obj["depth_mm"]
        net_footprint = width_mm * depth_mm
        priority_score = _PRIORITY_SCORE.get(obj_type, 40)
        family = _get_family(obj_type)

        # 1. local cap 체크 (gross footprint 기준)
        # 1-2 (#520 후속): brand 매뉴얼 명시 횟수만큼 effective local cap raise (max 처리).
        if obj_type not in local_cap_cache:
            local_cap_cache[obj_type] = calculate_local_cap(
                obj_type, width_mm, depth_mm, effective_budget
            )
        default_local_cap = local_cap_cache[obj_type]
        brand_in_type = brand_count_by_type.get(obj_type, 0)
        effective_local_cap = max(default_local_cap, brand_in_type)
        current_count = type_counts.get(obj_type, 0)
        if current_count >= effective_local_cap:
            rejections.append({
                "type": obj_type,
                "priority_score": priority_score,
                "reason": "Cap_Exceeded",
                "local_cap": effective_local_cap,
                "default_local_cap": default_local_cap,
                "brand_in_type": brand_in_type,
            })
            continue

        # 2. family cap 체크 (같은 기능 기물 합산 한도)
        # 1-2 (#520 후속): brand 매뉴얼 명시 횟수만큼 effective cap raise (max 처리).
        # 매뉴얼 명시 의도 보존 — counter 2개 (POS + 증정품) 명시 시 cap 1 → 2 동적 raise.
        if family and family in FAMILY_CAPS_SMALL:
            default_cap = FAMILY_CAPS_SMALL[family]
            brand_in_family = brand_count_by_family.get(family, 0)
            effective_family_cap = max(default_cap, brand_in_family)
            current_family_count = family_counts.get(family, 0)
            if current_family_count >= effective_family_cap:
                rejections.append({
                    "type": obj_type,
                    "priority_score": priority_score,
                    "reason": "Family_Exceeded",
                    "family": family,
                    "family_cap": effective_family_cap,
                    "default_family_cap": default_cap,
                    "brand_in_family": brand_in_family,
                })
                continue

        # 3. 전체 예산 체크 (net footprint 기준)
        if used_budget + net_footprint > effective_budget:
            rejections.append({
                "type": obj_type,
                "priority_score": priority_score,
                "reason": "Budget_Exceeded",
                "net_footprint": net_footprint,
                "remaining_budget": effective_budget - used_budget,
            })
            continue

        # 4. 통과
        accepted.append(obj)
        used_budget += net_footprint
        type_counts[obj_type] = current_count + 1
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1

    # type_allocation: 요청(입력 기준) vs 할당 비교
    requested_counts: dict[str, int] = {}
    for obj in eligible:
        t = obj["object_type"]
        requested_counts[t] = requested_counts.get(t, 0) + 1
    type_allocation = {
        t: {"requested": req, "allocated": type_counts.get(t, 0)}
        for t, req in requested_counts.items()
    }

    allocation_log = {
        "budget_summary": {
            "total_effective_budget": effective_budget,
            "used_budget": used_budget,
            "utilization_rate": (used_budget / effective_budget) if effective_budget > 0 else 0.0,
        },
        "type_allocation": type_allocation,
        "rejection_details": rejections,
    }

    return accepted, allocation_log




def run(state: SmallState) -> SmallState:
    """공간 제약 + 브랜드 금지 소재 필터링 + IQI 밀도 추론."""
    brand_data = state.get("brand_data") or {}
    placement_rules = brand_data.get("placement_rules") or []
    usable_poly = state.get("usable_poly")

    # Step 1: 메뉴얼 오브젝트 (필수) + 기본 오브젝트 (보충) 합치기
    density_ratio = state.get("density_ratio") or MAX_DENSITY_RATIO
    brand_category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(brand_category, dict):
        brand_category = brand_category.get("value", "기타")
    logger.info(f"[object_selection] brand_category='{brand_category}'")
    # 2026-05-01 SSOT trace: object_selection 진입 시점 카테고리 흐름 dump
    from app.categories import dump_category_trace
    dump_category_trace(
        stage="object_selection.entered",
        raw_brand_category=brand_category,
        manual_placement_rules_count=len(placement_rules),
        manual_rule_types=[r.get("object_type") for r in placement_rules if isinstance(r, dict)],
    )
    # 2026-05-01 (#377 J): brand 매뉴얼 유무에 따라 supplement 정책 분기.
    # - brand 있음: cat.essential_supplement | cat.extras (보수적 보충)
    # - brand 없음: MAX_COUNT_GENERIC | cat.extras (기존 generic 전체, fallback path)
    default_rules = _default_placement_rules(
        usable_poly,
        brand_category=brand_category,
        has_brand_manual=bool(placement_rules),
    )

    # partition_intent에 따라 가벽 추가 (concept_gen 연결)
    # 단, MAX_COUNT_BY_CATEGORY에 이미 partition_wall_I가 있으면 중복 추가 안 함
    design_concept = state.get("design_concept") or {}
    partition_intent = design_concept.get("partition_intent", "미사용")
    existing_partition = any(r["object_type"] == "partition_wall_I" for r in default_rules)
    if partition_intent != "미사용" and not existing_partition:
        # get_vmd_boundaries는 top-level import 사용 (L11)
        # I형 기본 추가
        bounds_i = get_vmd_boundaries(brand_category).get("partition_wall_I")
        if bounds_i:
            default_rules.append({
                "object_type": "partition_wall_I",
                "name": "가벽(일자형)",
                "width_mm": bounds_i["width_mm"]["std"],
                "depth_mm": bounds_i["depth_mm"]["std"],
                "height_mm": bounds_i["height_mm"]["std"],
                "max_count": 1,
            })
            logger.info(f"[object_selection] partition_intent='{partition_intent}' → partition_wall_I 추가")
    elif partition_intent != "미사용" and existing_partition:
        logger.info(f"[object_selection] partition_intent='{partition_intent}' 있으나 default_rules에 이미 partition_wall_I 존재 — 중복 추가 안 함")

    if not placement_rules:
        logger.info("[object_selection] placement_rules 없음 — 기본 세트만 사용")
        combined_rules = default_rules
    else:
        # brand_manual의 object_type을 표준 ID로 정규화 (pos_counter/카운터/POS → counter 등)
        for r in placement_rules:
            raw = r.get("object_type", "")
            normalized = normalize_object_type(raw)
            if normalized != raw:
                logger.info(f"[object_selection] normalize: '{raw}' → '{normalized}'")
                r["object_type"] = normalized
            r["_from_brand"] = True
        manual_types = {r["object_type"] for r in placement_rules}
        supplement = [r for r in default_rules if r["object_type"] not in manual_types]
        combined_rules = list(placement_rules) + supplement
        logger.info(f"[object_selection] 메뉴얼 {len(placement_rules)}종 + 기본 보충 {len(supplement)}종 = {len(combined_rules)}종")

    # combined_rules → eligible 목록 구성
    objects = []
    for rule in combined_rules:
        if not (rule.get("width_mm") and rule.get("depth_mm")):
            continue
        count = rule.get("max_count") or rule.get("min_count") or 1
        for _ in range(count):
            obj_type = rule["object_type"]
            # front_edge: VMD_BOUNDARIES에서 가져오기 (브랜드 rule에도 있으면 우선)
            bounds = get_vmd_boundaries(brand_category).get(obj_type, {})
            fe = rule.get("front_edge") or bounds.get("front_edge", "width")
            # 1-2 (#520 후속): brand 매뉴얼에서 온 rule 은 사용자 명시 의도 라벨 (예: "POS 카운터" / "증정품 카운터")
            # 을 manual_label 로 보존. 같은 std_id 다른 의도 인스턴스가 design LLM 에서 1개로 합쳐지는 회귀 차단용.
            # default 풀에서 온 rule (_from_brand=False) 은 None — 합쳐도 무방한 보충 인스턴스.
            manual_label = (rule.get("name") or rule.get("label")) if rule.get("_from_brand") else None
            std = OBJECT_STANDARDS.get(obj_type)
            objects.append({
                "object_type": obj_type,
                "name": rule.get("name") or (std and std.get("name")) or obj_type,
                # b-3: raw 명명 보존 (mooni_figure / stella_figure 등 자유 명명 매장 표시용).
                # _normalize_placement_rules 가 이미 채워줬으나, default 풀에서 온 rule 은 누락 가능 → fallback.
                # 2026-05-10: rule.label / rule.name 둘 다 누락 시 OBJECT_STANDARDS.name (한국어) 으로 fallback.
                # 과거엔 obj_type (영문 std_id) 박혀서 프론트에 "counter" 같은 영문 노출 회귀.
                "label": rule.get("label") or rule.get("name") or (std and std.get("name")) or obj_type,
                "manual_label": manual_label,
                "width_mm": rule["width_mm"],
                "depth_mm": rule["depth_mm"],
                "height_mm": rule.get("height_mm", DEFAULT_HEIGHT_MM),
                "category": rule.get("object_type", ""),
                "material": rule.get("material", ""),
                "wall_attachment": rule.get("wall_attachment") or VMD_WALL_ATTACHMENT.get(obj_type, "free"),
                "front_edge": fe,
                "is_mandatory": bool(rule.get("_from_brand")),  # 브랜드 매뉴얼에서 온 기물은 전부 필수
                # #377 M 후속 fix: _apply_area_hard_cap sort key 가 _from_brand 기반 brand 우선 보존.
                # is_mandatory 만 있고 _from_brand 자체가 obj 에 없어서 sort 가 모두 동률 처리되던 버그.
                "_from_brand": bool(rule.get("_from_brand")),
            })

    if not objects:
        return {"eligible_objects": []}

    # Step 2: 공간 제약 필터
    brand = brand_data.get("brand", {})
    ceiling_h_field = brand.get("ceiling_height_mm", {})
    ceiling_h_brand = ceiling_h_field.get("value") if isinstance(ceiling_h_field, dict) else None
    # 브랜드 매뉴얼에 층고 없으면 도면 단면도 감지값 사용, 둘 다 없으면 3000mm 기본값
    ceiling_h = ceiling_h_brand or state.get("ceiling_height_mm") or 3000

    eligible = [
        obj for obj in objects
        if (obj.get("height_mm") or DEFAULT_HEIGHT_MM) <= ceiling_h
    ]

    # Step 3: 브랜드 금지 소재 필터
    prohibited = brand.get("prohibited_material", {})
    prohibited_val = prohibited.get("value") if isinstance(prohibited, dict) else None

    if prohibited_val:
        # 문자열 또는 리스트 모두 처리
        if isinstance(prohibited_val, list):
            prohibited_list = [v.lower() for v in prohibited_val if isinstance(v, str)]
        elif isinstance(prohibited_val, str):
            prohibited_list = [prohibited_val.lower()]
        else:
            prohibited_list = []

        if prohibited_list:
            before = len(eligible)
            eligible = [
                obj for obj in eligible
                if not any(p in obj.get("material", "").lower() for p in prohibited_list)
            ]
            logger.info(f"[object_selection] 금지 소재 {prohibited_list}: {before} → {len(eligible)}")

    # Step 4: 통합 allocator — IQI + cap 단일 greedy 루프 (2026-04-22 S-8d)
    # 제미나이 자문 반영: 이중 필터(IQI→cap) 통합. net_footprint = budget 체크, gross = local cap 체크.
    # density_ratio 는 면적대별 동적 (S-8g-1). 사용자 state override 있으면 그 값 우선.
    usable_area = usable_poly.area if usable_poly else 100_000_000
    density_ratio = state.get("density_ratio")  # None 이면 _allocate_eligible 내부에서 tier 자동 조회
    eligible, allocation_log = _allocate_eligible(eligible, usable_area, density_ratio)

    # Step 5: resolved_intents 수량 보정 — allocator 이후 적용해 사용자 요청 수량 보장
    resolved_intents = state.get("resolved_intents") or []
    if resolved_intents:
        eligible = _merge_intent_requirements(eligible, resolved_intents, brand_category=brand_category)

    # 2026-05-01 (#377 M): 면적별 hard cap 적용 — IQI cap 외에 절대 max 강제.
    # anti-pattern reviewer (#474) 망할 때 backstop. brand 항목 우선 보존.
    eligible, hard_cap_info = _apply_area_hard_cap(eligible, usable_area)

    logger.info(f"[object_selection] {len(eligible)} eligible: "
                f"{[o['object_type'] for o in eligible]}")
    logger.info(
        f"[object_selection] budget utilization: "
        f"{allocation_log['budget_summary']['utilization_rate']:.1%}, "
        f"rejections: {len(allocation_log['rejection_details'])}"
    )

    # ── 디버그 덤프 ──
    import json as _json, os as _os
    from datetime import datetime as _dt
    _dd = _os.path.join(_os.path.dirname(__file__), "..", "..", "debug_logs", _dt.now().strftime("%Y-%m-%d"))
    _os.makedirs(_dd, exist_ok=True)
    with open(_os.path.join(_dd, "object_selection_debug.json"), "w", encoding="utf-8") as _f:
        _json.dump({
            "brand_category": brand_category,
            "brand_keys": list(brand_data.get("brand", {}).keys()),
            "placement_rules_count": len(placement_rules),
            "allocation_log": allocation_log,
            "eligible_final": [
                {
                    "type": o["object_type"],
                    "w": o.get("width_mm"),
                    "d": o.get("depth_mm"),
                    "from_brand": bool(o.get("_from_brand")),
                }
                for o in eligible
            ],
            "total_eligible_count": len(eligible),
        }, _f, ensure_ascii=False, indent=2)

    # 2026-05-01 SSOT trace: eligible 풀 결정 후 카테고리 흐름 dump
    # #377 J + M 추적 정보 추가 — essential_supplement 사용 / hard cap 적용 / drop 객체
    from app.categories import get_category as _get_cat
    _cat_for_trace = _get_cat(brand_category)
    _has_brand = bool(placement_rules)
    _essential_used = (
        sorted(_cat_for_trace.essential_supplement.keys())
        if _has_brand and _cat_for_trace.essential_supplement
        else []
    )
    dump_category_trace(
        stage="object_selection.eligible_finalized",
        raw_brand_category=brand_category,
        manual_placement_rules_count=len(placement_rules),
        eligible_count=len(eligible),
        eligible_types=[o["object_type"] for o in eligible],
        eligible_from_brand_count=sum(1 for o in eligible if o.get("_from_brand")),
        # #377 J 추적
        supplement_mode="essential_only" if _has_brand else "generic_fallback",
        essential_supplement_used=_essential_used,
        # #377 M 추적
        hard_cap_threshold=hard_cap_info.get("cap"),
        hard_cap_applied=hard_cap_info.get("applied"),
        hard_cap_dropped_count=hard_cap_info.get("dropped_count", 0),
        hard_cap_dropped_types=hard_cap_info.get("dropped_types", []),
    )

    return {"eligible_objects": eligible, "allocation_log": allocation_log}


def _merge_intent_requirements(eligible: list, resolved_intents: list, brand_category: str = "기타") -> list:
    """resolved_intents의 요청 수량이 eligible에 부족하면 추가 보충.

    IQI 이후 실행되므로 사용자가 명시한 수량은 밀도 제약에도 보장된다.
    quantity=-1(fill)은 design LLM에 맡기므로 건너뜀.
    """
    from collections import Counter
    # VMD_WALL_ATTACHMENT, get_vmd_boundaries は top-level import (L11)

    boundaries = get_vmd_boundaries(brand_category)
    current_counts = Counter(o["object_type"] for o in eligible)

    for intent in resolved_intents:
        obj_type = intent.get("object_type") or ""
        quantity = intent.get("quantity", 1)
        if quantity == -1 or not obj_type:
            continue
        shortage = quantity - current_counts.get(obj_type, 0)
        if shortage <= 0:
            continue
        template = next((o for o in eligible if o["object_type"] == obj_type), None)
        if not template:
            bounds = boundaries.get(obj_type)
            if not bounds:
                logger.warning(f"[object_selection] intent 보충 실패: {obj_type} — VMD_BOUNDARIES 없음")
                continue
            std = OBJECT_STANDARDS.get(obj_type)
            template = {
                "object_type": obj_type,
                "name": std["name"] if std else obj_type,
                # 2026-05-10: brand 매뉴얼이 LLM 비결정성으로 obj_type 누락 시 default 풀로 충전됨.
                # 과거엔 label = obj_type (영문) 박아서 프론트에 "counter" 같은 영문 노출.
                # OBJECT_STANDARDS.name (한국어) 으로 fallback — 다른 팀원/배포 환경에서 라벨 영문 회귀 차단.
                "label": std["name"] if std else obj_type,
                "manual_label": None,  # 1-2: intent 보충은 brand 매뉴얼 의도 X
                "width_mm": bounds["width_mm"]["std"],
                "depth_mm": bounds["depth_mm"]["std"],
                "height_mm": bounds["height_mm"]["std"],
                "category": obj_type,
                "material": "",
                "wall_attachment": VMD_WALL_ATTACHMENT.get(obj_type, "free"),
                "_from_brand": False,  # default 풀에서 보충 — non-brand. hard cap sort 시 뒤로 밀림
            }
        for _ in range(shortage):
            # 1-2 (#520 후속): brand obj 를 template 으로 clone 시 manual_label / _from_brand 가 끌려가지
            # 않도록 명시 reset. intent 보충 인스턴스는 사용자가 quantity 만 명시한 일반 보충.
            clone = dict(template)
            clone["manual_label"] = None
            clone["_from_brand"] = False
            eligible.append(clone)
        logger.info(f"[object_selection] intent 수량 보충: {obj_type} +{shortage}개 (요청={quantity}, 기존={current_counts.get(obj_type, 0)})")

    return eligible




# 2026-05-01 (#377 M) 면적별 hard cap — VMD 실무 기준 + 5-1 두 AI (GPT/Gemini) 평가 일치.
# IQI cap (density_ratio 기반) 외에 절대 max 객체 수 강제. anti-pattern reviewer (#474)
# 망할 때 backstop 안전망 — reviewer 의존 X, 정적 cap 으로 동작 보장.
#
# 임계값 근거:
#   - 18평 (60㎡): 7개. 5-1 GPT/Gemini 평가 + reports/AD/화이트박스_실무_기준_정리.md
#   - 30평 (99㎡): 10개. 비례 추정. 중형 실측 진입 시 튜닝 (M-7).
#   - 50평 (165㎡): 14개. 소·중형 분기 임계 (SMALL_AREA_THRESHOLD = 165M_mm²).
#   - 165㎡ 초과 = 대형 (nodes_large). 본 cap 미적용.
AREA_HARD_CAP_MM2: list[tuple[int, int]] = [
    (60_000_000, 7),
    (99_000_000, 10),
    (165_000_000, 14),
]


def _resolve_hard_cap(usable_area_mm2: float) -> int:
    """면적 → hard cap 변환. 가장 작은 tier 부터 매칭.

    Graceful fallback:
      - 면적 ≤ 0 → 가장 작은 tier cap (7) + logger.error
      - 165㎡ 초과 (정상은 대형) → 가장 큰 tier cap (14) + logger.warning
      - AREA_HARD_CAP_MM2 빈 list (정의 누락) → 999 (사실상 cap 없음) + logger.error
    """
    if not AREA_HARD_CAP_MM2:
        logger.error("[hard_cap] AREA_HARD_CAP_MM2 빈 list — cap 미적용 (999)")
        return 999

    if usable_area_mm2 <= 0:
        smallest = AREA_HARD_CAP_MM2[0][1]
        logger.error(
            f"[hard_cap] 비정상 면적 {usable_area_mm2} → 가장 작은 tier cap {smallest} 적용 (fallback)"
        )
        return smallest

    for area_threshold, cap in AREA_HARD_CAP_MM2:
        if usable_area_mm2 <= area_threshold:
            return cap

    largest = AREA_HARD_CAP_MM2[-1][1]
    logger.warning(
        f"[hard_cap] 면적 {usable_area_mm2 / 1e6:.0f}㎡ 가 hard cap tier 초과 — "
        f"최대 cap {largest} 적용 (fallback). 165㎡ 초과는 대형 (nodes_large) 영역"
    )
    return largest


def _apply_area_hard_cap(eligible: list, usable_area_mm2: float) -> tuple[list, dict]:
    """면적별 hard cap 적용. brand 매뉴얼 항목 우선순위 보존.

    정렬 키 (오름차순 = 보존):
      1. _from_brand=True (brand 매뉴얼) 우선 = 먼저 보존
      2. _PRIORITY_SCORE 내림차순 (높은 score 먼저)
      3. footprint 오름차순 (작은 것 먼저, tie-break)

    1-2 (#523/#524 후속): brand 매뉴얼 명시 횟수와 default cap 의 max 처리. 매뉴얼이 명시한
    의도 (예: 18평에 photo + counter×2 + partition + shelf×2 + consultation×2 + test_bar = 9개)
    가 default cap 7 에 의해 잘리던 회귀 차단. local_cap / family_cap 에서 같은 패턴 적용한 것과
    일관. placement 단계가 진짜 공간 부족이면 자체 검증으로 drop (failed_objects).

    Returns:
        (capped_list, info_dict) — info 에 cap / dropped / before_count + brand_count
    """
    default_cap = _resolve_hard_cap(usable_area_mm2)
    brand_count = sum(1 for o in eligible if o.get("_from_brand"))
    cap = max(default_cap, brand_count)
    info = {
        "cap": cap,
        "default_cap": default_cap,
        "brand_count": brand_count,
        "before_count": len(eligible),
        "applied": False,
        "dropped_count": 0,
        "dropped_types": [],
    }

    if len(eligible) <= cap:
        return eligible, info

    # cap 초과 — 정렬 후 cap 까지만 보존
    sorted_eligible = sorted(
        eligible,
        key=lambda o: (
            not o.get("_from_brand", False),       # brand=True 가 먼저 (False=0, True=1 → not 으로 reverse)
            -_PRIORITY_SCORE.get(o["object_type"], 40),  # priority 높을수록 먼저
            calculate_footprint(
                o["object_type"], o.get("width_mm", 0), o.get("depth_mm", 0)
            ),  # footprint 작은 것 먼저
        ),
    )
    capped = sorted_eligible[:cap]
    dropped = sorted_eligible[cap:]

    info["applied"] = True
    info["dropped_count"] = len(dropped)
    info["dropped_types"] = [o["object_type"] for o in dropped]

    if cap > default_cap:
        logger.info(
            f"[hard_cap] brand 매뉴얼 명시 {brand_count}개 → cap raise: default={default_cap} → effective={cap}"
        )
    logger.warning(
        f"[hard_cap] 면적 cap 적용 — area={usable_area_mm2 / 1e6:.0f}㎡, "
        f"cap={cap}, eligible {len(eligible)} → {cap} ({len(dropped)}개 drop). "
        f"drop: {info['dropped_types']}"
    )
    return capped, info


def _default_placement_rules(usable_poly, brand_category: str = "기타", has_brand_manual: bool = False) -> list:
    """기본 오브젝트 세트 — brand 매뉴얼 보충용.

    카테고리별 max_count + 면적 스케일링.
    규격은 get_vmd_boundaries(category)에서 조회.

    [2026-04-23] MAX_COUNT_BY_CATEGORY (legacy, character_ip fallback) →
    MAX_COUNT_GENERIC + CATEGORY_EXTRAS dict union 으로 전환.
    미등록 카테고리도 generic 만 받음 → character_bbox 누출 자연 차단.

    [2026-05-01 SSOT] CATEGORY_EXTRAS lookup 을 app.categories.get_category(key).extras
    로 전환.

    [2026-05-01 (#377 J)] has_brand_manual 파라미터 신규.
      - True: brand 매뉴얼이 placement_rules 제공함 → 보수적 supplement
        count_table = cat.essential_supplement | cat.extras
        (매뉴얼 우선 + 카테고리별 essential 1-3개만 보충)
      - False: brand 매뉴얼 부재 (fallback path) → 기존 generic 전체 사용
        count_table = MAX_COUNT_GENERIC | cat.extras
        (기존 동작 보존 — brand 부재 시 안전망)

    Why: 5-1 13:36 라이브 dump — 18평 placed=11 비대화. brand + generic 합집합이
    14-15개 → IQI cap 후 11. essential 만 보충하면 brand + 1-3 = 6-9 → cap 7-8 목표.
    """
    from app.vmd_constants import MAX_COUNT_GENERIC, scale_count as _scale_count
    from app.categories import get_category, DEFAULT_CATEGORY
    # get_vmd_boundaries は top-level import (L11)

    area_sqm = usable_poly.area / 1_000_000 if usable_poly else 50
    cat = get_category(brand_category)
    boundaries = get_vmd_boundaries(brand_category)

    # 2026-05-01 (#377 J): has_brand_manual 분기
    if has_brand_manual:
        # brand 매뉴얼 우선 — essential supplement 만 보충
        essential = cat.essential_supplement
        if not essential:
            # graceful fallback: 미등록 카테고리 (테크/아트/엔터) 또는 정의 누락
            # → DEFAULT_CATEGORY ("기타") 의 essential 사용
            essential = DEFAULT_CATEGORY.essential_supplement
            logger.warning(
                f"[object_selection] {brand_category} essential_supplement 빈 set → "
                f"DEFAULT_CATEGORY '기타' essential 사용 (fallback): {essential}"
            )
        # dict union: extras override 우선 (뷰티의 display_table 2 등)
        count_table = essential | cat.extras
        logger.info(
            f"[object_selection] brand 매뉴얼 우선 — essential supplement {len(essential)}개 + "
            f"extras {len(cat.extras)}개 = count_table {len(count_table)}개 (#377 J)"
        )
    else:
        # brand 매뉴얼 부재 — generic 전체 사용 (기존 동작)
        count_table = MAX_COUNT_GENERIC | cat.extras
        logger.info(
            f"[object_selection] brand 매뉴얼 부재 (fallback) — generic 전체 + extras = "
            f"{len(count_table)}개"
        )

    # 카테고리별 max_count에 면적 스케일링 적용
    counts = {}
    for obj_type, base_count in count_table.items():
        counts[obj_type] = _scale_count(base_count, area_sqm)

    total = sum(counts.values())
    logger.info(f"[object_selection] 기본 세트 ({brand_category}): {area_sqm:.0f}㎡, {total}개 {counts}")

    rules = []
    for std_id, count in counts.items():
        std = OBJECT_STANDARDS.get(std_id)
        bounds = boundaries.get(std_id)
        if not bounds:
            continue
        rules.append({
            "object_type": std_id,
            "name": std["name"] if std else std_id,
            "width_mm": bounds["width_mm"]["std"],
            "depth_mm": bounds["depth_mm"]["std"],
            "height_mm": bounds["height_mm"]["std"],
            "max_count": count,
        })

    return rules
