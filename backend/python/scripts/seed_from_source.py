"""
LandUp DB Seeder — 소스 상수 → DB 삽입

소스 진실의 원본:
  - backend/app/utils.py        (OBJECT_STANDARDS)
  - backend/app/vmd_constants.py (VMD_BOUNDARIES*, MAX_COUNT_*, AREA_TYPES, CATEGORY_FOLDER, LAYER patterns, BRAND_DEFAULTS, SPACE_CAP, FIRE_RULES, CONSTRUCTION_RULES)
  - backend/app/nodes_small/object_selection.py (_SPACE_CAP_RULES_SMALL)

실행:
  python seed_from_source.py

재실행 안전: INSERT ... ON DUPLICATE KEY UPDATE.

최종 배포 위치: backend/db/seed.py 또는 landup_team/db/seed.py
(현재는 docs/docs-shin/matrix/DB/확정/ 에 draft로 둠)
"""
import json
import os
import sys
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────
# scripts/ 에서 실행해도 app.* 모듈 import 되도록 backend/python 을 sys.path 에 추가
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_PYTHON = _PROJECT_ROOT / "backend" / "python"
sys.path.insert(0, str(_BACKEND_PYTHON))

import pymysql
from dotenv import load_dotenv

# 프로젝트 루트의 .env 자동 로드
load_dotenv(_PROJECT_ROOT / ".env")

# 실제 import (런타임 기준):
# from app.utils import OBJECT_STANDARDS
# from app.vmd_constants import (
#     VMD_BOUNDARIES, VMD_BOUNDARIES_BEAUTY,
#     VMD_WALL_ATTACHMENT, DIRECTIONAL_CLEARANCE, DIRECTIONAL_CLEARANCE_FLOOR, VMD_PAIR_RULES,
#     MAX_COUNT_CHARACTER_IP, MAX_COUNT_BEAUTY,
#     STEP_DOWN_MM, SCALING_REFERENCE_AREA_MM2,
# )

# ── DB 연결 ────────────────────────────────────────────────────────
# 환경변수 우선, 없으면 로컬 기본값.
# CI/CD (cd.yml seed-db job) 에서 GitHub Secrets 로 주입.
# 로컬에서 돌릴 땐 env 미설정 시 localhost 기본값 사용.
DB_CONFIG = dict(
    host=os.getenv("DB_HOST") or "localhost",
    port=int(os.getenv("DB_PORT") or "3306"),
    user=os.getenv("DB_USER") or "landup",
    password=os.getenv("DB_PASSWORD") or "landup",
    database=os.getenv("DB_NAME") or "landup",
    charset="utf8mb4",
    autocommit=False,
)

# ══════════════════════════════════════════════════════════════════
# 1. object_palette
# ══════════════════════════════════════════════════════════════════
def seed_object_palette(cur, OBJECT_STANDARDS, VMD_BOUNDARIES):
    """
    OBJECT_STANDARDS + VMD_BOUNDARIES → object_palette (카탈로그 + std 규격만)
    - code, name_ko, priority: OBJECT_STANDARDS
    - front_edge, width/depth/height_std_mm: VMD_BOUNDARIES
    - is_structural: partition_wall_* 만 TRUE
    - fixture_role: OBJECT_STANDARDS[code].get('fixture_role') (가벽 I/L = 'partition')
    - wall_attachment / clearance 는 별도 테이블 (seed_object_wall_attachment / seed_object_clearance)
    """
    for code, std in OBJECT_STANDARDS.items():
        bounds = VMD_BOUNDARIES.get(code, {})
        cur.execute(
            """
            INSERT INTO object_palette
                (code, name_ko, priority, front_edge, is_structural,
                 fixture_role, width_std_mm, depth_std_mm, height_std_mm)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                name_ko=VALUES(name_ko),
                priority=VALUES(priority),
                front_edge=VALUES(front_edge),
                is_structural=VALUES(is_structural),
                fixture_role=VALUES(fixture_role),
                width_std_mm=VALUES(width_std_mm),
                depth_std_mm=VALUES(depth_std_mm),
                height_std_mm=VALUES(height_std_mm)
            """,
            (
                code,
                std.get("name", code),
                std.get("priority", 50),
                bounds.get("front_edge", "width"),
                code in ("partition_wall_I", "partition_wall_L"),
                std.get("fixture_role"),
                bounds.get("width_mm", {}).get("std", 800),
                bounds.get("depth_mm", {}).get("std", 600),
                bounds.get("height_mm", {}).get("std", 1500),
            ),
        )


# ══════════════════════════════════════════════════════════════════
# 2-b. object_clearance (DIRECTIONAL_CLEARANCE → 1:1 테이블)
# ══════════════════════════════════════════════════════════════════
def seed_object_clearance(cur, DIRECTIONAL_CLEARANCE, DIRECTIONAL_CLEARANCE_FLOOR):
    """DIRECTIONAL_CLEARANCE + FLOOR → object_clearance (1:1 per object_palette).

    front_mm / back_mm      = 기본 clearance
    front_floor_mm / back_floor_mm = 인체 안전 하한선 (step-down 시 max(computed, floor) 강제)
    """
    for code, clearance in DIRECTIONAL_CLEARANCE.items():
        cur.execute("SELECT id FROM object_palette WHERE code=%s", (code,))
        r = cur.fetchone()
        if not r:
            continue
        pid = r[0]
        floor = DIRECTIONAL_CLEARANCE_FLOOR.get(code, {})
        cur.execute(
            """
            INSERT INTO object_clearance
                (object_palette_id, front_mm, back_mm, front_floor_mm, back_floor_mm)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                front_mm       = VALUES(front_mm),
                back_mm        = VALUES(back_mm),
                front_floor_mm = VALUES(front_floor_mm),
                back_floor_mm  = VALUES(back_floor_mm)
            """,
            (
                pid,
                clearance.get("front", 0),
                clearance.get("back", 0),
                floor.get("front", 0),
                floor.get("back", 0),
            ),
        )


# ══════════════════════════════════════════════════════════════════
# 2-c. object_wall_attachment (VMD_WALL_ATTACHMENT → 1:1 테이블)
# ══════════════════════════════════════════════════════════════════
def seed_object_wall_attachment(cur, VMD_WALL_ATTACHMENT):
    """VMD_WALL_ATTACHMENT → object_wall_attachment (1:1 per object_palette)"""
    for code, attachment in VMD_WALL_ATTACHMENT.items():
        cur.execute("SELECT id FROM object_palette WHERE code=%s", (code,))
        r = cur.fetchone()
        if not r:
            continue
        pid = r[0]
        cur.execute(
            """
            INSERT INTO object_wall_attachment (object_palette_id, attachment)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE attachment=VALUES(attachment)
            """,
            (pid, attachment),
        )


# ══════════════════════════════════════════════════════════════════
# 2. object_ranges (min/max + 카테고리 오버라이드)
# ══════════════════════════════════════════════════════════════════
def seed_object_ranges(cur, VMD_BOUNDARIES, VMD_BOUNDARIES_BEAUTY):
    """
    VMD_BOUNDARIES → brand_category=NULL 기본 row
    VMD_BOUNDARIES_BEAUTY → brand_category='뷰티·코스메틱' 오버라이드 row
    """
    palette_id_cache = {}
    def _palette_id(code):
        if code not in palette_id_cache:
            cur.execute("SELECT id FROM object_palette WHERE code=%s", (code,))
            r = cur.fetchone()
            palette_id_cache[code] = r[0] if r else None
        return palette_id_cache[code]

    def _insert(code, brand_category, bounds):
        pid = _palette_id(code)
        if pid is None:
            return  # palette에 없는 오브젝트는 스킵
        cur.execute(
            """
            INSERT INTO object_ranges
                (object_palette_id, brand_category,
                 width_min_mm, width_max_mm,
                 depth_min_mm, depth_max_mm,
                 height_min_mm, height_max_mm)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                width_min_mm=VALUES(width_min_mm), width_max_mm=VALUES(width_max_mm),
                depth_min_mm=VALUES(depth_min_mm), depth_max_mm=VALUES(depth_max_mm),
                height_min_mm=VALUES(height_min_mm), height_max_mm=VALUES(height_max_mm)
            """,
            (
                pid, brand_category,
                bounds["width_mm"]["min"], bounds["width_mm"]["max"],
                bounds["depth_mm"]["min"], bounds["depth_mm"]["max"],
                bounds["height_mm"]["min"], bounds["height_mm"]["max"],
            ),
        )

    # 기본 (brand_category=NULL)
    for code, bounds in VMD_BOUNDARIES.items():
        _insert(code, None, bounds)

    # 뷰티 오버라이드
    for code, bounds in VMD_BOUNDARIES_BEAUTY.items():
        _insert(code, "뷰티·코스메틱", bounds)


# ══════════════════════════════════════════════════════════════════
# 3. object_aliases
# ══════════════════════════════════════════════════════════════════
def seed_object_aliases(cur, OBJECT_STANDARDS):
    """
    OBJECT_STANDARDS[*].aliases + name 필드도 별칭으로 등록 (한글명 매칭)
    """
    for code, std in OBJECT_STANDARDS.items():
        cur.execute("SELECT id FROM object_palette WHERE code=%s", (code,))
        pid_row = cur.fetchone()
        if not pid_row:
            continue
        pid = pid_row[0]

        # 별칭 + name_ko 자체도 alias에 포함 (정규화 시 한글명으로 매칭 가능)
        aliases = set(std.get("aliases", []))
        aliases.add(std.get("name", ""))
        aliases.add(code)
        aliases.discard("")

        for alias in aliases:
            try:
                cur.execute(
                    """
                    INSERT INTO object_aliases (object_palette_id, alias)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE object_palette_id=VALUES(object_palette_id)
                    """,
                    (pid, alias),
                )
            except pymysql.err.IntegrityError:
                # UNIQUE 위반 (다른 오브젝트가 이미 사용 중) → 경고 후 skip
                print(f"[warn] alias conflict: '{alias}' already owned by another object")


# ══════════════════════════════════════════════════════════════════
# 4. object_max_count
# ══════════════════════════════════════════════════════════════════
def seed_object_max_count(cur, MAX_COUNT_CHARACTER_IP, MAX_COUNT_BEAUTY):
    """
    MAX_COUNT_CHARACTER_IP → '캐릭터 IP' row
    MAX_COUNT_BEAUTY → '뷰티·코스메틱' row
    (기타 카테고리는 MAX_COUNT_CHARACTER_IP와 동일하다 가정 — brand_category=NULL로 동일값)
    """
    def _insert(code, brand_category, count):
        cur.execute("SELECT id FROM object_palette WHERE code=%s", (code,))
        r = cur.fetchone()
        if not r:
            return
        pid = r[0]
        cur.execute(
            """
            INSERT INTO object_max_count (object_palette_id, brand_category, max_count)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE max_count=VALUES(max_count)
            """,
            (pid, brand_category, count),
        )

    for code, count in MAX_COUNT_CHARACTER_IP.items():
        _insert(code, "캐릭터 IP", count)
        _insert(code, None, count)  # 기본(NULL) = 캐릭터 IP 동일
    for code, count in MAX_COUNT_BEAUTY.items():
        _insert(code, "뷰티·코스메틱", count)


# ══════════════════════════════════════════════════════════════════
# 5. brand_defaults (single-row)
# ══════════════════════════════════════════════════════════════════
def seed_brand_defaults(cur, SCALING_REFERENCE_AREA_MM2=99_000_000, STEP_DOWN_MM=200):
    """single-row brand_defaults — 대부분 DDL DEFAULT 로 채워지고, Python 상수 연동이 필요한 값만 명시 주입.

    SCALING_REFERENCE_AREA_MM2 / STEP_DOWN_MM 는 vmd_constants.py 와 동기화 보장.
    """
    cur.execute(
        """
        INSERT INTO brand_defaults (id, scaling_reference_area_mm2, step_down_mm)
        VALUES (1, %s, %s)
        ON DUPLICATE KEY UPDATE
            scaling_reference_area_mm2 = VALUES(scaling_reference_area_mm2),
            step_down_mm               = VALUES(step_down_mm)
        """,
        (SCALING_REFERENCE_AREA_MM2, STEP_DOWN_MM),
    )


# ══════════════════════════════════════════════════════════════════
# 6. area_types
# ══════════════════════════════════════════════════════════════════
_AREA_TYPES_SEED = [
    # code, name_ko, target_objects, position_hint, description
    ("entrance",    "맞이",    ["character_bbox", "banner_stand", "signage_stand"], "entrance_front", "입구 맞이 구역"),
    ("photo",       "포토",    ["photo_wall", "photo_island", "character_bbox"],    "mid",            "포토 촬영 구역"),
    ("experience",  "체험",    ["display_table", "kiosk"],                          "mid",            "체험 인터랙션 구역"),
    ("screening",   "상영",    ["kiosk"],                                           "deep",           "영상 상영 구역"),
    ("merchandise", "굿즈판매", ["shelf_wall", "shelf_3tier", "display_table"],      "deep",           "굿즈 판매 구역"),
    ("checkout",    "결제",    ["counter", "kiosk"],                                "entrance_front", "결제 카운터 구역"),
    ("mixed",       "혼합",    [],                                                  None,             "복합 구역"),
]

def seed_area_types(cur):
    for order, (code, name_ko, targets, pos_hint, desc) in enumerate(_AREA_TYPES_SEED):
        cur.execute(
            """
            INSERT INTO area_types (code, name_ko, target_objects, position_hint, description, display_order)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                name_ko=VALUES(name_ko),
                target_objects=VALUES(target_objects),
                position_hint=VALUES(position_hint),
                description=VALUES(description),
                display_order=VALUES(display_order)
            """,
            (code, name_ko, json.dumps(targets, ensure_ascii=False), pos_hint, desc, order),
        )


# ══════════════════════════════════════════════════════════════════
# 7. brand_categories
# ══════════════════════════════════════════════════════════════════
# code = 정본 slug (ref_image_loader.CATEGORY_FOLDER 의 영문값과 1:1 일치).
# 디스크 폴더 (references/images/{code}/) + Python loader + Java FK 모두 이 값으로 통일.
# folder_name 은 현재 = code 지만, 미래에 폴더 경로가 분리될 가능성 위해 컬럼 유지.
_BRAND_CATEGORIES_SEED = [
    ("character_ip",   "캐릭터 IP",       "character_ip"),
    ("fashion",        "패션 브랜드",     "fashion"),
    ("fnb",            "F&B",            "fnb"),
    ("beauty",         "뷰티·코스메틱",   "beauty"),
    ("tech",           "테크·전자제품",   "tech"),
    ("art",            "아트·전시",       "art"),
    ("entertainment",  "엔터·팬미팅",     "entertainment"),
    ("other",          "기타",           "other"),
]

# 2026-04-27: slug 정본화 마이그레이션 — 구 code 제거.
# beauty_cosmetic → beauty, etc → other 로 의미 동일하나 키가 어긋났던 잔재 정리.
# 재실행 시 idempotent (대상 row 없으면 0 affected).
_OBSOLETE_BRAND_CODES = ("beauty_cosmetic", "etc")


def seed_brand_categories(cur):
    cur.execute(
        f"DELETE FROM brand_categories WHERE code IN ({','.join(['%s'] * len(_OBSOLETE_BRAND_CODES))})",
        _OBSOLETE_BRAND_CODES,
    )
    for code, name_ko, folder in _BRAND_CATEGORIES_SEED:
        cur.execute(
            """
            INSERT INTO brand_categories (code, name_ko, folder_name)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                name_ko=VALUES(name_ko), folder_name=VALUES(folder_name)
            """,
            (code, name_ko, folder),
        )


# ══════════════════════════════════════════════════════════════════
# 8. layer_keywords (DXF 매칭 패턴)
# ══════════════════════════════════════════════════════════════════
_LAYER_KEYWORDS_SEED = {
    "entrance":     ["entrance", "입구", "정문", "main_door"],
    "emergency":    ["emergency", "비상", "exit", "피난"],
    "inaccessible": ["stair", "toilet", "pillar", "core", "계단", "화장실", "기둥"],
    "sprinkler":    ["sprinkler", "스프링클러", "Fire_Sprinkler", "소방_스프링클러"],
    "hydrant":      ["hydrant", "소화전", "Fire_Hydrant"],
    "panel":        ["panel", "분전반", "electrical_panel", "Electric_Panel"],
}

def seed_layer_keywords(cur):
    for category, keywords in _LAYER_KEYWORDS_SEED.items():
        for kw in keywords:
            cur.execute(
                """
                INSERT INTO layer_keywords (category, keyword)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE keyword=VALUES(keyword)
                """,
                (category, kw),
            )


# ══════════════════════════════════════════════════════════════════
# 8-b. object_pair_rules (VMD_PAIR_RULES → source='vmd_default')
# ══════════════════════════════════════════════════════════════════
def seed_object_pair_rules(cur, VMD_PAIR_RULES):
    """
    VMD_PAIR_RULES 14건 → object_pair_rules (source='vmd_default')
    브랜드 매뉴얼 추출분(source='manual')은 pipeline 런타임에 brand_data_json에서 처리.
    """
    for rule in VMD_PAIR_RULES:
        cur.execute(
            """
            INSERT INTO object_pair_rules
                (object_a_code, object_b_code, relation, min_gap_mm, overlap_margin_mm, source)
            VALUES (%s,%s,%s,%s,%s,'vmd_default')
            ON DUPLICATE KEY UPDATE
                min_gap_mm=VALUES(min_gap_mm),
                overlap_margin_mm=VALUES(overlap_margin_mm)
            """,
            (
                rule["object_a"],
                rule["object_b"],
                rule["relation"],
                rule.get("min_gap_mm", 0),
                rule.get("overlap_margin_mm", 0),
            ),
        )


# ══════════════════════════════════════════════════════════════════
# 9. space_cap_rules (진규)
# ══════════════════════════════════════════════════════════════════
_SPACE_CAP_SEED = [
    # scope, key_name, key_kind, cap_value, reason
    ("small_store", "counter",    "object_type",  1, "20평 이하 매장은 counter 2개 안 들어감"),
    ("small_store", "photo_wall", "object_type",  1, "20평 이하 포토월 최대 1개"),
    ("small_store", "partition",  "fixture_role", 1, "20평 이하 가벽 I/L 합계 최대 1개"),
]

def seed_space_cap_rules(cur):
    for scope, key_name, key_kind, cap, reason in _SPACE_CAP_SEED:
        cur.execute(
            """
            INSERT INTO space_cap_rules (scope, key_name, key_kind, cap_value, reason_note)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                key_kind=VALUES(key_kind),
                cap_value=VALUES(cap_value),
                reason_note=VALUES(reason_note)
            """,
            (scope, key_name, key_kind, cap, reason),
        )


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════
def main():
    # 실제 import
    from app.utils import OBJECT_STANDARDS
    from app.vmd_constants import (
        VMD_BOUNDARIES, VMD_BOUNDARIES_BEAUTY,
        VMD_WALL_ATTACHMENT, DIRECTIONAL_CLEARANCE, DIRECTIONAL_CLEARANCE_FLOOR,
        VMD_PAIR_RULES,
        MAX_COUNT_CHARACTER_IP, MAX_COUNT_BEAUTY,
        STEP_DOWN_MM, SCALING_REFERENCE_AREA_MM2,
    )

    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            print("[seed] brand_defaults ...")
            seed_brand_defaults(cur, SCALING_REFERENCE_AREA_MM2, STEP_DOWN_MM)

            print("[seed] brand_categories ...")
            seed_brand_categories(cur)

            print("[seed] area_types ...")
            seed_area_types(cur)

            print("[seed] layer_keywords ...")
            seed_layer_keywords(cur)

            print("[seed] object_palette ...")
            seed_object_palette(cur, OBJECT_STANDARDS, VMD_BOUNDARIES)

            print("[seed] object_ranges ...")
            seed_object_ranges(cur, VMD_BOUNDARIES, VMD_BOUNDARIES_BEAUTY)

            print("[seed] object_aliases ...")
            seed_object_aliases(cur, OBJECT_STANDARDS)

            print("[seed] object_max_count ...")
            seed_object_max_count(cur, MAX_COUNT_CHARACTER_IP, MAX_COUNT_BEAUTY)

            print("[seed] object_pair_rules ...")
            seed_object_pair_rules(cur, VMD_PAIR_RULES)

            print("[seed] object_clearance ...")
            seed_object_clearance(cur, DIRECTIONAL_CLEARANCE, DIRECTIONAL_CLEARANCE_FLOOR)

            print("[seed] object_wall_attachment ...")
            seed_object_wall_attachment(cur, VMD_WALL_ATTACHMENT)

            print("[seed] space_cap_rules ...")
            seed_space_cap_rules(cur)

        conn.commit()
        print("[seed] done.")
    except Exception as e:
        conn.rollback()
        print(f"[seed] failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
