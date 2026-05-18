package com.landup.job;

import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

/**
 * Job 수명주기 관리 — 기존 JobService 대체.
 * 변경점:
 *   - progress(JSON 단일) → progressStage/progressPct/progressMessage 3필드
 *   - updateProgress/updateStatus 시그니처 3필드 버전으로 교체
 */
@Service
@RequiredArgsConstructor
public class JobService {

    private static final String CANCEL_KEY_PREFIX = "cancel:";

    private final JobRepository repo;
    private final StringRedisTemplate redis;

    @Transactional
    public Job createJob(Long userId, Job.JobType type) {
        return repo.save(Job.builder()
                .userId(userId)
                .jobType(type)
                .status(Job.JobState.pending)
                .progressPct(0)
                .build());
    }

    public Job getJob(Long jobId, Long userId) {
        Job job = getJobUnsafe(jobId);
        if (!job.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "job access denied");
        }
        return job;
    }

    public Job getJobUnsafe(Long jobId) {
        return repo.findById(jobId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "job not found: " + jobId));
    }

    @Transactional
    public Job updateProgress(Long jobId, String stage, Integer pct, String message) {
        Job job = getJobUnsafe(jobId);
        if (stage != null) job.setProgressStage(stage);
        if (pct != null) job.setProgressPct(pct);
        if (message != null) job.setProgressMessage(message);
        if (job.getStartedAt() == null && job.getStatus() != Job.JobState.pending) {
            job.setStartedAt(LocalDateTime.now());
        }
        return repo.save(job);
    }

    @Transactional
    public Job updateStatus(Long jobId,
                            Job.JobState status,
                            String stage, Integer pct, String message,
                            Long resultProjectId,
                            String errorMessage) {
        Job job = getJobUnsafe(jobId);
        job.setStatus(status);
        if (stage != null) job.setProgressStage(stage);
        if (pct != null) job.setProgressPct(pct);
        if (message != null) job.setProgressMessage(message);
        if (resultProjectId != null) job.setResultProjectId(resultProjectId);
        if (errorMessage != null) job.setErrorMessage(errorMessage);

        if (status == Job.JobState.running && job.getStartedAt() == null) {
            job.setStartedAt(LocalDateTime.now());
        }
        if (status == Job.JobState.done || status == Job.JobState.error || status == Job.JobState.cancelled) {
            job.setCompletedAt(LocalDateTime.now());
        }
        return repo.save(job);
    }

    @Transactional
    public void cancelJob(Long jobId, Long userId) {
        Job job = getJob(jobId, userId);
        Job.JobState s = job.getStatus();
        if (s == Job.JobState.done || s == Job.JobState.error || s == Job.JobState.cancelled) {
            return; // 이미 종료된 작업 — 무시
        }
        // Redis 취소 신호 설정 (TTL 1시간 — worker 가 확인)
        redis.opsForValue().set(CANCEL_KEY_PREFIX + jobId, "1", Duration.ofHours(1));
    }

    public List<Job> listByUser(Long userId) {
        return repo.findAllByUserIdOrderByCreatedAtDesc(userId);
    }
}
