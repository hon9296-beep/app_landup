"""
references/images/{slug}/ 의 기존 디스크 이미지를 Java DB ref_image 테이블에 일괄 적재.

용도:
  - DDG 다운로드는 디스크 저장만 하던 시절(register_ref_image 호출 누락 상태)에 쌓인
    이미지를 admin 페이지에서 조회 가능하게 만든다.
  - userProjectId 는 None (어느 프로젝트의 다운로드인지 추적 불가). admin 자산으로만 등록.
  - floorSizeTier 는 'medium' default (당시 프로젝트 면적 정보 없음).

실행:
  python scripts/backfill_ref_images.py [--dry-run]

전제:
  - JAVA_API_BASE 가동 중 (default http://localhost:8081/api)
  - REF_IMAGE_HANDOFF_ENABLED=1 (없으면 ref_image_client 가 즉시 None 반환 → no-op)
  - brand_categories 테이블이 정본 slug 8종으로 seed 되어 있음

idempotent: Java 측 unique constraint (userProjectId, imageSha256) 가 중복 거부.
재실행해도 이미 적재된 row 는 새로 추가되지 않음.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path

# project_root 추가 (scripts/ 에서 직접 실행 가능하게)
_THIS = Path(__file__).resolve()
_PYTHON_ROOT = _THIS.parents[1]
sys.path.insert(0, str(_PYTHON_ROOT))

from app.clients.ref_image_client import register_ref_image  # noqa: E402
from app.services.brand_category_lookup import lookup_brand_category_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_ref_images")

# ref_image_loader.CATEGORY_FOLDER 와 1:1 일치해야 함 (정본 slug)
KNOWN_SLUGS = ("character_ip", "fashion", "fnb", "beauty", "tech", "art", "entertainment", "other")

# 한글 폴더명 → slug 매핑 (잔재 마이그레이션). 영문 slug 폴더와 동시 존재 가능.
LEGACY_KOREAN_FOLDERS = {
    "캐릭터IP": "character_ip",
    "캐릭터 IP": "character_ip",
    "패션브랜드": "fashion",
    "패션 브랜드": "fashion",
    "F&B": "fnb",
    "뷰티·코스메틱": "beauty",
    "뷰티코스메틱": "beauty",
    "테크·전자제품": "tech",
    "아트·전시": "art",
    "엔터·팬미팅": "entertainment",
    "기타": "other",
}

DEFAULT_TIER = "medium"


def _resolve_images_dir() -> Path:
    """ref_image_loader 와 동일한 도커/로컬 경로 자동 선택."""
    docker_path = Path("/references/images")
    if docker_path.exists():
        return docker_path
    return _PYTHON_ROOT.parents[1] / "references" / "images"


def _slug_from_folder_name(name: str) -> str | None:
    if name in KNOWN_SLUGS:
        return name
    if name in LEGACY_KOREAN_FOLDERS:
        return LEGACY_KOREAN_FOLDERS[name]
    return None


def _scan_files(images_dir: Path) -> list[tuple[str, Path]]:
    """images_dir 하위 폴더 순회. (slug, file_path) 리스트 반환."""
    out: list[tuple[str, Path]] = []
    if not images_dir.exists():
        logger.warning("images_dir 없음: %s", images_dir)
        return out
    for sub in images_dir.iterdir():
        if not sub.is_dir():
            continue
        slug = _slug_from_folder_name(sub.name)
        if slug is None:
            logger.warning("[skip] 알 수 없는 폴더 (slug 매핑 없음): %s", sub.name)
            continue
        # ref_*.{jpg,png,webp} — _hashes.json 등 메타 파일 제외
        for f in sub.rglob("ref_*"):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                out.append((slug, f))
    return out


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="실제 register 호출 없이 시뮬레이션만")
    parser.add_argument("--tier", default=DEFAULT_TIER, choices=["small", "medium", "large", "outdoor"])
    args = parser.parse_args()

    if not args.dry_run and os.environ.get("REF_IMAGE_HANDOFF_ENABLED") != "1":
        logger.error("REF_IMAGE_HANDOFF_ENABLED=1 필요. 환경변수 설정 후 재실행.")
        sys.exit(2)

    images_dir = _resolve_images_dir()
    logger.info("images_dir = %s", images_dir)
    files = _scan_files(images_dir)
    logger.info("scan 결과: %d 파일", len(files))

    # slug → brandCategoryId 캐시 1회 prewarm
    bcid_cache: dict[str, int | None] = {}
    for slug in {s for s, _ in files}:
        bcid_cache[slug] = lookup_brand_category_id(slug) if not args.dry_run else -1
        logger.info("  slug=%s → brand_category_id=%s", slug, bcid_cache[slug])

    stats = {"attempted": 0, "registered": 0, "skipped_no_bcid": 0, "failed": 0}
    for slug, fp in files:
        bcid = bcid_cache.get(slug)
        if bcid is None:
            stats["skipped_no_bcid"] += 1
            continue
        stats["attempted"] += 1
        try:
            sha = _sha256_of(fp)
            size = fp.stat().st_size
            payload = {
                "userProjectId": None,
                "brandCategoryId": bcid,
                "imageSha256": sha,
                "floorSizeTier": args.tier,
                "searchKeyword": None,
                "sourceUrl": None,
                "filePath": f"references/images/{slug}/{fp.name}",
                "fileSizeBytes": size,
                "refPath": "backfill (디스크 기존 자료)",
            }
            if args.dry_run:
                logger.info("[dry-run] %s → bcid=%s sha=%s..", fp.name, bcid, sha[:12])
                stats["registered"] += 1
            else:
                # 2026-04-29 S3 통합: image_bytes 같이 전송 → Java 가 S3 업로드 + s3Url 채움.
                img_bytes = fp.read_bytes()
                ext = fp.suffix.lower().lstrip(".")
                media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
                result = register_ref_image(
                    payload=payload,
                    image_bytes=img_bytes,
                    image_filename=fp.name,
                    image_content_type=media_type,
                )
                if result is None:
                    stats["failed"] += 1
                    logger.warning("[fail] %s — register None (중복/네트워크/검증 실패)", fp.name)
                else:
                    stats["registered"] += 1
                    logger.info("[ok] %s → id=%s", fp.name, result.get("id"))
        except Exception as e:
            stats["failed"] += 1
            logger.error("[err] %s: %s", fp.name, e)

    logger.info("=" * 40)
    logger.info("결과: %s", stats)


if __name__ == "__main__":
    main()
