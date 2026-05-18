package com.landup.job;

import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * Job 상태 폴링 Controller — 기존 JobController 대체.
 * 응답 필드명 변경: progress(Map) → progress_stage/progress_pct/progress_message (3필드 flat).
 */
@RestController
@RequestMapping("/jobs")
@RequiredArgsConstructor
public class JobController {

    private final JobService jobService;

    @PostMapping("/{id}/cancel")
    public Map<String, Object> cancelJob(@PathVariable Long id,
                                         @AuthenticationPrincipal User user) {
        jobService.cancelJob(id, user.getId());
        return Map.of("ok", true, "job_id", id);
    }

    @GetMapping("/{id}")
    public Map<String, Object> getJob(@PathVariable Long id,
                                      @AuthenticationPrincipal User user) {
        Job job = jobService.getJob(id, user.getId());
        Map<String, Object> resp = new HashMap<>();
        resp.put("id", job.getId());
        resp.put("user_id", job.getUserId());
        resp.put("job_type", job.getJobType());
        resp.put("status", job.getStatus());
        resp.put("progress_stage", job.getProgressStage());
        resp.put("progress_pct", job.getProgressPct());
        resp.put("progress_message", job.getProgressMessage());
        resp.put("result_project_id", job.getResultProjectId());
        resp.put("error_message", job.getErrorMessage());
        resp.put("created_at", job.getCreatedAt());
        resp.put("started_at", job.getStartedAt());
        resp.put("completed_at", job.getCompletedAt());
        return resp;
    }
}
