"""
가벽 (partition_wall) 후속 활용 로직 — A-3 (#115).

가벽은 structure (구조물) 로 일반 furniture 와 다른 상위 개념. partition_placement.py
의 초기 배치 후, 다른 기물의 fallback 시점에서 partition 을 재활용하는 로직을 본 모듈에서 전담.

미래 추가 로직 (재배치 / 면 변경 / 회전 등) 도 본 모듈에 누적.

호출 위치: app/nodes_small/fallback.py 의 Phase 3 (실패) 후 Phase 4 진입 전 — photo_wall 한정.

설계 원칙:
- LLM 의도 무관 — 코드가 자동 처리 (진규님 "유연 운영" 의도)
- 단방향 한정 — partition → photo_wall 대체만. 역방향 (photo_wall → partition) 절대 금지
- feature flag (LANDUP_PARTITION_REUSE) — 2026-05-08 default ON 전환 (그래픽 월 가이드 활성화).
  opt-out 만 허용: LANDUP_PARTITION_REUSE=0 명시 시만 비활성화. 그 외 기본 ON.
- graceful degradation — 사용자 화면 노출 X. 디버그/운영자만 인지
"""
from __future__ import annotations

import logging
import os

from app.state import SmallState

logger = logging.getLogger(__name__)


def try_reuse_partition_for_photo_wall(state: SmallState, failed_obj: dict) -> bool:
    """photo_wall 배치 실패 시 기존 partition_wall_I/L 재활용 (graphic_face='outer' 할당).

    조건 (모두 충족 시 재활용 시도):
    1. LANDUP_PARTITION_REUSE env != "0" (opt-out 만, 2026-05-08 default ON 전환)
    2. failed_obj.object_type == "photo_wall"
    3. placed_objects 에 graphic_face=="none" 인 partition_wall_I/L 존재

    2026-05-08: facade gate (allow_rear_graphic_wall) 제거. 진규님 5-8 결정 — 본 시스템은
    매장 내부 photo_wall 대체용. facade 시인성 (외부 광고) 과 무관하게 자리 부족 시
    가벽 그래픽 면이 photo_wall 역할. closed 매장도 활성화.

    선정 규칙:
    - 가장 가까운 partition (entrance 거리 최소)
    - 미래 — raycasting max_front_clearance_mm / 시인성 score 등 보강 가능

    부작용 (성공 시):
    - 선정된 partition 의 graphic_face: 'none' → 'outer'
    - graphic_face_basis: 'default_front' → 'photo_wall_substitute'
    - logger.info 기록 (운영자 가시성)

    return:
    - True: 재활용 성공 — 호출자가 photo_wall 을 placed 처리해야 함
    - False: skip — 호출자가 다음 fallback Phase 진행
    """
    # 2026-05-08: Gate 별 진단 추적 (5-8 라이브 partition_reuse 미작동 진단)
    from app.nodes_small.agent_graph.reason_dump import dump_agent_reason

    # Gate 1: feature flag (2026-05-08 default ON 전환 — opt-out 만)
    env_val = os.environ.get("LANDUP_PARTITION_REUSE")
    if env_val == "0":
        dump_agent_reason(state, node="partition_reuse", decision="gate1_blocked",
                          reason=f"LANDUP_PARTITION_REUSE='{env_val}' opt-out",
                          context={"env": env_val})
        return False

    # Gate 2: photo_wall 한정 (다른 객체엔 본 로직 적용 X)
    if failed_obj.get("object_type") != "photo_wall":
        dump_agent_reason(state, node="partition_reuse", decision="gate2_blocked",
                          reason=f"obj_type={failed_obj.get('object_type')} != photo_wall",
                          context={"obj_type": failed_obj.get("object_type")})
        return False

    # Gate 3 (2026-05-08 제거): facade 시인성 제거. 진규님 5-8 결정 — 매장 내부 photo_wall
    # 대체용이라 facade 무관 활성화. closed 매장도 partition.graphic_face='outer' 부여 가능.

    # Gate 4: 재활용 후보 파악 (graphic_face='none' 인 partition_wall_I/L)
    placed = state.get("placed_objects", []) or []
    partitions_in_placed = [
        {"obj_type": p.get("object_type"), "anchor_key": p.get("anchor_key"),
         "graphic_face": p.get("graphic_face"), "center": (p.get("center_x_mm"), p.get("center_y_mm"))}
        for p in placed if str(p.get("object_type", "")).startswith("partition_wall")
    ]
    candidates = [
        p for p in placed
        if str(p.get("object_type", "")).startswith("partition_wall")
        and p.get("graphic_face", "none") == "none"
    ]
    if not candidates:
        logger.info(
            "[partition_reuse] photo_wall 대체 skip — "
            "후보 partition (graphic_face='none') 없음"
        )
        dump_agent_reason(state, node="partition_reuse", decision="gate4_blocked",
                          reason=f"graphic_face='none' partition 후보 0",
                          context={
                              "placed_objects_count": len(placed),
                              "partitions_in_placed": partitions_in_placed,
                          })
        return False

    # 선정: entrance 거리 최소
    entrance = state.get("entrance_mm") or (0, 0)
    ex, ey = entrance[0], entrance[1]
    best = min(
        candidates,
        key=lambda p: ((p.get("center_x_mm", 0) - ex) ** 2 + (p.get("center_y_mm", 0) - ey) ** 2) ** 0.5,
    )

    # 부작용: graphic_face / graphic_face_basis / label 갱신
    best["graphic_face"] = "outer"
    best["graphic_face_basis"] = "photo_wall_substitute"
    # 2026-05-08: 프론트 표시 구분용 label — 일반 partition_wall_I 와 시각적 구분.
    best_obj_type = best.get("object_type", "partition_wall_I")
    best["label"] = f"{best_obj_type} (graphic_wall)"

    # 2026-05-08: state.placed_raw 의 동일 partition entry 도 동기화.
    # 이유: place_serializer.py:182 가 dump 시 state.placed_raw (원본 entry) 직렬화 →
    # state.placed_objects 와 별도 list. partition_reuse 가 placed_objects 만 변경하면
    # dump 에 graphic_face='none' 으로 나타나는 회귀 (5-8 16:23 라이브 진단).
    # anchor_key 매칭으로 동일 partition entry 식별 후 동기화.
    for raw in state.get("placed_raw", []) or []:
        if (raw.get("anchor_key") == best.get("anchor_key")
                and str(raw.get("object_type", "")).startswith("partition_wall")):
            raw["graphic_face"] = "outer"
            raw["graphic_face_basis"] = "photo_wall_substitute"
            raw["label"] = f"{raw.get('object_type', 'partition_wall_I')} (graphic_wall)"
            break

    logger.info(
        f"[partition_reuse] photo_wall 대체 성공: "
        f"{best.get('object_type')} @ {best.get('anchor_key')} "
        f"center=({best.get('center_x_mm', 0):.0f}, {best.get('center_y_mm', 0):.0f}) "
        f"graphic_face='none' → 'outer' (basis=photo_wall_substitute)"
    )
    dump_agent_reason(state, node="partition_reuse", decision="success",
                      reason=f"absorbed photo_wall via {best.get('anchor_key')}",
                      context={
                          "best_anchor_key": best.get("anchor_key"),
                          "best_center": (best.get("center_x_mm"), best.get("center_y_mm")),
                          "candidates_count": len(candidates),
                          "graphic_face_after": best.get("graphic_face"),
                      })
    return True
