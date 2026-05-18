import io, sys, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
BRAND_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\01_ryancorp_spec.pdf"
FLOOR_FILE = r"C:\Users\804\Documents\카카오톡 받은 파일\demo_brands2\18pyeong.dxf"

# detect
with open(FLOOR_FILE, "rb") as f:
    r = requests.post(f"{BASE}/api/detect", files={"floor_plan": ("18pyeong.dxf", f)}, data={"file_type": "dxf"})
detect = r.json()
print("DETECT keys:", list(detect.keys()))
print("polygon_px:", detect.get("floor_polygon_px"))
print("entrance:", detect.get("entrance"))
print("scale:", detect.get("scale_mm_per_px"))

# brand
with open(BRAND_FILE, "rb") as f:
    r = requests.post(f"{BASE}/api/brand", files={"brand_manual": ("01_ryancorp_spec.pdf", f)}, data={"file_type": "pdf"}, timeout=120)
brand = r.json()
print("\nBRAND response (top-level keys):", list(brand.keys()))
print("brand sub-keys:", list(brand.get("brand", {}).keys()) if "brand" in brand else "NO BRAND KEY")
print("placement_rules count:", len(brand.get("placement_rules", [])))
print("full brand.brand:", json.dumps(brand.get("brand", {}), ensure_ascii=False, indent=2)[:800])

# space-data
cat = brand.get("brand", {}).get("brand_category", "기타")
if isinstance(cat, dict): cat = cat.get("value", "기타")
space_body = {"auto_detected": detect, "brand_dict": brand, "brand_category": cat}
r = requests.post(f"{BASE}/api/space-data", json=space_body)
space_resp = r.json()
print("\nSPACE_DATA response (top keys):", list(space_resp.keys()))
sd = space_resp.get("space_data", space_resp)
print("space_data keys:", list(sd.keys()) if isinstance(sd, dict) else type(sd))
print("scale_type:", sd.get("scale_type"))
print("usable_area_sqm:", sd.get("usable_area_sqm"))
print("floor.polygon_mm len:", len(sd.get("floor", {}).get("polygon_mm", [])))
print("floor full:", json.dumps(sd.get("floor", {}), ensure_ascii=False)[:300])
print("entrance:", sd.get("entrance"))
