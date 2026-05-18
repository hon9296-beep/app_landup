"""
가벽 전처리 배치 노드 — A-1.

design_intents에서 가벽(partition_wall_I/L)만 추출하여 먼저 배치.
배치 후 Virtual Wall ref_point 생성 + 가벽 bbox를 dead_zones에 추가.
이후 placement.py는 가벽이 이미 static_cache에 포함된 상태로 기물만 배치.
"""
import logging

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.state import SmallState
from app.utils import extract_structural_dead_zones

logger = logging.getLogger(__name__)

SAFETY_MARGIN_MM = 50


def run(state: SmallState) -> SmallState:
    """가벽만 먼저 배치 → ref_point 생성 → dead_zones에 가벽 bbox 추가."""
    intents = state.get("design_intents") or []
    eligible = state.get("eligible_objects") or []
    usable_poly_raw = state.get("usable_poly")

    if not usable_poly_raw:
        return {}

    usable_poly = usable_poly_raw

    dead_zones = list(state.get("dead_zones") or [])
    dead_zone_types = list(state.get("dead_zone_types") or [])
    structural_dz = extract_structural_dead_zones(state)
    reference_points = list(state.get("reference_points") or [])
    # 디버그: wall_linestring 보유 ref_point 수
    wall_rp_count = sum(1 for rp in reference_points if rp.get("wall_linestring"))
    logger.info(f"[partition_placement] ref_points: {len(reference_points)}개, wall_linestring 보유: {wall_rp_count}개")
    main_artery = state.get("main_artery")
    entrance_buffer = state.get("entrance_buffer")

    # static_cache 구성 (placement.py와 동일)
    static_obstacles = [dz for dz in dead_zones if hasattr(dz, "area")]
    for dz_entry in structural_dz:
        if dz_entry["type"] == "core_access":
            static_obstacles.append(dz_entry["poly"])
    if main_artery:
        static_obstacles.append(main_artery.buffer(450))
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None

    # 가벽 intent만 필터
    partition_intents = [it for it in intents if it.get("object_type", "").startswith("partition_wall")]
    other_intents = [it for it in intents if not it.get("object_type", "").startswith("partition_wall")]

    if not partition_intents:
        logger.info("[partition_placement] 가벽 intent 없음 — 스킵")
        return {"design_intents": other_intents}

    # eligible에서 가벽만
    obj_map = {}
    for o in eligible:
        if o["object_type"].startswith("partition_wall"):
            obj_map[o["object_type"]] = o

    ref_point_map = {rp["id"]: rp for rp in reference_points}
    placed_partitions = []
    new_ref_points = []

    for intent in partition_intents:
        obj_type = intent["object_type"]
        obj = obj_map.get(obj_type)
        if not obj:
            logger.warning(f"[partition_placement] {obj_type} eligible에 없음 — 스킵")
            continue

        ref_point_id = intent.get("ref_point_id")
        zone_label = intent.get("zone_label", "")

        # ref_point 후보 구성
        rp_candidates = []
        if ref_point_id and ref_point_id in ref_point_map:
            rp_candidates.append(ref_point_map[ref_point_id])
        # 같은 zone ref_point 추가
        for rp in reference_points:
            if rp.get("_is_blocked"):
                continue
            if rp["id"] != ref_point_id and rp.get("zone_label") == zone_label:
                rp_candidates.append(rp)
        # 나머지 ref_point
        for rp in reference_points:
            if rp.get("_is_blocked"):
                continue
            if rp not in rp_candidates:
                rp_candidates.append(rp)

        placed = False
        w = obj["width_mm"]
        d = obj["depth_mm"]
        import os, json as _json
        from datetime import datetime as _dt
        import math
        from shapely.ops import nearest_points
        _dd = os.path.join(os.path.dirname(__file__), "..", "..", "debug_logs", _dt.now().strftime("%Y-%m-%d"))
        os.makedirs(_dd, exist_ok=True)
        # 거부 사유 추적용
        reject_log = []

        for rp in rp_candidates:
            # ── 0. 벽 ref_point만 허용 — 벽 이름 prefix로 판별 ──
            # wall_linestring 은 Shapely 객체라 state 직렬화 전달 시 누락될 수 있음
            # → wall_ prefix ref_point만 허용 + usable_poly.exterior에서 벽 세그먼트 직접 탐색
            rp_id = rp.get("id", "")
            if not (rp_id.startswith("wall_") or rp_id.startswith("east_wall_") or rp_id.startswith("north_wall_")):
                reject_log.append({"rp_id": rp_id, "reason": "벽 prefix 아님"})
                continue

            # ── Layer 1b 강화 (#250): zone_label 기준 차단 ──
            # ref_point.label 과 zone_label 디커플링 약점 (label=거리 ratio, zone=walk_mm) 으로
            # design.py 에서 우회되어 partition 의도가 entrance_zone ref_point 에 매칭되는
            # 케이스 차단. R8 prompt 룰 + design.py _OBJ_PREFERENCE.zones 위에 코드층 안전망.
            # facade 변형 케이스 (#345, 통유리 미디어 가벽) 활성 시 본 차단 풀거나 예외 처리 필요.
            rp_zone = rp.get("zone_label", "")
            if obj_type.startswith("partition_wall") and rp_zone == "entrance_zone":
                reject_log.append({"rp_id": rp_id, "reason": f"{obj_type} entrance_zone 차단 (Layer 1b R8)"})
                continue
            # C4 (5-7 21:36 + 5-8 13:30 라이브 회귀 fix): partition_wall_I mid_zone 차단.
            # mid_zone wall ref 에 가벽 매핑 시 placement 가 매장 중앙 향해 수직 돌출 →
            # 매장 한복판 가로 시위 형태. AP-010 + design prompt 위에 코드층 안전망.
            # L 은 staff_zone (deep_zone 코너) 정공 — 본 차단 미적용 (예외 통과).
            if obj_type == "partition_wall_I" and rp_zone == "mid_zone":
                reject_log.append({"rp_id": rp_id, "reason": "partition_wall_I mid_zone 차단 (C4 — 시위 회귀 fix)"})
                continue

            wall_ls = rp.get("wall_linestring")
            if not wall_ls:
                # fallback: usable_poly.exterior에서 ref_point에 가장 가까운 벽 세그먼트 구성
                from shapely.geometry import LineString
                rp_pt = Point(rp["coord"][0], rp["coord"][1])
                ext_coords = list(usable_poly.exterior.coords)
                best_seg = None
                best_dist = float("inf")
                for i in range(len(ext_coords) - 1):
                    seg = LineString([ext_coords[i], ext_coords[i + 1]])
                    seg_dist = seg.distance(rp_pt)
                    if seg_dist < best_dist:
                        best_dist = seg_dist
                        best_seg = seg
                if best_seg and best_dist < 2000:  # 2000mm 이내 벽만
                    wall_ls = best_seg
                    logger.info(f"[partition_placement] {rp_id}: wall_linestring 없음 → exterior fallback (dist={best_dist:.0f}mm)")
                else:
                    reject_log.append({"rp_id": rp_id, "reason": f"벽 세그먼트 못 찾음 (dist={best_dist:.0f}mm)"})
                    continue

            # ── 1. anchor_end 확정 — 벽 위 정확한 점 ──
            raw_x, raw_y = rp["coord"]
            foot_pt = Point(raw_x, raw_y)
            proj = wall_ls.project(foot_pt)
            foot = wall_ls.interpolate(proj)
            anchor_x, anchor_y = foot.x, foot.y

            # anchor_end snap — 벽(usable_poly.exterior)에서 떨어져 있으면 가장 가까운 벽 위로
            anchor_pt = Point(anchor_x, anchor_y)
            dist_to_wall = usable_poly.exterior.distance(anchor_pt)
            if dist_to_wall > 50:  # 50mm 이상 떨어져 있으면 snap
                nearest_wall_pt, _ = nearest_points(usable_poly.exterior, anchor_pt)
                anchor_x, anchor_y = nearest_wall_pt.x, nearest_wall_pt.y
                logger.info(f"[partition_placement] anchor_end snap: ({raw_x:.0f},{raw_y:.0f}) → ({anchor_x:.0f},{anchor_y:.0f}), dist={dist_to_wall:.0f}mm")

            # ── 2. 벽 법선 방향(매장 안쪽) ──
            delta = 10
            p1 = wall_ls.interpolate(max(0, proj - delta))
            p2 = wall_ls.interpolate(min(wall_ls.length, proj + delta))
            wall_dx = p2.x - p1.x
            wall_dy = p2.y - p1.y
            wall_len = math.hypot(wall_dx, wall_dy)
            if wall_len < 0.01:
                reject_log.append({"rp_id": rp_id, "reason": "wall_len < 0.01"})
                continue

            # 벽 수직 후보 2개 중 바닥 중심 향하는 쪽
            n1x, n1y = -wall_dy / wall_len, wall_dx / wall_len
            n2x, n2y = wall_dy / wall_len, -wall_dx / wall_len
            fcx, fcy = usable_poly.centroid.x, usable_poly.centroid.y
            dot1 = n1x * (fcx - anchor_x) + n1y * (fcy - anchor_y)
            dot2 = n2x * (fcx - anchor_x) + n2y * (fcy - anchor_y)
            nx, ny = (n1x, n1y) if dot1 >= dot2 else (n2x, n2y)

            # ── 3. free_end + center 계산 ──
            free_x = anchor_x + nx * w
            free_y = anchor_y + ny * w

            # free_end 바닥 밖이면 배치 거부 (반대편 벽 발사 방지)
            if not usable_poly.contains(Point(free_x, free_y)):
                reject_log.append({"rp_id": rp_id, "reason": f"free_end 바닥 밖 ({free_x:.0f},{free_y:.0f})"})
                continue

            cx = (anchor_x + free_x) / 2
            cy = (anchor_y + free_y) / 2

            # ── 4. bbox 직접 생성 ──
            wall_ux, wall_uy = wall_dx / wall_len, wall_dy / wall_len
            hw, hd = w / 2, d / 2
            corners = [
                (cx - nx * hw - wall_ux * hd, cy - ny * hw - wall_uy * hd),
                (cx - nx * hw + wall_ux * hd, cy - ny * hw + wall_uy * hd),
                (cx + nx * hw + wall_ux * hd, cy + ny * hw + wall_uy * hd),
                (cx + nx * hw - wall_ux * hd, cy + ny * hw - wall_uy * hd),
            ]
            bbox = Polygon(corners)

            # 렌더링용 rotation
            rot_deg = (math.degrees(math.atan2(-nx, ny)) + 90) % 360
            front_vec = (nx, ny)

            # ── 5. 검증 ──
            if usable_poly and bbox.area > 0:
                overlap = usable_poly.intersection(bbox).area
                ratio = overlap / bbox.area
                if ratio < 0.999:
                    reject_log.append({"rp_id": rp_id, "reason": f"바닥 overlap 부족 ({ratio:.3f})"})
                    continue
            if static_cache and bbox.intersects(static_cache):
                reject_log.append({"rp_id": rp_id, "reason": "static_cache 충돌"})
                continue
            collision = False
            for pp in placed_partitions:
                if bbox.intersects(pp["bbox_polygon"]):
                    collision = True
                    break
            if collision:
                reject_log.append({"rp_id": rp_id, "reason": "기배치 가벽 충돌"})
                continue

            # ── 배치 성공 ──
            entry = {
                "center_x_mm": round(cx, 1),
                "center_y_mm": round(cy, 1),
                "rotation_deg": round(rot_deg, 1),
                "width_mm": w,
                "depth_mm": d,
                "bbox_polygon": bbox,
                "object_type": obj_type,
                "front_vec": front_vec,
                "anchor_key": rp["id"],
                "zone_label": rp.get("zone_label") or zone_label,
                "direction": "wall_perpendicular",
                "placed_because": intent.get("placed_because", ""),
                "inspired_by_images": intent.get("inspired_by_images") or [],  # PR #226 Phase 2 복원
                "inspired_by_insights": intent.get("inspired_by_insights") or [],  # PR #226 Phase 2.1 복원
                # 2026-04-29: intent 의 placement_reason 을 entry 에 보존.
                # ref_point fallback (의도 wall_X 거부 → wall_Y 성공) 시 Layer 3 매칭 키
                # (intent.ref_point_id == pp.anchor_key) 가 깨져서 정당한 가벽이 drop 되던 bug.
                # entry 가 placement_reason 자체 보유 → Layer 3 가 next() 검색 없이 직접 사용.
                "placement_reason": intent.get("placement_reason", ""),
                # 2026-04-29 (#114 + #115): graphic_face 메타 — 가벽 면 활용 추적.
                # 기본값 "none" + basis "default_front" — 추후 partition_reuse 가 photo_wall 대체 시
                # "outer" + "photo_wall_substitute" 로 갱신. LLM intent 무관, 코드가 직접 부여.
                "graphic_face": "none",
                "graphic_face_basis": "default_front",
                "height_mm": obj.get("height_mm", 2400),
                "category": obj.get("category", ""),
                "wall_attachment": "flush",
                "front_edge": "width",
                # 2026-05-09 진규님 명시: label / manual_label 누락 fix — placement json 회귀 차단.
                "label": obj.get("label") or obj.get("name") or obj.get("object_type", ""),
                "manual_label": intent.get("manual_label") or obj.get("manual_label"),
                # 디버깅용 — anchor_end/free_end
                "anchor_end_mm": [round(anchor_x, 1), round(anchor_y, 1)],
                "free_end_mm": [round(free_x, 1), round(free_y, 1)],
                "normal_vec": [round(nx, 4), round(ny, 4)],
                "wall_vec": [round(wall_ux, 4), round(wall_uy, 4)],
                "bbox_corners": [[round(c[0]), round(c[1])] for c in corners],
                "anchor_snap_dist": round(dist_to_wall, 1),
            }
            placed_partitions.append(entry)
            logger.info(
                f"[partition_placement] 배치: {obj_type} @ ({entry['center_x_mm']:.0f},{entry['center_y_mm']:.0f}) "
                f"rot={entry['rotation_deg']:.1f} fv={entry.get('front_vec')} slot={rp['id']}"
            )

            # Virtual Wall ref_point 생성
            from app.nodes_small.placement import _generate_partition_wall_linestrings
            from app.nodes_small.ref_point_gen import _split_long_segment, _segment_to_ref_points

            virtual_walls = _generate_partition_wall_linestrings(entry, usable_poly, structural_dead_zones=structural_dz)
            entrance_pt = Point(state.get("entrance_mm")) if state.get("entrance_mm") else None
            for vw in virtual_walls:
                segs = _split_long_segment(vw)
                for seg in segs:
                    rps = _segment_to_ref_points(seg, len(reference_points) + len(new_ref_points), "inner", usable_poly, entrance_pt, 0)
                    for nrp in rps:
                        nrp["is_partition"] = True
                        nrp["label"] = "partition_face"
                    new_ref_points.extend(rps)
            logger.info(f"[partition_placement] Virtual Wall → {len(virtual_walls)}면, new ref_points +{len(new_ref_points)}")

            placed = True
            break

        if not placed:
            logger.warning(f"[partition_placement] {obj_type} 배치 실패 — 모든 ref_point 거부")

        # 거부 사유 JSON 덤프
        with open(os.path.join(_dd, "partition_reject_log.json"), "w", encoding="utf-8") as _f:
            _json.dump({
                "obj_type": obj_type,
                "intended_rp": ref_point_id,
                "total_candidates": len(rp_candidates),
                "wall_candidates": sum(1 for rp in rp_candidates if rp.get("id", "").startswith("wall_")),
                "placed": placed,
                "placed_at": placed_partitions[-1]["anchor_key"] if placed and placed_partitions else None,
                "reject_log": reject_log,
            }, _f, ensure_ascii=False, indent=2)

    # ── Layer 3: 짝꿍 검증 — 단독 배치 partition drop ──
    # 사유 기반:
    #   - "space_partition" / "u_shape" / "staff_zone" : 구조적 분할 의도 명시 → 짝꿍 없어도 통과
    #     · staff_zone (#253) : Back of House 분할은 본 목적상 외부 짝꿍 불필요 (폐쇄 구역)
    #   - "back_to_back" / "pair_join" : 짝꿍 필수 → 동일 zone 에 pair candidate 없으면 drop
    #   - 그 외 (예: balance) : Layer 1b 의 RESTRICTED_REASONS 가 막아야 했지만 빠져나온 케이스 → drop
    # drop 시 partition_face ref_point 도 자동 누락 → 후속 placement 가 자연스럽게 다른 ref_point 시도 (기존 fallback 메커니즘 활용).
    # 2026-04-29 (#254): _PARTITION_PAIR_CANDIDATES 로컬 dict 외부화 — prompt_rules.PARTITION_PAIR_GENERIC
    # + PARTITION_PAIR_BY_CATEGORY (카테고리 차등) + get_partition_pair_candidates() 헬퍼.
    _PAIR_REQUIRED_REASONS = {"back_to_back", "pair_join"}
    _SOLO_OK_REASONS = {"space_partition", "u_shape", "staff_zone"}

    # 카테고리 추출 — brand_data 또는 default "기타"
    from app.nodes_small.prompt_rules import get_partition_pair_candidates
    _brand_data = state.get("brand_data") or {}
    _brand = _brand_data.get("brand") if isinstance(_brand_data.get("brand"), dict) else _brand_data
    _category_raw = (_brand or {}).get("brand_category", "기타")
    _category = _category_raw.get("value", "기타") if isinstance(_category_raw, dict) else (_category_raw or "기타")

    def _has_pair_in_zone(pp_zone: str, obj_type: str) -> bool:
        candidates = get_partition_pair_candidates(obj_type, _category)
        if not candidates:
            return False
        for it in other_intents:
            if it.get("object_type") in candidates and it.get("zone_label") == pp_zone:
                return True
        return False

    filtered_partitions = []
    filtered_new_ref_points = []
    for pp in placed_partitions:
        obj_type = pp["object_type"]
        # 2026-04-29: entry 가 placement_reason 직접 보유 (placement loop 에서 저장).
        # 이전 next() 검색은 intent.ref_point_id == pp.anchor_key 매칭 필요 → ref_point fallback
        # 시 매칭 실패 → 빈 문자열 → 정당한 가벽이 화이트리스트 외 분기로 drop 되던 bug.
        intent_reason = pp.get("placement_reason", "")
        pp_zone = pp.get("zone_label", "")
        keep = False
        drop_reason = None
        if intent_reason in _SOLO_OK_REASONS:
            keep = True  # 구조적 분할 의도 명시 → 통과
        elif intent_reason in _PAIR_REQUIRED_REASONS:
            if _has_pair_in_zone(pp_zone, obj_type):
                keep = True
            else:
                drop_reason = f"placement_reason={intent_reason!r} 인데 zone={pp_zone!r} 에 pair candidate 없음"
        else:
            drop_reason = f"placement_reason={intent_reason!r} — 화이트리스트 외 (Layer 1b 우회)"

        if keep:
            filtered_partitions.append(pp)
            # 해당 partition 의 face ref_point 만 유지 (anchor_key 기반 매칭)
            for nrp in new_ref_points:
                if nrp.get("source_partition_anchor") == pp["anchor_key"] or True:
                    # 현재 코드는 partition 별 ref_point 분리 안 함 — 일괄 유지 (filter 비효율은 추후 개선)
                    pass
            filtered_new_ref_points = new_ref_points
        else:
            logger.warning(
                f"[partition_placement] {obj_type} drop @ {pp['anchor_key']}: {drop_reason}"
            )

    placed_partitions = filtered_partitions
    new_ref_points = filtered_new_ref_points if filtered_partitions else []
    if not placed_partitions:
        logger.info("[partition_placement] 모든 가벽 drop — partition_face ref_point 미생성")

    # 가벽 bbox를 dead_zones에 추가 → 이후 placement에서 static_cache로 인식
    for pp in placed_partitions:
        dead_zones.append(pp["bbox_polygon"])
        dead_zone_types.append("partition_wall")

    # ref_point에 가벽 면 추가
    reference_points.extend(new_ref_points)

    logger.info(
        f"[partition_placement] 완료: 가벽 {len(placed_partitions)}개 배치, "
        f"ref_points +{len(new_ref_points)}개, dead_zones +{len(placed_partitions)}개"
    )

    # 1-3 (#523 후속): sub_graph_reasons dump — partition 배치/실패 사유 가시화.
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        partition_intents = [i for i in (state.get("design_intents") or [])
                             if i.get("object_type", "").startswith("partition_wall")]
        failed_count = len(partition_intents) - len(placed_partitions)
        dump_agent_reason(state, node="partition_placement",
                          decision="success" if failed_count == 0 and partition_intents else ("partial" if placed_partitions else "noop"),
                          reason=f"intents={len(partition_intents)} placed={len(placed_partitions)} failed={failed_count}",
                          context={
                              "intent_types": [i.get("object_type") for i in partition_intents],
                              "intent_reasons": [i.get("placement_reason") for i in partition_intents],
                              "placed_anchor_keys": [p.get("anchor_key") for p in placed_partitions],
                              "new_ref_points": len(new_ref_points),
                          })
    except Exception as _e:
        logger.warning(f"[partition_placement] reason_dump 실패 — skip: {_e}")

    return {
        "design_intents": other_intents,  # 가벽 제거한 기물 intent만
        "placed_partitions": placed_partitions,
        "reference_points": reference_points,
        "dead_zones": dead_zones,
        "dead_zone_types": dead_zone_types,
        # 기물 placement에서 가벽을 placed_polygons 초기값으로 사용
        "_partition_placed_raw": placed_partitions,
    }
