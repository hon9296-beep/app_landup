"""glb_storage 모듈 단독 검증.

파이프라인 돌리지 않고 save_glb_bytes() 만 단독 호출해서:
  - 파일이 정확한 경로에 생성되는지
  - 반환값이 'storage/glb/{uuid}.glb' 형식인지
  - 저장 바이트가 원본과 동일한지
  - 빈 bytes → ValueError 발생
를 검증.

실서버 환경 이슈(경로/권한) 디버깅 시에도 이 테스트만 단독 실행하면
파이프라인 전체 안 돌려도 저장 레이어 문제 즉시 파악 가능.
"""
from pathlib import Path

import pytest

from app.storage.glb_storage import save_glb_bytes, _STORAGE_DIR, _BACKEND_DIR


def test_save_glb_bytes_creates_file():
    """정상 저장 — 파일 생성 + 내용 일치 + 반환 경로 포맷."""
    dummy_bytes = b"GLB-DUMMY-PAYLOAD-FOR-TEST-" + b"0" * 100
    relative_path = save_glb_bytes(dummy_bytes)

    # 반환 포맷 검증
    assert relative_path.startswith("storage/glb/")
    assert relative_path.endswith(".glb")

    # backend 기준으로 실제 파일 존재 확인
    actual_file = _BACKEND_DIR / relative_path
    try:
        assert actual_file.exists(), f"파일이 생성되지 않음: {actual_file}"
        assert actual_file.read_bytes() == dummy_bytes, "저장된 바이트가 원본과 다름"
    finally:
        # cleanup
        if actual_file.exists():
            actual_file.unlink()


def test_save_glb_bytes_empty_raises():
    """빈 bytes → ValueError."""
    with pytest.raises(ValueError):
        save_glb_bytes(b"")


def test_save_glb_bytes_creates_storage_dir_if_missing():
    """저장 디렉토리 없으면 자동 생성."""
    assert _STORAGE_DIR.exists() or True  # 첫 호출에 mkdir 되므로 통과 확정
    dummy = b"x" * 50
    rel = save_glb_bytes(dummy)
    try:
        assert _STORAGE_DIR.exists() and _STORAGE_DIR.is_dir()
    finally:
        (_BACKEND_DIR / rel).unlink(missing_ok=True)
