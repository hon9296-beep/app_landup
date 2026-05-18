"""
demo_brands 폴더용 large DXF 생성 — 100평 안팎 3종.

표준 레이어 박힌 도면 = nodes_large/parser_dxf 의 `_parse_by_layer` 직접 추출.

레이어:
  - usable_poly       : 외곽선 (LWPOLYLINE)
  - entrance_zone     : 입구 (LINE)
  - core_toilet       : 화장실 (LWPOLYLINE)
  - dead_zone_pillar  : 기둥 (LWPOLYLINE, factory 만)
  - mep_sprinkler     : 스프링클러 (CIRCLE)

도면:
  - 100py_rect.dxf    : 직사각형 22m × 15m = 330m² (100평) + 스프링클러 6개
  - 100py_tshape.dxf  : T자형 윗 24m×12m + 다리 8m×6m = 336m² (102평) + 스프링클러 8개
  - 100py_factory.dxf : 공장형 25m×14m + 기둥 5개 = 347m² (≈105평) + 스프링클러 8개
"""
import os
import ezdxf

OUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "demo_brands")
)

SPRINKLER_RADIUS_MM = 200  # 표시용 반경 (실제 살수 반경 3000~4000mm 와 별개)


def _new_doc():
    doc = ezdxf.new(dxfversion="R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # millimeters
    doc.layers.add(name="usable_poly", color=7)        # 외곽선
    doc.layers.add(name="entrance_zone", color=3)      # 입구 (green)
    doc.layers.add(name="core_toilet", color=5)        # 화장실 (blue)
    doc.layers.add(name="dead_zone_pillar", color=1)   # 기둥 (red)
    doc.layers.add(name="mep_sprinkler", color=6)      # 스프링클러 (magenta)
    return doc


def _add_sprinklers(msp, points):
    for x, y in points:
        msp.add_circle(
            center=(x, y),
            radius=SPRINKLER_RADIUS_MM,
            dxfattribs={"layer": "mep_sprinkler"},
        )


def gen_rect():
    """직사각형 22m × 15m = 330m² (100평) + 스프링클러 6개."""
    doc = _new_doc()
    msp = doc.modelspace()

    # 외곽
    msp.add_lwpolyline(
        [(0, 0), (22000, 0), (22000, 15000), (0, 15000)],
        close=True,
        dxfattribs={"layer": "usable_poly"},
    )

    # 입구 (하단 중앙, 폭 1200mm) — LINE 으로 그리면 parser 가 중점을 입구로 잡음
    msp.add_line(
        (10400, 0), (11600, 0),
        dxfattribs={"layer": "entrance_zone"},
    )

    # 화장실 (우측 상단 2m × 3m)
    msp.add_lwpolyline(
        [(20000, 12000), (22000, 12000), (22000, 15000), (20000, 15000)],
        close=True,
        dxfattribs={"layer": "core_toilet"},
    )

    # 스프링클러 그리드 — 3 cols × 2 rows = 6개. 간격 5500mm × 5000mm
    sprinklers = [
        (5500, 5000), (11000, 5000), (16500, 5000),
        (5500, 10000), (11000, 10000), (16500, 10000),
    ]
    _add_sprinklers(msp, sprinklers)

    out = os.path.join(OUT_DIR, "demo_large_rect.dxf")
    doc.saveas(out)
    return out, 22 * 15


def gen_tshape():
    """T자형 윗 24m×12m + 다리 8m×6m = 336m² (102평) + 스프링클러 8개.

    좌표: 좌하단 (0,0). 다리: x=8000~16000, y=0~6000. 윗부분: x=0~24000, y=6000~18000.
    """
    doc = _new_doc()
    msp = doc.modelspace()

    msp.add_lwpolyline(
        [
            (8000, 0), (16000, 0), (16000, 6000), (24000, 6000),
            (24000, 18000), (0, 18000), (0, 6000), (8000, 6000),
        ],
        close=True,
        dxfattribs={"layer": "usable_poly"},
    )

    # 입구 — 다리 끝
    msp.add_line(
        (11400, 0), (12600, 0),
        dxfattribs={"layer": "entrance_zone"},
    )

    # 화장실 — 윗부분 우측 상단
    msp.add_lwpolyline(
        [(21500, 15500), (24000, 15500), (24000, 18000), (21500, 18000)],
        close=True,
        dxfattribs={"layer": "core_toilet"},
    )

    # 스프링클러 — 윗부분 6개 (3×2 그리드) + 다리 2개
    sprinklers = [
        # 윗부분: x=[5000, 12000, 19000], y=[10000, 15000]
        (5000, 10000), (12000, 10000), (19000, 10000),
        (5000, 15000), (12000, 15000), (19000, 15000),
        # 다리: x=12000, y=[2000, 4500]
        (12000, 2000), (12000, 4500),
    ]
    _add_sprinklers(msp, sprinklers)

    out = os.path.join(OUT_DIR, "demo_large_tshape.dxf")
    doc.saveas(out)
    return out, 24 * 12 + 8 * 6


def gen_factory():
    """공장형 25m × 14m + 기둥 5개 + 스프링클러 8개 = 347m² (≈105평)."""
    doc = _new_doc()
    msp = doc.modelspace()

    msp.add_lwpolyline(
        [(0, 0), (25000, 0), (25000, 14000), (0, 14000)],
        close=True,
        dxfattribs={"layer": "usable_poly"},
    )

    # 입구 — 짧은 변 (좌측), 폭 1500mm
    msp.add_line(
        (0, 6250), (0, 7750),
        dxfattribs={"layer": "entrance_zone"},
    )

    # 화장실 — 우측 하단 코너
    msp.add_lwpolyline(
        [(22500, 0), (25000, 0), (25000, 2500), (22500, 2500)],
        close=True,
        dxfattribs={"layer": "core_toilet"},
    )

    # 구조용 기둥 5개 (0.8m × 0.8m) — 공장형 H-beam grid, 가운데 가로축
    pillar_size = 800
    pillar_xs = [4000, 8500, 13000, 17500, 21000]
    pillar_y_center = 7000
    for cx in pillar_xs:
        x0 = cx - pillar_size / 2
        y0 = pillar_y_center - pillar_size / 2
        msp.add_lwpolyline(
            [(x0, y0), (x0 + pillar_size, y0),
             (x0 + pillar_size, y0 + pillar_size), (x0, y0 + pillar_size)],
            close=True,
            dxfattribs={"layer": "dead_zone_pillar"},
        )

    # 스프링클러 — 4 cols × 2 rows = 8개. 공장형은 천장 높아서 촘촘.
    # x=[5000, 10000, 15000, 20000], y=[4000, 11000] (기둥 라인 7000 피해서 위/아래)
    sprinklers = [
        (5000, 4000), (10000, 4000), (15000, 4000), (20000, 4000),
        (5000, 11000), (10000, 11000), (15000, 11000), (20000, 11000),
    ]
    _add_sprinklers(msp, sprinklers)

    out = os.path.join(OUT_DIR, "demo_large_factory.dxf")
    doc.saveas(out)
    return out, 25 * 14 - 5 * (0.8 * 0.8)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for fn, name in [(gen_rect, "rect"), (gen_tshape, "tshape"), (gen_factory, "factory")]:
        path, area_m2 = fn()
        py = area_m2 / 3.3058
        print(f"[{name}] {path}")
        print(f"        area = {area_m2:.1f} m^2 = {py:.1f} pyeong")


if __name__ == "__main__":
    main()
