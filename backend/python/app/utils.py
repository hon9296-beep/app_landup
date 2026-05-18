"""
공통 유틸리티 — 모든 노드가 공유하는 함수.

노드끼리 직접 import하지 않고, 이 모듈만 import한다.
"""
import json
import logging
import math
import re
import uuid
from typing import Optional

from shapely.affinity import rotate as shapely_rotate
from shapely.geometry import LineString, Point, Polygon, box

logger = logging.getLogger(__name__)


# ── 오브젝트 표준 테이블 ─────────────────────────────────────────────────
# 전 노드가 참조하는 유일한 오브젝트 정의.
# key = 표준 ID (영문), aliases = LLM이 뱉을 수 있는 한글/영문 변형

OBJECT_STANDARDS: dict[str, dict] = {
    # 규격(w/d/h)은 VMD_BOUNDARIES(reference.py)로 일원화. 여기에는 넣지 않는다.
    # 색상은 프론트 레이어에서 object_type 기반 매핑. 배치 엔진(whitebox)에 불필요.
    #
    # ── family (선택 필드, 2026-04-22 S-8c-2) ──
    # 같은 기능을 수행하는 여러 object_type 을 하나의 그룹으로 묶어
    # _allocate_eligible 에서 합산 cap(FAMILY_CAPS) 적용. 잉여 기물 사전 차단용.
    # 미부여 obj_type 은 prefix fallback (_get_family) 또는 cap 미적용.
    "counter": {
        "name": "계산대",
        # [중요/회귀방지] 2026-04-20 이후 counter 통합 규칙.
        # pos_counter, gift_counter, money_counter, check_counter, cashier 등은 전부
        # counter의 alias로 취급. reference.py의 _normalize_placement_rules가 같은 std_id로
        # 매핑되는 rule들의 max_count를 합산하므로, LUMIA 같은 매뉴얼에 "counter" +
        # "gift_counter"가 각각 1개씩 들어오면 정규화 후 counter max_count=2가 되어야 한다.
        # 과거(A안 normalize 강화 이전, 2026-04-20 15:00 이전)에는 3단계 부분 매칭으로
        # "counter" in "gift_counter" 우연 매칭이 이 합산을 성사시켰으나, 오탐 방지 목적으로
        # 부분 매칭이 제거되면서 gift_counter 같은 변형이 정확/canonical 매칭에 걸리지 않아
        # counter max_count=1로 쪼개지는 회귀가 발생. 아래 aliases에 명시적으로 추가해 복구.
        # 참고: reports/AD/2026-04-20_normalize_partial_match_regression.md
        "aliases": [
            "계산대", "카운터", "캐시어",
            "pos_counter", "POS", "POS counter",
            "gift_counter", "gift counter",      # LUMIA 매뉴얼 등에서 선물 증정용 counter
            "money_counter", "money counter",    # 현금 응대 counter
            "check_counter", "check counter",    # 체크아웃 전용 counter
            "cashier",
        ],
        "priority": 95,
        # [2026-04-22 S-8f] single-type family. FAMILY_CAPS_SMALL["counter"]=1 과 연동.
        # 18평 counter 2개는 기하학적 허수 (separate 1200 + clearance 900/600).
        # LUMIA 매뉴얼 "counter+gift_counter" 합산 2 요구를 allocator 단계에서 1로 차단.
        "family": "counter",
    },
    "display_table": {
        "name": "진열대",
        "aliases": ["진열대", "전시 테이블", "테이블", "진열 테이블"],
        "priority": 90,
        "family": "display",
    },
    "display_table_standard": {
        "name": "진열대(표준형)",
        "aliases": ["표준 진열대", "display_table_standard", "표준 테이블"],
        "priority": 90,
        "family": "display",
    },
    "character_bbox": {
        "name": "캐릭터 조형물",
        "aliases": ["캐릭터", "캐릭터 입체물", "캐릭터 조형물", "캐릭터 조형", "character"],
        "priority": 80,
    },
    "photo_wall": {
        "name": "포토월",
        "aliases": ["포토월", "포토존 배경 월", "포토 배경", "photo wall", "배경 패널", "그래픽 월"],
        "priority": 85,
        "family": "photo",
    },
    "photo_island": {
        "name": "포토 아일랜드",
        "aliases": ["포토존", "포토 존", "photo zone", "photo island", "포토존 구조물", "360도 포토"],
        "priority": 85,
        "family": "photo",
    },
    "shelf_wall": {
        "name": "벽면 선반",
        "aliases": ["선반", "벽면 선반", "상품 선반", "진열 선반", "shelf", "벽선반"],
        "priority": 65,
        "family": "shelf",
    },
    "shelf_standard": {
        "name": "표준 선반",
        "aliases": ["표준 선반", "shelf_standard", "stand 선반"],
        "priority": 65,
        "family": "shelf",
    },
    "test_bar": {
        "name": "시연대",
        "aliases": ["시연대", "시연 바", "test_bar", "테스트 바", "체험 바"],
        "priority": 75,
    },
    "consultation_desk": {
        "name": "상담 데스크",
        "aliases": ["상담 데스크", "상담대", "consultation_desk", "컨설테이션 데스크"],
        "priority": 75,
        "family": "consultation",
    },
    "shelf_3tier": {
        "name": "3단 선반",
        "aliases": ["3단 선반", "3tier", "다단 선반"],
        "priority": 70,
        "family": "shelf",
    },
    "banner_stand": {
        "name": "배너",
        # "입간판"은 의미상 안내판(signage) — 2026-04-20 alias 충돌 정리로 signage_stand 전용
        "aliases": ["배너", "배너 스탠드", "banner", "사인"],
        "priority": 50,
    },
    # partition_wall (범용) 폐기 — flush+center_freestanding 모순. I/L만 사용.
    "partition_wall_I": {
        "name": "가벽(일자형)",
        "aliases": ["일자가벽", "백월", "백월가벽", "일자형가벽", "partition_I", "가벽", "파티션", "partition", "partition_wall"],
        "priority": 98,       # 공간 구조 — 기물 배치 전 선행
        "family": "partition",
    },
    "partition_wall_L": {
        "name": "가벽(ㄱ자형)",
        "aliases": ["ㄱ자가벽", "코너가벽", "간이창고", "ㄱ자형가벽", "partition_L"],
        "priority": 98,       # 공간 구조 — 기물 배치 전 선행
        "family": "partition",
    },
    "signage_stand": {
        "name": "안내판",
        "aliases": ["안내판", "A보드", "입간판", "사인보드", "signage"],
        "priority": 35,
    },
    "kiosk": {
        "name": "키오스크",
        "aliases": ["키오스크", "무인결제기", "웨이팅기기", "아이패드거치대"],
        "priority": 45,
    },
    # [2026-04-22 S-8f v4] aux_table — LUMIA 매뉴얼의 "포장대 보조 테이블".
    # 증정품 포장 등 보조 용도. brand_data 에만 존재했고 OBJECT_STANDARDS 미등록으로
    # normalize 에서 raw 통과되던 것 정식 등록.
    # wall_attachment/규격은 brand_data 에 포함된 값 사용 (vmd_constants 미등록).
    # family 미부여 — single-type 이고 brand 가 보통 1개만 요청.
    "aux_table": {
        "name": "포장대 보조 테이블",
        "aliases": ["포장대", "포장 테이블", "보조 테이블", "wrap_table", "packaging_table", "포장"],
        "priority": 55,  # banner_stand(50) 과 shelf_3tier(70) 사이, 보조 역할
    },
}

def _canonicalize(s: str) -> str:
    """문자열 정규화 — 대소문자/공백/하이픈/언더스코어 완전 제거.

    "POS Counter", "pos_counter", "pos-counter", "POSCounter" → "poscounter" 동일 처리.
    한국어 붙여쓰기 자유도 대응: "상담 데스크" / "상담데스크" 모두 "상담데스크"로 매칭.
    """
    if not isinstance(s, str):
        return ""
    return re.sub(r"[-_\s]+", "", s.strip()).lower()


# aliases → 표준 ID 역매핑 (정규화용)
# _ALIAS_MAP: 원문 그대로의 키 매핑 (정확 매칭 1단계)
# _CANONICAL_MAP: 전처리된 키 매핑 (canonical 매칭 2단계)
_ALIAS_MAP: dict[str, str] = {}
_CANONICAL_MAP: dict[str, str] = {}
_alias_conflicts: list[tuple[str, str, str]] = []

for _std_id, _std in OBJECT_STANDARDS.items():
    _candidates = [_std_id, _std["name"], *_std["aliases"]]
    for _alias in _candidates:
        _ALIAS_MAP[_alias] = _std_id
        _canon = _canonicalize(_alias)
        if _canon and _canon in _CANONICAL_MAP and _CANONICAL_MAP[_canon] != _std_id:
            _alias_conflicts.append((_canon, _CANONICAL_MAP[_canon], _std_id))
        elif _canon:
            _CANONICAL_MAP[_canon] = _std_id

for _canon, _first, _second in _alias_conflicts:
    logger.warning(
        f"[normalize] alias 충돌: '{_canon}' → '{_first}' vs '{_second}' "
        f"(먼저 등록된 '{_first}' 우선). OBJECT_STANDARDS 정리 필요."
    )


# 매칭 실패 input 집합 (개발 중 alias 보강 백로그)
_UNMATCHED_TYPES: set[str] = set()


def normalize_object_type(raw_type: str) -> str:
    """가변 오브젝트 이름 → OBJECT_STANDARDS 표준 ID.

    매칭 순서:
      1. 정확 매칭 (_ALIAS_MAP 원문 키)
      2. canonical 매칭 (소문자 + 공백/하이픈/언더스코어 통일)

    부분 문자열 매칭은 2026-04-20 제거됨 — false positive 유발 (예: alias "bar"가
    "barcode"에 오매칭). 실패 input은 _UNMATCHED_TYPES에 수집되고 logger.warning
    1회 발송. 누락 alias 확인 후 OBJECT_STANDARDS에 직접 추가.
    """
    if not raw_type:
        return raw_type
    if raw_type in _ALIAS_MAP:
        return _ALIAS_MAP[raw_type]
    canon = _canonicalize(raw_type)
    if canon in _CANONICAL_MAP:
        return _CANONICAL_MAP[canon]
    if raw_type not in _UNMATCHED_TYPES:
        _UNMATCHED_TYPES.add(raw_type)
        logger.warning(
            f"[normalize] unmatched object_type: '{raw_type}' — "
            f"OBJECT_STANDARDS alias 보강 필요"
        )
    return raw_type


def get_object_defaults(std_id: str) -> dict:
    """표준 ID → 기본 치수/우선순위 반환. 규격은 VMD_BOUNDARIES(constants.py)에서 조회."""
    from app.vmd_constants import VMD_BOUNDARIES
    std = OBJECT_STANDARDS.get(std_id)
    bounds = VMD_BOUNDARIES.get(std_id)
    name = std["name"] if std else std_id
    if bounds:
        return {
            "object_type": std_id,
            "name": name,
            "width_mm": bounds["width_mm"]["std"],
            "depth_mm": bounds["depth_mm"]["std"],
            "height_mm": bounds["height_mm"]["std"],
        }
    return {"object_type": std_id, "name": name, "width_mm": 800, "depth_mm": 600, "height_mm": 1200}


# ── 수학/기하 ─────────────────────────────────────────────────────────────

def frange(start: float, stop: float, step: float) -> list[float]:
    """float range 생성."""
    result = []
    v = start
    while v <= stop:
        result.append(v)
        v += step
    return result


def angle_deg(dx: float, dy: float) -> float:
    """(dx, dy) → 각도 (degree)."""
    return math.degrees(math.atan2(dy, dx))


def angle_diff(a: float, b: float) -> float:
    """두 각도의 최소 차이 (0~180)."""
    return abs(((a - b + 540) % 360) - 180)


# ── 방향 벡터 ─────────────────────────────────────────────────────────────

_NORMAL_MAP = {
    "north": (0.0, 1.0),
    "south": (0.0, -1.0),
    "east":  (1.0, 0.0),
    "west":  (-1.0, 0.0),
}


def normal_to_vector(normal: str) -> tuple[float, float]:
    """wall_normal 문자열 → 단위 벡터 (Y-up)."""
    return _NORMAL_MAP.get(normal, (0.0, 1.0))


def normal_label(nx_dir: float, ny_dir: float) -> str:
    """법선 벡터 → 방향 라벨."""
    if abs(nx_dir) > abs(ny_dir):
        return "east" if nx_dir > 0 else "west"
    return "north" if ny_dir > 0 else "south"


def wall_direction_name(dx: float, dy: float) -> str:
    """벽 방향 벡터 → 벽 이름."""
    if abs(dx) > abs(dy):
        return "south_wall" if dy >= 0 else "north_wall"
    return "east_wall" if dx >= 0 else "west_wall"


# ── Shapely 공통 ─────────────────────────────────────────────────────────

def make_rotated_rect(
    center: tuple[float, float],
    width: float,
    depth: float,
    angle_deg: float,
) -> Polygon:
    """중심 + width/depth + 회전각 → Shapely Polygon."""
    cx, cy = center
    rect = box(cx - width / 2, cy - depth / 2, cx + width / 2, cy + depth / 2)
    if angle_deg != 0:
        rect = shapely_rotate(rect, angle_deg, origin=(cx, cy))
    return rect


def floor_overlap_ratio(bbox: Polygon, floor_poly: Polygon) -> float:
    """bbox가 floor_poly 안에 몇 % 들어가는지."""
    if bbox.area <= 0:
        return 0.0
    return floor_poly.intersection(bbox).area / bbox.area


def point_in_any_obstacle(pt: Point, obstacles: list) -> bool:
    """점이 장애물 목록 중 하나에 포함되는지."""
    return any(dz.contains(pt) for dz in obstacles)


def point_near_any(pt: Point, ref_points: list, radius: float) -> bool:
    """점이 기준점 목록 중 하나의 반경 안에 있는지."""
    return any(rp.distance(pt) < radius for rp in ref_points)


# ── 좌표 변환 ─────────────────────────────────────────────────────────────

def px_to_mm(coords: list, scale: float) -> list[tuple[float, float]]:
    """[[x_px, y_px], ...] → [(x_mm, y_mm), ...]."""
    return [(p[0] * scale, p[1] * scale) for p in coords]


def px_point_to_mm(pt: dict, scale: float) -> tuple[float, float]:
    """{"x_px": ..., "y_px": ...} → (x_mm, y_mm)."""
    return (pt["x_px"] * scale, pt["y_px"] * scale)


# ── LLM JSON 파싱 ────────────────────────────────────────────────────────

def parse_llm_json(text: str) -> dict:
    """Claude 응답에서 JSON 블록 추출. trailing comma 등 깨진 JSON 자동 복구."""
    # 1차: ```json ... ``` 블록
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return json.loads(_fix_json(m.group(1)))
    # 2차: { ... } 추출
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return json.loads(_fix_json(m.group(0)))
    raise ValueError("JSON 파싱 실패")


def _fix_json(text: str) -> str:
    """깨진 JSON 복구: trailing comma, 주석 제거."""
    text = re.sub(r"//.*?\n", "\n", text)           # // 주석 제거
    text = re.sub(r",\s*([}\]])", r"\1", text)      # trailing comma 제거
    text = re.sub(r"'", '"', text)                   # 작은따옴표 → 큰따옴표
    return text


def parse_llm_json_list(text: str) -> list:
    """Claude 응답에서 JSON 배열 추출."""
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = m.group(1) if m else text
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return data.get("placements", data.get("intents", []))
    except json.JSONDecodeError:
        m2 = re.search(r"\[.*\]", text, re.DOTALL)
        if m2:
            return json.loads(m2.group(0))
    return []


# ── alignment 각도 계산 ──────────────────────────────────────────────────

def alignment_to_angle(alignment: str, wall_angle_deg: float, code_angle: float) -> float:
    """alignment Enum + 벽 각도 → 최종 회전각."""
    if alignment == "none":
        return code_angle
    if alignment == "parallel":
        candidates = [wall_angle_deg % 360, (wall_angle_deg + 180) % 360]
    elif alignment == "perpendicular":
        candidates = [(wall_angle_deg + 90) % 360, (wall_angle_deg + 270) % 360]
    elif alignment == "opposite":
        return (wall_angle_deg + 180) % 360
    else:
        candidates = [wall_angle_deg % 360, (wall_angle_deg + 180) % 360]
    return min(candidates, key=lambda c: angle_diff(code_angle, c))


# ── 배치 좌표 계산 ─────────────────────────────────────────────────────

STAFF_CLEARANCE_MM = 600  # counter 후면 스태프 작업 공간 (near 전용, 18평 기준 600mm)


def calculate_position(slot, obj, direction, alignment, usable_poly, structural_dead_zones=None):
    """slot + obj → 중심 좌표 + bbox polygon 계산."""
    width, depth = obj["width_mm"], obj["depth_mm"]
    # front_edge="depth"면 depth 면이 앞면 → width/depth swap하여 depth 면을 벽과 평행하게
    if obj.get("front_edge") == "depth":
        width, depth = depth, width
    wall_attachment = obj.get("wall_attachment", "free")

    front_vec = None
    if direction in ("wall_facing", "outward"):
        center, code_angle, front_vec = _wall_facing(slot, depth, wall_attachment)
    elif direction == "inward":
        center, code_angle = _inward(slot, usable_poly)
    elif direction in ("center", "freestanding"):
        center, code_angle = _center(slot, usable_poly)
    elif direction == "focal":
        center, code_angle = _center(slot, usable_poly)
    else:
        center, code_angle = _center(slot, usable_poly)

    if direction in ("wall_facing", "outward") and slot.get("wall_linestring"):
        # 벽 LineString 기반 — _wall_facing에서 벽 방향 법선으로 정확한 각도 산출
        # 스냅 불필요. 벽에 평행하게 자동 정렬됨
        final_angle = code_angle
    else:
        # 벽 LineString 없거나 center/inward — 기존 alignment + 스냅
        wall_angle = slot.get("wall_angle_deg")
        if wall_angle is not None:
            final_angle = alignment_to_angle(alignment, wall_angle, code_angle)
            # 벽 기준 90도 스냅
            candidates = [(wall_angle + offset) % 360 for offset in (0, 90, 180, 270)]
            final_angle = min(candidates, key=lambda c: min(abs(final_angle - c), 360 - abs(final_angle - c)))
        else:
            final_angle = code_angle
            final_angle = round(final_angle / 90) * 90

    bbox = make_rotated_rect(center, width, depth, final_angle)

    # _nudge_inside — 대각선 벽 근처 bbox 모서리 보정 (1000mm 제한으로 과도한 이동 방지)
    if usable_poly and not usable_poly.contains(bbox):
        center, bbox = _nudge_inside(center, bbox, usable_poly, width, depth, final_angle)

    # front_vec 없으면 (center/inward) — 입구 방향 지향, 입구 없으면 final_angle에서 계산
    if front_vec is None or (front_vec[0] == 0 and front_vec[1] == 0):
        entrance_mm = slot.get("_entrance_mm")
        cx_tmp, cy_tmp = center
        if entrance_mm:
            # 입구 방향 벡터 (오브젝트 → 입구)
            ex, ey = entrance_mm[0] - cx_tmp, entrance_mm[1] - cy_tmp
            ed = math.hypot(ex, ey)
            if ed > 1:
                front_vec = (ex / ed, ey / ed)
                # front_vec에서 역산한 angle
                final_angle = math.degrees(math.atan2(front_vec[0], front_vec[1])) % 360
                final_angle = round(final_angle / 90) * 90  # 90° 스냅
                rad = math.radians(final_angle)
                front_vec = (math.sin(rad), math.cos(rad))
                bbox = make_rotated_rect(center, width, depth, final_angle)
        if front_vec is None or (front_vec[0] == 0 and front_vec[1] == 0):
            rad = math.radians(final_angle)
            front_vec = (math.sin(rad), math.cos(rad))

    # 구조물 dead zone 향하면 front 180° 반전 — free/center/inward 기물만 적용
    # wall_facing 기물은 _wall_facing에서 바닥 중심 기준으로 이미 올바른 방향이므로 건드리지 않음
    if front_vec and direction not in ("wall_facing", "outward"):
        cx, cy = center

        # 구조물 dead zone (pillar/toilet/stair) — 정면에 구조물이 있으면 반전
        if structural_dead_zones:
            for dz_entry in structural_dead_zones:
                dz = dz_entry["poly"] if isinstance(dz_entry, dict) else dz_entry
                if not hasattr(dz, 'centroid'):
                    continue
                dist = dz.distance(Point(cx, cy))
                if dist > 1500:
                    continue
                dx = dz.centroid.x - cx
                dy = dz.centroid.y - cy
                d = math.hypot(dx, dy)
                if d < 1:
                    continue
                dot = front_vec[0] * (dx / d) + front_vec[1] * (dy / d)
                if dot > 0.3:
                    front_vec = (-front_vec[0], -front_vec[1])
                    final_angle = (final_angle + 180) % 360
                    break

        bbox = make_rotated_rect(center, width, depth, final_angle)

    return {
        "center_x_mm": round(center[0], 1),
        "center_y_mm": round(center[1], 1),
        "rotation_deg": round(final_angle, 1),
        "bbox_polygon": bbox,
        "width_mm": width,
        "depth_mm": depth,
        "object_type": obj["object_type"],
        "front_vec": front_vec,
    }


def _nudge_inside(center, bbox, usable_poly, width, depth, angle, max_iter=5):
    """bbox가 polygon 밖으로 나가면 안쪽으로 밀어넣기.

    밖에 나간 꼭짓점 → polygon 경계까지 최대 이동량 계산 → center 이동 → bbox 재생성.
    최대 5회 반복. 원래 위치에서 너무 멀어지면 중단.
    """
    origin = center
    for _ in range(max_iter):
        if usable_poly.contains(bbox):
            break
        # 원래 위치에서 너무 멀어지면 중단 (의도와 다른 위치 방지)
        if math.hypot(center[0] - origin[0], center[1] - origin[1]) > 1000:
            break
        # bbox 꼭짓점 중 polygon 밖에 있는 점
        outside_pts = [p for p in bbox.exterior.coords[:-1]
                       if not usable_poly.contains(Point(p))]
        if not outside_pts:
            break
        # 가장 많이 벗어난 점 → polygon 경계로 당기는 벡터
        max_dist = 0
        shift_x, shift_y = 0, 0
        for ox, oy in outside_pts:
            nearest = usable_poly.exterior.interpolate(
                usable_poly.exterior.project(Point(ox, oy)))
            dx, dy = nearest.x - ox, nearest.y - oy
            dist = math.hypot(dx, dy)
            if dist > max_dist:
                max_dist = dist
                shift_x, shift_y = dx, dy
        if max_dist < 1:  # 1mm 미만 — 무시
            break
        # 안전 마진 50mm 추가
        shift_len = math.hypot(shift_x, shift_y)
        if shift_len > 0:
            shift_x *= (shift_len + 50) / shift_len
            shift_y *= (shift_len + 50) / shift_len
        center = (center[0] + shift_x, center[1] + shift_y)
        bbox = make_rotated_rect(center, width, depth, angle)
    return center, bbox


def _wall_facing(slot, depth, wall_attachment="free"):
    """벽 방향 배치 좌표 계산.

    핵심 규칙: "벽 반대쪽이 정면".
      1. 벽 위의 기준점(foot) 확정
      2. 벽에서 바닥 중심을 향하는 방향 = 정면(front_vec)
      3. 뒷면(back)을 벽에 밀착
      4. wall_attachment별 offset 적용

    법선 계산/probe/반전 돌려막기 제거. 바닥 중심 방향 한 번에 결정.
    """
    wall_ls = slot.get("wall_linestring")
    floor_poly = slot.get("_floor_poly")
    sx, sy = slot["x_mm"], slot["y_mm"]

    # ── 1. 벽 기준점(foot) + 벽 방향 벡터 확정 ──
    if wall_ls is not None:
        ref_pt = Point(sx, sy)
        proj_dist = wall_ls.project(ref_pt)
        foot = wall_ls.interpolate(proj_dist)
        base_x, base_y = foot.x, foot.y

        # 벽 방향 벡터 (벽을 따라가는 방향, 회전각 계산용)
        delta = 10
        p1 = wall_ls.interpolate(max(0, proj_dist - delta))
        p2 = wall_ls.interpolate(min(wall_ls.length, proj_dist + delta))
        wall_dx = p2.x - p1.x
        wall_dy = p2.y - p1.y
    else:
        base_x, base_y = sx, sy
        wall_dx, wall_dy = 1, 0  # 벽 정보 없으면 기본 수평

    # ── 2. front_vec = 벽에서 바닥 중심을 향하는 방향 ──
    if floor_poly:
        fcx, fcy = floor_poly.centroid.x, floor_poly.centroid.y
    else:
        fcx, fcy = base_x, base_y + 1000  # fallback

    # 벽 기준점 → 바닥 중심 방향
    to_center_x = fcx - base_x
    to_center_y = fcy - base_y
    to_center_d = math.hypot(to_center_x, to_center_y)
    if to_center_d < 1:
        to_center_x, to_center_y = 0, 1  # 극단 케이스

    # 벽 수직 방향 2개 중 바닥 중심을 향하는 쪽 선택
    wall_len = math.hypot(wall_dx, wall_dy)
    if wall_len < 0.01:
        wall_len = 1
    # 벽 수직 후보 2개
    n1x, n1y = -wall_dy / wall_len, wall_dx / wall_len
    n2x, n2y = wall_dy / wall_len, -wall_dx / wall_len

    # 바닥 중심 방향과 내적이 큰 쪽 = 안쪽
    dot1 = n1x * to_center_x + n1y * to_center_y
    dot2 = n2x * to_center_x + n2y * to_center_y
    if dot1 >= dot2:
        nx, ny = n1x, n1y
    else:
        nx, ny = n2x, n2y

    # ── 3. offset 적용 (뒷면 벽 밀착) ──
    if wall_attachment == "near":
        offset = depth / 2 + STAFF_CLEARANCE_MM
    else:
        offset = depth / 2

    cx, cy = base_x + nx * offset, base_y + ny * offset

    # ── 4. 회전각 + front_vec 반환 ──
    # front_vec = (nx, ny) = 벽에서 바닥 중심 방향
    # Three.js 보정: rotation={[0, -rad, 0]}이므로 atan2(-nx, ny)
    angle = math.degrees(math.atan2(-nx, ny))
    return (cx, cy), angle, (nx, ny)


def _inward(slot, usable_poly):
    """내향 배치 좌표 계산."""
    nx, ny = normal_to_vector(slot.get("wall_normal", "south"))
    candidates = _generate_candidates(slot, nx, ny, usable_poly)
    if not candidates:
        candidates = [(slot["x_mm"] + nx * 500, slot["y_mm"] + ny * 500)]
    best = candidates[0]
    return best, 0.0


def _center(slot, usable_poly):
    """중앙 방향 배치 좌표 계산."""
    sx, sy = slot["x_mm"], slot["y_mm"]
    wn = slot.get("wall_normal", "south")

    # 중앙 ref_point (wall_normal=none) → 좌표 그대로 사용
    if wn == "none":
        return (sx, sy), 0.0

    nx, ny = normal_to_vector(wn)
    candidates = _generate_candidates(slot, nx, ny, usable_poly)
    if not candidates:
        candidates = [(sx + nx * 500, sy + ny * 500)]
    if usable_poly:
        fc = usable_poly.centroid
        best = min(candidates, key=lambda c: math.hypot(c[0]-fc.x, c[1]-fc.y))
        angle = math.degrees(math.atan2(fc.y-best[1], fc.x-best[0]))
    else:
        best = candidates[0]
        angle = 0.0
    return best, angle


def _generate_candidates(slot, nx, ny, floor_poly, max_steps=8, step_base=300):
    """법선 방향 후보 좌표 생성."""
    candidates = []
    sx, sy = slot["x_mm"], slot["y_mm"]
    for i in range(1, max_steps + 1):
        offset = step_base * i
        cx, cy = sx + nx * offset, sy + ny * offset
        if floor_poly and floor_poly.contains(Point(cx, cy)):
            candidates.append((cx, cy))
    return candidates


# 2026-04-29: substring 기반 canonical 정규화로 전환.
# 기존 exact tuple matching 은 'core_toilet'/'dead_zone_toilet'/'w.c'/'staircase' 같은 변형 미스.
# parser 명명 다양성 (DXF layer 명명 규칙 도면별 상이) 에 robust 하게 대응.
# 매칭 우선순위 = dict 삽입 순서: stair 먼저 (core_access 자동 생성 분기 보존) → toilet → pillar → core.
STRUCTURAL_DZ_KEYWORDS: dict[str, tuple[str, ...]] = {
    "stair":  ("stair", "step"),                              # core_access 자동 생성 트리거
    "toilet": ("toilet", "restroom", "lavatory", "wc"),       # "w.c" 는 점 제거 후 wc 매칭
    "pillar": ("pillar", "column"),
    "core":   ("core",),                                       # core_access / dead_zone_core 등 잔여
}


def canonical_dz_type(dz_type: str) -> str:
    """parser dz_type 의 변형을 canonical category 로 정규화.

    매칭 예:
      'core_stair' → 'stair' (stair 우선 — core_access 생성)
      'core_toilet' → 'toilet'
      'dead_zone_toilet' → 'toilet'
      'w.c' → 'toilet' (점 제거 → wc)
      'staircase' → 'stair'
      'dead_zone_core' → 'core'
      'electrical_panel' → '' (구조물 아님)
    매칭 없으면 빈 문자열 (STRUCTURAL_DZ 아님).
    """
    if not dz_type:
        return ""
    name = str(dz_type).lower().replace(".", "")
    for canonical, keywords in STRUCTURAL_DZ_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return canonical
    return ""



# 계단 입구 감압 구역 — 소방법 1200mm + VMD 실무 여유 → 1500mm
STAIR_ACCESS_CLEARANCE_MM = 1500


def _build_stair_core_access(stair_poly: Polygon, floor_poly: Polygon) -> list:
    """계단 폴리곤에서 매장 내부를 향한 입구 변을 찾고, 1500mm core_access 폴리곤을 생성.

    판별 로직 (제미나이 팩트체크 반영):
      1. 계단 폴리곤의 각 변을 순회
      2. 바닥 외곽선(floor boundary)과 접촉하는 변 = 벽 쪽 → 스킵
      3. 접촉하지 않는 변 = 매장 내부 입구 → 법선 방향 1500mm 확장
    정사각형 계단에서도 동작 (길이 비교가 아닌 boundary 접촉 판별).
    """
    import logging
    logger = logging.getLogger(__name__)

    if not stair_poly.is_valid or not floor_poly.is_valid:
        return []

    coords = list(stair_poly.exterior.coords)
    floor_boundary = floor_poly.boundary

    results = []

    for i in range(len(coords) - 1):
        edge_start = coords[i]
        edge_end = coords[i + 1]
        edge = LineString([edge_start, edge_end])
        edge_len = edge.length

        if edge_len < 100:  # 극소 변 무시
            continue

        mid_x = (edge_start[0] + edge_end[0]) / 2
        mid_y = (edge_start[1] + edge_end[1]) / 2

        # 1차: 바닥 외곽선과 접촉 여부 — 변의 중점이 boundary에서 50mm 이내면 벽 쪽
        dist_to_boundary = floor_boundary.distance(Point(mid_x, mid_y))
        if dist_to_boundary < 50:
            continue

        # 매장 내부를 향한 입구 변 → 법선 방향으로 1500mm 확장
        dx = edge_end[0] - edge_start[0]
        dy = edge_end[1] - edge_start[1]
        # 외향 법선 (반시계 방향 가정: 오른쪽 법선)
        nx, ny = dy / edge_len, -dx / edge_len

        # 법선이 매장 내부를 향하는지 확인 — 계단 중심 → 법선 방향 반대면 뒤집기
        cx, cy = stair_poly.centroid.x, stair_poly.centroid.y
        probe_x = mid_x + nx * 100
        probe_y = mid_y + ny * 100
        # 법선이 계단 중심 쪽이면 뒤집기 (바깥으로 향해야 함)
        if ((probe_x - cx) ** 2 + (probe_y - cy) ** 2) < ((mid_x - cx) ** 2 + (mid_y - cy) ** 2):
            nx, ny = -nx, -ny

        # 매장 바닥 안을 향하는지 최종 확인
        probe_inside = Point(mid_x + nx * 200, mid_y + ny * 200)
        if not floor_poly.contains(probe_inside):
            continue

        # core_access 사각형: 변에서 법선 방향 1500mm 확장
        cl = STAIR_ACCESS_CLEARANCE_MM
        access_poly = Polygon([
            (edge_start[0], edge_start[1]),
            (edge_end[0], edge_end[1]),
            (edge_end[0] + nx * cl, edge_end[1] + ny * cl),
            (edge_start[0] + nx * cl, edge_start[1] + ny * cl),
        ])

        if access_poly.is_valid and access_poly.area > 0:
            results.append(access_poly)
            logger.info(
                "[stair_core_access] 계단 입구 감지: edge=(%.0f,%.0f)→(%.0f,%.0f) "
                "법선=(%.2f,%.2f) 면적=%.0fmm²",
                edge_start[0], edge_start[1], edge_end[0], edge_end[1],
                nx, ny, access_poly.area,
            )

    return results


def extract_structural_dead_zones(state: dict) -> list:
    """state에서 구조물 dead zone(pillar/toilet/stair/core)만 추출.
    stair인 경우 입구 앞 1500mm core_access 폴리곤도 자동 생성.

    parser dz_type 명명 변형 (예: 'core_toilet', 'dead_zone_stair', 'w.c') 은
    canonical_dz_type() 으로 정규화 — entry["type"] 은 항상 canonical (stair/toilet/pillar/core).

    Returns: [{"type": str (canonical), "poly": Polygon, "raw_type": str}, ...]
    """
    dead_zones = state.get("dead_zones") or []
    dz_types = state.get("dead_zone_types") or []
    result = []
    for i, dz in enumerate(dead_zones):
        if i >= len(dz_types) or not hasattr(dz, "centroid"):
            continue
        canonical = canonical_dz_type(dz_types[i])
        if canonical:
            result.append({"type": canonical, "poly": dz, "raw_type": dz_types[i]})

    # 계단 입구 core_access 자동 생성
    floor_poly = state.get("usable_poly")
    if floor_poly and hasattr(floor_poly, "boundary"):
        # 계단 외 구조물 폴리곤 수집 — 인접 구조물에 붙은 변은 입구 아님
        other_polys = [e["poly"] for e in result if e["type"] != "stair"]
        stair_entries = [e for e in result if e["type"] == "stair"]
        for entry in stair_entries:
            access_polys = _build_stair_core_access(entry["poly"], floor_poly)
            for ap in access_polys:
                # 인접 구조물과 80% 이상 겹치면 스킵 (화장실 옆 등)
                skip = False
                for op in other_polys:
                    if ap.intersects(op):
                        overlap = ap.intersection(op).area / ap.area if ap.area > 0 else 0
                        if overlap > 0.3:
                            skip = True
                            break
                if skip:
                    continue
                # 바닥 폴리곤으로 클리핑 — 바닥 밖으로 나가지 않도록
                clipped = ap.intersection(floor_poly)
                if clipped.is_valid and clipped.area > 100_000:  # 최소 0.1㎡
                    result.append({"type": "core_access", "poly": clipped})

    return result


def serialize_placement(p):
    """배치 결과 → JSON 직렬화. 정본 네이밍만."""
    bbox = p["bbox_polygon"]
    return {
        "id": f"{p['object_type']}_{uuid.uuid4().hex[:8]}",
        "object_type": p["object_type"],
        # #472 b-3: 매뉴얼 raw 명명 frontend 전파 — _build_entry 가 label 채워줌, fallback object_type.
        "label": p.get("label") or p.get("object_type", ""),
        # 1-2 (#523/#524 후속): 매뉴얼 명시 의도 라벨 (POS 카운터 vs 증정품 카운터 등) frontend / DB 전파.
        # _build_entry 가 박지만 직렬화 단계에서 drop 되던 회귀 차단. None 가능 (default 풀 obj).
        "manual_label": p.get("manual_label"),
        "center_x_mm": p["center_x_mm"],
        "center_y_mm": p["center_y_mm"],
        "rotation_deg": p["rotation_deg"],
        "width_mm": p["width_mm"],
        "depth_mm": p["depth_mm"],
        "height_mm": p.get("height_mm", 1500),
        "category": p.get("category", ""),
        "anchor_key": p.get("anchor_key", ""),
        "zone_label": p["zone_label"],
        "concept_area_id": p.get("concept_area_id"),  # 2026-05-01 Phase 2 — concept_areas FK 전파
        "concept_area": p.get("concept_area"),         # 2026-05-01 Phase 4 — 프론트 색칠용 한국어 라벨
        "direction": p["direction"],
        "placed_because": p["placed_because"],
        "wall_attachment": p.get("wall_attachment", "free"),
        "bbox_bounds": [round(b) for b in bbox.bounds],
        "front_vec": list(p["front_vec"]) if p.get("front_vec") else None,
        "front_edge": p.get("front_edge", "width"),
        "is_partition_face": p.get("is_partition_face", False),
        "join_with": p.get("join_with"),
        "candidates_count": p.get("candidates_count", 0),
        # 2026-05-08: partition_wall_I/L 의 그래픽 면 메타. partition_reuse 가 photo_wall 흡수 시
        # graphic_face='outer' / basis='photo_wall_substitute' 박음. 직렬화 누락 시 frontend / dump
        # 가시성 X + partition_reuse 추적 불가능 → 본 키 추가 (None 허용 — partition 외 obj).
        "graphic_face": p.get("graphic_face"),
        "graphic_face_basis": p.get("graphic_face_basis"),
    }


# ── 파싱 신뢰도 계산 ─────────────────────────────────────────────────────

def calculate_parse_confidence(polygon_source: str, scale_source: str = "direct") -> float:
    """도면 파싱 결과의 신뢰도(0.0~1.0) 계산.

    polygon_source:
      "vector"      — DXF (벡터, 항상 정확)
      "pdf_vector"  — PDF + scale_confirmed + is_vector
      "pdf_raster"  — PDF + scale 미확인
      "hough"       — 이미지 Hough Line Transform
      "opencv"      — 이미지 OpenCV contour
      "vision"      — 이미지 Claude Vision fallback
    scale_source:
      "direct" / "text" / "vision" / "default"
      default면 -0.2 페널티 (이미지 파서 전용)
    """
    polygon_score = {
        "vector":     1.0,
        "pdf_vector": 0.9,
        "pdf_raster": 0.5,
        "hough":      0.9,
        "opencv":     0.7,
        "vision":     0.6,
    }.get(polygon_source, 0.5)

    scale_penalty = -0.2 if scale_source == "default" else 0.0

    return round(max(0.0, min(1.0, polygon_score + scale_penalty)), 2)
