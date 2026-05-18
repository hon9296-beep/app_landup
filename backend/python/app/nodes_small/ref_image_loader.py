"""
레퍼런스 이미지 로더 노드 — Shin reference_search.py 복원.

로드 전략 (Shin 원본 방식):
  1. 로컬 캐시 먼저 (references/images/{카테고리}/ref_*)
  2. 없으면 Tavily 검색 → 다운로드 → 로컬 저장 (다음엔 안 검색)
  3. SHA256 해시로 중복 이미지 방지
  4. 3.5MB 초과 시 리사이즈 (Claude API 5MB 제한)
  5. 배치 예시 JSON 로드 (layouts/)
"""
import base64
import hashlib
import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from app.state import SmallState

logger = logging.getLogger(__name__)

# 도커·로컬 경로 자동 선택 (project_root/references/ 로 수렴).
# - 도커: docker-compose 가 ./references 를 /references 로 마운트 → 즉시 선택
# - 로컬: __file__ = backend/python/app/nodes_small/ref_image_loader.py → parents[4] = project_root
# 도커 경로 체크를 먼저 해서 parents[4] IndexError (컨테이너 내부 /app/... 깊이 부족) 회피.
_DOCKER_PATH = Path("/references")
if _DOCKER_PATH.exists():
    REFERENCES_DIR = _DOCKER_PATH
else:
    REFERENCES_DIR = Path(__file__).resolve().parents[4] / "references"
IMAGES_DIR = REFERENCES_DIR / "images"
LAYOUTS_DIR = REFERENCES_DIR / "layouts"

# [중요/회귀방지] 2026-04-20: 한글 폴더명 → 영문 slug 교체.
# 이유: cross-platform 인코딩 불일치 (Windows cp949 vs Linux UTF-8), Docker 볼륨 마운트,
# S3/nginx 경로, CLI shell escape 등에서 한글 경로는 장기적으로 깨지기 쉬움.
# 임시 공존 전략: Small 신규 검색은 영문 slug 경로로 저장. 기존 한글 폴더는 Large 파이프라인
# (Shin 영역)이 계속 쓰므로 보존. Shin과 협의 후 양쪽 영문 slug 통일 시 한글 폴더 정리.
# 참고: reports/AD/2026-04-20_small_store_backlog.md F-9 (영문 slug 전면 전환)
CATEGORY_FOLDER = {
    "\uce90\ub9ad\ud130 IP": "character_ip",
    "\ud328\uc158 \ube0c\ub79c\ub4dc": "fashion",
    "F&B": "fnb",
    "\ubdf0\ud2f0\xb7\ucf54\uc2a4\uba54\ud2f1": "beauty",
    "\ud14c\ud06c\xb7\uc804\uc790\uc81c\ud488": "tech",
    "\uc544\ud2b8\xb7\uc804\uc2dc": "art",
    "\uc5d4\ud130\xb7\ud32c\ubbf8\ud305": "entertainment",
    "\uae30\ud0c0": "other",
}

# 검색 키워드 / 필터 — #491 prompts 중앙화 (nodes_small/prompts/ref_image_loader.py)
from app.nodes_small.prompts.ref_image_loader import (
    CATEGORY_KEYWORDS,
    SEARCH_SUFFIX,
    PINTEREST_FILTER,
)

MAX_IMAGES = 5
MAX_LAYOUTS = 2
MAX_IMAGE_BYTES = 3_500_000  # 3.5MB

# 4-tier 평형 임계 (Java RefImage.FloorSizeTier 와 일치).
# 5~20평(16.5~66m²)=small / 20~50평(66~165m²)=medium / 50평~(165m²~)=large / outdoor 별도
_TIER_SMALL_MAX_M2 = 66
_TIER_MEDIUM_MAX_M2 = 165


def _compute_floor_size_tier(state) -> str:
    """state.usable_poly 면적 → ref_image FloorSizeTier 4-tier 매핑.

    outdoor 는 별도 플래그가 필요해 면적만으로는 판정 불가 → small/medium/large 만 반환.
    면적 미상이면 'medium' default (가장 안전한 중립값).
    """
    usable_poly = state.get("usable_poly") if hasattr(state, "get") else None
    if not usable_poly:
        return "medium"
    area_m2 = usable_poly.area / 1_000_000
    if area_m2 < _TIER_SMALL_MAX_M2:
        return "small"
    if area_m2 < _TIER_MEDIUM_MAX_M2:
        return "medium"
    return "large"


def run(state: SmallState) -> SmallState:
    """로컬 우선 → DDG+Pinterest fallback → 이미지 + 배치 예시 반환.

    reference_meta 필드에 검색 결정/통계/이미지별 메타를 함께 기록해 추적성 확보.
    """
    brand_data = state.get("brand_data") or {}
    design_concept = state.get("design_concept") or {}

    category = brand_data.get("brand", {}).get("brand_category", "\uae30\ud0c0")
    if isinstance(category, dict):
        category = category.get("value", "\uae30\ud0c0") or "\uae30\ud0c0"

    # concept_gen이 생성한 검색 키워드 (있으면 DDG 검색에 활용)
    concept_keywords = design_concept.get("search_keywords") or []

    category_slug = CATEGORY_FOLDER.get(category, "other")
    user_project_id = state.get("user_project_id")
    floor_size_tier = _compute_floor_size_tier(state)
    meta: dict = {
        "category": category,
        "category_slug": category_slug,
        "concept_keywords_from_design": concept_keywords,
        "max_images_cap": MAX_IMAGES,
        "pinterest_filter": PINTEREST_FILTER,
        "source": None,  # "local_cache" | "ddg_pinterest" | "empty"
        "search_decision": None,
        "search_stats": None,
        "images_meta": [],
        "handoff": {
            "user_project_id": user_project_id,
            "floor_size_tier": floor_size_tier,
            "category_slug": category_slug,
        },
    }

    # 1. 로컬 캐시에서 로드
    images, local_meta = _load_local_images_with_meta(category)
    if images:
        meta["source"] = "local_cache"
        meta["search_decision"] = {
            "reason": "로컬 캐시에 이미지 존재 — DDG 검색 건너뜀 (rate limit + 재현성 보호)",
            "folder": str(local_meta.get("folder", "")),
            "total_candidates": local_meta.get("total_candidates", 0),
        }
        meta["search_stats"] = {"selected_count": len(images), "from_cache": True}
        meta["images_meta"] = local_meta.get("images_meta", [])

        # Java handoff (A 안: 프로젝트별 row).
        # 같은 (user_project_id, sha256) 은 unique constraint 로 중복 거부 → idempotent.
        # user_project_id None (단독 노드 호출 등) 이면 skip — backfill 스크립트가 카탈로그 적재 담당.
        if user_project_id is not None:
            _register_local_images(local_meta, user_project_id, floor_size_tier, category_slug)

    # 2. 로컬에 없으면 DDG+Pinterest 검색 → 다운로드 → 저장 → Java handoff
    if not images:
        images, search_meta = _search_and_save_with_meta(
            category,
            concept_keywords,
            user_project_id=user_project_id,
            floor_size_tier=floor_size_tier,
            category_slug=category_slug,
        )
        if images:
            meta["source"] = "ddg_pinterest"
        else:
            meta["source"] = "empty"
        meta["search_decision"] = search_meta.get("decision", {})
        meta["search_stats"] = search_meta.get("stats", {})
        meta["images_meta"] = search_meta.get("images_meta", [])

    # 3. 배치 예시 (layouts/ 폴더)
    examples = _load_layout_examples(category)
    meta["layout_examples_count"] = len(examples)

    logger.info(
        "[ref_image_loader] category=%s, source=%s, images=%d, layouts=%d",
        category, meta["source"], len(images), len(examples),
    )
    return {
        "reference_images": images,
        "layout_examples": examples,
        "reference_meta": meta,
    }


# ── Java handoff: 로컬 캐시 분기 register ─────────────────────────────────

def _register_local_images(local_meta: dict, user_project_id: int, floor_size_tier: str, category_slug: str) -> None:
    """로컬 캐시에서 로드된 이미지들을 Java ref_image 테이블에 (project별) 등록.

    각 이미지 파일을 다시 읽어 SHA256(64자 full) 재계산 — _load_local_images_with_meta 가
    저장하는 hash_prefix(12자) 만으로는 Java DTO 검증 통과 불가.
    실패는 silent — 파이프라인 무중단 (ref_image_client._enabled() 체크 + 네트워크 graceful).
    """
    import hashlib as _hashlib
    from app.clients.ref_image_client import register_ref_image as _reg
    from app.services.brand_category_lookup import lookup_brand_category_id as _bid

    bcid = _bid(category_slug)
    if bcid is None:
        logger.debug("[ref_image_loader] local register skip — slug %s lookup 실패", category_slug)
        return

    for img_meta in local_meta.get("images_meta", []):
        rel_path = img_meta.get("local_path")
        if not rel_path:
            continue
        file_path = IMAGES_DIR / rel_path
        try:
            img_bytes = file_path.read_bytes()
            full_sha = _hashlib.sha256(img_bytes).hexdigest()
            # 2026-04-29 S3 통합: 로컬 캐시 재사용도 image_bytes 같이 전송 → Java 가 S3 업로드 + s3Url 채움
            _reg(
                payload={
                    "userProjectId": user_project_id,
                    "brandCategoryId": bcid,
                    "imageSha256": full_sha,
                    "floorSizeTier": floor_size_tier,
                    "searchKeyword": None,
                    "sourceUrl": None,
                    "filePath": f"references/images/{rel_path}".replace("\\", "/"),
                    "fileSizeBytes": img_meta.get("size_bytes"),
                    "refPath": "로컬 캐시 재사용",
                },
                image_bytes=img_bytes,
                image_filename=file_path.name,
                image_content_type=img_meta.get("media_type") or "image/jpeg",
            )
        except Exception as e:
            logger.debug("[ref_image_loader] local register 실패 %s: %s", file_path, e)


# ── 로컬 이미지 로드 ────────────────────────────────────────────────────

_MEDIA_TYPE = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _load_local_images_with_meta(category: str) -> tuple[list, dict]:
    """로컬 캐시에서 ref_* 이미지 로드 + 메타 반환.

    Returns: (images, meta)
      meta = {"folder": Path, "total_candidates": N, "images_meta": [{path, zone, size_bytes, hash_prefix}, ...]}
    """
    folder = _resolve_folder(IMAGES_DIR, category)
    meta_base = {"folder": folder, "total_candidates": 0, "images_meta": []}
    if not folder or not folder.exists():
        return [], meta_base

    files = list(folder.rglob("ref_*"))
    meta_base["total_candidates"] = len(files)
    if not files:
        return [], meta_base

    selected = random.sample(files, min(MAX_IMAGES, len(files)))
    images = []
    images_meta = []
    for f in selected:
        try:
            img_bytes = f.read_bytes()
            media_type = _MEDIA_TYPE.get(f.suffix.lower(), "image/jpeg")
            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            # analyzer reject 시 mark_blacklisted 호출용 — 파일명엔 16자만 저장돼 full 다시 계산
            hash_full = hashlib.sha256(img_bytes).hexdigest()
            images.append({
                "url": f"local://{f.name}",
                "base64": b64,
                "media_type": media_type,
            })
            images_meta.append({
                "url": f"local://{f.name}",
                "local_path": str(f.relative_to(IMAGES_DIR)),
                "zone_subdir": f.parent.name if f.parent != folder else None,
                "size_bytes": len(img_bytes),
                "hash_prefix": f.stem.replace("ref_", "")[:12],
                "hash_full": hash_full,
                "source": "local_cache",
            })
        except Exception as e:
            logger.warning("[ref_image_loader] \ub85c\uceec \ub85c\ub4dc \uc2e4\ud328: %s \u2014 %s", f.name, e)
    meta_base["images_meta"] = images_meta
    return images, meta_base


# ── DuckDuckGo + Pinterest 검색 + 다운로드 + 저장 ──────────────────────
# [회귀방지] 2026-04-20 Tier 1-4: Tavily → DuckDuckGo+Pinterest 교체.
# Tavily는 유료 API 필요 + 결과 품질 낮아 기각. Large 파이프라인이 채택한 DDG+pinimg
# 우선 방식과 일원화. 이전 tavily 의존성 완전 제거.
# 참고: backend/app/nodes_large/ref_image_loader.py::_ddg_image_search

def _search_and_save_with_meta(
    category: str,
    concept_keywords: list = None,
    user_project_id: int | None = None,
    floor_size_tier: str = "medium",
    category_slug: str = "other",
) -> tuple[list, dict]:
    """DuckDuckGo 이미지 검색(Pinterest 우선) → 다운로드 → 로컬 저장 → (images, meta) 반환.

    meta 구조:
      {
        "decision": {keyword_base, keyword_final, concept_keywords_applied, pinterest_filter, query_full, rationale},
        "stats": {attempts, rate_limited, total_found, pinterest_count, other_count,
                  download_attempted, download_succeeded, duplicates_skipped, max_cap},
        "images_meta": [{url, local_path, hash_prefix, size_bytes, is_pinterest, media_type}]
      }
    """
    meta: dict = {
        "decision": {},
        "stats": {"rate_limited": False, "attempts": 0},
        "images_meta": [],
    }

    try:
        from ddgs import DDGS
        from ddgs.exceptions import RatelimitException
    except ImportError:
        logger.warning("[ref_image_loader] ddgs \ud328\ud0a4\uc9c0 \uc5c6\uc74c")
        meta["decision"] = {"rationale": "ddgs 패키지 미설치 — 검색 스킵"}
        return [], meta

    base_keyword = CATEGORY_KEYWORDS.get(category, "popup store retail")
    # concept_gen이 생성한 키워드가 있으면 검색에 추가
    keyword = base_keyword
    if concept_keywords:
        keyword = " ".join(concept_keywords[:3]) + " " + base_keyword
        logger.info(f"[ref_image_loader] \ucee8\uc149 \ud0a4\uc6cc\ub4dc \ubc18\uc601: {keyword[:80]}")
    query = f"{PINTEREST_FILTER} {keyword}{SEARCH_SUFFIX}".strip()

    meta["decision"] = {
        "keyword_base": base_keyword,
        "concept_keywords_applied": (concept_keywords or [])[:3],
        "keyword_final": keyword,
        "pinterest_filter": PINTEREST_FILTER,
        "search_suffix": SEARCH_SUFFIX.strip(),
        "query_full": query,
        "rationale": (
            f"카테고리 '{category}'의 기본 키워드 + concept_gen의 컨셉 키워드 상위 3개 + "
            f"site:pinterest.com 필터 + 탑뷰/조감도 suffix 조합. DDG가 Pinterest CDN에서 "
            f"우선 인덱싱된 이미지를 우선 정렬."
        ),
    }

    # DDG 검색 + Pinterest 우선 정렬 (Rate limit 재시도 최대 3회)
    search_results = []
    for attempt in range(3):
        meta["stats"]["attempts"] = attempt + 1
        try:
            results = list(DDGS().images(query, max_results=10))
            pinterest = [r for r in results if "pinimg.com" in r.get("image", "")]
            others = [r for r in results if "pinimg.com" not in r.get("image", "")]
            search_results = (pinterest + others)[:8]
            break
        except RatelimitException:
            meta["stats"]["rate_limited"] = True
            wait = 5 * (attempt + 1)
            if attempt < 2:
                logger.info(f"[ref_image_loader] DDG rate limit, {wait}\ucd08 \ub300\uae30 (attempt {attempt+1})")
                import time as _time
                _time.sleep(wait)
            else:
                logger.warning("[ref_image_loader] DDG rate limit 3\ud68c \u2014 \uac80\uc0c9 \ud3ec\uae30")
                return [], meta
        except Exception as e:
            logger.warning("[ref_image_loader] DDG \uac80\uc0c9 \uc2e4\ud328: %s", e)
            meta["stats"]["error"] = str(e)[:200]
            return [], meta

    if not search_results:
        logger.info("[ref_image_loader] DDG \uac80\uc0c9 \uacb0\uacfc 0\uac74")
        meta["stats"]["total_found"] = 0
        return [], meta

    image_urls = [r.get("image", "") for r in search_results if r.get("image")]
    pinterest_count = sum(1 for u in image_urls if "pinimg.com" in u)
    meta["stats"]["total_found"] = len(image_urls)
    meta["stats"]["pinterest_count"] = pinterest_count
    meta["stats"]["other_count"] = len(image_urls) - pinterest_count
    meta["stats"]["max_cap"] = MAX_IMAGES
    logger.info(
        "[ref_image_loader] DDG %d\uac74 \ubc1c\uacac (pinterest %d\uac74), \ub2e4\uc6b4\ub85c\ub4dc \uc2dc\uc791",
        len(image_urls), pinterest_count,
    )

    # 저장 폴더 확보 — for_save=True: fallback 금지. 신규 카테고리는 target 폴더 그대로 mkdir
    # (2026-04-23 bugfix: 기존엔 neighbor 폴더 `other/` 존재 시 거기로 fallback 되어
    #  신규 카테고리 이미지가 other/ 에 섞이는 영구적 오염 발생)
    folder = _resolve_folder(IMAGES_DIR, category, for_save=True)
    folder.mkdir(parents=True, exist_ok=True)

    # 기존 해시 로드
    hashes = _load_hashes(folder)
    # 1-3 (#523) — 카테고리 mismatch 로 거부된 hash list 로드. 다운로드 차단 용.
    rejected_hashes = _load_rejected_hashes(folder)

    # 병렬 다운로드
    images = []
    images_meta_list = []
    download_attempted = 0
    duplicates_skipped = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_download_image, url): url for url in image_urls[:8]}
        for future in futures:
            url = futures[future]
            download_attempted += 1
            try:
                img_bytes = future.result(timeout=10)
                if not img_bytes:
                    continue

                # 해시 계산 — 파일명 prefix (16자, 기존 컬벤션) + Java DB 전송용 full (64자)
                img_hash_full = hashlib.sha256(img_bytes).hexdigest()
                img_hash = img_hash_full[:16]

                # 로컬 캐시 중복 체크
                if img_hash in hashes:
                    duplicates_skipped += 1
                    logger.debug("[ref_image_loader] \uc911\ubcf5 \uc2a4\ud0b5: %s", img_hash)
                    continue

                # Java 블랙리스트 체크 (ref-image-python-handoff) — 관리자가
                # 차단한 이미지면 저장 skip. REF_IMAGE_HANDOFF_ENABLED=1 환경에서만 동작.
                from app.clients.ref_image_client import is_blacklisted as _is_black
                if _is_black(img_hash_full):
                    duplicates_skipped += 1
                    logger.info("[ref_image_loader] \ube14\ub799\ub9ac\uc2a4\ud2b8 \uc2a4\ud0b5: %s", img_hash)
                    continue

                                # 1-3 (#523) — local _rejected_hashes (카테고리 mismatch 거부 hash) 차단
                if img_hash_full in rejected_hashes:
                    duplicates_skipped += 1
                    logger.info("[ref_image_loader] 카테고리 mismatch 거부 hash 스킵: %s", img_hash)
                    continue

# 리사이즈 (3.5MB 초과 시)
                original_size = len(img_bytes)
                img_bytes = _maybe_resize(img_bytes)
                resized = len(img_bytes) < original_size

                # 저장
                ext = _guess_ext(img_bytes)
                filename = f"ref_{img_hash}{ext}"
                filepath = folder / filename
                filepath.write_bytes(img_bytes)
                hashes.add(img_hash)

                # base64
                media_type = _MEDIA_TYPE.get(ext, "image/jpeg")
                b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
                images.append({
                    "url": url,
                    "base64": b64,
                    "media_type": media_type,
                })
                images_meta_list.append({
                    "url": url,
                    "local_path": str(filepath.relative_to(IMAGES_DIR)),
                    "hash_prefix": img_hash[:12],
                    "hash_full": img_hash_full,  # analyzer reject 시 mark_blacklisted 호출용
                    "size_bytes": len(img_bytes),
                    "resized": resized,
                    "is_pinterest": "pinimg.com" in url,
                    "media_type": media_type,
                    "source": "ddg_pinterest",
                })
                logger.info("[ref_image_loader] \uc800\uc7a5: %s (%dKB)", filename, len(img_bytes) // 1024)

                # Java handoff \u2014 admin \ud398\uc774\uc9c0\uc5d0\uc11c \uc870\ud68c \uac00\ub2a5\ud558\ub3c4\ub85d DB \uc801\uc7ac.
                # REF_IMAGE_HANDOFF_ENABLED=0 \ub610\ub294 Java \ub2e4\uc6b4 \uc2dc None \ubc18\ud658, \ud30c\uc774\ud504\ub77c\uc778\uc740 \ubb34\uc911\ub2e8.
                from app.clients.ref_image_client import register_ref_image as _reg
                from app.services.brand_category_lookup import lookup_brand_category_id as _bid
                _bcid = _bid(category_slug)
                if _bcid is not None:
                    # 2026-04-29 S3 \ud1b5\ud569: image_bytes \uac19\uc774 \uc804\uc1a1 \u2192 Java \uac00 S3 \uc5c5\ub85c\ub4dc + s3Url \ucc44\uc6c0
                    _reg(
                        payload={
                            "userProjectId": user_project_id,
                            "brandCategoryId": _bcid,
                            "imageSha256": img_hash_full,
                            "floorSizeTier": floor_size_tier,
                            "searchKeyword": query[:255] if 'query' in locals() else None,
                            "sourceUrl": url[:500],
                            "filePath": f"references/images/{category_slug}/{filename}",
                            "fileSizeBytes": len(img_bytes),
                            "refPath": f"DDG \uac80\uc0c9 (pinimg \uc6b0\uc120)" if "pinimg.com" in url else "DDG \uac80\uc0c9",
                        },
                        image_bytes=img_bytes,
                        image_filename=filename,
                        image_content_type=media_type,
                    )

                if len(images) >= MAX_IMAGES:
                    break
            except Exception as e:
                logger.debug("[ref_image_loader] \ub2e4\uc6b4\ub85c\ub4dc \uc2e4\ud328: %s \u2014 %s", url[:60], e)

    meta["stats"]["download_attempted"] = download_attempted
    meta["stats"]["download_succeeded"] = len(images)
    meta["stats"]["duplicates_skipped"] = duplicates_skipped
    meta["images_meta"] = images_meta_list

    # 해시 저장
    _save_hashes(folder, hashes)

    return images, meta


def _download_image(url: str) -> bytes | None:
    """이미지 URL → bytes. 실패 시 None."""
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        ct = resp.headers.get("content-type", "")
        if "image" not in ct and not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return None
        return resp.content
    except Exception:
        return None


def _maybe_resize(img_bytes: bytes) -> bytes:
    """3.5MB 초과 시 PIL로 리사이즈 (Shin 원본)."""
    if len(img_bytes) <= MAX_IMAGE_BYTES:
        return img_bytes
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        # 긴 변 1500px으로
        ratio = 1500 / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        result = buf.getvalue()
        logger.info("[ref_image_loader] \ub9ac\uc0ac\uc774\uc988: %dKB \u2192 %dKB", len(img_bytes) // 1024, len(result) // 1024)
        return result
    except Exception:
        return img_bytes


def _guess_ext(img_bytes: bytes) -> str:
    """매직 바이트로 확장자 판단."""
    if img_bytes[:4] == b"\x89PNG":
        return ".png"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


# ── SHA256 해시 관리 ─────────────────────────────────────────────────────

def _load_hashes(folder: Path) -> set:
    """_hashes.json에서 기존 해시 로드."""
    hash_file = folder / "_hashes.json"
    if hash_file.exists():
        try:
            return set(json.loads(hash_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_hashes(folder: Path, hashes: set):
    """해시를 _hashes.json에 저장."""
    hash_file = folder / "_hashes.json"
    try:
        hash_file.write_text(json.dumps(sorted(hashes)), encoding="utf-8")
    except Exception as e:
        logger.warning("[ref_image_loader] \ud574\uc2dc \uc800\uc7a5 \uc2e4\ud328: %s", e)





def _load_rejected_hashes(folder: Path) -> set:
    """1-3 (#523) — _rejected_hashes.json 에서 카테고리 mismatch 로 거부된 hash 로드."""
    rejected_file = folder / "_rejected_hashes.json"
    if rejected_file.exists():
        try:
            return set(json.loads(rejected_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


# ── 배치 예시 로드 ───────────────────────────────────────────────────────

def _load_layout_examples(category: str) -> list:
    """references/layouts/{폴더}/layout_*.json 로드."""
    folder = _resolve_folder(LAYOUTS_DIR, category)
    if not folder or not folder.exists():
        return []
    files = list(folder.glob("layout_*.json"))
    if not files:
        return []
    selected = random.sample(files, min(MAX_LAYOUTS, len(files)))
    examples = []
    for f in selected:
        try:
            examples.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("[ref_image_loader] \ub808\uc774\uc544\uc6c3 \ub85c\ub4dc \uc2e4\ud328: %s \u2014 %s", f.name, e)
    return examples


def _resolve_folder(base_dir: Path, category: str, for_save: bool = False) -> Path:
    """카테고리 → 폴더 경로.

    2026-04-20 영문 slug 전환 이후 기본 fallback은 "other" (영문).
    과거 한글 "기타" 폴더는 Shin 영역(Large 파이프라인)이 계속 쓰므로 보존되나,
    Small은 이 함수를 거쳐 영문 경로만 참조한다.

    for_save=False (LOAD 용, 기본):
      - 목표 폴더 존재하면 그대로 반환
      - 없으면 폴더 path 그대로 반환 (호출자가 not exists 체크 → 빈 list → DDG 검색 trigger)
    for_save=True (SAVE 용):
      - 항상 목표 폴더 그대로 반환
      - caller 가 `folder.mkdir(parents=True, exist_ok=True)` 로 실제 폴더 생성 책임

    [#489 — 2026-05-05] other fallback 폐기.
      이전 동작: 카테고리 폴더 (예: beauty) 없으면 other/ fallback → other 캐시 사용
      문제: 신규 카테고리 첫 호출 시 카테고리별 DDG 검색이 영구히 trigger 안 됨
            → 카테고리별 특화 (뷰티 화장대 / F&B 카페) 패턴 추출 X
      현재: 폴더 없으면 그대로 반환 → 호출자가 빈 list → DDG 검색 trigger
      [회귀방지] 2026-04-23 SAVE 분리 (for_save=True) 와는 별개. SAVE 는 신규 카테고리
            target 폴더 그대로 mkdir (other/ 혼입 방지). LOAD 도 동일하게 other/ 미혼입.
    """
    folder_name = CATEGORY_FOLDER.get(category, "other")
    folder = base_dir / folder_name
    if for_save:
        return folder
    if folder.exists():
        return folder
    logger.warning(
        "[ref_image_loader] '%s' 폴더 없음 (%s) — other fallback 폐기 (#489), DDG 검색 trigger 예정",
        category, folder
    )
    return folder
