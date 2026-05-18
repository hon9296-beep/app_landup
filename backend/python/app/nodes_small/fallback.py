"""
Fallback 노드 — rendy/modules/failure_handler.py 강화.

4단계 재시도:
  Phase 1: zone 무시, 전체 ref_point 순회 (wall_facing + parallel)
  Phase 2: direction 변경 (inward + perpendicular)
  Phase 3: center + none (ref_point 최후 수단)
  Phase 4: slot 전수 순회 (Rendy deterministic_fallback 대응) — ref_point 근처 아닌 slot까지 포함
"""
import logging

from app.state import SmallState
from app.utils import calculate_position, serialize_placement, OBJECT_STANDARDS
from app.nodes_small.placement import (
    _validate_placement,
    MAIN_ARTERY_HALF_BUFFER_MM, DEFAULT_CLEARSPACE_MM, DEFAULT_HEIGHT_MM,
)

logger = logging.getLogger(__name__)

MAX_FALLBACK_ROUNDS = 3  # Rendy 기준 3회. 통합 시 2회로 줄었으나 원작자 판단 복원.


def _ref_point_to_slot(rp: dict) -> dict:
    """reference_point → slot 호환 딕셔너리 변환."""
    return {
        "x_mm": rp["coord"][0],
        "y_mm": rp["coord"][1],
        "wall_linestring": rp.get("wall_segment"),
        "wall_normal": rp.get("wall_normal", "north"),
        "wall_normal_vec": rp.get("wall_normal_vec", (0.0, 1.0)),
        "wall_angle_deg": rp.get("wall_angle_deg", 0.0),
        "zone_label": rp.get("zone_label", "mid_zone"),
    }


def run(state: SmallState) -> SmallState:
    """실패 오브젝트 재배치 시도 — ref_point 기반."""
    # 2026-05-08: fallback 진입 추적 (photo_wall partition_reuse 미작동 진단용)
    from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
    failed = state.get("failed_objects") or []
    current_round = state.get("fallback_round", 0)
    dump_agent_reason(state, node="fallback", decision="enter",
                      reason=f"failed={len(failed)} round={current_round}",
                      context={
                          "failed_types": [f.get("object_type") for f in failed],
                          "round": current_round,
                          "max_rounds": MAX_FALLBACK_ROUNDS,
                      })

    if not failed:
        dump_agent_reason(state, node="fallback", decision="skip_no_failed",
                          reason="failed list 비어있음", context={})
        return {"fallback_round": 0}

    if current_round >= MAX_FALLBACK_ROUNDS:
        logger.info(f"[fallback] max rounds reached ({MAX_FALLBACK_ROUNDS})")
        dump_agent_reason(state, node="fallback", decision="skip_max_rounds",
                          reason=f"round {current_round} >= MAX {MAX_FALLBACK_ROUNDS}",
                          context={})
        return {}

    eligible = state.get("eligible_objects") or []
    reference_points = state.get("reference_points") or []
    usable_poly = state.get("usable_poly")
    placed_raw = list(state.get("placed_raw") or [])
    placed_objects = list(state.get("placed_objects") or [])
    brand_data = state.get("brand_data") or {}
    pair_rules = brand_data.get("pair_rules") or []

    # static cache (placement.py와 동일)
    from shapely.ops import unary_union
    from app.utils import extract_structural_dead_zones
    dead_zones = state.get("dead_zones") or []
    main_artery = state.get("main_artery")
    entrance_buffer = state.get("entrance_buffer")
    structural_dz = extract_structural_dead_zones(state)
    static_obstacles = [dz for dz in dead_zones if hasattr(dz, "area")]
    # 계단 입구 core_access (감압구역 1500mm) 반드시 포함 — 소방법 절대 차단
    for dz_entry in structural_dz:
        if dz_entry["type"] == "core_access":
            static_obstacles.append(dz_entry["poly"])
    if main_artery:
        static_obstacles.append(main_artery.buffer(MAIN_ARTERY_HALF_BUFFER_MM))
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None
    clearspace = brand_data.get("brand", {}).get("clearspace_mm", {})
    clearspace = clearspace.get("value", DEFAULT_CLEARSPACE_MM) if isinstance(clearspace, dict) else DEFAULT_CLEARSPACE_MM

    if not usable_poly or not reference_points:
        return {"fallback_round": current_round + 1}

    obj_map = {o["object_type"]: o for o in eligible}
    # Layer 1-B 호환 — placement.run이 산출한 scaled_clearances를 fallback 검증에서도 동일하게 적용
    scaled_clearances = dict(state.get("scaled_clearances") or {})
    # brand_clearances — placement.run과 동일 구성 (Phase 5 step-down 시 compute_scaled_clearance 재호출용)
    brand_clearances_raw = {}
    for rule in brand_data.get("placement_rules") or []:
        ot = rule.get("object_type")
        if ot and (rule.get("front_clearance_mm") is not None or rule.get("back_clearance_mm") is not None):
            brand_clearances_raw[ot] = {
                "front": rule.get("front_clearance_mm", 0),
                "back": rule.get("back_clearance_mm", 0),
            }
    still_failed = []
    new_placed = []

    # 3단계 시도 전략
    strategies = [
        ("wall_facing", "parallel"),    # Phase 1: 기본
        ("inward", "perpendicular"),    # Phase 2: direction 변경
        ("center", "none"),             # Phase 3: 최후 수단
    ]

    # walk_mm 내림차순 정렬 (먼 ref_point부터 — 여유 공간 가능성 높음)
    # _is_blocked ref_point 제외 — inaccessible_rooms 근처 배치 원천 차단
    sorted_rps = sorted(
        [rp for rp in reference_points if not rp.get("_is_blocked")],
        key=lambda rp: rp.get("walk_mm", 0), reverse=True,
    )

    # 순차 완화 단계: 기물 간 간격을 단계적으로 줄임
    # 주동선(1200mm)은 절대 타협 불가 (static_cache에 600mm 버퍼로 들어있음)
    relax_steps = [0, 50, 100]  # 0mm(기본 900mm), 50mm(800mm), 100mm(700mm)

    for fail_entry in failed:
        obj_type = fail_entry["object_type"]
        obj = obj_map.get(obj_type)
        if not obj:
            still_failed.append(fail_entry)
            continue

        placed = False
        for direction, alignment in strategies:
            if placed:
                break
            # 가벽은 center 배치 금지 — 벽에 못 붙으면 배치 포기
            if direction == "center" and obj_type.startswith("partition_wall"):
                continue

            for relax_mm in relax_steps:
                if placed:
                    break

                for rp in sorted_rps:
                    rp_slot = _ref_point_to_slot(rp)
                    rp_slot["_floor_poly"] = usable_poly

                    result = calculate_position(rp_slot, obj, direction, alignment, usable_poly)

                    # 검증: strict=False (접근성/corridor 스킵) + 간격 순차 완화
                    # VMD 절대 차단(R2/R4)은 strict 무관하게 항상 적용
                    reason = _validate_placement(
                        result, usable_poly, static_cache, placed_raw, clearspace,
                        obj_type=obj_type, pair_rules=pair_rules,
                        strict=False, corridor_relax_mm=relax_mm,
                        zone_label=rp.get("zone_label", ""),
                        height_mm=obj.get("height_mm", 0),
                        brand_clearances=brand_clearances_raw,
                        scaled_clearances=scaled_clearances,
                    )
                    if reason != "ok":
                        continue

                    entry = {
                        **result,
                        "anchor_key": rp["id"],
                        "zone_label": rp.get("zone_label", "mid_zone"),
                        "direction": direction,
                        "placed_because": f"fallback_phase_{strategies.index((direction, alignment)) + 1}_relax{relax_mm}",
                        "height_mm": obj.get("height_mm", DEFAULT_HEIGHT_MM),
                        "category": obj.get("category", ""),
                        # 2026-05-09 진규님 명시: label / manual_label / wall_attachment / front_edge 누락 fix
                        # — placement json placed_objects 의 manual_label=None 회귀 차단 (5-9 15:05 진단).
                        "label": obj.get("label") or obj.get("name") or (OBJECT_STANDARDS.get(obj.get("object_type", "")) or {}).get("name") or obj.get("object_type", ""),
                        "manual_label": obj.get("manual_label"),
                        "wall_attachment": obj.get("wall_attachment", "free"),
                        "front_edge": obj.get("front_edge", "width"),
                    }
                    placed_raw.append(entry)
                    placed_objects.append(serialize_placement(entry))
                    new_placed.append(obj_type)
                    placed = True
                    break

        # ── Phase 3.5: photo_wall 만 — partition 재활용 시도 (#114 + #115, A-3) ──
        # Phase 1~3 (ref_point 기반 시도) 다 실패 후, Phase 4 (slot 전수) 진입 전.
        # 기 배치된 partition_wall_I/L 의 외측면을 photo_wall 의 그래픽 역할로 흡수.
        # 2026-05-08: LANDUP_PARTITION_REUSE default ON 전환 (그래픽 월 가이드). opt-out 만 (=0).
        if not placed and obj_type == "photo_wall":
            from app.nodes_small.partition_reuse import try_reuse_partition_for_photo_wall
            # 2026-05-08: 진입 추적 (5-8 진단 — partition_reuse 미작동 사유)
            dump_agent_reason(state, node="partition_reuse", decision="enter",
                              reason=f"photo_wall fallback Phase 1~3 fail → Phase 3.5 진입",
                              context={
                                  "obj_type": obj_type,
                                  "phase_1_3_placed": placed,
                              })
            failed_obj_for_reuse = {"object_type": obj_type}
            reuse_result = try_reuse_partition_for_photo_wall(state, failed_obj_for_reuse)
            dump_agent_reason(state, node="partition_reuse", decision=("absorbed" if reuse_result else "skipped"),
                              reason=f"try_reuse_partition_for_photo_wall returned {reuse_result}",
                              context={
                                  "result": reuse_result,
                                  "placed_partitions_with_graphic_none": [
                                      {"obj_type": p.get("object_type"), "anchor_key": p.get("anchor_key"),
                                       "graphic_face": p.get("graphic_face")}
                                      for p in (state.get("placed_objects") or [])
                                      if str(p.get("object_type", "")).startswith("partition_wall")
                                  ],
                              })
            if reuse_result:
                # 재활용 성공 → photo_wall 은 placed 처리. partition 의 graphic_face 가 갱신됨 (state.placed_objects 안)
                # placed_raw 에 별도 entry 추가 안 함 — partition 자체가 photo_wall 역할 흡수.
                # new_placed 에 photo_wall 명시 → 호출자 (place_service) 가 failed 에서 제거 가능.
                new_placed.append(obj_type)
                placed = True

        # ── Phase 4: slot 전수 순회 (Rendy deterministic_fallback 대응) ──
        # ref_point 기반 시도 전부 실패 시, slot 그리드까지 전수 탐색
        # zone 무시, strict=False, clearspace 최대 완화
        if not placed:
            slots = state.get("slots") or {}
            # walk_mm 내림차순 — 안쪽 slot부터
            sorted_slots = sorted(slots.items(), key=lambda kv: kv[1].get("walk_mm", 0), reverse=True)
            for slot_key, slot in sorted_slots:
                if placed:
                    break
                # flush 기물은 벽 slot만 허용 — center/interior 튕겨나가는 것 방지
                if obj.get("wall_attachment") == "flush" and ("center" in slot_key or "interior" in slot_key):
                    continue
                slot["_floor_poly"] = usable_poly
                for direction, alignment in strategies:
                    if obj_type.startswith("partition_wall") and direction == "center":
                        continue
                    result = calculate_position(slot, obj, direction, alignment, usable_poly)
                    reason = _validate_placement(
                        result, usable_poly, static_cache, placed_raw, clearspace,
                        obj_type=obj_type, pair_rules=pair_rules,
                        strict=False, corridor_relax_mm=100,
                        zone_label=slot.get("zone_label", ""),
                        height_mm=obj.get("height_mm", 0),
                        brand_clearances=brand_clearances_raw,
                        scaled_clearances=scaled_clearances,
                    )
                    if reason != "ok":
                        continue
                    entry = {
                        **result,
                        "anchor_key": slot_key,
                        "zone_label": slot.get("zone_label", "mid_zone"),
                        "direction": direction,
                        "placed_because": f"fallback_phase_4_slot_exhaustive ({direction})",
                        "height_mm": obj.get("height_mm", DEFAULT_HEIGHT_MM),
                        "category": obj.get("category", ""),
                        # 2026-05-09 진규님 명시: label / manual_label / wall_attachment / front_edge 누락 fix.
                        "label": obj.get("label") or obj.get("name") or (OBJECT_STANDARDS.get(obj.get("object_type", "")) or {}).get("name") or obj.get("object_type", ""),
                        "manual_label": obj.get("manual_label"),
                        "wall_attachment": obj.get("wall_attachment", "free"),
                        "front_edge": obj.get("front_edge", "width"),
                    }
                    placed_raw.append(entry)
                    placed_objects.append(serialize_placement(entry))
                    new_placed.append(obj_type)
                    logger.info(f"[fallback] Phase 4 slot 전수 성공: {obj_type} → {slot_key}")
                    placed = True
                    break

        # ── Phase 5: clearance step-down 재시도 (Tier 1-1 Layer 1-C) ──
        # Phase 1~4 전부 실패 시 해당 기물의 scaled_clearances를 200mm씩 낮춰 재시도.
        # floor 하한선(DIRECTIONAL_CLEARANCE_FLOOR)에 도달하면 중단 → still_failed.
        # 참고: reports/AD/2026-04-20_small_store_finalization_tier1.md §1
        if not placed:
            from app.vmd_constants import step_down_clearance
            current_dc = dict(scaled_clearances.get(obj_type) or {"front": 0, "back": 0})
            stepdown_iter = 0
            MAX_STEPDOWN_ITERATIONS = 10  # 무한루프 방지 (실제로는 floor 도달이 먼저)

            while stepdown_iter < MAX_STEPDOWN_ITERATIONS and not placed:
                next_dc = step_down_clearance(current_dc, obj_type)
                if next_dc is None:
                    break  # floor 도달
                stepdown_iter += 1
                # 이 기물만 임시로 낮춘 scaled_clearances 구성
                temp_clearances = dict(scaled_clearances)
                temp_clearances[obj_type] = next_dc

                # ref_point + slot 전수 재시도 (strategies × relax_steps)
                for direction, alignment in strategies:
                    if placed:
                        break
                    if direction == "center" and obj_type.startswith("partition_wall"):
                        continue
                    for rp in sorted_rps:
                        if placed:
                            break
                        rp_slot = _ref_point_to_slot(rp)
                        rp_slot["_floor_poly"] = usable_poly
                        result = calculate_position(rp_slot, obj, direction, alignment, usable_poly)
                        reason = _validate_placement(
                            result, usable_poly, static_cache, placed_raw, clearspace,
                            obj_type=obj_type, pair_rules=pair_rules,
                            strict=False, corridor_relax_mm=100,
                            zone_label=rp.get("zone_label", ""),
                            height_mm=obj.get("height_mm", 0),
                            brand_clearances=brand_clearances_raw,
                            scaled_clearances=temp_clearances,
                        )
                        if reason != "ok":
                            continue
                        entry = {
                            **result,
                            "anchor_key": rp["id"],
                            "zone_label": rp.get("zone_label", "mid_zone"),
                            "direction": direction,
                            "placed_because": f"fallback_phase_5_stepdown_front{next_dc['front']}mm_back{next_dc['back']}mm",
                            "height_mm": obj.get("height_mm", DEFAULT_HEIGHT_MM),
                            "category": obj.get("category", ""),
                            # 2026-05-09 진규님 명시: label / manual_label / wall_attachment / front_edge 누락 fix.
                            "label": obj.get("label") or obj.get("name") or (OBJECT_STANDARDS.get(obj.get("object_type", "")) or {}).get("name") or obj.get("object_type", ""),
                            "manual_label": obj.get("manual_label"),
                            "wall_attachment": obj.get("wall_attachment", "free"),
                            "front_edge": obj.get("front_edge", "width"),
                        }
                        placed_raw.append(entry)
                        placed_objects.append(serialize_placement(entry))
                        new_placed.append(obj_type)
                        # 성공한 scaled 값을 state용에 반영 (이 기물은 완화값으로 최종 확정)
                        scaled_clearances[obj_type] = next_dc
                        placed = True
                        logger.info(
                            f"[fallback] Phase 5 step-down 성공: {obj_type} → {rp['id']} "
                            f"(front={next_dc['front']}mm, back={next_dc['back']}mm, iter={stepdown_iter})"
                        )
                        break

                current_dc = next_dc  # 다음 루프에서 한 번 더 낮춤

        if not placed:
            still_failed.append(fail_entry)

    logger.info(f"[fallback] round {current_round+1}: {len(new_placed)} recovered, {len(still_failed)} still failed")

    # 1-3 (#523 후속): sub_graph_reasons dump — fallback 노드의 round 단위 사유 가시화.
    # recovered = fallback 단계가 강제 끼워박은 obj. still_failed = fallback 도 못 살린 obj.
    # 사용자 의문 ("agent 가 왜 못 놓았는지") 의 핵심 path — placement reject → fallback 진입 → 결과.
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        dump_agent_reason(state, node="fallback",
                          decision="recovered" if new_placed else ("failed" if still_failed else "noop"),
                          reason=f"round {current_round+1}: recovered={len(new_placed)} still_failed={len(still_failed)}",
                          context={
                              "round": current_round + 1,
                              "max_rounds": MAX_FALLBACK_ROUNDS,
                              "recovered_types": [p.get("object_type") for p in new_placed],
                              "recovered_phases": [p.get("placed_because", "")[:80] for p in new_placed],
                              "still_failed_types": [f.get("object_type") for f in still_failed],
                              "still_failed_reasons": [f.get("reason", "")[:80] for f in still_failed],
                          })
    except Exception as _e:
        logger.warning(f"[fallback] reason_dump 실패 — skip: {_e}")

    return {
        "placed_objects": placed_objects,
        "placed_raw": placed_raw,
        "failed_objects": still_failed,
        "scaled_clearances": scaled_clearances,  # Phase 5 step-down으로 수정되었을 수 있음
        # fallback_round는 failure_classifier에서 관리
    }
