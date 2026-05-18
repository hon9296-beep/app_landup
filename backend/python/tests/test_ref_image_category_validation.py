"""
ref_image 카테고리 부합 검증 (1-3 #523) 단위 테스트.

5-7 진단에서 발견된 회귀: 뷰티 폴더에 TENGA / 바른생각 같은 비-뷰티 (성인용품) 이미지
혼재 → ref_analysis 가 카테고리 mismatch 결과로 design LLM 한테 전달 → 배치 결과 오염.

Fix:
  - VisionAnalysisResult 에 rejected_image_indices / rejected_image_reasons 필드
  - tool schema 동기
  - analyzer 가 per-image rejected 를 ref_image_loader 의 _rejected_hashes.json 에 등록
  - loader 가 다음 다운로드 전 _rejected_hashes 체크 → 같은 이미지 재다운로드 차단

본 테스트는 mock LLM 호출 비용 회피 — schema / file IO contract 만 검증.
"""
import json
import pytest

from app.nodes_small.ref_image_analyzer import VisionAnalysisResult, _write_local_rejected_hashes
from app.nodes_small.ref_image_loader import _load_rejected_hashes
from app.nodes_small.prompts.ref_image_analyzer import VISION_ANALYSIS_TOOL


# ── 모델 schema 검증 ───────────────────────────────────────────────


def test_vision_result_has_rejected_fields():
    """1-3 신규 필드: rejected_image_indices / rejected_image_reasons. default = 빈 list."""
    r = VisionAnalysisResult()
    assert r.rejected_image_indices == []
    assert r.rejected_image_reasons == []


def test_vision_result_accepts_rejected_data():
    """rejected 인덱스 + 사유 list 정상 받음."""
    r = VisionAnalysisResult(
        rejected_image_indices=[1, 3],
        rejected_image_reasons=["TENGA 사인 — 성인용품", "음식점 — 카테고리 불일치"],
    )
    assert r.rejected_image_indices == [1, 3]
    assert len(r.rejected_image_reasons) == 2


def test_vision_result_default_is_real_photo_true():
    """is_real_photo default = True (회귀 차단 — 기존 동작 유지)."""
    r = VisionAnalysisResult()
    assert r.is_real_photo is True


# ── tool schema 동기 검증 ───────────────────────────────────────────


def test_tool_schema_includes_rejected_fields():
    """Anthropic tool_use schema 에 rejected_image_indices/reasons 포함 + required."""
    props = VISION_ANALYSIS_TOOL["input_schema"]["properties"]
    required = VISION_ANALYSIS_TOOL["input_schema"]["required"]
    assert "rejected_image_indices" in props
    assert "rejected_image_reasons" in props
    assert "rejected_image_indices" in required
    assert "rejected_image_reasons" in required
    assert props["rejected_image_indices"]["type"] == "array"
    assert props["rejected_image_indices"]["items"]["type"] == "integer"


# ── _rejected_hashes.json 파일 IO contract ──────────────────────────


def test_load_rejected_hashes_empty_folder(tmp_path):
    """폴더에 _rejected_hashes.json 없으면 빈 set."""
    assert _load_rejected_hashes(tmp_path) == set()


def test_load_rejected_hashes_existing_file(tmp_path):
    """_rejected_hashes.json 있으면 sha256 list set 반환."""
    hashes = ["a" * 64, "b" * 64, "c" * 64]
    (tmp_path / "_rejected_hashes.json").write_text(
        json.dumps(hashes), encoding="utf-8"
    )
    loaded = _load_rejected_hashes(tmp_path)
    assert loaded == set(hashes)


def test_load_rejected_hashes_corrupt_file(tmp_path):
    """JSON parse 실패 시 graceful 빈 set 반환 (회귀 차단)."""
    (tmp_path / "_rejected_hashes.json").write_text("invalid json", encoding="utf-8")
    assert _load_rejected_hashes(tmp_path) == set()


def test_write_local_rejected_hashes_empty_input():
    """빈 input → noop. 예외 안 남."""
    _write_local_rejected_hashes([])  # raise 안 하면 OK


def test_write_local_rejected_hashes_creates_file(tmp_path, monkeypatch):
    """rejected hash 박으면 카테고리 폴더에 _rejected_hashes.json 생성."""
    # IMAGES_DIR 을 tmp 로 patch
    import app.nodes_small.ref_image_loader as loader_mod
    monkeypatch.setattr(loader_mod, "IMAGES_DIR", tmp_path)

    sha_list = [("a" * 64, "beauty"), ("b" * 64, "beauty"), ("c" * 64, "fnb")]
    _write_local_rejected_hashes(sha_list)

    beauty_file = tmp_path / "beauty" / "_rejected_hashes.json"
    fnb_file = tmp_path / "fnb" / "_rejected_hashes.json"
    assert beauty_file.exists()
    assert fnb_file.exists()
    beauty_hashes = json.loads(beauty_file.read_text(encoding="utf-8"))
    fnb_hashes = json.loads(fnb_file.read_text(encoding="utf-8"))
    assert "a" * 64 in beauty_hashes
    assert "b" * 64 in beauty_hashes
    assert len(beauty_hashes) == 2
    assert "c" * 64 in fnb_hashes


def test_write_local_rejected_hashes_appends_existing(tmp_path, monkeypatch):
    """기존 _rejected_hashes.json 있으면 append (덮어쓰기 X — 회귀 차단)."""
    import app.nodes_small.ref_image_loader as loader_mod
    monkeypatch.setattr(loader_mod, "IMAGES_DIR", tmp_path)

    folder = tmp_path / "beauty"
    folder.mkdir()
    (folder / "_rejected_hashes.json").write_text(
        json.dumps(["existing_hash_64chars" + "x" * (64 - len("existing_hash_64chars"))]),
        encoding="utf-8",
    )

    sha_list = [("new_hash_64chars" + "x" * (64 - len("new_hash_64chars")), "beauty")]
    _write_local_rejected_hashes(sha_list)

    final = json.loads((folder / "_rejected_hashes.json").read_text(encoding="utf-8"))
    assert len(final) == 2  # existing + new


def test_write_local_rejected_hashes_dedup(tmp_path, monkeypatch):
    """중복 hash 박아도 set 처리 → 1번만 저장."""
    import app.nodes_small.ref_image_loader as loader_mod
    monkeypatch.setattr(loader_mod, "IMAGES_DIR", tmp_path)

    sha_list = [("a" * 64, "beauty"), ("a" * 64, "beauty")]
    _write_local_rejected_hashes(sha_list)
    final = json.loads((tmp_path / "beauty" / "_rejected_hashes.json").read_text(encoding="utf-8"))
    assert len(final) == 1
