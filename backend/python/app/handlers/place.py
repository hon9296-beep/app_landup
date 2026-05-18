"""
place 작업 핸들러 — 배치 파이프라인 실행.

params:
  - user_id (int, 필수)
  - floor_detection_id (int, 필수) — space_data 재조회 키
  - space_data (dict, 선택) — 있으면 재조회 건너뜀 (구 호출 경로)
  - brand_dict (dict, 선택)
  - brand_category (str, 선택)
  - density_ratio (float, 선택)
  - user_requirements (str, 선택)
  - locked_objects (list, 선택)
  - floor_archive_id, brand_manual_id, project_id (선택) — FK 유지용  # 2026-04-27 rename: pdf_id → floor_archive_id

흐름:
  1. space_data 재조회 (Java /api/internal/floor-detections/{id})
  2. state 재구성 (Shapely 객체 생성)
  3. place_large or place_small (대형/소형 분기)
  4. 결과를 Java에 전달 → placement_objects INSERT + user_projects INSERT
"""
import asyncio
import logging

import httpx

from app.services.java_callback import notify_java
from app.worker_config import JAVA_INTERNAL_URL, get_http_client, is_cancelled

logger = logging.getLogger(__name__)


async def handle(job_id: int, params: dict) -> None:
    """배치 생성 작업 — LLM 배치 + 검증 파이프라인."""
    project_id = params.get("project_id")

    if is_cancelled(job_id):
        await notify_java(job_id, status="cancelled", project_id=project_id)
        return

    await notify_java(job_id, status="running")

    try:
        user_id = params.get("user_id")
        floor_archive_id = params.get("floor_archive_id")
        brand_manual_id = params.get("brand_manual_id")
        floor_detection_id = params.get("floor_detection_id")

        # 신 스키마: Java 가 space_data 를 params 에 안 넣음. worker 가 floor_detection_id 로 재조회.
        space_data = params.get("space_data") or {}
        if not space_data:
            if not floor_detection_id:
                raise ValueError("space_data / floor_detection_id 둘 다 없음")
            # /internal/** 는 SecurityConfig 에서 permitAll (JWT 없이 호출 가능 — Docker 네트워크 전용)
            fd_url = f"{JAVA_INTERNAL_URL}/api/internal/floor-detections/{floor_detection_id}"
            for _attempt in range(3):
                try:
                    fd_res = await get_http_client().get(fd_url)
                    fd_res.raise_for_status()
                    space_data = fd_res.json().get("result") or {}
                    break
                except httpx.HTTPError as e:
                    if _attempt == 2:
                        raise ValueError(f"space_data 조회 실패 (3회): {e}") from e
                    logger.warning(f"[handle_place] space_data 조회 실패 (attempt {_attempt + 1}): {e}")
                    await asyncio.sleep(2 ** _attempt)
            logger.info(f"[handle_place] space_data 재조회 완료 (fdId={floor_detection_id})")
        if not space_data:
            raise ValueError(f"space_data 재조회 실패: floor_detection_id={floor_detection_id}")

        # 구 api.py 방식은 {"space_data": {...}} 로 이중 래핑 저장됨. 언래핑.
        if "space_data" in space_data and "floor" not in space_data:
            space_data = space_data["space_data"]
            logger.info("[handle_place] 이중 래핑 언래핑됨")

        # 디버깅: space_data 구조 확인
        logger.info(f"[handle_place] space_data keys: {list(space_data.keys())}")
        floor_obj = space_data.get("floor", {})
        logger.info(f"[handle_place] floor keys: {list(floor_obj.keys()) if isinstance(floor_obj, dict) else 'NOT A DICT'}")
        logger.info(f"[handle_place] polygon_mm length: {len(floor_obj.get('polygon_mm', [])) if isinstance(floor_obj, dict) else 0}")

        # rebuild_state_from_body 에 맞는 body 구성
        # 2026-04-29 (TR_D [데드존_위_설치] 처리 + rendy 권장 spread 패턴 리팩터링):
        #   - **space_data** 로 모든 키 자동 spread (floor / entrance / sprinklers_mm /
        #     hydrants_mm / electric_panels_mm / dead_zones / venue_type / facade_type 등)
        #   - 이후 params 명시 키가 spread 를 덮어씀 (Python dict 순서상 뒤에 명시한 키 우선)
        #   - routers/place.py 의 PlaceRequest schema (USE_DIRECT 흐름) 와 동일 contract.
        #   - 향후 새 state 키 추가 시 PlaceRequest schema 만 갱신하면 양쪽 자동 동기화 (이중 정의 제거).
        body = {
            **space_data,
            "brand_dict": params.get("brand_dict", space_data.get("brand", {})),
            "brand_category": params.get("brand_category", "기타"),
            "density_ratio": params.get("density_ratio"),
            "user_requirements": params.get("user_requirements", ""),
            "locked_objects": params.get("locked_objects", []),
        }

        if is_cancelled(job_id):
            await notify_java(job_id, status="cancelled", project_id=project_id)
            return

        await notify_java(job_id, progress={"stage": "state_rebuild", "pct": 10, "message": "공간 데이터 복원 중"})

        from app.services.place_service import place_large, place_small
        from app.services.state_builder import is_large, rebuild_state_from_body
        state = rebuild_state_from_body(body)

        # 방어: rebuild_state_from_body 후 usable_poly 유실 시 재생성
        if not state.get("usable_poly"):
            from shapely.geometry import Polygon
            poly_mm = body["floor"].get("polygon_mm", [])
            if len(poly_mm) >= 3:
                state["usable_poly"] = Polygon(poly_mm)
                logger.warning("[handle_place] usable_poly 재생성 (rebuild 후 None이었음)")

        logger.info(f"[handle_place] state keys: {list(state.keys())[:15]}")
        logger.info(f"[handle_place] has usable_poly: {state.get('usable_poly') is not None}")
        logger.info(f"[handle_place] _scale_type: {state.get('_scale_type')}")

        # ref_image_loader → Java handoff 용. project 컨텍스트 추적.
        if project_id is not None:
            state["user_project_id"] = project_id

        # 2026-05-01 Phase 2 — concept_area 영속화 용 floor_detection_id 주입
        if floor_detection_id is not None:
            state["floor_detection_id"] = floor_detection_id

        # density_ratio / user_requirements 반영
        density = params.get("density_ratio")
        if density is not None:
            state["density_ratio"] = density
        user_req = params.get("user_requirements", "")
        if user_req:
            state["user_requirements"] = user_req
            state.pop("resolved_intents", None)  # 재배치 시 이전 인텐트 초기화

        # locked_objects 반영 (기존 배치 유지 — 추가/제거 모드 진입 조건)
        # 우선순위: params 직접 전달 > DB 자동 조회
        locked_objects = params.get("locked_objects") or []
        if not locked_objects and user_req and project_id and user_id:
            # 재배치 요청 + 프론트가 locked_objects를 넘기지 않은 경우 → DB에서 자동 조회
            lo_url = f"{JAVA_INTERNAL_URL}/api/internal/projects/{project_id}/layout-objects?user_id={user_id}"
            try:
                lo_res = await get_http_client().get(lo_url)
                if lo_res.status_code == 200:
                    locked_objects = lo_res.json().get("objects", [])
                    logger.info(f"[handle_place] DB에서 locked_objects {len(locked_objects)}개 로드 (projectId={project_id})")
                elif lo_res.status_code == 404:
                    logger.info(f"[handle_place] layout-objects 없음 (404)")
                else:
                    logger.warning(f"[handle_place] layout-objects 조회 실패: status={lo_res.status_code}")
            except Exception as e:
                logger.warning(f"[handle_place] layout-objects 조회 예외: {e}")
        if locked_objects:
            state["locked_objects"] = locked_objects
            logger.info(f"[handle_place] locked_objects {len(locked_objects)}개 적용 → 추가 모드 가능")

        # 면적 분기
        scale_type = state.get("_scale_type") or ("large" if is_large(state) else "small")

        if is_cancelled(job_id):
            await notify_java(job_id, status="cancelled", project_id=project_id)
            return

        await notify_java(job_id, progress={"stage": "design", "pct": 40, "message": "배치 의도 결정 중 (LLM)"})

        loop = asyncio.get_running_loop()
        if scale_type == "large":
            result = await loop.run_in_executor(None, place_large, state)
        else:
            result = await loop.run_in_executor(None, place_small, state)

        await notify_java(
            job_id,
            critical=True,
            status="done",
            user_id=user_id,
            floor_archive_id=floor_archive_id,
            brand_manual_id=brand_manual_id,
            floor_detection_id=floor_detection_id,
            project_id=project_id,
            result=result,
            progress={"stage": "done", "pct": 100, "message": "완료"},
        )
        placed_count = len(result.get("placed", [])) if result else 0
        logger.info(f"[handle_place] 완료 job_id={job_id} placed={placed_count}")

    except Exception as e:
        logger.error(f"[handle_place] 실패 job_id={job_id}: {e}", exc_info=True)
        await notify_java(job_id, critical=True, status="error", project_id=project_id, error_message=str(e))
