"""sub-graph 노드별 결정 사유 dump — 라이브 검증 가시성 용.

각 sub-graph 노드 (design / design_reviewer / placement_reviewer / 등) 가 결정 시점
(pass / reject / fallback / skipped) 에 호출. JSON line append 방식으로 한 라이브 실행
= 한 jsonl 파일에 누적. session_id 가 있으면 그 단위로 묶고 없으면 process startup time
사용.

출력 위치: backend/python/debug_logs/sub_graph_reasons/{date}/{session}.jsonl
.gitignore 처리됨 — 로컬 디버그 전용.

호출 예시:
    from app.nodes_small.agent_graph.reason_dump import dump_agent_reason
    dump_agent_reason(state, node="design", decision="fallback",
                      reason="REF_CONTEXT_MISSING",
                      context={"images": 0, "ref_analysis_keys": []})
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# 모듈 로드 시점을 fallback session id 로 사용 — state 에 session_id 없을 때
_PROCESS_START_TS = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _resolve_session_id(state: dict) -> str:
    """state 에서 session_id 추출. 없으면 프로세스 startup time."""
    sid = state.get("session_id") if isinstance(state, dict) else None
    if sid:
        return str(sid)
    return _PROCESS_START_TS


def _resolve_dump_path(session_id: str) -> str:
    """덤프 파일 경로. {date}/{session}.jsonl. 폴더 없으면 생성."""
    today = datetime.now().strftime("%Y-%m-%d")
    base = os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "debug_logs", "sub_graph_reasons", today,
    )
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{session_id}.jsonl")


def dump_agent_reason(
    state: dict,
    node: str,
    decision: str,
    reason: str,
    context: dict | None = None,
) -> None:
    """sub-graph 노드 결정 사유 1건 append.

    Args:
        state: SmallState (session_id 추출용. 없으면 프로세스 시작 시각 fallback)
        node: 호출 노드 이름 (예: "design", "design_reviewer", "placement_reviewer")
        decision: 결정 종류 (예: "pass", "reject", "fallback", "skipped", "retry")
        reason: 결정 사유 자연어 또는 코드 (예: "REF_CONTEXT_MISSING", "AP-001 violation")
        context: 부가 정보 dict (예: {"violation_count": 3, "iteration": 1})

    그래프 흐름 막지 않음 — 어떤 예외도 logger.warning 후 swallow.
    """
    try:
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "node": node,
            "decision": decision,
            "reason": reason,
            "context": context or {},
        }
        session_id = _resolve_session_id(state if isinstance(state, dict) else {})
        path = _resolve_dump_path(session_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[reason_dump] {node}/{decision} dump 실패 — skip: {e}")
