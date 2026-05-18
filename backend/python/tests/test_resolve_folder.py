"""
_resolve_folder 버그 회귀 방지 (2026-04-23).

기존 버그: `_resolve_folder` 가 LOAD/SAVE 구분 없이 neighbor `other/` 폴더
 존재 시 fallback 했음. 결과: 신규 카테고리(예: tech, fashion) 첫 DDG 저장 시
 `other/` 폴더에 섞여 들어가 영구적 카테고리 오염.

픽스: `for_save=True` 일 땐 fallback 금지. target 폴더 그대로 반환 → caller mkdir.
"""
import pytest
from pathlib import Path

from app.nodes_small.ref_image_loader import _resolve_folder


BEAUTY = "뷰티\xb7코스메틱"  # "뷰티·코스메틱"
TECH = "테크\xb7전자제품"     # "테크·전자제품"
FASHION = "패션 브랜드"            # "패션 브랜드"


# ── LOAD 모드 (for_save=False, 기본값) ────────────────────────────────────

def test_load_target_folder_exists_returns_target(tmp_path: Path):
    """beauty/ 가 실제 존재하면 beauty/ 반환 (fallback 타지 않음)."""
    (tmp_path / "beauty").mkdir()
    (tmp_path / "other").mkdir()  # fallback 후보 존재

    result = _resolve_folder(tmp_path, BEAUTY)
    assert result == tmp_path / "beauty"


def test_load_target_missing_returns_target_not_other(tmp_path: Path):
    """[#489 — 2026-05-05] LOAD 모드 other fallback 폐기.

    이전: target 없고 other/ 있으면 other/ fallback → 카테고리별 DDG 검색 영구히 trigger X.
    현재: target 폴더 path 그대로 반환 → 호출자 not exists 체크 → 빈 list → DDG trigger.
    """
    (tmp_path / "other").mkdir()
    # tech 폴더 없음

    result = _resolve_folder(tmp_path, TECH)
    assert result == tmp_path / "tech", \
        "LOAD 모드도 other fallback 폐기. 신규 카테고리 첫 호출 시 DDG 검색 trigger 보장"


def test_load_both_missing_returns_target(tmp_path: Path):
    """LOAD 모드에서 target, other 둘 다 없으면 target 반환 (caller 가 존재 체크)."""
    # 아무 폴더도 안 만듦

    result = _resolve_folder(tmp_path, FASHION)
    assert result == tmp_path / "fashion"


# ── SAVE 모드 (for_save=True) — 버그 픽스 핵심 ─────────────────────────────

def test_save_target_missing_other_exists_returns_target_not_other(tmp_path: Path):
    """핵심 회귀 방지: SAVE 모드는 other/ 존재해도 target 반환.

    이전 버그: tech 폴더 없고 other 있으면 other 반환 → DDG 결과가 other/ 에 저장됨.
    픽스 후: tech 폴더 없어도 tech 반환 → caller 가 mkdir 로 생성 후 tech/ 에 저장.
    """
    (tmp_path / "other").mkdir()
    # tech 폴더 없음

    result = _resolve_folder(tmp_path, TECH, for_save=True)
    assert result == tmp_path / "tech", \
        "SAVE 모드는 other/ fallback 금지. 신규 카테고리는 target 폴더 그대로 반환해야 함"


def test_save_target_exists_returns_target(tmp_path: Path):
    """SAVE 모드에서 target 이미 있어도 정상 반환."""
    (tmp_path / "beauty").mkdir()

    result = _resolve_folder(tmp_path, BEAUTY, for_save=True)
    assert result == tmp_path / "beauty"


def test_save_unknown_category_returns_other(tmp_path: Path):
    """CATEGORY_FOLDER 매핑 없는 카테고리는 SAVE 시에도 'other' 반환.

    (기본값 'other' 는 fallback 이 아닌 '미지정 카테고리의 공식 목적지')
    """
    result = _resolve_folder(tmp_path, "존재하지 않는 카테고리", for_save=True)
    assert result == tmp_path / "other"


# ── 기존 LOAD 동작 보존 확인 ─────────────────────────────────────────────

def test_load_unknown_category_falls_back_to_other(tmp_path: Path):
    """LOAD 모드에서 미지정 카테고리는 other 매핑 → other/ 존재 시 other 반환."""
    (tmp_path / "other").mkdir()

    result = _resolve_folder(tmp_path, "존재하지 않는 카테고리")
    assert result == tmp_path / "other"
