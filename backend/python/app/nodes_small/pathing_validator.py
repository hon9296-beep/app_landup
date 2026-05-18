"""
방문자 동선 검증 노드 — yeonhwa/agent3/pathing_validator.py 기반.

Dijkstra 최단경로로 입구 → 각 오브젝트 접근 가능 여부 검증.
viewing zone (600~2500mm) 기반 관람 위치 탐색.

1-3 (#533) C1 — sub-graph 진입:
  기존 place_service 직접 호출 → agent_graph 9번째 노드로 격리.
  trapped_objects 발생 시 design 재호출 (재기획 권한) — 진규님 비전대로
  agent 자율 판단 (양보 / 이동 / 띄움). 코드 측 강제 fix 금지.

흐름:
  placement_reviewer (pass) → pathing_validator
    - status="pass" (trapped 0) → END
    - status="reject" (trapped > 0) + iter<MAX → design 재호출 (_pathing_validator_feedback inject)
    - iter>=MAX → END (warning)
"""
import math
import logging

import networkx as nx
from shapely.geometry import Point, box as shapely_box

from app.state import SmallState

logger = logging.getLogger(__name__)

GRID_STEP_MM = 1000  # 1m 해상도 (yeonhwa 원본)
HUMAN_BUFFER_MM = 600  # 인간 통과 최소 보장 폭의 절반
VIEW_MIN_MM = 600
VIEW_MAX_MM = 2500

# ── 종료 조건 상수 (1-3 #533 C1) ─────────────────────────────
# MAX_PATHING_REVIEW_ITERATIONS 변천:
#   - 1-3 #533 C1: 2 (design_reviewer / placement_reviewer 와 일관)
#   - 1-3 후속 (#535 후속, 5-7 라이브 분석 D): 2 → 1 (retry 무용 + 시간 단축)
# 변경 사유: design_reviewer / placement_reviewer 와 동시 변경 (B4 일관성 정책 준수).
# 5-7 라이브 측정 결과 retry 가 회귀 fix 못 함 + 시간 ↑ — 결정적 fix 는
# pair_rules / placement priority / prompt 영역.
MAX_PATHING_REVIEW_ITERATIONS = 1


def _build_trapped_feedback(trapped: list[str], placed: list[dict]) -> str:
    """trapped_objects → design 재호출용 자연어 피드백.

    진규님 비전 (autonomous agent): trapped 사유를 명시하고 재배치 권한 부여.
    구체 좌표 / 강제 zone 명시 절대 X — design 이 placed 현황 보고 양보 / 이동 자율 판단.
    """
    if not trapped:
        return ""
    trapped_set = set(trapped)
    surrounding = []
    for p in placed:
        if p.get("object_type") in trapped_set:
            continue
        zone = p.get("zone_label", "?")
        ot = p.get("object_type", "?")
        surrounding.append(f"  - {ot} @ {zone}")
    surrounding_summary = "\n".join(surrounding[:10]) or "  (참고 placed 없음)"

    return f"""
## [pathing_validator 피드백 — 동선 차단 obj 재배치]
다음 obj 가 입구에서 Dijkstra 최단경로로 **접근 불가** (방문자가 도달 못 함):
{chr(10).join(f'  - {t}' for t in trapped)}

**원인 후보** (자율 판단):
- 주변 placed obj 들이 600mm 인간 통과 폭을 막아 통로 단절
- viewing zone (600~2500mm 거리) 안에 도달 가능한 좌표 0개
- usable_poly 외곽 / 사각지대 매핑

**현재 placed obj (참고 — 양보 후보)**:
{surrounding_summary}

**[재기획 권한]**:
- 차단된 obj 의 zone / ref_point 재기획 — 입구 동선 안쪽으로 이동
- 주변 placed obj 양보 — 통로 폭 확보 위해 인접 obj 의 위치 재기획
- 띄움 (Float) — wall_facing 으로 박힌 obj 를 standalone 전환해 동선 확보
- 단순 retry 가 아니라 **placement 결과 + 동선 차단 정보** 종합 재설계
"""


def run(state: SmallState) -> SmallState:
    """입구 → 각 오브젝트 Dijkstra 동선 검증 + design retry 트리거.

    Returns dict — state 에 박힐 키:
      - pathways: list[dict] — 도달 가능 path
      - trapped_objects: list[str] — 도달 불가 obj_type
      - _pathing_validator_status: "pass" | "reject"
      - _pathing_validator_feedback: str (design retry inject 용)
      - _pathing_review_iteration: int (현 호출 후 +1)
    """
    placed = state.get("placed_objects") or []
    usable_poly = state.get("usable_poly")
    entrance_mm = state.get("entrance_mm")
    iteration = state.get("_pathing_review_iteration", 0)

    if not placed or not usable_poly or not entrance_mm:
        return {
            "pathways": [],
            "trapped_objects": [],
            "_pathing_validator_status": "pass",
            "_pathing_validator_feedback": "",
            "_pathing_review_iteration": iteration + 1,
        }

    # 1. 장애물 bbox 생성 (600mm 버퍼)
    obstacle_boxes = []
    for obj in placed:
        cx, cy = obj["center_x_mm"], obj["center_y_mm"]
        w_h = obj.get("width_mm", 600) / 2
        d_h = obj.get("depth_mm", 400) / 2
        obstacle_boxes.append(
            shapely_box(
                cx - w_h - HUMAN_BUFFER_MM,
                cy - d_h - HUMAN_BUFFER_MM,
                cx + w_h + HUMAN_BUFFER_MM,
                cy + d_h + HUMAN_BUFFER_MM,
            )
        )

    # 2. 그리드 그래프 구축
    minx, miny, maxx, maxy = usable_poly.bounds
    G = nx.Graph()
    grid_nodes = []

    for gx in range(int(minx), int(maxx) + GRID_STEP_MM, GRID_STEP_MM):
        for gy in range(int(miny), int(maxy) + GRID_STEP_MM, GRID_STEP_MM):
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            blocked = any(obs.contains(pt) for obs in obstacle_boxes)
            if blocked:
                continue
            G.add_node((gx, gy))
            grid_nodes.append((gx, gy))

    # 인접 노드 연결 (대각선 포함)
    for i, n1 in enumerate(grid_nodes):
        for n2 in grid_nodes[i + 1:]:
            dist = math.hypot(n1[0] - n2[0], n1[1] - n2[1])
            if dist <= GRID_STEP_MM * 1.5:
                G.add_edge(n1, n2, weight=dist)

    if not grid_nodes:
        logger.warning("[pathing] 가동 노드 없음 — 공간 부족")
        trapped_all = [obj["object_type"] for obj in placed]
        return {
            "pathways": [],
            "trapped_objects": trapped_all,
            "_pathing_validator_status": "reject",
            "_pathing_validator_feedback": _build_trapped_feedback(trapped_all, placed),
            "_pathing_review_iteration": iteration + 1,
        }

    # 입구 노드
    ex, ey = entrance_mm
    start_node = min(grid_nodes, key=lambda p: math.hypot(ex - p[0], ey - p[1]))

    # 3. 각 오브젝트에 대해 Dijkstra
    pathways = []
    trapped = []

    for obj in placed:
        ox, oy = obj["center_x_mm"], obj["center_y_mm"]

        # viewing zone: 오브젝트에서 600~2500mm 거리의 노드
        candidates = [
            n for n in grid_nodes
            if VIEW_MIN_MM < math.hypot(ox - n[0], oy - n[1]) < VIEW_MAX_MM
        ]
        if not candidates:
            trapped.append(obj["object_type"])
            continue

        target = min(candidates, key=lambda p: math.hypot(ox - p[0], oy - p[1]))

        try:
            path = nx.shortest_path(G, source=start_node, target=target, weight="weight")
            pathways.append({
                "path_id": f"route_to_{obj['object_type']}",
                "object_type": obj["object_type"],
                "nodes": [{"x": p[0], "y": p[1]} for p in path],
                "distance_mm": round(nx.shortest_path_length(G, start_node, target, weight="weight")),
            })
        except nx.NetworkXNoPath:
            trapped.append(obj["object_type"])
            logger.warning(f"[pathing] {obj['object_type']} 접근 불가")

    status = "reject" if trapped else "pass"
    feedback = _build_trapped_feedback(trapped, placed) if trapped else ""

    logger.info(
        f"[pathing] iter={iteration} status={status} "
        f"{len(pathways)} paths, {len(trapped)} trapped"
    )

    # 1-2 (#520 후속): sub_graph_reasons dump
    try:
        from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
        dump_agent_reason(state, node="pathing_validator", decision=status,
                          reason=f"trapped={len(trapped)} pathways={len(pathways)}",
                          context={
                              "iteration": iteration,
                              "trapped_objects": trapped,
                              "pathway_count": len(pathways),
                              "feedback_excerpt": feedback[:500] if feedback else "",
                          })
    except Exception as e:
        logger.warning(f"[pathing] reason_dump 실패 — skip: {e}")

    return {
        "pathways": pathways,
        "trapped_objects": trapped,
        "_pathing_validator_status": status,
        "_pathing_validator_feedback": feedback,
        "_pathing_review_iteration": iteration + 1,
    }
