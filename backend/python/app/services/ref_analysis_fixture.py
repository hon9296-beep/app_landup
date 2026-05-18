"""
ref_analysis 검증용 fixture loader.

용도:
  - 검증 인프라 (Phase 1) 의 counterfactual 테스트 — 실제 analyzer 출력을 다른 카테고리로 swap.
  - 같은 도면 + 같은 카테고리 조건에서 ref_analysis 만 다르게 주입 → 결과 변화 측정.
  - 환경변수 REF_FIXTURE_CATEGORY 로 활성화. design.py 가 이 로더를 참조.

사용 예:
    REF_FIXTURE_CATEGORY=character_ip python -m ...
    → design.py 가 ref_image_analyzer 의 실제 결과 무시하고 character_ip fixture 로 swap.

Fixture 위치: backend/python/tests/fixtures/ref_analysis/{slug}.json
필요한 키: layout_patterns / focal_points / flow_description / density_impression /
          space_mood / composition_principle / partition_usage / design_highlights
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# tests/ 는 production 패키지 외부지만 fixture 데이터로만 사용 (코드 import 안 함).
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ref_analysis"

_VALID_KEYS = {
    "layout_patterns",
    "partition_usage",
    "focal_points",
    "flow_description",
    "density_impression",
    "space_mood",
    "composition_principle",
    "design_highlights",
}


def list_available_categories() -> list[str]:
    """현재 fixture 가 있는 카테고리 slug 목록."""
    if not _FIXTURE_DIR.exists():
        return []
    return sorted(p.stem for p in _FIXTURE_DIR.glob("*.json"))


def load_fixture(category_slug: str) -> Optional[dict]:
    """slug → ref_analysis dict. 파일 없거나 깨졌으면 None.

    반환 dict 는 ref_image_analyzer 의 실제 result 형식과 동일 (평면 dict).
    __meta 필드는 logger 용으로 분리 후 제거.
    """
    if not category_slug:
        return None
    path = _FIXTURE_DIR / f"{category_slug}.json"
    if not path.exists():
        logger.warning(
            "[ref_fixture] 카테고리 fixture 없음: %s (사용 가능: %s)",
            category_slug, list_available_categories(),
        )
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[ref_fixture] %s 로드 실패: %s", path.name, e)
        return None

    meta = data.pop("__meta", {})
    # __meta 외 다른 모르는 키는 보존 (LLM 결과 schema 변동 대비)
    cleaned = {k: v for k, v in data.items() if not k.startswith("__")}
    logger.info(
        "[ref_fixture] swap → %s (source=%s, patterns=%d, focals=%d)",
        category_slug,
        meta.get("source", "?"),
        len(cleaned.get("layout_patterns", [])),
        len(cleaned.get("focal_points", [])),
    )
    return cleaned
