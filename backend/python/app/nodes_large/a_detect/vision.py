"""
Vision 감지 노드 — Claude Vision으로 스프링클러/소화전/분전반/입구 감지.

Shin 코드 베이스. px → 1200x900 정규화 좌표 변환.
px→mm 변환 + usable_poly 구축도 이 노드에서 수행.
"""
import base64
import logging
from typing import Optional

from anthropic import Anthropic
from shapely.geometry import Polygon

from app.state import LargeState
from app.utils import parse_llm_json

logger = logging.getLogger(__name__)

VISION_SYSTEM = """당신은 한국 건축 CAD 도면 분석 전문가입니다.
한국 건축 도면의 표준 기호 체계에 정통하며, 보이는 것을 빠짐없이 보고합니다.
확신 정도는 confidence로 구분하세요."""

VISION_PROMPT = """아래 이미지는 한국 팝업스토어 부지의 CAD 도면입니다 (평면도 영역만 크롭됨).
이미지의 실제 픽셀 좌표로 응답하세요.

## 감지 규칙

---

### 1. entrances (입구) — 최우선 감지
다음 중 하나라도 보이면 감지 (복수 가능):
- **벽 개구부(오픈형 입구)**: 외벽이 끊어진 넓은 구간 → 양쪽 끝점을 x_px,y_px와 x2_px,y2_px로 반환
- **문 호(arc) 기호**: 벽 개구부에 1/4 원호가 그려진 표준 문 기호
- **"입구" "출입구" "ENTRANCE" 텍스트**가 있는 위치
- **굵은 화살표(→ ↑)**가 벽 개구부를 향하는 경우
주의: 창문(가는 선 2개), 환기구, 단순 벽 틈은 입구 아님
오픈형 입구가 아니면 x2_px, y2_px는 null로 반환

### 2. sprinklers (스프링클러)
다음이 보이면 감지 (여러 개 가능):
- 원 안에 +, ×, S 기호가 있는 심볼
- "SP" 텍스트와 함께 있는 원형 기호
- 천장 평면에 규칙적으로 배열된 원형 심볼들
주의: 기호 없는 단순 원, 조명 기호는 스프링클러 아님

### 3. fire_hydrant (소화전)
다음 중 하나라도 보이면 감지:
- "FH" 또는 "소화전" 텍스트가 명확히 보이는 경우 → confidence: "high"
- 벽면에 부착된 사각형 기호 + 호스릴 형태 → confidence: "medium"
- 벽면의 빨간색/특수 마킹된 사각형 박스 → confidence: "medium"

### 4. electrical_panel (분전반)
다음 중 하나라도 보이면 감지:
- "EP", "분전반", "MCC", "배전반" 텍스트가 보이는 경우 → confidence: "high"
- 벽면에 부착된 직사각형 심볼 (번개/전기 기호 동반) → confidence: "medium"
- 벽면의 눈에 띄는 직사각형 박스 (설비 영역) → confidence: "medium"

---

```json
{
  "entrances": [
    {"x_px": 숫자, "y_px": 숫자, "x2_px": 숫자_또는_null, "y2_px": 숫자_또는_null, "is_main": true, "confidence": "high|medium"}
  ],
  "sprinklers": [{"x_px": 숫자, "y_px": 숫자, "confidence": "high|medium"}],
  "fire_hydrant": [{"x_px": 숫자, "y_px": 숫자, "confidence": "high|medium"}],
  "electrical_panel": [{"x_px": 숫자, "y_px": 숫자, "confidence": "high|medium"}]
}
```"""


def run(state: LargeState) -> LargeState:
    """Vision 감지 + px→mm 변환 + usable_poly 구축."""
    import os
    updates: dict = {}

    # Vision 감지 (이미지가 있을 때만)
    image_bytes = state.get("image_bytes")
    transform = state.get("vision_transform")

    if image_bytes and transform:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.info("[vision] API 키 없음 — Vision 감지 건너뜀")
        else:
            try:
                client = Anthropic(api_key=api_key)
                vision_result = _run_vision(client, image_bytes)

                # 좌표 변환 — 복수 입구 지원
                # entrances (신규 복수 형식) 또는 entrance (구 단일 형식) 처리
                vision_entrances = vision_result.get("entrances") or []
                if not vision_entrances and vision_result.get("entrance"):
                    vision_entrances = [vision_result["entrance"]]

                # Vision 결과가 있으면 항상 우선 (parser 휴리스틱보다 신뢰)
                entrance = state.get("entrance")
                entrances = state.get("entrances") or []
                if vision_entrances:
                    rescaled = [_rescale(e, transform) for e in vision_entrances]
                    rescaled = [r for r in rescaled if r]
                    if rescaled:
                        main = next((r for r in rescaled if r.get("is_main")), rescaled[0])
                        entrance = main
                        entrances = rescaled
                updates["entrance"] = entrance
                updates["entrances"] = entrances

                sprinklers = state.get("sprinklers") or []
                if not sprinklers:
                    sprinklers = [r for r in [_rescale(p, transform) for p in (vision_result.get("sprinklers") or [])] if r]
                updates["sprinklers"] = sprinklers

                fh = state.get("fire_hydrants") or []
                if not fh:
                    fh = [r for r in [_rescale(p, transform) for p in (vision_result.get("fire_hydrant") or [])] if r]
                updates["fire_hydrants"] = fh

                ep = state.get("electrical_panels") or []
                if not ep:
                    ep = [r for r in [_rescale(p, transform) for p in (vision_result.get("electrical_panel") or [])] if r]
                updates["electrical_panels"] = ep

                logger.info(f"[vision] 감지: entrances={len(entrances)}, SP={len(sprinklers)}, FH={len(fh)}, EP={len(ep)}")
            except Exception as e:
                logger.error(f"[vision] Vision 실패: {e}")

    # ── OCR 치수 추출로 scale 보정 (yeonhwa/detect_floor_outline.py) ────
    scale_confirmed = state.get("scale_confirmed", False)
    if not scale_confirmed and state.get("image_bytes"):
        ocr_scale = _try_ocr_scale(state["image_bytes"])
        if ocr_scale:
            updates["scale_mm_per_px"] = ocr_scale
            updates["scale_confirmed"] = True
            logger.info(f"[vision] OCR scale 보정: {ocr_scale:.2f} mm/px")

    # ── px→mm 변환 + usable_poly 구축 ──────────────────────────────────
    floor_polygon_px = state.get("floor_polygon_px")
    scale = updates.get("scale_mm_per_px") or state.get("scale_mm_per_px") or 1.0

    if floor_polygon_px and len(floor_polygon_px) >= 3:
        # px 좌표를 mm로 변환
        coords_mm = [(p[0] * scale, p[1] * scale) for p in floor_polygon_px]
        usable_poly = Polygon(coords_mm)
        if not usable_poly.is_valid:
            from shapely.validation import make_valid
            usable_poly = make_valid(usable_poly)

        updates["usable_poly"] = usable_poly

        # 입구 mm 변환
        entrance = updates.get("entrance") or state.get("entrance")
        if entrance:
            updates["entrance_mm"] = (entrance["x_px"] * scale, entrance["y_px"] * scale)
        else:
            # fallback: polygon 하단 중앙 (Y-down 좌표계 — max(ys)가 화면 아래=바닥, small과 정합)
            xs = [p[0] for p in floor_polygon_px]
            ys = [p[1] for p in floor_polygon_px]
            updates["entrance_mm"] = ((min(xs) + max(xs)) / 2 * scale, max(ys) * scale)

        # 복수 입구 mm
        entrances = state.get("entrances") or []
        all_entrances_mm = []
        for ent in entrances:
            coord = (ent.get("x_px", 0) * scale, ent.get("y_px", 0) * scale)
            all_entrances_mm.append({"coord": coord, "type": ent.get("type", "MAIN_DOOR")})
        if not all_entrances_mm and updates.get("entrance_mm"):
            all_entrances_mm = [{"coord": updates["entrance_mm"], "type": "MAIN_DOOR"}]
        updates["all_entrances_mm"] = all_entrances_mm

        # 설비 mm 변환
        updates["sprinklers_mm"] = [(p["x_px"]*scale, p["y_px"]*scale)
                                     for p in (updates.get("sprinklers") or state.get("sprinklers") or [])]
        updates["hydrants_mm"] = [(p["x_px"]*scale, p["y_px"]*scale)
                                   for p in (updates.get("fire_hydrants") or state.get("fire_hydrants") or [])]
        updates["electric_panels_mm"] = [(p["x_px"]*scale, p["y_px"]*scale)
                                 for p in (updates.get("electrical_panels") or state.get("electrical_panels") or [])]

        # inaccessible rooms → Shapely Polygon
        inaccessible_polys = []
        for room in (state.get("inaccessible_rooms") or []):
            coords = room.get("polygon_px", [])
            if len(coords) >= 3:
                mm_coords = [(p[0]*scale, p[1]*scale) for p in coords]
                poly = Polygon(mm_coords)
                if poly.is_valid and poly.area > 0:
                    inaccessible_polys.append(poly)
        updates["inaccessible_polys"] = inaccessible_polys

        # floor_px 최솟값 (dead_zone에서 inner wall 보정용)
        px_xs = [p[0] for p in floor_polygon_px]
        px_ys = [p[1] for p in floor_polygon_px]
        updates["floor_px_min_x"] = min(px_xs)
        updates["floor_px_min_y"] = min(px_ys)

    return updates


def _run_vision(client, image_bytes: bytes) -> dict:
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        temperature=0,
        system=VISION_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    from app.token_tracker import track_usage
    track_usage("vision.py", response)
    if not response.content:
        raise ValueError("Vision API 빈 응답")
    return parse_llm_json(response.content[0].text)


def _try_ocr_scale(image_bytes: bytes) -> Optional[float]:
    """OCR로 치수 텍스트 추출 → scale_mm_per_px 계산 (yeonhwa 기반).

    pytesseract가 설치되어 있으면 시도, 없으면 None 반환.
    """
    try:
        import pytesseract
        import cv2
        import numpy as np
        import re
    except ImportError:
        return None

    try:
        img_array = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            return None

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 여백 영역 크롭 (치수선은 보통 가장자리에 위치)
        regions = [
            gray[:int(h * 0.15), :],          # 상단 15%
            gray[int(h * 0.85):, :],           # 하단 15%
            gray[:, :int(w * 0.10)],           # 좌측 10%
        ]

        numbers = []
        pattern = re.compile(r'(\d{3,6})\s*(mm|m|cm)?')

        for region in regions:
            text = pytesseract.image_to_string(region, config='--psm 6')
            for match in pattern.finditer(text):
                val = int(match.group(1))
                unit = match.group(2)
                if unit == 'm' and val < 100:
                    val *= 1000
                elif unit == 'cm':
                    val *= 10
                if 3000 <= val <= 100000:
                    numbers.append(val)

        if not numbers:
            return None

        max_dim_mm = max(numbers)
        # 이미지 가장 긴 변 = max_dim_mm
        max_px = max(w, h)
        scale = max_dim_mm / max_px
        logger.info(f"[vision/OCR] {max_dim_mm}mm / {max_px}px = {scale:.2f} mm/px")
        return scale

    except Exception as e:
        logger.debug(f"[vision/OCR] 실패: {e}")
        return None


def _rescale(pt: Optional[dict], transform: dict) -> Optional[dict]:
    if pt is None:
        return None
    px_x, px_y = float(pt.get("x_px", 0)), float(pt.get("y_px", 0))
    pt_per_px = 72.0 / transform["render_dpi"]

    if transform.get("range_x", 0) <= 0 or transform.get("range_y", 0) <= 0:
        return None

    t = transform["type"]
    if t == "vector_clip":
        doc_x = transform["clip_x0_pt"] + px_x * pt_per_px
        doc_y = transform["clip_y0_pt"] + px_y * pt_per_px
        norm_x = (doc_x - transform["poly_offset_x"]) / transform["range_x"] * 1200
        norm_y = (doc_y - transform["poly_offset_y"]) / transform["range_y"] * 900
    elif t == "vision_bbox":
        norm_x = (px_x * pt_per_px - transform["offset_x"]) / transform["range_x"] * 1200
        norm_y = (px_y * pt_per_px - transform["offset_y"]) / transform["range_y"] * 900
    elif t in ("vector", "full_page"):
        doc_x = px_x * pt_per_px
        doc_y = px_y * pt_per_px
        norm_x = (doc_x - transform["offset_x"]) / transform["range_x"] * 1200
        norm_y = (doc_y - transform["offset_y"]) / transform["range_y"] * 900
    else:
        norm_x = (px_x - transform["offset_x"]) / transform["range_x"] * 1200
        norm_y = (px_y - transform["offset_y"]) / transform["range_y"] * 900

    return {**pt, "x_px": round(norm_x), "y_px": round(norm_y)}
