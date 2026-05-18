"""
UserProject 관련 Pydantic 스키마 — 사용자 작업물 상위 묶음

DB `user_projects` 테이블과 1:1 매핑.
하나의 작업(도면 업로드 + 브랜드 분석 + 공간 분석 + 배치)을 한 row로 묶음.
프론트의 `frontend/src/types/project.ts`와 구조 동기화 (수동).
"""
from datetime import datetime
from typing import Literal, Optional, Any

from pydantic import BaseModel


# ── 리터럴 타입 ─────────────────────────────────────────

ProjectState = Literal["processing", "done", "error"]
"""프로젝트 전체 상태. 개별 job 상태와 별개로 프로젝트 레벨"""


# ── 프로젝트 목록용 (가벼움) ──────────────────────────

class UserProjectListItem(BaseModel):
    """
    GET /me/projects 응답의 배열 아이템.

    MyPage 내이력 탭 리스트 표시용. 무거운 JSON(space_data, layout_objects) 제외.
    """
    id: int
    user_id: int
    name: Optional[str] = None
    """사용자 지정 이름. 예: "강남점 v1" """

    status: ProjectState
    created_at: datetime
    updated_at: Optional[datetime] = None


class UserProjectList(BaseModel):
    """GET /me/projects 전체 응답"""
    projects: list[UserProjectListItem]


# ── 프로젝트 상세 (무거움) ───────────────────────────

class UserProjectDetail(BaseModel):
    """
    GET /projects/{id} 응답.

    ResultPage가 3D 뷰어를 그리려면 필요한 모든 데이터 포함.
    """
    id: int
    user_id: int
    name: Optional[str] = None
    status: ProjectState

    # 연결된 하위 결과 ID들 (FK)
    # 2026-04-27 rename: pdf_id → floor_archive_id
    floor_archive_id: Optional[int] = None
    brand_manual_id: Optional[int] = None
    floor_detection_id: Optional[int] = None

    # 실제 렌더링 데이터 (JOIN 해서 가져옴)
    space_data: Optional[dict[str, Any]] = None
    """공간 분석 결과 — floor, entrance, reference_points, dead_zones, zone_map 등"""

    layout_objects: Optional[list[dict[str, Any]]] = None
    """배치 결과 — 각 오브젝트의 좌표/타입/회전"""

    brand_data: Optional[dict[str, Any]] = None
    """브랜드 매뉴얼 분석 결과"""

    created_at: datetime
    updated_at: Optional[datetime] = None


# ── 프로젝트 생성/수정 ────────────────────────────────

class UserProjectCreate(BaseModel):
    """
    워커가 작업 완료 시 user_projects INSERT에 사용.
    프론트에서 직접 받지 않음. 서버 내부 사용.
    """
    user_id: int
    name: Optional[str] = None
    floor_archive_id: Optional[int] = None
    brand_manual_id: Optional[int] = None
    floor_detection_id: Optional[int] = None
    status: ProjectState = "processing"


class UserProjectRename(BaseModel):
    """
    PATCH /projects/{id} — 사용자가 "저장하기" 누르고 이름 변경할 때.
    """
    name: str
