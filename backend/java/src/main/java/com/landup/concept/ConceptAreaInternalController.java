package com.landup.concept;

import com.landup.concept.dto.ConceptAreaCreateBatchRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Python 배치 엔진 (placement-engine) 이 호출하는 내부 API (2026-05-01 신설).
 *
 * 외부 사용자 노출 X — /internal/ prefix + Spring Security permitAll (Docker 네트워크 전용).
 *
 * 엔드포인트:
 *   POST /internal/concept-areas/batch — concept_area.py 한 사이클의 영역 일괄 INSERT
 */
@RestController
@RequestMapping("/internal/concept-areas")
@RequiredArgsConstructor
public class ConceptAreaInternalController {

    private final ConceptAreaService service;

    /**
     * batch INSERT.
     *
     * Request: { floorDetectionId: 123, areas: [{name, polygonJson, areaRatio, targetObjectsJson}, ...] }
     * Response: { "welcome": 1, "photo": 2, "experience": 3, ... }  (영역 name → DB id)
     */
    @PostMapping("/batch")
    public Map<String, Long> createBatch(@Valid @RequestBody ConceptAreaCreateBatchRequest req) {
        return service.createBatch(req);
    }
}
