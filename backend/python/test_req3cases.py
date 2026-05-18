"""
요구사항 3케이스 테스트:
1. 상품진열대 두개 제거해줘
2. 계산대 입구쪽으로 옮겨줘
3. 3단 선반을 하나 추가해주고, 진열대를 하나 제거해줘

실행: python test_req3cases.py   (backend/python/ 에서)
"""
import io
import json
import sys
import time
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
BRAND_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\01_ryancorp_spec.pdf"
FLOOR_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\18pyeong.dxf"

TESTS = [
    "상품진열대 두개 제거해줘",
    "계산대 입구쪽으로 옮겨줘",
    "3단 선반을 하나 추가해주고, 진열대를 하나 제거해줘",
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
brand_cat_raw = brand_info.get("brand_category", "기타")
brand_cat = brand_cat_raw.get("value", "기타") if isinstance(brand_cat_raw, dict) else brand_cat_raw
log(f"brand_name: {brand_info.get('brand_name', {}).get('value', '?')}")
log(f"brand_category: {brand_cat}")
log(f"placement_rules: {len(brand_data.get('placement_rules', []))} 개")

# ── Step 3: space-data ─────────────────────────────────────────
step("3. /api/space-data — 공간 계산")
space_body = {
    "auto_detected": detect_result,
    "brand_dict": brand_data,
    "brand_category": brand_cat,
}
r = requests.post(f"{BASE}/api/space-data", json=space_body, timeout=60)
if r.status_code != 200:
    print(f"FAIL: {r.status_code} — {r.text[:300]}")
    sys.exit(1)

space_resp = r.json()
space_data = space_resp.get("space_data", space_resp)
log(f"usable_area_sqm: {space_data.get('usable_area_sqm', '?')}")
log(f"scale_type: {space_data.get('scale_type', '?')}")

# ── Step 4: 기본 배치 ─────────────────────────────────────────
step("4. /api/place — 기본 배치 (요구사항 없음)")


def build_place_body(space_data, brand_data, user_req="", locked=None):
    return {
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
        "locked_objects": locked or [],
    }


t0 = time.time()
r = requests.post(f"{BASE}/api/place", json=build_place_body(space_data, brand_data), timeout=300)
elapsed = time.time() - t0
if r.status_code != 200:
    print(f"FAIL ({elapsed:.0f}s): {r.status_code} — {r.text[:500]}")
    sys.exit(1)

base_result = r.json()
placed = base_result.get("objects", base_result.get("placed", []))
log(f"기본 배치 완료: {len(placed)}개 ({elapsed:.0f}s)")
type_counts_base = {}
for obj in placed:
    ot = obj.get("object_type", "?")
    type_counts_base[ot] = type_counts_base.get(ot, 0) + 1
for ot, cnt in sorted(type_counts_base.items()):
    log(f"  · {ot}: {cnt}개")

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
        log(f"ERROR: {r.text[:800]}")
        results[req] = {"status": "ERROR", "detail": r.text[:500]}
        continue

    result = r.json()
    new_placed = result.get("objects", result.get("placed", []))
    failed = result.get("failed_objects", [])
    resolved = result.get("resolved_intents", [])

    log(f"응답 ({elapsed:.0f}s): 배치 {len(new_placed)}개, 실패 {len(failed)}개")

    # intent 파싱 결과
    log(f"resolved_intents: {len(resolved)}개")
    for ri in resolved:
        log(f"  · action={ri.get('action')} type={ri.get('object_type')} qty={ri.get('quantity')} "
            f"zone={ri.get('zone_hint')} dir={ri.get('direction_hint')} removal={ri.get('is_removal')}")

    # 배치 결과 타입별 카운트
    type_counts = {}
    for obj in new_placed:
        ot = obj.get("object_type", "?")
        type_counts[ot] = type_counts.get(ot, 0) + 1
    log("배치 결과:")
    for ot, cnt in sorted(type_counts.items()):
        base_cnt = type_counts_base.get(ot, 0)
        diff = cnt - base_cnt
        diff_str = f" (기존 {base_cnt} → {cnt}, {'▲+' if diff > 0 else '▼'}{diff})" if diff != 0 else f" (기존과 동일: {cnt}개)"
        log(f"  · {ot}: {cnt}개{diff_str}")

    # 케이스별 자동 검증
    if "상품진열대" in req and "제거" in req:
        base_dt = [o for o in locked_objects if o.get("object_type") in ("display_table", "display_table_standard")]
        new_dt = [o for o in new_placed if o.get("object_type") in ("display_table", "display_table_standard")]
        removed = len(base_dt) - len(new_dt)
        log(f"\n[검증] display_table 기존 {len(base_dt)}개 → 결과 {len(new_dt)}개 (제거 {removed}개)")
        if removed == 2:
            verdict = "PASS — 정확히 2개 제거됨"
        elif removed > 0:
            verdict = f"PARTIAL — {removed}개 제거됨 (2개 요청)"
        else:
            verdict = f"FAIL — 제거 안 됨 (오히려 {abs(removed)}개 {'추가' if removed < 0 else '동일'})"

    elif "계산대" in req and "입구" in req:
        counters = [o for o in new_placed if o.get("object_type") == "counter"]
        log(f"\n[검증] counter {len(counters)}개 배치됨")
        for c in counters:
            log(f"  zone={c.get('zone_label')} dir={c.get('direction')} anchor={c.get('anchor_key')} "
                f"placed_because={c.get('placed_because', '')}")
        entrance_zone = any(
            "entrance" in str(c.get("zone_label", "")).lower() or
            "entrance" in str(c.get("anchor_key", "")).lower() or
            c.get("zone_label") == "입구존"
            for c in counters
        )
        verdict = "PASS" if (counters and entrance_zone) else (
            "PARTIAL — counter는 있으나 입구존 확인 불가" if counters else "FAIL — counter 없음"
        )

    elif "3단 선반" in req and "추가" in req and "제거" in req:
        base_shelf = [o for o in locked_objects if o.get("object_type") == "shelf_3tier"]
        base_dt = [o for o in locked_objects if o.get("object_type") in ("display_table", "display_table_standard")]
        new_shelf = [o for o in new_placed if o.get("object_type") == "shelf_3tier"]
        new_dt = [o for o in new_placed if o.get("object_type") in ("display_table", "display_table_standard")]

        shelf_added = len(new_shelf) - len(base_shelf)
        dt_removed = len(base_dt) - len(new_dt)
        log(f"\n[검증] shelf_3tier {len(base_shelf)} → {len(new_shelf)} (추가 {shelf_added}개, 1개 필요)")
        log(f"[검증] display_table {len(base_dt)} → {len(new_dt)} (제거 {dt_removed}개, 1개 필요)")

        shelf_ok = shelf_added >= 1
        dt_ok = dt_removed >= 1
        if shelf_ok and dt_ok:
            verdict = "PASS — 3단선반 추가 + 진열대 제거 모두 성공"
        elif shelf_ok:
            verdict = f"PARTIAL — 3단선반 추가 성공, 진열대 제거 실패 (제거={dt_removed})"
        elif dt_ok:
            verdict = f"PARTIAL — 진열대 제거 성공, 3단선반 추가 실패 (추가={shelf_added})"
        else:
            verdict = f"FAIL — 둘 다 실패 (shelf_added={shelf_added}, dt_removed={dt_removed})"
    else:
        verdict = "CHECK"

    print(f"\n  {'✓' if 'PASS' in verdict else ('△' if 'PARTIAL' in verdict else '✗')} 결과: {verdict}")
    results[req] = {
        "status": "PASS" if "PASS" in verdict else ("PARTIAL" if "PARTIAL" in verdict else "FAIL"),
        "verdict": verdict,
        "placed_count": len(new_placed),
        "failed_count": len(failed),
        "type_counts": type_counts,
        "type_counts_base": type_counts_base,
    }

# ── 최종 요약 ──────────────────────────────────────────────────
print(f"\n{'='*60}")
print("[최종 요약]")
print(f"{'='*60}")
for req, res in results.items():
    status = res.get("status", "?")
    symbol = "✓" if status == "PASS" else ("△" if status == "PARTIAL" else "✗")
    print(f"{symbol} \"{req}\"")
    print(f"    → {res.get('verdict', res.get('detail', ''))}")

with open("test_req3cases_result.json", "w", encoding="utf-8") as f:
    json.dump({
        "base_placed_types": type_counts_base,
        "tests": results
    }, f, ensure_ascii=False, indent=2)
print("\n결과 저장: test_req3cases_result.json")
