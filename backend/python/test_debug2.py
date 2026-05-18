import io, sys, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
BRAND_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\01_ryancorp_spec.pdf"
FLOOR_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\18pyeong.dxf"

# detect
with open(FLOOR_FILE, "rb") as f:
    detect = requests.post(f"{BASE}/api/detect", files={"floor_plan": ("18pyeong.dxf", f)}, data={"file_type": "dxf"}).json()

# brand
with open(BRAND_FILE, "rb") as f:
    brand = requests.post(f"{BASE}/api/brand", files={"brand_manual": ("01_ryancorp_spec.pdf", f)}, data={"file_type": "pdf"}, timeout=120).json()

# space-data
cat = brand.get("brand", {}).get("brand_category", "기타")
if isinstance(cat, dict): cat = cat.get("value", "기타")
sd_resp = requests.post(f"{BASE}/api/space-data", json={"auto_detected": detect, "brand_dict": brand, "brand_category": cat}).json()
sd = sd_resp.get("space_data", sd_resp)

print("dead_zones:", sd.get("dead_zones"))
print("main_artery:", str(sd.get("main_artery", "none"))[:100])
print("reference_points count:", len(sd.get("reference_points", [])))
print("floor:", json.dumps(sd.get("floor", {}), ensure_ascii=False))
print("entrance:", sd.get("entrance"))

# place 전체 raw 응답
place_body = {
    "floor": sd.get("floor", {}),
    "entrance": sd.get("entrance", {}),
    "dead_zones": sd.get("dead_zones", []),
    "sprinklers_mm": sd.get("sprinklers_mm", []),
    "hydrants_mm": sd.get("hydrants_mm", []),
    "electric_panels_mm": sd.get("electric_panels_mm", []),
    "brand_dict": brand,
    "brand_category": cat,
    "venue_type": sd.get("venue_type"),
    "facade_type": sd.get("facade_type"),
    "density_ratio": 0.25,
    "user_requirements": "",
    "locked_objects": [],
}
print("\nplace body (preview):")
print(json.dumps({k: (v if k not in ("brand_dict",) else "...") for k, v in place_body.items()}, ensure_ascii=False, indent=2)[:600])

r = requests.post(f"{BASE}/api/place", json=place_body, timeout=300)
print("\nplace status:", r.status_code)
result = r.json()
print("place response keys:", list(result.keys()) if isinstance(result, dict) else type(result))
print("placed_objects:", len(result.get("placed_objects", [])))
print("failed_objects:", len(result.get("failed_objects", [])))
print("placement_strategy:", result.get("placement_strategy"))
print("eligible_objects count:", len(result.get("eligible_objects", [])))
# print first few placed
for obj in result.get("placed_objects", [])[:5]:
    print("  placed:", obj.get("object_type"), "@", obj.get("anchor_key"), obj.get("zone_label"))
# print any error
if "detail" in result:
    print("ERROR detail:", result["detail"])
