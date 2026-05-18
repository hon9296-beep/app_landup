"""
ref_image_loader 검색 키워드 / 필터 — #491 prompts 중앙화.

조절 의도:
  - 카테고리별 키워드 — CATEGORY_KEYWORDS dict 만 수정
  - 전체 공통 suffix — SEARCH_SUFFIX 단일 변경 (조감도 탑뷰 배치 등)
  - 검색 사이트 필터 — PINTEREST_FILTER (다른 site: 로 변경 가능)

1-3 (#523 후속): 검색어 강화. 5-7 라이브에서 뷰티 폴더에 TENGA / 바른생각 (성인용품)
혼재 — 검색어가 "popup interior VMD" 같은 일반 키워드 위주라 비-카테고리 매장도 매칭.
fix 방향:
  1. 카테고리 specific 단어 우선 (skincare / makeup / vanity / counter 등 fixture 명사)
  2. Negative exclusion (DDG `-` 연산자) — 다른 카테고리 키워드 차단
  3. 한국어 specific 단어 강화 (화장품 / 매대 / 코스메틱 매장 등)
"""

# 이미지 검색 키워드 (DuckDuckGo + Pinterest 필터용)
# 1-3 (#523) 제미나이 자문 반영 — 압축 + fixture 명사 + exclusion 보강.
# 구조: 영문 핵심 4 + 한국어 핵심 4 + fixture 명사 2-3 (각 언어) + exclusion 8-10
# 의도:
#   1. 쿼리 압축 — DDG 가 너무 긴 쿼리 일부 단어 누락 (OR 처리). 핵심 단어 3-4 이내 권고
#   2. fixture 명사 (tester / fitting / pedestal / counter 등) Pinterest 핀 description 매칭률 ↑
#   3. exclusion 보강 — 5-7 trigger (TENGA / 바른생각 = 콘돔) 직접 차단 + 카테고리 cross-contamination 방지
# 자문 md: reports/AD/2026-05-07_16-21_ref_image_search_keywords_review_request.md
CATEGORY_KEYWORDS: dict[str, str] = {
    "캐릭터 IP": (
        "character IP popup store mascot figure "
        "캐릭터 팝업스토어 포토존 마스코트 대형피규어 "
        "-adult -성인 -idol -kpop -아이돌 -팬미팅 -음식점 -의류 -화장품"
    ),
    "패션 브랜드": (
        "fashion clothing popup showroom fitting mannequin "
        "패션 의류 팝업스토어 쇼룸 행거 피팅룸 마네킹 "
        "-adult -성인 -음식점 -food -cafe -화장품 -cosmetic -굿즈샵"
    ),
    "F&B": (
        "cafe restaurant popup interior counter seating "
        "카페 음식점 팝업스토어 인테리어 주방 테이블석 "
        "-adult -성인 -의류 -clothing -화장품 -cosmetic -굿즈샵 -fashion"
    ),
    "뷰티·코스메틱": (
        "beauty cosmetic skincare popup store tester display "
        "뷰티 화장품 코스메틱 매장 매대 테스터존 진열대 "
        "-adult -성인 -성인용품 -tenga -condom -콘돔 -wellness -clinic -supplement -음식점 -의류 -fashion"
    ),
    "테크·전자제품": (
        "tech electronics popup demo interactive display "
        "테크 전자제품 팝업스토어 체험존 인터랙티브테이블 디바이스진열대 "
        "-adult -성인 -의류 -clothing -화장품 -cosmetic -음식점 -fashion"
    ),
    "아트·전시": (
        "art exhibition gallery installation pedestal artwork "
        "아트 전시 갤러리 미술 좌대 가벽 작품 "
        "-adult -성인 -retail -상점 -매장 -의류 -clothing -화장품 -fashion -음식점"
    ),
    "엔터·팬미팅": (
        "kpop idol popup fan-store MD-booth photo-wall "
        "엔터 아이돌 팝업스토어 팬미팅 MD부스 포토월 굿즈 "
        "-adult -성인 -character -캐릭터 -animation -애니메이션 -의류 -음식점 -화장품"
    ),
    "기타": (
        "popup store retail interior visual merchandising "
        "팝업스토어 공간디자인 매장 인테리어 VMD "
        "-adult -성인 -condom -콘돔 -wellness"
    ),
}

# 일반 suffix — 모든 카테고리 공통. real photo + interior + 실제 공간 강조해서 stock photo / mockup 차단.
SEARCH_SUFFIX = " real photo interior space actual installation 실제 공간 매장 인테리어"

PINTEREST_FILTER = "site:pinterest.com"  # DDG에 site 필터 걸어 Pinterest 우선 반환
