/**
 * useJob — 비동기 작업 상태 폴링 훅
 *
 * POST /api/detect 등 호출 후 받은 job_id로 이 훅 호출.
 * **동적 폴링 (2026-04-20)**: progress.pct에 따라 interval 조정 — 초반 5s / 중반 3s / 완료 임박 1s.
 * status === 'done' | 'error' 되면 자동 중지 + 콜백 호출.
 *
 * 사용 예:
 *   const { job, stop } = useJob(jobId, {
 *     onDone: (job) => { ... resultProjectId로 페이지 이동 ... },
 *     onError: (job) => toast(job.error_message),
 *   });
 */
import { useEffect, useRef, useState } from 'react';
import { getJob } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import type { Job } from '../types/job';

// 동적 polling interval (ms) — progress.pct 기반
const POLL_INIT_MS = 5000;   // pct < 30 (초반)
const POLL_MID_MS = 3000;    // 30 ≤ pct < 70 (중반)
const POLL_NEAR_MS = 1000;   // pct ≥ 70 (완료 임박)
const POLL_RETRY_MS = 3000;  // 네트워크 오류 시 재시도
const POLL_MAX_WAIT_MS = 30 * 60 * 1000;  // 30분 — worker 크래시·stale job 방어 최대 대기

/** 동적 polling interval — progress.pct 기반. 페이지별 inline pollJob에서도 재사용 가능. */
export function computePollInterval(pct?: number | null): number {
  if (pct == null) return POLL_INIT_MS;
  if (pct >= 70) return POLL_NEAR_MS;
  if (pct >= 30) return POLL_MID_MS;
  return POLL_INIT_MS;
}

interface UseJobOptions {
  onDone?: (job: Job) => void;
  onError?: (job: Job) => void;
  /** running 시 변화 알림 (progress 업데이트 등) */
  onProgress?: (job: Job) => void;
}

export function useJob(jobId: number | null, opts: UseJobOptions = {}) {
  const [job, setJob] = useState<Job | null>(null);
  const [polling, setPolling] = useState(false);
  const { currentUser } = useAuth();
  const timerRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);

  // 최신 콜백 참조 (deps 변화로 interval 재생성 방지)
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const stop = () => {
    stoppedRef.current = true;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setPolling(false);
  };

  useEffect(() => {
    // jobId 가드: 0 / NaN / 비정수 / null 거름 (TR_D 4-27 [500_jobs_입력검증부재] 프론트 잔여 fix).
    // 백엔드는 4-28 GlobalExceptionHandler 로 400 정상 반환하지만, 호출 자체를 막아 노이즈 ↓.
    if (!jobId || !Number.isFinite(Number(jobId)) || jobId <= 0 || !currentUser) {
      stop();
      return;
    }

    stoppedRef.current = false;
    setPolling(true);
    const startedAt = Date.now();

    const schedule = (delayMs: number) => {
      if (stoppedRef.current) return;
      timerRef.current = window.setTimeout(() => void tick(), delayMs);
    };

    const tick = async () => {
      if (stoppedRef.current) return;
      // MAX_WAIT 초과 — worker 크래시·stale job 방어
      if (Date.now() - startedAt > POLL_MAX_WAIT_MS) {
        console.warn(`[useJob] timeout (${POLL_MAX_WAIT_MS}ms) job_id=${jobId}`);
        stop();
        optsRef.current.onError?.({
          id: jobId,
          status: 'error',
          error_message: '작업이 30분 이상 완료되지 않아 중단했습니다. 다시 시도해 주세요.',
        } as unknown as Job);
        return;
      }
      try {
        const next = await getJob(jobId);
        if (stoppedRef.current) return;
        setJob(next);

        if (next.status === 'done') {
          stop();
          optsRef.current.onDone?.(next);
          return;
        }
        if (next.status === 'error') {
          stop();
          optsRef.current.onError?.(next);
          return;
        }
        optsRef.current.onProgress?.(next);
        // 다음 폴링 — progress_pct 기반 동적 interval
        schedule(computePollInterval(next.progress_pct ?? undefined));
      } catch (e) {
        // 네트워크 일시 오류는 고정 간격으로 재시도
        console.warn('[useJob] 폴링 실패:', e);
        schedule(POLL_RETRY_MS);
      }
    };

    // 즉시 1회 호출 (이후는 tick이 스스로 schedule)
    void tick();

    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, currentUser?.id]);

  return { job, polling, stop };
}
