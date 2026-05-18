"""
Intent 처리 서비스 — resolved_intents 의 action 조합을 전략으로 변환하고 적용.

전략:
  FULL_RELAYOUT       : locked 전체 초기화 + global_direction_hint
  PARTIAL_REORIENT    : 해당 타입만 locked에서 꺼내 새 direction_hint 로 add
  RESIZE_ONLY         : 치수 오버라이드 + locked 에서 꺼내 add
  RESIZE_AND_ADD      : RESIZE + 기존 add
  ADD_ONLY            : 기존 add
  NOOP                : 아무 것도 안 함
"""
import logging

logger = logging.getLogger(__name__)


def resolve_strategy(intents: list) -> str:
    """resolved_intents의 action 조합을 보고 파이프라인 전략 결정."""
    if not intents:
        return "NOOP"

    action_types = {i.get("action", "add") for i in intents}

    if "reorient" in action_types:
        reorient = [i for i in intents if i.get("action") == "reorient"]
        if any(i.get("scope") == "all" or i.get("object_type") == "*" for i in reorient):
            return "FULL_RELAYOUT"
        return "PARTIAL_REORIENT"

    if "resize" in action_types:
        if "add" in action_types:
            return "RESIZE_AND_ADD"
        return "RESIZE_ONLY"

    if "add" in action_types:
        return "ADD_ONLY"

    return "NOOP"


def apply_resize_intents(state: dict) -> None:
    """resize 인텐트 처리: 치수 오버라이드 계산 + locked에서 해당 타입 꺼내 add 인텐트로 전환."""
    intents = state.get("resolved_intents") or []
    resize_intents = [i for i in intents if i.get("action") == "resize"]
    if not resize_intents:
        return

    from app.vmd_constants import get_vmd_boundaries
    brand_data = state.get("brand_data") or {}
    brand_cat = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(brand_cat, dict):
        brand_cat = brand_cat.get("value", "기타")
    boundaries = get_vmd_boundaries(brand_cat)

    dim_overrides = dict(state.get("dimension_overrides") or {})
    locked = list(state.get("locked_objects") or [])
    new_add_intents: list[dict] = []

    for ri in resize_intents:
        obj_type = ri.get("object_type")
        modifier = ri.get("size_modifier") or "larger"
        qty = ri.get("quantity", -1)

        if obj_type not in boundaries:
            logger.warning(f"[resize] {obj_type}: VMD_BOUNDARIES에 없음 — 건너뜀")
            continue

        spec = boundaries[obj_type]
        w_spec = spec["width_mm"]
        d_spec = spec["depth_mm"]

        h_spec = spec.get("height_mm", {})
        cur = dim_overrides.get(obj_type, {})
        new_w = cur.get("width_mm", w_spec["std"])
        new_d = cur.get("depth_mm", d_spec["std"])
        new_h = cur.get("height_mm", h_spec.get("std") if h_spec else None)

        if modifier == "larger":
            new_w = int(w_spec["std"] + (w_spec["max"] - w_spec["std"]) * 0.7)
            new_d = int(d_spec["std"] + (d_spec["max"] - d_spec["std"]) * 0.7)
        elif modifier == "smaller":
            new_w = int(w_spec["std"] - (w_spec["std"] - w_spec["min"]) * 0.7)
            new_d = int(d_spec["std"] - (d_spec["std"] - d_spec["min"]) * 0.7)
        elif modifier == "wider":
            new_w = int(w_spec["std"] + (w_spec["max"] - w_spec["std"]) * 0.7)
        elif modifier == "narrower":
            new_w = int(w_spec["std"] - (w_spec["std"] - w_spec["min"]) * 0.7)
        elif modifier == "taller" and h_spec:
            new_h = int(h_spec["std"] + (h_spec["max"] - h_spec["std"]) * 0.7)
        elif modifier == "shorter" and h_spec:
            new_h = int(h_spec["std"] - (h_spec["std"] - h_spec["min"]) * 0.7)
        elif modifier == "max":
            new_w, new_d = w_spec["max"], d_spec["max"]
            if h_spec:
                new_h = h_spec["max"]
        elif modifier == "min":
            new_w, new_d = w_spec["min"], d_spec["min"]
            if h_spec:
                new_h = h_spec["min"]
        else:
            continue

        entry: dict = {"width_mm": new_w, "depth_mm": new_d}
        if new_h is not None:
            entry["height_mm"] = new_h
        dim_overrides[obj_type] = entry
        logger.info(
            f"[resize] {obj_type}: 새 치수 w={new_w} d={new_d}"
            + (f" h={new_h}" if new_h else "")
            + f"mm (modifier={modifier})"
        )

        # locked에서 해당 타입 꺼내 add 인텐트로 전환
        new_locked = []
        extracted = 0
        for lo in locked:
            if lo.get("object_type") == obj_type and (qty == -1 or extracted < qty):
                new_add_intents.append({
                    "action": "add",
                    "object_type": obj_type,
                    "quantity": 1,
                    "zone_hint": lo.get("zone_label") or "mid_zone",
                    "direction_hint": lo.get("direction") or None,
                    "original_text": ri.get("original_text", ""),
                    "is_removal": False,
                    "size_modifier": None,
                    "scope": "type",
                })
                extracted += 1
            else:
                new_locked.append(lo)
        locked = new_locked
        logger.info(f"[resize] {obj_type}: locked에서 {extracted}개 꺼냄 → add 인텐트 생성")

    state["locked_objects"] = locked
    state["dimension_overrides"] = dim_overrides
    remaining = [i for i in intents if i.get("action") != "resize"]
    state["resolved_intents"] = remaining + new_add_intents


def apply_reorient_intents(state: dict, strategy: str) -> None:
    """reorient 인텐트 처리.

    FULL_RELAYOUT    : locked 전체 초기화 + global_direction_hint 설정 → design 전체 재실행
    PARTIAL_REORIENT : 해당 타입만 locked에서 꺼내 새 direction_hint로 add 인텐트 생성
    """
    intents = state.get("resolved_intents") or []
    reorient_intents = [i for i in intents if i.get("action") == "reorient"]
    if not reorient_intents:
        return

    if strategy == "FULL_RELAYOUT":
        global_dir = reorient_intents[0].get("direction_hint") or "center"
        state["global_direction_hint"] = global_dir
        state["locked_objects"] = []
        logger.info(f"[reorient:full] global_direction_hint={global_dir}, locked_objects 초기화")
    else:
        locked = list(state.get("locked_objects") or [])
        new_add_intents: list[dict] = []

        for ri in reorient_intents:
            obj_type = ri.get("object_type")
            new_dir = ri.get("direction_hint") or "center"
            qty = ri.get("quantity", -1)

            new_locked = []
            extracted = 0
            for lo in locked:
                if lo.get("object_type") == obj_type and (qty == -1 or extracted < qty):
                    new_add_intents.append({
                        "action": "add",
                        "object_type": obj_type,
                        "quantity": 1,
                        "zone_hint": ri.get("zone_hint") or lo.get("zone_label") or "mid_zone",
                        "direction_hint": new_dir,
                        "original_text": ri.get("original_text", ""),
                        "is_removal": False,
                        "size_modifier": None,
                        "scope": "type",
                    })
                    extracted += 1
                else:
                    new_locked.append(lo)
            locked = new_locked
            logger.info(f"[reorient:partial] {obj_type}: {extracted}개 꺼냄 → dir={new_dir} add 인텐트 생성")

        state["locked_objects"] = locked
        state["resolved_intents"] = [i for i in intents if i.get("action") != "reorient"] + new_add_intents


def filter_eligible_for_addition(state: dict) -> None:
    """추가 모드: eligible_objects를 resolved_intents에 명시된 타입만으로 필터링.

    design.py가 전체 재배치하지 않고 요청된 오브젝트만 처리하도록 제한.
    """
    resolved = state.get("resolved_intents") or []
    if not resolved:
        return

    requested_types = {ri.get("object_type") for ri in resolved if ri.get("object_type")}
    if not requested_types:
        return

    eligible = state.get("eligible_objects") or []
    filtered = [o for o in eligible if o.get("object_type") in requested_types]

    if len(filtered) != len(eligible):
        removed = {o["object_type"] for o in eligible if o.get("object_type") not in requested_types}
        logger.info(f"[addition_filter] eligible_objects 필터링: {len(eligible)} → {len(filtered)} (제외: {removed})")

    state["eligible_objects"] = filtered


def apply_removal_intents(state: dict) -> None:
    """제거 인텐트(is_removal=True)를 처리: locked_objects에서 해당 타입을 수량만큼 제거.

    처리 후 resolved_intents에서 제거 인텐트를 제외해 배치 파이프라인이 무시하도록 한다.
    """
    intents = state.get("resolved_intents") or []
    removal_intents = [i for i in intents if i.get("is_removal")]
    if not removal_intents:
        return

    locked = list(state.get("locked_objects") or [])
    for ri in removal_intents:
        obj_type = ri.get("object_type")
        qty = ri.get("quantity", 1)
        if qty == -1:
            before = len(locked)
            locked = [lo for lo in locked if lo.get("object_type") != obj_type]
            logger.info(f"[removal] {obj_type} 전체 제거: {before} → {len(locked)}")
        else:
            removed = 0
            new_locked = []
            for lo in locked:
                if lo.get("object_type") == obj_type and removed < qty:
                    removed += 1
                else:
                    new_locked.append(lo)
            logger.info(f"[removal] {obj_type} {removed}개 제거 (요청={qty})")
            locked = new_locked

    state["locked_objects"] = locked
    # 제거 인텐트는 배치 파이프라인 대상에서 제외
    state["resolved_intents"] = [i for i in intents if not i.get("is_removal")]
