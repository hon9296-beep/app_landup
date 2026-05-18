package com.landup.concept.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.*;

/**
 * Python concept_area.py 가 batch 호출 시 각 영역의 페이로드.
 */
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ConceptAreaCreateRequest {

    /** 영문 키 (welcome / photo / experience / screening / retail / checkout / hybrid / lounge). */
    @NotBlank(message = "name 필수")
    @Size(max = 50, message = "name 50자 이내")
    private String name;

    /** Shapely Polygon → [[x,y],...] JSON 직렬화 결과. */
    private String polygonJson;

    /** 전체 usable_poly 대비 비율 (0.0 ~ 1.0). */
    private Float areaRatio;

    /** AREA_TYPES.target_objects JSON list (예: ["counter"]). */
    private String targetObjectsJson;
}
