"""
노드 단위 테스트 — nodes_small (소·중형, Rendy 담당).

실행: cd landup_team/backend && python -m pytest tests/test_nodes_small.py -v

참고:
  - nodes_small은 SmallState 기반 (state.py 참조)
  - slot 룰 기반 배치 (ref_point 아님)
  - import 경로: from app.nodes_small.xxx import run
  - base_state는 SmallState 구조에 맞춰 작성해야 함
  - 면적 기준: 165m² 미만 (api.py _is_large() 참조)

예시 구조:
  from app.nodes_small.slot_gen import run as slot_run
  from app.nodes_small.dead_zone import run as dead_zone_run
  from app.nodes_small.object_selection import run as obj_run
  from app.nodes_small.design import run as design_run
  from app.nodes_small.placement import run as placement_run

TODO: SmallState 기준 fixture + 테스트 케이스 작성
"""
