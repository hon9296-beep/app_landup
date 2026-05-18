"""nodes_small/agent_graph — design ~ placement_reviewer sub-graph 패키지.

폴더 분리 의도 (5-5): nodes_small 안에 sub-graph 분리해 알아보기 쉽게.
graph.py 의 build_small_graph (디버그용 통합) 와 무관.

사용:
    from app.nodes_small.agent_graph import AGENT_GRAPH
    state = AGENT_GRAPH.invoke(state)

파일:
    builder.py — build_agent_graph() + AGENT_GRAPH (compile 결과)
    routes.py — conditional_edges 분기 함수들
"""
from .builder import AGENT_GRAPH, build_agent_graph

__all__ = ["AGENT_GRAPH", "build_agent_graph"]
