"""
PDF 파서 노드 — Shin PDF fitz 기반.

벡터 path >= 10: pymupdf path 직접 파싱 (CAD PDF)
벡터 path < 10: OpenCV contour fallback (스캔 PDF)
1200x900 정규화. Vision용 이미지 렌더링.
"""
import re
import math
import logging
from typing import Optional

import fitz
import cv2
import numpy as np
from shapely.geometry import Polygon as ShapelyPoly, MultiPolygon as ShapelyMP, LineString
from shapely.ops import polygonize, unary_union, snap
from shapely.validation import make_valid

from app.state import LargeState
from app.utils import calculate_parse_confidence

logger = logging.getLogger(__name__)

TARGET_W, TARGET_H = 1200, 900


# ── LangGraph 노드 함수 ───────────────────────────────────────────────────

def run(state: LargeState) -> LargeState:
    """PDF 파일 파싱 → floor_polygon_px + scale + Vision 이미지."""
    pdf_bytes = state["file_bytes"]
    result = _parse_cad_pdf(pdf_bytes)

    inner_walls = []
    if result["is_vector"] and result["floor_polygon_px"]:
        inner_walls = result.get("inner_walls", [])

    return {
        "floor_polygon_px": result["floor_polygon_px"],
        "scale_mm_per_px": result["scale_mm_per_px"],
        "scale_confirmed": result["scale_confirmed"],
        "parse_confidence": calculate_parse_confidence(
            "pdf_vector" if result["is_vector"] else "pdf_raster",
            "direct" if result["scale_confirmed"] else "default",
        ),
        "detected_width_mm": result.get("detected_width_mm"),
        "detected_height_mm": result.get("detected_height_mm"),
        "ceiling_height_mm": result.get("ceiling_height_mm"),
        "is_vector": result["is_vector"],
        "image_bytes": result["image_bytes"],
        "vision_transform": result["vision_transform"],
        "entrance": None,
        "entrances": [],
        "inner_walls": inner_walls,
        "inaccessible_rooms": [],
        "sprinklers": [],
        "fire_hydrants": [],
        "electrical_panels": [],
    }


# ── 내부 구현 ─────────────────────────────────────────────────────────────

def _extract_ceiling_height_from_pdf(doc) -> Optional[float]:
    """다중 페이지 PDF에서 단면도 페이지를 찾아 층고(2100~6000mm) 추출.

    페이지 텍스트에 "단면/section" 키워드가 있으면 단면도 페이지로 간주.
    거기서 4자리 숫자 중 2100~6000mm 범위 값을 추출, 가장 많이 등장하는 값 반환.
    2100mm 하한은 상업공간 건축법 최소 층고 기준 (이하는 가구 치수 오탐 가능성).
    감지 실패 시 None 반환 (에러 없음).
    """
    from collections import Counter
    SECTION_KEYWORDS = re.compile(r'단면|section|s-\d|층고', re.IGNORECASE)
    HEIGHT_PATTERN = re.compile(r'\b(\d{4})\b')

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        if not SECTION_KEYWORDS.search(text):
            continue
        candidates = []
        for m in HEIGHT_PATTERN.findall(text):
            val = float(m)
            if 2100 <= val <= 6000:  # 상업공간 건축법 최소 층고 2100mm 기준
                candidates.append(val)
        if candidates:
            result = Counter(candidates).most_common(1)[0][0]
            logger.info(f"[parser] 층고 감지: {result}mm (페이지={page_num + 1}, 후보={candidates})")
            return result

    logger.info("[parser] 단면도 페이지에서 층고 감지 실패")
    return None


def _parse_cad_pdf(pdf_bytes: bytes) -> dict:
    """CAD PDF → floor_polygon_px + scale + Vision 이미지."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    render_dpi = 150.0
    mat_full = fitz.Matrix(render_dpi / 72, render_dpi / 72)

    drawings = page.get_drawings()
    logger.info(f"[parser] 벡터 path 수: {len(drawings)}")

    ceiling_height = _extract_ceiling_height_from_pdf(doc)

    result = {
        "floor_polygon_px": None,
        "scale_mm_per_px": None,
        "scale_confirmed": False,
        "ceiling_height_mm": ceiling_height,
        "is_vector": False,
        "image_bytes": None,
        "vision_transform": None,
    }

    if len(drawings) >= 10:
        result["is_vector"] = True
        ret = _extract_polygon_from_paths(page, drawings)

        if ret:
            polygon, bbox = ret
            result["floor_polygon_px"] = polygon
            min_x, min_y, range_x, range_y = bbox

            # ── 스케일: 벡터 pt 좌표 → mm 직접 변환 ──
            # CAD PDF는 도면 좌표가 그대로 pt에 들어있음
            # polygon의 실제 mm 크기 = range_pt × (실제mm / pt비율)
            # 하지만 CAD PDF는 1:1이 아님 — 도면 좌표계가 mm 단위로 작성되어 있으면
            # pt 좌표값 자체가 mm를 반영함 (AutoCAD → PDF 변환 시)
            #
            # 핵심: 1200x900 정규화 좌표와 실제 mm의 비율만 구하면 됨
            # range_x(pt) = 도면 가로 폭의 pt값
            # 이 pt값이 실제로 몇 mm인지는 도면 텍스트에서 치수를 읽어서 결정

            # 텍스트에서 치수(mm) 읽기
            text_scale = _extract_scale_from_text(page)
            if text_scale:
                # height_mm 가 텍스트에서 직접 잡혔으면 우선. 아니면 단일 scale × TARGET_H fallback.
                # 독립 스케일링이라 height_mm 미확정 시 scale × TARGET_H 는 비율 어긋난 도면에서 부정확.
                w_mm = text_scale["width_mm"]
                h_mm = text_scale["height_mm"] if text_scale["height_mm"] else text_scale["scale"] * TARGET_H
                result["scale_mm_per_px"] = text_scale["scale"]
                result["scale_confirmed"] = True
                result["detected_width_mm"] = w_mm
                result["detected_height_mm"] = h_mm
                logger.info(f"[parser] 스케일(치수 텍스트): {text_scale['scale']:.2f} mm/px, "
                            f"실제 크기={w_mm:.0f}x{h_mm:.0f}mm")
            else:
                # 텍스트 치수 없으면: pt 좌표를 mm로 직접 사용
                # AutoCAD에서 mm 단위로 작업 → PDF 내보내기 시 1unit = 1pt가 아닌
                # 스케일 팩터 적용됨. 일반적으로 도면 좌표 = mm 값 그대로인 경우가 많음.
                # range_x_pt가 수백~수천이면 mm 단위 도면일 가능성 높음
                if range_x > 1000 or range_y > 1000:
                    # pt 값이 큼 → mm 단위 도면으로 간주
                    real_w_mm = range_x
                    real_h_mm = range_y
                else:
                    # pt 값이 작음 → m 단위 도면으로 간주 (×1000)
                    real_w_mm = range_x * 1000
                    real_h_mm = range_y * 1000

                scale = max(real_w_mm / TARGET_W, real_h_mm / TARGET_H)
                result["scale_mm_per_px"] = scale
                result["scale_confirmed"] = True
                result["detected_width_mm"] = real_w_mm
                result["detected_height_mm"] = real_h_mm
                logger.info(f"[parser] 스케일(벡터 직접): range={range_x:.0f}x{range_y:.0f}pt → "
                            f"{real_w_mm:.0f}x{real_h_mm:.0f}mm → {scale:.2f} mm/px")

            # 크롭 렌더링 (Vision 품질 향상)
            PAD_PT = 60
            clip = fitz.Rect(
                min_x - PAD_PT, min_y - PAD_PT,
                min_x + range_x + PAD_PT, min_y + range_y + PAD_PT,
            )
            pix = page.get_pixmap(matrix=mat_full, clip=clip)
            result["image_bytes"] = pix.tobytes("png")
            result["vision_transform"] = {
                "type": "vector_clip",
                "clip_x0_pt": float(clip.x0),
                "clip_y0_pt": float(clip.y0),
                "poly_offset_x": min_x,
                "poly_offset_y": min_y,
                "range_x": range_x,
                "range_y": range_y,
                "render_dpi": render_dpi,
            }
        else:
            pix = page.get_pixmap(matrix=mat_full)
            result["image_bytes"] = pix.tobytes("png")
            result["vision_transform"] = {
                "type": "full_page",
                "offset_x": 0, "offset_y": 0,
                "range_x": float(page.rect.width),
                "range_y": float(page.rect.height),
                "render_dpi": render_dpi,
            }

            # 벡터 실패한 경우만 텍스트 스케일 시도
            scale_info = _extract_scale_from_text(page)
            if scale_info:
                result["scale_mm_per_px"] = scale_info["scale"]
                result["scale_confirmed"] = True
    else:
        # OpenCV fallback
        pix = page.get_pixmap(matrix=mat_full)
        result["image_bytes"] = pix.tobytes("png")

        nparr = np.frombuffer(result["image_bytes"], np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        img_h, img_w = img.shape[:2]

        polygon = _extract_polygon_opencv(img)
        if polygon:
            result["floor_polygon_px"] = polygon
        result["vision_transform"] = {
            "type": "image",
            "offset_x": 0.0, "offset_y": 0.0,
            "range_x": float(img_w), "range_y": float(img_h),
            "render_dpi": render_dpi,
        }

    doc.close()
    return result


def _extract_polygon_from_paths(page, drawings) -> Optional[tuple]:
    """벡터 path → Shapely polygonize → 최대 면적 polygon → 1200x900."""
    page_area = page.rect.width * page.rect.height

    all_lines = []
    for d in drawings:
        line_width = d.get("width") or 1.0
        if line_width < 1.0:
            continue
        for item in d.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                all_lines.append(LineString([(p1.x, p1.y), (p2.x, p2.y)]))
            elif item[0] == "re":
                r = item[1]
                all_lines.append(LineString([
                    (r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)
                ]))
            elif item[0] == "qu":
                q = item[1]
                if hasattr(q, "ul"):
                    pts = [q.ul, q.ur, q.lr, q.ll, q.ul]
                    all_lines.append(LineString([(p.x, p.y) for p in pts]))
            elif item[0] == "c":
                if len(item) >= 5:
                    p1, p4 = item[1], item[4]
                    all_lines.append(LineString([(p1.x, p1.y), (p4.x, p4.y)]))

    if not all_lines:
        return None

    try:
        merged = unary_union(all_lines)
        merged = snap(merged, merged, 1.0)
        polys = list(polygonize(merged))
        if polys:
            biggest = max(polys, key=lambda p: p.area)
            if biggest.area > page_area * 0.03:
                if not biggest.is_valid:
                    biggest = make_valid(biggest)
                if isinstance(biggest, ShapelyMP):
                    biggest = max(biggest.geoms, key=lambda g: g.area)
                # 2026-05-04 — 같은 직선상 잉여 vertex 제거 (직사각형 8점 → 4점 정리).
                # 외곽선이 dead_zone 모서리와 만나면서 생긴 colinear vertex + 작은 노이즈 cut.
                # tolerance 2.0pt (≈0.7mm) 로 colinear 정리 + 작은 들쑥날쑥 제거.
                biggest = biggest.simplify(2.0, preserve_topology=True)
                if isinstance(biggest, ShapelyMP):
                    biggest = max(biggest.geoms, key=lambda g: g.area)
                coords = list(biggest.exterior.coords)[:-1]

                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                range_x = max_x - min_x or 1
                range_y = max_y - min_y or 1

                # 2026-05-04 — 독립 스케일링 (small mirror). 비율 유지는 직사각형에서만 정확하고
                # 십자형 등 비정사각형 도면에서 폴리곤 일부 외곽 누락 발생. small 의 독립 스케일링이 정합.
                norm = [
                    [round((c[0] - min_x) / range_x * TARGET_W),
                     round((c[1] - min_y) / range_y * TARGET_H)]
                    for c in coords
                ]
                logger.info(f"[parser] polygonize 성공: {len(norm)}점")
                return norm, (min_x, min_y, range_x, range_y)
    except Exception as e:
        logger.warning(f"[parser] polygonize 실패: {e}")

    return None


def _extract_polygon_opencv(image: np.ndarray) -> Optional[list]:
    """OpenCV contour → 최대 polygon → 1200x900."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(binary, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    img_area = image.shape[0] * image.shape[1]
    valid = [c for c in contours if cv2.contourArea(c) > img_area * 0.05]
    if not valid:
        return None

    largest = max(valid, key=cv2.contourArea)
    epsilon = 0.02 * cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, epsilon, True).squeeze()

    if approx.ndim != 2 or len(approx) < 3:
        return None

    h, w = image.shape[:2]
    return [
        [round(float(p[0]) / w * TARGET_W), round(float(p[1]) / h * TARGET_H)]
        for p in approx
    ]


def _extract_scale_from_text(page) -> Optional[dict]:
    """PDF 텍스트 치수선 → {"scale", "width_mm", "height_mm"}.

    전략 (우선순위 순):
    0. W×H 패턴 직접 매칭 (예: "SIZE 15m x 10m", "15000 x 10000", "15m × 10m") → width_mm, height_mm 둘 다 확정
    1. 단위 동반 숫자 (12000mm, 12m, 1200cm) — height 미확정
    2. 순수 숫자 3~6자리 (mm 가정) — height 미확정

    독립 스케일링 캔버스에선 width / height 가 다른 비율로 늘어나기 때문에
    height_mm 따로 추출 못하면 detected_height_mm 이 부정확. 옛 코드 = `scale * 900` 으로 추정 → 비율 어긋난 도면에서 12% 오차.
    """
    text = page.get_text()

    # ── 전략 0: W×H 패턴 (우선) ─────────────────────────────────────────
    # 매칭 예시:
    #   "SIZE 15m x 10m (150sqm)"
    #   "15m × 10m"
    #   "15000 x 10000"
    #   "15000mm × 10000mm"
    # 단위가 있으면 단위로, 없으면 숫자 크기로 m/mm 자동 판별.
    wh_pattern = re.compile(
        r"(\d{1,6}(?:\.\d+)?)\s*(mm|cm|m)?\s*[x×*X]\s*(\d{1,6}(?:\.\d+)?)\s*(mm|cm|m)?",
        re.IGNORECASE,
    )
    for m in wh_pattern.finditer(text):
        w_raw = float(m.group(1))
        w_unit = (m.group(2) or "").lower()
        h_raw = float(m.group(3))
        h_unit = (m.group(4) or "").lower()

        def _to_mm(val: float, unit: str) -> Optional[float]:
            if unit == "mm":
                return val
            if unit == "cm":
                return val * 10
            if unit == "m":
                return val * 1000
            # 단위 없음: 크기로 추정
            if val < 200:
                return val * 1000  # m 단위로 추정
            if val >= 1000:
                return val  # mm 단위로 추정
            return None

        w_mm = _to_mm(w_raw, w_unit)
        h_mm = _to_mm(h_raw, h_unit)
        if w_mm and h_mm and 2000 <= w_mm <= 100000 and 2000 <= h_mm <= 100000:
            scale = w_mm / TARGET_W
            logger.info(
                f"[parser] scale (W×H 직접): {w_mm:.0f} × {h_mm:.0f} mm "
                f"→ scale={scale:.2f} mm/px"
            )
            return {"scale": scale, "width_mm": w_mm, "height_mm": h_mm}

    # ── 전략 1: 단위 동반 숫자 ──────────────────────────────────────────
    unit_pattern = re.compile(r"(\d{1,6})\s*(mm|cm|m)\b")
    mm_values = []
    for m in unit_pattern.finditer(text):
        val = int(m.group(1))
        unit = m.group(2)
        if unit == "m" and val < 200:
            val *= 1000
        elif unit == "cm":
            val *= 10
        if 2000 <= val <= 100000:
            mm_values.append(val)

    # ── 전략 2: 순수 숫자 (3~6자리, mm 가정) ─────────────────────────────
    blocks = page.get_text("blocks")
    for b in blocks:
        block_text = b[4].strip()
        for token in re.split(r"[\s,\n]+", block_text):
            token = token.strip()
            if re.fullmatch(r"\d{3,6}", token):
                val = int(token)
                if 2000 <= val <= 100000:
                    mm_values.append(val)

    if not mm_values:
        return None

    max_num = max(mm_values)
    scale = max_num / TARGET_W
    logger.info(f"[parser] scale: {max_num}mm / {TARGET_W}px = {scale:.2f} mm/px (height 미확정)")
    return {"scale": scale, "width_mm": float(max_num), "height_mm": None}



def _infer_entrance_from_polygon(polygon_px: list) -> Optional[dict]:
    """벡터 polygon에서 입구 위치 추론.

    전략: polygon 하단 변(y가 가장 큰 변)의 중점을 입구로 추정.
    한국 CAD 도면에서 입구는 보통 하단(남쪽) 또는 좌측에 위치.
    가장 긴 하단 edge의 중점을 선택.
    """
    if not polygon_px or len(polygon_px) < 3:
        return None

    pts = polygon_px
    # y가 가장 큰(하단) 점 찾기
    max_y = max(p[1] for p in pts)
    min_y = min(p[1] for p in pts)
    y_range = max_y - min_y
    if y_range == 0:
        return None

    # 하단 20% 범위의 edge 중 가장 긴 것
    bottom_threshold = max_y - y_range * 0.2
    best_edge = None
    best_len = 0

    for i in range(len(pts)):
        p1 = pts[i]
        p2 = pts[(i + 1) % len(pts)]
        # 둘 다 하단 근처인 edge
        if p1[1] >= bottom_threshold and p2[1] >= bottom_threshold:
            edge_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if edge_len > best_len:
                best_len = edge_len
                best_edge = (p1, p2)

    if best_edge:
        mx = round((best_edge[0][0] + best_edge[1][0]) / 2)
        my = round((best_edge[0][1] + best_edge[1][1]) / 2)
        logger.info(f"[parser] 입구 추론: ({mx}, {my}) — 하단 edge 중점")
        return {"x_px": mx, "y_px": my, "confidence": "medium"}

    # fallback: 하단 중앙
    xs = [p[0] for p in pts]
    mx = round((min(xs) + max(xs)) / 2)
    logger.info(f"[parser] 입구 fallback: ({mx}, {max_y})")
    return {"x_px": mx, "y_px": round(max_y), "confidence": "low"}
