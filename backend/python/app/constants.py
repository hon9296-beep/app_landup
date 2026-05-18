"""
공용 알고리즘 상수 — 엔진 tier 분기 + 파이프라인 공용값.

Single Source of Truth. 여러 노드/모듈에서 공유되는 경계값/임계값은 여기서만 정의.
도메인별 상수 (VMD 실무 수치 등) 는 vmd_constants.py / venue_rules.py 참조.

상세 원칙: CLAUDE.md "공용 상수 중앙화"
"""

# ─────────────────────────────────────────────────────────────────────
# 엔진 tier 경계 (mm²)
# ─────────────────────────────────────────────────────────────────────
# Landup 엔진은 면적 기반 3단 tier 로 파라미터 분기.
#   small  : < 66M mm² (20평 미만) — 벽면형 / kiosk 급
#   medium : 66M ~ 165M mm² (20~50평) — 부스형 / 가벽 분할
#   large  : ≥ 165M mm² (50평 이상) — Shin 담당 (nodes_large/)
# Rendy 담당 (nodes_small/) 은 small + medium 커버. large 는 api.py 에서 분기.

SMALL_AREA_THRESHOLD_MM2 = 66_000_000    # 20평 = 66㎡. 소/중 분기
MEDIUM_AREA_THRESHOLD_MM2 = 165_000_000  # 50평 = 165㎡. 중/대 (Rendy/Shin) 분기
