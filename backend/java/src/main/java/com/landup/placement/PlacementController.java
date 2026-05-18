package com.landup.placement;

import com.landup.file.BrandManualService;
import com.landup.file.FloorArchive;
import com.landup.file.FloorArchiveService;
import com.landup.job.Job;
import com.landup.job.JobPublisher;
import com.landup.job.JobService;
import com.landup.plan.PlanLimitService;
import com.landup.plan.RedeploymentLogService;
import com.landup.project.UserProject;
import com.landup.project.UserProjectService;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;

/**
 * 배치 엔진 프록시 — B안 비동기.
 *
 * 엔드포인트 경로 (실소스 기준 — prefix 없음):
 *   POST /detect        multipart (floor_plan, file_type, user_id)
 *   POST /brand         multipart (brand_manual, user_id, project_id?)
 *   POST /space-data    json (user_id query, body)
 *   POST /place         json (user_id query, body — floor_detection_id 필수)
 *
 * 신 스키마 변환:
 *   - pdf_file_id → pdf_id → floor_archive_id (2026-04-27)
 *   - brand_analysis_id → brand_manual_id
 *   - /place 의 space_data 복원 로직 제거 (신 floor_detections 에 result_json 없음.
 *     Python worker 가 GET /floor-detections/{id} 로 재조회).
 */
@RestController
@RequiredArgsConstructor
public class PlacementController {

    private final FloorArchiveService floorArchiveService;
    private final PlanLimitService planLimitService;
    private final RedeploymentLogService redeploymentLogService;
    private final BrandManualService brandManualService;
    private final JobService jobService;
    private final JobPublisher jobPublisher;
    private final UserProjectService userProjectService;

    // ── /detect — 도면 분석 ────────────────────────────────────────────

    @PostMapping(value = "/detect", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> detect(
            @RequestParam("floor_plan") MultipartFile floorPlan,
            // file_type 지원: pdf (default) / dxf / dwg / image / photo (Phase 1 방 사진 — Python parser_photo 모듈 구현 예정)
            @RequestParam(value = "file_type", defaultValue = "pdf") String fileType,
            @RequestParam(value = "force_layer", required = false) String forceLayer,
            @AuthenticationPrincipal User user
    ) throws IOException {
        Long userId = user.getId();

        // 1. floor_archive 메타 DB 저장 (동기) — 도면 원본 박물관
        FloorArchive saved = floorArchiveService.saveFloorArchive(userId, floorPlan);
        Long floorArchiveId = saved.getId();

        // 2. user_projects stub INSERT
        UserProject stub = userProjectService.createStub(user, floorArchiveId);
        Long projectId = stub.getId();

        // 3. job 생성
        Job job = jobService.createJob(userId, Job.JobType.detect);

        // 4. worker params (신 payload — floor_archive_id, project_id, file_bytes_b64)
        Map<String, Object> params = new HashMap<>();
        params.put("user_id", userId);
        params.put("floor_archive_id", floorArchiveId);
        params.put("project_id", projectId);
        params.put("file_type", fileType);
        params.put("file_bytes_b64", Base64.getEncoder().encodeToString(floorPlan.getBytes()));
        if (forceLayer != null && !forceLayer.isBlank()) {
            params.put("force_layer", forceLayer);
        }

        jobPublisher.publish(job.getId(), Job.JobType.detect, params);

        return Map.of(
                "job_id", job.getId(),
                "status", job.getStatus().name(),
                "floor_archive_id", floorArchiveId,
                "project_id", projectId
        );
    }

    // ── /brand — 브랜드 메뉴얼 추출 ────────────────────────────────────

    @PostMapping(value = "/brand", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> brand(
            @RequestParam("brand_manual") MultipartFile brandManual,
            @AuthenticationPrincipal User user,
            @RequestParam(value = "project_id", required = false) Long projectId
    ) throws IOException {
        Long userId = user.getId();

        // 파일 메타 DB 저장 (동기) — 2026-04-27 정책: 매번 새 row INSERT (sha256 dup 검출 X)
        Long brandManualId = brandManualService.saveBrandManual(userId, brandManual);

        // project 에 즉시 attach
        if (projectId != null) {
            userProjectService.attachBrandManual(projectId, brandManualId);
        }

        Job job = jobService.createJob(userId, Job.JobType.brand);

        Map<String, Object> params = new HashMap<>();
        params.put("user_id", userId);
        params.put("brand_manual_id", brandManualId);
        if (projectId != null) params.put("project_id", projectId);
        params.put("file_bytes_b64", Base64.getEncoder().encodeToString(brandManual.getBytes()));

        jobPublisher.publish(job.getId(), Job.JobType.brand, params);

        return Map.of(
                "job_id", job.getId(),
                "status", job.getStatus().name(),
                "brand_manual_id", brandManualId
        );
    }

    // ── /space-data — 공간 계산 ────────────────────────────────────────

    @PostMapping("/space-data")
    public Map<String, Object> spaceData(
            @RequestBody Map<String, Object> body,
            @AuthenticationPrincipal User user
    ) {
        Long userId = user.getId();

        Job job = jobService.createJob(userId, Job.JobType.space_data);
        Map<String, Object> params = new HashMap<>(body);
        params.put("user_id", userId);

        // 2026-04-29 자동 보강: body 에 project_id 없으면 floor_archive_id 로 역추적해서 채움.
        // 목적: space-data 완료 콜백의 attachFloorDetection 정상 작동 → user_projects.floor_detection_id 채워짐
        //   → 그 후 /place 의 findByFloorDetectionId 자동 보강도 작동 (chain 회복) → ref_image 의 user_project_id 정상화.
        if (params.get("project_id") == null) {
            Long floorArchiveId = toLong(body.get("floor_archive_id"));
            if (floorArchiveId != null) {
                userProjectService.findByFloorArchiveId(floorArchiveId)
                    .ifPresent(p -> params.put("project_id", p.getId()));
            }
        }

        jobPublisher.publish(job.getId(), Job.JobType.space_data, params);

        return Map.of(
                "job_id", job.getId(),
                "status", job.getStatus().name()
        );
    }

    // ── /place — 배치 생성 ────────────────────────────────────────────

    /**
     * 신 스키마: space_data 는 worker 가 GET /floor-detections/{id} 로 재조회.
     * Java 는 floor_detection_id 유효성만 확인하고 params 에 포함해서 큐로 보냄.
     */
    @PostMapping("/place")
    public Map<String, Object> place(
            @RequestBody Map<String, Object> body,
            @AuthenticationPrincipal User user
    ) {
        Long userId = user.getId();

        Long floorDetectionId = toLong(body.get("floor_detection_id"));
        if (floorDetectionId == null) {
            throw new IllegalArgumentException("floor_detection_id is required for place");
        }

        Long projectId = toLong(body.get("project_id"));
        planLimitService.checkRedeployLimit(user, projectId);

        Job job = jobService.createJob(userId, Job.JobType.place);
        redeploymentLogService.record(userId, projectId);

        Map<String, Object> params = new HashMap<>(body);
        params.put("user_id", userId);
        params.put("floor_detection_id", floorDetectionId);

        // 2026-04-29 자동 보강: body 에 project_id 없으면 floor_detection_id 로 역추적해서 채움.
        // 목적: Python ref_image_loader 의 user_project_id 분기 정상화 → ref_image S3 업로드 활성.
        // (frontend 가 매번 project_id 챙겨 보낼 필요 없게 backend 에서 일관 처리)
        if (params.get("project_id") == null) {
            userProjectService.findByFloorDetectionId(floorDetectionId)
                .ifPresent(p -> params.put("project_id", p.getId()));
        }

        jobPublisher.publish(job.getId(), Job.JobType.place, params);

        return Map.of(
                "job_id", job.getId(),
                "status", job.getStatus().name()
        );
    }

    private Long toLong(Object v) {
        if (v == null) return null;
        if (v instanceof Number n) return n.longValue();
        if (v instanceof String s) {
            try { return Long.parseLong(s); } catch (NumberFormatException e) { return null; }
        }
        return null;
    }
}
