"""
Job 관련 Pydantic 스키마 — 비동기 백그라운드 작업 상태 관리

DB `jobs` 테이블과 1:1 매핑.
프론트의 `frontend/src/types/job.ts`와 구조 동기화 (수동).
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


# ── 리터럴 타입 ─────────────────────────────────────────

JobType = Literal["detect", "brand", "space_data", "place", "export"]
"""작업 종류 — 도면 분석 / 브랜드 매뉴얼 분석 / 공간 분석 / 배치 생성 / 내보내기"""

JobState = Literal["pending", "running", "done", "error"]
"""작업 상태 — 대기 / 실행 중 / 완료 / 실패"""


# ── 진행 상황 ─────────────────────────────────────────

class JobProgress(BaseModel):
    """
    작업 진행 상황. `jobs.progress` JSON 칼럼에 저장.

    백엔드 워커가 단계별로 업데이트.
    프론트가 진행 바 + 메시지 렌더링에 사용.
    """
    stage: str
    """현재 단계 — 예: "vision", "dead_zone", "design" """

    pct: int
    """진행률 0~100"""

    message: Optional[str] = None
    """사용자에게 보여줄 한 줄 설명 — 예: "Dead Zone 계산 중..." """


# ── 작업 생성 요청 ─────────────────────────────────────

class JobCreate(BaseModel):
    """
    작업 큐 등록 시 내부 사용. 프론트에서 직접 받지는 않음.
    POST /detect, /place 등에서 파이프라인 호출 전 jobs INSERT용.
    """
    user_id: int
    job_type: JobType


# ── 작업 상태 응답 ─────────────────────────────────────

class JobStatus(BaseModel):
    """
    GET /jobs/{id} 응답 형식.

    DB `jobs` 테이블 row → 그대로 직렬화.
    프론트 useJob 훅이 폴링으로 이걸 받음.
    """
    id: int
    """job_id (자동증가 INT)"""

    user_id: int
    """작업 소유자. 권한 체크에 사용"""

    job_type: JobType

    status: JobState
    """프론트가 분기에 사용하는 핵심 필드"""

    progress: Optional[JobProgress] = None
    """실행 중일 때만 있음. pending/done/error 시 None 가능"""

    result_project_id: Optional[int] = None
    """status == 'done'일 때 user_projects.id 연결"""

    error_message: Optional[str] = None
    """status == 'error'일 때 실패 사유"""

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── 작업 생성 응답 ─────────────────────────────────────

class JobEnqueued(BaseModel):
    """
    POST /detect, POST /place 등 비동기 API의 응답.

    작업은 아직 시작 안 됐고, job_id만 발급.
    프론트는 이 id로 GET /jobs/{id} 폴링 시작.
    """
    job_id: int
    status: JobState = "pending"
