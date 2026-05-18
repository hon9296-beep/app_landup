"""
MAX_COUNT_GENERIC + CATEGORY_EXTRAS 구조 검증 (2026-04-23).

배경:
  기존 MAX_COUNT_BY_CATEGORY 가 미등록 카테고리(fashion/F&B/tech/art/entertainment/기타) 를
  캐릭터 IP dict 로 fallback 시킴 → 패션 매장에 character_bbox 배치되는 오염 발생.
  신규 구조: generic pool + category extras 로 카테고리별 후보군 정확히 통제.

  Data Layer (본 테스트 대상) — 후보군 '종류' 통제.
  S-8 Allocator — '수량' 컴퓨팅 (별도 테스트).

검증 범위:
  - generic-only 카테고리 (fashion / 기타 / 미등록) 에 character_bbox 누출 없음
  - 등록 카테고리 (캐릭터 IP / 뷰티) 에 예상 extras 포함
  - dict union 우선순위 (뷰티 display_table override 2) 정확 반영
"""
from app.vmd_constants import MAX_COUNT_GENERIC, CATEGORY_EXTRAS


def _resolve_count_table(category: str) -> dict[str, int]:
    """object_selection._default_placement_rules L800 과 동일 로직."""
    return MAX_COUNT_GENERIC | CATEGORY_EXTRAS.get(category, {})


# ── Generic pool 자체 검증 ──────────────────────────────────────────────

def test_generic_pool_has_no_character_bbox():
    """character_bbox 는 캐릭터 IP 전용. generic 에 섞이면 안 됨."""
    assert "character_bbox" not in MAX_COUNT_GENERIC, \
        "character_bbox 가 generic 에 있으면 모든 카테고리에 character_bbox 가 배치됨"


def test_generic_pool_contains_universal_fixtures():
    """모든 팝업스토어 공통 기물은 generic 에 있어야 함."""
    required = {"counter", "display_table", "shelf_wall", "photo_wall"}
    assert required.issubset(MAX_COUNT_GENERIC.keys()), \
        f"generic 누락: {required - MAX_COUNT_GENERIC.keys()}"


# ── 카테고리별 합성 결과 검증 ─────────────────────────────────────────

def test_character_ip_has_character_bbox():
    """캐릭터 IP 는 character_bbox 포함."""
    table = _resolve_count_table("캐릭터 IP")
    assert "character_bbox" in table
    assert table["character_bbox"] == 4


def test_fashion_has_no_character_bbox():
    """**핵심 회귀 방지**: 패션 매장에 character_bbox 배치 차단."""
    table = _resolve_count_table("패션 브랜드")
    assert "character_bbox" not in table, \
        "패션 브랜드 default pool 에 character_bbox 가 있으면 패션 매장에 캐릭터 조형물 배치됨"


def test_fnb_has_no_character_bbox():
    table = _resolve_count_table("F&B")
    assert "character_bbox" not in table


def test_tech_has_no_character_bbox():
    table = _resolve_count_table("테크·전자제품")
    assert "character_bbox" not in table


def test_art_has_no_character_bbox():
    table = _resolve_count_table("아트·전시")
    assert "character_bbox" not in table


def test_etc_has_no_character_bbox():
    """**'기타' 카테고리 fallback 버그 수정 확증**.
    이전: MAX_COUNT_BY_CATEGORY['기타'] = MAX_COUNT_CHARACTER_IP → character_bbox 포함.
    이후: CATEGORY_EXTRAS 미등록 → generic only → character_bbox 없음.
    """
    table = _resolve_count_table("기타")
    assert "character_bbox" not in table, \
        "'기타' 카테고리가 여전히 character_ip fallback 하고 있음"


def test_unregistered_category_falls_back_to_generic_only():
    """등록 안 된 카테고리도 generic 만 받음 (기타와 동일 동작)."""
    table = _resolve_count_table("존재하지 않는 카테고리")
    assert "character_bbox" not in table
    # generic 의 공통 기물은 받아야 함
    assert "counter" in table
    assert "display_table" in table


# ── dict union override 검증 ────────────────────────────────────────────

def test_beauty_display_table_override():
    """뷰티 CATEGORY_EXTRAS 가 generic 의 display_table 4 를 2 로 override."""
    table = _resolve_count_table("뷰티·코스메틱")
    assert table["display_table"] == 2, \
        f"뷰티 display_table override 실패. generic 4 가 extras 2 로 덮여야 함. 현재: {table.get('display_table')}"


def test_beauty_shelf_wall_override():
    """뷰티 shelf_wall 도 generic 6 → extras 3 override."""
    table = _resolve_count_table("뷰티·코스메틱")
    assert table["shelf_wall"] == 3


def test_beauty_has_category_specific_fixtures():
    """뷰티 고유 기물: test_bar, consultation_desk, aux_table 등."""
    table = _resolve_count_table("뷰티·코스메틱")
    for fixture in ["test_bar", "consultation_desk", "aux_table", "kiosk", "signage_stand"]:
        assert fixture in table, f"뷰티 extras 에 {fixture} 누락"


# ── 카테고리별 예상 셋 전수 확인 ──────────────────────────────────────

def test_fashion_generic_only():
    """패션 브랜드는 generic 과 정확히 동일 (등록된 fashion-specific 기물 없음)."""
    table = _resolve_count_table("패션 브랜드")
    assert table == MAX_COUNT_GENERIC


def test_tech_extras_applied():
    """테크: test_bar 2, consultation_desk 1, signage_stand 1."""
    table = _resolve_count_table("테크·전자제품")
    assert table.get("test_bar") == 2
    assert table.get("consultation_desk") == 1
    assert table.get("signage_stand") == 1


def test_entertainment_has_character_bbox():
    """엔터·팬미팅: 아티스트 등신대 용도로 character_bbox 1 개 허용 (예외 케이스)."""
    table = _resolve_count_table("엔터·팬미팅")
    assert table.get("character_bbox") == 1
