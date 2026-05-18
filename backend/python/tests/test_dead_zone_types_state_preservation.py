"""
SmallState / LargeState 에 `dead_zone_types` 정의 + LangGraph schema drop 방지 회귀 차단.

진규님 5-8 라이브 진단:
  - "코드단위로 차단했는데 왜 자꾸 계단 입구앞에다 배치하지?"
  - 시뮬 (dump 데이터) 에서는 partition_placement static_cache reject 정상 작동
  - 라이브 reject_log = [] 로 통과 — state.dead_zone_types 가 partition_placement 진입 시점 누락
  - 근본 원인: SmallState 에 dead_zone_types 미정의 → LangGraph TypedDict reducer 가 drop
  - 동일 패턴: inaccessible_types 가 5-6 에 같은 이유로 추가됨 (line 90 주석 "state drop 방지")

영향 범위:
  - dead_zone_types 누락 → extract_structural_dead_zones 의 `i >= len(dz_types)` 조건으로 모든 dz skip
  - structural_dz 빈 list → core_access 미생성
  - 계단 입구 1500mm 감압존 (소방법) 무력화
  - partition / object 가 계단 앞 침범 회귀
"""
from typing import get_type_hints

from app.state import SmallState


def test_small_state_has_dead_zone_types():
    """SmallState 에 dead_zone_types 정의 — LangGraph schema drop 방지.

    LargeState 는 신님 영역 + Large 라이브 회귀 미확인 → 본 fix scope 외.
    """
    hints = get_type_hints(SmallState)
    assert "dead_zone_types" in hints, (
        "SmallState 에 dead_zone_types 누락 — LangGraph 가 dead_zone.py return 의 dead_zone_types 를 drop → "
        "extract_structural_dead_zones 가 빈 list 로 모든 dz skip → core_access 미생성 → 계단 감압존 무력화 회귀"
    )


def test_small_state_dead_zone_types_paired_with_dead_zones():
    """SmallState 에 dead_zones 정의된 곳에 dead_zone_types 도 동시 정의 — 1:1 대응 원칙.

    dead_zone.py 가 두 키를 동시에 박음. state schema 도 동시 보존돼야 사용처
    (extract_structural_dead_zones / partition_placement / placement) 가 정상 동작.
    """
    hints = get_type_hints(SmallState)
    if "dead_zones" in hints:
        assert "dead_zone_types" in hints, (
            "SmallState 에 dead_zones 있는데 dead_zone_types 없음 — 1:1 대응 위반"
        )


def test_agent_graph_compile_with_dead_zone_types():
    """SmallState 변경 후 AGENT_GRAPH compile 가능 (schema 무결성)."""
    from app.nodes_small.agent_graph import build_agent_graph
    g = build_agent_graph()
    compiled = g.compile()
    assert compiled is not None


def test_extract_structural_dead_zones_with_types_present():
    """state.dead_zone_types 가 살아있을 때 extract_structural_dead_zones 가 core_access 생성.

    회귀 차단의 핵심 — 라이브 5-8 14:15 처럼 dead_zone_types 가 빈 list 면 core_access 0 개.
    """
    from shapely.geometry import Polygon
    from app.utils import extract_structural_dead_zones

    floor = Polygon([(0, 11000), (6000, 9000), (6000, 0), (0, 0)])
    stair = Polygon([(2000, 0), (4700, 0), (4700, 1200), (2000, 1200)])
    state = {
        "usable_poly": floor,
        "dead_zones": [stair],
        "dead_zone_types": ["stair"],
    }
    sd = extract_structural_dead_zones(state)
    types = [e["type"] for e in sd]
    assert "stair" in types
    assert "core_access" in types, (
        "stair 가 있는데 core_access 미생성 — _build_stair_core_access 회귀"
    )


def test_extract_structural_dead_zones_with_types_dropped():
    """state.dead_zone_types 가 빈 list (LangGraph drop 시) → core_access 미생성 (회귀 시뮬).

    이 케이스가 5-8 라이브에서 발생. dead_zones 정의 + dead_zone_types 누락.
    """
    from shapely.geometry import Polygon
    from app.utils import extract_structural_dead_zones

    floor = Polygon([(0, 11000), (6000, 9000), (6000, 0), (0, 0)])
    stair = Polygon([(2000, 0), (4700, 0), (4700, 1200), (2000, 1200)])
    state = {
        "usable_poly": floor,
        "dead_zones": [stair],
        # dead_zone_types 없음 (LangGraph drop 시뮬)
    }
    sd = extract_structural_dead_zones(state)
    # dz_types 빈 list → 모든 dz skip → structural_dz 빈 list → core_access 0
    assert len(sd) == 0, (
        "dead_zone_types 누락 시 structural_dz 가 빈 list 가 돼야 함 (회귀 시뮬). "
        "이게 라이브 5-8 의 근본 원인"
    )
