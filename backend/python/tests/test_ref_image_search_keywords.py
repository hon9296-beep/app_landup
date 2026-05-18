"""
ref_image_loader 검색 키워드 contract 검증 (1-3 #523 제미나이 자문 반영).

5-7 라이브 trigger: 뷰티 폴더에 TENGA / 바른생각 (성인용품) 혼재. 검색어 자체가 일반
("popup interior VMD") 위주라 카테고리 mismatch 빈번.

본 테스트는 CATEGORY_KEYWORDS 의 contract 검증:
  1. 모든 8 카테고리 정의됨
  2. 각 카테고리에 영문 + 한국어 핵심 단어 + exclusion 모두 포함
  3. 5-7 trigger 케이스 (TENGA / 콘돔 / 성인) 차단
  4. 카테고리 cross-contamination exclusion (뷰티 ↔ 패션 ↔ F&B 등)
  5. 쿼리 길이 — DDG OR 처리 회피 위해 적정 (단어 수 합리)

자문 md: reports/AD/2026-05-07_16-21_ref_image_search_keywords_review_request.md
"""
import pytest

from app.nodes_small.prompts.ref_image_loader import (
    CATEGORY_KEYWORDS,
    PINTEREST_FILTER,
    SEARCH_SUFFIX,
)


# ── 8 카테고리 모두 정의 ────────────────────────────────────────────


def test_all_8_categories_defined():
    expected = {
        "캐릭터 IP", "패션 브랜드", "F&B", "뷰티·코스메틱",
        "테크·전자제품", "아트·전시", "엔터·팬미팅", "기타",
    }
    assert set(CATEGORY_KEYWORDS.keys()) == expected


def test_pinterest_filter_unchanged():
    assert PINTEREST_FILTER == "site:pinterest.com"


def test_search_suffix_includes_real_photo():
    """real photo / interior / 실제 공간 강조 — stock photo / mockup 차단 의도."""
    assert "real photo" in SEARCH_SUFFIX
    assert "interior" in SEARCH_SUFFIX
    assert "실제 공간" in SEARCH_SUFFIX or "매장 인테리어" in SEARCH_SUFFIX


# ── 5-7 trigger 케이스 차단 검증 ───────────────────────────────────


def test_beauty_blocks_tenga_and_condom():
    """뷰티에서 5-7 trigger (TENGA / 바른생각=콘돔) 단어 직접 exclusion."""
    beauty = CATEGORY_KEYWORDS["뷰티·코스메틱"]
    assert "-tenga" in beauty
    assert "-condom" in beauty
    assert "-콘돔" in beauty
    assert "-성인용품" in beauty


def test_beauty_blocks_wellness_and_clinic():
    """제미나이 권고: 성인 웰니스 / 건강보조식품 / 약국 차단."""
    beauty = CATEGORY_KEYWORDS["뷰티·코스메틱"]
    assert "-wellness" in beauty
    assert "-clinic" in beauty
    assert "-supplement" in beauty


def test_all_categories_block_adult():
    """모든 카테고리에 -adult / -성인 기본 차단."""
    for cat, kw in CATEGORY_KEYWORDS.items():
        assert "-adult" in kw, f"{cat} 에 -adult 없음"
        assert "-성인" in kw, f"{cat} 에 -성인 없음"


# ── 카테고리별 fixture 명사 (제미나이 권고 — Pinterest 인덱싱 매칭률 ↑) ──


def test_beauty_has_fixture_terms():
    """뷰티 fixture: tester / display / 매대 / 테스터존."""
    beauty = CATEGORY_KEYWORDS["뷰티·코스메틱"]
    assert "tester" in beauty
    assert "display" in beauty
    assert "매대" in beauty or "테스터존" in beauty or "진열대" in beauty


def test_fashion_has_fitting_terms():
    """패션 fixture: fitting / mannequin / 행거 / 피팅룸."""
    fashion = CATEGORY_KEYWORDS["패션 브랜드"]
    assert "fitting" in fashion or "mannequin" in fashion
    assert "행거" in fashion or "피팅룸" in fashion or "마네킹" in fashion


def test_fnb_has_counter_seating():
    """F&B fixture: counter / seating / 주방 / 테이블석."""
    fnb = CATEGORY_KEYWORDS["F&B"]
    assert "counter" in fnb or "seating" in fnb
    assert "주방" in fnb or "테이블석" in fnb


def test_tech_has_interactive_demo():
    """테크 fixture: interactive / demo / 체험존 / 디바이스진열대."""
    tech = CATEGORY_KEYWORDS["테크·전자제품"]
    assert "interactive" in tech or "demo" in tech
    assert "체험존" in tech


def test_art_has_pedestal_and_partition():
    """아트 fixture: pedestal / 좌대 / 가벽."""
    art = CATEGORY_KEYWORDS["아트·전시"]
    assert "pedestal" in art or "좌대" in art
    assert "가벽" in art or "artwork" in art


def test_character_has_mascot_figure():
    """캐릭터 IP fixture: mascot / figure / 마스코트 / 대형피규어."""
    character = CATEGORY_KEYWORDS["캐릭터 IP"]
    assert "mascot" in character or "figure" in character
    assert "마스코트" in character or "대형피규어" in character or "포토존" in character


def test_entertainment_has_md_booth():
    """엔터 fixture: MD-booth / photo-wall / MD부스 / 포토월."""
    ent = CATEGORY_KEYWORDS["엔터·팬미팅"]
    assert "MD-booth" in ent or "MD부스" in ent or "굿즈" in ent
    assert "photo-wall" in ent or "포토월" in ent


# ── 카테고리 cross-contamination 차단 ──────────────────────────────


def test_beauty_blocks_fashion_and_food():
    """뷰티 ↔ 패션 / F&B 차단."""
    beauty = CATEGORY_KEYWORDS["뷰티·코스메틱"]
    assert "-fashion" in beauty
    assert "-음식점" in beauty
    assert "-의류" in beauty


def test_fashion_blocks_food_and_beauty():
    """패션 ↔ F&B / 뷰티 차단."""
    fashion = CATEGORY_KEYWORDS["패션 브랜드"]
    assert "-cafe" in fashion or "-food" in fashion
    assert "-cosmetic" in fashion or "-화장품" in fashion


def test_character_blocks_idol_and_kpop():
    """캐릭터 IP ↔ 엔터·팬미팅 차단 (제미나이 권고 — 굿즈샵 교집합 큼)."""
    character = CATEGORY_KEYWORDS["캐릭터 IP"]
    assert "-idol" in character or "-아이돌" in character
    assert "-kpop" in character or "-팬미팅" in character


def test_entertainment_blocks_character():
    """엔터 ↔ 캐릭터 IP 차단."""
    ent = CATEGORY_KEYWORDS["엔터·팬미팅"]
    assert "-character" in ent or "-캐릭터" in ent


def test_art_blocks_retail():
    """아트 전시는 상업 retail 성격 차단 (제미나이 권고)."""
    art = CATEGORY_KEYWORDS["아트·전시"]
    assert "-retail" in art or "-상점" in art or "-매장" in art


# ── 쿼리 길이 적정성 (DDG OR 처리 회피) ────────────────────────────


def test_each_keyword_token_count_reasonable():
    """제미나이 권고: 너무 길면 DDG 가 일부 단어 누락 (OR 처리). 25 단어 이내 권장.

    positive 단어 + exclusion 합산. 단순 split 기준 — 정확한 토큰 카운트 아니지만 합리적 proxy.
    """
    for cat, kw in CATEGORY_KEYWORDS.items():
        tokens = kw.split()
        assert len(tokens) <= 30, f"{cat} 키워드 길이 초과 ({len(tokens)} > 30) — DDG OR 처리 위험"


def test_each_category_has_minimum_signal():
    """카테고리 specific 단어 부재 회귀 차단 — 최소 4개 positive 단어 (영문 + 한국 합산)."""
    for cat, kw in CATEGORY_KEYWORDS.items():
        tokens = kw.split()
        positive = [t for t in tokens if not t.startswith("-")]
        assert len(positive) >= 6, f"{cat} positive 단어 부족 ({len(positive)} < 6)"


def test_each_category_has_minimum_exclusion():
    """exclusion 부재 회귀 차단 — 최소 3개."""
    for cat, kw in CATEGORY_KEYWORDS.items():
        tokens = kw.split()
        exclusions = [t for t in tokens if t.startswith("-")]
        assert len(exclusions) >= 3, f"{cat} exclusion 부족 ({len(exclusions)} < 3)"
