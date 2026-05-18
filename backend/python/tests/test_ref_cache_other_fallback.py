"""ref_image_loader #489 — other fallback 폐기 검증.

이전: 카테고리 폴더 없으면 other/ fallback → 카테고리별 DDG 검색 영구히 trigger X
현재: 폴더 없으면 그대로 반환 → 호출자가 not exists → 빈 list → DDG 검색 trigger
"""
from __future__ import annotations

from pathlib import Path

from app.nodes_small.ref_image_loader import (
    _resolve_folder,
    _load_local_images_with_meta,
)


def test_resolve_folder_returns_target_path_even_when_missing(tmp_path):
    """카테고리 폴더 없을 때 other 로 fallback 안 함 — 본래 카테고리 path 반환."""
    base = tmp_path / "images"
    base.mkdir()
    (base / "other").mkdir()
    (base / "other" / "ref_dummy.jpg").write_bytes(b"x")

    # beauty 카테고리 폴더 없음. for_save=False (LOAD).
    result = _resolve_folder(base, "뷰티·코스메틱", for_save=False)

    # other 가 아닌 beauty path 반환 (fallback 폐기)
    assert result.name == "beauty", f"other fallback 발동 — {result}"
    assert not result.exists(), "원래 없는 폴더 그대로"


def test_resolve_folder_existing_returns_self(tmp_path):
    """카테고리 폴더 존재 시 그대로 반환 (정상 케이스)."""
    base = tmp_path / "images"
    base.mkdir()
    (base / "beauty").mkdir()

    result = _resolve_folder(base, "뷰티·코스메틱", for_save=False)
    assert result.name == "beauty"
    assert result.exists()


def test_resolve_folder_for_save_unchanged(tmp_path):
    """for_save=True 동작 변경 없음 (SAVE 분리 정책 보존)."""
    base = tmp_path / "images"
    base.mkdir()
    (base / "other").mkdir()

    result = _resolve_folder(base, "뷰티·코스메틱", for_save=True)
    assert result.name == "beauty"
    assert not result.exists()  # SAVE 는 caller 가 mkdir


def test_load_local_returns_empty_when_category_folder_missing(tmp_path, monkeypatch):
    """카테고리 폴더 없을 때 _load_local_images_with_meta 가 빈 list 반환 → DDG trigger 조건."""
    import app.nodes_small.ref_image_loader as loader_mod
    base = tmp_path / "images"
    base.mkdir()
    (base / "other").mkdir()
    (base / "other" / "ref_should_not_be_used.jpg").write_bytes(b"x" * 100)
    monkeypatch.setattr(loader_mod, "IMAGES_DIR", base)

    images, meta = _load_local_images_with_meta("뷰티·코스메틱")
    assert images == [], f"other fallback 발동 — beauty 가 other 캐시 사용함: {len(images)}장"
    assert meta["total_candidates"] == 0
