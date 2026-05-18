package com.landup.job;

import com.landup.file.BrandManual;
import com.landup.file.BrandManualService;
import com.landup.file.FloorArchive;
import com.landup.file.FloorArchiveService;
import com.landup.floor.FloorDetectionService;
import com.landup.placement.PlacementResultService;
import com.landup.project.UserProjectService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Python worker → Spring 내부 콜백 — 기존 JobInternalController 대체.
 *
 * 주의: 내부 전용. Docker 네트워크 내부(worker → backend-java)에서만 호출.
 *      CloudFront 에서 /internal/* 외부 노출 차단 필요.
 *
 * 신 스키마 변환:
 *   payload key   : pdf_file_id → pdf_id → floor_archive_id (2026-04-27), brand_analysis_id → brand_manual_id, pdf_page_id → page_number
 *   progress      : Map 단일 → progress_stage + progress_pct + progress_message
 *   signature     : @RequestBody Map → InternalJobUpdate record
 *   DB 저장 호출  : PlacementDbService 분해본(5개 Service) 중 해당 Service 로 위임
 *     - detect done  → FloorArchiveService.applyDetectResult (구 PdfService)
 *     - brand done   → BrandManualService.applyBrandResult
 *     - space_data   → FloorDetectionService.applySpaceDataResult
 *     - place done   → PlacementResultService.applyPlaceResult (placement_result 자동 생성)
 */
@Slf4j
@RestController
@RequestMapping("/internal")
@RequiredArgsConstructor
public class JobInternalController {

    private final JobService jobService;
    private final FloorArchiveService floorArchiveService;
    private final BrandManualService brandManualService;
    private final FloorDetectionService floorDetectionService;
    private final PlacementResultService placementResultService;
    private final UserProjectService projectService;

    /**
     * worker 전용 floor_detection 조회 — JWT 인증 없이 호출 가능.
     * handle_place 가 space_data 재조회 시 사용. SecurityConfig 에서 /internal/** permitAll.
     * (Docker 내부 네트워크 전용. 외부 노출 차단 필수 — CloudFront/WAF 설정)
     */
    @GetMapping("/floor-detections/{id}")
    public Map<String, Object> getFloorDetectionInternal(@PathVariable Long id) {
        return Map.of("result", floorDetectionService.getAsSpaceData(id));
    }

    /**
     * worker 전용 이전 배치 오브젝트 조회 — 재배치 시 locked_objects 자동 주입용.
     * user_id 소유자 검증 포함. 이전 placement_result 없으면 objects=[] 반환.
     */
    @GetMapping("/projects/{id}/layout-objects")
    public Map<String, Object> getLayoutObjectsInternal(
            @PathVariable Long id,
            @RequestParam Long user_id) {
        List<Map<String, Object>> objects = projectService.loadLatestLayoutObjectsForInternal(id, user_id);
        log.info("[internal] layout-objects: projectId={} userId={} count={}", id, user_id, objects.size());
        return Map.of("objects", objects);
    }

    @PostMapping("/job-update")
    public Map<String, Object> jobUpdate(@RequestBody InternalJobUpdate req) {
        log.info("[internal] job-update: id={}, status={}, stage={}, pct={}",
                req.job_id(), req.status(), req.progress_stage(), req.progress_pct());

        Job.JobState newState = req.status() != null ? Job.JobState.valueOf(req.status()) : null;
        Long resultProjectId = req.project_id();

        // 1) done 시 job_type 별 결과 저장 + user_projects 연결
        if (newState == Job.JobState.done && req.result() != null) {
            Job job = jobService.getJobUnsafe(req.job_id());
            // 이미 cancelled 된 job 이 뒤늦게 done 콜백을 보내는 경우 무시 (레이스 컨디션 방어)
            if (job.getStatus() == Job.JobState.cancelled) {
                log.info("[job-update] done 무시 — 이미 cancelled jobId={}", req.job_id());
                return Map.of("ok", true, "skipped", true);
            }
            switch (job.getJobType()) {
                case detect -> handleDetectDone(req);
                case brand -> handleBrandDone(req);
                case space_data -> handleSpaceDataDone(req);
                case place -> handlePlaceDone(req);
                case export -> log.info("[internal] export done — Phase B 에서 처리");
            }
        }

        // 1-b) cancelled 시 project 에 error 마킹
        if (newState == Job.JobState.cancelled && req.project_id() != null) {
            projectService.markError(req.project_id());
            log.info("[job-update] cancelled — project markError jobId={} projectId={}", req.job_id(), req.project_id());
        }

        // 2) error 시 project 에 error 마킹 (brand 실패 / layer_select_needed 는 치명적 아님 — skip)
        if (newState == Job.JobState.error && req.project_id() != null) {
            Job failedJob = jobService.getJobUnsafe(req.job_id());
            boolean isLayerSelect = req.error_message() != null && req.error_message().startsWith("LAYER_SELECT:");
            if (failedJob.getJobType() != Job.JobType.brand && !isLayerSelect) {
                projectService.markError(req.project_id());
                log.info("[job-update] user_project markError jobId={} projectId={} type={}",
                        req.job_id(), req.project_id(), failedJob.getJobType());
            } else {
                log.info("[job-update] 에러 마킹 생략 jobId={} (brand={}, layerSelect={})",
                        req.job_id(), failedJob.getJobType() == Job.JobType.brand, isLayerSelect);
            }
        }

        // 3) Job 상태 업데이트 (progress 3필드)
        if (newState != null) {
            Job updated = jobService.updateStatus(
                    req.job_id(),
                    newState,
                    req.progress_stage(),
                    req.progress_pct(),
                    req.progress_message(),
                    resultProjectId,
                    req.error_message());
            return Map.of("ok", true, "job_id", updated.getId(), "status", updated.getStatus().name());
        } else {
            // status 없이 progress 만 업데이트하는 케이스
            jobService.updateProgress(req.job_id(), req.progress_stage(), req.progress_pct(), req.progress_message());
            return Map.of("ok", true, "job_id", req.job_id());
        }
    }

    // ══════════════ 단계별 핸들러 ══════════════

    private void handleDetectDone(InternalJobUpdate req) {
        if (req.floor_archive_id() == null) {
            log.warn("[job-update] detect done 이지만 floor_archive_id 없음 jobId={}", req.job_id());
            return;
        }
        FloorArchive archive = floorArchiveService.applyDetectResult(req.floor_archive_id(), req.result());
        log.info("[job-update] floor_archive UPDATE jobId={} floorArchiveId={} pageCount={}",
                req.job_id(), archive.getId(), archive.getPageCount());
        if (req.project_id() != null) {
            projectService.attachFloorArchive(req.project_id(), archive.getId());
        }
    }

    private void handleBrandDone(InternalJobUpdate req) {
        if (req.brand_manual_id() == null) {
            log.warn("[job-update] brand done 이지만 brand_manual_id 없음 jobId={}", req.job_id());
            return;
        }
        brandManualService.applyBrandResult(
                req.brand_manual_id(),
                BrandManual.ManualStatus.done,
                req.result());
        log.info("[job-update] brand_manual UPDATE jobId={} brandManualId={}",
                req.job_id(), req.brand_manual_id());
        if (req.project_id() != null) {
            projectService.attachBrandManual(req.project_id(), req.brand_manual_id());
        }
    }

    private void handleSpaceDataDone(InternalJobUpdate req) {
        // FK 복원: worker 가 floor_archive_id/brand_manual_id 누락해도 project_id 로 user_projects 에서 복원.
        // 프론트 state 유실·sessionStorage 초기화 등 경로 문제에 대한 서버 측 방어.
        Long floorArchiveId = req.floor_archive_id() != null ? req.floor_archive_id() : projectService.resolveFloorArchiveId(req.project_id());
        Long brandManualId = req.brand_manual_id() != null ? req.brand_manual_id()
                : projectService.resolveBrandManualId(req.project_id());
        if (floorArchiveId == null) {
            log.warn("[job-update] space_data done 이지만 floor_archive_id 복원 실패 jobId={} projectId={}",
                    req.job_id(), req.project_id());
            if (req.project_id() != null) {
                projectService.markError(req.project_id());
            }
            return;
        }

        Map<String, Object> request = new HashMap<>();
        request.put("floor_archive_id", floorArchiveId);
        request.put("page_number", req.page_number() != null ? req.page_number() : 1);
        request.put("brand_manual_id", brandManualId);

        Long floorId = floorDetectionService.applySpaceDataResult(request, req.result());
        log.info("[job-update] floor_detection INSERT jobId={} floorDetectionId={}", req.job_id(), floorId);
        if (req.project_id() != null && floorId != null) {
            projectService.attachFloorDetection(req.project_id(), floorId);
        }
    }

    private void handlePlaceDone(InternalJobUpdate req) {
        // FK 복원: worker 가 floor_detection_id 누락해도 project_id 로 복원 시도.
        Long floorDetectionId = req.floor_detection_id() != null
                ? req.floor_detection_id()
                : projectService.resolveFloorDetectionId(req.project_id());
        if (floorDetectionId == null) {
            log.warn("[job-update] place done 이지만 floor_detection_id 복원 실패 jobId={}", req.job_id());
            // silent return 대신 project 를 error 로 마킹 (데이터 무결성 — placement_result 미생성)
            if (req.project_id() != null) {
                projectService.markError(req.project_id());
            }
            return;
        }
        Long placementResultId = placementResultService.applyPlaceResult(
                floorDetectionId,
                req.result());
        log.info("[job-update] placement_result INSERT jobId={} placementResultId={}",
                req.job_id(), placementResultId);

        if (req.project_id() != null) {
            projectService.attachPlacementResult(req.project_id(), placementResultId);
            projectService.markDone(req.project_id());
            log.info("[job-update] user_project markDone jobId={} projectId={}",
                    req.job_id(), req.project_id());
        }
    }
}
