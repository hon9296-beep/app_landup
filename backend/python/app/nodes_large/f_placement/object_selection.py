"""
오브젝트 선별 노드.

브랜드 매뉴얼 + 기본 세트에서 오브젝트 목록 구성.
대형: priority 강제 정렬 없음, MAX_DENSITY 상한 없음.
"""
import logging

from app.state import LargeState
from app.utils import OBJECT_STANDARDS
from app.vmd_constants import VMD_WALL_ATTACHMENT

logger = logging.getLogger(__name__)

# 유효 면적 대비 최대 기물 점유율 (25%)
MAX_DENSITY_RATIO = 0.25

# 기물 우선순위 — OBJECT_STANDARDS에서 생성
_PRIORITY_SCORE: dict[str, int] = {
    std_id: std["priority"] for std_id, std in OBJECT_STANDARDS.items()
}


def run(state: LargeState) -> LargeState:
    """공간 제약 + 브랜드 금지 소재 필터링 + IQI 밀도 추론."""
    brand_data = state.get("brand_data") or {}
    placement_rules = brand_data.get("placement_rules") or []
    usable_poly = state.get("usable_poly")

    # Step 1: concept_areas 기반 or 기존 방식
    concept_areas = state.get("concept_areas") or []
    density_ratio = state.get("density_ratio") or MAX_DENSITY_RATIO

    if concept_areas:
        # concept_area 기반: 영역별 target_objects 합산 + 매뉴얼 오브젝트 병합
        combined_rules = _rules_from_concept_areas(concept_areas, placement_rules, usable_poly)
    elif not placement_rules:
        logger.info("[object_selection] placement_rules 없음 — 기본 세트만 사용")
        combined_rules = _default_placement_rules(usable_poly, density_ratio)
    else:
        manual_types = {r["object_type"] for r in placement_rules}
        default_rules = _default_placement_rules(usable_poly, density_ratio)
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
            objects.append({
                "object_type": obj_type,
                "name": rule.get("name", obj_type),
                "width_mm": rule["width_mm"],
                "depth_mm": rule["depth_mm"],
                "height_mm": rule.get("height_mm") or 1500,
                "category": rule.get("object_type", ""),
                "material": rule.get("material", ""),
                "wall_attachment": rule.get("wall_attachment") or VMD_WALL_ATTACHMENT.get(obj_type, "free"),
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
        if obj["height_mm"] <= ceiling_h
    ]

    # Step 3: 브랜드 금지 소재 필터
    prohibited = brand.get("prohibited_material", {})
    prohibited_val = prohibited.get("value") if isinstance(prohibited, dict) else None

    if prohibited_val:
        before = len(eligible)
        if isinstance(prohibited_val, list):
            eligible = [
                obj for obj in eligible
                if not any(p.lower() in obj.get("material", "").lower() for p in prohibited_val if isinstance(p, str))
            ]
        elif isinstance(prohibited_val, str):
            eligible = [
                obj for obj in eligible
                if prohibited_val.lower() not in obj.get("material", "").lower()
            ]
        logger.info(f"[object_selection] 금지 소재 '{prohibited_val}': {before} → {len(eligible)}")

    # Step 4: 대형 — IQI/density 상한 비적용. 오브젝트 전량 통과.
    area_sqm = usable_poly.area / 1_000_000 if usable_poly else 50
    logger.info(f"[object_selection] density: area={area_sqm:.0f}㎡, 대형 모드 — density 상한 비적용")

    # Step 5: resolved_intents 수량 보정 — intent_parser가 먼저 실행된 경우 요청 수량 보장
    resolved_intents = state.get("resolved_intents") or []
    if resolved_intents:
        eligible = _merge_intent_requirements(eligible, resolved_intents)

    logger.info(f"[object_selection] {len(eligible)} eligible: "
                f"{[o['object_type'] for o in eligible]}")

    # Step 6: 추가 모드 — locked + resolved_intents 시 eligible 을 요청 타입만으로 좁힘.
    # 2026-05-02 graph 랭그래프화 단계 2 — place_service.py:113-114 의 wrapper 호출 흡수.
    # state["eligible_objects"] 미리 박은 후 filter 호출 (filter 가 state 의 키를 갱신).
    state["eligible_objects"] = eligible
    if state.get("locked_objects") and state.get("resolved_intents"):
        from app.services.intent_service import filter_eligible_for_addition
        filter_eligible_for_addition(state)
        eligible = state["eligible_objects"]

    return {"eligible_objects": eligible}


def _merge_intent_requirements(eligible: list, resolved_intents: list) -> list:
    """resolved_intents의 요청 수량이 eligible에 부족하면 추가 보충.

    intent_parser가 먼저 실행된 후 object_selection이 실행될 때,
    사용자가 명시한 타입/수량이 eligible에 반드시 포함되도록 보장한다.
    quantity=-1(fill)은 수량 결정을 design LLM에 맡기므로 건너뜀.
    """
    from collections import Counter
    from app.vmd_constants import VMD_BOUNDARIES, VMD_WALL_ATTACHMENT

    current_counts = Counter(o["object_type"] for o in eligible)

    for intent in resolved_intents:
        obj_type = intent.get("object_type") or ""
        quantity = intent.get("quantity", 1)
        if quantity == -1 or not obj_type:
            continue
        shortage = quantity - current_counts.get(obj_type, 0)
        if shortage <= 0:
            continue
        # 기존 eligible에서 템플릿(치수) 조회, 없으면 VMD_BOUNDARIES에서 생성
        template = next((o for o in eligible if o["object_type"] == obj_type), None)
        if not template:
            bounds = VMD_BOUNDARIES.get(obj_type)
            if not bounds:
                logger.warning(f"[object_selection] intent 보충 실패: {obj_type} — VMD_BOUNDARIES 없음")
                continue
            std = OBJECT_STANDARDS.get(obj_type)
            template = {
                "object_type": obj_type,
                "name": std["name"] if std else obj_type,
                "width_mm": bounds["width_mm"]["std"],
                "depth_mm": bounds["depth_mm"]["std"],
                "height_mm": bounds["height_mm"]["std"],
                "category": obj_type,
                "material": "",
                "wall_attachment": VMD_WALL_ATTACHMENT.get(obj_type, "free"),
            }
        for _ in range(shortage):
            eligible.append(dict(template))
        logger.info(f"[object_selection] intent 수량 보충: {obj_type} +{shortage}개 (요청={quantity}, 기존={current_counts.get(obj_type, 0)})")

    return eligible


def _rules_from_concept_areas(concept_areas: list, placement_rules: list, usable_poly) -> list:
    """concept_area별 target_objects → 오브젝트 규칙 합산. 매뉴얼 규칙 우선 병합."""
    from app.vmd_constants import VMD_BOUNDARIES
    from collections import Counter

    # 영역별 target_objects 수집 → 타입별 수량 카운트
    type_counts: Counter = Counter()
    for area in concept_areas:
        for obj_type in area.get("target_objects", []):
            type_counts[obj_type] += 1

    # 매뉴얼 규칙 우선 적용
    manual_types = {r["object_type"] for r in placement_rules}
    rules = list(placement_rules)

    # concept_area에서 나온 타입 중 매뉴얼에 없는 것 보충
    for obj_type, count in type_counts.items():
        if obj_type in manual_types:
            continue
        bounds = VMD_BOUNDARIES.get(obj_type)
        std = OBJECT_STANDARDS.get(obj_type)
        if not bounds:
            continue
        rules.append({
            "object_type": obj_type,
            "name": std["name"] if std else obj_type,
            "width_mm": bounds["width_mm"]["std"],
            "depth_mm": bounds["depth_mm"]["std"],
            "height_mm": bounds["height_mm"]["std"],
            "max_count": count,
        })

    logger.info(f"[object_selection] concept_area 기반: {len(concept_areas)}개 영역 → {len(rules)}종 오브젝트")
    return rules


def _apply_iqi(eligible: list[dict], usable_area_mm2: float, density_ratio: float = MAX_DENSITY_RATIO) -> list[dict]:
    """IQI: 밀도 제약 기반 수량 추론.

    density_ratio는 사용자 설정 가능 (기본 0.25).
    밀도 초과 시 우선순위 낮은 오브젝트부터 수량 축소 (크기 축소 아님).
    탈락된 오브젝트는 로그에 기록.
    """
    max_footprint = usable_area_mm2 * density_ratio

    scored = sorted(
        eligible,
        key=lambda o: _PRIORITY_SCORE.get(o["object_type"], 40),
        reverse=True,
    )

    accepted = []
    dropped = []
    cumulative = 0.0

    for obj in scored:
        footprint = obj["width_mm"] * obj["depth_mm"]
        if cumulative + footprint > max_footprint:
            dropped.append(obj)
            continue
        cumulative += footprint
        accepted.append(obj)

    occupancy = (cumulative / usable_area_mm2 * 100) if usable_area_mm2 > 0 else 0

    # 탈락 피드백: 타입별 수량 변화
    if dropped:
        from collections import Counter
        orig_counts = Counter(o["object_type"] for o in eligible)
        accepted_counts = Counter(o["object_type"] for o in accepted)
        dropped_counts = Counter(o["object_type"] for o in dropped)
        for obj_type, drop_cnt in dropped_counts.items():
            logger.info(f"[IQI] 밀도 초과 수량 축소: {obj_type} {orig_counts[obj_type]}개 → "
                        f"{accepted_counts[obj_type]}개 ({drop_cnt}개 탈락, "
                        f"priority={_PRIORITY_SCORE.get(obj_type, 40)})")

    logger.info(f"[IQI] max={max_footprint / 1_000_000:.1f}m², "
                f"accepted={len(accepted)}, dropped={len(dropped)}, occupancy={occupancy:.1f}%")

    return accepted


def _compute_density_ratio(area_sqm: float) -> float:
    """면적 기반 동적 density 비율 — 로그 함수.

    density = -0.07 × ln(면적) + 0.54
    면적이 커질수록 점유 비율 감소 (동선/여백 확보).
    하한 10%, 상한 35%.
    """
    import math
    if area_sqm <= 0:
        return 0.25
    raw = -0.07 * math.log(area_sqm) + 0.54
    return max(0.10, min(0.35, raw))


def _default_placement_rules(usable_poly, density_ratio: float = MAX_DENSITY_RATIO) -> list:
    """브랜드 메뉴얼 없을 때 기본 오브젝트 세트.

    면적 기반 로그 함수로 density 비율 산출 → 목표 점유 면적 계산.
    각 타입별 비중(%)으로 면적을 배분 → footprint로 나눠 수량 역산.
    규격은 VMD_BOUNDARIES(vmd_constants)에서 std값 조회.
    """
    from app.vmd_constants import VMD_BOUNDARIES

    area_sqm = usable_poly.area / 1_000_000 if usable_poly else 50

    # 로그 함수 기반 동적 density (사용자 설정이 있으면 그걸 우선)
    auto_density = _compute_density_ratio(area_sqm)
    effective_density = density_ratio if density_ratio != MAX_DENSITY_RATIO else auto_density
    target_sqm = area_sqm * effective_density

    logger.info(f"[object_selection] density: area={area_sqm:.0f}㎡, auto={auto_density:.0%}, effective={effective_density:.0%}, target={target_sqm:.1f}㎡")

    # 타입별 면적 배분 비중 (합계 100%)
    # 고정 타입: 면적 배분과 무관하게 1개
    # 가변 타입: 목표 면적에서 비중만큼 차지
    fixed = {
        "counter": 1,
        "photo_wall": 1,  # 포토존 배경 기본 1개 (photo_island 는 variable 쪽으로 검토 예정)
        "character_bbox": 1,
    }

    variable_ratios = {
        "display_table": 0.30,   # 30%
        "shelf_wall": 0.25,      # 25%
        "shelf_3tier": 0.15,     # 15%
        "banner_stand": 0.10,    # 10%
        "partition_wall_I": 0.10,  # 10% — 일자형 가벽 (small 정합, partition_wall 단일 폐기)
        "partition_wall_L": 0.05,  # 5%  — ㄱ자형 가벽 (코너 전용, 위치 제한적이라 I 보다 적게)
    }
    # 나머지 5%는 고정 타입이 자연스럽게 차지

    # 고정 타입 면적 차감 (규격은 VMD_BOUNDARIES에서 조회)
    fixed_area = 0
    for std_id in fixed:
        bounds = VMD_BOUNDARIES.get(std_id)
        if bounds:
            fixed_area += (bounds["width_mm"]["std"] * bounds["depth_mm"]["std"]) / 1_000_000
    remaining_sqm = max(0, target_sqm - fixed_area)

    # 가변 타입 수량 역산
    counts = dict(fixed)
    for std_id, ratio in variable_ratios.items():
        bounds = VMD_BOUNDARIES.get(std_id)
        if not bounds:
            continue
        footprint_sqm = (bounds["width_mm"]["std"] * bounds["depth_mm"]["std"]) / 1_000_000
        alloc_sqm = remaining_sqm * ratio
        count = max(1, round(alloc_sqm / footprint_sqm))
        counts[std_id] = count

    # 작은 공간 보정: 30㎡ 미만이면 가벽/배너 제외
    if area_sqm < 30:
        counts.pop("partition_wall_I", None)
        counts.pop("partition_wall_L", None)
        counts.pop("banner_stand", None)

    rules = []
    for std_id, count in counts.items():
        std = OBJECT_STANDARDS.get(std_id)
        bounds = VMD_BOUNDARIES.get(std_id)
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

    total = sum(counts.values())
    logger.info(f"[object_selection] 기본 세트: {area_sqm:.0f}㎡ × {density_ratio:.0%} = 목표 {target_sqm:.1f}㎡, {total}개 ({counts})")
    return rules
