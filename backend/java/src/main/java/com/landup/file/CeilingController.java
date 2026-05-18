package com.landup.file;

import com.landup.placement.PlacementClient;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

/**
 * 단면도 파일에서 천장 높이(ceiling_height_mm) 추출 — Python으로 위임 후 DB 저장.
 */
@RestController
@RequiredArgsConstructor
public class CeilingController {

    private final PlacementClient placementClient;
    private final CrossSectionService crossSectionService;

    @PostMapping("/ceiling-height")
    public Map<String, Object> detectCeilingHeight(
            @RequestParam("cross_section") MultipartFile file,
            @RequestParam(value = "file_type", defaultValue = "pdf") String fileType,
            @AuthenticationPrincipal User user,
            @RequestParam(value = "floor_detection_id", required = false) Long floorDetectionId
    ) {
        Map<String, Object> result = placementClient.ceilingHeight(file, fileType);
        crossSectionService.save(file, fileType, user.getId(), floorDetectionId, result);
        return result;
    }
}
