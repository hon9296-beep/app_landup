"""
detect 작업 핸들러 — 도면 파싱 + Vision 감지.

params 구조:
  - user_id (int, 필수)
  - floor_archive_id (int, 필수)  # 2026-04-27 rename: pdf_id → floor_archive_id
  - project_id (선택)
  - file_type (str) — 'pdf' / 'dxf' / 'dwg' / 'image'
  - file_bytes_b64 (str) — Base64 인코딩된 파일

흐름:
  1. running 상태 알림
  2. 파서 (pdf / dxf / image 분기) → polygon + 스케일 감지
  3. Vision → 설비/입구 감지
  4. done 상태 + 결과 Java에 전달 (Java가 user_projects INSERT)
"""
import base64
import logging

from app.services.java_callback import notify_java

logger = logging.getLogger(__name__)


async def handle(job_id: int, params: dict) -> None:
    """도면 분석 작업 — 파서 + Vision 실행."""
    project_id = params.get("project_id")

    await notify_java(job_id, status="running")

    try:
        user_id = params.get("user_id")
        floor_archive_id = params.get("floor_archive_id")
        file_type = params.get("file_type", "pdf")
        b64 = params.get("file_bytes_b64", "")
        if not b64:
            raise ValueError("file_bytes_b64 missing")
        file_bytes = base64.b64decode(b64)

        force_layer = params.get("force_layer")

        initial_state = {
            "file_bytes": file_bytes,
            "file_type": file_type,
            "fallback_round": 0,
            "force_layer": force_layer,
        }

        await notify_java(job_id, progress={"stage": "parser", "pct": 10, "message": "도면 파싱 중"})

        # 2026-05-03 — detect_large_graph sub-graph invoke 로 교체.
        # nodes_large/parser·vision 이 nodes_small mirror 업그레이드 완료 (천장 높이 + token_tracker + dead_zone 세분류).
        # detect 단계는 매장 분기 전 공통이지만 large 모듈 사용 (small mirror 라 동작 동일).
        # sub-graph: parser/parser_dxf/parser_image (file_type conditional) → vision → END.
        from app.graph import compile_detect_large_graph
        _detect_graph = compile_detect_large_graph()

        # vision progress 콜백 (sub-graph stream 미사용이라 invoke 전 한 번)
        await notify_java(job_id, progress={"stage": "vision", "pct": 60, "message": "설비 감지 중"})

        merged = _detect_graph.invoke(initial_state)

        # Tier 2: 자동 추출 실패 → 레이어 선택 요청
        if merged.get("parse_status") == "layer_select_needed":
            import json as _json
            layers = merged.get("available_layers", [])
            await notify_java(
                job_id,
                status="error",
                project_id=project_id,
                error_message="LAYER_SELECT:" + _json.dumps({"available_layers": layers}, ensure_ascii=False),
            )
            logger.info(f"[handle_detect] layer_select_needed job_id={job_id}, layers={layers}")
            return

        image_bytes = merged.get("image_bytes")
        image_base64 = base64.b64encode(image_bytes).decode() if image_bytes else None

        # 결과 JSON (routers/detect.py 응답 포맷과 동일)
        result = {
            "floor_polygon_px": merged.get("floor_polygon_px"),
            "scale_mm_per_px": merged.get("scale_mm_per_px"),
            "scale_confirmed": merged.get("scale_confirmed", False),
            "entrance": merged.get("entrance"),
            "entrances": merged.get("entrances") or [],
            "sprinklers": merged.get("sprinklers") or [],
            "fire_hydrants": merged.get("fire_hydrants") or [],
            "electrical_panels": merged.get("electrical_panels") or [],
            "inaccessible_rooms": merged.get("inaccessible_rooms") or [],
            "inner_walls": merged.get("inner_walls") or [],
            "detected_width_mm": merged.get("detected_width_mm"),
            "detected_height_mm": merged.get("detected_height_mm"),
            "image_base64": image_base64,
            "vision_transform": merged.get("vision_transform"),
            "page_count": merged.get("page_count") or 1,
        }

        await notify_java(
            job_id,
            status="done",
            user_id=user_id,
            floor_archive_id=floor_archive_id,
            project_id=project_id,
            result=result,
            progress={"stage": "done", "pct": 100, "message": "완료"},
        )
        logger.info(f"[handle_detect] 완료 job_id={job_id}")

    except Exception as e:
        logger.error(f"[handle_detect] 실패 job_id={job_id}: {e}", exc_info=True)
        await notify_java(job_id, status="error", project_id=project_id, error_message=str(e))
