package com.landup.concept.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.*;

import java.util.List;

/**
 * Python concept_area.py 한 사이클의 영역 일괄 영속 페이로드.
 * 8개 영역 한 번에 INSERT — N+1 회피.
 */
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ConceptAreaCreateBatchRequest {

    @NotNull(message = "floorDetectionId 필수")
    private Long floorDetectionId;

    @Valid
    @NotEmpty(message = "areas 비어있음 — 최소 1개 영역 필요")
    private List<ConceptAreaCreateRequest> areas;
}
