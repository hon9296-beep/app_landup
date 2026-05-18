"""
space_data 작업 핸들러 — Shapely + NetworkX 공간 계산.

services/space_service.build_space_data 와 로직은 거의 동일하지만,
단계별 notify_java(progress) 를 끼워 넣어야 해서 인라인 복제 유지.
(루틴만 공유하려면 콜백 훅을 주입하는 설계가 필요. 후순위.)

params:
  - user_id, floor_archive_id, brand_manual_id, project_id (FK)  # 2026-04-27 rename: pdf_id → floor_archive_id
  - auto_detected, brand_dict, brand_category, venue_type, facade_type
  - manual_dead_zones_px (선택)
"""
import logging

from shapely.geometry import Polygon

from app.services.java_callback import notify_java
from app.worker_config import is_cancelled

logger = logging.getLogger(__name__)


async def handle(job_id: int, params: dict) -> None:
    """공간 계산 작업 — state(Shapely 포함) → Java 정규화 포맷으로 직렬화 후 콜백."""
    project_id = params.get("project_id")

    if is_cancelled(job_id):
        await notify_java(job_id, status="cancelled", project_id=project_id)
        return

    await notify_java(job_id, status="running")

    try:
        user_id = params.get("user_id")
        floor_archive_id = params.get("floor_archive_id")
        brand_manual_id = params.get("brand_manual_id")

        ad = params.get("auto_detected", {})
        brand_dict = params.get("brand_dict", {})
        brand_category = params.get("brand_category", "기타")
        from app.facade_rules import DEFAULT_FACADE_TYPE
        from app.venue_rules import DEFAULT_VENUE_TYPE
        venue_type = params.get("venue_type", DEFAULT_VENUE_TYPE)
        facade_type = params.get("facade_type", DEFAULT_FACADE_TYPE)

        # polygon + scale → usable_poly
        poly_px = ad.get("floor_polygon_px", [])
        scale = ad.get("scale_mm_per_px", 10)
        poly_mm = [(p[0] * scale, p[1] * scale) for p in poly_px]
        if len(poly_mm) < 3:
            raise ValueError("polygon too small")
        usable_poly = Polygon(poly_mm)

        # entrance
        ent = ad.get("entrance")
        if isinstance(ent, dict) and "x_px" in ent:
            entrance_mm = (ent["x_px"] * scale, ent["y_px"] * scale)
        elif isinstance(ent, dict) and "points" in ent:
            pts = ent["points"]
            entrance_mm = (pts[0]["x_px"] * scale, pts[0]["y_px"] * scale) if pts else None
        else:
            entrance_mm = None

        sprinklers_mm = [(s["x_px"] * scale, s["y_px"] * scale)
                         for s in ad.get("sprinklers", []) if isinstance(s, dict)]
        hydrants_mm = [(s["x_px"] * scale, s["y_px"] * scale)
                       for s in ad.get("fire_hydrants", []) if isinstance(s, dict)]
        electric_panels_mm = [(s["x_px"] * scale, s["y_px"] * scale)
                              for s in ad.get("electrical_panels", []) if isinstance(s, dict)]

        brand_data = brand_dict if "brand" in brand_dict else {
            "brand": {**brand_dict, "brand_category": brand_category},
            "fire": {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200},
            "construction": {"wall_clearance_mm": 300, "object_gap_mm": 300},
            "placement_rules": brand_dict.get("placement_rules", []),
        }

        # inaccessible_rooms
        inaccessible_polys = []
        inaccessible_types = []
        for room in ad.get("inaccessible_rooms", []):
            pts = room.get("polygon_px", [])
            if len(pts) >= 3:
                mm_pts = [(p[0] * scale, p[1] * scale) for p in pts]
                p = Polygon(mm_pts)
                if p.is_valid and p.area > 0:
                    inaccessible_polys.append(p)
                    inaccessible_types.append(room.get("type", "unknown"))

        # entrances
        entrances_raw = ad.get("entrances", []) or []
        all_entrances_mm = []
        if entrances_raw:
            for e in entrances_raw:
                if isinstance(e, dict):
                    x = e.get("x_px", 0) * scale
                    y = e.get("y_px", 0) * scale
                    all_entrances_mm.append({"coord": (x, y), "type": e.get("type", "MAIN_DOOR")})
        elif entrance_mm:
            all_entrances_mm = [{"coord": entrance_mm, "type": "MAIN_DOOR"}]

        state = {
            "usable_poly": usable_poly,
            "entrance_mm": entrance_mm,
            "all_entrances_mm": all_entrances_mm,
            "entrance_width_mm": 1200,
            "sprinklers_mm": sprinklers_mm,
            "hydrants_mm": hydrants_mm,
            "electric_panels_mm": electric_panels_mm,
            "inner_wall_linestrings": [],
            "inaccessible_polys": inaccessible_polys,
            "inaccessible_types": inaccessible_types,
            "dead_zones": [],
            "floor_polygon_px": poly_px,
            "scale_mm_per_px": scale,
            "brand_data": brand_data,
            "fallback_round": 0,
        }

        # 면적 분기 — 로컬 bool (services.state_builder.is_large 함수와 이름 중복 방지)
        SCALE_THRESHOLD_M2 = 165
        area_m2 = usable_poly.area / 1_000_000
        is_large_area = area_m2 >= SCALE_THRESHOLD_M2

        if is_cancelled(job_id):
            await notify_java(job_id, status="cancelled", project_id=project_id)
            return

        await notify_java(job_id, progress={"stage": "dead_zone", "pct": 30, "message": "Dead Zone 계산 중"})

        if is_large_area:
            # 2026-05-02 graph 랭그래프화 단계 5 — sub-graph invoke 로 교체.
            # space_data_large_graph (dead_zone → ref_point_gen → walk_mm) 가 운영 진실.
            # walk_mm 진입 시점 progress 콜백은 graph stream 모드 미사용이라 invoke 전 한 번만.
            from app.graph import compile_space_data_large_graph
            await notify_java(job_id, progress={"stage": "walk_mm", "pct": 70, "message": "보행 거리 계산 중"})
            _space_data_graph = compile_space_data_large_graph()
            result = _space_data_graph.invoke(state)
            state.update(result)
            state["_scale_type"] = "large"
            # 2026-05-04 dev2 머지 — sub-graph invoke 후 cancel 체크. sub-graph 안 cancel 은 후속.
            if is_cancelled(job_id):
                await notify_java(job_id, status="cancelled", project_id=project_id)
                return
        else:
            from app.nodes_small import dead_zone, ref_point_gen, slot_gen, walk_mm
            state["venue_type"] = venue_type
            state["facade_type"] = facade_type
            state.update(dead_zone.run(state))
            state.update(slot_gen.run(state))
            state.update(ref_point_gen.run(state))
            if is_cancelled(job_id):
                await notify_java(job_id, status="cancelled", project_id=project_id)
                return
            await notify_java(job_id, progress={"stage": "walk_mm", "pct": 70, "message": "보행 거리 계산 중"})
            state.update(walk_mm.run(state))
            state["_scale_type"] = "small"

        # 수동 데드존
        manual_dzs = params.get("manual_dead_zones_px", []) or []
        if manual_dzs:
            from shapely.geometry import Point
            from shapely.geometry import box as shapely_box
            existing = state.get("dead_zones") or []
            for dz in manual_dzs:
                x_mm = dz["x_px"] * scale
                y_mm = dz["y_px"] * scale
                if dz.get("shape") == "rect":
                    w_mm = dz["w_px"] * scale
                    h_mm = dz["h_px"] * scale
                    existing.append(shapely_box(x_mm, y_mm, x_mm + w_mm, y_mm + h_mm))
                else:
                    r_mm = dz["radius_px"] * scale
                    existing.append(Point(x_mm, y_mm).buffer(r_mm))
            state["dead_zones"] = existing

        # state → Java 정규화 포맷으로 직렬화 (points/polygons/anchors/zones/main_artery)
        from app.serializers.space_serializer import space_data_to_java_payload
        space_data_payload = space_data_to_java_payload(state)

        await notify_java(
            job_id,
            status="done",
            user_id=user_id,
            floor_archive_id=floor_archive_id,
            brand_manual_id=brand_manual_id,
            project_id=project_id,
            result=space_data_payload,  # Java applySpaceDataResult 기대 구조
            progress={"stage": "done", "pct": 100, "message": "완료"},
        )
        logger.info(f"[handle_space_data] 완료 job_id={job_id} area={round(area_m2, 2)}m²")

    except Exception as e:
        logger.error(f"[handle_space_data] 실패 job_id={job_id}: {e}", exc_info=True)
        await notify_java(job_id, status="error", project_id=project_id, error_message=str(e))
