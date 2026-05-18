"""
이미지 전용 파서 노드 — 고도화 버전 (2026-04-24)

PNG/JPG 입력 → 도면 윤곽 + 치수 + 설비 추출.

파이프라인:
  ① Morphological ops + Hough Line Transform → 벽선 기반 polygon 추출
  ② PaddleOCR → 치수선 숫자 읽기 → scale 계산
  ③ Claude Vision → 입구 / 스프링클러 등 설비 감지 + floor_polygon_px fallback
  ④ polygon + scale 보정 → 실제 모양 + 올바른 크기

fallback 우선순위:
  polygon: Hough → OpenCV → Vision floor_polygon_px
  scale:   PaddleOCR → Vision 치수선 → 기본값(10.0)
"""
import base64
import json
import os
import re
import logging

import cv2
import numpy as np
from anthropic import Anthropic

from app.state import LargeState
from app.token_tracker import track_usage
from app.utils import calculate_parse_confidence

logger = logging.getLogger(__name__)

# ── PaddleOCR 지연 초기화 ─────────────────────────────────────────────────
# 첫 호출 시 한 번만 로드. 미설치·로드 실패 시 None 반환 → Vision fallback.
_paddle_ocr = None


def _get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
            logger.info("[parser_image] PaddleOCR 초기화 완료")
        except Exception as e:
            logger.warning("[parser_image] PaddleOCR 사용 불가: %s — Vision fallback 사용", e)
    return _paddle_ocr


VISION_PROMPT = """당신은 건축 평면도 분석 전문가입니다.
아래 도면 이미지에서 항목들을 감지하여 아래 JSON 형식만 출력하세요.

{
  "floor_polygon_px": [[x1,y1],[x2,y2],...],
  "dimensions": [
    {"value_mm": 12000, "start_px": [x1,y1], "end_px": [x2,y2], "direction": "horizontal"},
    {"value_mm": 8000, "start_px": null, "end_px": null, "direction": "unknown"}
  ],
  "entrances": [
    {"x_px": 1400, "y_px": 1052, "confidence": "high", "is_main": true, "type": "MAIN_DOOR"}
  ],
  "sprinklers": [{"x_px": 200, "y_px": 150, "confidence": "high"}],
  "fire_hydrant": [],
  "electrical_panel": [],
  "inner_walls": [{"start_px": [x1,y1], "end_px": [x2,y2], "confidence": "high"}],
  "inaccessible_rooms": [{"polygon_px": [[x1,y1],...], "confidence": "high"}]
}

## 규칙
- floor_polygon_px: 건물 외벽의 가장 큰 닫힌 다각형. 직사각형이 아닌 경우(L자, 뾰족한 형태, ㄷ자 등) 실제 모양대로 꼭짓점을 최대한 정확하게 추출하세요. 최소 4개 꼭짓점.
- dimensions: 이미지에서 보이는 모든 치수 정보를 mm 단위로 추출하세요. cm→×10, m→×1000.
  · 치수선(화살표 양 끝에 숫자): start_px, end_px, direction("horizontal"/"vertical") 포함
  · 도면 옆에 텍스트로만 적힌 치수 (예: "12m", "20,000", "15000", "180m²" 제외): start_px=null, end_px=null, direction="unknown"
  · 콤마 포함 숫자(20,000) → 20000으로 변환. 단위 없는 4~5자리 숫자(건축 도면)는 mm로 간주.
  · 넓이(㎡, m²) 값은 제외하고, 길이 치수만 포함.
- entrances: 모든 출입구. is_main=주출입구.
- 좌표는 이미지 픽셀 기준 (좌상단 0,0).
- JSON만 출력. 설명 텍스트 금지."""


def run(state: LargeState) -> LargeState:
    """이미지 파일 파싱 → floor_polygon_px + 설비 + scale."""
    image_bytes = state["file_bytes"]

    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지 디코딩 실패")

    img_h, img_w = img.shape[:2]

    # ① polygon 추출: Hough → OpenCV fallback
    hough_polygon = _extract_floor_polygon_hough(img)
    opencv_polygon = None
    if hough_polygon is None:
        logger.info("[parser_image] Hough polygon 실패 → OpenCV fallback")
        opencv_polygon = _extract_floor_polygon_opencv(img)

    # ② Vision 호출 (설비 감지 + floor_polygon_px fallback + 치수선)
    vision_bytes = _resize_for_vision(image_bytes)
    vision_result = _call_vision(vision_bytes)

    # ③ polygon 최종 결정: Hough → OpenCV → Vision floor_polygon_px
    vision_polygon = vision_result.get("floor_polygon_px") or []
    if hough_polygon and len(hough_polygon) >= 3:
        floor_polygon = hough_polygon
        polygon_source = "hough"
    elif opencv_polygon and len(opencv_polygon) >= 3:
        floor_polygon = opencv_polygon
        polygon_source = "opencv"
    elif len(vision_polygon) >= 3:
        floor_polygon = [(float(p[0]), float(p[1])) for p in vision_polygon]
        polygon_source = "vision"
    else:
        raise ValueError("도면 polygon 추출 실패")

    # ④ scale 계산: PaddleOCR → Vision 치수선 → 기본값
    width_mm, height_mm = _extract_dims_paddle(image_bytes)
    scale_source = "paddle"

    if width_mm is None and height_mm is None:
        width_mm, height_mm = _extract_building_dims(vision_result.get("dimensions", []))
        scale_source = "vision" if (width_mm or height_mm) else "default"

    scale = _calc_scale(floor_polygon, width_mm, height_mm)

    logger.info(
        "[parser_image] polygon=%s(%dpts) scale=%.2f(%s) dims=%sx%smm",
        polygon_source, len(floor_polygon), scale, scale_source,
        width_mm, height_mm,
    )

    # ⑤ 입구 처리
    entrances = [e for e in vision_result.get("entrances", []) if e]
    entrance = next((e for e in entrances if e.get("is_main")), None)
    if not entrance and entrances:
        entrance = entrances[0]

    return {
        "floor_polygon_px": floor_polygon,
        "scale_mm_per_px": scale,
        "scale_confirmed": scale_source != "default",
        "parse_confidence": calculate_parse_confidence(polygon_source, scale_source),
        "is_vector": False,
        "image_bytes": image_bytes,
        "vision_transform": {
            "type": "image",
            "offset_x": 0.0,
            "offset_y": 0.0,
            "range_x": float(img_w),
            "range_y": float(img_h),
            "render_dpi": 150.0,
        },
        "entrance": entrance,
        "entrances": entrances,
        "inner_walls": vision_result.get("inner_walls", []),
        "inaccessible_rooms": vision_result.get("inaccessible_rooms", []),
        "sprinklers": vision_result.get("sprinklers", []),
        "fire_hydrants": vision_result.get("fire_hydrant", []),
        "electrical_panels": vision_result.get("electrical_panel", []),
    }


# ── ① Hough Line Transform 기반 polygon 추출 ──────────────────────────────

def _extract_floor_polygon_hough(img: np.ndarray) -> list[tuple[float, float]] | None:
    """Morphological ops + Hough Lines → 벽선 마스크 → polygon."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Morphological closing — 끊어진 벽선 연결
    kernel = np.ones((5, 5), np.uint8)
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)

    # Otsu's thresholding — 이미지별 최적 이진화
    _, binary = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Canny edge
    edges = cv2.Canny(binary, 50, 150)

    # HoughLinesP — 이미지 단변의 5% 이상인 선만 벽선으로 인식
    min_len = min(h, w) * 0.05
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=50, minLineLength=min_len, maxLineGap=20,
    )

    if lines is None or len(lines) < 4:
        logger.info("[parser_image] Hough: 감지 선 부족 (%s개)", len(lines) if lines is not None else 0)
        return None

    # 감지된 벽선을 빈 마스크에 그리기
    mask = np.zeros((h, w), dtype=np.uint8)
    for line in lines:
        x1, y1, x2, y2 = line[0]
        cv2.line(mask, (x1, y1), (x2, y2), 255, 3)

    # 선 끝단 연결 (dilate)
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8), iterations=2)

    # 가장 큰 유효 윤곽 추출
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    image_area = h * w
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contour)
        if area < image_area * 0.03:
            continue
        epsilon = 0.02 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        if len(approx) >= 3:
            return [(float(pt[0][0]), float(pt[0][1])) for pt in approx]

    return None


# ── OpenCV fallback polygon 추출 ──────────────────────────────────────────

def _extract_floor_polygon_opencv(img: np.ndarray) -> list[tuple[float, float]]:
    """Canny + findContours 방식 (Hough 실패 시 fallback)."""
    h, w = img.shape[:2]
    image_area = h * w
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    dilated = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("바닥 polygon 추출 실패")

    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contour)
        if area > image_area * 0.85 or area < image_area * 0.05:
            continue
        epsilon = 0.01 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        return [(float(pt[0][0]), float(pt[0][1])) for pt in approx]

    largest = sorted(contours, key=cv2.contourArea, reverse=True)[0]
    epsilon = 0.01 * cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, epsilon, True)
    return [(float(pt[0][0]), float(pt[0][1])) for pt in approx]


# ── ② PaddleOCR 치수 추출 ─────────────────────────────────────────────────

def _extract_dims_paddle(image_bytes: bytes) -> tuple[float | None, float | None]:
    """PaddleOCR로 이미지에서 치수 텍스트 추출 → (width_mm, height_mm)."""
    ocr = _get_paddle_ocr()
    if ocr is None:
        return None, None

    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        return None, None

    try:
        result = ocr.ocr(img, cls=True)
    except Exception as e:
        logger.warning("[parser_image] PaddleOCR 실행 실패: %s", e)
        return None, None

    if not result or not result[0]:
        return None, None

    # 치수값을 bbox 방향(가로/세로)으로 분류
    h_dims: list[float] = []  # 가로로 긴 bbox에서 추출된 값 → width 후보
    v_dims: list[float] = []  # 세로로 긴 bbox에서 추출된 값 → height 후보

    for line in result[0]:
        bbox, (text, conf) = line
        if conf < 0.6:
            continue
        values = _parse_dim_text(text)
        if not values:
            continue

        pts = np.array(bbox)
        bw = float(pts[:, 0].max() - pts[:, 0].min())
        bh = float(pts[:, 1].max() - pts[:, 1].min())

        for val_mm in values:
            if not (300 <= val_mm <= 100_000):  # 0.3m ~ 100m 범위만 유효
                continue
            if bw >= bh:
                h_dims.append(val_mm)
            else:
                v_dims.append(val_mm)

    width_mm = max(h_dims) if h_dims else (max(v_dims) if v_dims else None)
    height_mm = max(v_dims) if v_dims else None

    logger.info("[parser_image] PaddleOCR dims: width=%smm height=%smm", width_mm, height_mm)
    return width_mm, height_mm


def _parse_dim_text(text: str) -> list[float]:
    """텍스트에서 mm 단위로 변환된 치수값 목록 추출."""
    text = text.replace(',', '').replace(' ', '').replace('_', '')
    results = []

    for m in re.finditer(r'(\d+(?:\.\d+)?)mm', text, re.IGNORECASE):
        results.append(float(m.group(1)))
    for m in re.finditer(r'(\d+(?:\.\d+)?)cm', text, re.IGNORECASE):
        results.append(float(m.group(1)) * 10)
    for m in re.finditer(r'(\d+(?:\.\d+)?)(?<![mc])m(?!m)', text, re.IGNORECASE):
        val = float(m.group(1)) * 1000
        if val <= 100_000:
            results.append(val)
    # 단위 없는 4~5자리 숫자 → mm로 간주 (건축 도면 관행)
    for m in re.finditer(r'\b(\d{4,5})\b', text):
        val = float(m.group(1))
        if 1000 <= val <= 30_000:
            results.append(val)

    return results


# ── scale 계산 ─────────────────────────────────────────────────────────────

def _calc_scale(
    polygon: list[tuple[float, float]],
    width_mm: float | None,
    height_mm: float | None,
) -> float:
    """polygon 픽셀 크기 + 치수(mm)로 scale_mm_per_px 계산."""
    if not polygon or (width_mm is None and height_mm is None):
        return 10.0

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    px_w = max(xs) - min(xs)
    px_h = max(ys) - min(ys)

    scales = []
    if width_mm and px_w > 10:
        scales.append(width_mm / px_w)
    if height_mm and px_h > 10:
        scales.append(height_mm / px_h)

    return sum(scales) / len(scales) if scales else 10.0


# ── Vision 치수선 fallback ─────────────────────────────────────────────────

def _extract_building_dims(dims: list[dict]) -> tuple[float | None, float | None]:
    """Vision 치수선 결과에서 가장 큰 가로/세로 치수 추출.
    direction이 명확하거나 start_px/end_px 좌표로 방향을 계산할 수 있는 것만 사용."""
    max_h, max_v = None, None

    for d in dims:
        try:
            val = float(d.get("value_mm", 0))
            if val <= 0:
                continue

            direction = d.get("direction", "unknown")
            start_px = d.get("start_px")
            end_px = d.get("end_px")

            if direction == "horizontal":
                if max_h is None or val > max_h:
                    max_h = val
            elif direction == "vertical":
                if max_v is None or val > max_v:
                    max_v = val
            elif start_px and end_px:
                # 좌표로 방향 판별
                sx, sy = start_px
                ex, ey = end_px
                if abs(ex - sx) > abs(ey - sy):
                    if max_h is None or val > max_h:
                        max_h = val
                else:
                    if max_v is None or val > max_v:
                        max_v = val
            # direction="unknown"이고 좌표도 없으면 스킵
        except (KeyError, TypeError, ValueError):
            continue

    return max_h, max_v


# ── Vision 호출 ────────────────────────────────────────────────────────────

def _call_vision(image_bytes: bytes) -> dict:
    """Claude Vision 호출 — 설비 감지 + floor_polygon_px."""
    media_type = "image/jpeg" if image_bytes[:2] == b'\xff\xd8' else "image/png"
    b64 = base64.standard_b64encode(image_bytes).decode()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    track_usage("parser_image.py", response)

    raw = response.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Vision 응답 파싱 실패: {raw[:200]}")

    return _parse_json_lenient(match.group())


def _parse_json_lenient(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r'//[^\n]*', '', raw)
    fixed = fixed.replace("'", '"')
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        raise ValueError(f"Vision JSON 복구 실패: {e}")


def _resize_for_vision(image_bytes: bytes, max_bytes: int = 4_500_000) -> bytes:
    """Vision API 5MB 제한 대응."""
    if len(image_bytes) <= max_bytes:
        return image_bytes
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes
    h, w = img.shape[:2]
    ratio = (max_bytes / len(image_bytes)) ** 0.5
    new_w, new_h = int(w * ratio), int(h * ratio)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()
