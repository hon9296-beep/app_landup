"""
ref_image 테이블 스키마 정합성 검증 (2026-04-23, feature/ref-image-schema).

init_v2.sql 의 ref_image DDL 을 정적 파싱하여 다음을 검증:
  - 테이블 존재 + 위치
  - 모든 요구 컬럼 정의 + 타입
  - FK 제약 (참조 테이블 존재 + ON DELETE 정책)
  - UNIQUE / INDEX 존재
  - 기존 테이블 수 증가 확인

수동 검증 (커밋 전 따로 확인):
  - MySQL CLI 또는 워크벤치로 init_v2.sql 전체 replay → syntax error 없는지
  - testcontainers-mysql 도입은 별도 브랜치 (본 브랜치 scope 외)
"""
import re
from pathlib import Path

import pytest


INIT_SQL_PATH = Path(__file__).resolve().parents[3] / "db" / "init_v2.sql"


@pytest.fixture(scope="module")
def sql_text() -> str:
    assert INIT_SQL_PATH.exists(), f"init_v2.sql 없음: {INIT_SQL_PATH}"
    return INIT_SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ref_image_ddl(sql_text: str) -> str:
    """ref_image 테이블 DDL 블록만 추출."""
    # CREATE TABLE ref_image ( ... ) ENGINE=...; 까지
    m = re.search(
        r"CREATE\s+TABLE\s+ref_image\s*\((.*?)\)\s*ENGINE\s*=\s*InnoDB[^;]*;",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )
    assert m, "ref_image 테이블 DDL 블록 추출 실패"
    return m.group(1)


# ── 테이블 존재 + 카운트 ──────────────────────────────────────────

def test_ref_image_table_exists(sql_text: str):
    assert re.search(r"CREATE\s+TABLE\s+ref_image\s*\(", sql_text, re.IGNORECASE), \
        "init_v2.sql 에 ref_image 테이블 CREATE 문이 없음"


def test_table_count_incremented_to_36(sql_text: str):
    """End 주석이 36 tables 로 갱신됐는지 (35 → 36)."""
    assert "36 tables" in sql_text, "End 주석의 테이블 수가 36 으로 갱신되지 않음"


def test_table_placement_after_user_projects(sql_text: str):
    """FK 순서상 user_projects 이후에 정의되어야 함."""
    up_pos = sql_text.index("CREATE TABLE user_projects")
    ri_pos = sql_text.index("CREATE TABLE ref_image")
    assert ri_pos > up_pos, "ref_image 가 user_projects 보다 먼저 정의됨 — FK 순서 위반"


# ── 요구 컬럼 존재 + 타입 ──────────────────────────────────────────

REQUIRED_COLUMNS = {
    "id":                 r"BIGINT\s+AUTO_INCREMENT\s+PRIMARY\s+KEY",
    "user_project_id":    r"BIGINT\s+NULL",
    "brand_category_id":  r"BIGINT\s+NOT\s+NULL",
    "image_sha256":       r"CHAR\(64\)\s+NOT\s+NULL",
    "floor_size_tier":    r"ENUM\s*\(\s*'small'\s*,\s*'medium'\s*,\s*'large'\s*,\s*'outdoor'\s*\)\s+NOT\s+NULL",
    "search_keyword":     r"VARCHAR\(255\)\s+NULL",
    "source_url":         r"VARCHAR\(500\)\s+NULL",
    "s3_url":             r"VARCHAR\(500\)\s+NULL",
    "file_path":          r"VARCHAR\(500\)\s+NULL",
    "file_size_bytes":    r"INT\s+NULL",
    "ref_path":           r"VARCHAR\(500\)\s+NULL",
    "is_deleted":         r"BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+FALSE",
    "is_blacklisted":     r"BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+FALSE",
    "deleted_at":         r"TIMESTAMP\s+NULL",
    "deleted_by":         r"BIGINT\s+NULL",
    "blacklisted_at":     r"TIMESTAMP\s+NULL",
    "blacklisted_by":     r"BIGINT\s+NULL",
    "created_at":         r"TIMESTAMP\s+DEFAULT\s+CURRENT_TIMESTAMP",
}


@pytest.mark.parametrize("column,type_pattern", REQUIRED_COLUMNS.items())
def test_required_column_defined(ref_image_ddl: str, column: str, type_pattern: str):
    pattern = rf"\b{column}\s+{type_pattern}"
    assert re.search(pattern, ref_image_ddl, re.IGNORECASE), \
        f"컬럼 {column!r} 정의 누락 또는 타입 불일치. 기대: {type_pattern}"


def test_no_unexpected_columns(ref_image_ddl: str):
    """DDL 에 요구 목록 외 컬럼 안 들어갔는지 (스키마 오염 방지)."""
    # 컬럼 라인 = 각 줄 시작 공백 + 식별자 + 공백 + 타입
    lines = [l.strip() for l in ref_image_ddl.split("\n") if l.strip()]
    column_lines = [
        l for l in lines
        if re.match(r"^[a-z_]+\s+", l.lower())
        and not l.upper().startswith(("FOREIGN", "UNIQUE", "INDEX", "PRIMARY"))
    ]
    defined_cols = set()
    for l in column_lines:
        m = re.match(r"^([a-z_]+)\s+", l)
        if m:
            defined_cols.add(m.group(1))

    unexpected = defined_cols - set(REQUIRED_COLUMNS.keys())
    assert not unexpected, f"요구 목록 외 컬럼 발견: {unexpected}"


# ── Foreign Key 제약 ──────────────────────────────────────────

FK_REQUIREMENTS = [
    # (column, references_table, references_column, on_delete_policy)
    ("user_project_id",   "user_projects",    "id", "SET NULL"),
    ("brand_category_id", "brand_categories", "id", "RESTRICT"),
    ("deleted_by",        "users",            "id", "SET NULL"),
    ("blacklisted_by",    "users",            "id", "SET NULL"),
]


@pytest.mark.parametrize("col,ref_table,ref_col,policy", FK_REQUIREMENTS)
def test_foreign_key_defined(ref_image_ddl: str, col: str, ref_table: str, ref_col: str, policy: str):
    pattern = (
        rf"FOREIGN\s+KEY\s*\(\s*{col}\s*\)\s+"
        rf"REFERENCES\s+{ref_table}\s*\(\s*{ref_col}\s*\)\s+"
        rf"ON\s+DELETE\s+{policy}"
    )
    assert re.search(pattern, ref_image_ddl, re.IGNORECASE), \
        f"FK 누락 또는 정책 불일치: {col} → {ref_table}({ref_col}) ON DELETE {policy}"


def test_referenced_tables_exist(sql_text: str):
    """FK 참조 대상 테이블이 init_v2.sql 에 모두 존재하는지."""
    for ref_table in {"user_projects", "brand_categories", "users"}:
        assert re.search(rf"CREATE\s+TABLE\s+{ref_table}\b", sql_text, re.IGNORECASE), \
            f"FK 참조 대상 테이블 누락: {ref_table}"


# ── UNIQUE / INDEX ────────────────────────────────────────────

def test_unique_project_sha_constraint(ref_image_ddl: str):
    """동일 프로젝트 내 같은 sha256 중복 방지 UNIQUE."""
    assert re.search(
        r"UNIQUE\s+KEY\s+\w+\s*\(\s*user_project_id\s*,\s*image_sha256\s*\)",
        ref_image_ddl,
        re.IGNORECASE,
    ), "UNIQUE (user_project_id, image_sha256) 제약 누락"


REQUIRED_INDEXES = [
    # (index_cols_pattern, 설명)
    (r"brand_category_id\s*,\s*floor_size_tier", "카테고리+tier 조회 최적화"),
    (r"image_sha256\s*,\s*is_blacklisted",       "sha256 블랙리스트 조회"),
    (r"created_at\s+DESC",                        "최신순 정렬"),
]


@pytest.mark.parametrize("cols_pattern,description", REQUIRED_INDEXES)
def test_required_index_defined(ref_image_ddl: str, cols_pattern: str, description: str):
    pattern = rf"INDEX\s+\w+\s*\(\s*{cols_pattern}\s*\)"
    assert re.search(pattern, ref_image_ddl, re.IGNORECASE), \
        f"INDEX 누락: {cols_pattern} ({description})"


# ── ENGINE / CHARSET ──────────────────────────────────────────

def test_engine_innodb_utf8mb4(sql_text: str):
    """ref_image 가 다른 테이블과 동일한 엔진/charset 사용."""
    pattern = r"CREATE\s+TABLE\s+ref_image.*?ENGINE\s*=\s*InnoDB\s+DEFAULT\s+CHARSET\s*=\s*utf8mb4"
    assert re.search(pattern, sql_text, re.IGNORECASE | re.DOTALL), \
        "ref_image 가 InnoDB + utf8mb4 선언을 갖지 않음"
