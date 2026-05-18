"""
brand_category SSOT — 카테고리별 모든 룰을 한 곳에서 정의.

Why: 4-30 진단 (5중 누락 매트릭스) 결과 — 카테고리 정의가 5곳에 흩어져 있어
새 카테고리 추가 시 누락이 반복됨. 뷰티·코스메틱이 vmd_constants 에 등록됐지만
design.py `_CATEGORY_OVERRIDES` 에 누락된 것이 대표 사례.

How: 모든 카테고리별 룰을 `Category` dataclass 한 곳에 모아두고,
기존 모듈은 lookup 만 한다 (`get_category(key).extras` 등).
새 카테고리 추가 = 이 파일에 `Category(...)` 한 개 append.

설계 원칙:
- 카테고리 = SSOT. 다른 모듈은 lookup 만.
- 미등록 카테고리 → DEFAULT_CATEGORY ("기타") fallback.
- LLM 추출 가능 카테고리 (BRAND_TOOL.enum) 와 등록만 된 카테고리 분리 (`is_llm_extractable`).
- 행위 보존: 기존 모듈의 lookup 결과가 refactor 전 dict 와 동일해야 함 (단위 테스트로 검증).

참고:
- 행위 변경 ANGENT 분리: design.py LLM prompt 주입 (E1) 은 별도 PR. 이 파일은
  `llm_hint` 필드 자리만 만들어 두고 본 PR 에서는 미사용.
- Shin 영역 (`nodes_large/`) 의 LEGACY MAX_COUNT_BY_CATEGORY 는 vmd_constants 에서
  유지 (이 파일과 별도). 우리 영역 (`nodes_small/`) 만 SSOT 사용.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.vmd_constants import VMD_BOUNDARIES_BEAUTY


# ─────────────────────────────────────────────────────────────────────────
# Category dataclass
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Category:
    """brand_category 1개의 모든 룰을 보관.

    Fields:
        key: brand_category 키 (한글). lookup 의 단일 키.
        is_llm_extractable: BRAND_TOOL.brand_category enum 에 포함 여부.
            False 면 LLM 출력 안 됨 (수동/외부 입력 시에만 lookup).
        extras: MAX_COUNT_GENERIC 에 합성될 카테고리 cap override.
            예: 뷰티의 display_table=2 (generic 4 → 2 override).
            빈 dict = generic 만.
        boundaries: VMD 기물 규격. None = VMD_BOUNDARIES default 사용.
        cat_overrides: design.py `_default_intents` 의 ref_point 매칭 override.
            예: 캐릭터 IP 의 character_bbox 에 entrance_adjacent label 우선.
            빈 dict = generic _OBJ_PREFERENCE 만 사용.
        partition_pair: 가벽 (partition_wall_I/L) 짝꿍 후보 set.
            빈 dict = PARTITION_PAIR_GENERIC 만 사용.
        essential_supplement: 매뉴얼이 빠뜨려도 매장 운영 위해 반드시 추가될 기물 (#377 J).
            "매뉴얼 우선 + 카테고리별 essential 만 보충" 정책의 SSOT.
            예: 뷰티 = {"counter": 1, "display_table": 1} — 계산대 + 진열대 운영 최소.
            ───────────────────────────────────────────────────────────────
            object_selection.py:_default_placement_rules 가 사용:
              - brand 매뉴얼 placement_rules 있음: cat.essential_supplement | cat.extras
                (매뉴얼이 정한 풀 + 카테고리별 essential 보충 + extras override)
              - brand 매뉴얼 부재: MAX_COUNT_GENERIC | cat.extras (기존 generic 전체 fallback)
            ───────────────────────────────────────────────────────────────
            essential_supplement 빈 카테고리 (테크/아트/엔터):
              → DEFAULT_CATEGORY ("기타") 의 essential 사용 + logger.warning
            ───────────────────────────────────────────────────────────────
            도입 배경 (5-1):
              5-1 13:36 라이브 dump — 18평 뷰티 매뉴얼에서 placed=11 비대화 관찰.
              brand placement_rules + MAX_COUNT_GENERIC 합집합 메커니즘이 원인.
              매뉴얼 의도 (10개) + default 7개 - 겹침 ≈ 합집합 14-15개 → IQI cap 후 11.
              본 필드로 default 보충을 카테고리별 essential 1-3개로 축소 → placed 7-8 목표.
        minimal_placement_rules: 카테고리별 "운영상 absolute essential" 기물 set.
            ⚠ 검증 트리거 아님 (5-1 G 옵션 이후). 모니터링/통계용.
            ───────────────────────────────────────────────────────────────
            [의미 변천]
            - 4-30 (PR #366 c6f3dd9): 검증 트리거. 누락 시 BrandRulesResult.model_validator
              가 ValueError raise → harness retry → 3회 실패 → _fallback_brand_defaults()
              호출 → brand 전체 default 리셋. 잘못된 결합 (placement_rules 검증 실패가
              brand_category 등 다른 LLM 추출분까지 폐기시킴).
            - 5-1 (G 옵션): model_validator 제거. 본 set 은 reference.py 후처리에서
              logger.warning 발생 기준으로만 사용. brand 응답 LLM 추출분 항상 보존.
            ───────────────────────────────────────────────────────────────
            [재사용 백로그]
            - 부실 응답 패턴 통계 / 대시보드 (예: 카테고리별 누락율 추적)
            - 회귀 감지 (특정 카테고리에서 평소 안 나오던 누락 발생 시 알림)
            - 매뉴얼 품질 자동 평가 (LLM 이 핵심 풀 못 채우는 매뉴얼 = 매뉴얼 부실)
            ───────────────────────────────────────────────────────────────
            ⚠ 본 set 누락이 brand 추출 실패를 의미하지 않음. 매뉴얼에 해당 기물
            정보가 단순히 부재할 수 있음 (정상 상황). 검증 강제 X.
        llm_hint: design.py LLM prompt 주입 텍스트 (E1, 본 PR 미사용).
            예: "뷰티·코스메틱: 체험과 상담 위주 매장."
    """
    key: str
    is_llm_extractable: bool = True
    extras: dict = field(default_factory=dict)
    boundaries: dict | None = None
    cat_overrides: dict = field(default_factory=dict)
    partition_pair: dict = field(default_factory=dict)
    essential_supplement: dict = field(default_factory=dict)
    minimal_placement_rules: set = field(default_factory=set)
    llm_hint: str = ""


# ─────────────────────────────────────────────────────────────────────────
# 카테고리 등록 — 기존 5곳 흩어진 데이터를 통합. 행위 보존.
#
# 데이터 출처 (refactor 전):
#   - extras                : vmd_constants.CATEGORY_EXTRAS
#   - boundaries            : vmd_constants.VMD_BOUNDARIES_BY_CATEGORY
#   - cat_overrides         : nodes_small/design.py _CATEGORY_OVERRIDES
#   - partition_pair        : prompt_rules.PARTITION_PAIR_BY_CATEGORY
#   - minimal_placement_rules: nodes_small/reference.py _MINIMAL_PLACEMENT_RULES_BY_CATEGORY
# ─────────────────────────────────────────────────────────────────────────

_CATEGORIES: list[Category] = [
    # 캐릭터 IP — 메인 어트랙션(캐릭터 조형물) + 웨이팅/이벤트 키오스크
    Category(
        key="캐릭터 IP",
        is_llm_extractable=True,
        extras={
            "character_bbox": 4,
            "kiosk": 1,
        },
        boundaries=None,  # VMD_BOUNDARIES default
        cat_overrides={
            "character_bbox": {"labels": ["entrance_adjacent", "side_wall"], "allowed_directions": ["focal", "wall_facing"], "alignment": "parallel"},
            "photo_wall":     {"labels": ["side_wall"], "allowed_directions": ["wall_facing", "focal"], "alignment": "parallel"},
        },
        partition_pair={
            "partition_wall_I": {"shelf_wall", "shelf_3tier", "photo_wall", "display_table"},
            "partition_wall_L": {"shelf_wall"},
        },
        # 매뉴얼이 빠뜨려도 캐릭터 IP 매장 운영 필수 (#377 J)
        essential_supplement={"counter": 1, "photo_wall": 1},
        # 2026-05-01 minimal 약화 (옵션 C): 카테고리 정체성 1개만 강제. 캐릭터 IP 의
        # 정체성 = character_bbox. 매뉴얼에 캐릭터 표현 0건이면 정상 캐릭터 IP 매장 아니거나
        # LLM 분류 오류 → retry 합리적. 운영 필수 counter 는 generic 보충에 의존.
        minimal_placement_rules={"character_bbox"},
        llm_hint="",  # E1 후속 PR
    ),
    # 뷰티·코스메틱 — 체험·상담·진열 sub-zone 분리. consultation_desk + test_bar 강조.
    Category(
        key="뷰티·코스메틱",
        is_llm_extractable=True,
        extras={
            "display_table": 2,        # generic 4 → 2
            "shelf_wall": 3,           # generic 6 → 3
            "test_bar": 2,
            "consultation_desk": 2,
            "signage_stand": 1,
            "kiosk": 1,
            "partition_wall_I": 1,
            "aux_table": 1,
        },
        boundaries=VMD_BOUNDARIES_BEAUTY,
        cat_overrides={},  # ⚠ 4-30 진단 — 뷰티 cat_overrides 미등록 상태 유지 (E1 후속 PR 에서 추가)
        partition_pair={
            "partition_wall_I": {"shelf_wall", "shelf_3tier", "consultation_desk", "test_bar", "display_table"},
            "partition_wall_L": {"shelf_wall", "shelf_3tier"},
        },
        # 매뉴얼이 빠뜨려도 뷰티 매장 운영 필수 (#377 J)
        essential_supplement={"counter": 1, "display_table": 1},
        # 2026-05-01 minimal 약화 (옵션 C): 운영 필수 counter 만. 매뉴얼이 display_table /
        # shelf_wall 정보 없으면 LLM 도 못 만듦 → 강제하면 합리적 응답 reject 후 fallback.
        # 5-1 13:04 라이브 테스트에서 뷰티 매뉴얼에 display_table 없음 확인.
        minimal_placement_rules={"counter"},
        llm_hint="",
    ),
    # 패션 브랜드 — 진열 위주. shelf 다양성 + display_table.
    Category(
        key="패션 브랜드",
        is_llm_extractable=True,
        extras={},  # fashion 특화 기물 미등록 (worklist I-4)
        boundaries=None,
        cat_overrides={
            "shelf_wall":    {"labels": ["side_wall", "deep_wall"], "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
            "display_table": {"labels": ["center_freestanding"], "allowed_directions": ["center", "inward"], "alignment": "none"},
        },
        partition_pair={
            "partition_wall_I": {"shelf_wall", "shelf_3tier", "display_table"},
            "partition_wall_L": {"shelf_wall", "shelf_3tier"},
        },
        # 매뉴얼이 빠뜨려도 패션 매장 운영 필수 (#377 J)
        essential_supplement={"counter": 1, "display_table": 1, "shelf_wall": 1},
        # 2026-05-01 minimal 약화 (옵션 C): 운영 필수 counter 만.
        minimal_placement_rules={"counter"},
        llm_hint="",
    ),
    # F&B — 회전율 키오스크 + 메뉴판
    Category(
        key="F&B",
        is_llm_extractable=True,
        extras={
            "kiosk": 1,
            "signage_stand": 1,
        },
        boundaries=None,
        cat_overrides={
            "counter":       {"labels": ["deep_wall", "side_wall"], "allowed_directions": ["wall_facing", "inward"], "alignment": "parallel"},
            "display_table": {"labels": ["center_freestanding"], "allowed_directions": ["center", "inward"], "alignment": "none"},
        },
        partition_pair={
            "partition_wall_I": {"shelf_wall", "kiosk", "test_bar", "signage_stand"},
            "partition_wall_L": {"shelf_wall"},
        },
        # 매뉴얼이 빠뜨려도 F&B 매장 운영 필수 (#377 J)
        essential_supplement={"counter": 1, "display_table": 1},
        # 2026-05-01 minimal 약화 (옵션 C): 운영 필수 counter 만.
        minimal_placement_rules={"counter"},
        llm_hint="",
    ),
    # 테크·전자제품 — 시연 + 상담 + 스펙 안내. BRAND_TOOL.enum 미포함 (LLM 출력 X).
    Category(
        key="테크·전자제품",
        is_llm_extractable=False,
        extras={
            "test_bar": 2,
            "consultation_desk": 1,
            "signage_stand": 1,
        },
        boundaries=None,
        cat_overrides={},
        partition_pair={
            "partition_wall_I": {"shelf_wall", "test_bar", "consultation_desk", "signage_stand", "display_table"},
            "partition_wall_L": {"shelf_wall"},
        },
        minimal_placement_rules=set(),
        llm_hint="",
    ),
    # 아트·전시 — 작품 걸이 가벽 + 캡션 안내. BRAND_TOOL.enum 미포함.
    Category(
        key="아트·전시",
        is_llm_extractable=False,
        extras={
            "partition_wall_I": 2,
            "display_table_standard": 2,
            "signage_stand": 2,
        },
        boundaries=None,
        cat_overrides={},
        partition_pair={},
        minimal_placement_rules=set(),
        llm_hint="",
    ),
    # 엔터·팬미팅 — 아티스트 등신대. BRAND_TOOL.enum 미포함.
    Category(
        key="엔터·팬미팅",
        is_llm_extractable=False,
        extras={
            "character_bbox": 1,
        },
        boundaries=None,
        cat_overrides={},
        partition_pair={},
        minimal_placement_rules=set(),
        llm_hint="",
    ),
    # 기타 — fallback. CATEGORY_EXTRAS 미등록 상태 보존 (generic only).
    Category(
        key="기타",
        is_llm_extractable=True,
        extras={},
        boundaries=None,
        cat_overrides={},
        partition_pair={},
        # 매뉴얼이 빠뜨려도 매장 운영 필수 (#377 J).
        # 미등록 카테고리 (테크/아트/엔터) 는 DEFAULT_CATEGORY (= 기타) 의 essential 사용.
        essential_supplement={"counter": 1, "display_table": 1},
        # 2026-05-01 minimal 약화 (옵션 C): 운영 필수 counter 만.
        minimal_placement_rules={"counter"},
        llm_hint="",
    ),
]


CATEGORIES_BY_KEY: dict[str, Category] = {c.key: c for c in _CATEGORIES}

# 미등록 / unknown 카테고리 fallback. lookup 실패 시 이 인스턴스 반환.
DEFAULT_CATEGORY: Category = CATEGORIES_BY_KEY["기타"]


# ─────────────────────────────────────────────────────────────────────────
# 공용 lookup API
# ─────────────────────────────────────────────────────────────────────────

def get_category(key: str | None) -> Category:
    """카테고리 lookup. 미등록 / None → DEFAULT_CATEGORY ('기타')."""
    if not key:
        return DEFAULT_CATEGORY
    return CATEGORIES_BY_KEY.get(key, DEFAULT_CATEGORY)


def llm_extractable_keys() -> list[str]:
    """LLM 추출 가능 카테고리 키 목록 — BRAND_TOOL.brand_category enum 자동 생성용."""
    return [c.key for c in _CATEGORIES if c.is_llm_extractable]


def all_keys() -> list[str]:
    """등록된 모든 카테고리 키 목록 (LLM 추출 불가 포함)."""
    return [c.key for c in _CATEGORIES]


# ─────────────────────────────────────────────────────────────────────────
# 카테고리 흐름 추적 dump (라이브 검증용)
# ─────────────────────────────────────────────────────────────────────────
# 입력 brand_category 가 파이프라인 단계마다 어떻게 해석/사용되는지 추적.
# `debug_logs/YYYY-MM-DD/category_trace.json` 에 단계별 누적 기록.
# 사용자 라이브 테스트 시 카테고리 mismatch / 누락을 단계별로 식별 가능.

def dump_category_trace(stage: str, raw_brand_category, **extra_info) -> None:
    """카테고리 흐름 추적 dump. 단계별로 호출되어 한 파일에 누적.

    Args:
        stage: 호출 단계 라벨. 예: "brand_extracted", "object_selection",
               "design_llm_call", "design_default_intents".
        raw_brand_category: 입력 brand_category (str 또는 dict 형식 그대로).
        **extra_info: 단계별 추가 컨텍스트 (예: eligible_count, intents_count).

    Behavior:
        - JSON 파일 read-modify-write 로 누적 (req 1회당 약 4단계 호출 가정)
        - 같은 카테고리가 단계마다 어떻게 해석되는지 SSOT lookup 결과 함께 기록
        - DEBUG_LOG_DISABLED=1 환경변수 시 skip (운영 환경 IO 비용 회피)
    """
    import os as _os
    if _os.environ.get("DEBUG_LOG_DISABLED") == "1":
        return

    import json as _json
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    # raw 입력을 정규화하여 lookup
    normalized: str | None
    if isinstance(raw_brand_category, dict):
        normalized = raw_brand_category.get("value")
    elif isinstance(raw_brand_category, str):
        normalized = raw_brand_category
    else:
        normalized = None

    cat = get_category(normalized)
    is_known = bool(normalized) and normalized in CATEGORIES_BY_KEY
    fell_back = (not is_known) or (cat is DEFAULT_CATEGORY and normalized != DEFAULT_CATEGORY.key)

    # boundaries 출처 식별 (디버그용 라벨)
    from app.vmd_constants import VMD_BOUNDARIES_BEAUTY
    if cat.boundaries is None:
        boundaries_source = "default (VMD_BOUNDARIES)"
    elif cat.boundaries is VMD_BOUNDARIES_BEAUTY:
        boundaries_source = "VMD_BOUNDARIES_BEAUTY"
    else:
        boundaries_source = "custom"

    entry = {
        "stage": stage,
        "timestamp": _dt.now().isoformat(timespec="seconds"),
        "raw_input": raw_brand_category,
        "normalized_input": normalized,
        "ssot_resolved_key": cat.key,
        "is_known_category": is_known,
        "fell_back_to_default": fell_back,
        "is_llm_extractable": cat.is_llm_extractable,
        "extras_count": len(cat.extras),
        "extras_keys": sorted(cat.extras.keys()),
        "cat_overrides_count": len(cat.cat_overrides),
        "cat_overrides_keys": sorted(cat.cat_overrides.keys()),
        "partition_pair_count": len(cat.partition_pair),
        "partition_pair_keys": sorted(cat.partition_pair.keys()),
        "minimal_placement_rules": sorted(cat.minimal_placement_rules),
        "boundaries_source": boundaries_source,
        "extra": extra_info,
    }

    base_dir = _Path(__file__).parent.parent / "debug_logs" / _dt.now().strftime("%Y-%m-%d")
    base_dir.mkdir(parents=True, exist_ok=True)
    trace_file = base_dir / "category_trace.json"

    if trace_file.exists():
        try:
            with trace_file.open(encoding="utf-8") as f:
                trace = _json.load(f)
            if not isinstance(trace, list):
                trace = []
        except Exception:
            trace = []
    else:
        trace = []
    trace.append(entry)

    with trace_file.open("w", encoding="utf-8") as f:
        _json.dump(trace, f, ensure_ascii=False, indent=2)
