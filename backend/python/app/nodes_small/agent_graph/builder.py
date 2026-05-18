"""agent_graph 빌더 — design ~ pathing_validator sub-graph 정의.

진규님 의도 (5-5):
  graph.py 의 build_small_graph (디버그용) 와 별개. nodes_small 폴더 안 self-contained
  sub-graph. design 부터 pathing_validator 까지 LLM agent 자율 흐름만 graph 화.
  전처리 (parser/vision/dead_zone/object_selection 등) + 후처리 (sub_path/glb_exporter
  /report_gen 등) 는 place_service 의 직접 호출 유지.

흐름 (1-3 #533 C1 — pathing_validator 진입):
  design → design_reviewer
    ├─ pass / 수렴 / 한도 → partition_placement → placement → verify
    │                                                  ├─ failed + round<2 → failure_classifier → fallback → verify
    │                                                  └─ done → placement_reviewer
    │                                                              ├─ pass / 한도 → pathing_validator
    │                                                              │                  ├─ pass / 한도 → END
    │                                                              │                  └─ reject + iter<MAX → design (trapped hint inject)
    │                                                              └─ reject → design (slot 양보 hint inject)
    └─ reject + iter<MAX → design (재호출, _reviewer_feedback inject)

각 분기 조건은 routes.py 의 route_after_* 함수 참조.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END

from app.state import SmallState
from app.nodes_small import (
    design,
    design_reviewer,
    partition_placement,
    placement,
    verify,
    failure_classifier,
    fallback,
    placement_reviewer,
    pathing_validator,
)
from .routes import (
    route_after_design_reviewer,
    route_after_verify,
    route_after_placement_reviewer,
    route_after_pathing_validator,
)


def build_agent_graph() -> StateGraph:
    """design ~ pathing_validator sub-graph 정의 (compile 전).

    place_service.place_small() 이 \\_AGENT_GRAPH (compile 결과) 를 invoke.
    재시도 한도 / 수렴 등은 reviewer 노드 자체에서 결정 → 본 graph 는 분기만.
    """
    g = StateGraph(SmallState)

    # ── 노드 등록 (9 — 1-3 #533 C1: pathing_validator 추가) ──
    g.add_node("design", design.run)
    g.add_node("design_reviewer", design_reviewer.run)
    g.add_node("partition_placement", partition_placement.run)
    g.add_node("placement", placement.run)
    g.add_node("verify", verify.run)
    g.add_node("failure_classifier", failure_classifier.run)
    g.add_node("fallback", fallback.run)
    g.add_node("placement_reviewer", placement_reviewer.run)
    g.add_node("pathing_validator", pathing_validator.run)

    # ── entry ──
    g.set_entry_point("design")

    # ── 직선 ──
    g.add_edge("design", "design_reviewer")

    # ── design_reviewer 후 분기 ──
    g.add_conditional_edges(
        "design_reviewer",
        route_after_design_reviewer,
        {
            "design": "design",                  # reject + iter < MAX
            "partition_placement": "partition_placement",  # pass / skipped / 수렴 / 한도
        },
    )

    g.add_edge("partition_placement", "placement")
    g.add_edge("placement", "verify")

    # ── verify 후 분기 (fallback loop / placement_reviewer 진입) ──
    g.add_conditional_edges(
        "verify",
        route_after_verify,
        {
            "failure_classifier": "failure_classifier",  # failed + round<2
            "placement_reviewer": "placement_reviewer",  # done
        },
    )
    g.add_edge("failure_classifier", "fallback")
    g.add_edge("fallback", "verify")  # loop

    # ── placement_reviewer 후 분기 (1-3 #533 C1: pass → pathing_validator) ──
    g.add_conditional_edges(
        "placement_reviewer",
        route_after_placement_reviewer,
        {
            "design": "design",                          # reject + iter < MAX (slot 양보 hint inject)
            "pathing_validator": "pathing_validator",    # pass / skipped / 한도 → 동선 검증
        },
    )

    # ── pathing_validator 후 분기 (1-3 #533 C1) ──
    g.add_conditional_edges(
        "pathing_validator",
        route_after_pathing_validator,
        {
            "design": "design",   # trapped + iter < MAX (trapped hint inject)
            END: END,             # pass / 한도
        },
    )

    return g


# 모듈 레벨 1회 컴파일 (재컴파일 비용 절감)
AGENT_GRAPH = build_agent_graph().compile()
