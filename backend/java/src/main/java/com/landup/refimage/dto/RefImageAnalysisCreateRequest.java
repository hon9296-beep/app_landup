package com.landup.refimage.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * Python ref_image_analyzer 가 분석 결과 영속 시 호출하는 internal API 의 request DTO.
 *
 * 검증:
 *   - visionAnalysisJson: 필수 (JSON 문자열)
 *   - 나머지 nullable (refImageId / conceptArea / brandCategory / modelVersion)
 */
public record RefImageAnalysisCreateRequest(
        Long refImageId,
        @Size(max = 50) String conceptArea,
        @Size(max = 50) String brandCategory,
        @NotBlank(message = "vision_analysis_json 은 필수") String visionAnalysisJson,
        @Size(max = 50) String modelVersion
) {}
