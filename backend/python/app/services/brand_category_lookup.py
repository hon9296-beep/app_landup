"""
brand_categories code(slug) → id 변환 lookup (process-local cache).

용도:
  - ref_image_loader 가 register_ref_image 호출 시 brandCategoryId(Long) 필요
  - DB 직접 조회 (Java 인증 우회 + HTTP 라운드트립 제거). 정적 reference 데이터.

실패 정책:
  - DB 미가동 / 매핑 없음 → None 반환
  - caller 가 None 이면 register 호출 skip → 파이프라인 무중단
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_cache: dict[str, int] = {}


def _connect():
    """pymysql 연결. .env 의 DB_* 환경변수 사용."""
    import pymysql
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "landup_v2"),
        charset="utf8mb4",
        connect_timeout=3,
    )


def lookup_brand_category_id(code: str) -> Optional[int]:
    """slug(code) → brand_categories.id 변환. 실패 시 None.

    process-local 캐시. 동일 code 재요청은 즉시 반환.
    DB 미가동 / 매핑 없음 등 모두 graceful — caller 가 register 호출 skip 하면 됨.
    """
    if not code:
        return None
    if code in _cache:
        return _cache[code]

    try:
        con = _connect()
        try:
            with con.cursor() as cur:
                cur.execute("SELECT id FROM brand_categories WHERE code=%s", (code,))
                row = cur.fetchone()
                if row is None:
                    logger.warning("[brand_category_lookup] code=%s 매핑 없음", code)
                    return None
                _cache[code] = int(row[0])
                return _cache[code]
        finally:
            con.close()
    except Exception as e:
        logger.warning("[brand_category_lookup] DB lookup 실패 code=%s: %s", code, e)
        return None
