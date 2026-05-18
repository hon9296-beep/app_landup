"""/api/place (HTTP) — 배치 파이프라인 실행."""
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.place import PlaceRequest
from app.services.place_service import place_large, place_small
from app.services.state_builder import is_large, rebuild_state_from_body

router = APIRouter()
logger = logging.getLogger(__name__)


def _prepare_state(body: dict) -> dict:
    """body → state 재구성 + 프론트 override(brand_category/density/locked/user_req) 반영."""
    session_id = body.get("_session_id")
    logger.info(f"[place] state 재구성 (캐시 비활성화): session={session_id}")
    state = rebuild_state_from_body(body)

    # density_ratio 반영
    density = body.get("density_ratio")
    if density is not None:
        state["density_ratio"] = density

    # user_requirements 반영 (intent_parser 입력)
    user_req = body.get("user_requirements", "")
    if user_req:
        state["user_requirements"] = user_req
        state.pop("resolved_intents", None)  # 재배치 시 이전 인텐트 초기화

    # locked_objects 반영 (기존 배치 유지 — 추가/제거 모드 진입 조건)
    locked = body.get("locked_objects") or []
    if locked:
        state["locked_objects"] = locked
        logger.info(f"[place] locked_objects {len(locked)}개 적용")

    # brand_data 업데이트 (space-data 이후 프론트가 brand_dict 편집 가능)
    if "brand_dict" in body and body["brand_dict"]:
        bd = body["brand_dict"]
        if "brand" in bd:
            # [2026-04-22 S-8f] 프론트 선택 brand_category override 재적용.
            # rebuild_state_from_body 에서 override 한 brand_data 를 여기서 덮어쓰면
            # LLM 파싱 "기타" 로 되돌아감. 동일 로직 여기도 수행.
            user_cat = body.get("brand_category")
            if user_cat and user_cat != "기타":
                bd = dict(bd)
                bd["brand"] = {**bd.get("brand", {}), "brand_category": user_cat}
            state["brand_data"] = bd
        elif "placement_rules" in bd:
            state["brand_data"]["placement_rules"] = bd["placement_rules"]

    return state


@router.post("/api/place")
async def place_objects(body: PlaceRequest):
    """면적 분기에 따라 대형 or 소중형 배치 파이프라인 실행. DB 저장 없음 — Java가 처리."""
    try:
        state = _prepare_state(body.model_dump())

        # 2026-05-01 SSOT trace: API 입력단 — 사용자 brand_category override 진입 시점 dump
        from app.categories import dump_category_trace
        body_dict = body.model_dump()
        dump_category_trace(
            stage="api.place_request_received",
            raw_brand_category=body_dict.get("brand_category"),
            user_override_present=bool(body_dict.get("brand_category") and body_dict.get("brand_category") != "기타"),
            brand_dict_present=bool(body_dict.get("brand_dict")),
            brand_dict_brand_category=(
                body_dict.get("brand_dict", {}).get("brand", {}).get("brand_category")
                if isinstance(body_dict.get("brand_dict"), dict)
                else None
            ),
        )

        # ── 면적 분기 ──
        scale_type = state.get("_scale_type", "large" if is_large(state) else "small")

        loop = asyncio.get_running_loop()
        if scale_type == "large":
            return await loop.run_in_executor(None, place_large, state)
        else:
            return await loop.run_in_executor(None, place_small, state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Place 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


