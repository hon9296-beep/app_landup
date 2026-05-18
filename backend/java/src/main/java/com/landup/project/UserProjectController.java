package com.landup.project;

import com.landup.user.User;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * UserProject Controller — 기존 UserProjectController 대체.
 *
 * 경로 (실소스 동일, prefix 없음):
 *   GET    /me/projects
 *   GET    /projects/{id}
 *   PATCH  /projects/{id}
 *   DELETE /projects/{id}
 *
 * 응답 필드명 변경:
 *   pdf_file_id       → pdf_id → floor_archive_id (2026-04-27)
 *   brand_analysis_id → brand_manual_id
 *   placement_result_id 신규
 *
 * stage 값: detecting/space_ready/place_ready/placing/done/error/init
 */
@RestController
@RequiredArgsConstructor
public class UserProjectController {

    private final UserProjectService service;

    @GetMapping("/me/projects")
    public Map<String, Object> listMine(@AuthenticationPrincipal User user) {
        return Map.of("projects", service.summarizeListForUser(user.getId()));
    }

    @GetMapping("/projects/{id}")
    public Map<String, Object> detail(@PathVariable("id") Long projectId,
                                      @AuthenticationPrincipal User user) {
        return service.getProjectDetail(projectId, user.getId());
    }

    @PatchMapping("/projects/{id}")
    public Map<String, Object> rename(@PathVariable("id") Long projectId,
                                       @AuthenticationPrincipal User user,
                                       @Valid @RequestBody RenameProjectRequest body) {
        UserProject p = service.rename(projectId, user.getId(), body.name().trim());
        return Map.of(
                "id", p.getId(),
                "name", p.getName(),
                "status", p.getStatus().name(),
                "floor_archive_id", p.getFloorArchiveId() == null ? 0 : p.getFloorArchiveId(),
                "brand_manual_id", p.getBrandManualId() == null ? 0 : p.getBrandManualId(),
                "floor_detection_id", p.getFloorDetectionId() == null ? 0 : p.getFloorDetectionId(),
                "placement_result_id", p.getPlacementResultId() == null ? 0 : p.getPlacementResultId()
        );
    }

    @DeleteMapping("/projects/{id}")
    public Map<String, Object> delete(@PathVariable("id") Long projectId,
                                       @AuthenticationPrincipal User user) {
        service.delete(projectId, user.getId());
        return Map.of("deleted", true, "id", projectId);
    }
}
