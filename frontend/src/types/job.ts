/**
 * Job 관련 타입 — 비동기 백그라운드 작업 상태
 *
 * 백엔드 `backend/python/app/schemas/job.py`와 구조 동기화 (수동).
 * 변경 시 양쪽 동시 수정.
 */

// ── 리터럴 타입 ─────────────────────────────────────────

/** 작업 종류 */
export type JobType = 'detect' | 'brand' | 'space_data' | 'place' | 'export';

/** 작업 상태 4단계 */
export type JobState = 'pending' | 'running' | 'done' | 'error';

// ── 작업 상태 응답 ─────────────────────────────────────

/**
 * GET /jobs/{id} 응답 — Java `JobController.getJob` 와 정확히 일치.
 *
 * Job Entity 재설계 (2026-04-20): progress(JSON) → progress_stage/pct/message 3필드 flat.
 * 파생 ID (floor_archive_id, floor_detection_id, project_id 등) 는 응답에 포함되지 않음.
 * 필요 시 user_projects / floor_archive 등 도메인 테이블에서 별도 조회.
 *
 * `Job` 은 동일 타입 alias (import 호환용).
 */
export type Job = JobStatus;
export interface JobStatus {
  id: number;
  user_id: number;
  job_type: JobType;
  status: JobState;
  progress_stage: string | null;
  progress_pct: number | null;
  progress_message: string | null;
  result_project_id: number | null;   // status === 'done'일 때만
  error_message: string | null;       // status === 'error'일 때만
  created_at: string;                 // ISO 8601
  started_at: string | null;
  completed_at: string | null;
}

// ── 작업 생성 응답 ─────────────────────────────────────

/**
 * POST /detect, POST /place 등 비동기 API 응답.
 * 작업은 아직 시작 안 됐고 job_id만 발급됨.
 */
export interface JobEnqueued {
  job_id: number;
  status: JobState;   // 보통 'pending'
}
