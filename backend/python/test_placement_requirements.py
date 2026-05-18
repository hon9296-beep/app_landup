"""
배치 요구사항 3가지 케이스 자동화 테스트.
1. 계산대 입구 오른편으로 갖다놔주세요
2. 진열대 전부 제거해주세요
3. 3단선반 2개 추가해주세요

실행: python test_placement_requirements.py
"""
import io
import json
import sys
import time
import requests

# Windows cp949 인코딩 문제 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
BRAND_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\01_ryancorp_spec.pdf"
FLOOR_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\18pyeong.dxf"

TESTS = [
    "계산대 입구 오른편으로 갖다놔주세요",
    "진열대 전부 제거해주세요",
    "3단선반 2개 추가해주세요",
]


def log(msg):
    print(f"  {msg}", flush=True)


def step(title):
    print(f"\n{'='*60}\n[STEP] {title}\n{'='*60}", flush=True)


# ── Step 1: detect ─────────────────────────────────────────────
step("1. /api/detect — 도면 파싱")
with open(FLOOR_FILE, "rb") as f:
    r = requests.post(
        f"{BASE}/api/detect",
        files={"floor_plan": ("18pyeong.dxf", f, "application/octet-stream")},
        data={"file_type": "dxf"},
        timeout=60,
    )
if r.status_code != 200:
    print(f"FAIL: {r.status_code} — {r.text[:300]}")
    sys.exit(1)

detect_result = r.json()
log(f"polygon points: {len(detect_result.get('floor_polygon_px', []))}")
log(f"scale: {detect_result.get('scale_mm_per_px')} mm/px")
log(f"entrance: {detect_result.get('entrance')}")

# ── Step 2: brand ──────────────────────────────────────────────
step("2. /api/brand — 브랜드 매뉴얼 추출")
with open(BRAND_FILE, "rb") as f:
    r = requests.post(
        f"{BASE}/api/brand",
        files={"brand_manual": ("01_ryancorp_spec.pdf", f, "application/pdf")},
        data={"file_type": "pdf"},
        timeout=120,
    )
if r.status_code != 200:
    print(f"FAIL: {r.status_code} — {r.text[:300]}")
    sys.exit(1)

brand_data = r.json()
brand_info = brand_data.get("brand", {})
log(f"brand_name: {brand_info.get('brand_name', {}).get('value', '?')}")
log(f"brand_category: {brand_info.get('brand_category', '?')}")
log(f"placement_rules: {len(brand_data.get('placement_rules', []))} 개")

# ── Step 3: space-data ─────────────────────────────────────────
step("3. /api/space-data — 공간 계산")
space_body = {
    "auto_detected": detect_result,
    "brand_dict": brand_data,
    "brand_category": brand_info.get("brand_category", "기타") if isinstance(brand_info.get("brand_category"), str) else brand_info.get("brand_category", {}).get("value", "기타"),
}
r = requests.post(f"{BASE}/api/space-data", json=space_body, timeout=60)
if r.status_code != 200:
    print(f"FAIL: {r.status_code} — {r.text[:300]}")
    sys.exit(1)

space_resp = r.json()
space_data = space_resp.get("space_data", space_resp)
log(f"floor polygon_mm points: {len(space_data.get('floor', {}).get('polygon_mm', []))}")
log(f"usable_area_sqm: {space_data.get('usable_area_sqm', '?')}")
log(f"scale_type: {space_data.get('scale_type', '?')}")

# ── Step 4: 기본 배치 (user_requirements 없음) ─────────────────
step("4. /api/place — 기본 배치 (요구사항 없음)")

def build_place_body(space_data, brand_data, user_req="", locked=[]):
    body = {
        "floor": space_data.get("floor", {}),
        "entrance": space_data.get("entrance", {}),
        "dead_zones": space_data.get("dead_zones", []),
        "sprinklers_mm": space_data.get("sprinklers_mm", []),
        "hydrants_mm": space_data.get("hydrants_mm", []),
        "electric_panels_mm": space_data.get("electric_panels_mm", []),
        "brand_dict": brand_data,
        "brand_category": space_data.get("brand_category", "기타"),
        "venue_type": space_data.get("venue_type"),
        "facade_type": space_data.get("facade_type"),
        "density_ratio": 0.25,
        "user_requirements": user_req,
        "locked_objects": locked,
    }
    return body

t0 = time.time()
r = requests.post(
    f"{BASE}/api/place",
    json=build_place_body(space_data, brand_data),
    timeout=300,
)
elapsed = time.time() - t0
if r.status_code != 200:
    print(f"FAIL ({elapsed:.0f}s): {r.status_code} — {r.text[:500]}")
    sys.exit(1)

base_result = r.json()
placed = base_result.get("objects", [])
log(f"배치 완료: {len(placed)}개 ({elapsed:.0f}s)")
for obj in placed:
    log(f"  · {obj.get('object_type','?')} @ {obj.get('anchor_key','?')} ({obj.get('zone_label','?')})")

# locked_objects = 기본 배치 결과 (추가 모드 테스트용)
locked_objects = placed

# ── Step 5: 3가지 요구사항 테스트 ──────────────────────────────
results = {}

for req in TESTS:
    step(f"5. 요구사항 테스트: \"{req}\"")
    t0 = time.time()
    r = requests.post(
        f"{BASE}/api/place",
        json=build_place_body(space_data, brand_data, user_req=req, locked=locked_objects),
        timeout=300,
    )
    elapsed = time.time() - t0

    if r.status_code != 200:
        log(f"FAIL ({elapsed:.0f}s): {r.status_code}")
        log(f"ERROR: {r.text[:500]}")
        results[req] = {"status": "ERROR", "detail": r.text[:500]}
        continue

    result = r.json()
    new_placed = result.get("objects", [])
    failed = result.get("failed_objects", [])
    resolved = result.get("resolved_intents", [])

    log(f"응답 ({elapsed:.0f}s): 배치 {len(new_placed)}개, 실패 {len(failed)}개")

    # intent 파싱 결과 확인
    if resolved:
        log(f"resolved_intents: {len(resolved)}개")
        for ri in resolved:
            log(f"  · action={ri.get('action')} type={ri.get('object_type')} qty={ri.get('quantity')} zone={ri.get('zone_hint')} dir={ri.get('direction_hint')}")
    else:
        log("resolved_intents: 없음 (파싱 실패 or 전략 적용 전 제거)")

    # 배치 결과 출력
    log("배치 결과:")
    type_counts = {}
    for obj in new_placed:
        ot = obj.get("object_type", "?")
        type_counts[ot] = type_counts.get(ot, 0) + 1
    for ot, cnt in sorted(type_counts.items()):
        log(f"  · {ot}: {cnt}개")

    # 케이스별 검증
    if "계산대" in req and "오른편" in req:
        counters = [o for o in new_placed if o.get("object_type") == "counter"]
        log(f"[검증] counter {len(counters)}개 배치됨")
        for c in counters:
            log(f"  zone={c.get('zone_label')} dir={c.get('direction')} anchor={c.get('anchor_key')}")
        verdict = "PASS" if counters else "FAIL — counter 없음"

    elif "진열대" in req and "제거" in req:
        display_tables = [o for o in new_placed if o.get("object_type") in ("display_table", "display_table_standard")]
        log(f"[검증] display_table {len(display_tables)}개 남아있음 (0이어야 PASS)")
        verdict = "PASS" if not display_tables else f"FAIL — display_table {len(display_tables)}개 남음"

    elif "3단선반" in req and "추가" in req:
        shelf3 = [o for o in new_placed if o.get("object_type") == "shelf_3tier"]
        base_shelf3 = [o for o in locked_objects if o.get("object_type") == "shelf_3tier"]
        log(f"[검증] 기존 shelf_3tier={len(base_shelf3)}개 → 결과 shelf_3tier={len(shelf3)}개 (추가 {len(shelf3)-len(base_shelf3)}개)")
        added = len(shelf3) - len(base_shelf3)
        verdict = "PASS" if added >= 2 else f"FAIL — shelf_3tier {added}개 추가됨 (2개 필요)"
    else:
        verdict = "CHECK"

    log(f"\n{'✓' if 'PASS' in verdict else '✗'} 결과: {verdict}")
    results[req] = {
        "status": "PASS" if "PASS" in verdict else "FAIL",
        "verdict": verdict,
        "placed_count": len(new_placed),
        "failed_count": len(failed),
        "type_counts": type_counts,
    }

# ── 최종 요약 ──────────────────────────────────────────────────
print(f"\n{'='*60}")
print("[최종 요약]")
print(f"{'='*60}")
for req, res in results.items():
    status = res.get("status", "?")
    symbol = "✓" if status == "PASS" else "✗"
    print(f"{symbol} \"{req}\"")
    print(f"    → {res.get('verdict', res.get('detail', ''))}")

# 결과를 JSON으로 저장
with open("test_results.json", "w", encoding="utf-8") as f:
    json.dump({"base_placed": [o.get("object_type") for o in placed], "tests": results}, f, ensure_ascii=False, indent=2)
print("\n결과 저장: test_results.json")
