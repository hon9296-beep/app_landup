"""pillar_toilet_detect 노드 — large 전용 (2026-05-05 burning_task 1단계).

도면 이미지에서 기둥/화장실 검출 (Haiku Vision). 별도 노드라 기존 vision 흐름 영향 X.
검출 결과는 dead_zone 노드가 dead_zones 에 흡수 (sprinkler / fire_hydrant 처럼).

설계: docs/docs-shin/main_tasks/burning_task/8_[배치]_기둥_화장실_데드존_인식_누락.md
"""
import base64
import logging
import os

from anthropic import Anthropic

from app.state import LargeState
from app.nodes_large.b_space_data.prompts.pillar_toilet_detect import (
    PILLAR_TOILET_DETECT_SYSTEM,
    PILLAR_TOILET_DETECT_TOOL,
    PILLAR_TOILET_DETECT_PROMPT,
)

logger = logging.getLogger(__name__)


def run(state: LargeState) -> dict:
    """이미지에서 기둥/화장실 검출. mm 좌표 변환 후 state 박음.

    Shin 결정 (2026-05-05):
    - 모델: claude-haiku-4-5 (저비용, 단순 판정 충분)
    - temperature: 0.1
    - 기존 vision 흐름 영향 X (별도 노드)
    - dead_zone 노드가 받아서 dead_zones 통합 흡수 (DB 컬럼 신설 X)

    return:
      - pillars_mm: list of {"x_mm", "y_mm", "w_mm", "h_mm"}
      - toilets_mm: list of {"x_mm", "y_mm", "w_mm", "h_mm", "label"}
    실패 시 빈 list (재시도 X — 후속 노드 무영향).
    """
    image_bytes = state.get("image_bytes")
    scale_mm_per_px = state.get("scale_mm_per_px") or 1.0

    if not image_bytes:
        logger.info("[pillar_toilet_detect] image_bytes 없음 — skip")
        return {"pillars_mm": [], "toilets_mm": []}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[pillar_toilet_detect] API 키 없음 — skip")
        return {"pillars_mm": [], "toilets_mm": []}

    client = Anthropic(api_key=api_key)
    img_b64 = base64.b64encode(image_bytes).decode()

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            temperature=0.1,
            system=PILLAR_TOILET_DETECT_SYSTEM,
            tools=[PILLAR_TOILET_DETECT_TOOL],
            tool_choice={"type": "tool", "name": "detect_pillar_toilet"},
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {"type": "text", "text": PILLAR_TOILET_DETECT_PROMPT},
                ],
            }],
        )
        from app.token_tracker import track_usage
        track_usage("large.pillar_toilet_detect", response)

        # Tool use 응답 파싱
        result = {}
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                result = dict(block.input or {})
                break

        # px → mm 변환
        pillars_mm = []
        for p in result.get("pillars", []) or []:
            try:
                pillars_mm.append({
                    "x_mm": float(p["x_px"]) * scale_mm_per_px,
                    "y_mm": float(p["y_px"]) * scale_mm_per_px,
                    "w_mm": float(p["w_px"]) * scale_mm_per_px,
                    "h_mm": float(p["h_px"]) * scale_mm_per_px,
                })
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[pillar_toilet_detect] pillar 파싱 실패: {e}")

        toilets_mm = []
        for t in result.get("toilets", []) or []:
            try:
                toilets_mm.append({
                    "x_mm": float(t["x_px"]) * scale_mm_per_px,
                    "y_mm": float(t["y_px"]) * scale_mm_per_px,
                    "w_mm": float(t["w_px"]) * scale_mm_per_px,
                    "h_mm": float(t["h_px"]) * scale_mm_per_px,
                    "label": t.get("label", ""),
                })
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[pillar_toilet_detect] toilet 파싱 실패: {e}")

        logger.info(
            f"[pillar_toilet_detect] 기둥={len(pillars_mm)}, 화장실={len(toilets_mm)} "
            f"(scale={scale_mm_per_px:.2f}mm/px)"
        )
        return {"pillars_mm": pillars_mm, "toilets_mm": toilets_mm}

    except Exception as e:
        logger.warning(f"[pillar_toilet_detect] 호출 실패 — skip: {e}")
        return {"pillars_mm": [], "toilets_mm": []}
