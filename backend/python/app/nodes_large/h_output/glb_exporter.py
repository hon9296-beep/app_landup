"""
GLB 3D 내보내기 노드 — rendy/modules/glb_exporter.py 기반.

배치 결과 → trimesh Whitebox 메시 → .glb 바이트.
좌표계: mm 단위, Y-up (Three.js 기본).
  space_data (X, Y) → glb (X=width, Y=height, Z=depth)
"""
import math
import logging

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

from app.state import LargeState

logger = logging.getLogger(__name__)

# zone별 색상 (RGBA 0~255)
ZONE_COLORS = {
    "entrance_zone": [76, 175, 80, 255],
    "mid_zone":      [255, 152, 0, 255],
    "deep_zone":     [33, 150, 243, 255],
    "unknown":       [158, 158, 158, 255],
}
FLOOR_COLOR = [240, 240, 240, 255]
WALL_COLOR  = [180, 180, 180, 255]
MIN_DEPTH_MM = 20  # 등신대/배너 최소 두께

# dead_zone 타입별 색상
DEAD_ZONE_COLORS: dict[str, list[int]] = {
    "pillar":           [120, 113, 108, 255],  # warm stone
    "core":             [148, 163, 184, 255],  # slate
    "toilet":           [148, 163, 184, 255],  # slate
    "stair":            [100, 116, 139, 255],  # darker slate
    "inner_wall":       [176, 176, 176, 255],  # wall gray
    "core_access":      [203, 213, 225, 255],  # light slate
    "electrical_panel": [109,  40, 217, 255],  # purple
    "sprinkler":        [ 59, 130, 246, 255],  # blue
    "fire_hydrant":     [239,  68,  68, 255],  # red
    "emergency_exit":   [ 34, 197,  94, 255],  # green
}
_DZ_DEFAULT_COLOR = [158, 158, 158, 255]

# 장비류 — 바닥 위 마커 (위치 표시 전용, 높이 100mm)
_DZ_EQUIPMENT = {"sprinkler", "fire_hydrant", "emergency_exit"}
# 절반 높이 (계단은 올라가는 형태라 절반 높이로 표현)
_DZ_HALF_HEIGHT = {"stair"}
# 얇은 슬라브 (core_access 는 바닥 구역 표시)
_DZ_THIN = {"core_access"}


def run(state: LargeState) -> LargeState:
    """배치 결과 → GLB 3D 파일 생성."""
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")

    if not placed or not usable_poly:
        return {"glb_bytes": None}

    ceiling_h = _get_ceiling_height(state)
    scene = trimesh.Scene()

    # 바닥
    floor_mesh = _create_floor(usable_poly)
    scene.add_geometry(floor_mesh, node_name="floor")

    # 벽
    wall_meshes = _create_walls(usable_poly, ceiling_h)
    for i, wm in enumerate(wall_meshes):
        scene.add_geometry(wm, node_name=f"wall_{i}")

    # 이격구역 (기둥, 화장실, 계단 등)
    for i, (dzm, dztype) in enumerate(_create_dead_zones(state, ceiling_h)):
        scene.add_geometry(dzm, node_name=f"dz_{i}_{dztype}")

    # 오브젝트
    for i, obj in enumerate(placed):
        mesh = _create_object_mesh(obj, ceiling_h)
        scene.add_geometry(mesh, node_name=f"obj_{i}_{obj.get('object_type', 'unknown')}")

    glb_bytes = scene.export(file_type="glb")
    logger.info(f"[glb_exporter] {len(placed)} objects → {len(glb_bytes)} bytes")

    # 디스크 저장 → state["glb_path"] 로 Java 에 전파.
    # 저장 실패해도 glb_bytes 반환은 막히지 않도록 try/except 격리.
    glb_path = None
    try:
        from app.storage.glb_storage import save_glb_bytes
        glb_path = save_glb_bytes(glb_bytes)
    except Exception as e:
        logger.warning(f"[glb_exporter] glb 파일 저장 실패 (glb_bytes 는 유지): {e}")

    return {"glb_bytes": glb_bytes, "glb_path": glb_path}


# ── 색상 ─────────────────────────────────────────────────────────────────

def _apply_color(mesh: trimesh.Trimesh, rgba: list[int]) -> None:
    r, g, b, a = [c / 255.0 for c in rgba]
    mat = PBRMaterial(
        baseColorFactor=[r, g, b, a],
        metallicFactor=0.0,
        roughnessFactor=0.6,
    )
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)


# ── 바닥 ─────────────────────────────────────────────────────────────────

def _create_floor(usable_poly) -> trimesh.Trimesh:
    """Shapely polygon → extrude → Y↔Z swap (Y-up)."""
    minx, miny, maxx, maxy = usable_poly.bounds
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2

    try:
        floor = trimesh.creation.extrude_polygon(usable_poly, height=10)
        swap_yz = np.array([
            [1, 0, 0, 0],
            [0, 0, 1, 0],
            [0, 1, 0, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        floor.apply_transform(swap_yz)
        floor.apply_translation([0, -5, 0])
        floor.fix_normals()
        _apply_color(floor, FLOOR_COLOR)
        return floor
    except Exception:
        w = maxx - minx
        d = maxy - miny
        floor = trimesh.creation.box(extents=[w, 10, d])
        floor.apply_translation([cx, -5, cy])
        _apply_color(floor, FLOOR_COLOR)
        return floor


# ── 벽 ──────────────────────────────────────────────────────────────────

def _create_walls(usable_poly, height_mm: float) -> list[trimesh.Trimesh]:
    coords = list(usable_poly.exterior.coords)
    walls = []
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 10:
            continue
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        angle = math.atan2(y2 - y1, x2 - x1)

        wall = trimesh.creation.box(extents=[length, height_mm, 50])
        rot = trimesh.transformations.rotation_matrix(-angle, [0, 1, 0])
        wall.apply_transform(rot)
        wall.apply_translation([cx, height_mm / 2, cy])
        _apply_color(wall, WALL_COLOR)
        walls.append(wall)
    return walls


# ── 오브젝트 ─────────────────────────────────────────────────────────────

def _create_object_mesh(obj: dict, ceiling_h: float) -> trimesh.Trimesh:
    w = obj.get("width_mm", 600)
    d = obj.get("depth_mm", 400)
    h = obj.get("height_mm", 1000)
    cx = obj["center_x_mm"]
    cy = obj["center_y_mm"]
    rot_deg = obj.get("rotation_deg", 0)
    category = obj.get("category", "")

    if d < MIN_DEPTH_MM:
        d = MIN_DEPTH_MM

    is_cylinder = any(kw in category.lower() for kw in ("cylinder", "round", "column", "pillar"))

    if is_cylinder:
        diameter = max(w, d)
        mesh = trimesh.creation.cylinder(radius=diameter / 2, height=h, sections=32)
    else:
        mesh = trimesh.creation.box(extents=[w, h, d])

    if rot_deg != 0:
        rot = trimesh.transformations.rotation_matrix(math.radians(-rot_deg), [0, 1, 0])
        mesh.apply_transform(rot)

    mesh.apply_translation([cx, h / 2, cy])

    zone = obj.get("zone_label", "unknown")
    color = ZONE_COLORS.get(zone, ZONE_COLORS["unknown"])
    _apply_color(mesh, color)

    return mesh


def _get_ceiling_height(state: LargeState) -> float:
    brand_data = state.get("brand_data") or {}
    ch = brand_data.get("brand", {}).get("ceiling_height_mm", {})
    if isinstance(ch, dict):
        return ch.get("value", 3000)
    return 3000


# ── 이격구역 (dead zones) ────────────────────────────────────────────────────

def _dz_height(dz_type: str, ceiling_h: float) -> float:
    if dz_type in _DZ_EQUIPMENT:
        return 100
    if dz_type in _DZ_THIN:
        return 80
    if dz_type in _DZ_HALF_HEIGHT:
        return ceiling_h * 0.5
    return ceiling_h


def _to_single_polygon(geom):
    """Shapely 도형 → 단일 Polygon. MultiPolygon이면 면적 최대 조각 반환. 실패 시 None."""
    if geom is None or geom.is_empty:
        return None
    gtype = geom.geom_type
    if gtype == "Polygon":
        return geom if geom.area > 100 else None
    if gtype == "MultiPolygon":
        largest = max(geom.geoms, key=lambda g: g.area)
        return largest if largest.area > 100 else None
    if gtype == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        candidate = max(polys, key=lambda g: g.area)
        return _to_single_polygon(candidate)
    # Point / LineString 등 — 면적 없음
    return None


def _create_dead_zones(state: LargeState, ceiling_h: float) -> list[tuple[trimesh.Trimesh, str]]:
    """dead_zones (Shapely Polygon 리스트) → GLB 메시 리스트.

    구조 영역(기둥/화장실/계단 등): polygon 압출 + Y-up 변환.
    장비 마커(스프링클러/소화전 등): 바닥 위 얇은 박스로 위치 표시.
    """
    dead_zones = state.get("dead_zones") or []
    dz_types = state.get("dead_zone_types") or []
    results: list[tuple[trimesh.Trimesh, str]] = []

    logger.info(f"[glb_exporter] dead_zones count={len(dead_zones)} types={dz_types}")

    swap_yz = np.array([
        [1, 0, 0, 0],
        [0, 0, 1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
    ], dtype=float)

    for i, dz in enumerate(dead_zones):
        dz_type = dz_types[i] if i < len(dz_types) else "unknown"
        color = DEAD_ZONE_COLORS.get(dz_type, _DZ_DEFAULT_COLOR)
        h = _dz_height(dz_type, ceiling_h)

        try:
            cx, cy = dz.centroid.x, dz.centroid.y

            if dz_type in _DZ_EQUIPMENT:
                # 장비류 — 바닥 위 얇은 박스 마커 (위치 표시용)
                bounds = dz.bounds
                size = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 200)
                mesh = trimesh.creation.box(extents=[size, h, size])
                mesh.apply_translation([cx, h / 2, cy])
            else:
                # 구조 영역 — Polygon/MultiPolygon/GeometryCollection 모두 처리
                poly = _to_single_polygon(dz)
                if poly is None:
                    logger.warning(f"[glb_exporter] dead_zone {i} ({dz_type}) geom_type={dz.geom_type} skip: no valid polygon")
                    continue
                try:
                    mesh = trimesh.creation.extrude_polygon(poly, height=h)
                except Exception as ext_err:
                    # 복잡한 폴리곤 실패 시 convex_hull 으로 재시도
                    logger.warning(f"[glb_exporter] dead_zone {i} ({dz_type}) extrude failed ({ext_err}), retrying with convex_hull")
                    mesh = trimesh.creation.extrude_polygon(poly.convex_hull, height=h)
                mesh.apply_transform(swap_yz)

            mesh.fix_normals()
            _apply_color(mesh, color)
            results.append((mesh, dz_type))
            logger.info(f"[glb_exporter] dead_zone {i} ({dz_type}) h={h:.0f}mm → OK")

        except Exception as e:
            logger.warning(f"[glb_exporter] dead_zone {i} ({dz_type}) skip: {e}")

    return results
