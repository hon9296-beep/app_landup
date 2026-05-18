"""
LangGraph 시각화 (Mermaid 텍스트 출력) — Issue #517.

사용:
    python -m scripts.visualize_graphs              # stdout 출력
    python -m scripts.visualize_graphs > out.md     # 파일로 저장

대상 5 graph:
  - compile_detect_large_graph        (운영 사용 — handlers/detect.py)
  - compile_space_data_large_graph    (Large 운영 — handlers/space_data.py)
  - compile_place_large_graph         (Large 운영 — services/place_service.py)
  - compile_large_graph               (Dead code — /api/run 디버그만, Shin 영역)
  - AGENT_GRAPH                       (Small 운영 sub-graph — 본인 5-5 작업)

(2026-05-06 1-1: build_small_graph 제거됨 — Small 운영은 place_service.place_small + AGENT_GRAPH 가 담당)

출력 형태:
  각 graph 마다 ## 섹션 + ```mermaid 블록.
  GitHub / VS Code / Notion 미리보기에서 자동 렌더링.
"""
from __future__ import annotations

import sys

# Windows cp949 콘솔에서 UTF-8 출력 (em-dash / 한글 mermaid label 등)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _render(name: str, compiled, note: str = "") -> None:
    """compiled graph 의 mermaid 텍스트를 stdout 으로 출력."""
    print(f"\n## {name}")
    if note:
        print(f"\n> {note}")
    print("\n```mermaid")
    print(compiled.get_graph().draw_mermaid())
    print("```")


def main() -> int:
    print("# LangGraph 시각화 (Mermaid)\n")
    print("Issue #517 — 시각화 3종 비교 1단계 (Mermaid 텍스트 출력).")

    from app.graph import (
        compile_detect_large_graph,
        compile_space_data_large_graph,
        compile_place_large_graph,
        compile_large_graph,
    )
    from app.nodes_small.agent_graph import AGENT_GRAPH

    targets = [
        ("detect_large_graph", compile_detect_large_graph(),
         "운영 사용 — handlers/detect.py 가 invoke. parser × 3 + vision."),
        ("space_data_large_graph", compile_space_data_large_graph(),
         "Large 운영 — handlers/space_data.py large 분기. dead_zone + ref_point_gen."),
        ("place_large_graph", compile_place_large_graph(),
         "Large 운영 — services/place_service.place_large. 20 노드 + 3 conditional_edges + fallback loop."),
        ("AGENT_GRAPH (Small 운영 sub-graph)", AGENT_GRAPH,
         "Small 운영 — services/place_service.place_small 가 invoke. 8 노드 + 3 conditional_edges."),
        ("build_large_graph (DEAD CODE)", compile_large_graph(),
         "/api/run 디버그 + tests 만 사용 (Shin 영역, 옵션 B 결정으로 보존)."),
    ]

    for name, g, note in targets:
        try:
            _render(name, g, note)
        except Exception as e:
            print(f"\n## {name}\n\n> ❌ 렌더 실패: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
