/**
 * UserProject 관련 타입 — 사용자 작업물 상위 묶음
 *
 * 백엔드 `backend/python/app/schemas/project.py`와 구조 동기화 (수동).
 * 변경 시 양쪽 동시 수정.
 */
import type { SpaceData, LayoutObject, BrandExtraction, AutoDetected } from './floor';

// ── 리터럴 타입 ─────────────────────────────────────────

/** 프로젝트 전체 상태 (개별 job 상태와 별개) */
export type ProjectState = 'processing' | 'done' | 'error';

/** 프로젝트 진행 단계 (백엔드에서 DB 상태로 계산) */
export type ProjectStage = 'init' | 'detecting' | 'space_ready' | 'place_ready' | 'done' | 'error';

// ── 프로젝트 목록용 (가벼움) ──────────────────────────

/**
 * GET /me/projects 응답의 배열 아이템.
 * MyPage 내이력 탭 리스트 표시용. 무거운 JSON 제외.
 */
export interface UserProjectListItem {
  id: number;
  user_id: number;
  name: string | null;              // 사용자 지정 이름 — 예: "강남점 v1"
  status: ProjectState;
  created_at: string;               // ISO 8601
  updated_at: string | null;

  // 단계 판별용 FK (null이면 해당 단계 아직 도달 안 함)
  // 2026-04-27 rename: pdf_id → floor_archive_id (pdf 테이블 → floor_archive 박물관)
  floor_archive_id: number | null;
  brand_manual_id: number | null;
  floor_detection_id: number | null;
  has_layout: boolean;              // placement_objects 존재 여부 — "완료" 단계 판정
  stage: ProjectStage;              // 백엔드 계산 단계 — MyPage 배지 + handleOpen 분기

  // 진행중 프로젝트 복원 시 NewProjectPage에 표시
  original_filename: string | null;
}

export interface UserProjectList {
  projects: UserProjectListItem[];
}

// ── 프로젝트 상세 (무거움) ───────────────────────────

/**
 * GET /projects/{id} 응답.
 * ResultPage가 3D 뷰어를 그리려면 필요한 모든 데이터 포함.
 */
export interface UserProjectDetail {
  id: number;
  user_id: number;
  name: string | null;
  status: ProjectState;

  // 연결된 하위 결과 ID들 (FK)
  // 2026-04-27 rename: pdf_id → floor_archive_id
  floor_archive_id: number | null;
  brand_manual_id: number | null;
  floor_detection_id: number | null;
  placement_result_id: number | null;  // 최신 배치 결과 PK — GLB 다운로드/뷰 엔드포인트 호출용

  // 실제 렌더링 데이터
  auto_detected: AutoDetected | null;   // detect 결과 (FloorPage 마킹·공간 확인용)
  space_data: SpaceData | null;          // space_data 결과 (ResultPage 렌더)
  layout_objects: LayoutObject[] | null; // place 결과
  brand_data: BrandExtraction | null;

  created_at: string;
  updated_at: string | null;
}

// ── 프로젝트 이름 변경 요청 ──────────────────────────

/**
 * PATCH /projects/{id} — "저장하기" 버튼 누르고 이름 입력할 때.
 */
export interface UserProjectRename {
  name: string;
}
