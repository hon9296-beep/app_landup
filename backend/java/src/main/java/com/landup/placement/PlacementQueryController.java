package com.landup.placement;

import com.landup.common.ApiException;
import com.landup.project.UserProjectRepository;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 배치 이력/상세 조회 + rerun — 기존 PlacementQueryController 대체.
 *
 * 엔드포인트 불변:
 *   GET  /api/placements/{floorDetectionId}
 *   GET  /api/placements/history?userId=
 *   POST /api/placements/{floorDetectionId}/rerun
 */
@RestController
@RequestMapping("/placements")
@RequiredArgsConstructor
public class PlacementQueryController {

    private final PlacementQueryService queryService;
    private final PlacementResultService resultService;
    private final PlacementObjectService objectService;
    private final PlacementResultRepository resultRepo;
    private final UserProjectRepository projectRepo;

    @GetMapping("/{floorDetectionId}")
    public Map<String, Object> getByFloor(@PathVariable Long floorDetectionId) {
        return queryService.getLatestByFloor(floorDetectionId);
    }

    @GetMapping("/history")
    public Map<String, Object> history(@AuthenticationPrincipal User user) {
        return queryService.getHistoryByUser(user.getId());
    }

    @PostMapping("/{floorDetectionId}/rerun")
    public Map<String, Object> rerun(@PathVariable Long floorDetectionId,
                                     @AuthenticationPrincipal User user,
                                     @RequestBody Map<String, Object> overrides) {
        return queryService.rerun(floorDetectionId, overrides, user);
    }

    /** 배치 결과 상세 (오브젝트 + 검증 포함). */
    @GetMapping("/results/{placementResultId}")
    public Map<String, Object> resultDetail(@PathVariable Long placementResultId) {
        return resultService.getFullDetail(placementResultId);
    }

    /** 개별 오브젝트 편집(이동/회전/삭제). */
    @PatchMapping("/objects/{objectId}")
    public PlacementObject updateObject(@PathVariable Long objectId,
                                        @RequestBody PlacementObject body) {
        return objectService.update(objectId, body);
    }

    @DeleteMapping("/objects/{objectId}")
    public Map<String, Object> deleteObject(@PathVariable Long objectId) {
        objectService.delete(objectId);
        return Map.of("deleted", true, "id", objectId);
    }

    /** 프로젝트별 구조화 리포트 조회. report_json 없으면 404. */
    @GetMapping("/projects/{projectId}/report")
    public Map<String, Object> getProjectReport(@PathVariable Long projectId,
                                                @AuthenticationPrincipal User user) {
        var project = projectRepo.findById(projectId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "project not found: " + projectId));

        Long prId = project.getPlacementResultId();
        if (prId == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "no placement result for project: " + projectId);
        }

        PlacementResult pr = resultRepo.findById(prId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "placement result not found: " + prId));

        String reportJson = pr.getReportJson();
        if (reportJson == null || reportJson.isBlank()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "report not available for project: " + projectId);
        }

        return Map.of("report_json", reportJson);
    }
}
