package com.landup.placement;

import com.landup.common.ApiException;
import com.landup.file.FloorArchive;
import com.landup.file.FloorArchiveRepository;
import com.landup.floor.FloorDetection;
import com.landup.floor.FloorDetectionRepository;
import com.landup.job.Job;
import com.landup.job.JobPublisher;
import com.landup.job.JobService;
import com.landup.plan.PlanLimitService;
import com.landup.plan.RedeploymentLogService;
import com.landup.project.UserProjectRepository;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 배치 이력/재배치(rerun) 질의 서비스 — 기존 PlacementQueryService 대체.
 *
 * 변경점:
 *   - placement_objects 조회 키: floor_detection_id → placement_result_id
 *   - rerun 은 placement_result 재생성 (기존 유지하되 최신 1건만 live)
 */
@Service
@RequiredArgsConstructor
public class PlacementQueryService {

    private final PlacementResultRepository resultRepo;
    private final PlacementObjectRepository objectRepo;
    private final FloorDetectionRepository floorRepo;
    private final FloorArchiveRepository floorArchiveRepo;
    private final UserProjectRepository projectRepo;
    private final JobService jobService;
    private final PlanLimitService planLimitService;
    private final RedeploymentLogService redeploymentLogService;
    private final JobPublisher jobPublisher;

    public Map<String, Object> getLatestByFloor(Long floorDetectionId) {
        PlacementResult latest = resultRepo.findAllByFloorDetectionIdOrderByCreatedAtDesc(floorDetectionId).stream()
                .findFirst()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND,
                        "no placement_result for floor_detection: " + floorDetectionId));
        Map<String, Object> out = new HashMap<>();
        out.put("placement_result_id", latest.getId());
        out.put("floor_detection_id", latest.getFloorDetectionId());
        out.put("status", latest.getStatus());
        out.put("created_at", latest.getCreatedAt());
        out.put("objects", objectRepo.findAllByPlacementResultId(latest.getId()));
        return out;
    }

    public Map<String, Object> getHistoryByUser(Long userId) {
        List<Map<String, Object>> rows = new ArrayList<>();
        projectRepo.findAllByUserIdOrderByCreatedAtDesc(userId).forEach(p -> {
            if (p.getFloorDetectionId() == null) return;
            FloorDetection fd = floorRepo.findById(p.getFloorDetectionId()).orElse(null);
            if (fd == null) return;
            List<PlacementResult> results = resultRepo.findAllByFloorDetectionIdOrderByCreatedAtDesc(fd.getId());
            if (results.isEmpty()) return;
            PlacementResult r = results.get(0);
            Map<String, Object> m = new HashMap<>();
            m.put("floor_detection_id", fd.getId());
            m.put("placement_result_id", r.getId());
            m.put("object_count", r.getPlacedCount());
            m.put("status", r.getStatus());
            m.put("created_at", r.getCreatedAt());
            if (p.getFloorArchiveId() != null) {
                FloorArchive archive = floorArchiveRepo.findById(p.getFloorArchiveId()).orElse(null);
                if (archive != null) m.put("floor_archive_filename", archive.getOriginalFilename());
            }
            rows.add(m);
        });
        return Map.of("placements", rows);
    }

    /** rerun — 기존 place 요청을 density/brand overrides 로 재호출. */
    public Map<String, Object> rerun(Long floorDetectionId, Map<String, Object> overrides, User user) {
        Long projectId = projectRepo.findByFloorDetectionId(floorDetectionId)
                .map(p -> p.getId()).orElse(null);
        planLimitService.checkRedeployLimit(user, projectId);

        Job job = jobService.createJob(user.getId(), Job.JobType.place);
        Map<String, Object> payload = new HashMap<>();
        payload.put("floor_detection_id", floorDetectionId);
        payload.putAll(overrides);
        jobPublisher.publish(job.getId(), Job.JobType.place, payload);

        redeploymentLogService.record(user.getId(), projectId);
        return Map.of("job_id", job.getId(), "status", job.getStatus());
    }
}
