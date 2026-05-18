"""
레퍼런스 이미지 로더 노드 — area별 DuckDuckGo + Pinterest 검색.

Phase 2.5 개편:
  - concept_areas 우선 (keywords_gen이 만든 area별 영문 키워드 사용)
  - 없으면 DEFAULT_ZONES_CHARACTER_IP fallback

검색 전략:
  1. 영역별 한글 키워드(concept_area.AREA_TYPES.search_keyword) + 영문 키워드(area.search_keywords) 결합
  2. 로컬 캐시 + 신규 검색 결과 합쳐서 반환
  3. 항상 검색 — 로컬에 있어도 새로운 이미지 찾으면 저장

폴더 구조:
  references/images/{카테고리}/{영역이름}/ref_*.jpg

향후 S3 + DB 이관 예정.
"""
import base64
import hashlib
import json
import logging
import os
import random
import time
from pathlib import Path

import httpx

from app.state import LargeState

logger = logging.getLogger(__name__)

# 도커·로컬 경로 자동 선택 (project_root/references/ 로 수렴).
# - 도커: docker-compose 가 ./references 를 /references 로 마운트 → 즉시 선택
# - 로컬: __file__ = backend/python/app/nodes_large/ref_image_loader.py → parents[4] = project_root
# 도커 경로 체크를 먼저 해서 parents[4] IndexError (컨테이너 내부 /app/... 깊이 부족) 회피.
_DOCKER_PATH = Path("/references")
if _DOCKER_PATH.exists():
    REFERENCES_DIR = _DOCKER_PATH
else:
    REFERENCES_DIR = Path(__file__).resolve().parents[4] / "references"
IMAGES_DIR = REFERENCES_DIR / "images"
LAYOUTS_DIR = REFERENCES_DIR / "layouts"

# 카테고리 → 영문 slug 폴더명 (small 정합, 2026-04-30)
# 이전엔 한국어 폴더명 + 별도 CATEGORY_SLUG 이중 dict 였으나 영문 slug 단일화.
# Windows cp949 / S3 key / 컨테이너 볼륨 마운트 호환을 위한 영문화.
# area sub-folder ("맞이"/"포토" 등) 는 LLM 출력 한국어 그대로 유지 (4-29 결정: LLM 입출력 = 한국어).
CATEGORY_FOLDER = {
    "캐릭터 IP": "character_ip",
    "패션 브랜드": "fashion",
    "F&B": "fnb",
    "뷰티·코스메틱": "beauty",
    "테크·전자제품": "tech",
    "아트·전시": "art",
    "엔터·팬미팅": "entertainment",
    "기타": "other",
}

# 카테고리별 디자인 톤 검색 가이드 (2026-05-03 신설)
# Pinterest 검색 query 에 카테고리별 차별화된 톤 키워드 추가 → 검색 결과 다양성 확보
# 디자인 도메인 협의 (TR_M) 후 키워드 튜닝 예정 — 현재는 보수적 default
# 출처: docs/docs-shin/main_tasks/TR_S_고도화/2026-05-01_[디자인_참조_로직]_카테고리별_검색_가이드.md
CATEGORY_SEARCH_GUIDE = {
    "캐릭터 IP": "character popup interactive playful",
    "패션 브랜드": "fashion popup minimalist showcase",
    "F&B": "cafe popup cozy lounge",
    "뷰티·코스메틱": "beauty popup elegant display",
    "테크·전자제품": "tech popup modern minimal",
    "아트·전시": "exhibition popup gallery contemporary",
    "엔터·팬미팅": "fanmeeting popup event stage",
    "기타": "popup store interior",
}

# 면적 → ref_image FloorSizeTier 매핑 (small 정합)
_TIER_SMALL_MAX_M2 = 50
_TIER_MEDIUM_MAX_M2 = 165


def _compute_floor_size_tier(state) -> str:
    """state.usable_poly 면적 → ref_image FloorSizeTier ('small'|'medium'|'large').
    면적 미상이면 'large' default (large 노드 호출 컨텍스트라 large 추정).
    """
    usable_poly = state.get("usable_poly") if hasattr(state, "get") else None
    if not usable_poly:
        return "large"
    area_m2 = usable_poly.area / 1_000_000
    if area_m2 < _TIER_SMALL_MAX_M2:
        return "small"
    if area_m2 < _TIER_MEDIUM_MAX_M2:
        return "medium"
    return "large"

# 캐릭터IP 기본 영역 목록 (concept_areas 없을 때 fallback) — concept_area name 그대로 사용 (2026-04-30 정합)
DEFAULT_ZONES_CHARACTER_IP = [
    "맞이", "체험", "상영", "포토", "굿즈판매", "결제",
]

# ZONE_KEYWORDS / AREA_TO_ZONE 제거 (2026-04-30):
#   - 옛 zone_planner (archive) 시절 분류 잔재 + concept_area 도입 후 임시 어댑터 layer
#   - 이제 concept_area.AREA_TYPES 의 search_keyword 필드를 단일 진실의 소스로 사용
#   - 호출처는 _get_search_keyword(area_name) 헬퍼로 일원화

PINTEREST_FILTER = "site:pinterest.com"
# REF_IMAGES_PER_ZONE: .env에서 영역당 검색/사용 이미지 수 설정. 테스트: 1, 운영: 3 권장.
MAX_IMAGES_PER_ZONE = int(os.environ.get("REF_IMAGES_PER_ZONE", "3"))

# 2026-04-29 신설 (S3 인프라 N+1 흐름):
#   REF_NEW_SEARCH_LIMIT — DDG 신규 검색 이미지 수 (개발 1, 운영 3 권장). 1건도 DB JSON 영속 됨.
#   REF_POOL_FETCH_LIMIT — concept_area 별 DB 풀 fetch 최대 (LLM 컨텍스트 토큰 고려, 기본 10)
NEW_SEARCH_LIMIT = int(os.environ.get("REF_NEW_SEARCH_LIMIT", "1"))
POOL_FETCH_LIMIT = int(os.environ.get("REF_POOL_FETCH_LIMIT", "10"))
MAX_IMAGE_BYTES = 3_500_000

# 2026-05-08 신설 — 검색 결과가 GIF / 품질 reject 등으로 빈 list 가까울 때 query 변형 후 재검색.
# 1차 검색 + 재검색 max 2회 = 총 3회 시도. 그래도 빈이면 local_imgs (run() 안 _load_local_images) 가 fallback.
# local 도 빈이면 그 영역 ref pool 0 으로 진행 (사용자 결정).
SEARCH_RETRY_MAX = 2
SEARCH_RETRY_THRESHOLD = 2  # new_images 가 이 미만이면 재검색 트리거

_DDG_BACKOFFS = [10, 30, 60]  # exponential backoff 확대 (기존 5/10/15)


def run(state: LargeState) -> LargeState:
    """영역별 레퍼런스 이미지 검색 + 로컬 캐시 합산 반환."""
    brand_data = state.get("brand_data") or {}
    concept_areas = state.get("concept_areas") or []

    category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(category, dict):
        category = category.get("value", "기타") or "기타"

    cat_folder = CATEGORY_FOLDER.get(category, "other")

    # Java handoff 용 메타 (small 정합) — register_ref_image 호출 시 필요
    user_project_id = state.get("user_project_id")
    floor_size_tier = _compute_floor_size_tier(state)
    category_slug = cat_folder  # CATEGORY_FOLDER 영문 slug 단일화 후 cat_folder 와 동일 값 (2026-04-30)

    # 검색 항목 구성 (Phase 2.5: concept_areas 우선)
    # zone_alias 제거 (2026-04-30) — concept_area.AREA_TYPES 의 search_keyword 직접 사용
    if concept_areas:
        items = [
            {
                "name": a.get("name", ""),
                "keywords": a.get("search_keywords") or [],
            }
            for a in concept_areas
            if a.get("name")
        ]
        source = "concept_areas"
    else:
        items = [
            {"name": z, "keywords": []}
            for z in DEFAULT_ZONES_CHARACTER_IP
        ]
        source = "default"

    # 영역별 풀 fetch (DB) + 신규 검색 결합 — 2026-04-29 N+1 흐름 도입
    # 풀 = ref_image_analyses 누적 (분석 결과 JSON 만, base64 X) → LLM 컨텍스트 토큰 ↓
    # 신규 = DDG 검색 이미지 (base64) → Vision 호출 대상 (분석 후 영속화)
    from app.clients.ref_image_client import fetch_analysis_pool
    from app.nodes_large.c_brand_area.concept_area import CONCEPT_AREA_LABEL_EN

    all_images = {}
    area_meta = []  # reference_meta.areas
    for item in items:
        # 2026-05-07 fix: area_name 의 trailing/leading 공백 제거.
        # 한국어 + 공백 폴더명은 Windows / git 가 access 못 하는 경우 발생 (예: "맞이 "/_hashes.json fail).
        name = (item.get("name") or "").strip()
        if not name:
            continue  # 빈 이름 영역 skip
        folder = IMAGES_DIR / cat_folder / name
        folder.mkdir(parents=True, exist_ok=True)

        # ── 1. DB 풀 fetch — concept_area (영문) 매칭. 분석 결과 JSON 만 (no base64) ─────
        concept_area_en = CONCEPT_AREA_LABEL_EN.get(name)  # 한국어 area name → 영문 키
        pool_analyses: list[dict] = []
        if concept_area_en:
            pool_analyses = fetch_analysis_pool(
                concept_area=concept_area_en,
                brand_category=category if category and category != "기타" else None,
                limit=POOL_FETCH_LIMIT,
            )

        # ── 2. 로컬 캐시 + DDG 신규 검색 (base64) ────────────────────────────────
        local_imgs = _load_local_images(folder)
        new_imgs = _search_area(
            category=category,
            area_name=name,
            area_keywords=item["keywords"],
            target_folder=folder,
            user_project_id=user_project_id,
            floor_size_tier=floor_size_tier,
            category_slug=category_slug,
        )

        # 신규 + 로컬 합산. 신규 검색 quota 별도 (N+1 흐름 — REF_NEW_SEARCH_LIMIT)
        combined = local_imgs + new_imgs
        if len(combined) > NEW_SEARCH_LIMIT:
            combined = random.sample(combined, NEW_SEARCH_LIMIT)

        # 풀 분석 결과를 image dict 형식으로 변환 (Vision 호출 skip 표지 — has_cached_analysis=True)
        pool_imgs = [{
            "ref_image_id": pa.get("refImageId"),
            "zone": name,
            "concept_area_en": concept_area_en,
            "cached_analysis_json": pa.get("visionAnalysisJson"),
            "has_cached_analysis": True,
        } for pa in pool_analyses]

        all_images[name] = pool_imgs + combined  # 풀 + 신규
        logger.info(
            "[ref_image_loader] area=%s, pool=%d, local=%d, new=%d, total=%d (zone_en=%s)",
            name, len(pool_imgs), len(local_imgs), len(new_imgs), len(all_images[name]), concept_area_en,
        )

        # LangSmith 가시화용 — 영역별 수집 메타
        area_meta.append({
            "name": name,
            "concept_area_en": concept_area_en,
            "keywords": item["keywords"],
            "pool_count": len(pool_imgs),
            "local_count": len(local_imgs),
            "new_count": len(new_imgs),
            "total_count": len(all_images[name]),
        })

    # 배치 예시
    examples = _load_layout_examples(category)

    # 전체 이미지 리스트 (기존 호환)
    flat_images = []
    for imgs in all_images.values():
        flat_images.extend(imgs)

    logger.info(
        "[ref_image_loader] source=%s, category=%s, areas=%d, total_images=%d",
        source, category, len(items), len(flat_images),
    )

    # reference_meta — LangSmith state snapshot 으로 자동 가시화
    reference_meta = {
        "category": category,
        "engine": "ddg+pinterest",
        "source": source,
        "max_per_zone": MAX_IMAGES_PER_ZONE,
        "total_collected": len(flat_images),
        "areas": area_meta,
    }

    return {
        "reference_images": flat_images,
        "reference_images_by_zone": all_images,  # key=area_name (concept_areas 사용 시)
        "layout_examples": examples,
        "reference_meta": reference_meta,
    }


# ── 영역별 검색 ────────────────────────────────────────────────────────────

def _search_area(
    category: str,
    area_name: str,
    area_keywords: list,
    target_folder: Path,
    user_project_id: int | None = None,
    floor_size_tier: str = "large",
    category_slug: str = "other",
) -> list:
    """영역 단위 Pinterest 검색 → 새 이미지만 저장 + 반환.

    한글 키워드: concept_area.AREA_TYPES[area_name].search_keyword (단일 진실의 소스, 2026-04-30)
                  매핑 없는 커스텀 area 는 fallback ("팝업스토어 {area_name} 인테리어")
    영문 키워드: keywords_gen 산출물 (area_keywords) 최대 2개

    Java handoff (small 정합):
      - register_ref_image 호출 → ref_image 테이블 INSERT → 응답의 id 를 ref_image_id 메타로 image dict 에 포함
      - REF_IMAGE_HANDOFF_ENABLED=0 / Java 다운 / user_project_id None 시 등록 skip (graceful)
    """
    cat_keyword = CATEGORY_FOLDER.get(category, "팝업스토어")
    # 카테고리별 디자인 톤 키워드 (2026-05-03 신설) — 검색 결과 다양성 확보
    cat_tone = CATEGORY_SEARCH_GUIDE.get(category, "")

    # 한글 키워드 — concept_area.AREA_TYPES 의 search_keyword 직접 lookup (단일 진실의 소스)
    from app.nodes_large.c_brand_area.concept_area import AREA_TYPES
    area_def = AREA_TYPES.get(area_name, {})
    kor_keyword = area_def.get("search_keyword") or f"팝업스토어 {area_name} 인테리어"

    # 영문 키워드 (keywords_gen 산출물, 최대 2개로 쿼리 길이 제한)
    eng_str = " ".join(area_keywords[:2]) if area_keywords else ""

    base_query = f"{PINTEREST_FILTER} {cat_keyword} {cat_tone} {kor_keyword} {eng_str}".strip()

    # 기존 해시 로드
    hashes = _load_hashes(target_folder)
    new_images = []

    # 2026-05-08: 검색 결과가 GIF/품질 reject 로 빈 list 에 가까우면 query 변형 후 재검색.
    # 1차 + 재검색 max SEARCH_RETRY_MAX 회 = 총 SEARCH_RETRY_MAX+1 회 시도.
    # new_images 가 SEARCH_RETRY_THRESHOLD 이상 모이면 즉시 break.
    for retry in range(SEARCH_RETRY_MAX + 1):  # 0 (1차) ~ SEARCH_RETRY_MAX (마지막 재검색)
        try_query = _vary_search_query(base_query, retry) if retry > 0 else base_query

        if retry > 0:
            logger.info(
                f"[ref_image_loader] 재검색 {retry}/{SEARCH_RETRY_MAX} — "
                f"new_images={len(new_images)} (area={area_name}, query={try_query[:80]!r})"
            )

        results = _ddg_image_search(try_query, max_results=MAX_IMAGES_PER_ZONE)
        if not results:
            continue

        for r in results:
            url = r.get("image", "")
            if not url:
                continue

            img_bytes = _download_image(url)
            if not img_bytes:
                continue

            img_hash_full = hashlib.sha256(img_bytes).hexdigest()
            img_hash = img_hash_full[:16]
            if img_hash in hashes:
                continue

            # 품질 필터 (2026-05-03 신설, 약 강도) — 사이즈/종횡비 reject
            if not _passes_quality_filter(img_bytes):
                logger.info(f"[ref_image_loader] 품질 필터 reject: {url[:80]}")
                continue

            img_bytes = _maybe_resize(img_bytes)
            ext = _guess_ext(img_bytes)
            media_type = _MEDIA_TYPE.get(ext, "image/jpeg")

            # 저장
            filename = f"ref_{img_hash}{ext}"
            (target_folder / filename).write_bytes(img_bytes)
            hashes.add(img_hash)

            # ── Java handoff (small 정합) ─────────────────────────────────
            # ref_image 테이블 INSERT → 응답의 id 를 image dict 메타로 포함.
            # ref_image_analyzer 가 이 id 활용해서 캐시 hit 조회 + ref_image_analyses 영속.
            # REF_IMAGE_HANDOFF_ENABLED=0 / Java 다운 / user_project_id None / lookup 실패 시 None.
            ref_image_id: int | None = None
            if user_project_id is not None:
                from app.clients.ref_image_client import register_ref_image as _reg
                from app.services.brand_category_lookup import lookup_brand_category_id as _bid
                _bcid = _bid(category_slug)
                if _bcid is not None:
                    # 2026-04-29: multipart 전송 — image_bytes 같이 전달 → Java 가 S3 업로드 + s3Url 채움.
                    resp = _reg(
                        payload={
                            "userProjectId": user_project_id,
                            "brandCategoryId": _bcid,
                            "imageSha256": img_hash_full,
                            "floorSizeTier": floor_size_tier,
                            "searchKeyword": try_query[:255],
                            "sourceUrl": url[:500],
                            "filePath": f"references/images/{category_slug}/{filename}",
                            "fileSizeBytes": len(img_bytes),
                            "refPath": "DDG 검색 (pinimg 우선)" if "pinimg.com" in url else "DDG 검색",
                        },
                        image_bytes=img_bytes,
                        image_filename=filename,
                        image_content_type=media_type,
                    )
                    if resp and isinstance(resp, dict):
                        ref_image_id = resp.get("id")

            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            new_images.append({
                "url": url,
                "base64": b64,
                "media_type": media_type,
                "zone": area_name,  # 호환: 키 이름은 zone 유지, 값은 area_name
                "ref_image_id": ref_image_id,  # Java ref_image 테이블 row id (handoff 비활성/실패 시 None)
            })
            logger.info("[ref_image_loader] 저장: %s/%s (%dKB) ref_image_id=%s", area_name, filename, len(img_bytes) // 1024, ref_image_id)

        # 2026-05-08: 충분히 모이면 재검색 skip
        if len(new_images) >= SEARCH_RETRY_THRESHOLD:
            break

    if new_images:
        _save_hashes(target_folder, hashes)

    return new_images


def _vary_search_query(base_query: str, retry: int) -> str:
    """재검색 시 query 변형 — GIF / 비-정적 이미지 제외 키워드 추가.

    2026-05-08 신설. SEARCH_RETRY_MAX (2) 까지 호출됨.
    - retry 1: '-gif' 추가 (Google/DDG 의 키워드 제외 옵션)
    - retry 2: 'photography' 추가 (정적 실사 위주)
    """
    if retry == 1:
        return f"{base_query} -gif"
    if retry == 2:
        return f"{base_query} photography"
    return base_query


def _ddg_image_search(query: str, max_results: int = 3) -> list:
    """DuckDuckGo 이미지 검색. Pinterest 우선. exponential backoff (10/30/60)."""
    try:
        from ddgs import DDGS
        from ddgs.exceptions import RatelimitException
    except ImportError:
        logger.warning("[ref_image_loader] ddgs 패키지 없음 (구 duckduckgo-search 후속)")
        return []

    for attempt in range(3):
        try:
            results = DDGS().images(query, max_results=max_results + 2)
            # Pinterest 우선 정렬
            pinterest = [r for r in results if "pinimg.com" in r.get("image", "")]
            others = [r for r in results if "pinimg.com" not in r.get("image", "")]
            return (pinterest + others)[:max_results]
        except RatelimitException:
            wait = _DDG_BACKOFFS[attempt]
            if attempt < 2:
                logger.info(f"[ref_image_loader] Rate limit, {wait}초 대기 (attempt {attempt+1})")
                time.sleep(wait)
            else:
                logger.warning("[ref_image_loader] Rate limit 3회 — 스킵")
                return []
        except Exception as e:
            logger.warning("[ref_image_loader] 검색 실패: %s", e)
            return []

    return []


# ── 로컬 이미지 로드 ────────────────────────────────────────────────────

_MEDIA_TYPE = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _load_local_images(folder: Path) -> list:
    """폴더에서 ref_* 이미지 로드."""
    if not folder.exists():
        return []

    files = list(folder.glob("ref_*"))
    if not files:
        return []

    selected = random.sample(files, min(MAX_IMAGES_PER_ZONE, len(files)))
    images = []
    for f in selected:
        try:
            img_bytes = f.read_bytes()
            media_type = _MEDIA_TYPE.get(f.suffix.lower(), "image/jpeg")
            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            zone_name = f.parent.name
            images.append({
                "url": f"local://{zone_name}/{f.name}",
                "base64": b64,
                "media_type": media_type,
                "zone": zone_name,
            })
        except Exception as e:
            logger.warning("[ref_image_loader] 로컬 로드 실패: %s — %s", f.name, e)
    return images


def _download_image(url: str) -> bytes | None:
    """이미지 다운로드."""
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


def _passes_quality_filter(img_bytes: bytes) -> bool:
    """이미지 품질 필터 — 사이즈 + 종횡비 + blur + 포맷.

    2026-05-03 신설 (사이즈 + 종횡비). 2026-05-04 blur 추가. 2026-05-06 GIF reject 추가.
    Shin 결정: OpenCV 박음 (이미 requirements.txt 에 opencv-python-headless 있음). blur 임계값 = 중 (50 미만 reject).

    검사 항목:
    - 포맷: GIF reject (애니메이션 / 저화질 → 디자인 레퍼런스로 부적합. Anthropic Vision 도 jpeg 박힌 채 보내면 400 거부.)
    - 사이즈: 200x200 미만 reject (저해상도)
    - 종횡비: 0.3 미만 또는 3.5 초과 reject (세로 모바일 캡처 / 길쭉한 가로 배너 등)
    - blur: Laplacian 분산값 50 미만 reject (흐릿함). cv2.Laplacian 으로 이미지 미분 = 윤곽선 강도의 분산 측정

    실패 시 True (통과) — 필터 자체 실패가 이미지 reject 보다 안전.
    출처: docs/docs-shin/main_tasks/TR_S_고도화/2026-04-24_[디자인_참조_로직]_이미지_품질_필터.md
    """
    # GIF magic byte 체크 — GIF87a / GIF89a 둘 다 시작이 b"GIF8"
    if img_bytes[:4] == b"GIF8":
        return False

    try:
        from PIL import Image
        import io
        import numpy as np
        import cv2

        img = Image.open(io.BytesIO(img_bytes))
        # 2026-05-08 GIF 우회 fix — magic byte 변형 / 다른 wrapper 케이스도 PIL 이 잡음.
        # Anthropic Vision 이 "image/jpeg 박힌 채 GIF 데이터" 받으면 400 거부.
        if img.format == "GIF":
            return False
        w, h = img.size
        if w < 200 or h < 200:
            return False
        ratio = w / h if h > 0 else 1.0
        if ratio < 0.3 or ratio > 3.5:
            return False

        # blur 검사 — Laplacian 분산값 (윤곽선 강도). 낮음 = 흐릿함.
        gray = np.array(img.convert("L"))  # PIL → numpy grayscale
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if laplacian_var < 50:
            return False

        return True
    except Exception:
        return True


def _maybe_resize(img_bytes: bytes) -> bytes:
    """3.5MB 초과 시 리사이즈."""
    if len(img_bytes) <= MAX_IMAGE_BYTES:
        return img_bytes
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        ratio = 1500 / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return img_bytes


def _guess_ext(img_bytes: bytes) -> str:
    if img_bytes[:4] == b"\x89PNG":
        return ".png"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


# ── 해시 관리 ────────────────────────────────────────────────────────────

def _load_hashes(folder: Path) -> set:
    hash_file = folder / "_hashes.json"
    if hash_file.exists():
        try:
            return set(json.loads(hash_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_hashes(folder: Path, hashes: set):
    hash_file = folder / "_hashes.json"
    try:
        hash_file.write_text(json.dumps(sorted(hashes)), encoding="utf-8")
    except Exception as e:
        logger.warning("[ref_image_loader] 해시 저장 실패: %s", e)


# ── 배치 예시 ────────────────────────────────────────────────────────────

def _load_layout_examples(category: str) -> list:
    folder_name = CATEGORY_FOLDER.get(category, "기타")
    folder = LAYOUTS_DIR / folder_name
    if not folder.exists():
        return []
    files = list(folder.glob("layout_*.json"))
    if not files:
        return []
    selected = random.sample(files, min(2, len(files)))
    examples = []
    for f in selected:
        try:
            examples.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("[ref_image_loader] 레이아웃 로드 실패: %s — %s", f.name, e)
    return examples
